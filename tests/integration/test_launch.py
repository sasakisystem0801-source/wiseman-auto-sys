"""モックアプリ起動 → ランチャー表示の統合テスト（ADR-007, #3）。"""

from __future__ import annotations

import pytest

from tests.integration.conftest import MOCK_APP_EXE

pytestmark = pytest.mark.integration


class TestLaunch:
    """モックアプリの起動テスト。

    実機ワイズマンはUSBドングル認証のみでログイン画面はなく、
    起動直後に「ワイズマンシステムSP」ランチャー(frmStartUp)が表示される。
    ケア記録メインウィンドウは select_care_system() 経由で開く必要がある。
    """

    def test_launch_opens_launcher(self, engine) -> None:
        """起動 → ランチャー(frmStartUp)が表示される。"""
        engine.launch(str(MOCK_APP_EXE))

        # ランチャーウィンドウが表示されていることを確認
        assert engine._launcher_window is not None
        title = engine._launcher_window.window_text()
        assert "ワイズマン" in title
        # この時点ではメインウィンドウは未選択
        assert engine._main_window is None
