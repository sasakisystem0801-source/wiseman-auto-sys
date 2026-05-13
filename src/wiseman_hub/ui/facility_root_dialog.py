"""事業所ルートフォルダ管理ダイアログ（W4）。

PR #124 で実装した単一事業所結合機能（merge_facility）の上層に位置し、
ルートフォルダ配下の複数事業所を **チェックボックス UI で一括 / 選択処理** できる。

アーキテクチャ:
    - ``FacilityRootViewModel``: pure Python の状態管理（テスト容易性のため分離）
    - ``FacilityRootManagerDialog``: Tk widget 部分の薄いラッパー（ViewModel に依存）

UI ロジックの中心は ViewModel に集約し、Tk 部分は表示と入力の bridge のみ。
これにより macOS でも実機に依存せず大半をテストできる。

スレッド境界:
    - スキャン / 設定保存は main thread で同期実行
    - run_bulk_merge は worker thread（既存 launcher.py の root.after パターン踏襲）
    - progress_callback は worker から root.after(0, ...) 経由で main thread に bridge
"""

from __future__ import annotations

import contextlib
import logging
import threading
import tkinter as tk
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Final

from wiseman_hub.config import AppConfig, save_config
from wiseman_hub.pdf.facility_bulk_runner import (
    BulkExecutionItem,
    BulkExecutionStatus,
    run_bulk_merge,
)
from wiseman_hub.pdf.facility_scanner import (
    FacilityCandidate,
    FacilityStatus,
    scan_facility_root,
)
from wiseman_hub.ui.common import (
    MessageBoxLike,
    assert_main_thread,
    default_messagebox,
    install_tk_exception_guard,
)
from wiseman_hub.utils.os_open import open_with_default_app

logger = logging.getLogger(__name__)


# UI 文言定数（介護現場向けの平易な日本語、PII を含まない）
_LABEL_PENDING: Final[str] = "実行待ち"
_LABEL_A_MISSING: Final[str] = "⚠ 事業所直下にPDFがありません"
_LABEL_A_MULTIPLE: Final[str] = "⚠ PDFが複数あります → 1つ選択してください"
_LABEL_RUNNING: Final[str] = "処理中…"
_LABEL_PARTIAL: Final[str] = "⚠ 結合対象なし（除外のみ）"
_LABEL_CANCELLED: Final[str] = "— 停止により未処理"


# =============================================================================
# ViewModel（pure Python、テスト容易）
# =============================================================================


@dataclass
class FacilityRow:
    """UI の 1 行分の状態。

    candidate（scanner 由来、frozen）に加えて、UI 操作で変化する状態を保持する。
    """

    candidate: FacilityCandidate
    selected: bool = False
    selected_a_pdf: Path | None = None  # A_MULTIPLE 解決済の選択 path
    execution_status: BulkExecutionStatus | None = None  # 実行後ステータス
    error_message: str | None = None
    success_count: int = 0  # SUCCESS 時の結合人数（display_status の "完了 N名" 用）

    @property
    def resolved_a_pdf(self) -> Path | None:
        """実行用に解決済 A.pdf path を返す。未解決なら None。"""
        if self.candidate.status == FacilityStatus.PENDING:
            return self.candidate.a_pdf_path
        if self.candidate.status == FacilityStatus.A_MULTIPLE:
            return self.selected_a_pdf
        return None  # A_MISSING

    @property
    def is_executable(self) -> bool:
        """selected かつ A.pdf 解決済なら実行可能。"""
        return self.selected and self.resolved_a_pdf is not None

    @property
    def is_unrunnable(self) -> bool:
        """A_MISSING または未解決 A_MULTIPLE → 実行不可（サマリ集計用）。"""
        if self.candidate.status == FacilityStatus.A_MISSING:
            return True
        return (
            self.candidate.status == FacilityStatus.A_MULTIPLE
            and self.selected_a_pdf is None
        )

    @property
    def can_open_output_pdf(self) -> bool:
        """「結合PDFを開く」ボタンを活性化すべきか。

        - 既存出力ファイルがある（スキャン時点）
        - または実行 SUCCESS で新規生成された
        """
        if self.candidate.has_existing_output:
            return True
        return self.execution_status == BulkExecutionStatus.SUCCESS

    @property
    def display_status(self) -> str:
        """UI 表示用の文言（介護現場向け平易な日本語）。"""
        # 実行中 / 実行後の状態を最優先（scan 由来 status を上書き）
        if self.execution_status is not None:
            return self._format_execution_status()

        # scan 由来の status
        if self.candidate.status == FacilityStatus.PENDING:
            return _LABEL_PENDING
        if self.candidate.status == FacilityStatus.A_MISSING:
            return _LABEL_A_MISSING
        if self.candidate.status == FacilityStatus.A_MULTIPLE:
            if self.selected_a_pdf is not None:
                # 解決済なら通常の PENDING 扱い
                return _LABEL_PENDING
            return _LABEL_A_MULTIPLE
        return ""

    def _format_execution_status(self) -> str:
        status = self.execution_status
        if status == BulkExecutionStatus.RUNNING:
            return _LABEL_RUNNING
        if status == BulkExecutionStatus.SUCCESS:
            return f"✓ 完了（{self.success_count}名結合）"
        if status == BulkExecutionStatus.PARTIAL:
            return _LABEL_PARTIAL
        if status == BulkExecutionStatus.FAILED_LOCKED:
            return f"⚠ {self.error_message or '結合PDFがロックされています'}"
        if status == BulkExecutionStatus.FAILED:
            return f"⚠ エラー（{self.error_message or '不明'}）"
        if status == BulkExecutionStatus.CANCELLED_SKIPPED:
            return _LABEL_CANCELLED
        return ""


