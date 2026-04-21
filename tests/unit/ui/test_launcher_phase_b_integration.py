"""タスク 13C Phase 3: Launcher ↔ 確認 UI / Phase B 統合テスト。

AC-L-3: 「確認待ちセッション」ボタン → `on_open_review` (main thread) 呼出 →
        session_id が返れば `on_run_phase_b` を worker thread で実行。
AC-L-3-Async: Phase B 実行中も mainloop 応答（Phase A と同じ worker thread パターン）。
AC-L-3-Done: 完了時に出力 PDF パス通知、失敗時は型名のみ通知（PII 防御）。
AC-L-3-NoSel: `on_open_review` が None 返却（cancel）時は Phase B スキップ + busy 解除。
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

import pytest

os.environ.setdefault("TK_SILENCE_DEPRECATION", "1")

from tests.unit.ui.conftest import FakeMessageBox, make_configured_appconfig  # noqa: E402
from wiseman_hub.ui.launcher import Launcher, LauncherAction  # noqa: E402

tk_required = pytest.mark.tk_required

_configured_appconfig = make_configured_appconfig
_FakeMessageBox = FakeMessageBox


@tk_required
class TestOpenReviewMainThread:
    """AC-L-3: `on_open_review` は main thread で呼ばれる（Tk を触るため）。"""

    def test_open_review_runs_on_main_thread(self, tmp_path: Path) -> None:
        import tkinter as tk

        config_path = tmp_path / "config.toml"
        config_path.write_text("", encoding="utf-8")

        main_tid = threading.get_ident()
        captured_tid: list[int] = []

        def open_review() -> str | None:
            captured_tid.append(threading.get_ident())
            return None  # cancel

        root = tk.Tk()
        try:
            launcher = Launcher(
                config=_configured_appconfig(),
                config_path=config_path,
                root=root,
                on_open_review=open_review,
                on_run_phase_b=lambda _sid: None,
                messagebox_fn=_FakeMessageBox(),
            )
            launcher.invoke_action(LauncherAction.OPEN_REVIEW)
        finally:
            root.destroy()

        assert captured_tid == [main_tid]


@tk_required
class TestPhaseBWorkerThread:
    """AC-L-3-Async: Phase B は worker thread で実行される。"""

    def test_phase_b_runs_in_worker_thread(self, tmp_path: Path) -> None:
        import tkinter as tk

        config_path = tmp_path / "config.toml"
        config_path.write_text("", encoding="utf-8")

        main_tid = threading.get_ident()
        phase_b_tids: list[int] = []

        def open_review() -> str | None:
            return "20260101T120000Z-abcd1234"

        def run_phase_b(session_id: str) -> None:
            phase_b_tids.append(threading.get_ident())

        root = tk.Tk()
        try:
            launcher = Launcher(
                config=_configured_appconfig(),
                config_path=config_path,
                root=root,
                on_open_review=open_review,
                on_run_phase_b=run_phase_b,
                messagebox_fn=_FakeMessageBox(),
            )
            launcher.invoke_action(LauncherAction.OPEN_REVIEW)
            launcher.wait_until_idle(timeout=5.0)
        finally:
            root.destroy()

        assert len(phase_b_tids) == 1
        assert phase_b_tids[0] != main_tid


@tk_required
class TestCancelSkipsPhaseB:
    """AC-L-3-NoSel: picker cancel (None) 時は Phase B 呼ばれない + busy 解除。"""

    def test_none_returned_skips_phase_b_and_clears_busy(
        self, tmp_path: Path
    ) -> None:
        import tkinter as tk

        config_path = tmp_path / "config.toml"
        config_path.write_text("", encoding="utf-8")

        phase_b_called = False

        def open_review() -> str | None:
            return None

        def run_phase_b(_sid: str) -> None:
            nonlocal phase_b_called
            phase_b_called = True

        root = tk.Tk()
        try:
            launcher = Launcher(
                config=_configured_appconfig(),
                config_path=config_path,
                root=root,
                on_open_review=open_review,
                on_run_phase_b=run_phase_b,
                messagebox_fn=_FakeMessageBox(),
            )
            launcher.invoke_action(LauncherAction.OPEN_REVIEW)
            # cancel パスは同期完結（executor に submit しない）
            assert phase_b_called is False
            assert launcher._busy is False
        finally:
            root.destroy()


@tk_required
class TestPhaseBCompletionNotification:
    """AC-L-3-Done: Phase B 成功で showinfo、失敗で showerror + PII 防御。"""

    def test_success_shows_info(self, tmp_path: Path) -> None:
        import tkinter as tk

        config_path = tmp_path / "config.toml"
        config_path.write_text("", encoding="utf-8")

        def open_review() -> str | None:
            return "20260101T120000Z-abcd1234"

        def run_phase_b(_sid: str) -> None:
            pass  # success

        mb = _FakeMessageBox()
        root = tk.Tk()
        try:
            launcher = Launcher(
                config=_configured_appconfig(),
                config_path=config_path,
                root=root,
                on_open_review=open_review,
                on_run_phase_b=run_phase_b,
                messagebox_fn=mb,
            )
            launcher.invoke_action(LauncherAction.OPEN_REVIEW)
            launcher.wait_until_idle(timeout=5.0)
        finally:
            root.destroy()

        assert any(
            kind == "info" and "完了" in title
            for kind, title, _ in mb.calls
        )

    def test_exception_shows_error_and_sanitizes_log(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        import tkinter as tk

        config_path = tmp_path / "config.toml"
        config_path.write_text("", encoding="utf-8")

        def open_review() -> str | None:
            return "20260101T120000Z-abcd1234"

        def run_phase_b(_sid: str) -> None:
            raise RuntimeError("/Users/secret/patient-山田太郎.pdf")

        mb = _FakeMessageBox()
        root = tk.Tk()
        try:
            launcher = Launcher(
                config=_configured_appconfig(),
                config_path=config_path,
                root=root,
                on_open_review=open_review,
                on_run_phase_b=run_phase_b,
                messagebox_fn=mb,
            )
            with caplog.at_level(logging.ERROR):
                launcher.invoke_action(LauncherAction.OPEN_REVIEW)
                launcher.wait_until_idle(timeout=5.0)
        finally:
            root.destroy()

        # 画面には型名のみ
        assert any(
            kind == "error" and "RuntimeError" in msg
            for kind, _, msg in mb.calls
        )
        # ログから PII（パス・氏名）が漏れないこと
        assert "RuntimeError" in caplog.text
        assert "山田太郎" not in caplog.text
        assert "/Users/secret" not in caplog.text


@tk_required
class TestRepeatedClickIgnoredPhaseB:
    """AC-L-3-NoDouble: Phase B 実行中の 2 回目 invoke は無視される（busy）。"""

    def test_second_invoke_is_ignored_while_busy(self, tmp_path: Path) -> None:
        import tkinter as tk

        config_path = tmp_path / "config.toml"
        config_path.write_text("", encoding="utf-8")

        start = threading.Event()
        proceed = threading.Event()
        open_review_calls = 0

        def open_review() -> str | None:
            nonlocal open_review_calls
            open_review_calls += 1
            return "20260101T120000Z-abcd1234"

        def run_phase_b(_sid: str) -> None:
            start.set()
            proceed.wait(timeout=5.0)

        root = tk.Tk()
        try:
            launcher = Launcher(
                config=_configured_appconfig(),
                config_path=config_path,
                root=root,
                on_open_review=open_review,
                on_run_phase_b=run_phase_b,
                messagebox_fn=_FakeMessageBox(),
            )
            launcher.invoke_action(LauncherAction.OPEN_REVIEW)
            assert start.wait(timeout=5.0)
            # 2 回目は busy で open_review すら呼ばれない
            launcher.invoke_action(LauncherAction.OPEN_REVIEW)
            proceed.set()
            launcher.wait_until_idle(timeout=5.0)
        finally:
            proceed.set()
            root.destroy()

        assert open_review_calls == 1
