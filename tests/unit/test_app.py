"""WisemanHub オーケストレータのユニットテスト"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from wiseman_hub.app import WisemanHub
from wiseman_hub.rpa.mock_engine import MockEngine


class TestWisemanHubWithMock:
    """MockEngineを使ったパイプライン統合テスト"""

    def _create_config_toml(self, tmp_path: Path) -> Path:
        """テスト用の設定ファイルを作成"""
        config_path = tmp_path / "test_config.toml"
        config_path.write_text(
            '[app]\n'
            'version = "0.1.0-test"\n'
            'log_level = "DEBUG"\n'
            '\n'
            '[wiseman]\n'
            'exe_path = "C:\\\\wiseman.exe"\n'
            'username = "testuser"\n'
            '\n'
            '[reports]\n'
            'targets = [\n'
            '  { name = "ケア記録", menu_path = ["ケア記録", "日報"], output_format = "csv" },\n'
            ']\n'
            '\n'
            '[gcp]\n'
            'project_id = "test-project"\n'
            'bucket_name = "test-bucket"\n',
            encoding="utf-8",
        )
        return config_path

    def test_init_with_mock_engine(self, tmp_path: Path) -> None:
        config_path = self._create_config_toml(tmp_path)
        engine = MockEngine()
        hub = WisemanHub(config_path=config_path, rpa_engine=engine)
        assert hub.rpa is engine
        assert hub.config.version == "0.1.0-test"

    @patch("wiseman_hub.app.upload_files", return_value=["gs://test-bucket/mock.csv"])
    def test_pipeline_runs_with_mock(self, mock_upload: object, tmp_path: Path) -> None:
        """MockEngineでパイプライン全体が動作するか"""
        config_path = self._create_config_toml(tmp_path)
        engine = MockEngine()
        hub = WisemanHub(config_path=config_path, rpa_engine=engine)
        hub.output_dir = tmp_path / "exports"

        # keyringをモックしてパスワード取得をバイパス
        with patch("keyring.get_password", return_value="mock_password"):
            hub.run()

        # RPAの呼び出し履歴を確認
        assert any("launch_and_login" in c for c in engine.call_log)
        assert any("navigate_menu" in c for c in engine.call_log)
        assert any("export_csv" in c for c in engine.call_log)
        assert any("close_current_window" in c for c in engine.call_log)
        assert any("close_wiseman" in c for c in engine.call_log)

    @patch("wiseman_hub.app.upload_files", return_value=[])
    def test_pipeline_no_reports(self, mock_upload: object, tmp_path: Path) -> None:
        """帳票設定が空のとき、CSVなし警告で正常終了"""
        config_path = tmp_path / "no_reports.toml"
        config_path.write_text(
            '[wiseman]\n'
            'exe_path = "C:\\\\wiseman.exe"\n'
            'username = "testuser"\n'
            '\n'
            '[gcp]\n'
            'project_id = "test-project"\n'
            'bucket_name = "test-bucket"\n',
            encoding="utf-8",
        )
        engine = MockEngine()
        hub = WisemanHub(config_path=config_path, rpa_engine=engine)

        with patch("keyring.get_password", return_value="mock_password"):
            hub.run()

        # upload_filesは呼ばれない（CSVがないため）
        mock_upload.assert_not_called()

    def test_create_rpa_engine_returns_mock_on_macos(self, tmp_path: Path) -> None:
        """macOS環境ではMockEngineが自動選択される"""
        config_path = self._create_config_toml(tmp_path)
        hub = WisemanHub(config_path=config_path)
        assert type(hub.rpa).__name__ == "MockEngine"
