"""ランチャー GUI（3 ボタン骨格）。

アプリ起動時にユーザーが最初に見る画面。3 ボタンを提供する:
1. PDF マージ処理を実行（コールバック DI）
2. 確認待ちセッション（コールバック DI）
3. 設定（コールバック DI、未注入時はプレースホルダメッセージ）

設計方針:
- 全コールバックを DI で差替え可能（テスト容易性）
- 設定未完了時は ``on_config_missing`` を呼ぶ（PDF マージ処理押下時のみ）
- PII（氏名・パス）は logger に出さない
"""

from __future__ import annotations

import contextlib
import enum
import logging
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import ttk

from wiseman_hub.config import AppConfig
from wiseman_hub.ui.common import assert_main_thread
from wiseman_hub.ui.confirm_dialog import MessageBoxLike, default_messagebox

logger = logging.getLogger(__name__)


class LauncherAction(enum.Enum):
    """ランチャーの 3 つの主要操作。"""

    RUN_PDF_MERGE = "run_pdf_merge"
    OPEN_REVIEW = "open_review"
    OPEN_SETTINGS = "open_settings"


_BTN_RUN_PDF_MERGE = "PDF マージ処理を実行"
_BTN_OPEN_REVIEW = "確認待ちセッション"
_BTN_OPEN_SETTINGS = "設定"

_TITLE_CONFIG_MISSING = "設定が未完了"
_MSG_CONFIG_MISSING = (
    "必要な設定が未入力です。\n\n"
    "入力フォルダ / 出力フォルダ / A.pdf ファイル名 / OCR エンドポイント / OCR API キー "
    "のすべてを「設定」画面から入力してください。"
)

_TITLE_UNIMPL = "未実装"
_MSG_PDF_MERGE_UNIMPL = "PDF マージ処理の統合は後続タスクで実装予定です。"
_MSG_REVIEW_UNIMPL = "確認待ちセッション機能は後続タスクで実装予定です。"

_TITLE_SETTINGS_PLACEHOLDER = "設定画面（未実装）"
_MSG_SETTINGS_PLACEHOLDER = (
    "設定画面は後続タスクで実装予定です。\n"
    "現状は config/default.toml を直接編集してください。"
)


def validate_config_ready(config: AppConfig) -> bool:
    """必須設定がすべて入力済みかチェック。

    必須: input_dir / output_dir / source_a_filename / ocr_backend.endpoint_url / api_key
    """
    return bool(
        config.pdf_merge.input_dir
        and config.pdf_merge.output_dir
        and config.pdf_merge.source_a_filename
        and config.ocr_backend.endpoint_url
        and config.ocr_backend.api_key
    )


class Launcher:
    """3 ボタン構成のメインランチャー GUI。

    コールバック省略時は既定のプレースホルダメッセージを表示する。
    """

    def __init__(
        self,
        config: AppConfig,
        config_path: Path,
        *,
        root: tk.Tk | None = None,
        on_run_pdf_merge: Callable[[], None] | None = None,
        on_open_review: Callable[[], None] | None = None,
        on_open_settings: Callable[[], None] | None = None,
        on_config_missing: Callable[[], None] | None = None,
        messagebox_fn: MessageBoxLike | None = None,
    ) -> None:
        assert_main_thread("Launcher")

        self._config = config
        self._config_path = config_path
        self._messagebox = messagebox_fn or default_messagebox()

        self._on_run_pdf_merge = on_run_pdf_merge
        self._on_open_review = on_open_review
        self._on_open_settings = on_open_settings
        self._on_config_missing = on_config_missing

        self._owns_root = root is None
        self._root = root if root is not None else tk.Tk()

        self._build_ui()

    def _build_ui(self) -> None:
        root = self._root
        root.title("Wiseman PDF ツール")
        root.geometry("420x280")

        ttk.Label(
            root,
            text="Wiseman PDF ツール",
            font=("TkDefaultFont", 14, "bold"),
            padding=12,
        ).pack()

        btn_frame = ttk.Frame(root, padding=12)
        btn_frame.pack(fill="both", expand=True)

        self._btn_run = ttk.Button(
            btn_frame,
            text=_BTN_RUN_PDF_MERGE,
            command=lambda: self.invoke_action(LauncherAction.RUN_PDF_MERGE),
        )
        self._btn_review = ttk.Button(
            btn_frame,
            text=_BTN_OPEN_REVIEW,
            command=lambda: self.invoke_action(LauncherAction.OPEN_REVIEW),
        )
        self._btn_settings = ttk.Button(
            btn_frame,
            text=_BTN_OPEN_SETTINGS,
            command=lambda: self.invoke_action(LauncherAction.OPEN_SETTINGS),
        )

        for btn in (self._btn_run, self._btn_review, self._btn_settings):
            btn.pack(fill="x", pady=6, ipady=6)

    def button_labels(self) -> tuple[str, str, str]:
        """各ボタンのラベル（テスト用）。"""
        return (_BTN_RUN_PDF_MERGE, _BTN_OPEN_REVIEW, _BTN_OPEN_SETTINGS)

    def invoke_action(self, action: LauncherAction) -> None:
        """指定アクションのハンドラを実行する（ボタン押下と同等）。"""
        match action:
            case LauncherAction.RUN_PDF_MERGE:
                self._handle_run_pdf_merge()
            case LauncherAction.OPEN_REVIEW:
                self._invoke_or_show(
                    self._on_open_review, _TITLE_UNIMPL, _MSG_REVIEW_UNIMPL
                )
            case LauncherAction.OPEN_SETTINGS:
                self._invoke_or_show(
                    self._on_open_settings,
                    _TITLE_SETTINGS_PLACEHOLDER,
                    _MSG_SETTINGS_PLACEHOLDER,
                )

    def run(self) -> None:
        """mainloop を起動する。"""
        try:
            self._root.mainloop()
        finally:
            if self._owns_root:
                with contextlib.suppress(tk.TclError):
                    self._root.destroy()

    def _handle_run_pdf_merge(self) -> None:
        if not validate_config_ready(self._config):
            logger.info("PDF merge requested but config is incomplete")
            if self._on_config_missing is not None:
                self._on_config_missing()
            else:
                self._messagebox.showerror(_TITLE_CONFIG_MISSING, _MSG_CONFIG_MISSING)
            return

        self._invoke_or_show(
            self._on_run_pdf_merge, _TITLE_UNIMPL, _MSG_PDF_MERGE_UNIMPL
        )

    def _invoke_or_show(
        self, callback: Callable[[], None] | None, title: str, message: str
    ) -> None:
        """コールバックが注入されていれば呼ぶ、なければ showinfo でプレースホルダ表示。"""
        if callback is not None:
            callback()
        else:
            self._messagebox.showinfo(title, message)
