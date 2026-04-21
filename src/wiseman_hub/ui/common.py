"""UI モジュール共通ヘルパ（最下層、他の ui モジュールから参照される土台）。"""

from __future__ import annotations

import logging
import re
import threading
from tkinter import messagebox as _tk_messagebox
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import tkinter as tk

logger = logging.getLogger(__name__)


_TITLE_INTERNAL_ERROR = "内部エラー"
_MSG_INTERNAL_ERROR_FMT = (
    "処理中にエラーが発生しました。詳細はログを確認してください。\n\n{type}"
)

# ログ grep 可読性維持のため component ラベルは空白・制御文字・空文字を禁止。
# snake_case / session_<id> 等を想定。
_COMPONENT_INVALID = re.compile(r"\s")


def assert_main_thread(component_name: str) -> None:
    """Tk は main thread でしか安全に使えないため、worker thread からの生成を fail-fast で拒否する。

    Tkinter（filedialog / messagebox / mainloop）は非 main thread から呼び出すと
    Windows 本番でハング / TclError を起こしうる。
    """
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError(
            f"{component_name} must be instantiated on the main thread "
            "(tkinter is not thread-safe)"
        )


class MessageBoxLike(Protocol):
    """``tkinter.messagebox`` の最小インターフェース（DI 用）。

    ui 配下の Launcher / ConfirmDialog / SettingsDialog / SessionPicker (13C) が共通で依存する
    Protocol。structural subtyping により任意の fake / mock を注入可能。
    """

    def askyesno(self, title: str, message: str) -> bool: ...

    def showinfo(self, title: str, message: str) -> None: ...

    def showerror(self, title: str, message: str) -> None: ...


class _DefaultMessageBox:
    """``tkinter.messagebox`` をそのまま使う実装。"""

    def askyesno(self, title: str, message: str) -> bool:
        return bool(_tk_messagebox.askyesno(title, message))

    def showinfo(self, title: str, message: str) -> None:
        _tk_messagebox.showinfo(title, message)

    def showerror(self, title: str, message: str) -> None:
        _tk_messagebox.showerror(title, message)


def default_messagebox() -> MessageBoxLike:
    """``tkinter.messagebox`` を使う既定実装を返す（ui モジュール共通）。"""
    return _DefaultMessageBox()


def install_tk_exception_guard(
    root: tk.Misc,
    *,
    component: str,
    messagebox: MessageBoxLike,
) -> None:
    """Tk callback 内の未捕捉例外を PII 防御付きで捕捉する guard を ``root`` にインストールする。

    Tk は `command=` や `bind` で登録した callback 内で raise された例外を握り潰さず
    stderr にダンプするが、例外文字列には PDF パス・利用者氏名などの PII が混入しうる。
    本 guard は ``report_callback_exception`` に差し替え、以下を保証する:

    - ログ: ``exc_type.__name__`` のみ（``exc_value`` の str は出さない）
    - 画面: ``messagebox.showerror`` で sanitized メッセージ（型名のみ）
    - 二次失敗: ``showerror`` 自体が失敗（root destroy 後等）しても warning で握り潰し

    :param component: ログ集計用のラベル。snake_case、空白・空文字禁止
        （grep 可読性維持のため実行時 validation あり）。例: ``"launcher"``,
        ``"settings"``, ``"session_picker"``, ``"session_<id>"``。
    :param messagebox: ``showerror`` のみが呼ばれる。DI により
        ``tkinter.messagebox`` を差替え可能（テスト容易性）。

    launcher / settings / SessionPicker (13C) で共通利用する。confirm_dialog は
    session_id 付加・aborted フラグ・quit 副作用があるため本 guard の対象外。
    """
    if not component or _COMPONENT_INVALID.search(component):
        raise ValueError(
            f"component must be non-empty and contain no whitespace "
            f"(got {component!r})"
        )

    def _handler(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_tb: object,
    ) -> None:
        logger.error("%s callback exception: %s", component, exc_type.__name__)
        try:
            messagebox.showerror(
                _TITLE_INTERNAL_ERROR,
                _MSG_INTERNAL_ERROR_FMT.format(type=exc_type.__name__),
            )
        except Exception as e:  # noqa: BLE001 — 二次 showerror 失敗は握り潰し可
            logger.warning(
                "%s showerror failed during callback exception: %s",
                component,
                type(e).__name__,
            )

    # tkinter の stub は report_callback_exception を公開していないが、
    # 実体は Tk / Toplevel で動的に読まれる公式 API（Python docs: Tk.report_callback_exception）。
    root.report_callback_exception = _handler  # type: ignore[attr-defined]
