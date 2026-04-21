"""SessionPicker のユニットテスト（タスク 13C Phase 2）。

2 層構成（ConfirmDialog / SettingsDialog と同じ）:
  1. Pure logic: filter_pickable / format_entry （Tk 非依存）
  2. UI wiring: SessionPicker クラス（tk_required）

Launcher の「確認待ちセッション」ボタン押下から呼び出されるセッション選択モーダル。
NEEDS_REVIEW / READY_TO_MERGE の session_id を一覧表示し、選択結果を返す。
"""

from __future__ import annotations

import logging
import os
import tkinter as tk
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest

os.environ.setdefault("TK_SILENCE_DEPRECATION", "1")

from wiseman_hub.pdf.session import (  # noqa: E402
    PairStatus,
    Session,
    SessionStatus,
    UserCandidate,
)

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_session(
    session_id: str = "20260101T120000Z-abcd1234",
    status: SessionStatus = SessionStatus.NEEDS_REVIEW,
    *,
    source_a_path: str = "/tmp/A.pdf",
    user_name_ocr: str = "テスト",
) -> Session:
    now = datetime.now(UTC).isoformat()
    candidate = UserCandidate(
        page_index=1,
        user_name_ocr=user_name_ocr,
        confidence=0.9,
        matched_b_path=None,
        matched_c_path=None,
        status=PairStatus.NEEDS_CONFIRMATION,
    )
    return Session(
        session_id=session_id,
        status=status,
        created_at=now,
        updated_at=now,
        config_snapshot={"concat_order": ["A", "B", "C"]},
        source_a_path=source_a_path,
        candidates=[candidate],
        a_page_pdf_bytes_dir="/tmp/.pages",
        output_path=None,
        total_pages_a=1,
    )


@dataclass
class _FakeMessageBox:
    showinfo_calls: list[tuple[str, str]] = field(default_factory=list)
    showerror_calls: list[tuple[str, str]] = field(default_factory=list)
    askyesno_calls: list[tuple[str, str]] = field(default_factory=list)
    yesno_return: bool = True

    def showinfo(self, title: str, message: str) -> None:
        self.showinfo_calls.append((title, message))

    def showerror(self, title: str, message: str) -> None:
        self.showerror_calls.append((title, message))

    def askyesno(self, title: str, message: str) -> bool:
        self.askyesno_calls.append((title, message))
        return self.yesno_return


# ---------------------------------------------------------------------------
# Pure logic
# ---------------------------------------------------------------------------


class TestFilterPickable:
    """Launcher から呼ぶ目的（確認 UI + Phase B 実行）に合致する session のみ通す。"""

    def test_needs_review_passes(self) -> None:
        from wiseman_hub.ui.session_picker import filter_pickable

        s = _make_session(status=SessionStatus.NEEDS_REVIEW)
        assert filter_pickable([s]) == [s]

    def test_ready_to_merge_passes(self) -> None:
        from wiseman_hub.ui.session_picker import filter_pickable

        s = _make_session(status=SessionStatus.READY_TO_MERGE)
        assert filter_pickable([s]) == [s]

    def test_completed_rejected(self) -> None:
        from wiseman_hub.ui.session_picker import filter_pickable

        s = _make_session(status=SessionStatus.COMPLETED)
        assert filter_pickable([s]) == []

    def test_running_phase_a_rejected(self) -> None:
        from wiseman_hub.ui.session_picker import filter_pickable

        s = _make_session(status=SessionStatus.RUNNING_PHASE_A)
        assert filter_pickable([s]) == []

    def test_preserves_order(self) -> None:
        from wiseman_hub.ui.session_picker import filter_pickable

        s1 = _make_session(session_id="20260101T000000Z-aaaaaaaa")
        s2 = _make_session(session_id="20260102T000000Z-bbbbbbbb",
                          status=SessionStatus.READY_TO_MERGE)
        s3 = _make_session(session_id="20260103T000000Z-cccccccc",
                          status=SessionStatus.COMPLETED)
        assert filter_pickable([s1, s2, s3]) == [s1, s2]


class TestFormatEntry:
    """Listbox 表示用の文字列に PII が混入しない契約（氏名・パスは出さない）。"""

    def test_shows_session_id_and_status(self) -> None:
        from wiseman_hub.ui.session_picker import format_entry

        s = _make_session(
            session_id="20260101T120000Z-abcd1234",
            status=SessionStatus.NEEDS_REVIEW,
        )
        text = format_entry(s)
        assert "20260101T120000Z-abcd1234" in text
        assert "needs_review" in text

    def test_no_pii_in_entry(self) -> None:
        """氏名・A.pdf パスが Listbox 行に混入しないこと。"""
        from wiseman_hub.ui.session_picker import format_entry

        s = _make_session(
            session_id="20260101T120000Z-abcd1234",
            status=SessionStatus.NEEDS_REVIEW,
            source_a_path="/Users/secret/patient-山田太郎.pdf",
            user_name_ocr="山田太郎",
        )
        text = format_entry(s)
        assert "山田太郎" not in text
        assert "/Users/secret" not in text


# ---------------------------------------------------------------------------
# Tk wiring
# ---------------------------------------------------------------------------


_skip_if_no_tk = pytest.mark.tk_required


@pytest.fixture
def tk_root() -> object:
    import contextlib

    root = tk.Tk()
    root.withdraw()
    yield root
    with contextlib.suppress(tk.TclError):
        root.destroy()