@dataclass(frozen=True)
class FacilitySummary:
    """実行前サマリ（「選択中: N / 実行不可: N / 上書き: N」表示用）。"""

    selected_count: int
    unrunnable_count: int
    overwrite_count: int


@dataclass
class FacilityRootViewModel:
    """事業所ルートフォルダ管理画面の状態。

    Dialog から DI される単一の状態オブジェクト。Tk 非依存で完結する。
    """

    config: AppConfig | None = None
    root_dir: Path | None = None
    rows: list[FacilityRow] = field(default_factory=list)

    def set_root_and_rows(
        self, root: Path, candidates: Iterable[FacilityCandidate]
    ) -> None:
        """ルートとスキャン結果を反映。AppConfig も更新（呼び出し元で永続化）。"""
        self.root_dir = root
        self.rows = [
            FacilityRow(
                candidate=c,
                # PENDING はデフォルト ON（一括処理が主目的）
                selected=(c.status == FacilityStatus.PENDING),
            )
            for c in candidates
        ]
        if self.config is not None:
            # Issue #27 続編 E Phase 3b: AppConfig + PdfMergeConfig 共に frozen=True
            # のため、``replace()`` を二重に重ねて新 AppConfig instance に差し替える。
            # ``self.config`` 自体は通常 class attribute なので再代入可能。
            self.config = replace(
                self.config,
                pdf_merge=replace(
                    self.config.pdf_merge,
                    facility_root_dir=str(root),
                ),
            )

    def select_all(self) -> None:
        """選択可能な行（PENDING または解決済 A_MULTIPLE）を全選択。"""
        for row in self.rows:
            if row.resolved_a_pdf is not None:
                row.selected = True

    def deselect_all(self) -> None:
        for row in self.rows:
            row.selected = False

    def resolve_a_multiple(self, index: int, chosen: Path) -> None:
        """A_MULTIPLE の行に対しユーザーが選択した A.pdf を反映する。

        Raises:
            ValueError: chosen が candidate.a_pdf_candidates に含まれていない
                （UI 側で外部から任意 path を許してしまうのを防ぐ）。
        """
        row = self.rows[index]
        if chosen not in row.candidate.a_pdf_candidates:
            raise ValueError(
                f"chosen path not in candidates for index={index}"
            )
        row.selected_a_pdf = chosen
        row.selected = True

    def summary(self) -> FacilitySummary:
        """実行前サマリ（選択中 / 実行不可 / 上書き予定）を集計。"""
        selected = sum(1 for r in self.rows if r.is_executable)
        unrunnable = sum(1 for r in self.rows if r.is_unrunnable)
        overwrite = sum(
            1
            for r in self.rows
            if r.is_executable and r.candidate.has_existing_output
        )
        return FacilitySummary(
            selected_count=selected,
            unrunnable_count=unrunnable,
            overwrite_count=overwrite,
        )

    def build_executable_items(self) -> list[BulkExecutionItem]:
        """runner に渡す BulkExecutionItem のリストを構築。

        selected=True かつ resolved_a_pdf 非 None のもののみが対象。
        順序は ViewModel の rows 順を維持（事業所名昇順 = scan 順）。
        """
        items: list[BulkExecutionItem] = []
        if self.root_dir is None:
            return items
        for row in self.rows:
            if not row.is_executable:
                continue
            a_pdf = row.resolved_a_pdf
            if a_pdf is None:
                continue
            items.append(
                BulkExecutionItem(
                    candidate=row.candidate,
                    a_pdf_path=a_pdf,
                    output_root=self.root_dir,
                )
            )
        return items

    def apply_item_update(self, item: BulkExecutionItem) -> None:
        """runner の progress_callback または完了結果を該当行に反映。

        candidate identity（facility_dir）でマッチング。マッチしない場合は
        warning ログを出して silent skip（実行中に rows が再構築された等の race）。
        """
        for row in self.rows:
            if row.candidate.facility_dir == item.candidate.facility_dir:
                row.execution_status = item.status
                row.error_message = item.error_message
                if item.report is not None:
                    row.success_count = len(item.report.success)
                return
        # 不一致は設計上想定外。UI rows と進行中 items の整合性が崩れた状態を
        # fail-loud で記録し、silent failure を回避する（PII 防御で facility_name のみ）。
        logger.warning(
            "apply_item_update: no row matches facility=%s (rows replaced during run?)",
            item.candidate.facility_name,
        )


