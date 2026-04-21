"""ランチャー GUI（3 ボタン骨格 + Phase A 非同期実行）。

アプリ起動時にユーザーが最初に見る画面。3 ボタンを提供する:
1. PDF マージ処理を実行（コールバック DI、worker thread で非同期実行）
2. 確認待ちセッション（コールバック DI）
3. 設定（コールバック DI、未注入時はプレースホルダメッセージ）

設計方針:
- 全コールバックを DI で差替え可能（テスト容易性）
- 設定未完了時は ``on_config_missing`` を呼ぶ（PDF マージ処理押下時のみ）
- PII（氏名・パス）は logger に出さない
- Phase A 実行中は全ボタン disable + 2 回目クリック無視（Issue #62 / AC-L-2-Async, NoDouble）
- worker thread → main thread 遷移は ``root.after(0, ...)`` で安全に（Tk は main thread only）
"""

from __future__ import annotations

import concurrent.futures
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
_MSG_REVIEW_UNIMPL = "確認待ちセッション機能は後続タスクで実装予定です。"

_TITLE_SETTINGS_PLACEHOLDER = "設定画面（未実装）"
_MSG_SETTINGS_PLACEHOLDER = (
    "設定画面は後続タスクで実装予定です。\n"
    "現状は config/default.toml を直接編集してください。"
)

_TITLE_PHASE_A_DONE = "Phase A 完了"
_MSG_PHASE_A_DONE = (
    "PDF マージ処理（Phase A）が完了しました。\n"
    "確認待ちセッションがある場合は「確認待ちセッション」ボタンから処理してください。"
)
_TITLE_PHASE_A_ERROR = "Phase A 実行エラー"
_MSG_PHASE_A_ERROR_FMT = (
    "PDF マージ処理中にエラーが発生しました。\n"
    "詳細はログを確認してください。\n\n{type}"
)


def validate_config_ready(config: AppConfig) -> bool:
    """必須設定がすべて入力済みかチェック。

    必須: input_dir / output_dir / source_a_filename / ocr_backend.endpoint_url / api_key
    空白のみの入力は未設定扱い（TOML 編集ミス・コピペ事故を早期検出）。
    """
    required = (
        config.pdf_merge.input_dir,
        config.pdf_merge.output_dir,
        config.pdf_merge.source_a_filename,
        config.ocr_backend.endpoint_url,
        config.ocr_backend.api_key,
    )
    return all(bool(v.strip()) for v in required)


