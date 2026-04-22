"""`install_tk_exception_guard` のテスト (Issue #67)。

launcher / settings / SessionPicker (13C) で共通利用する Tk callback 例外ガード。
PII 防御: logger には型名のみ、messagebox は sanitized メッセージ、二次 showerror
失敗は warning ログで握り潰し。
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest


class _FakeRoot:
    """report_callback_exception を書き込める最小 stub。"""

    def __init__(self) -> None:
        self.report_callback_exception: Any = None


class TestInstallTkExceptionGuard:
    def test_registers_handler_on_root(self) -> None:
        from wiseman_hub.ui.common import install_tk_exception_guard

        root = _FakeRoot()
        messagebox = MagicMock()
        install_tk_exception_guard(
            root, component="launcher", messagebox=messagebox
        )

        assert callable(root.report_callback_exception)

    def test_handler_logs_type_name_only(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """ログには exc_type.__name__ のみ。exc_value の文字列（PII 含みうる）は出さない。"""
        from wiseman_hub.ui.common import install_tk_exception_guard

        root = _FakeRoot()
        messagebox = MagicMock()
        install_tk_exception_guard(
            root, component="launcher", messagebox=messagebox
        )

        with caplog.at_level(logging.ERROR):
            err = ValueError("/Users/secret/patient-山田太郎.pdf")
            root.report_callback_exception(ValueError, err, None)

        assert "ValueError" in caplog.text
        assert "山田太郎" not in caplog.text
        assert "/Users/secret" not in caplog.text

    def test_handler_includes_component_in_log(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from wiseman_hub.ui.common import install_tk_exception_guard

        root = _FakeRoot()
        messagebox = MagicMock()
        install_tk_exception_guard(
            root, component="settings", messagebox=messagebox
        )

        with caplog.at_level(logging.ERROR):
            root.report_callback_exception(RuntimeError, RuntimeError("x"), None)

        assert "settings" in caplog.text
        assert "RuntimeError" in caplog.text

    def test_handler_calls_showerror_with_sanitized_message(self) -> None:
        from wiseman_hub.ui.common import install_tk_exception_guard

        root = _FakeRoot()
        messagebox = MagicMock()
        install_tk_exception_guard(
            root, component="launcher", messagebox=messagebox
        )

        err = OSError("/secret/path.pdf")
        root.report_callback_exception(OSError, err, None)

        messagebox.showerror.assert_called_once()
        args, _ = messagebox.showerror.call_args
        body = args[1]
        assert "OSError" in body
        assert "/secret/path.pdf" not in body

    def test_handler_swallows_secondary_showerror_failure(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """messagebox.showerror が失敗しても二次例外を raise しない（warning ログのみ）。"""
        from wiseman_hub.ui.common import install_tk_exception_guard

        root = _FakeRoot()
        messagebox = MagicMock()
        messagebox.showerror.side_effect = RuntimeError("tk destroyed")
        install_tk_exception_guard(
            root, component="launcher", messagebox=messagebox
        )

        with caplog.at_level(logging.WARNING):
            root.report_callback_exception(ValueError, ValueError("x"), None)

        assert "RuntimeError" in caplog.text

    @pytest.mark.parametrize(
        "bad_component",
        ["", "launcher main", "session picker", "\t", "a\nb"],
    )
    def test_rejects_invalid_component_label(self, bad_component: str) -> None:
        """空文字・空白・制御文字入り component は ValueError（grep 可読性保護）。"""
        from wiseman_hub.ui.common import install_tk_exception_guard

        root = _FakeRoot()
        with pytest.raises(ValueError, match="component must be non-empty"):
            install_tk_exception_guard(
                root, component=bad_component, messagebox=MagicMock()
            )

    @pytest.mark.parametrize(
        "ok_component",
        ["launcher", "settings", "session_picker", "session_abc-123"],
    )
    def test_accepts_snake_case_component(self, ok_component: str) -> None:
        from wiseman_hub.ui.common import install_tk_exception_guard

        root = _FakeRoot()
        install_tk_exception_guard(
            root, component=ok_component, messagebox=MagicMock()
        )
        assert callable(root.report_callback_exception)

    def test_handler_raises_attribute_error_on_exc_type_none(self) -> None:
        """Issue #71 #1: exc_type=None は現行実装で AttributeError を raise する。

        Tk の `report_callback_exception` は通常 (exc_class, exc_value, tb) を渡すが、
        仕様外の呼び出しで exc_type=None になる可能性を踏まえ、現行挙動を契約として
        固定する。AttributeError は Tk の main loop に伝播して Tk 側でログされ、
        アプリ全体を停止させない（defense-in-depth）。
        """
        from wiseman_hub.ui.common import install_tk_exception_guard

        root = _FakeRoot()
        messagebox = MagicMock()
        install_tk_exception_guard(
            root, component="launcher", messagebox=messagebox
        )

        with pytest.raises(AttributeError):
            root.report_callback_exception(None, ValueError("x"), None)

        # showerror は AttributeError 発生前に呼ばれていない（型名解決で先に落ちる）
        messagebox.showerror.assert_not_called()

    def test_handler_does_not_swallow_system_exit(self) -> None:
        """Issue #71 #2: showerror が BaseException 派生を投げた場合は伝播させる。

        実装の二次失敗ハンドラは `except Exception` で KeyboardInterrupt / SystemExit
        を意図的に通す設計（プロセス終了を阻害しない）。regression 検知のため契約固定。
        """
        from wiseman_hub.ui.common import install_tk_exception_guard

        root = _FakeRoot()
        messagebox = MagicMock()
        messagebox.showerror.side_effect = SystemExit(1)
        install_tk_exception_guard(
            root, component="launcher", messagebox=messagebox
        )

        with pytest.raises(SystemExit):
            root.report_callback_exception(ValueError, ValueError("x"), None)

    def test_handler_does_not_swallow_keyboard_interrupt(self) -> None:
        """Issue #71 #2: showerror が KeyboardInterrupt を投げた場合も伝播。

        SystemExit と同じく、プロセス中断シグナルは握り潰さない契約。
        """
        from wiseman_hub.ui.common import install_tk_exception_guard

        root = _FakeRoot()
        messagebox = MagicMock()
        messagebox.showerror.side_effect = KeyboardInterrupt()
        install_tk_exception_guard(
            root, component="launcher", messagebox=messagebox
        )

        with pytest.raises(KeyboardInterrupt):
            root.report_callback_exception(ValueError, ValueError("x"), None)
