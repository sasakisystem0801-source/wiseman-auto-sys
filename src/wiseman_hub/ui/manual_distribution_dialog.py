"""手動振り分けダイアログ (PR4)。

``ExExtractorDialog`` の pending_manual 経由で起動され、AMBIGUOUS / UNMATCHED の
.ex_ ファイルを 1 件ずつ手動確定 + 抽出する。

UI 設計:
    - 1 件ずつ表示 (テーブル UI ではなく順次確定、誤選択防止)
    - AMBIGUOUS → resolve_result.candidates をプルダウン
    - UNMATCHED → 全 facility をプルダウン + 「スキップ」
    - 確定前の確認ステップ (filename + 選択先 + 出力先パスを表示、誤配布防止)
    - 既定選択は空 (先頭 facility が誤って選ばれることを防ぐ)
    - SFX 実行は worker thread (UI 凍結防止)

PR3 公開 API: ``extract_one(..., force_facility=...)`` で resolver を bypass。
``ResolveReason.MANUAL_OVERRIDE`` で「自動」と「手動」を結果上区別。

PII 保護方針 (ADR-014 準拠):
    - 本ダイアログ内では filename / 事業所名 / 候補リスト の表示は許容
      (運用者が手動確定するために必要)
    - logger 出力は filename + enum 値のみ
    - ダイアログ閉鎖後は親 ExExtractorDialog のサマリで件数のみ表示
"""

from __future__ import annotations

import contextlib
import logging
import tkinter as tk
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from tkinter import ttk
from typing import Final

