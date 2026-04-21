"""SessionPicker: NEEDS_REVIEW / READY_TO_MERGE セッション選択モーダル（タスク 13C Phase 2）。

Launcher の「確認待ちセッション」ボタン押下から呼び出される。sessions_dir を列挙し、
Phase B に進められる session（NEEDS_REVIEW or READY_TO_MERGE）をリスト表示して
選択させる。

設計方針:
- Toplevel + grab_set で必ずモーダル（Launcher 前提、parent 必須）
- list_sessions / load_session は DI でテスト差替え可能
- PII 防御: ログ / Listbox 表示とも session_id + status のみ、氏名・パスは出さない
- broken session（SessionCorruptedError）は warning で skip、一覧に表示しない
- 空リスト時は showinfo で通知して即キャンセル
"""

from __future__ import annotations

import contextlib
import logging
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tkinter import ttk

from wiseman_hub.pdf.session import (
    Session,
    SessionCorruptedError,
    SessionNotFoundError,
    SessionStatus,
    list_sessions,
    load_session,
)
from wiseman_hub.ui.common import (
    MessageBoxLike,
    assert_main_thread,
    default_messagebox,
    install_tk_exception_guard,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


_PICKABLE_STATUSES: frozenset[SessionStatus] = frozenset(
    {SessionStatus.NEEDS_REVIEW, SessionStatus.READY_TO_MERGE}
)


@dataclass(frozen=True)
class SessionPickerResult:
    """選択結果。``session_id is None`` がキャンセル（selected プロパティ参照推奨）。"""

    session_id: str | None = None
    status: SessionStatus | None = None

    @property
    def selected(self) -> bool:
        return self.session_id is not None


# ---------------------------------------------------------------------------
# Pure logic（Tk 非依存）
# ---------------------------------------------------------------------------


def filter_pickable(sessions: list[Session]) -> list[Session]:
    """Phase B に進めるステータス（NEEDS_REVIEW / READY_TO_MERGE）のみ残す。"""
    return [s for s in sessions if s.status in _PICKABLE_STATUSES]


def format_entry(session: Session) -> str:
    """Listbox 1 行の表示文字列。PII（氏名・パス）は絶対に含めない。"""
    return f"{session.session_id} [{session.status.value}]"


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------


ListSessionsFn = Callable[[Path], list[str]]
LoadSessionFn = Callable[..., Session]


def _default_list_sessions(sessions_dir: Path) -> list[str]:
    return list_sessions(sessions_dir=sessions_dir)


def _default_load_session(session_id: str, *, sessions_dir: Path) -> Session:
    return load_session(session_id, sessions_dir=sessions_dir)


# ---------------------------------------------------------------------------
# SessionPicker
# ---------------------------------------------------------------------------


_TITLE_NO_SESSIONS = "確認待ちセッションなし"
_MSG_NO_SESSIONS = (
    "確認待ち / 結合待ちのセッションはありません。\n"
    "先に「PDF マージ処理を実行」からセッションを作成してください。"
)
_TITLE_NO_SELECTION = "選択してください"
_MSG_NO_SELECTION = "リストからセッションを選択してください。"
_TITLE_WINDOW = "セッション選択"


class SessionPicker:
    """Launcher から呼び出されるセッション選択モーダル。

    parent 必須（Launcher 前提）。内部で ``Toplevel`` を生成し、呼出側の ``run()``
    終了までブロックする（``wait_window``）。
    """

    def __init__(
        self,
        *,
        sessions_dir: Path,
        parent: tk.Misc,
        list_sessions_fn: ListSessionsFn = _default_list_sessions,
        load_session_fn: LoadSessionFn = _default_load_session,
        messagebox_fn: MessageBoxLike | None = None,
    ) -> None:
        assert_main_thread("SessionPicker")

        self._sessions_dir = sessions_dir
        self._list_sessions_fn = list_sessions_fn
        self._load_session_fn = load_session_fn
        self._messagebox = messagebox_fn or default_messagebox()

        toplevel = tk.Toplevel(parent)
        toplevel.transient(parent)  # type: ignore[call-overload]
        toplevel.grab_set()
        # 空リスト時のフラッシュ（一瞬ウィンドウが表示されて即消える）を防ぐため、
        # 構築直後は withdraw し、run() で非空を確認してから deiconify する。
        toplevel.withdraw()
        self._root = toplevel

        install_tk_exception_guard(
            self._root, component="session_picker", messagebox=self._messagebox
        )

        self._result = SessionPickerResult()
        self._sessions: list[Session] = self._load_pickable_sessions()

        self._build_ui()

    # -- session loading ----------------------------------------------------

    def _load_pickable_sessions(self) -> list[Session]:
        """sessions_dir を列挙し、NEEDS_REVIEW / READY_TO_MERGE のみ返す。

        load_session 失敗（corrupted / not found / OSError）は warning で skip。
        PII 防御: ログに出るのは session_id + 例外型名のみ。
        """
        loaded: list[Session] = []
        for session_id in self._list_sessions_fn(self._sessions_dir):
            try:
                session = self._load_session_fn(
                    session_id, sessions_dir=self._sessions_dir
                )
            except (SessionCorruptedError, SessionNotFoundError, OSError) as e:
                logger.warning(
                    "session %s load failed (skipping from picker): %s",
                    session_id,
                    type(e).__name__,
                )
                continue
            loaded.append(session)
        return filter_pickable(loaded)

    # -- UI construction ----------------------------------------------------

    def _build_ui(self) -> None:
        root = self._root
        root.title(_TITLE_WINDOW)
        root.geometry("520x360")
        root.protocol("WM_DELETE_WINDOW", self._on_cancel)

        ttk.Label(
            root,
            text="実行対象のセッションを選択してください:",
            padding=(10, 8),
            anchor="w",
        ).pack(fill="x")

        list_frame = ttk.Frame(root, padding=(10, 0))
        list_frame.pack(fill="both", expand=True)

        self._listbox = tk.Listbox(list_frame, selectmode=tk.SINGLE, exportselection=0)
        self._listbox.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(
            list_frame, orient="vertical", command=self._listbox.yview
        )
        scroll.pack(side="right", fill="y")
        self._listbox.configure(yscrollcommand=scroll.set)
        self._listbox.bind("<Double-Button-1>", lambda _e: self._on_ok())

        for session in self._sessions:
            self._listbox.insert(tk.END, format_entry(session))

        btn_frame = ttk.Frame(root, padding=10)
        btn_frame.pack(fill="x")
        self._btn_ok = ttk.Button(btn_frame, text="選択", command=self._on_ok)
        self._btn_cancel = ttk.Button(
            btn_frame, text="キャンセル", command=self._on_cancel
        )
        self._btn_ok.pack(side="right", padx=(6, 0))
        self._btn_cancel.pack(side="right")

    # -- Public entry -------------------------------------------------------

    def run(self) -> SessionPickerResult:
        """wait_window で閉じるまで block。空リスト時は即通知してキャンセル扱い。

        __init__ で withdraw 済みなので、空リスト時は UI 表示を全く行わず showinfo
        のみ出して終了する（Toplevel フラッシュ回避）。
        """
        if not self._sessions:
            self._messagebox.showinfo(_TITLE_NO_SESSIONS, _MSG_NO_SESSIONS)
            self._close_dialog()
            return self._result
        # 非空時のみウィンドウを表示
        with contextlib.suppress(tk.TclError):
            self._root.deiconify()
        try:
            self._root.wait_window()
        finally:
            with contextlib.suppress(tk.TclError):
                self._root.destroy()
        return self._result

    # -- handlers -----------------------------------------------------------

    def _on_ok(self) -> None:
        selection = self._listbox.curselection()  # type: ignore[no-untyped-call]
        if not selection:
            self._messagebox.showinfo(_TITLE_NO_SELECTION, _MSG_NO_SELECTION)
            return
        index = int(selection[0])
        session = self._sessions[index]
        self._result = SessionPickerResult(
            session_id=session.session_id, status=session.status
        )
        self._close_dialog()

    def _on_cancel(self) -> None:
        self._result = SessionPickerResult()
        self._close_dialog()

    def _close_dialog(self) -> None:
        """Toplevel を閉じる（親 mainloop は継続）。"""
        with contextlib.suppress(tk.TclError):
            self._root.destroy()
