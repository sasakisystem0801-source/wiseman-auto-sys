"""navigate_menu 統合テスト。"""

from __future__ import annotations

import pytest

from tests.integration.conftest import MOCK_APP_EXE

pytestmark = pytest.mark.integration


class TestNavigateMenu:
    """メニュー遷移テスト。"""

    def test_navigate_to_care_record(self, engine) -> None:
        """ケア記録 → 集計表 でCareRecordFormが開く。"""
        engine.launch(str(MOCK_APP_EXE))
        engine.select_care_system()
        engine.navigate_menu(["ケア記録", "集計表"])

        # MDI子ウィンドウ「ケア記録集計表」が存在することを確認
        # WinForms MDI: Pane (MDI Client) > Window の階層
        mdi_child = engine._get_active_mdi_child()
        assert mdi_child is not None
        assert "ケア記録集計表" in mdi_child.window_text()
