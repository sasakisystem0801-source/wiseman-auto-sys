"""read_grid_data 統合テスト。"""

from __future__ import annotations

import pytest

from tests.integration.conftest import MOCK_APP_EXE

pytestmark = pytest.mark.integration


class TestReadGrid:
    """DataGridView読み取りテスト。"""

    def test_read_grid_returns_data(self, engine) -> None:
        """DataGridViewからデータを読み取れる。"""
        engine.launch_and_login(str(MOCK_APP_EXE), "testuser", "testpass")
        engine.navigate_menu(["ケア記録", "集計表"])

        data = engine.read_grid_data()

        # ヘッダー含めて6行以上（MockDataで8行 + ヘッダー1行）
        assert len(data) >= 6
        # 最初の行はヘッダー
        assert "利用者名" in data[0]