# =============================================================================
# Dialog（Tk widget、ViewModel に依存）
# =============================================================================


# UI 文字列（クラス外に置くことでテストから参照しやすい）
_TITLE: Final[str] = "事業所フォルダ一括結合"

_BTN_BROWSE_ROOT: Final[str] = "ルート選択..."
_BTN_RESCAN: Final[str] = "再スキャン"
_BTN_SELECT_ALL: Final[str] = "全選択"
_BTN_DESELECT_ALL: Final[str] = "全解除"
_BTN_RUN: Final[str] = "実行"
_BTN_STOP: Final[str] = "停止"
_BTN_CLOSE: Final[str] = "閉じる"
_BTN_OPEN_FOLDER: Final[str] = "📁"
_BTN_OPEN_PDF: Final[str] = "📄"
_BTN_PICK_A: Final[str] = "PDF選択..."

_TITLE_INVALID_INPUT: Final[str] = "入力不備"
_TITLE_SCAN_ERROR: Final[str] = "スキャンエラー"
_TITLE_OPEN_ERROR: Final[str] = "ファイルを開けません"
_TITLE_RUN_ERROR: Final[str] = "実行エラー"

_MSG_NO_ROOT: Final[str] = (
    "ルートフォルダが選択されていません。「ルート選択...」から指定してください。"
)
_MSG_NO_SELECTION: Final[str] = (
    "実行対象の事業所が選択されていません。チェックボックスで選択してください。"
)


# DI 用 type alias
ScanFn = Callable[[Path], list[FacilityCandidate]]
RunFn = Callable[..., list[BulkExecutionItem]]
SaveConfigFn = Callable[..., None]
OpenFn = Callable[[Path], None]


