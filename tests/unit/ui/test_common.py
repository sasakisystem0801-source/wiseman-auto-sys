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
