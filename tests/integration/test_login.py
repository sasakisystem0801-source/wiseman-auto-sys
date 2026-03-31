"""LoginForm → MainForm のログインフロー統合テスト。"""

from __future__ import annotations

import pytest

from tests.integration.conftest import MOCK_APP_EXE

pytestmark = pytest.mark.integration


class TestLogin:
    """モックアプリへのログインテスト。"""

    def test_launch_and_login_success(self, mock_app_process, engine) -> None:
        """正しい資格情報でログイン → MainFormが表示される。"""
        engine.launch_and_login(str(MOCK_APP_EXE), "testuser", "testpass")

        # メインウィンドウが表示されていることを確認
        assert engine._main_window is not None
        title = engine._main_window.window_text()
        assert "管理システム SP" in title
