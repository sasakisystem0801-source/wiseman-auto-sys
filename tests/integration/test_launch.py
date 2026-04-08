"""モックアプリ起動 → MainForm 表示の統合テスト（ADR-007）。"""

from __future__ import annotations

import pytest

from tests.integration.conftest import MOCK_APP_EXE

pytestmark = pytest.mark.integration


class TestLaunch:
    """モックアプリの起動テスト。

    実機ワイズマンはUSBドングル認証のみでログイン画面がなく、
    モックも同様に起動直後にMainFormが直接表示される。
    """

    def test_launch_success(self, engine) -> None:
        """起動 → MainForm が直接表示される（ログイン画面なし）。"""
        engine.launch(str(MOCK_APP_EXE))

        # メインウィンドウが表示されていることを確認
        assert engine._main_window is not None
        title = engine._main_window.window_text()
        assert "管理システム SP" in title
