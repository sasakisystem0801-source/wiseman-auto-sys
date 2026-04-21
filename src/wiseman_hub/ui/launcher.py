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
import time
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import ttk

from wiseman_hub.config import AppConfig
from wiseman_hub.ui.common import assert_main_thread, install_tk_exception_guard
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
        install_tk_exception_guard(
            self._root, component="launcher", messagebox=self._messagebox
        )

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

    def reload_config(self, config: AppConfig) -> None:
        """設定 GUI で保存された直後に呼ぶ。以降の ``validate_config_ready`` 判定が新値で行われる。"""
        self._config = config

    def get_root(self) -> tk.Tk:
        """子ダイアログ（SettingsDialog など）が ``tk.Toplevel(parent)`` で
        モーダル化するための親 widget を返す。"""
        return self._root

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
            self._shutdown_executor()
            if self._owns_root:
                with contextlib.suppress(tk.TclError):
                    self._root.destroy()

    def __del__(self) -> None:
        # ``run()`` を呼ばずに Launcher インスタンスが破棄されるパス（テストで
        # __init__ 後に root.destroy() で抜ける等）向けのベストエフォート cleanup。
        # CPython の __del__ はインタプリタ終了時や循環参照検出時に呼ばれない
        # ことがあるため、本番経路では ``run()`` の finally で shutdown を行うこと。
        self._shutdown_executor()

    def _shutdown_executor(self) -> None:
        executor = getattr(self, "_executor", None)
        if executor is None:
            return
        try:
            executor.shutdown(wait=False, cancel_futures=True)
        except Exception as e:  # noqa: BLE001 — GC / double-shutdown パスでも落とさない
            # PII 防御で型名のみ。二重 shutdown で ``RuntimeError`` が出ても続行可能。
            logger.warning("executor shutdown failed: %s", type(e).__name__)

    def wait_until_idle(self, timeout: float) -> None:
        """実行中の Phase A が完了し、完了処理が main thread で pump されるまで待機する（テスト用）。

        順序保証（CPython の concurrent.futures 実装に基づく）::

            1. worker thread: callback 完了 → ``future.set_result()``
            2. worker thread: ``set_result`` 直後に同一 worker thread で ``_invoke_callbacks``
               が走り、``add_done_callback`` で登録した ``_schedule_phase_a_done`` を呼ぶ
               → ``root.after(0, _on_phase_a_done, future)`` で Tk queue に enqueue
            3. main thread: ``future.result(timeout)`` から return
            4. main thread: ``while self._busy: root.update()`` で enqueue された
               ``_on_phase_a_done`` を pump → ``_set_busy(False)``

        ``_busy`` フラグが ``_on_phase_a_done`` 内で False に落ちるまで pump を継続する
        ため、enqueue と pump の race は ``deadline`` まで吸収される。
        """
        future = self._current_future
        if future is None:
            return
        deadline = time.monotonic() + timeout
        with contextlib.suppress(concurrent.futures.TimeoutError):
            future.result(timeout=timeout)
        while self._busy and time.monotonic() < deadline:
            with contextlib.suppress(tk.TclError):
                self._root.update()
            time.sleep(0.01)

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
            # コールバック未注入時のプレースホルダ（テスト環境や未統合状態のみ発生）。
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
            self._root.after(0, self._on_phase_a_done, future)
        except (RuntimeError, tk.TclError) as e:
            # root が既に destroy 済みなら after は RuntimeError / TclError。
            # 通知先の UI は消失しているが、future の結果/例外をロスせず型名だけでも
            # ログに残して silent failure を防ぐ（PII 防御で exception message は除外）。
            logger.warning(
                "launcher after() failed after root destroy: %s", type(e).__name__
            )
            exc = future.exception()
            if exc is not None:
                logger.error(
                    "phase A callback failed (root destroyed): %s",
                    type(exc).__name__,
                )

    def _on_phase_a_done(
        self, future: concurrent.futures.Future[None]
    ) -> None:
        """Phase A 完了後処理（main thread で実行）。成功/失敗を通知しボタンを再有効化。

        ``_set_busy(False)`` は ``future.result()`` より先に呼ぶ。例外が raise される
        ケースでも必ずボタンを再有効化するための意図的な順序（変更禁止）。
        """
        self._set_busy(False)
        self._current_future = None
        try:
            future.result()
        except Exception as exc:
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

