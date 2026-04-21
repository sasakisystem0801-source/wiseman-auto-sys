"""タスク 13B: Launcher ↔ Phase A 統合の非同期化テスト（Issue #62）。

AC-L-2-Async: Phase A 実行中も mainloop が応答する（Windows「応答なし」防止）。
AC-L-2-NoDouble: 実行中の 2 回目クリックが無視される。
AC-L-2-Done: 完了時に成功 / 失敗の通知が出る。
AC-L-2-PIIDefense: 例外 message に PII（パス・氏名）が含まれていてもログには型名のみ。
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("TK_SILENCE_DEPRECATION", "1")

from tests.unit.ui.conftest import FakeMessageBox, make_configured_appconfig  # noqa: E402
from wiseman_hub.config import AppConfig  # noqa: E402
from wiseman_hub.ui.launcher import Launcher, LauncherAction  # noqa: E402

tk_required = pytest.mark.tk_required

_configured_appconfig = make_configured_appconfig
_FakeMessageBox = FakeMessageBox


@tk_required
class TestPhaseAWorkerThread:
    """AC-L-2-Async: Phase A コールバックが worker thread で実行される。"""

    def test_callback_runs_in_worker_thread(self, tmp_path: Path) -> None:
        import tkinter as tk

        config_path = tmp_path / "config.toml"
        config_path.write_text("", encoding="utf-8")

        thread_ids: list[int] = []

        def capture_thread() -> None:
            thread_ids.append(threading.get_ident())

        root = tk.Tk()
        try:
            launcher = Launcher(
                config=_configured_appconfig(),
                config_path=config_path,
                root=root,
                on_run_pdf_merge=capture_thread,
                messagebox_fn=_FakeMessageBox(),
            )
            launcher.invoke_action(LauncherAction.RUN_PDF_MERGE)
            launcher.wait_until_idle(timeout=5.0)
        finally:
            root.destroy()

        assert len(thread_ids) == 1
        assert thread_ids[0] != threading.get_ident(), (
            "callback must run in a worker thread, not the main/test thread"
        )


@tk_required
class TestRepeatedClickIgnored:
    """AC-L-2-NoDouble: busy 中の 2 回目の invoke は無視される。"""

    def test_second_invoke_is_ignored_while_busy(self, tmp_path: Path) -> None:
        import tkinter as tk

        config_path = tmp_path / "config.toml"
        config_path.write_text("", encoding="utf-8")

        start = threading.Event()
        proceed = threading.Event()
        call_count = 0
        lock = threading.Lock()

        def slow_callback() -> None:
            nonlocal call_count
            with lock:
                call_count += 1
            start.set()
            proceed.wait(timeout=5.0)

        root = tk.Tk()
        try:
            launcher = Launcher(
                config=_configured_appconfig(),
                config_path=config_path,
                root=root,
                on_run_pdf_merge=slow_callback,
                messagebox_fn=_FakeMessageBox(),
            )
            launcher.invoke_action(LauncherAction.RUN_PDF_MERGE)
            assert start.wait(timeout=5.0), "first callback did not start"
            # 2 回目の invoke は busy で捨てられる想定
            launcher.invoke_action(LauncherAction.RUN_PDF_MERGE)
            launcher.invoke_action(LauncherAction.RUN_PDF_MERGE)
            proceed.set()
            launcher.wait_until_idle(timeout=5.0)
        finally:
            root.destroy()

        assert call_count == 1, f"expected 1 call, got {call_count}"


@tk_required
class TestButtonStatesWhileBusy:
    """busy 中は 3 ボタン全てが disable される。"""

    def test_buttons_disabled_while_busy_and_reenabled_after(
        self, tmp_path: Path
    ) -> None:
        import tkinter as tk

        config_path = tmp_path / "config.toml"
        config_path.write_text("", encoding="utf-8")

        start = threading.Event()
        proceed = threading.Event()
        button_states_during: list[tuple[bool, bool, bool]] = []

        root = tk.Tk()

        def slow_callback() -> None:
            start.set()
            proceed.wait(timeout=5.0)

        try:
            launcher = Launcher(
                config=_configured_appconfig(),
                config_path=config_path,
                root=root,
                on_run_pdf_merge=slow_callback,
                messagebox_fn=_FakeMessageBox(),
            )
            launcher.invoke_action(LauncherAction.RUN_PDF_MERGE)
            assert start.wait(timeout=5.0)
            # main thread で state を読む（Tk 安全）
            root.update()
            button_states_during.append(
                (
                    "disabled" in launcher._btn_run.state(),
                    "disabled" in launcher._btn_review.state(),
                    "disabled" in launcher._btn_settings.state(),
                )
            )
            proceed.set()
            launcher.wait_until_idle(timeout=5.0)
            final_states = (
                "disabled" in launcher._btn_run.state(),
                "disabled" in launcher._btn_review.state(),
                "disabled" in launcher._btn_settings.state(),
            )
        finally:
            root.destroy()

        assert button_states_during[0] == (True, True, True), (
            "all 3 buttons must be disabled while Phase A is running"
        )
        assert final_states == (False, False, False), (
            "buttons must be re-enabled after Phase A finishes"
        )


@tk_required
class TestCompletionNotifications:
    """AC-L-2-Done: 成功/失敗時の通知。"""

    def test_success_shows_info_dialog(self, tmp_path: Path) -> None:
        import tkinter as tk

        config_path = tmp_path / "config.toml"
        config_path.write_text("", encoding="utf-8")

        mbox = _FakeMessageBox()

        root = tk.Tk()
        try:
            launcher = Launcher(
                config=_configured_appconfig(),
                config_path=config_path,
                root=root,
                on_run_pdf_merge=lambda: None,
                messagebox_fn=mbox,
            )
            launcher.invoke_action(LauncherAction.RUN_PDF_MERGE)
            launcher.wait_until_idle(timeout=5.0)
        finally:
            root.destroy()

        info_calls = [c for c in mbox.calls if c[0] == "info"]
        assert len(info_calls) == 1
        assert "完了" in info_calls[0][1] or "完了" in info_calls[0][2]

    def test_exception_shows_error_and_sanitizes_log(
        self, tmp_path: Path, caplog: Any
    ) -> None:
        import tkinter as tk

        config_path = tmp_path / "config.toml"
        config_path.write_text("", encoding="utf-8")

        mbox = _FakeMessageBox()

        def failing_callback() -> None:
            raise RuntimeError("/sensitive/path/to/山田太郎.pdf not found")

        root = tk.Tk()
        try:
            with caplog.at_level(logging.ERROR, logger="wiseman_hub.ui.launcher"):
                launcher = Launcher(
                    config=_configured_appconfig(),
                    config_path=config_path,
                    root=root,
                    on_run_pdf_merge=failing_callback,
                    messagebox_fn=mbox,
                )
                launcher.invoke_action(LauncherAction.RUN_PDF_MERGE)
                launcher.wait_until_idle(timeout=5.0)
        finally:
            root.destroy()

        error_calls = [c for c in mbox.calls if c[0] == "error"]
        assert len(error_calls) == 1

        logged = " ".join(r.getMessage() for r in caplog.records)
        assert "RuntimeError" in logged
        assert "山田太郎" not in logged, "PII (name) leaked into log"
        assert "/sensitive/path" not in logged, "PII (path) leaked into log"


@tk_required
class TestButtonReEnabledOnException:
    """例外発生時もボタン再有効化を保証する（_set_busy(False) 順序不変性）。"""

    def test_buttons_reenabled_even_if_callback_raises(
        self, tmp_path: Path
    ) -> None:
        import tkinter as tk

        config_path = tmp_path / "config.toml"
        config_path.write_text("", encoding="utf-8")

        def failing() -> None:
            raise RuntimeError("boom")

        root = tk.Tk()
        try:
            launcher = Launcher(
                config=_configured_appconfig(),
                config_path=config_path,
                root=root,
                on_run_pdf_merge=failing,
                messagebox_fn=_FakeMessageBox(),
            )
            launcher.invoke_action(LauncherAction.RUN_PDF_MERGE)
            launcher.wait_until_idle(timeout=5.0)
            final_states = (
                "disabled" in launcher._btn_run.state(),
                "disabled" in launcher._btn_review.state(),
                "disabled" in launcher._btn_settings.state(),
            )
        finally:
            root.destroy()

        assert final_states == (False, False, False), (
            "buttons must be re-enabled even when the Phase A callback raises"
        )


@tk_required
class TestConfigMissingBypassesExecutor:
    """設定未完了時は executor を起動しない（既存 AC-L-4 誘導フローを壊さない）。"""

    def test_config_missing_does_not_submit_to_executor(
        self, tmp_path: Path
    ) -> None:
        import tkinter as tk

        config_path = tmp_path / "config.toml"
        config_path.write_text("", encoding="utf-8")

        called: list[str] = []

        root = tk.Tk()
        try:
            launcher = Launcher(
                config=AppConfig(),  # 空設定
                config_path=config_path,
                root=root,
                on_run_pdf_merge=lambda: called.append("run"),
                messagebox_fn=_FakeMessageBox(),
                on_open_settings=lambda: called.append("settings"),
            )
            launcher.invoke_action(LauncherAction.RUN_PDF_MERGE)
            # wait_until_idle は submit されていない場合も即 return
            launcher.wait_until_idle(timeout=1.0)
        finally:
            root.destroy()

        # on_run_pdf_merge は呼ばれず、AC-L-4 誘導で on_open_settings が呼ばれる
        assert "run" not in called
        assert called == ["settings"]
