"""設定ローダーのユニットテスト"""

from pathlib import Path

from wiseman_hub.config import AppConfig, load_config


def test_load_config_default() -> None:
    """設定ファイルが存在しない場合、デフォルト値を返す"""
    config = load_config(Path("/nonexistent/path.toml"))
    assert isinstance(config, AppConfig)
    assert config.version == "0.1.0"
    assert config.gcp.region == "asia-northeast1"


def test_load_config_from_file(tmp_path: Path) -> None:
    """TOMLファイルから設定を読み込む"""
    toml_content = """\
[app]
version = "1.0.0"
log_level = "DEBUG"

[wiseman]
exe_path = "C:\\\\test\\\\wiseman.exe"
startup_wait_sec = 15

[gcp]
project_id = "test-project"
bucket_name = "test-bucket"
region = "asia-northeast1"

[[reports.targets]]
name = "テスト帳票"
menu_path = ["メニュー1", "サブメニュー"]
output_format = "csv"
"""
    config_file = tmp_path / "config.toml"
    config_file.write_text(toml_content, encoding="utf-8")

    config = load_config(config_file)
    assert config.version == "1.0.0"
    assert config.log_level == "DEBUG"
    assert config.wiseman.exe_path == "C:\\test\\wiseman.exe"
    assert config.wiseman.startup_wait_sec == 15
    assert config.gcp.project_id == "test-project"
    assert len(config.reports) == 1
    assert config.reports[0].name == "テスト帳票"