class Launcher:
    """3 ボタン構成のメインランチャー GUI。

    コールバック省略時は既定のプレースホルダメッセージを表示する。
    Phase A は worker thread で実行し、busy 中は全ボタン disable + 2 回目クリック無視。
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
        # Tk 既定は callback 例外を stderr に traceback 出力して mainloop 継続。
        # Phase A 統合時に OCR/ファイル I/O 例外が氏名・パスを含みうるため、
        # ConfirmDialog と同じく型名のみログに残し、UI には sanitized メッセージで通知する。
        self._root.report_callback_exception = self._on_callback_exception

        # Phase A 非同期実行用。max_workers=1 で Phase A の直列実行を保証
        # （Phase A は session lock で他プロセスとは競合しないが、同プロセス内の二重起動を防ぐ）。
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="phase-a"
        )
        self._busy = False
        self._current_future: concurrent.futures.Future[None] | None = None

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
            case _:
                raise ValueError(f"Unhandled LauncherAction: {action}")

    def run(self) -> None:
        """mainloop を起動する。"""
        try:
            self._root.mainloop()
        finally:
            # executor は run 終了時に必ず shutdown する（Daemon thread 化していないため
            # 残留すると Python プロセス終了を妨げる）
            self._executor.shutdown(wait=False, cancel_futures=True)
            if self._owns_root:
                with contextlib.suppress(tk.TclError):
                    self._root.destroy()

    def wait_until_idle(self, timeout: float) -> None:
        """実行中の Phase A が完了するまで待機する（テスト用）。

        ``_on_phase_a_done`` は ``root.after(0, ...)`` で main thread に
        再スケジュールされるため、呼出側は続けて ``root.update()`` を呼んで
        after コールバックを pump すること。
        """
        future = self._current_future
        if future is None:
            return
        with contextlib.suppress(concurrent.futures.TimeoutError):
            future.result(timeout=timeout)

    def _handle_run_pdf_merge(self) -> None:
        if self._busy:
            logger.info("PDF merge requested but launcher is busy; ignored")
            return

        if not validate_config_ready(self._config):
            logger.info("PDF merge requested but config is incomplete")
            if self._on_config_missing is not None:
                self._on_config_missing()
                return
            self._messagebox.showerror(_TITLE_CONFIG_MISSING, _MSG_CONFIG_MISSING)
            # AC-L-4「設定 GUI へ誘導」: エラーダイアログ確認後、設定アクションを続けて起動する。
            self.invoke_action(LauncherAction.OPEN_SETTINGS)
            return

        if self._on_run_pdf_merge is None:
            # Phase A コールバック未注入時は 13A 互換のプレースホルダ挙動を維持。
            self._messagebox.showinfo(
                _TITLE_UNIMPL,
                "PDF マージ処理の統合は後続タスクで実装予定です。",
            )
            return

        self._set_busy(True)
        callback = self._on_run_pdf_merge
        future = self._executor.submit(callback)
        self._current_future = future
        future.add_done_callback(self._schedule_phase_a_done)

    def _schedule_phase_a_done(
        self, future: concurrent.futures.Future[None]
    ) -> None:
        """worker thread → main thread 遷移（Tk は main thread 以外から触れない）。"""
        try:
            self._root.after(0, lambda: self._on_phase_a_done(future))
        except RuntimeError as e:
            # root が既に destroy 済みなら after は RuntimeError。PII 防御で型名のみ。
            logger.warning(
                "launcher after() failed after root destroy: %s", type(e).__name__
            )

    def _on_phase_a_done(
        self, future: concurrent.futures.Future[None]
    ) -> None:
        """Phase A 完了後処理（main thread で実行）。成功/失敗を通知しボタンを再有効化。"""
        self._set_busy(False)
        self._current_future = None
        try:
            future.result()
        except BaseException as exc:  # noqa: BLE001 — worker thread 例外は全種類を捕捉
            # PII 防御: logger には型名のみ（exc の message はパス/氏名を含みうる）。
            logger.error("phase A callback failed: %s", type(exc).__name__)
            self._messagebox.showerror(
                _TITLE_PHASE_A_ERROR,
                _MSG_PHASE_A_ERROR_FMT.format(type=type(exc).__name__),
            )
            return
        self._messagebox.showinfo(_TITLE_PHASE_A_DONE, _MSG_PHASE_A_DONE)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = ["disabled"] if busy else ["!disabled"]
        for btn in (self._btn_run, self._btn_review, self._btn_settings):
            btn.state(state)  # type: ignore[no-untyped-call]

    def _invoke_or_show(
        self, callback: Callable[[], None] | None, title: str, message: str
    ) -> None:
        """コールバックが注入されていれば呼ぶ、なければ showinfo でプレースホルダ表示。"""
        if callback is not None:
            callback()
        else:
            self._messagebox.showinfo(title, message)

    def _on_callback_exception(
        self,
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_tb: object,
    ) -> None:
        """Tk callback 内の未捕捉例外を fail-fast でハンドルする（PII 防御）。

        logger には型名のみを残す（exc_value は PDF パスや氏名を含みうる）。
        画面には sanitized なメッセージで通知し、ユーザーに ErrorDialog として示す。
        """
        logger.error("launcher callback exception: %s", exc_type.__name__)
        self._messagebox.showerror(
            "内部エラー",
            "処理中にエラーが発生しました。詳細はログを確認してください。\n\n"
            f"{exc_type.__name__}",
        )
