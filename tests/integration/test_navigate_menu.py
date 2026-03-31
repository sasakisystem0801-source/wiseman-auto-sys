"""navigate_menu 統合テスト。"""

from __future__ import annotations

import pytest

from tests.integration.conftest import MOCK_APP_EXE

pytestmark = pytest.mark.integration


class TestNavigateMenu:
    """メニュー遷移テスト。"""

    def test_navigate_to_care_record(self, mock_app_process, engine) -> None:
        """ケア記録 → 集計表 でCareRecordFormが開く。"""
        engine.launch_and_login(str(MOCK_APP_EXE), "testuser", "testpass")
        engine.navigate_menu(["ケア記録", "集計表"])

        # MDI子ウィンドウ「ケア記録集計表」が存在することを確認
        children = engine._main_window.children(control_type="Window")
        assert len(children) > 0
        child_titles = [c.window_text() for c in children]
        assert any("ケア記録集計表" in t for t in child_titles)
