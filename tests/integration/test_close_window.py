"""close_current_window / close_wiseman 統合テスト。"""

from __future__ import annotations

import time

import pytest

from tests.integration.conftest import MOCK_APP_EXE

pytestmark = pytest.mark.integration


class TestCloseWindow:
    """ウィンドウ閉じるテスト。"""

    def test_close_current_window(self, mock_app_process, engine) -> None:
        """MDI子ウィンドウを閉じた後、子ウィンドウが0になる。"""
        engine.launch_and_login(str(MOCK_APP_EXE), "testuser", "testpass")
        engine.navigate_menu(["ケア記録", "集計表"])

        # 子ウィンドウが存在することを確認
        children = engine._main_window.children(control_type="Window")
        assert len(children) > 0

        engine.close_current_window()
        time.sleep(0.5)

        # 子ウィンドウが閉じられたことを確認
        children_after = engine._main_window.children(control_type="Window")
        assert len(children_after) < len(children)

    def test_close_wiseman(self, mock_app_process, engine) -> None:
        """ワイズマン終了後、プロセスが終了する。"""
        engine.launch_and_login(str(MOCK_APP_EXE), "testuser", "testpass")
        engine.close_wiseman()
        time.sleep(1)

        # プロセスが終了していることを確認
        assert mock_app_process.poll() is not None
