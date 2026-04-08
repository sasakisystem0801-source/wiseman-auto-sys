"""E2E最小シナリオ: 起動 → ケア記録システム選択 → 新規登録ボタンクリック（#3）。

ADR-007 で確定した実機フロー:
1. launch(.lnk or .exe) → frmStartUp (システム選択ランチャー) 表示
2. select_care_system() → Pane クリック → frmMenu200 (ケアメイン) 表示
3. click_new_registration() → Button クリック → frmKihon (新規登録フォーム) 表示
"""

from __future__ import annotations

import pytest

from tests.integration.conftest import MOCK_APP_EXE

pytestmark = pytest.mark.integration


class TestNewRegistrationFlow:
    """最小E2Eシナリオ: ランチャー → ケア記録 → 新規登録"""

    def test_launch_opens_launcher(self, engine) -> None:
        """launch() 後、ランチャー frmStartUp が表示される。"""
        engine.launch(str(MOCK_APP_EXE))

        assert engine._launcher_window is not None
        title = engine._launcher_window.window_text()
        assert "ワイズマン" in title

    def test_select_care_system_opens_main(self, engine) -> None:
        """select_care_system() 後、ケア記録メイン frmMenu200 が表示される。"""
        engine.launch(str(MOCK_APP_EXE))
        engine.select_care_system()

        assert engine._main_window is not None
        title = engine._main_window.window_text()
        assert "管理システム SP" in title

    def test_click_new_registration_opens_registration_form(self, engine) -> None:
        """click_new_registration() 後、新規登録フォーム frmKihon が表示される。"""
        engine.launch(str(MOCK_APP_EXE))
        engine.select_care_system()
        engine.click_new_registration()

        # frmKihon が開いていることを確認
        reg_window = engine._app.window(auto_id="frmKihon")
        assert reg_window.exists(timeout=5)
