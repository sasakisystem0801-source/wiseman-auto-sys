"""E2E統合テスト: ログイン → メニュー → グリッド読取 → CSV出力 → 閉じる → 終了。"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.integration.conftest import MOCK_APP_EXE

pytestmark = pytest.mark.integration


class TestFullPipeline:
    """モックアプリに対するフルパイプラインテスト。"""

    def test_full_rpa_pipeline(self, mock_app_process, engine, tmp_path: Path) -> None:
        """RPAパイプライン全体が一連で成功する。"""

        # Step 1: ログイン（失敗時はlaunch_and_loginが例外を投げる）
        engine.launch_and_login(str(MOCK_APP_EXE), "testuser", "testpass")

        # Step 2: メニュー遷移
        engine.navigate_menu(["ケア記録", "集計表"])
        assert engine._get_active_mdi_child() is not None

        # Step 3: グリッドデータ読み取り
        data = engine.read_grid_data()
        assert len(data) >= 2  # ヘッダー + データ行

        # Step 4: CSV出力
        csv_path = engine.export_csv(tmp_path)
        assert csv_path is not None
        assert csv_path.exists()

        # Step 5: MDI子ウィンドウを閉じる
        engine.close_current_window()

        # Step 6: ワイズマン終了
        engine.close_wiseman()
        assert engine._main_window is None
