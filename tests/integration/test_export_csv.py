"""export_csv 統合テスト。"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.integration.conftest import MOCK_APP_EXE

pytestmark = pytest.mark.integration


class TestExportCsv:
    """CSV出力テスト。"""

    def test_export_csv_creates_file(self, engine, tmp_path: Path) -> None:
        """印刷ボタン → SaveFileDialog → CSVファイルが作成される。"""
        engine.launch(str(MOCK_APP_EXE))
        engine.navigate_menu(["ケア記録", "集計表"])

        csv_path = engine.export_csv(tmp_path)

        assert csv_path is not None
        assert csv_path.exists()
        assert csv_path.suffix == ".csv"

        # CSVに日本語データが含まれることを確認
        content = csv_path.read_text(encoding="shift_jis")
        assert "利用者名" in content or "赤松" in content
