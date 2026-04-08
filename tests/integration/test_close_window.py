"""close_current_window / close_wiseman 統合テスト。"""

from __future__ import annotations

import time

import pytest

from tests.integration.conftest import MOCK_APP_EXE

pytestmark = pytest.mark.integration


class TestCloseWindow:
    """ウィンドウ閉じるテスト。"""

    def test_close_current_window(self, engine) -> None:
        """MDI子ウィンドウを閉じた後、子ウィンドウが検出されなくなる。"""
        engine.launch(str(MOCK_APP_EXE))
        engine.navigate_menu(["ケア記録", "集計表"])

        # 子ウィンドウが存在することを確認
        mdi_child = engine._get_active_mdi_child()
        assert mdi_child is not None

        engine.close_current_window()
        time.sleep(1)

        # 子ウィンドウが閉じられたことを確認（WindowSpecificationの.exists()で判定）
        mdi_child_after = engine._get_active_mdi_child()
        assert mdi_child_after is None or not mdi_child_after.exists(timeout=1)

    def test_close_wiseman(self, engine) -> None:
        """ワイズマン終了後、内部状態がクリアされる。"""
        engine.launch(str(MOCK_APP_EXE))
        engine.close_wiseman()
        time.sleep(1)

        # engine内部状態がクリアされていることを確認
        assert engine._main_window is None
        assert engine._app is None
