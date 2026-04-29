"""ex_extractor 統合ダイアログ (PR4)。

Wiseman .ex_ ファイル PDF 抽出 + 事業所フォルダ振り分けのデスクトップ UI。
PR3 の ``extract_directory`` を呼ぶオーケストレータで、AMBIGUOUS / UNMATCHED は
``ManualDistributionDialog`` 経由で手動振り分けする。

アーキテクチャ:
    - ``ExExtractorViewModel``: pure Python の状態管理 (テスト容易性のため分離)
    - ``ExExtractorDialog``: Tk widget の薄ラッパー (ViewModel に依存)

UI ロジックの中心は ViewModel に集約し、Tk 部分は表示と入力の bridge のみ。
これにより macOS でも実機に依存せず大半をテストできる (facility_root_dialog 踏襲)。

スレッド境界:
    - extract_directory は worker thread (独立 ThreadPoolExecutor)
    - 結果は ``root.after(0, ...)`` で main thread に bridge

PII 保護方針 (ADR-014 準拠):
    - 進捗 / 結果サマリは件数のみ
    - 事業所名・候補・matched_facility はサマリに出さない (ManualDistributionDialog 内のみ表示)
    - filename は表示許容 (運用者識別用)
    - orphan_alias_canonicals は警告バナーで表示 (alias 設定不整合通知用、外部送信なし)
"""

from __future__ import annotations

import contextlib
import logging
import tkinter as tk
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Final, Protocol

