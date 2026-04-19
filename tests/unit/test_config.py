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
    # 新セクション未指定時はデフォルト値を保持（OcrBackendConfig / PdfMergeConfig）
    assert config.ocr_backend.endpoint_url == ""
    assert config.ocr_backend.timeout_sec == 30
    assert config.pdf_merge.concat_order == ["A", "B", "C"]
    assert config.pdf_merge.user_name_bbox.dpi == 200


def test_load_config_with_ocr_and_pdf_merge_sections(tmp_path: Path) -> None:
    """[ocr_backend] / [pdf_merge] / [pdf_merge.user_name_bbox] セクションの TOML 読込を検証。

    ADR-008 で追加された新セクションと、load_config() のネスト bbox 特殊処理
    （pdf_merge_data.pop("user_name_bbox", {})）が正しく動作することを保証する。
    """
    toml_content = """\
[ocr_backend]
endpoint_url = "https://wiseman-ocr-proxy-xxx.a.run.app"
api_key = "test-key-abc123"
timeout_sec = 60
max_retries = 5

[pdf_merge]
input_dir = "C:\\\\Users\\\\test\\\\input"
output_dir = "C:\\\\Users\\\\test\\\\output"
source_a_filename = "utilization.pdf"
source_d_filename = "common_footer.pdf"
source_b_pattern = "invoice_{name}.pdf"
source_c_pattern = "receipt_{name}.pdf"
concat_order = ["A", "C", "B"]

[pdf_merge.user_name_bbox]
x0 = 50.0
y0 = 100.5
x1 = 300.0
y1 = 130.0
dpi = 300
"""
    config_file = tmp_path / "config.toml"
    config_file.write_text(toml_content, encoding="utf-8")

    config = load_config(config_file)

    # OcrBackendConfig 全フィールド
    assert config.ocr_backend.endpoint_url == "https://wiseman-ocr-proxy-xxx.a.run.app"
    assert config.ocr_backend.api_key == "test-key-abc123"
    assert config.ocr_backend.timeout_sec == 60
    assert config.ocr_backend.max_retries == 5

    # PdfMergeConfig（トップレベル）
    assert config.pdf_merge.input_dir == "C:\\Users\\test\\input"
    assert config.pdf_merge.output_dir == "C:\\Users\\test\\output"
    assert config.pdf_merge.source_a_filename == "utilization.pdf"
    assert config.pdf_merge.source_d_filename == "common_footer.pdf"
    assert config.pdf_merge.source_b_pattern == "invoice_{name}.pdf"
    assert config.pdf_merge.source_c_pattern == "receipt_{name}.pdf"
    assert config.pdf_merge.concat_order == ["A", "C", "B"]

    # UserNameBBox（ネスト、pop 特殊処理の検証ポイント）
    assert config.pdf_merge.user_name_bbox.x0 == 50.0
    assert config.pdf_merge.user_name_bbox.y0 == 100.5
    assert config.pdf_merge.user_name_bbox.x1 == 300.0
    assert config.pdf_merge.user_name_bbox.y1 == 130.0
    assert config.pdf_merge.user_name_bbox.dpi == 300
