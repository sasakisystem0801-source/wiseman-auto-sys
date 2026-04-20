"""設定ローダーのユニットテスト"""

from dataclasses import replace
from pathlib import Path
from typing import Any

from wiseman_hub.config import AppConfig, load_config, save_config


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


class TestSaveConfig:
    """save_config(): AppConfig を TOML に書き戻すテスト。

    tomlkit でコメント・空行を維持したラウンドトリップを保証する。
    """

    def test_save_roundtrip_preserves_all_values(self, tmp_path: Path) -> None:
        """save → load で全フィールドが同じ値になる（ラウンドトリップ）。"""
        source = tmp_path / "source.toml"
        source.write_text(
            """\
[app]
version = "1.2.3"
log_level = "DEBUG"
log_dir = "/var/log/wiseman"

[wiseman]
exe_path = "C:\\\\wiseman.exe"
startup_wait_sec = 20
window_title_pattern = ".*TEST.*"

[schedule]
enabled = true
cron = "0 9 * * *"

[gcp]
project_id = "my-project"
bucket_name = "my-bucket"
service_account_key_path = "sa.json"
region = "asia-northeast1"

[updater]
enabled = true
check_interval_hours = 6
release_bucket = "releases"

[ocr_backend]
endpoint_url = "https://ocr.example.com"
api_key = "secret-key"
timeout_sec = 45
max_retries = 4

[pdf_merge]
input_dir = "/in"
output_dir = "/out"
source_a_filename = "A.pdf"
source_d_filename = "D.pdf"
source_b_pattern = "B_{name}.pdf"
source_c_pattern = "C_{name}.pdf"
concat_order = ["A", "C", "B"]

[pdf_merge.user_name_bbox]
x0 = 10.0
y0 = 20.0
x1 = 200.0
y1 = 50.0
dpi = 300

[[reports.targets]]
name = "帳票1"
menu_path = ["メニュー", "サブ"]
output_format = "csv"
""",
            encoding="utf-8",
        )
        cfg = load_config(source)

        target = tmp_path / "target.toml"
        save_config(cfg, target, create_if_missing=True)

        reloaded = load_config(target)
        assert reloaded == cfg

    def test_save_to_new_file_creates_valid_toml(self, tmp_path: Path) -> None:
        """既存ファイルなしで save(create_if_missing=True) → 新規作成、load で同じ値。"""
        cfg = AppConfig()
        cfg = replace(cfg, log_level="WARNING")
        cfg.pdf_merge.input_dir = "/tmp/in"
        cfg.pdf_merge.output_dir = "/tmp/out"
        cfg.pdf_merge.source_a_filename = "A.pdf"
        cfg.ocr_backend.endpoint_url = "https://example.com"
        cfg.ocr_backend.api_key = "xyz"

        target = tmp_path / "new.toml"
        save_config(cfg, target, create_if_missing=True)

        assert target.exists()
        reloaded = load_config(target)
        assert reloaded.log_level == "WARNING"
        assert reloaded.pdf_merge.input_dir == "/tmp/in"
        assert reloaded.ocr_backend.api_key == "xyz"

    def test_save_raises_file_not_found_by_default(self, tmp_path: Path) -> None:
        """create_if_missing=False（既定）で存在しないファイル → FileNotFoundError。"""
        import pytest

        cfg = AppConfig()
        target = tmp_path / "missing.toml"

        with pytest.raises(FileNotFoundError):
            save_config(cfg, target)
        assert not target.exists()

    def test_save_preserves_comments_when_existing_file(self, tmp_path: Path) -> None:
        """既存 TOML にコメントがある場合、save 後もコメントが残る（tomlkit の機能確認）。"""
        target = tmp_path / "commented.toml"
        target.write_text(
            """\
# これはトップレベルコメント
[app]
version = "0.0.1"  # バージョンコメント
log_level = "INFO"

# PDF マージ設定
[pdf_merge]
input_dir = ""  # 入力フォルダ
output_dir = ""
""",
            encoding="utf-8",
        )
        cfg = load_config(target)
        cfg.pdf_merge.input_dir = "/new/in"
        save_config(cfg, target)

        written = target.read_text(encoding="utf-8")
        assert "# これはトップレベルコメント" in written
        assert "# PDF マージ設定" in written
        assert "# 入力フォルダ" in written
        assert '/new/in' in written

    def test_save_overwrites_existing_file(self, tmp_path: Path) -> None:
        """既存ファイルを save で上書きできる。新しい値がロードされる。"""
        target = tmp_path / "existing.toml"
        target.write_text('[app]\nversion = "original"\n', encoding="utf-8")

        cfg = AppConfig()
        save_config(cfg, target)

        assert target.exists()
        reloaded = load_config(target)
        assert reloaded.version == cfg.version

    def test_save_preserves_bbox_nested_section(self, tmp_path: Path) -> None:
        """ネストセクション [pdf_merge.user_name_bbox] が正しく書き戻される。"""
        cfg = AppConfig()
        cfg.pdf_merge.user_name_bbox.x0 = 11.0
        cfg.pdf_merge.user_name_bbox.y0 = 22.0
        cfg.pdf_merge.user_name_bbox.x1 = 333.0
        cfg.pdf_merge.user_name_bbox.y1 = 44.0
        cfg.pdf_merge.user_name_bbox.dpi = 250

        target = tmp_path / "bbox.toml"
        save_config(cfg, target, create_if_missing=True)

        reloaded = load_config(target)
        assert reloaded.pdf_merge.user_name_bbox.x0 == 11.0
        assert reloaded.pdf_merge.user_name_bbox.y0 == 22.0
        assert reloaded.pdf_merge.user_name_bbox.x1 == 333.0
        assert reloaded.pdf_merge.user_name_bbox.y1 == 44.0
        assert reloaded.pdf_merge.user_name_bbox.dpi == 250

    def test_save_reports_targets_list(self, tmp_path: Path) -> None:
        """複数の [[reports.targets]] が正しく書き戻される。"""
        from wiseman_hub.config import ReportTarget

        cfg = AppConfig()
        cfg.reports.append(
            ReportTarget(name="報告書1", menu_path=["A", "B"], output_format="csv")
        )
        cfg.reports.append(
            ReportTarget(name="報告書2", menu_path=["X"], output_format="xlsx")
        )

        target = tmp_path / "reports.toml"
        save_config(cfg, target, create_if_missing=True)

        reloaded = load_config(target)
        assert len(reloaded.reports) == 2
        assert reloaded.reports[0].name == "報告書1"
        assert reloaded.reports[0].menu_path == ["A", "B"]
        assert reloaded.reports[1].name == "報告書2"
        assert reloaded.reports[1].output_format == "xlsx"

    def test_save_creates_parent_directory_if_missing(self, tmp_path: Path) -> None:
        """保存先の親ディレクトリが存在しない場合、自動作成する。"""
        cfg = AppConfig()
        target = tmp_path / "deeply" / "nested" / "config.toml"

        save_config(cfg, target, create_if_missing=True)

        assert target.exists()
        reloaded = load_config(target)
        assert reloaded.version == cfg.version

    def test_save_empty_reports_list(self, tmp_path: Path) -> None:
        """reports が空リストでも [[reports.targets]] を書き戻せる。"""
        cfg = AppConfig()
        target = tmp_path / "empty.toml"
        save_config(cfg, target, create_if_missing=True)

        reloaded = load_config(target)
        assert reloaded.reports == []

    def test_save_with_inline_table_notation(self, tmp_path: Path) -> None:
        """既存 TOML がインラインテーブル記法 `section = {...}` でも save できる。"""
        target = tmp_path / "inline.toml"
        target.write_text(
            'wiseman = {exe_path = "C:\\\\foo.exe", startup_wait_sec = 10, '
            'window_title_pattern = ".*"}\n',
            encoding="utf-8",
        )
        cfg = load_config(target)
        cfg.wiseman.startup_wait_sec = 25

        save_config(cfg, target)

        reloaded = load_config(target)
        assert reloaded.wiseman.startup_wait_sec == 25
        assert reloaded.wiseman.exe_path == "C:\\foo.exe"

    def test_save_raises_type_error_when_section_is_not_table(self, tmp_path: Path) -> None:
        """section に table 以外（整数等）が入っている不正 TOML では TypeError を返す。"""
        import pytest

        target = tmp_path / "bad.toml"
        target.write_text("wiseman = 42\n", encoding="utf-8")

        cfg = AppConfig()
        with pytest.raises(TypeError, match="is not a table"):
            save_config(cfg, target)

    def test_save_atomic_rollback_on_dump_error(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """tomlkit.dumps が例外を上げた場合、元ファイルが保たれ tmp は残らない。"""
        import pytest

        target = tmp_path / "target.toml"
        original = '[app]\nversion = "keep-this"\n'
        target.write_text(original, encoding="utf-8")

        def _raise(_doc: Any) -> str:
            raise RuntimeError("boom")

        monkeypatch.setattr("wiseman_hub.config.tomlkit.dumps", _raise)

        cfg = AppConfig()
        with pytest.raises(RuntimeError, match="boom"):
            save_config(cfg, target)

        assert target.read_text(encoding="utf-8") == original
        assert not any(p.suffix == ".tmp" for p in tmp_path.iterdir())

    def test_save_unicode_names_preserved_in_file(self, tmp_path: Path) -> None:
        """日本語氏名が UTF-8 で実ファイルに保存されている（生バイト確認）。"""
        from wiseman_hub.config import ReportTarget

        cfg = AppConfig()
        cfg.reports.append(ReportTarget(name="山田太郎", menu_path=["集計"]))
        target = tmp_path / "unicode.toml"
        save_config(cfg, target, create_if_missing=True)

        written = target.read_text(encoding="utf-8")
        assert "山田太郎" in written
        assert "集計" in written

    def test_save_concat_order_reorder(self, tmp_path: Path) -> None:
        """concat_order を並び替えても save/load で順序が保存される。"""
        target = tmp_path / "order.toml"
        target.write_text(
            "[pdf_merge]\nconcat_order = [\"A\", \"B\", \"C\"]\n", encoding="utf-8"
        )
        cfg = load_config(target)
        cfg.pdf_merge.concat_order = ["C", "A", "B"]

        save_config(cfg, target)

        reloaded = load_config(target)
        assert reloaded.pdf_merge.concat_order == ["C", "A", "B"]

    def test_save_overwrites_existing_file_value_actually_changes(
        self, tmp_path: Path
    ) -> None:
        """save 後に元の値が文字列として残っていない（強い overwrite 保証）。"""
        target = tmp_path / "overwrite.toml"
        target.write_text('[app]\nversion = "original-value-zzz"\n', encoding="utf-8")

        cfg = AppConfig()
        save_config(cfg, target)

        written = target.read_text(encoding="utf-8")
        assert "original-value-zzz" not in written
        assert cfg.version in written

    def test_save_sweeps_stale_tmp_files_before_write(self, tmp_path: Path) -> None:
        """過去のクラッシュで残った {name}.*.tmp が save 実行時に削除される。"""
        target = tmp_path / "config.toml"
        target.write_text('[app]\nversion = "0.1.0"\n', encoding="utf-8")

        stale1 = tmp_path / "config.toml.abc123.tmp"
        stale2 = tmp_path / "config.toml.xyz789.tmp"
        stale1.write_text("PII=山田太郎 api_key=leaked", encoding="utf-8")
        stale2.write_text("PII=/施設/patient/report.pdf", encoding="utf-8")

        cfg = AppConfig()
        save_config(cfg, target)

        assert not stale1.exists()
        assert not stale2.exists()

    def test_save_cleanup_warning_does_not_leak_path_or_pii(
        self, tmp_path: Path, monkeypatch: Any, caplog: Any
    ) -> None:
        """os.replace 失敗時の cleanup warning にパスや PII が含まれない。"""
        import logging

        import pytest

        target = tmp_path / "config.toml"
        target.write_text('[app]\nversion = "0.1.0"\n', encoding="utf-8")

        cfg = AppConfig()
        cfg.pdf_merge.input_dir = "/private/施設A/patient/山田太郎"

        def _fail_replace(src: str, dst: str) -> None:
            raise PermissionError("simulated Windows file lock")

        def _fail_unlink(_: str) -> None:
            raise PermissionError("simulated unlink failure")

        monkeypatch.setattr("wiseman_hub.config.os.replace", _fail_replace)
        monkeypatch.setattr("wiseman_hub.config.os.unlink", _fail_unlink)

        with caplog.at_level(logging.WARNING, logger="wiseman_hub.config"), pytest.raises(
            PermissionError
        ):
            save_config(cfg, target)

        logged = " ".join(r.getMessage() for r in caplog.records)
        assert "山田太郎" not in logged
        assert "施設A" not in logged
        assert str(tmp_path) not in logged
        assert ".tmp" not in logged