@_skip_if_no_tk
class TestSessionPickerConstruction:
    def test_requires_parent(self, tk_root: tk.Tk) -> None:
        """parent なしで起動不可（Launcher 前提）。"""
        from wiseman_hub.ui.session_picker import SessionPicker

        with pytest.raises(TypeError):
            SessionPicker(sessions_dir=Path("/tmp/.sessions"))  # type: ignore[call-arg]

    def test_creates_toplevel(self, tk_root: tk.Tk) -> None:
        from wiseman_hub.ui.session_picker import SessionPicker

        picker = SessionPicker(
            sessions_dir=Path("/tmp/.sessions"),
            parent=tk_root,
            list_sessions_fn=lambda _p: [],
            load_session_fn=lambda _sid, sessions_dir: _make_session(),
            messagebox_fn=_FakeMessageBox(),
        )
        try:
            assert isinstance(picker._root, tk.Toplevel)
        finally:
            import contextlib as _cl

            with _cl.suppress(tk.TclError):
                picker._root.destroy()


@_skip_if_no_tk
class TestSessionPickerEmpty:
    """該当セッション 0 件の UX（showinfo でユーザーに通知してキャンセル扱い）。"""

    def test_empty_shows_info_and_returns_none(self, tk_root: tk.Tk) -> None:
        from wiseman_hub.ui.session_picker import SessionPicker

        mb = _FakeMessageBox()
        picker = SessionPicker(
            sessions_dir=Path("/tmp/.sessions"),
            parent=tk_root,
            list_sessions_fn=lambda _p: [],
            load_session_fn=lambda _sid, sessions_dir: _make_session(),
            messagebox_fn=mb,
        )
        result = picker.run()
        assert result.session_id is None
        assert len(mb.showinfo_calls) == 1


@_skip_if_no_tk
class TestSessionPickerLoadFailure:
    """load_session 失敗セッションはスキップしつつログに残す（PII 防御で型名のみ）。"""

    def test_broken_session_is_skipped(
        self, tk_root: tk.Tk, caplog: pytest.LogCaptureFixture
    ) -> None:
        from wiseman_hub.pdf.session import SessionCorruptedError
        from wiseman_hub.ui.session_picker import SessionPicker

        def _load(sid: str, *, sessions_dir: Path) -> Session:
            if sid == "bad":
                raise SessionCorruptedError("corrupted")
            return _make_session(session_id=sid)

        mb = _FakeMessageBox()
        with caplog.at_level(logging.WARNING):
            picker = SessionPicker(
                sessions_dir=Path("/tmp/.sessions"),
                parent=tk_root,
                list_sessions_fn=lambda _p: ["bad", "20260101T120000Z-abcd1234"],
                load_session_fn=_load,
                messagebox_fn=mb,
            )
        try:
            # 表示 entry は 1 件のみ
            assert picker._listbox.size() == 1
            # ログには型名のみ（"corrupted" の raw メッセージは出さない）
            assert "SessionCorruptedError" in caplog.text
            assert "corrupted" not in caplog.text
        finally:
            import contextlib as _cl

            with _cl.suppress(tk.TclError):
                picker._root.destroy()


@_skip_if_no_tk
class TestSessionPickerSelection:
    def test_cancel_returns_none(self, tk_root: tk.Tk) -> None:
        from wiseman_hub.ui.session_picker import SessionPicker

        picker = SessionPicker(
            sessions_dir=Path("/tmp/.sessions"),
            parent=tk_root,
            list_sessions_fn=lambda _p: ["20260101T120000Z-abcd1234"],
            load_session_fn=lambda sid, sessions_dir: _make_session(session_id=sid),
            messagebox_fn=_FakeMessageBox(),
        )
        try:
            picker._on_cancel()
            result = picker._result
            assert result.session_id is None
            assert result.status is None
        finally:
            import contextlib as _cl

            with _cl.suppress(tk.TclError):
                picker._root.destroy()

    def test_ok_without_selection_does_not_close(self, tk_root: tk.Tk) -> None:
        """Listbox 未選択で OK ボタン押下 → messagebox 警告 + dialog 継続。"""
        from wiseman_hub.ui.session_picker import SessionPicker

        mb = _FakeMessageBox()
        picker = SessionPicker(
            sessions_dir=Path("/tmp/.sessions"),
            parent=tk_root,
            list_sessions_fn=lambda _p: ["20260101T120000Z-abcd1234"],
            load_session_fn=lambda sid, sessions_dir: _make_session(session_id=sid),
            messagebox_fn=mb,
        )
        try:
            # 選択なしで _on_ok 呼出
            picker._on_ok()
            assert len(mb.showinfo_calls) >= 1  # 選択なし通知
            # dialog は閉じていない
            assert picker._root.winfo_exists()
        finally:
            import contextlib as _cl

            with _cl.suppress(tk.TclError):
                picker._root.destroy()

    def test_ok_with_selection_returns_session(self, tk_root: tk.Tk) -> None:
        from wiseman_hub.ui.session_picker import SessionPicker

        picker = SessionPicker(
            sessions_dir=Path("/tmp/.sessions"),
            parent=tk_root,
            list_sessions_fn=lambda _p: ["20260101T120000Z-abcd1234"],
            load_session_fn=lambda sid, sessions_dir: _make_session(
                session_id=sid, status=SessionStatus.READY_TO_MERGE
            ),
            messagebox_fn=_FakeMessageBox(),
        )
        try:
            picker._listbox.selection_set(0)
            picker._on_ok()
            result = picker._result
            assert result.session_id == "20260101T120000Z-abcd1234"
            assert result.status == SessionStatus.READY_TO_MERGE
        finally:
            import contextlib as _cl

            with _cl.suppress(tk.TclError):
                picker._root.destroy()