class FacilityRootManagerDialog:
    """事業所ルートフォルダ管理 Toplevel ダイアログ（W4 メイン）。

    Tk widget 部分は薄く、ロジックは FacilityRootViewModel に委譲する。
    """

    def __init__(
        self,
        parent: tk.Tk | tk.Toplevel | tk.Misc,
        *,
        config: AppConfig,
        config_path: Path,
        view_model: FacilityRootViewModel | None = None,
        scan_fn: ScanFn | None = None,
        run_fn: RunFn | None = None,
        save_config_fn: SaveConfigFn | None = None,
        open_fn: OpenFn | None = None,
        messagebox_fn: MessageBoxLike | None = None,
        filedialog_askdirectory: Callable[..., str] | None = None,
        filedialog_askopenfilename: Callable[..., str] | None = None,
    ) -> None:
        assert_main_thread("FacilityRootManagerDialog")

        self._parent = parent
        self._config = config
        self._config_path = config_path
        self._vm = view_model if view_model is not None else FacilityRootViewModel(
            config=config
        )
        if self._vm.config is None:
            self._vm.config = config

        self._scan_fn: ScanFn = scan_fn or scan_facility_root
        self._run_fn: RunFn = run_fn or run_bulk_merge
        self._save_config_fn: SaveConfigFn = save_config_fn or save_config
        self._open_fn: OpenFn = open_fn or open_with_default_app
        self._messagebox = messagebox_fn or default_messagebox()
        self._askdirectory = filedialog_askdirectory or filedialog.askdirectory
        self._askopenfilename = (
            filedialog_askopenfilename or filedialog.askopenfilename
        )

        # スレッド管理（既存 launcher.py パターン踏襲）
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="facility-bulk"
        )
        self._cancel_event: threading.Event | None = None
        self._busy = False

        self._top = tk.Toplevel(parent)
        self._top.title(_TITLE)
        self._top.geometry("760x520")
        self._top.transient(parent)  # type: ignore[arg-type]
        self._top.grab_set()
        # X ボタン / Alt+F4 を _on_close に bind（実行中の強制クローズで worker thread が
        # 宙吊りになるのを防ぐ）。confirm_dialog / session_picker と同じパターン。
        self._top.protocol("WM_DELETE_WINDOW", self._on_close)
        install_tk_exception_guard(
            self._top, component="facility_root", messagebox=self._messagebox
        )

        self._root_var = tk.StringVar(
            value=self._config.pdf_merge.facility_root_dir
        )
        self._summary_var = tk.StringVar(value="")
        self._row_widgets: list[_RowWidget] = []

        self._build_ui()

        # 既存設定 root があれば自動スキャン（次回起動時の利便性）
        if self._config.pdf_merge.facility_root_dir:
            saved_root = Path(self._config.pdf_merge.facility_root_dir)
            if saved_root.exists() and saved_root.is_dir():
                self._do_scan(saved_root)

    # ----- UI 構築 -----

    def _build_ui(self) -> None:
        outer = ttk.Frame(self._top, padding=10)
        outer.pack(fill="both", expand=True)

        # ルート選択行
        top_row = ttk.Frame(outer)
        top_row.pack(fill="x")
        ttk.Label(top_row, text="ルート:").pack(side="left", padx=(0, 6))
        ttk.Entry(top_row, textvariable=self._root_var, width=60).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(
            top_row, text=_BTN_BROWSE_ROOT, command=self._on_browse_root
        ).pack(side="left", padx=(6, 0))
        ttk.Button(top_row, text=_BTN_RESCAN, command=self._on_rescan).pack(
            side="left", padx=(6, 0)
        )

        # ツールバー（全選択 / 全解除 / サマリ）
        tool_row = ttk.Frame(outer)
        tool_row.pack(fill="x", pady=(8, 4))
        self._btn_select_all = ttk.Button(
            tool_row, text=_BTN_SELECT_ALL, command=self._on_select_all
        )
        self._btn_deselect_all = ttk.Button(
            tool_row, text=_BTN_DESELECT_ALL, command=self._on_deselect_all
        )
        self._btn_select_all.pack(side="left")
        self._btn_deselect_all.pack(side="left", padx=(6, 0))
        ttk.Label(tool_row, textvariable=self._summary_var).pack(
            side="right"
        )

        # 一覧（ScrollableFrame: Canvas + 内部 Frame）
        list_outer = ttk.Frame(outer)
        list_outer.pack(fill="both", expand=True, pady=(4, 4))
        self._canvas = tk.Canvas(list_outer, highlightthickness=0)
        scrollbar = ttk.Scrollbar(
            list_outer, orient="vertical", command=self._canvas.yview
        )
        self._canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)
        self._inner_frame = ttk.Frame(self._canvas)
        self._canvas_window = self._canvas.create_window(
            (0, 0), window=self._inner_frame, anchor="nw"
        )
        self._inner_frame.bind(
            "<Configure>",
            lambda _e: self._canvas.configure(
                scrollregion=self._canvas.bbox("all")
            ),
        )

        # 実行ボタン行
        btn_row = ttk.Frame(outer)
        btn_row.pack(fill="x", pady=(6, 0))
        self._btn_run = ttk.Button(btn_row, text=_BTN_RUN, command=self._on_run)
        self._btn_stop = ttk.Button(
            btn_row, text=_BTN_STOP, command=self._on_stop, state="disabled"
        )
        self._btn_close = ttk.Button(
            btn_row, text=_BTN_CLOSE, command=self._on_close
        )
        self._btn_run.pack(side="left", padx=(0, 6))
        self._btn_stop.pack(side="left")
        self._btn_close.pack(side="right")

        self._refresh_summary()

    def _refresh_summary(self) -> None:
        s = self._vm.summary()
        self._summary_var.set(
            f"選択中: {s.selected_count}件 / 実行不可: {s.unrunnable_count}件 "
            f"/ 上書き: {s.overwrite_count}件"
        )

    def _rebuild_rows(self) -> None:
        """ViewModel の rows から行ウィジェットを作り直す。"""
        for w in self._row_widgets:
            w.destroy()
        self._row_widgets = []

        for index, row in enumerate(self._vm.rows):
            widget = _RowWidget(
                self._inner_frame,
                row=row,
                index=index,
                on_toggle=self._on_row_toggle,
                on_open_folder=self._on_open_folder,
                on_open_pdf=self._on_open_pdf,
                on_pick_a=self._on_pick_a,
            )
            widget.pack(fill="x", pady=2)
            self._row_widgets.append(widget)

        self._refresh_summary()

    # ----- イベントハンドラ -----

    def _on_browse_root(self) -> None:
        if self._busy:
            # 実行中の再スキャンは進行中 items の candidate 参照と齟齬を起こすため抑止
            return
        path = self._askdirectory(parent=self._top, title="ルートフォルダ選択")
        if path:
            self._do_scan(Path(path))

    def _on_rescan(self) -> None:
        if self._busy:
            # 実行中の再スキャンは progress_callback の facility_dir マッチを破壊するため抑止
            return
        text = self._root_var.get().strip()
        if not text:
            self._messagebox.showerror(_TITLE_INVALID_INPUT, _MSG_NO_ROOT)
            return
        self._do_scan(Path(text))

    def _do_scan(self, root: Path) -> None:
        try:
            candidates = self._scan_fn(root)
        except FileNotFoundError:
            self._messagebox.showerror(
                _TITLE_SCAN_ERROR,
                "ルートフォルダが見つかりません。パスを確認してください。",
            )
            return
        except NotADirectoryError:
            self._messagebox.showerror(
                _TITLE_SCAN_ERROR,
                "指定したパスはフォルダではありません。",
            )
            return
        except Exception as e:  # noqa: BLE001 — ネットワーク断・権限等の汎用エラー
            # PII 防御: logger.exception はトレースバック経由で例外 message
            # （絶対パス含む）を漏らすため使わない。bulk_runner と同じく型名のみ。
            logger.error("scan failed: %s", type(e).__name__)
            self._messagebox.showerror(
                _TITLE_SCAN_ERROR,
                f"スキャン中にエラーが発生しました（{type(e).__name__}）。",
            )
            return

        self._vm.set_root_and_rows(root, candidates)
        self._root_var.set(str(root))
        # AppConfig 更新を永続化（既存ファイルなら無条件上書き、無ければ作成）
        save_failed = False
        try:
            self._save_config_fn(self._config, self._config_path, create_if_missing=True)
        except Exception as e:  # noqa: BLE001 — 保存失敗で UI を止めない
            # error レベル: 介護現場で「設定したのに次回反映されない」混乱の主因
            logger.error(
                "save_config failed (root_dir won't persist): %s", type(e).__name__
            )
            save_failed = True
        self._rebuild_rows()
        if save_failed:
            # サマリ行に控えめ警告を追記（モーダルではなく非侵襲、N=20 件運用で煩雑にしない）
            self._summary_var.set(
                self._summary_var.get()
                + " ⚠ 設定保存失敗（次回起動時にルート再選択が必要）"
            )

    def _on_select_all(self) -> None:
        self._vm.select_all()
        for w in self._row_widgets:
            w.refresh_check()
        self._refresh_summary()

    def _on_deselect_all(self) -> None:
        self._vm.deselect_all()
        for w in self._row_widgets:
            w.refresh_check()
        self._refresh_summary()

    def _on_row_toggle(self, index: int, value: bool) -> None:
        # PENDING 以外で selected=True にしようとした場合は無効化
        row = self._vm.rows[index]
        if value and row.resolved_a_pdf is None:
            self._row_widgets[index].refresh_check()  # 元に戻す
            return
        row.selected = value
        self._refresh_summary()

    def _on_open_folder(self, index: int) -> None:
        self._safe_open(self._vm.rows[index].candidate.facility_dir)

    def _on_open_pdf(self, index: int) -> None:
        self._safe_open(self._vm.rows[index].candidate.output_pdf_path)

    def _safe_open(self, path: Path) -> None:
        try:
            self._open_fn(path)
        except FileNotFoundError:
            self._messagebox.showerror(
                _TITLE_OPEN_ERROR,
                "ファイル / フォルダが見つかりません。",
            )
        except Exception as e:  # noqa: BLE001 — open 系の汎用エラー
            logger.warning("open failed: %s", type(e).__name__)
            self._messagebox.showerror(
                _TITLE_OPEN_ERROR,
                f"開けませんでした（{type(e).__name__}）。",
            )

    def _on_pick_a(self, index: int) -> None:
        row = self._vm.rows[index]
        path = self._askopenfilename(
            parent=self._top,
            title="A.pdf を選択",
            initialdir=str(row.candidate.facility_dir),
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if not path:
            return
        chosen = Path(path)
        try:
            self._vm.resolve_a_multiple(index, chosen)
        except ValueError:
            self._messagebox.showerror(
                _TITLE_INVALID_INPUT,
                "選択したファイルは事業所フォルダ直下の PDF ではありません。",
            )
            return
        self._row_widgets[index].refresh_all()
        self._refresh_summary()

    def _on_run(self) -> None:
        if self._busy:
            return
        items = self._vm.build_executable_items()
        if not items:
            self._messagebox.showerror(_TITLE_INVALID_INPUT, _MSG_NO_SELECTION)
            return

        self._cancel_event = threading.Event()
        self._set_busy(True)

        cancel = self._cancel_event

        def _worker() -> None:
            try:
                self._run_fn(
                    items,
                    progress_callback=self._on_progress,
                    cancel_event=cancel,
                )
            except Exception as e:  # noqa: BLE001 — runner からの予期せぬ伝播
                # PII 防御: logger.exception は traceback 経由で例外 message
                # （絶対パス含む）を漏らすため使わない。_do_scan / bulk_runner と統一。
                logger.error("bulk run failed (worker): %s", type(e).__name__)
                # main thread で notify
                with contextlib.suppress(RuntimeError, tk.TclError):
                    self._top.after(0, self._on_run_error, type(e).__name__)
            else:
                with contextlib.suppress(RuntimeError, tk.TclError):
                    self._top.after(0, self._on_run_done)

        self._executor.submit(_worker)

    def _on_progress(self, _index: int, item: BulkExecutionItem) -> None:
        """worker thread から呼ばれる progress callback。main thread に bridge する。"""
        with contextlib.suppress(RuntimeError, tk.TclError):
            self._top.after(0, self._apply_progress, item)

    def _apply_progress(self, item: BulkExecutionItem) -> None:
        self._vm.apply_item_update(item)
        for w in self._row_widgets:
            if w.row.candidate.facility_dir == item.candidate.facility_dir:
                w.refresh_all()
                break

    def _on_run_done(self) -> None:
        self._set_busy(False)
        self._refresh_summary()
        # 完了サマリを messagebox で明示告知。N=20 件処理で失敗を見落とすリスクを回避。
        # 本 PR の主目的「サイレント失敗回避」に直結（review 指摘を反映）。
        self._messagebox.showinfo("実行完了", self._build_completion_summary())

    def _build_completion_summary(self) -> str:
        """実行後の各 status 件数を集計したサマリ文字列を構築する。"""
        counts: dict[BulkExecutionStatus, int] = {s: 0 for s in BulkExecutionStatus}
        for row in self._vm.rows:
            if row.execution_status is not None:
                counts[row.execution_status] += 1
        lines = [
            f"完了: {counts[BulkExecutionStatus.SUCCESS]}件",
            f"結合対象なし: {counts[BulkExecutionStatus.PARTIAL]}件",
            f"PDFロック: {counts[BulkExecutionStatus.FAILED_LOCKED]}件",
            f"エラー: {counts[BulkExecutionStatus.FAILED]}件",
            f"未処理(停止): {counts[BulkExecutionStatus.CANCELLED_SKIPPED]}件",
        ]
        return "\n".join(lines)

    def _on_run_error(self, type_name: str) -> None:
        self._set_busy(False)
        self._messagebox.showerror(
            _TITLE_RUN_ERROR,
            f"処理中にエラーが発生しました（{type_name}）。",
        )

    def _on_stop(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()

    def _on_close(self) -> None:
        if self._busy:
            # 実行中はクローズ抑止（停止してから閉じる）
            return
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._top.destroy()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        run_state = ["disabled"] if busy else ["!disabled"]
        stop_state = ["!disabled"] if busy else ["disabled"]
        self._btn_run.state(run_state)  # type: ignore[no-untyped-call]
        self._btn_stop.state(stop_state)  # type: ignore[no-untyped-call]

    # ----- テスト用アクセサ -----

    def get_view_model(self) -> FacilityRootViewModel:
        return self._vm

    def get_toplevel(self) -> tk.Toplevel:
        return self._top


# =============================================================================
# 行ウィジェット（内部用、UI 内部実装の詳細）
# =============================================================================


class _RowWidget(ttk.Frame):
    """1 事業所行の widget。Checkbutton + Label + Button x N。"""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        row: FacilityRow,
        index: int,
        on_toggle: Callable[[int, bool], None],
        on_open_folder: Callable[[int], None],
        on_open_pdf: Callable[[int], None],
        on_pick_a: Callable[[int], None],
    ) -> None:
        super().__init__(parent)
        self.row = row
        self._index = index
        self._on_toggle = on_toggle

        self._var = tk.BooleanVar(value=row.selected)
        self._check = ttk.Checkbutton(
            self,
            variable=self._var,
            command=lambda: on_toggle(index, bool(self._var.get())),
        )
        self._name = ttk.Label(self, text=row.candidate.facility_name, width=30)
        self._status = ttk.Label(self, text=row.display_status, width=35)
        self._btn_folder = ttk.Button(
            self, text=_BTN_OPEN_FOLDER, width=3, command=lambda: on_open_folder(index)
        )
        self._btn_pdf = ttk.Button(
            self, text=_BTN_OPEN_PDF, width=3, command=lambda: on_open_pdf(index)
        )
        self._btn_pick = ttk.Button(
            self, text=_BTN_PICK_A, command=lambda: on_pick_a(index)
        )

        self._check.grid(row=0, column=0, padx=(0, 6))
        self._name.grid(row=0, column=1, sticky="w")
        self._status.grid(row=0, column=2, sticky="w", padx=(8, 0))
        self._btn_folder.grid(row=0, column=3, padx=(8, 0))
        self._btn_pdf.grid(row=0, column=4, padx=(2, 0))
        self._btn_pick.grid(row=0, column=5, padx=(2, 0))

        self.refresh_all()

    def refresh_check(self) -> None:
        self._var.set(self.row.selected)

    def refresh_all(self) -> None:
        self._var.set(self.row.selected)
        self._status.configure(text=self.row.display_status)
        # 「PDFを開く」は出力存在時のみ
        self._btn_pdf.state(  # type: ignore[no-untyped-call]
            ["!disabled"] if self.row.can_open_output_pdf else ["disabled"]
        )
        # 「PDF選択」は A_MULTIPLE 時のみ表示
        if self.row.candidate.status == FacilityStatus.A_MULTIPLE:
            self._btn_pick.grid()
        else:
            self._btn_pick.grid_remove()