from wiseman_hub.pdf.ex_extractor import (
    ExtractionItem,
    ExtractionStatus,
    SfxAdapter,
    extract_one,
)
from wiseman_hub.ui.common import (
    MessageBoxLike,
    assert_main_thread,
    default_messagebox,
    install_tk_exception_guard,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# UI 状態遷移
# ---------------------------------------------------------------------------


class ManualUiState(StrEnum):
    """ManualDistributionDialog の状態。

    遷移:
        SELECTING → CONFIRMING (「次へ」、選択あり)
        SELECTING → EXTRACTING (「スキップ」、UNMATCHED のみ)
        CONFIRMING → SELECTING (「戻る」)
        CONFIRMING → EXTRACTING (「確定」)
        EXTRACTING → SELECTING (次の item) または DONE (全件処理完了)
    """

    SELECTING = "selecting"
    CONFIRMING = "confirming"
    EXTRACTING = "extracting"
    DONE = "done"


# ---------------------------------------------------------------------------
# ViewModel (pure Python、テスト容易)
# ---------------------------------------------------------------------------


@dataclass
class ManualDistributionViewModel:
    """ManualDistributionDialog の状態管理。

    Attributes:
        pending_items: 入力 (AMBIGUOUS / UNMATCHED の item 群)
        facility_names: 振り分け先候補 (UNMATCHED のプルダウン用)
        facility_root_dir: 出力先パス組み立て用 (確認画面で表示)
        current_index: 処理中の item index (0-based)
        selected_facility: 現在選択中の facility (None = 未選択 / スキップ)
        state: UI 状態
        completed_results: 各 item の処理結果 (extract_one の戻り値 or skip 表示用)
        error_message: 直前の処理エラー (PII-safe enum 値)
    """

    pending_items: tuple[ExtractionItem, ...]
    facility_names: list[str]
    facility_root_dir: Path
    current_index: int = 0
    selected_facility: str | None = None
    state: ManualUiState = ManualUiState.SELECTING
    completed_results: list[ExtractionItem] = field(default_factory=list)
    error_message: str | None = None

    @property
    def current_item(self) -> ExtractionItem | None:
        """処理中の item (DONE なら None)。"""
        if self.current_index >= len(self.pending_items):
            return None
        return self.pending_items[self.current_index]

    @property
    def is_done(self) -> bool:
        return self.state is ManualUiState.DONE

    @property
    def remaining_count(self) -> int:
        return len(self.pending_items) - self.current_index

    @property
    def total_count(self) -> int:
        return len(self.pending_items)

    @property
    def candidate_options(self) -> list[str]:
        """現在 item の候補リスト (AMBIGUOUS = candidates、UNMATCHED = 全 facility)。"""
        item = self.current_item
        if item is None:
            return []
        if item.status is ExtractionStatus.SKIPPED_AMBIGUOUS:
            return list(item.resolve_result.candidates)
        if item.status is ExtractionStatus.SKIPPED_UNMATCHED:
            return list(self.facility_names)
        return []

    @property
    def is_unmatched(self) -> bool:
        """現在 item が UNMATCHED (= スキップボタンを表示する)。"""
        item = self.current_item
        return (
            item is not None
            and item.status is ExtractionStatus.SKIPPED_UNMATCHED
        )

    @property
    def can_confirm(self) -> bool:
        """「次へ」が押下可能か (SELECTING で facility 選択あり)。"""
        return (
            self.state is ManualUiState.SELECTING
            and self.selected_facility is not None
        )

    @property
    def can_skip(self) -> bool:
        """「スキップ」が押下可能か (SELECTING かつ UNMATCHED)。"""
        return self.state is ManualUiState.SELECTING and self.is_unmatched

    def select_facility(self, facility: str | None) -> None:
        """プルダウン選択を反映 (SELECTING でのみ有効)。"""
        if self.state is not ManualUiState.SELECTING:
            return
        # 空文字 / None は未選択扱い
        if facility is None or not facility.strip():
            self.selected_facility = None
            return
        # 候補リストに含まれない値は受け付けない (UI 不整合の防御)
        if facility not in self.candidate_options:
            return
        self.selected_facility = facility

    def transition_to_confirming(self) -> None:
        """SELECTING → CONFIRMING (選択ありで「次へ」)。"""
        if self.state is not ManualUiState.SELECTING:
            raise RuntimeError(f"cannot confirm from {self.state}")
        if self.selected_facility is None:
            raise RuntimeError("cannot confirm without selection")
        self.state = ManualUiState.CONFIRMING

    def back_to_selecting(self) -> None:
        """CONFIRMING → SELECTING (「戻る」)。"""
        if self.state is not ManualUiState.CONFIRMING:
            return
        self.state = ManualUiState.SELECTING

    def transition_to_extracting(self) -> None:
        """CONFIRMING → EXTRACTING (「確定」)。"""
        if self.state is not ManualUiState.CONFIRMING:
            raise RuntimeError(f"cannot extract from {self.state}")
        self.state = ManualUiState.EXTRACTING
        self.error_message = None

    def add_completed_and_advance(self, item: ExtractionItem) -> None:
        """EXTRACTING → 次 item の SELECTING (or 全件完了で DONE)。"""
        self.completed_results.append(item)
        self._advance_or_done()

    def skip_current(self) -> None:
        """SELECTING (UNMATCHED) → 元 item を skip 扱いで保持し次へ。"""
        if not self.can_skip:
            return
        item = self.current_item
        if item is not None:
            # skip は元 item をそのまま保持 (status は SKIPPED_UNMATCHED のまま)
            self.completed_results.append(item)
        self._advance_or_done()

    def fail_current_and_advance(
        self, item: ExtractionItem, error_message: str
    ) -> None:
        """EXTRACTING → 失敗 item を結果に積み次の item へ (例外パス)。"""
        self.completed_results.append(item)
        self.error_message = error_message
        self._advance_or_done()

    def _advance_or_done(self) -> None:
        self.current_index += 1
        self.selected_facility = None
        if self.current_index >= len(self.pending_items):
            self.state = ManualUiState.DONE
        else:
            self.state = ManualUiState.SELECTING


# ---------------------------------------------------------------------------
# UI 文言定数
# ---------------------------------------------------------------------------


_TITLE: Final[str] = "手動振り分け"

_BTN_NEXT: Final[str] = "次へ..."
_BTN_CONFIRM: Final[str] = "確定"
_BTN_BACK: Final[str] = "戻る"
_BTN_SKIP: Final[str] = "スキップ (この件は振り分けない)"
_BTN_CLOSE: Final[str] = "閉じる"

_LBL_PROGRESS_FMT: Final[str] = "{idx} / {total} 件目"
_LBL_FILENAME: Final[str] = "ファイル名:"
_LBL_SELECT_AMBIGUOUS: Final[str] = "候補から振り分け先を選択してください:"
_LBL_SELECT_UNMATCHED: Final[str] = (
    "全事業所から振り分け先を選択するか、スキップしてください:"
)
_LBL_CONFIRM_HEADER: Final[str] = "以下の内容で確定します。よろしいですか？"
_LBL_CONFIRM_FILENAME: Final[str] = "ファイル:"
_LBL_CONFIRM_DEST_FACILITY: Final[str] = "振り分け先事業所:"
_LBL_CONFIRM_DEST_PATH: Final[str] = "出力先パス:"
_LBL_EXTRACTING: Final[str] = "抽出中..."
_LBL_DONE: Final[str] = "全件処理完了。閉じてください。"

_TITLE_RUN_ERROR: Final[str] = "抽出エラー"

_SELECT_PLACEHOLDER: Final[str] = "(未選択)"


class ManualDistributionDialog:
    """手動振り分け Toplevel ダイアログ。

    pending_items を 1 件ずつ処理。確定前確認ステップで誤配布リスクを構造的に低減。
    """

    def __init__(
        self,
        parent: tk.Tk | tk.Toplevel | tk.Misc,
        *,
        pending_items: tuple[ExtractionItem, ...],
        facility_names: list[str],
        facility_root_dir: Path,
        adapter: SfxAdapter,
        view_model: ManualDistributionViewModel | None = None,
        extract_one_fn: Callable[..., ExtractionItem] | None = None,
        messagebox_fn: MessageBoxLike | None = None,
    ) -> None:
        assert_main_thread("ManualDistributionDialog")

        self._parent = parent
        self._adapter = adapter
        self._extract_one_fn = extract_one_fn or extract_one
        self._messagebox = messagebox_fn or default_messagebox()

        if view_model is None:
            view_model = ManualDistributionViewModel(
                pending_items=pending_items,
                facility_names=facility_names,
                facility_root_dir=facility_root_dir,
            )
        self._vm = view_model

        # 独立 executor (extract_one 中の UI 凍結防止、Codex MEDIUM-7)
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="manual-extract"
        )

        self._top = tk.Toplevel(parent)
        self._top.title(_TITLE)
        self._top.geometry("520x420")
        self._top.transient(parent)  # type: ignore[arg-type]
        self._top.grab_set()
        self._top.protocol("WM_DELETE_WINDOW", self._on_close)
        install_tk_exception_guard(
            self._top,
            component="manual_distribution",
            messagebox=self._messagebox,
        )

        # 入力が空なら即 DONE
        if not pending_items:
            self._vm.state = ManualUiState.DONE

        self._build_ui()
        self._redraw()

    # ----- UI 構築 -----

    def _build_ui(self) -> None:
        outer = ttk.Frame(self._top, padding=12)
        outer.pack(fill="both", expand=True)

        # 進捗
        self._lbl_progress = ttk.Label(
            outer, text="", font=("TkDefaultFont", 11, "bold")
        )
        self._lbl_progress.pack(anchor="w")

        # 動的フレーム (SELECTING / CONFIRMING で内容を切替)
        self._content_frame = ttk.Frame(outer, padding=(0, 8))
        self._content_frame.pack(fill="both", expand=True)

        # 下段ボタン
        self._bottom = ttk.Frame(outer)
        self._bottom.pack(fill="x", pady=(8, 0))

        self._btn_next = ttk.Button(
            self._bottom, text=_BTN_NEXT, command=self._on_next_click
        )
        self._btn_confirm = ttk.Button(
            self._bottom, text=_BTN_CONFIRM, command=self._on_confirm_click
        )
        self._btn_back = ttk.Button(
            self._bottom, text=_BTN_BACK, command=self._on_back_click
        )
        self._btn_skip = ttk.Button(
            self._bottom, text=_BTN_SKIP, command=self._on_skip_click
        )
        self._btn_close = ttk.Button(
            self._bottom, text=_BTN_CLOSE, command=self._on_close
        )

    def _redraw(self) -> None:
        """vm.state に基づき UI 再描画。"""
        # 既存 content をクリア
        for child in self._content_frame.winfo_children():
            child.destroy()
        # 既存ボタンを bottom から外す (再配置)
        for child in self._bottom.winfo_children():
            if isinstance(child, ttk.Button | ttk.Label | ttk.Frame):
                child.pack_forget()

        item = self._vm.current_item

        if self._vm.state is ManualUiState.DONE:
            self._lbl_progress.configure(text="完了")
            ttk.Label(self._content_frame, text=_LBL_DONE).pack(anchor="w")
            self._btn_close.pack(side="right")
            return

        progress = _LBL_PROGRESS_FMT.format(
            idx=self._vm.current_index + 1, total=self._vm.total_count
        )
        self._lbl_progress.configure(text=progress)

        if self._vm.state is ManualUiState.EXTRACTING:
            ttk.Label(
                self._content_frame, text=_LBL_EXTRACTING, foreground="#0066cc"
            ).pack(anchor="w")
            return

        if self._vm.state is ManualUiState.SELECTING:
            self._build_selecting_view(item)
            self._btn_next.configure(
                state="normal" if self._vm.can_confirm else "disabled"
            )
            self._btn_next.pack(side="left")
            if self._vm.can_skip:
                self._btn_skip.pack(side="left", padx=(8, 0))
            self._btn_close.pack(side="right")
            return

        if self._vm.state is ManualUiState.CONFIRMING:
            self._build_confirming_view(item)
            self._btn_back.pack(side="left")
            self._btn_confirm.pack(side="left", padx=(8, 0))
            self._btn_close.pack(side="right")
            return

    def _build_selecting_view(self, item: ExtractionItem | None) -> None:
        if item is None:
            return
        # filename
        ttk.Label(
            self._content_frame, text=_LBL_FILENAME, foreground="#444"
        ).pack(anchor="w")
        ttk.Label(
            self._content_frame,
            text=item.source_path.name,
            font=("TkDefaultFont", 10, "bold"),
        ).pack(anchor="w", pady=(0, 8))

        # ラベル
        label_text = (
            _LBL_SELECT_UNMATCHED
            if self._vm.is_unmatched
            else _LBL_SELECT_AMBIGUOUS
        )
        ttk.Label(self._content_frame, text=label_text).pack(anchor="w")

        # プルダウン (既定値は空、Codex HIGH-3)
        options = [_SELECT_PLACEHOLDER, *self._vm.candidate_options]
        self._combo_var = tk.StringVar(
            value=self._vm.selected_facility or _SELECT_PLACEHOLDER
        )
        combo = ttk.Combobox(
            self._content_frame,
            textvariable=self._combo_var,
            values=options,
            state="readonly",
            width=40,
        )
        combo.pack(anchor="w", pady=(4, 0))
        combo.bind("<<ComboboxSelected>>", self._on_combo_changed)

    def _build_confirming_view(self, item: ExtractionItem | None) -> None:
        if item is None:
            return
        facility = self._vm.selected_facility
        if facility is None:
            return

        ttk.Label(
            self._content_frame,
            text=_LBL_CONFIRM_HEADER,
            font=("TkDefaultFont", 10, "bold"),
            foreground="#c60",
        ).pack(anchor="w", pady=(0, 8))

        for label, value in (
            (_LBL_CONFIRM_FILENAME, item.source_path.name),
            (_LBL_CONFIRM_DEST_FACILITY, facility),
            (
                _LBL_CONFIRM_DEST_PATH,
                str(self._vm.facility_root_dir / facility),
            ),
        ):
            row = ttk.Frame(self._content_frame)
            row.pack(anchor="w", fill="x", pady=2)
            ttk.Label(row, text=label, foreground="#444", width=18).pack(
                side="left"
            )
            ttk.Label(row, text=value, font=("TkDefaultFont", 10, "bold")).pack(
                side="left"
            )

    # ----- イベントハンドラ -----

    def _on_combo_changed(self, _event: object = None) -> None:
        value = self._combo_var.get()
        if value == _SELECT_PLACEHOLDER:
            self._vm.select_facility(None)
        else:
            self._vm.select_facility(value)
        self._redraw()

    def _on_next_click(self) -> None:
        if not self._vm.can_confirm:
            return
        self._vm.transition_to_confirming()
        self._redraw()

    def _on_back_click(self) -> None:
        self._vm.back_to_selecting()
        self._redraw()

    def _on_confirm_click(self) -> None:
        item = self._vm.current_item
        if item is None or self._vm.selected_facility is None:
            return
        facility = self._vm.selected_facility

        try:
            self._vm.transition_to_extracting()
        except RuntimeError as e:
            logger.warning("invalid state transition: %s", type(e).__name__)
            return
        self._redraw()

        future = self._executor.submit(
            self._run_extract_one, item, facility
        )
        future.add_done_callback(
            lambda f: self._top.after(0, self._on_extract_done, f, item)
        )

    def _run_extract_one(
        self, item: ExtractionItem, facility: str
    ) -> ExtractionItem:
        return self._extract_one_fn(
            item.source_path,
            self._vm.facility_root_dir,
            self._vm.facility_names,
            {},  # 手動 override では aliases 不要 (resolver bypass)
            self._adapter,
            force_facility=facility,
        )

    def _on_extract_done(
        self,
        future: Future[ExtractionItem],
        original_item: ExtractionItem,
    ) -> None:
        try:
            new_item = future.result()
        except Exception as e:  # noqa: BLE001
            # PII 防御で型名のみ
            error_type = type(e).__name__
            logger.warning(
                "manual extract failed for %s: %s",
                original_item.source_path.name,
                error_type,
            )
            self._vm.fail_current_and_advance(original_item, error_type)
            self._redraw()
            self._messagebox.showerror(
                _TITLE_RUN_ERROR,
                f"抽出中にエラーが発生しました: {error_type}",
            )
            return

        self._vm.add_completed_and_advance(new_item)
        self._redraw()

    def _on_skip_click(self) -> None:
        if not self._vm.can_skip:
            return
        self._vm.skip_current()
        self._redraw()

    def _on_close(self) -> None:
        if self._vm.state is ManualUiState.EXTRACTING:
            return  # 抽出中は閉じない
        # 未処理 item は元の SKIPPED_* status のまま結果に積む
        while self._vm.current_index < len(self._vm.pending_items):
            item = self._vm.pending_items[self._vm.current_index]
            self._vm.completed_results.append(item)
            self._vm.current_index += 1
        self._vm.state = ManualUiState.DONE
        self._shutdown()
        with contextlib.suppress(tk.TclError):
            self._top.destroy()

    def _shutdown(self) -> None:
        try:
            self._executor.shutdown(wait=False, cancel_futures=True)
        except Exception as e:  # noqa: BLE001
            logger.warning("executor shutdown failed: %s", type(e).__name__)

    # ----- public (ExExtractorDialog から取得) -----

    def get_results(self) -> tuple[ExtractionItem, ...]:
        """全 pending_item の処理結果を返す (DONE 状態想定)。

        確定したものは extract_one 戻り値、skip / 未処理は元 item をそのまま返す。
        親 ExExtractorDialog が ``merge_manual_results`` で source_path 一致で統合する。
        """
        # まだ DONE でなければ wait_window で待つ (テストでは fake で即返却)
        if self._vm.state is not ManualUiState.DONE:
            self._top.wait_window()
        return tuple(self._vm.completed_results)

    @property
    def view_model(self) -> ManualDistributionViewModel:
        return self._vm
