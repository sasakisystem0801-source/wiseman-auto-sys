"""MockEngineのユニットテスト"""

from __future__ import annotations

from pathlib import Path

from wiseman_hub.rpa.mock_engine import MockEngine


class TestMockEngine:
    def test_launch_and_login(self) -> None:
        engine = MockEngine()
        engine.launch_and_login("C:\\wiseman.exe", "user1", "pass1")
        assert engine._logged_in is True
        assert "launch_and_login" in engine.call_log[0]

    def test_navigate_menu(self) -> None:
        engine = MockEngine()
        engine.navigate_menu(["ケア記録", "集計表"])
        assert engine._current_screen == "集計表"

    def test_export_csv_creates_file(self, tmp_path: Path) -> None:
        engine = MockEngine()
        engine._current_screen = "テスト帳票"
        result = engine.export_csv(tmp_path)
        assert result is not None
        assert result.exists()
        content = result.read_text(encoding="utf-8")
        assert "山田太郎" in content

    def test_read_grid_data(self) -> None:
        engine = MockEngine()
        data = engine.read_grid_data()
        assert len(data) == 3
        assert data[0][0] == "利用者名"

    def test_close_current_window(self) -> None:
        engine = MockEngine()
        engine._current_screen = "集計表"
        engine.close_current_window()
        assert engine._current_screen == ""

    def test_is_dongle_present(self) -> None:
        engine = MockEngine()
        assert engine.is_dongle_present() is True

    def test_take_screenshot(self, tmp_path: Path) -> None:
        engine = MockEngine()
        # data/screenshots にファイルが作られることを確認
        path = engine.take_screenshot("test_shot")
        assert path.exists()

    def test_call_log_tracks_operations(self) -> None:
        engine = MockEngine()
        engine.launch_and_login("exe", "u", "p")
        engine.navigate_menu(["メニュー1"])
        engine.is_dongle_present()
        assert len(engine.call_log) == 3

    def test_full_pipeline(self, tmp_path: Path) -> None:
        """PoC相当のパイプラインをモックで通しテスト"""
        engine = MockEngine()
        engine.launch_and_login("C:\\wiseman.exe", "user1", "pass1")
        engine.navigate_menu(["ケア記録", "集計表"])
        csv_path = engine.export_csv(tmp_path)
        assert csv_path is not None
        data = engine.read_grid_data()
        assert len(data) > 0
        engine.close_current_window()
        engine.close_wiseman()
        assert engine._logged_in is False
