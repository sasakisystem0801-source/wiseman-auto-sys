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
from tkinter import ttk
from typing import Final, Protocol

from wiseman_hub.config import AppConfig
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
        BUSY → SHOWING_RESULT (extract_directory 完了)
        BUSY → IDLE (例外時、エラーモーダル表示)
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
        """BUSY → IDLE (例外時、PII-safe メッセージのみ)。"""
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


# DI 用 type alias
ExtractFn = Callable[..., ExtractionResult]


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
        view_model: ExExtractorViewModel | None = None,
        extract_fn: ExtractFn | None = None,
        manual_dialog_factory: Callable[..., _ManualDialogProtocol] | None = None,
        messagebox_fn: MessageBoxLike | None = None,
    ) -> None:
        assert_main_thread("ExExtractorDialog")

        self._parent = parent
        self._config = config
        self._adapter = adapter
        self._extract_fn: ExtractFn = extract_fn or extract_directory
        self._manual_dialog_factory = manual_dialog_factory  # None なら遅延 import で default
        self._messagebox = messagebox_fn or default_messagebox()

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

        source_str = (
            str(self._vm.source_dir)
            if self._vm.source_dir.exists()
            else _LBL_NOT_SET
        )
        root_str = (
            str(self._vm.facility_root_dir)
            if self._vm.facility_root_dir.exists()
            else _LBL_NOT_SET
        )

        ttk.Label(path_frame, text=_LBL_SOURCE).grid(row=0, column=0, sticky="w")
        ttk.Label(
            path_frame, text=source_str, foreground="#444"
        ).grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Label(path_frame, text=_LBL_FACILITY_ROOT).grid(
            row=1, column=0, sticky="w"
        )
        ttk.Label(
            path_frame, text=root_str, foreground="#444"
        ).grid(row=1, column=1, sticky="w", padx=(8, 0))

        # 実行ボタン + ステータスラベル
        action_frame = ttk.Frame(outer)
        action_frame.pack(fill="x", pady=8)
        self._btn_run = ttk.Button(
            action_frame, text=_BTN_RUN, command=self._on_run_click
        )
        self._btn_run.pack(side="left")
        self._lbl_status = ttk.Label(action_frame, text="", foreground="#888")
        self._lbl_status.pack(side="left", padx=(12, 0))

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

        # ステータス文言
        if self._vm.state is UiState.BUSY:
            self._lbl_status.configure(text=_LBL_RUNNING, foreground="#0066cc")
        elif self._vm.error_message is not None:
            self._lbl_status.configure(
                text=f"エラー: {self._vm.error_message}", foreground="#c00"
            )
        else:
            self._lbl_status.configure(text="", foreground="#888")

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

        self._vm.transition_to_manual_distributing()
        self._redraw()

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
        facility_names = sorted(
            d.name
            for d in self._vm.facility_root_dir.iterdir()
            if d.is_dir() and not d.name.startswith("_")
        )

        dialog = factory(
            self._top,
            pending_items=self._vm.result.pending_manual,
            facility_names=facility_names,
            facility_root_dir=self._vm.facility_root_dir,
            adapter=self._adapter,
            messagebox_fn=self._messagebox,
        )
        manual_results = dialog.get_results()

        self._vm.merge_manual_results(manual_results)
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