from wiseman_hub.config import AppConfig, save_config
from wiseman_hub.pdf.ex_extractor import (
    ExtractionItem,
    ExtractionResult,
    ExtractionStatus,
    SfxAdapter,
    UnsupportedSfxPlatformError,
    extract_directory,
)
from wiseman_hub.pdf.facility_resolver import ResolveReason
from wiseman_hub.ui.common import (
    MessageBoxLike,
    assert_main_thread,
    default_messagebox,
    install_tk_exception_guard,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# UI 状態遷移 (CLAUDE.md: status 設計先行)
# ---------------------------------------------------------------------------


class UiState(StrEnum):
    """ExExtractorDialog の UI 状態。

    遷移:
        IDLE → BUSY (「実行」押下)
        SHOWING_RESULT → BUSY (再実行: 「実行」再押下)
        BUSY → SHOWING_RESULT (extract_directory 完了)
        BUSY → IDLE (例外時、エラーモーダル表示)
        MANUAL_DISTRIBUTING → IDLE (手動振り分け中の例外で復帰)
        SHOWING_RESULT → MANUAL_DISTRIBUTING (「手動振り分けへ」押下)
        MANUAL_DISTRIBUTING → SHOWING_RESULT (手動振り分け完了で結果統合)

    不変条件:
        - BUSY 中は他ボタン disable + 二重起動禁止 (close ボタンも抑止)
        - SHOWING_RESULT で result 非 None
    """

    IDLE = "idle"
    BUSY = "busy"
    SHOWING_RESULT = "showing_result"
    MANUAL_DISTRIBUTING = "manual_distributing"


# ---------------------------------------------------------------------------
# ViewModel (pure Python、テスト容易)
# ---------------------------------------------------------------------------


@dataclass
class ExExtractorViewModel:
    """ExExtractorDialog の状態管理 (Tk 非依存)。

    Attributes:
        source_dir: .ex_ 取込元 (PR1 ex_source_dir)
        facility_root_dir: 事業所サブフォルダの親 (PR #126 facility_root_dir)
        aliases: PR1 facility_aliases 検証済 dict
        state: UI 状態
        result: extract_directory の結果 (SHOWING_RESULT / MANUAL_DISTRIBUTING で非 None)
        error_message: BUSY → IDLE 遷移時のエラー (PII-safe enum 値 / 型名のみ)
    """

    source_dir: Path
    facility_root_dir: Path
    aliases: dict[str, list[str]] = field(default_factory=dict)
    state: UiState = UiState.IDLE
    result: ExtractionResult | None = None
    error_message: str | None = None

    @property
    def can_run(self) -> bool:
        """「実行」ボタンが押下可能か (IDLE で source/root が存在する場合)。"""
        return (
            self.state is UiState.IDLE
            and self.source_dir.exists()
            and self.facility_root_dir.exists()
        )

    @property
    def can_open_manual(self) -> bool:
        """「手動振り分けへ」が押下可能か (SHOWING_RESULT で pending_manual > 0)。"""
        if self.state is not UiState.SHOWING_RESULT or self.result is None:
            return False
        return len(self.result.pending_manual) > 0

    @property
    def is_busy(self) -> bool:
        """実行中か (BUSY または MANUAL_DISTRIBUTING)。"""
        return self.state in (UiState.BUSY, UiState.MANUAL_DISTRIBUTING)

    def transition_to_busy(self) -> None:
        """IDLE / SHOWING_RESULT → BUSY。"""
        if self.state not in (UiState.IDLE, UiState.SHOWING_RESULT):
            raise RuntimeError(f"cannot transition to BUSY from {self.state}")
        self.state = UiState.BUSY
        self.error_message = None

    def transition_to_showing_result(self, result: ExtractionResult) -> None:
        """BUSY / MANUAL_DISTRIBUTING → SHOWING_RESULT。"""
        if self.state not in (UiState.BUSY, UiState.MANUAL_DISTRIBUTING):
            raise RuntimeError(
                f"cannot transition to SHOWING_RESULT from {self.state}"
            )
        self.state = UiState.SHOWING_RESULT
        self.result = result

    def transition_to_idle_with_error(self, error_message: str) -> None:
        """BUSY / MANUAL_DISTRIBUTING → IDLE (例外時、PII-safe メッセージのみ)。

        HIGH-D (type-analyzer C1): 遷移元チェックを追加。SHOWING_RESULT から
        誤って呼ばれて result が宙に浮く事故を構造的に防ぐ。
        """
        if self.state not in (UiState.BUSY, UiState.MANUAL_DISTRIBUTING):
            raise RuntimeError(
                f"cannot transition to IDLE with error from {self.state}"
            )
        self.state = UiState.IDLE
        self.error_message = error_message

    def transition_to_manual_distributing(self) -> None:
        """SHOWING_RESULT → MANUAL_DISTRIBUTING。"""
        if self.state is not UiState.SHOWING_RESULT:
            raise RuntimeError(
                f"cannot transition to MANUAL_DISTRIBUTING from {self.state}"
            )
        self.state = UiState.MANUAL_DISTRIBUTING

    def merge_manual_results(
        self, manual_items: Sequence[ExtractionItem]
    ) -> None:
        """手動振り分けの結果を既存 result に統合する。

        pending_manual だった item を manual_items で置き換え (source_path 一致)、
        SHOWING_RESULT に戻す。
        """
        if self.result is None:
            raise RuntimeError("merge_manual_results requires existing result")

        manual_by_source = {item.source_path: item for item in manual_items}
        new_items = tuple(
            manual_by_source.get(item.source_path, item)
            for item in self.result.items
        )
        # pending_filenames も再計算
        pending_statuses = {
            ExtractionStatus.SKIPPED_AMBIGUOUS,
            ExtractionStatus.SKIPPED_UNMATCHED,
        }
        new_pending = tuple(
            item.source_path.name
            for item in new_items
            if item.status in pending_statuses
        )
        self.result = ExtractionResult(
            items=new_items,
            orphan_alias_canonicals=self.result.orphan_alias_canonicals,
            pending_filenames=new_pending,
        )
        self.state = UiState.SHOWING_RESULT

    def get_summary_lines(self) -> list[str]:
        """SHOWING_RESULT 時のサマリ行 (PII-safe、件数のみ)。"""
        if self.result is None:
            return []
        items = self.result.items
        success_count = self.result.success_count
        manual_override_count = sum(
            1
            for item in items
            if item.status is ExtractionStatus.SUCCESS
            and item.resolve_result.reason is ResolveReason.MANUAL_OVERRIDE
        )
        auto_success = success_count - manual_override_count
        pending_count = len(self.result.pending_manual)
        failed_count = len(self.result.failed)
        # 要確認 (PARTIAL_OUTPUT / partially_moved)
        attention_count = sum(
            1
            for item in items
            if item.status is ExtractionStatus.PARTIAL_OUTPUT
            or item.partially_moved
        )

        lines = [
            f"処理対象: {len(items)} 件",
            f"自動振り分け成功: {auto_success} 件",
            f"手動確定成功: {manual_override_count} 件",
            f"失敗: {failed_count} 件",
            f"手動振り分け待ち: {pending_count} 件",
        ]
        if attention_count > 0:
            lines.append(f"⚠ 要確認 (一部抽出/移動): {attention_count} 件")
        if self.result.orphan_alias_canonicals:
            lines.append(
                f"⚠ alias 設定不整合: {len(self.result.orphan_alias_canonicals)} 件"
            )
        return lines


# ---------------------------------------------------------------------------
# UI 文言定数 (介護現場向け、PII を含まない)
# ---------------------------------------------------------------------------


_TITLE: Final[str] = "ex_ ファイル変換 + 振り分け"

_BTN_RUN: Final[str] = "実行"
_BTN_OPEN_MANUAL: Final[str] = "手動振り分けへ..."
_BTN_CLOSE: Final[str] = "閉じる"
_BTN_BROWSE_SOURCE: Final[str] = "取込元選択..."

_LBL_SOURCE: Final[str] = "取込元 (.ex_):"
_LBL_FACILITY_ROOT: Final[str] = "事業所ルート:"
_LBL_NOT_SET: Final[str] = "(未設定)"
_LBL_RUNNING: Final[str] = "処理中... (最大 数分かかる場合があります)"

_TITLE_CONFIG_MISSING: Final[str] = "設定が未完了"
_MSG_SOURCE_MISSING: Final[str] = (
    "取込元フォルダ (ex_source_dir) が設定されていません。\n"
    "「設定」画面で TOML を編集してください。"
)
_MSG_ROOT_MISSING: Final[str] = (
    "事業所ルートフォルダ (facility_root_dir) が設定されていません。\n"
    "「事業所フォルダ一括結合」のルート選択で設定するか、TOML を編集してください。"
)
_TITLE_RUN_ERROR: Final[str] = "実行エラー"
_TITLE_PLATFORM_ERROR: Final[str] = "Windows 専用機能"
_MSG_PLATFORM_ERROR: Final[str] = (
    "ex_ ファイルの抽出は Windows 専用です (SFX 自己解凍 EXE 実行のため)。\n"
    "macOS では動作しません。"
)
_TITLE_INVALID_SOURCE: Final[str] = "取込元フォルダが無効"
_MSG_INVALID_SOURCE_FMT: Final[str] = (
    "選択されたフォルダが存在しないかディレクトリではありません:\n{path}"
)
_TITLE_BROWSE_SOURCE: Final[str] = "取込元 (.ex_) フォルダを選択"
_MSG_SOURCE_VALIDATION_ERROR_FMT: Final[str] = (
    "取込元フォルダの状態を確認できませんでした (型: {type})。\n"
    "ネットワーク切断 / 権限不足 / UNC パス到達不能の可能性があります。"
)
_MSG_SOURCE_SAVE_FAILED_FMT: Final[str] = (
    "取込元の設定保存に失敗しました ({type})。\n"
    "今回のセッションでは選択値で動作しますが、次回起動時には反映されません。"
)
_TITLE_SOURCE_SAVE_FAILED: Final[str] = "設定保存失敗"


# DI 用 type alias
ExtractFn = Callable[..., ExtractionResult]
SaveConfigFn = Callable[..., None]


class _ManualDialogProtocol(Protocol):
    """ManualDistributionDialog の最小契約 (テスト fake 用)。"""

    def get_results(self) -> tuple[ExtractionItem, ...]: ...


class ExExtractorDialog:
    """ex_extractor 統合 Toplevel ダイアログ (PR4 メイン)。

    Tk widget 部分は薄く、ロジックは ExExtractorViewModel に委譲する。
    facility_root_dialog のパターンを踏襲し、独立 executor + transient + grab_set。
    """

    def __init__(
        self,
        parent: tk.Tk | tk.Toplevel | tk.Misc,
        *,
        config: AppConfig,
        adapter: SfxAdapter,
        config_path: Path | None = None,
        view_model: ExExtractorViewModel | None = None,
        extract_fn: ExtractFn | None = None,
        save_config_fn: SaveConfigFn | None = None,
        on_source_persisted: Callable[[AppConfig], None] | None = None,
        manual_dialog_factory: Callable[..., _ManualDialogProtocol] | None = None,
        messagebox_fn: MessageBoxLike | None = None,
        filedialog_askdirectory: Callable[..., str] | None = None,
    ) -> None:
        assert_main_thread("ExExtractorDialog")

        self._parent = parent
        self._config = config
        # config_path = None の場合は永続化を skip (Tk smoke テスト等の DI 互換)。
        # 本番経路 (__main__._make_ex_extractor_callback) からは必ず明示的に渡される。
        self._config_path = config_path
        self._adapter = adapter
        self._extract_fn: ExtractFn = extract_fn or extract_directory
        # Issue #165 (R1): 取込元選択を TOML 永続化するための DI。FacilityRootDialog
        # と同パターンで save_config を inject 可能にして UI test で mock できるようにする。
        self._save_config_fn: SaveConfigFn = save_config_fn or save_config
        # 永続化成功時に launcher.reload_config 等を呼ぶための callback (Codex review D4)。
        # save 失敗時は呼ばない (AppConfig 不整合防止)。
        self._on_source_persisted = on_source_persisted
        self._manual_dialog_factory = manual_dialog_factory  # None なら遅延 import で default
        self._messagebox = messagebox_fn or default_messagebox()
        # Issue #155: 取込元 (.ex_) フォルダを GUI で都度選択可能にする (DI で
        # mock 可能にする)。FacilityRootDialog の同パターンを踏襲。
        self._askdirectory = filedialog_askdirectory or filedialog.askdirectory

        # ViewModel 初期化 (config から source/root/aliases を解決)
        if view_model is None:
            source = Path(config.pdf_merge.ex_source_dir or ".")
            root = Path(config.pdf_merge.facility_root_dir or ".")
            view_model = ExExtractorViewModel(
                source_dir=source,
                facility_root_dir=root,
                aliases=dict(config.pdf_merge.facility_aliases),
            )
        self._vm = view_model

        # 独立 executor (busy 状態が dialog 内で完結、launcher へ漏れない)
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="ex-extractor"
        )

        self._top = tk.Toplevel(parent)
        self._top.title(_TITLE)
        self._top.geometry("560x420")
        self._top.transient(parent)  # type: ignore[arg-type]
        self._top.grab_set()
        self._top.protocol("WM_DELETE_WINDOW", self._on_close)
        install_tk_exception_guard(
            self._top, component="ex_extractor", messagebox=self._messagebox
        )

        self._build_ui()
        self._redraw()

    # ----- UI 構築 -----

    def _build_ui(self) -> None:
        outer = ttk.Frame(self._top, padding=12)
        outer.pack(fill="both", expand=True)

        # 設定パス表示
        path_frame = ttk.Frame(outer)
        path_frame.pack(fill="x", pady=(0, 8))

        # Issue #155: source_dir / facility_root_dir の Label は再描画で
        # 値を更新する必要があるため self._lbl_source / self._lbl_facility_root
        # で保持する (browse 後 / vm 変更時に _redraw で text を更新)。
        ttk.Label(path_frame, text=_LBL_SOURCE).grid(row=0, column=0, sticky="w")
        self._lbl_source = ttk.Label(path_frame, text="", foreground="#444")
        self._lbl_source.grid(row=0, column=1, sticky="w", padx=(8, 0))
        # 取込元選択ボタン (Issue #155): TOML 固定の不便を解消、毎回違うフォルダ
        # から処理可能にする。FacilityRootDialog の Browse パターンを踏襲。
        self._btn_browse_source = ttk.Button(
            path_frame,
            text=_BTN_BROWSE_SOURCE,
            command=self._on_browse_source,
        )
        self._btn_browse_source.grid(row=0, column=2, sticky="w", padx=(8, 0))

        ttk.Label(path_frame, text=_LBL_FACILITY_ROOT).grid(
            row=1, column=0, sticky="w"
        )
        self._lbl_facility_root = ttk.Label(path_frame, text="", foreground="#444")
        self._lbl_facility_root.grid(row=1, column=1, sticky="w", padx=(8, 0))

        # 実行ボタン + ステータスラベル
        action_frame = ttk.Frame(outer)
        action_frame.pack(fill="x", pady=8)
        self._btn_run = ttk.Button(
            action_frame, text=_BTN_RUN, command=self._on_run_click
        )
        self._btn_run.pack(side="left")
        self._lbl_status = ttk.Label(action_frame, text="", foreground="#888")
        self._lbl_status.pack(side="left", padx=(12, 0))

        # orphan 警告バナー (MEDIUM-5: silent-failure-hunter MEDIUM-8 対応)
        # alias 設定不整合は次回以降も自動振り分け失敗を生む構造的問題のため、
        # サマリ末尾ではなく専用 frame を上部に常時表示で見落とし防止
        self._orphan_banner_frame = ttk.Frame(outer)
        self._lbl_orphan_banner = ttk.Label(
            self._orphan_banner_frame,
            text="",
            foreground="#c00",
            font=("TkDefaultFont", 10, "bold"),
        )
        self._lbl_orphan_banner.pack(anchor="w")

        # 結果サマリ
        self._summary_frame = ttk.LabelFrame(outer, text="結果", padding=8)
        self._summary_frame.pack(fill="both", expand=True, pady=(8, 0))
        self._summary_text = tk.Text(
            self._summary_frame, height=10, state="disabled", wrap="word"
        )
        self._summary_text.pack(fill="both", expand=True)

        # 下段ボタン
        bottom = ttk.Frame(outer)
        bottom.pack(fill="x", pady=(8, 0))
        self._btn_open_manual = ttk.Button(
            bottom,
            text=_BTN_OPEN_MANUAL,
            command=self._on_open_manual_click,
        )
        self._btn_open_manual.pack(side="left")
        self._btn_close = ttk.Button(
            bottom, text=_BTN_CLOSE, command=self._on_close
        )
        self._btn_close.pack(side="right")

    # ----- 状態反映 -----

    def _redraw(self) -> None:
        """vm.state に基づき UI を再描画。"""
        # Issue #155: source_dir / facility_root_dir のパス表示を毎回更新
        # (browse 直後の _redraw で新値が即座に反映される)。存在しないパスは
        # _LBL_NOT_SET 表示に切替えてユーザーに伝える。
        self._lbl_source.configure(
            text=str(self._vm.source_dir)
            if self._vm.source_dir.exists()
            else _LBL_NOT_SET
        )
        self._lbl_facility_root.configure(
            text=str(self._vm.facility_root_dir)
            if self._vm.facility_root_dir.exists()
            else _LBL_NOT_SET
        )

        # ボタン enable/disable
        self._btn_run.configure(
            state="normal" if self._vm.can_run else "disabled"
        )
        self._btn_open_manual.configure(
            state="normal" if self._vm.can_open_manual else "disabled"
        )
        self._btn_close.configure(
            state="disabled" if self._vm.is_busy else "normal"
        )
        # browse は busy 中は disable (race / 走行中変更を防ぐ)
        self._btn_browse_source.configure(
            state="disabled" if self._vm.is_busy else "normal"
        )

        # ステータス文言
        if self._vm.state is UiState.BUSY:
            self._lbl_status.configure(text=_LBL_RUNNING, foreground="#0066cc")
        elif self._vm.error_message is not None:
            self._lbl_status.configure(
                text=f"エラー: {self._vm.error_message}", foreground="#c00"
            )
        else:
            self._lbl_status.configure(text="", foreground="#888")

        # orphan banner (常時表示、SHOWING_RESULT 時のみ pack)
        if (
            self._vm.state is UiState.SHOWING_RESULT
            and self._vm.result is not None
            and self._vm.result.orphan_alias_canonicals
        ):
            count = len(self._vm.result.orphan_alias_canonicals)
            self._lbl_orphan_banner.configure(
                text=(
                    f"⚠ alias 設定不整合: {count} 件 — "
                    "実フォルダが存在しない canonical があります。"
                    "TOML を修正してください。"
                )
            )
            self._orphan_banner_frame.pack(
                fill="x", pady=(4, 0), before=self._summary_frame
            )
        else:
            self._orphan_banner_frame.pack_forget()

        # サマリテキスト
        self._summary_text.configure(state="normal")
        self._summary_text.delete("1.0", "end")
        if self._vm.state is UiState.SHOWING_RESULT and self._vm.result is not None:
            for line in self._vm.get_summary_lines():
                self._summary_text.insert("end", line + "\n")

            # 失敗 / 要確認 / pending の filename 一覧 (PII-safe)
            self._render_filenames_section(
                "--- 失敗 ---", self._vm.result.failed
            )
            attention = tuple(
                item
                for item in self._vm.result.items
                if item.status is ExtractionStatus.PARTIAL_OUTPUT
                or item.partially_moved
            )
            if attention:
                self._render_filenames_section("--- 要確認 ---", attention)
            if self._vm.result.pending_filenames:
                self._summary_text.insert("end", "\n--- 手動振り分け待ち ---\n")
                for name in self._vm.result.pending_filenames:
                    self._summary_text.insert("end", f"  ? {name}\n")
            if self._vm.result.orphan_alias_canonicals:
                self._summary_text.insert(
                    "end", "\n--- alias 設定不整合 ---\n"
                )
                for canonical in self._vm.result.orphan_alias_canonicals:
                    self._summary_text.insert("end", f"  ! {canonical}\n")
        self._summary_text.configure(state="disabled")

    def _render_filenames_section(
        self, header: str, items: Sequence[ExtractionItem]
    ) -> None:
        if not items:
            return
        self._summary_text.insert("end", f"\n{header}\n")
        for item in items:
            code = item.error_code.value if item.error_code else "—"
            self._summary_text.insert(
                "end", f"  x {item.source_path.name} [{code}]\n"
            )
            if item.partially_moved:
                self._summary_text.insert(
                    "end",
                    f"      (一部 PDF 移動済: {len(item.partially_moved)} 件)\n",
                )

    # ----- イベントハンドラ -----

    def _on_browse_source(self) -> None:
        """取込元 (.ex_) フォルダを folder browser で都度選択する (Issue #155 + #165)。

        分岐契約:
        - busy 中 → 何もしない (UI disable 済 + defensive)
        - キャンセル (空文字 return) → current value 保持
        - 存在しない / ディレクトリでない → ``_TITLE_INVALID_SOURCE`` 通知
        - ``exists()`` / ``is_dir()`` 自体が ``OSError`` を raise (Windows UNC /
          ネットワーク切断 / 権限拒否) → 型名のみログ + 検証エラー通知
          (silent-failure-hunter HIGH-1 対応)
        - 成功時 → ``_vm.source_dir`` 更新 + ``_config.pdf_merge.ex_source_dir`` 更新
          + ``save_config`` で **TOML 永続化** (R1, Issue #165) +
          ``on_source_persisted`` callback (launcher.reload_config 等) +
          ``_redraw`` で UI 反映
        - **save 失敗時** は callback を呼ばず (Codex review D4: AppConfig 不整合防止)、
          控えめエラー通知 + ViewModel 更新は維持 (今セッションは選択値で動作可能)
        """
        if self._vm.is_busy:
            return
        path = self._askdirectory(parent=self._top, title=_TITLE_BROWSE_SOURCE)
        if not path:
            return
        selected = Path(path)
        try:
            is_valid = selected.exists() and selected.is_dir()
        except OSError as exc:
            # PII 防御: path 文字列を log に出さない (型名のみ)。
            # messagebox には選択 path を含めない (原因型のみ表示)。
            logger.error(
                "browse source validation OSError: %s", type(exc).__name__
            )
            self._messagebox.showerror(
                _TITLE_INVALID_SOURCE,
                _MSG_SOURCE_VALIDATION_ERROR_FMT.format(
                    type=type(exc).__name__
                ),
            )
            return
        if not is_valid:
            self._messagebox.showerror(
                _TITLE_INVALID_SOURCE,
                _MSG_INVALID_SOURCE_FMT.format(path=selected),
            )
            return

        self._vm.source_dir = selected
        # R1 (Issue #165): TOML 永続化。FacilityRootDialog._do_scan のパターン踏襲
        # (save_failed なら控えめ警告 + on_source_persisted は呼ばない)。
        # config_path 未指定時 (テスト等) は永続化を skip して ViewModel 更新のみ。
        save_failed_type: str | None = None
        if self._config_path is not None:
            self._config.pdf_merge.ex_source_dir = str(selected)
            try:
                self._save_config_fn(
                    self._config, self._config_path, create_if_missing=True
                )
            except Exception as exc:  # noqa: BLE001 — 保存失敗で UI を止めない
                logger.error(
                    "save_config failed (ex_source_dir won't persist): %s",
                    type(exc).__name__,
                )
                save_failed_type = type(exc).__name__

            if save_failed_type is None and self._on_source_persisted is not None:
                # 保存成功時のみ launcher.reload_config 等の側方効果を発火
                # (Codex review D4: 失敗時 reload は AppConfig 不整合の温床)
                try:
                    self._on_source_persisted(self._config)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "on_source_persisted callback failed: %s",
                        type(exc).__name__,
                    )

        self._redraw()
        if save_failed_type is not None:
            # MessageBoxLike Protocol は showwarning 未定義のため showerror を流用
            # (タイトル「設定保存失敗」で warning レベルの意図を伝達)
            self._messagebox.showerror(
                _TITLE_SOURCE_SAVE_FAILED,
                _MSG_SOURCE_SAVE_FAILED_FMT.format(type=save_failed_type),
            )

    def _on_run_click(self) -> None:
        if not self._vm.can_run:
            self._show_config_missing_modal()
            return

        try:
            self._vm.transition_to_busy()
        except RuntimeError as e:
            logger.warning("invalid state transition: %s", type(e).__name__)
            return

        self._redraw()
        future = self._executor.submit(self._run_extract)
        future.add_done_callback(
            lambda f: self._top.after(0, self._on_extract_done, f)
        )

    def _run_extract(self) -> ExtractionResult:
        return self._extract_fn(
            source_dir=self._vm.source_dir,
            facility_root_dir=self._vm.facility_root_dir,
            aliases=self._vm.aliases,
            adapter=self._adapter,
        )

    def _on_extract_done(self, future: Future[ExtractionResult]) -> None:
        # HIGH-A / HIGH-B: dialog destroy 後の after callback 到達ガード
        # (close 後に extract_directory が完遂したケースの TclError 回避)
        if not self._top.winfo_exists():
            logger.warning(
                "extract result arrived after dialog destroy "
                "(possible orphaned worker thread)"
            )
            return

        try:
            result = future.result()
        except UnsupportedSfxPlatformError:
            self._vm.transition_to_idle_with_error("unsupported_platform")
            self._redraw()
            self._messagebox.showerror(_TITLE_PLATFORM_ERROR, _MSG_PLATFORM_ERROR)
            return
        except FileNotFoundError as e:
            self._vm.transition_to_idle_with_error(type(e).__name__)
            self._redraw()
            self._messagebox.showerror(_TITLE_RUN_ERROR, str(e))
            return
        except Exception as e:  # noqa: BLE001
            # PII 防御で型名のみ
            self._vm.transition_to_idle_with_error(type(e).__name__)
            self._redraw()
            self._messagebox.showerror(
                _TITLE_RUN_ERROR,
                f"処理中にエラーが発生しました: {type(e).__name__}",
            )
            return

        self._vm.transition_to_showing_result(result)
        self._redraw()

    def _on_open_manual_click(self) -> None:
        if not self._vm.can_open_manual:
            return
        if self._vm.result is None:
            return

        # HIGH-C: 例外時に MANUAL_DISTRIBUTING 固着を防ぐため、saved_result を保持
        # して例外発生時に SHOWING_RESULT に復帰可能にする
        saved_result = self._vm.result
        self._vm.transition_to_manual_distributing()
        self._redraw()

        try:
            # ManualDistributionDialog を遅延 import (循環 import 回避)
            factory: Callable[..., _ManualDialogProtocol]
            if self._manual_dialog_factory is None:
                from wiseman_hub.ui.manual_distribution_dialog import (
                    ManualDistributionDialog,
                )

                factory = ManualDistributionDialog
            else:
                factory = self._manual_dialog_factory

            # facility_root_dir 配下の facility_names を再計算
            # iterdir() の OSError も外側 except で捕捉される
            facility_names = sorted(
                d.name
                for d in self._vm.facility_root_dir.iterdir()
                if d.is_dir() and not d.name.startswith("_")
            )

            dialog = factory(
                self._top,
                pending_items=saved_result.pending_manual,
                facility_names=facility_names,
                facility_root_dir=self._vm.facility_root_dir,
                adapter=self._adapter,
                messagebox_fn=self._messagebox,
            )
            manual_results = dialog.get_results()

            self._vm.merge_manual_results(manual_results)
        except Exception as e:  # noqa: BLE001
            # 例外時は SHOWING_RESULT に復帰 (永久 BUSY 固着の防止)
            logger.warning(
                "manual distribution dialog failed: %s", type(e).__name__
            )
            # state を直接戻す (transition_to_showing_result は BUSY/MANUAL からのみ可、
            # ここでは MANUAL_DISTRIBUTING からの想定外復帰)
            self._vm.transition_to_showing_result(saved_result)
            self._messagebox.showerror(
                _TITLE_RUN_ERROR,
                f"手動振り分けダイアログを開けません: {type(e).__name__}",
            )

        # winfo_exists ガードで close 後の TclError を suppress
        if self._top.winfo_exists():
            self._redraw()

    def _show_config_missing_modal(self) -> None:
        if not self._vm.source_dir.exists():
            self._messagebox.showerror(_TITLE_CONFIG_MISSING, _MSG_SOURCE_MISSING)
        elif not self._vm.facility_root_dir.exists():
            self._messagebox.showerror(_TITLE_CONFIG_MISSING, _MSG_ROOT_MISSING)

    # ----- close 制御 -----

    def _on_close(self) -> None:
        if self._vm.is_busy:
            return  # 実行中は閉じない
        self._shutdown()
        with contextlib.suppress(tk.TclError):
            self._top.destroy()

    def _shutdown(self) -> None:
        try:
            self._executor.shutdown(wait=False, cancel_futures=True)
        except Exception as e:  # noqa: BLE001
            logger.warning("executor shutdown failed: %s", type(e).__name__)

    # ----- public (テスト用 / 呼び出し元の wait_window 用) -----

    @property
    def view_model(self) -> ExExtractorViewModel:
        return self._vm

    def get_toplevel(self) -> tk.Toplevel:
        """呼び出し元 (`__main__`) が ``wait_window`` で閉鎖を待つための Toplevel。"""
        return self._top
