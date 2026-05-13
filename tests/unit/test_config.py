"""設定ローダーのユニットテスト"""

import logging
import math
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from wiseman_hub.config import (
    AppConfig,
    ChecklistConfig,
    ConcatSourceLetter,
    OcrBackendConfig,
    PdfMergeConfig,
    ReportStaffEntry,
    UserNameBBox,
    load_config,
    save_config,
)


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
    assert config.pdf_merge.concat_order == ("A", "B", "C")
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
    assert config.pdf_merge.concat_order == ("A", "C", "B")

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

    def test_facility_root_dir_default_empty(self) -> None:
        """新規 AppConfig() で facility_root_dir はデフォルト空文字列。

        未設定状態（初回起動）を表現するため、None ではなく "" をデフォルトとする
        （他フィールドの慣例に合わせる）。
        """
        cfg = AppConfig()
        assert cfg.pdf_merge.facility_root_dir == ""

    def test_facility_root_dir_load_from_toml(self, tmp_path: Path) -> None:
        """[pdf_merge] facility_root_dir = "..." が TOML から読み込まれる。"""
        target = tmp_path / "facility_root.toml"
        target.write_text(
            """\
[pdf_merge]
facility_root_dir = "//Tera-station/share/03.FAX(事業所)"
""",
            encoding="utf-8",
        )

        cfg = load_config(target)

        assert cfg.pdf_merge.facility_root_dir == "//Tera-station/share/03.FAX(事業所)"

    def test_save_facility_root_dir_roundtrip(self, tmp_path: Path) -> None:
        """facility_root_dir の save → load ラウンドトリップ。日本語・UNC 含む。"""
        cfg = AppConfig()
        cfg.pdf_merge.facility_root_dir = "//Tera-station/share/03.FAX(事業所)"

        target = tmp_path / "roundtrip.toml"
        save_config(cfg, target, create_if_missing=True)

        reloaded = load_config(target)
        assert (
            reloaded.pdf_merge.facility_root_dir
            == "//Tera-station/share/03.FAX(事業所)"
        )

    def test_save_facility_root_dir_does_not_break_existing_fields(
        self, tmp_path: Path
    ) -> None:
        """facility_root_dir 追加で既存 PdfMergeConfig フィールドの値が変わらない。

        CLAUDE.md MUST: Partial Update する関数の追加 → 「更新対象外フィールドの値が
        変化しないこと」をテストに含める。
        """
        target = tmp_path / "partial.toml"
        target.write_text(
            """\
[pdf_merge]
input_dir = "/in"
output_dir = "/out"
source_a_filename = "A.pdf"
source_d_filename = "D.pdf"
source_b_pattern = "B_{name}.pdf"
source_c_pattern = "C_{name}.pdf"
concat_order = ["A", "C", "B"]

[pdf_merge.user_name_bbox]
x0 = 11.0
y0 = 22.0
x1 = 333.0
y1 = 44.0
dpi = 250
""",
            encoding="utf-8",
        )
        cfg = load_config(target)
        cfg.pdf_merge.facility_root_dir = "/srv/facility"

        save_config(cfg, target)
        reloaded = load_config(target)

        # 既存フィールドが変わらないこと（Partial Update 検証）
        assert reloaded.pdf_merge.input_dir == "/in"
        assert reloaded.pdf_merge.output_dir == "/out"
        assert reloaded.pdf_merge.source_a_filename == "A.pdf"
        assert reloaded.pdf_merge.source_d_filename == "D.pdf"
        assert reloaded.pdf_merge.source_b_pattern == "B_{name}.pdf"
        assert reloaded.pdf_merge.source_c_pattern == "C_{name}.pdf"
        assert reloaded.pdf_merge.concat_order == ("A", "C", "B")
        assert reloaded.pdf_merge.user_name_bbox.x0 == 11.0
        assert reloaded.pdf_merge.user_name_bbox.dpi == 250
        # 新フィールドが反映されること
        assert reloaded.pdf_merge.facility_root_dir == "/srv/facility"

    def test_facility_root_dir_unset_when_section_missing(
        self, tmp_path: Path
    ) -> None:
        """[pdf_merge] セクション自体がない TOML でも facility_root_dir は "" を返す。"""
        target = tmp_path / "nopdfmerge.toml"
        target.write_text('[app]\nversion = "1.0.0"\n', encoding="utf-8")

        cfg = load_config(target)
        assert cfg.pdf_merge.facility_root_dir == ""

    def test_save_concat_order_reorder(self, tmp_path: Path) -> None:
        """concat_order を並び替えても save/load で順序が保存される。"""
        target = tmp_path / "order.toml"
        target.write_text(
            "[pdf_merge]\nconcat_order = [\"A\", \"B\", \"C\"]\n", encoding="utf-8"
        )
        cfg = load_config(target)
        cfg.pdf_merge.concat_order = ("C", "A", "B")

        save_config(cfg, target)

        reloaded = load_config(target)
        assert reloaded.pdf_merge.concat_order == ("C", "A", "B")

    # --- ex_source_dir (.ex_ ファイル取込元フォルダ) ---

    def test_ex_source_dir_default_empty(self) -> None:
        """新規 AppConfig() で ex_source_dir はデフォルト空文字列（未設定状態）。"""
        cfg = AppConfig()
        assert cfg.pdf_merge.ex_source_dir == ""

    def test_ex_source_dir_load_from_toml(self, tmp_path: Path) -> None:
        """[pdf_merge] ex_source_dir = "..." が TOML から読み込まれる。"""
        target = tmp_path / "ex_source.toml"
        target.write_text(
            """\
[pdf_merge]
ex_source_dir = "C:\\\\Users\\\\sasak\\\\OneDrive\\\\デスクトップ\\\\本田様"
""",
            encoding="utf-8",
        )

        cfg = load_config(target)

        assert (
            cfg.pdf_merge.ex_source_dir
            == "C:\\Users\\sasak\\OneDrive\\デスクトップ\\本田様"
        )

    def test_save_ex_source_dir_roundtrip(self, tmp_path: Path) -> None:
        """ex_source_dir の save → load ラウンドトリップ。日本語パス含む。"""
        cfg = AppConfig()
        cfg.pdf_merge.ex_source_dir = "C:\\Users\\sasak\\OneDrive\\デスクトップ\\本田様"

        target = tmp_path / "roundtrip_ex.toml"
        save_config(cfg, target, create_if_missing=True)

        reloaded = load_config(target)
        assert (
            reloaded.pdf_merge.ex_source_dir
            == "C:\\Users\\sasak\\OneDrive\\デスクトップ\\本田様"
        )

    def test_ex_source_dir_unset_when_section_missing(self, tmp_path: Path) -> None:
        """[pdf_merge] セクションがない TOML でも ex_source_dir は "" を返す。"""
        target = tmp_path / "nopdfmerge_ex.toml"
        target.write_text('[app]\nversion = "1.0.0"\n', encoding="utf-8")

        cfg = load_config(target)
        assert cfg.pdf_merge.ex_source_dir == ""

    def test_save_ex_source_dir_does_not_break_existing_fields(
        self, tmp_path: Path
    ) -> None:
        """ex_source_dir 追加で既存 PdfMergeConfig フィールド（facility_root_dir 含む）の値が変わらない。

        CLAUDE.md MUST: Partial Update する関数の追加 → 「更新対象外フィールドの値が
        変化しないこと」をテストに含める。
        """
        target = tmp_path / "partial_ex.toml"
        target.write_text(
            """\
[pdf_merge]
input_dir = "/in"
output_dir = "/out"
source_a_filename = "A.pdf"
source_d_filename = "D.pdf"
source_b_pattern = "B_{name}.pdf"
source_c_pattern = "C_{name}.pdf"
concat_order = ["A", "C", "B"]
facility_root_dir = "/srv/facility"

[pdf_merge.user_name_bbox]
x0 = 11.0
y0 = 22.0
x1 = 333.0
y1 = 44.0
dpi = 250
""",
            encoding="utf-8",
        )
        cfg = load_config(target)
        cfg.pdf_merge.ex_source_dir = "/srv/ex_source"

        save_config(cfg, target)
        reloaded = load_config(target)

        # 既存フィールドが変わらないこと（Partial Update 検証）
        assert reloaded.pdf_merge.input_dir == "/in"
        assert reloaded.pdf_merge.output_dir == "/out"
        assert reloaded.pdf_merge.source_a_filename == "A.pdf"
        assert reloaded.pdf_merge.source_d_filename == "D.pdf"
        assert reloaded.pdf_merge.source_b_pattern == "B_{name}.pdf"
        assert reloaded.pdf_merge.source_c_pattern == "C_{name}.pdf"
        assert reloaded.pdf_merge.concat_order == ("A", "C", "B")
        assert reloaded.pdf_merge.facility_root_dir == "/srv/facility"
        assert reloaded.pdf_merge.user_name_bbox.x0 == 11.0
        assert reloaded.pdf_merge.user_name_bbox.dpi == 250
        # 新フィールドが反映されること
        assert reloaded.pdf_merge.ex_source_dir == "/srv/ex_source"

    # --- facility_aliases (事業所名の別名辞書) ---

    def test_facility_aliases_default_empty_dict(self) -> None:
        """新規 AppConfig() で facility_aliases はデフォルト空辞書（dict）。"""
        cfg = AppConfig()
        assert cfg.pdf_merge.facility_aliases == {}

    def test_facility_aliases_load_from_toml(self, tmp_path: Path) -> None:
        """[pdf_merge.facility_aliases] が dict[str, list[str]] として読み込まれる。

        TOML 形式:
            [pdf_merge.facility_aliases]
            "本田デイケア" = ["本田DC", "本田デイ"]
            "きなり(メール)※持参" = ["きなり"]
        """
        target = tmp_path / "aliases.toml"
        target.write_text(
            """\
[pdf_merge.facility_aliases]
"本田デイケア" = ["本田DC", "本田デイ"]
"きなり(メール)※持参" = ["きなり"]
""",
            encoding="utf-8",
        )

        cfg = load_config(target)

        assert cfg.pdf_merge.facility_aliases == {
            "本田デイケア": ["本田DC", "本田デイ"],
            "きなり(メール)※持参": ["きなり"],
        }

    def test_save_facility_aliases_roundtrip(self, tmp_path: Path) -> None:
        """facility_aliases の save → load ラウンドトリップ。日本語キー・複数別名。"""
        cfg = AppConfig()
        cfg.pdf_merge.facility_aliases = {
            "本田デイケア": ["本田DC", "本田デイ"],
            "きなり(メール)※持参": ["きなり"],
        }

        target = tmp_path / "roundtrip_aliases.toml"
        save_config(cfg, target, create_if_missing=True)

        reloaded = load_config(target)
        assert reloaded.pdf_merge.facility_aliases == {
            "本田デイケア": ["本田DC", "本田デイ"],
            "きなり(メール)※持参": ["きなり"],
        }

    def test_facility_aliases_empty_dict_when_section_missing(
        self, tmp_path: Path
    ) -> None:
        """[pdf_merge.facility_aliases] セクションがなければ空辞書を返す。"""
        target = tmp_path / "noaliases.toml"
        target.write_text('[pdf_merge]\ninput_dir = "/in"\n', encoding="utf-8")

        cfg = load_config(target)
        assert cfg.pdf_merge.facility_aliases == {}

    def test_save_facility_aliases_does_not_break_existing_fields(
        self, tmp_path: Path
    ) -> None:
        """facility_aliases 追加で既存 PdfMergeConfig 全フィールド（bbox 含む）が不変。

        CLAUDE.md MUST: Partial Update する関数の追加 → 「更新対象外フィールドの値が
        変化しないこと」をテストに含める。
        """
        target = tmp_path / "partial_aliases.toml"
        target.write_text(
            """\
[pdf_merge]
input_dir = "/in"
output_dir = "/out"
source_a_filename = "A.pdf"
source_d_filename = "D.pdf"
source_b_pattern = "B_{name}.pdf"
source_c_pattern = "C_{name}.pdf"
concat_order = ["A", "C", "B"]
facility_root_dir = "/srv/facility"
ex_source_dir = "/srv/ex"

[pdf_merge.user_name_bbox]
x0 = 11.0
y0 = 22.0
x1 = 333.0
y1 = 44.0
dpi = 250
""",
            encoding="utf-8",
        )
        cfg = load_config(target)
        cfg.pdf_merge.facility_aliases = {"本田デイケア": ["本田DC"]}

        save_config(cfg, target)
        reloaded = load_config(target)

        # 既存フィールドが変わらないこと
        assert reloaded.pdf_merge.input_dir == "/in"
        assert reloaded.pdf_merge.output_dir == "/out"
        assert reloaded.pdf_merge.source_a_filename == "A.pdf"
        assert reloaded.pdf_merge.source_d_filename == "D.pdf"
        assert reloaded.pdf_merge.source_b_pattern == "B_{name}.pdf"
        assert reloaded.pdf_merge.source_c_pattern == "C_{name}.pdf"
        assert reloaded.pdf_merge.concat_order == ("A", "C", "B")
        assert reloaded.pdf_merge.facility_root_dir == "/srv/facility"
        assert reloaded.pdf_merge.ex_source_dir == "/srv/ex"
        assert reloaded.pdf_merge.user_name_bbox.x0 == 11.0
        assert reloaded.pdf_merge.user_name_bbox.dpi == 250
        # 新フィールドが反映されること
        assert reloaded.pdf_merge.facility_aliases == {"本田デイケア": ["本田DC"]}

    def test_save_facility_aliases_preserves_comment_in_existing_toml(
        self, tmp_path: Path
    ) -> None:
        """既存 TOML のコメントが facility_aliases 追加で消失しない（tomlkit 動作確認）。

        ユーザーが手動編集したコメント（運用メモ等）を保護する。
        """
        target = tmp_path / "with_comment.toml"
        target.write_text(
            """\
# Wiseman Hub 設定ファイル
[app]
version = "1.0.0"  # important config

[pdf_merge]
# ルート以下の事業所フォルダを処理する
facility_root_dir = "/srv/facility"
""",
            encoding="utf-8",
        )
        cfg = load_config(target)
        cfg.pdf_merge.facility_aliases = {"本田デイケア": ["本田DC"]}

        save_config(cfg, target)
        written = target.read_text(encoding="utf-8")

        # 既存コメントが保持されること
        assert "# Wiseman Hub 設定ファイル" in written
        assert "# important config" in written
        assert "# ルート以下の事業所フォルダを処理する" in written
        # facility_aliases が実際に書き出されていること（緩い assert を強化）
        assert "facility_aliases" in written
        assert "本田デイケア" in written
        assert "本田DC" in written
        # ラウンドトリップで読み戻せること
        reloaded = load_config(target)
        assert reloaded.pdf_merge.facility_aliases == {"本田デイケア": ["本田DC"]}

    def test_save_facility_aliases_empty_value_overwrite(self, tmp_path: Path) -> None:
        """facility_aliases を空辞書に戻すと既存 alias がクリアされ、TOML から
        ``[pdf_merge.facility_aliases]`` セクション自体が消える。

        運用上、設定誤りで alias を一度入れたあと全削除する操作を保証する。
        TOML 文字列レベルで section header が消失することも確認（roundtrip だけだと
        空 table が残っても合格してしまう）。
        """
        target = tmp_path / "clear_aliases.toml"
        target.write_text(
            """\
[pdf_merge.facility_aliases]
"本田デイケア" = ["本田DC"]
""",
            encoding="utf-8",
        )
        cfg = load_config(target)
        assert cfg.pdf_merge.facility_aliases == {"本田デイケア": ["本田DC"]}

        cfg.pdf_merge.facility_aliases = {}
        save_config(cfg, target)

        written = target.read_text(encoding="utf-8")
        # section header / 別名・正式名すべてが TOML から消えていること
        assert "[pdf_merge.facility_aliases]" not in written
        assert "本田デイケア" not in written
        assert "本田DC" not in written

        reloaded = load_config(target)
        assert reloaded.pdf_merge.facility_aliases == {}

    # --- facility_aliases 入力検証（誤配布防止のため load_config が弾く） ---

    def test_facility_aliases_rejects_string_value_not_list(
        self, tmp_path: Path
    ) -> None:
        """alias value が文字列だと ``list("本田DC")`` で文字単位分解されるため、
        load_config が ``TypeError`` で弾く。

        現場担当者が default.toml のコメント例を見て手書きする際、配列ブラケットを
        忘れた場合の silent corruption を防ぐ（誤配布事故の温床）。
        """
        import pytest

        target = tmp_path / "bad_alias_str.toml"
        target.write_text(
            """\
[pdf_merge.facility_aliases]
"本田デイケア" = "本田DC"
""",
            encoding="utf-8",
        )
        with pytest.raises(TypeError, match="facility_aliases"):
            load_config(target)

    def test_facility_aliases_rejects_non_string_alias_elements(
        self, tmp_path: Path
    ) -> None:
        """alias value 配列の要素が文字列以外なら TypeError。"""
        import pytest

        target = tmp_path / "bad_alias_int.toml"
        target.write_text(
            """\
[pdf_merge.facility_aliases]
"本田デイケア" = [123, 456]
""",
            encoding="utf-8",
        )
        with pytest.raises(TypeError, match="facility_aliases"):
            load_config(target)

    def test_facility_aliases_rejects_empty_canonical_name(
        self, tmp_path: Path
    ) -> None:
        """正式名（key）が空文字列だと ValueError。

        空 key を許すと facility_resolver で空ファイル名が誤マッチする経路が生まれる。
        """
        import pytest

        target = tmp_path / "empty_key.toml"
        target.write_text(
            """\
[pdf_merge.facility_aliases]
"" = ["本田DC"]
""",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="facility_aliases"):
            load_config(target)

    def test_facility_aliases_rejects_empty_alias_string(
        self, tmp_path: Path
    ) -> None:
        """alias 配列に空文字列が含まれていたら ValueError。"""
        import pytest

        target = tmp_path / "empty_alias.toml"
        target.write_text(
            """\
[pdf_merge.facility_aliases]
"本田デイケア" = ["本田DC", ""]
""",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="facility_aliases"):
            load_config(target)

    def test_facility_aliases_rejects_duplicate_alias_within_facility(
        self, tmp_path: Path
    ) -> None:
        """同一 alias を同じ事業所の配列内で重複させたら ValueError（無意味なノイズ）。"""
        import pytest

        target = tmp_path / "dup_within.toml"
        target.write_text(
            """\
[pdf_merge.facility_aliases]
"本田デイケア" = ["本田DC", "本田DC"]
""",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="facility_aliases"):
            load_config(target)

    def test_facility_aliases_rejects_duplicate_alias_across_facilities(
        self, tmp_path: Path
    ) -> None:
        """同一 alias を複数事業所が共有していたら ValueError（最重要: 誤配布防止）。

        例: ``"本田"`` が「本田デイケア」と「本田訪問看護」両方に登録されていると、
        facility_resolver の最優先 alias 一致で先勝ち＝dict 順依存の不定動作になり、
        介護記録が別事業所に振り分けられる業務事故になる。
        """
        import pytest

        target = tmp_path / "dup_across.toml"
        target.write_text(
            """\
[pdf_merge.facility_aliases]
"本田デイケア" = ["本田"]
"本田訪問看護" = ["本田"]
""",
            encoding="utf-8",
        )
        # PII 防御 (ADR-014 / Issue #150 C1 対応): エラーメッセージに alias 文字列
        # ("本田" 等) を含めない設計に変更したため、構造的なメッセージのみ assert する。
        with pytest.raises(
            ValueError, match="facility_aliases.*shared by multiple facilities"
        ):
            load_config(target)

    def test_facility_aliases_rejects_alias_equal_to_other_canonical_name(
        self, tmp_path: Path
    ) -> None:
        """alias が他事業所の正式名と一致したら ValueError（最優先 alias と完全一致が衝突）。"""
        import pytest

        target = tmp_path / "alias_eq_canonical.toml"
        target.write_text(
            """\
[pdf_merge.facility_aliases]
"本田デイケア" = ["きなり"]
"きなり" = ["きなり訪問"]
""",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="facility_aliases"):
            load_config(target)

    def test_facility_aliases_accepts_self_reference_silently(
        self, tmp_path: Path
    ) -> None:
        """alias が自分自身の正式名と同じでも load 自体は通す（冗長だが害はない）。

        正規化完全一致と alias 一致のいずれでも同じ正式名にマップされるため、誤配布
        リスクなし。検証コストを増やすメリットも小さいので明示的に許容する設計。
        """
        target = tmp_path / "self_ref.toml"
        target.write_text(
            """\
[pdf_merge.facility_aliases]
"本田デイケア" = ["本田DC", "本田デイケア"]
""",
            encoding="utf-8",
        )
        cfg = load_config(target)
        assert cfg.pdf_merge.facility_aliases == {
            "本田デイケア": ["本田DC", "本田デイケア"]
        }

    # --- 同時更新の独立性（bbox + facility_aliases） ---

    def test_save_simultaneous_update_bbox_and_aliases_partial_update(
        self, tmp_path: Path
    ) -> None:
        """bbox と facility_aliases を同時に更新しても互いに上書きしない。

        ``_update_pdf_merge`` は両ネスト table を独立処理する設計だが、pop 順序や
        書き込み順を間違えると一方が他方を消す回帰が起こる。CLAUDE.md MUST の
        Partial Update 検証をネスト table 同士の組み合わせでも保証する。
        """
        target = tmp_path / "simul.toml"
        target.write_text(
            """\
[pdf_merge.user_name_bbox]
x0 = 11.0
y0 = 22.0
x1 = 333.0
y1 = 44.0
dpi = 250

[pdf_merge.facility_aliases]
"本田デイケア" = ["本田DC"]
""",
            encoding="utf-8",
        )
        cfg = load_config(target)
        cfg.pdf_merge.user_name_bbox.x0 = 99.0
        cfg.pdf_merge.facility_aliases = {
            "本田デイケア": ["本田DC", "本田デイ"],
            "きなり": ["きなり訪問"],
        }

        save_config(cfg, target)
        reloaded = load_config(target)

        assert reloaded.pdf_merge.user_name_bbox.x0 == 99.0
        assert reloaded.pdf_merge.user_name_bbox.y0 == 22.0  # 不変
        assert reloaded.pdf_merge.user_name_bbox.dpi == 250  # 不変
        assert reloaded.pdf_merge.facility_aliases == {
            "本田デイケア": ["本田DC", "本田デイ"],
            "きなり": ["きなり訪問"],
        }

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
        """os.replace 失敗時の cleanup warning にパスや PII が含まれない。

        save_config は内部で ``wiseman_hub.utils.atomic_io.write_bytes_atomically`` を
        呼ぶため、atomic_io 経由でも同じ PII 防御契約が維持されていることを確認する
        （atomic_io 本体のテストとは別に、config 統合経路を検証）。
        """
        import logging

        import pytest

        target = tmp_path / "config.toml"
        target.write_text('[app]\nversion = "0.1.0"\n', encoding="utf-8")

        cfg = AppConfig()
        cfg.pdf_merge.input_dir = "/private/施設A/patient/山田太郎"

        def _fail_replace(src: str, dst: str) -> None:
            raise PermissionError("simulated Windows file lock")

        def _fail_unlink(self: Path, missing_ok: bool = False) -> None:
            raise PermissionError("simulated unlink failure")

        monkeypatch.setattr("wiseman_hub.utils.atomic_io.os.replace", _fail_replace)
        monkeypatch.setattr(Path, "unlink", _fail_unlink)

        with caplog.at_level(logging.WARNING), pytest.raises(PermissionError):
            save_config(cfg, target)

        logged = " ".join(r.getMessage() for r in caplog.records)
        assert "山田太郎" not in logged
        assert "施設A" not in logged
        assert str(tmp_path) not in logged
        assert ".tmp" not in logged


class TestUserNameBBoxValidation:
    """UserNameBBox の不変条件検証 + is_configured。"""

    def test_default_is_unconfigured(self) -> None:
        bbox = UserNameBBox()
        assert bbox.is_configured is False

    def test_configured_when_any_coord_nonzero(self) -> None:
        bbox = UserNameBBox(x0=10.0, y0=20.0, x1=100.0, y1=80.0, dpi=200)
        assert bbox.is_configured is True

    @pytest.mark.parametrize(
        ("x0", "y0", "x1", "y1", "match"),
        [
            (100.0, 10.0, 50.0, 80.0, "x0 .* must be less than x1"),
            (50.0, 10.0, 50.0, 80.0, "x0 .* must be less than x1"),
            (10.0, 100.0, 50.0, 80.0, "y0 .* must be less than y1"),
            # 部分非ゼロ（x1=0）でも is_configured=True 経路に入るので順序逆転は raise する
            (10.0, 0.0, 0.0, 0.0, "x0 .* must be less than x1"),
        ],
    )
    def test_invalid_coord_order_raises(
        self, x0: float, y0: float, x1: float, y1: float, match: str
    ) -> None:
        with pytest.raises(ValueError, match=match):
            UserNameBBox(x0=x0, y0=y0, x1=x1, y1=y1)

    @pytest.mark.parametrize("dpi", [0, -1])
    def test_invalid_dpi_raises_regardless_of_configured(self, dpi: int) -> None:
        """dpi <= 0 は座標が未設定でも常時エラー（OCR 解像度の本質的な不正値）。"""
        with pytest.raises(ValueError, match="dpi must be positive"):
            UserNameBBox(dpi=dpi)

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("x0", float("nan")),
            ("y0", float("nan")),
            ("x1", float("nan")),
            ("y1", float("nan")),
            ("x0", float("inf")),
            ("y1", float("inf")),
            ("x0", float("-inf")),
            ("y0", float("-inf")),
        ],
    )
    def test_nan_inf_coord_raises(self, field: str, value: float) -> None:
        """Issue #152: NaN/inf 座標を ``math.isfinite`` で弾く。

        NaN は ``x0 >= x1`` 比較が常に False になり、後続の不変条件チェック
        (x0<x1, y0<y1) をすり抜けて silent fail する。``__post_init__`` の
        「未設定 return」より **前** で弾く必要がある (NaN は ``v == 0.0`` も
        False のため未設定判定にも引っ掛からず、return しないまま比較段に進む)。
        """
        # 他フィールドは妥当な値で埋める (NaN/inf 単独の影響を分離)
        coords: dict[str, float] = {"x0": 10.0, "y0": 20.0, "x1": 100.0, "y1": 80.0}
        coords[field] = value
        with pytest.raises(ValueError, match=f"{field} must be finite"):
            UserNameBBox(**coords)

    def test_nan_with_all_zero_coords_still_raises(self) -> None:
        """NaN は「未設定」判定 (4 値全 0) をすり抜けても弾かれる。

        ``x0=NaN, y0=0, x1=0, y1=0`` は ``NaN == 0`` が False なので
        未設定 return に入らず、NaN チェックで raise する。
        """
        with pytest.raises(ValueError, match="x0 must be finite"):
            UserNameBBox(x0=float("nan"), y0=0.0, x1=0.0, y1=0.0)

    def test_finite_coords_pass(self) -> None:
        """正常系: ``math.isfinite`` を通る通常座標は問題なく構築できる。"""
        bbox = UserNameBBox(x0=10.0, y0=20.0, x1=100.0, y1=80.0)
        assert math.isfinite(bbox.x0)
        assert bbox.is_configured is True

    @pytest.mark.parametrize(
        ("field", "bad_value"),
        [
            ("x0", True),
            ("y0", False),
            ("x1", "10"),
            ("y1", None),
            ("x0", [10.0]),
        ],
    )
    def test_non_numeric_coord_raises(self, field: str, bad_value: object) -> None:
        """Issue #27 §2: bool / str / None / list の座標は TypeError で起動時拒否。

        bool は ``int`` サブクラスのため ``math.isfinite(True)==True`` と
        ``True == 1`` で後続の NaN/inf チェック・座標順序チェックをすり抜ける。
        明示的に ``isinstance(v, bool)`` で除外する必要がある。
        """
        coords: dict[str, object] = {"x0": 10.0, "y0": 20.0, "x1": 100.0, "y1": 80.0}
        coords[field] = bad_value
        with pytest.raises(TypeError, match=f"{field} must be int or float"):
            UserNameBBox(**coords)  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad_value", [True, "200", None, 1.5])
    def test_non_int_dpi_raises(self, bad_value: object) -> None:
        """Issue #27 §2: bool / str / None / float の dpi は TypeError で起動時拒否。"""
        with pytest.raises(TypeError, match="dpi must be int"):
            UserNameBBox(dpi=bad_value)  # type: ignore[arg-type]

    def test_int_coords_accepted(self) -> None:
        """正常系: ``x0=10`` (int リテラル) も float field に受け入れる。"""
        bbox = UserNameBBox(x0=10, y0=20, x1=100, y1=80)
        assert bbox.is_configured is True


class TestOcrBackendConfigValidation:
    """OcrBackendConfig の不変条件検証 + is_configured。"""

    def test_default_is_unconfigured(self) -> None:
        cfg = OcrBackendConfig()
        assert cfg.is_configured is False

    def test_url_only_is_unconfigured(self) -> None:
        """endpoint_url 単独では呼び出し不可（api_key 必須）。"""
        cfg = OcrBackendConfig(endpoint_url="https://example.run.app")
        assert cfg.is_configured is False

    def test_key_only_is_unconfigured(self) -> None:
        cfg = OcrBackendConfig(api_key="abc")
        assert cfg.is_configured is False

    def test_both_url_and_key_is_configured(self) -> None:
        cfg = OcrBackendConfig(endpoint_url="https://example.run.app", api_key="abc")
        assert cfg.is_configured is True

    @pytest.mark.parametrize("timeout_sec", [0, -1])
    def test_invalid_timeout_raises(self, timeout_sec: int) -> None:
        with pytest.raises(ValueError, match="timeout_sec must be positive"):
            OcrBackendConfig(timeout_sec=timeout_sec)

    def test_max_retries_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="max_retries must be non-negative"):
            OcrBackendConfig(max_retries=-1)

    def test_max_retries_zero_allowed(self) -> None:
        """再試行なし運用（max_retries=0）は妥当な設定。"""
        cfg = OcrBackendConfig(max_retries=0)
        assert cfg.max_retries == 0

    @pytest.mark.parametrize("whitespace", ["   ", "\t", "\n", " \t\n"])
    def test_whitespace_only_endpoint_is_unconfigured(self, whitespace: str) -> None:
        """Issue #152: 空白文字列のみの endpoint_url は ``is_configured=False``。

        ``bool("   ")`` は truthy なので素朴な ``bool(url and key)`` では
        ``is_configured=True`` と誤判定し、HTTP 呼び出し時に runtime 失敗する。
        ``.strip()`` を噛ませて空白のみを「未設定」と扱う。
        """
        cfg = OcrBackendConfig(endpoint_url=whitespace, api_key="abc")
        assert cfg.is_configured is False

    @pytest.mark.parametrize("whitespace", ["   ", "\t", "\n", " \t\n"])
    def test_whitespace_only_api_key_is_unconfigured(self, whitespace: str) -> None:
        """Issue #152: 空白文字列のみの api_key は ``is_configured=False``。"""
        cfg = OcrBackendConfig(endpoint_url="https://example.run.app", api_key=whitespace)
        assert cfg.is_configured is False

    def test_both_whitespace_only_is_unconfigured(self) -> None:
        """Issue #152: 両方とも空白のみ → ``is_configured=False``。"""
        cfg = OcrBackendConfig(endpoint_url="   ", api_key="\t")
        assert cfg.is_configured is False

    @pytest.mark.parametrize("bad_value", [123, None, ["url"], True])
    def test_non_string_endpoint_url_raises(self, bad_value: object) -> None:
        """Issue #27 §2: 非文字列 endpoint_url は TypeError で起動時拒否。"""
        with pytest.raises(TypeError, match="endpoint_url must be str"):
            OcrBackendConfig(endpoint_url=bad_value)  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad_value", [456, None, {"key": "val"}, False])
    def test_non_string_api_key_raises(self, bad_value: object) -> None:
        """Issue #27 §2: 非文字列 api_key は TypeError で起動時拒否。"""
        with pytest.raises(TypeError, match="api_key must be str"):
            OcrBackendConfig(api_key=bad_value)  # type: ignore[arg-type]

    def test_api_key_typeerror_does_not_leak_value(self) -> None:
        """PII 防御: api_key の TypeError メッセージに値を含めない。

        型違反時に渡される値は str ではないため実シークレットそのものは
        含まれないが、pattern hygiene として ``{v!r}`` を含めない設計。
        ``type().__name__`` のみで型違反は十分診断可能。
        """
        sensitive_marker = "should_not_appear_in_message"
        with pytest.raises(TypeError) as exc_info:
            OcrBackendConfig(api_key=[sensitive_marker])  # type: ignore[arg-type]
        assert sensitive_marker not in str(exc_info.value)
        assert "api_key must be str" in str(exc_info.value)
        assert "list" in str(exc_info.value)  # 型名は出る

    @pytest.mark.parametrize("bad_value", [True, "30", 1.5, None])
    def test_non_int_timeout_sec_raises(self, bad_value: object) -> None:
        """Issue #27 §2: bool / str / float / None の timeout_sec は TypeError。"""
        with pytest.raises(TypeError, match="timeout_sec must be int"):
            OcrBackendConfig(timeout_sec=bad_value)  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad_value", [True, "3", 2.5, None])
    def test_non_int_max_retries_raises(self, bad_value: object) -> None:
        """Issue #27 §2: bool / str / float / None の max_retries は TypeError。"""
        with pytest.raises(TypeError, match="max_retries must be int"):
            OcrBackendConfig(max_retries=bad_value)  # type: ignore[arg-type]


class TestPdfMergeConfigValidation:
    """PdfMergeConfig.concat_order の Literal + 検証。"""

    def test_default_concat_order_valid(self) -> None:
        cfg = PdfMergeConfig()
        assert cfg.concat_order == ("A", "B", "C")

    def test_concat_order_subset_valid(self) -> None:
        """部分集合（例: A,C のみ）も許容。"""
        cfg = PdfMergeConfig(concat_order=["A", "C"])
        assert cfg.concat_order == ("A", "C")

    def test_concat_order_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            PdfMergeConfig(concat_order=[])

    @pytest.mark.parametrize(
        ("invalid_order", "reason"),
        [
            (["A", "B", "C", "D"], "D は source_d_filename 経由で末尾追加される別系統"),
            (["A", "X"], "未知の letter"),
            (["a", "b"], "大文字小文字違い（'a' != 'A'）"),
        ],
        ids=["d-rejected", "unknown-letter", "lowercase"],
    )
    def test_concat_order_unknown_value_raises(
        self, invalid_order: list[str], reason: str
    ) -> None:
        # Literal 不一致は runtime ではブロックされないため cast でテスト
        with pytest.raises(ValueError, match="unknown source"):
            PdfMergeConfig(concat_order=cast(list[ConcatSourceLetter], invalid_order))

    def test_concat_order_duplicate_raises(self) -> None:
        with pytest.raises(ValueError, match="duplicates"):
            PdfMergeConfig(concat_order=["A", "B", "A"])

    def test_post_construction_mutation_blocked_at_type_level(self) -> None:
        """Issue #151: ``concat_order`` を tuple 化したため、構築後の in-place
        mutation (``cfg.concat_order.append(...)`` / ``[i] = ...`` 等) は
        AttributeError / TypeError で型レベル阻止される。

        元実装では ``list`` だったため ``__post_init__`` の値域チェックを bypass
        できる経路が残っていた (merger.py の ``_validate_concat_order`` defensive
        layer 頼み)。Issue #151 で tuple 化したことで mutation 経路自体が構造的に
        阻止される設計に昇格した。defensive layer は依然として merger 直接呼出時の
        外部入力検証 (``Sequence[str]`` 引数) で有効。
        """
        cfg = PdfMergeConfig()
        # tuple は append / insert / __setitem__ いずれも持たない → mutation 不可
        assert isinstance(cfg.concat_order, tuple)
        assert not hasattr(cfg.concat_order, "append")
        assert not hasattr(cfg.concat_order, "insert")
        # __setitem__ は in-place 代入を試みると TypeError ('tuple' object does not support item assignment)
        with pytest.raises(TypeError, match="does not support item assignment"):
            cfg.concat_order[0] = cast(ConcatSourceLetter, "X")  # type: ignore[index]

    def test_post_init_normalizes_list_input_to_tuple(self) -> None:
        """Issue #151: __post_init__ で list 入力を tuple 化する fail-safe を検証。

        TOML / settings.py / 既存テストから ``concat_order=[...]`` で渡されても、
        最終的に tuple として保持され、構築後 mutation を防ぐ契約を保証する
        (呼出側の漏れを防ぐ DRY な設計)。
        """
        # cast は意図的な型嘘（runtime 正規化を検証する目的）
        cfg = PdfMergeConfig(concat_order=cast(
            "tuple[ConcatSourceLetter, ...]", ["A", "B", "C"]
        ))
        assert cfg.concat_order == ("A", "B", "C")
        assert isinstance(cfg.concat_order, tuple)

    def test_load_config_normalizes_toml_list_to_tuple(
        self, tmp_path: Path
    ) -> None:
        """Issue #151 (pr-test-analyzer Critical Gap #1): TOML 由来の
        ``list`` が ``__post_init__`` 経由で tuple に正規化されることを契約化。

        既存 assertion (`== ("C", "A", "B")`) は値の比較のみで型を検証しないため、
        TOML→list→tuple 経路が将来 bypass される regression を直接 catch する
        ``isinstance`` チェックを別軸で追加する。
        """
        target = tmp_path / "concat_tuple.toml"
        target.write_text(
            '[pdf_merge]\nconcat_order = ["C", "A", "B"]\n',
            encoding="utf-8",
        )
        cfg = load_config(target)
        assert isinstance(cfg.pdf_merge.concat_order, tuple)
        assert cfg.pdf_merge.concat_order == ("C", "A", "B")

    def test_iadd_does_not_bypass_post_init_validation_in_place(self) -> None:
        """Issue #151 (pr-test-analyzer Important #3): tuple は ``+=`` で
        in-place mutation できないが、Python 仕様上 **新規 tuple への再代入** に
        fall back する。再代入は ``__post_init__`` を経由しないため値域検証を
        bypass できる。本テストは「型レベルでは阻止できない」契約を明示し、
        将来 ``frozen=True`` 化で全置換も阻止する選択肢を検討する根拠とする。

        実害: ``cfg.concat_order += ("X",)`` で未知 letter を入れた状態で
        merger.py に渡すと、defensive layer (``_validate_concat_order``) が
        ``ValueError`` で catch する設計のため運用上は安全。
        """
        cfg = PdfMergeConfig()
        original_id = id(cfg.concat_order)
        # `cfg.concat_order = cfg.concat_order + (...,)` と等価 (tuple は __iadd__ なし)
        cfg.concat_order += (cast(ConcatSourceLetter, "X"),)
        # 同オブジェクトでなく新規 tuple に置き換わっている (in-place ではない)
        assert id(cfg.concat_order) != original_id
        assert isinstance(cfg.concat_order, tuple)
        # 値域違反は __post_init__ を経由しないため bypass されている (defensive
        # layer で守る前提): tuple 内に "X" が入っているが ValueError は raise されない
        assert "X" in cfg.concat_order


class TestDataclassTypeGuards:
    """Issue #27 続編 A: 7 dataclass の ``__post_init__`` 型ガード水平展開。

    各 dataclass の代表的フィールドで bool/str/None/list/dict 型違反が
    ``TypeError`` で起動時拒否されることを検証。
    helper 単位の網羅テストは TestTypeGuardHelpers で別途実施。
    """

    # --- WisemanConfig --------------------------------------------------
    def test_wiseman_non_string_exe_path_raises(self) -> None:
        with pytest.raises(TypeError, match="WisemanConfig.exe_path must be str"):
            from wiseman_hub.config import WisemanConfig
            WisemanConfig(exe_path=123)  # type: ignore[arg-type]

    def test_wiseman_non_int_startup_wait_raises(self) -> None:
        from wiseman_hub.config import WisemanConfig
        with pytest.raises(TypeError, match="startup_wait_sec must be int"):
            WisemanConfig(startup_wait_sec=True)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="startup_wait_sec must be int"):
            WisemanConfig(startup_wait_sec="15")  # type: ignore[arg-type]

    # --- ScheduleConfig -------------------------------------------------
    def test_schedule_non_bool_enabled_raises(self) -> None:
        from wiseman_hub.config import ScheduleConfig
        with pytest.raises(TypeError, match="ScheduleConfig.enabled must be bool"):
            ScheduleConfig(enabled=1)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="ScheduleConfig.enabled must be bool"):
            ScheduleConfig(enabled="true")  # type: ignore[arg-type]

    def test_schedule_non_string_cron_raises(self) -> None:
        from wiseman_hub.config import ScheduleConfig
        with pytest.raises(TypeError, match="ScheduleConfig.cron must be str"):
            ScheduleConfig(cron=None)  # type: ignore[arg-type]

    # --- ReportTarget ---------------------------------------------------
    def test_report_target_non_list_menu_path_raises(self) -> None:
        from wiseman_hub.config import ReportTarget
        with pytest.raises(TypeError, match="ReportTarget.menu_path must be list"):
            ReportTarget(menu_path="A/B/C")  # type: ignore[arg-type]

    def test_report_target_non_string_menu_item_raises(self) -> None:
        from wiseman_hub.config import ReportTarget
        with pytest.raises(TypeError, match=r"menu_path\[0\] must be str"):
            ReportTarget(menu_path=[123])  # type: ignore[list-item]

    # --- GcpConfig ------------------------------------------------------
    def test_gcp_non_string_project_id_raises(self) -> None:
        from wiseman_hub.config import GcpConfig
        with pytest.raises(TypeError, match="GcpConfig.project_id must be str"):
            GcpConfig(project_id=123)  # type: ignore[arg-type]

    def test_gcp_sa_key_path_typeerror_does_not_leak_value(self) -> None:
        """PII 防御: service_account_key_path の TypeError に値を含めない。"""
        from wiseman_hub.config import GcpConfig
        sensitive_marker = "should_not_appear_in_message"
        with pytest.raises(TypeError) as exc_info:
            GcpConfig(service_account_key_path=[sensitive_marker])  # type: ignore[arg-type]
        assert sensitive_marker not in str(exc_info.value)
        assert "service_account_key_path must be str" in str(exc_info.value)

    # --- UpdaterConfig --------------------------------------------------
    def test_updater_non_bool_enabled_raises(self) -> None:
        from wiseman_hub.config import UpdaterConfig
        with pytest.raises(TypeError, match="UpdaterConfig.enabled must be bool"):
            UpdaterConfig(enabled="true")  # type: ignore[arg-type]

    def test_updater_non_int_check_interval_raises(self) -> None:
        from wiseman_hub.config import UpdaterConfig
        with pytest.raises(TypeError, match="check_interval_hours must be int"):
            UpdaterConfig(check_interval_hours="1")  # type: ignore[arg-type]

    # --- ChecklistConfig ------------------------------------------------
    def test_checklist_non_string_karte_root_raises(self) -> None:
        from wiseman_hub.config import ChecklistConfig
        with pytest.raises(TypeError, match="karte_root must be str"):
            ChecklistConfig(karte_root=None)  # type: ignore[arg-type]

    def test_checklist_non_dict_facility_routing_raises(self) -> None:
        from wiseman_hub.config import ChecklistConfig
        with pytest.raises(TypeError, match="facility_routing must be dict"):
            ChecklistConfig(facility_routing=[])  # type: ignore[arg-type]

    def test_checklist_facility_routing_non_string_value_raises(self) -> None:
        from wiseman_hub.config import ChecklistConfig
        with pytest.raises(TypeError, match=r"facility_routing\['居宅A'\] must be str"):
            ChecklistConfig(facility_routing={"居宅A": 123})  # type: ignore[dict-item]

    def test_checklist_report_staff_non_entry_value_raises(self) -> None:
        from wiseman_hub.config import ChecklistConfig
        with pytest.raises(TypeError, match=r"report_staff\['宮下'\] must be ReportStaffEntry"):
            ChecklistConfig(report_staff={"宮下": "not-an-entry"})  # type: ignore[dict-item]

    def test_checklist_spreadsheet_id_typeerror_does_not_leak_value(self) -> None:
        """PII 防御: spreadsheet_id (Google Drive file id) の TypeError に値を含めない。"""
        from wiseman_hub.config import ChecklistConfig
        sensitive_marker = "secret_drive_file_id_12345"
        with pytest.raises(TypeError) as exc_info:
            ChecklistConfig(spreadsheet_id=[sensitive_marker])  # type: ignore[arg-type]
        assert sensitive_marker not in str(exc_info.value)
        assert "spreadsheet_id must be str" in str(exc_info.value)

    def test_checklist_legacy_warning_still_fires_after_type_guard(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """型ガード追加後も既存の legacy WARNING (PR #233) が維持されること。"""
        from wiseman_hub.config import ChecklistConfig
        with caplog.at_level(logging.WARNING, logger="wiseman_hub.config"):
            ChecklistConfig(monitoring_subfolder="08.運動器機能向上計画書")
        assert any("legacy value" in record.message for record in caplog.records)

    # --- ReportStaffEntry -----------------------------------------------
    def test_report_staff_entry_non_string_base_dir_raises(self) -> None:
        from wiseman_hub.config import ReportStaffEntry
        with pytest.raises(TypeError, match="ReportStaffEntry.base_dir must be str"):
            ReportStaffEntry(base_dir=123)  # type: ignore[arg-type]

    def test_report_staff_entry_non_list_suggest_patterns_raises(self) -> None:
        from wiseman_hub.config import ReportStaffEntry
        with pytest.raises(TypeError, match="suggest_patterns must be list"):
            ReportStaffEntry(suggest_patterns="*.xlsx")  # type: ignore[arg-type]

    # --- AppConfig default インスタンス化が全 type guard を通過 ----------
    def test_app_config_default_construction_passes_all_type_guards(self) -> None:
        """AppConfig() の default 値が全 dataclass の型ガードを通過すること (regression guard)。"""
        cfg = AppConfig()
        assert isinstance(cfg.wiseman.exe_path, str)
        assert isinstance(cfg.schedule.enabled, bool)
        assert isinstance(cfg.reports, list)
        assert isinstance(cfg.gcp.project_id, str)
        assert isinstance(cfg.updater.enabled, bool)
        assert isinstance(cfg.checklist.facility_routing, dict)

    # --- AppConfig 自身の field 型ガード (silent-failure review 反映) ----
    def test_app_config_non_string_version_raises(self) -> None:
        with pytest.raises(TypeError, match="AppConfig.version must be str"):
            AppConfig(version=123)  # type: ignore[arg-type]

    def test_app_config_non_string_log_level_raises(self) -> None:
        with pytest.raises(TypeError, match="AppConfig.log_level must be str"):
            AppConfig(log_level=None)  # type: ignore[arg-type]

    def test_app_config_non_list_reports_raises(self) -> None:
        with pytest.raises(TypeError, match="AppConfig.reports must be list"):
            AppConfig(reports="not-a-list")  # type: ignore[arg-type]

    def test_app_config_non_report_target_in_reports_raises(self) -> None:
        with pytest.raises(TypeError, match=r"AppConfig.reports\[0\] must be ReportTarget"):
            AppConfig(reports=["not-a-ReportTarget"])  # type: ignore[list-item]

    # --- ChecklistConfig.report_staff inline 検査の漏れたケース (pr-test rating 7) ---
    def test_checklist_report_staff_non_dict_raises(self) -> None:
        from wiseman_hub.config import ChecklistConfig
        with pytest.raises(TypeError, match="report_staff must be dict"):
            ChecklistConfig(report_staff=[])  # type: ignore[arg-type]

    def test_checklist_report_staff_non_string_key_raises(self) -> None:
        from wiseman_hub.config import ChecklistConfig, ReportStaffEntry
        with pytest.raises(TypeError, match="report_staff key must be str"):
            ChecklistConfig(report_staff={1: ReportStaffEntry()})  # type: ignore[dict-item]

    # --- ChecklistConfig.xlsx_path_cache 型ガード (pr-test rating 6) ----
    def test_checklist_xlsx_path_cache_non_dict_raises(self) -> None:
        from wiseman_hub.config import ChecklistConfig
        with pytest.raises(TypeError, match="xlsx_path_cache must be dict"):
            ChecklistConfig(xlsx_path_cache="not-a-dict")  # type: ignore[arg-type]

    def test_checklist_xlsx_path_cache_non_string_value_raises(self) -> None:
        from wiseman_hub.config import ChecklistConfig
        with pytest.raises(TypeError, match=r"xlsx_path_cache\['宮下:2026:3'\] must be str"):
            ChecklistConfig(xlsx_path_cache={"宮下:2026:3": 123})  # type: ignore[dict-item]


class TestTypeGuardHelpers:
    """Issue #27 続編 A: ``_check_*`` helper 関数群の単体テスト。"""

    def test_check_str_passes_str(self) -> None:
        from wiseman_hub.config import _check_str
        _check_str("field", "value")  # raises なし

    @pytest.mark.parametrize("bad", [123, None, [], {}, True])
    def test_check_str_raises_on_non_str(self, bad: object) -> None:
        from wiseman_hub.config import _check_str
        with pytest.raises(TypeError, match="field must be str"):
            _check_str("field", bad)

    def test_check_str_echo_value_false_hides_value(self) -> None:
        """PII 防御: echo_value=False で値がメッセージに含まれない。"""
        from wiseman_hub.config import _check_str
        marker = "leaked_secret_xyz"
        with pytest.raises(TypeError) as exc_info:
            _check_str("api_key", [marker], echo_value=False)
        assert marker not in str(exc_info.value)
        assert "list" in str(exc_info.value)  # 型名は出る

    def test_check_int_passes_int(self) -> None:
        from wiseman_hub.config import _check_int
        _check_int("field", 42)

    @pytest.mark.parametrize("bad", [True, False, "1", 1.5, None])
    def test_check_int_raises_on_non_int_or_bool(self, bad: object) -> None:
        """bool は int サブクラスのため明示除外。"""
        from wiseman_hub.config import _check_int
        with pytest.raises(TypeError, match="field must be int"):
            _check_int("field", bad)

    def test_check_bool_passes_bool(self) -> None:
        from wiseman_hub.config import _check_bool
        _check_bool("field", True)
        _check_bool("field", False)

    @pytest.mark.parametrize("bad", [1, 0, "true", None])
    def test_check_bool_raises_on_non_bool(self, bad: object) -> None:
        from wiseman_hub.config import _check_bool
        with pytest.raises(TypeError, match="field must be bool"):
            _check_bool("field", bad)

    def test_check_list_of_str_passes(self) -> None:
        from wiseman_hub.config import _check_list_of_str
        _check_list_of_str("field", ["a", "b", "c"])
        _check_list_of_str("field", [])  # 空 list も OK

    def test_check_list_of_str_raises_on_non_list(self) -> None:
        from wiseman_hub.config import _check_list_of_str
        with pytest.raises(TypeError, match="field must be list"):
            _check_list_of_str("field", "abc")

    def test_check_list_of_str_raises_on_non_str_element(self) -> None:
        from wiseman_hub.config import _check_list_of_str
        with pytest.raises(TypeError, match=r"field\[1\] must be str"):
            _check_list_of_str("field", ["a", 123, "c"])

    def test_check_dict_str_to_str_passes(self) -> None:
        from wiseman_hub.config import _check_dict_str_to_str
        _check_dict_str_to_str("field", {"k": "v"})
        _check_dict_str_to_str("field", {})  # 空 dict も OK

    def test_check_dict_str_to_str_raises_on_non_dict(self) -> None:
        from wiseman_hub.config import _check_dict_str_to_str
        with pytest.raises(TypeError, match="field must be dict"):
            _check_dict_str_to_str("field", [("k", "v")])

    def test_check_dict_str_to_str_raises_on_non_str_key(self) -> None:
        from wiseman_hub.config import _check_dict_str_to_str
        with pytest.raises(TypeError, match="field key must be str"):
            _check_dict_str_to_str("field", {1: "v"})

    def test_check_dict_str_to_str_raises_on_non_str_value(self) -> None:
        from wiseman_hub.config import _check_dict_str_to_str
        with pytest.raises(TypeError, match=r"field\['k'\] must be str"):
            _check_dict_str_to_str("field", {"k": 123})


class TestLoadConfigWithValidation:
    """load_config が検証エラーを伝播することを確認。"""

    def test_invalid_bbox_in_toml_propagates(self, tmp_path: Path) -> None:
        """TOML に反転 bbox を書くと load_config が ValueError を伝播する。"""
        toml_content = """\
[pdf_merge.user_name_bbox]
x0 = 100.0
y0 = 10.0
x1 = 50.0
y1 = 80.0
dpi = 200
"""
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content, encoding="utf-8")

        with pytest.raises(ValueError, match="x0 .* must be less than x1"):
            load_config(config_file)

    def test_invalid_concat_order_in_toml_propagates(self, tmp_path: Path) -> None:
        toml_content = """\
[pdf_merge]
concat_order = ["A", "X"]
"""
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content, encoding="utf-8")

        with pytest.raises(ValueError, match="unknown source"):
            load_config(config_file)

    def test_invalid_ocr_timeout_in_toml_propagates(self, tmp_path: Path) -> None:
        toml_content = """\
[ocr_backend]
timeout_sec = 0
"""
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content, encoding="utf-8")

        with pytest.raises(ValueError, match="timeout_sec must be positive"):
            load_config(config_file)

    def test_nan_bbox_coord_in_toml_propagates(self, tmp_path: Path) -> None:
        """Issue #152: TOML の ``nan`` リテラル座標を起動時 ValueError で fail-close。

        TOML 1.0 仕様で ``nan`` / ``inf`` / ``-inf`` は float リテラルとして
        解釈される (https://toml.io/en/v1.0.0#float)。手書き編集や設定ミスで
        NaN が混入しても dataclass の ``math.isfinite`` チェックで起動時に拒否。
        """
        toml_content = """\
[pdf_merge.user_name_bbox]
x0 = nan
y0 = 10.0
x1 = 100.0
y1 = 80.0
dpi = 200
"""
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content, encoding="utf-8")

        with pytest.raises(ValueError, match="x0 must be finite"):
            load_config(config_file)

    def test_bool_bbox_coord_in_toml_propagates(self, tmp_path: Path) -> None:
        """Issue #27 §2: TOML の ``x0 = true`` は TypeError で起動時拒否。

        bool は int サブクラスで silent にすり抜ける可能性があるため
        ``isinstance(v, bool)`` で明示除外。
        """
        toml_content = """\
[pdf_merge.user_name_bbox]
x0 = true
y0 = 10.0
x1 = 100.0
y1 = 80.0
"""
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content, encoding="utf-8")

        with pytest.raises(TypeError, match="x0 must be int or float"):
            load_config(config_file)

    def test_non_string_endpoint_in_toml_propagates(self, tmp_path: Path) -> None:
        """Issue #27 §2: TOML の ``endpoint_url = 123`` は TypeError で起動時拒否。"""
        toml_content = """\
[ocr_backend]
endpoint_url = 123
"""
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content, encoding="utf-8")

        with pytest.raises(TypeError, match="endpoint_url must be str"):
            load_config(config_file)

    def test_non_string_gcp_project_id_in_toml_propagates(
        self, tmp_path: Path
    ) -> None:
        """Issue #27 続編 A: TOML の ``[gcp] project_id = 123`` は TypeError で起動時拒否。"""
        toml_content = """\
[gcp]
project_id = 123
"""
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content, encoding="utf-8")

        with pytest.raises(TypeError, match="GcpConfig.project_id must be str"):
            load_config(config_file)

    def test_non_int_updater_check_interval_in_toml_propagates(
        self, tmp_path: Path
    ) -> None:
        """Issue #27 続編 A: TOML の ``[updater] check_interval_hours = "1"`` は TypeError。"""
        toml_content = """\
[updater]
check_interval_hours = "1"
"""
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content, encoding="utf-8")

        with pytest.raises(TypeError, match="check_interval_hours must be int"):
            load_config(config_file)


class TestLoadConfigSectionTypeGuards:
    """Issue #27 続編 B (Codex PR #260 review): load_config の section 値型ガード。

    旧 ``dict(data.get("gcp", {}))`` 強制変換と ``if routing_data:`` falsy 判定が
    silent 通過させていた経路を厳格化。dataclass `__post_init__` 型ガード設計が
    load_config 層で **無効化されない** ことを保証する。
    """

    @pytest.mark.parametrize(
        "section",
        ["app", "wiseman", "schedule", "gcp", "updater", "ocr_backend", "pdf_merge", "checklist"],
    )
    def test_array_section_raises_type_error(
        self, tmp_path: Path, section: str
    ) -> None:
        """TOML で ``gcp = []`` 等の array を section 値に書くと TypeError fail-close。

        旧コードは ``dict([])`` で ``{}`` 化、設定ミスを default で黙殺していた。
        """
        toml_content = f"{section} = []\n"
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content, encoding="utf-8")

        with pytest.raises(TypeError, match=f"\\[{section}\\] section must be a table"):
            load_config(config_file)

    def test_string_section_raises_type_error(self, tmp_path: Path) -> None:
        """TOML で ``wiseman = "string"`` のような scalar は TypeError。"""
        toml_content = 'wiseman = "string"\n'
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content, encoding="utf-8")

        with pytest.raises(TypeError, match=r"\[wiseman\] section must be a table"):
            load_config(config_file)

    def test_integer_section_raises_type_error(self, tmp_path: Path) -> None:
        """TOML で ``schedule = 123`` のような scalar は TypeError。"""
        toml_content = "schedule = 123\n"
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content, encoding="utf-8")

        with pytest.raises(TypeError, match=r"\[schedule\] section must be a table"):
            load_config(config_file)

    def test_empty_dict_section_passes(self, tmp_path: Path) -> None:
        """TOML で ``[wiseman]`` (空 section) は OK (default 値で構築)。"""
        toml_content = "[wiseman]\n"
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content, encoding="utf-8")

        cfg = load_config(config_file)
        assert cfg.wiseman.exe_path == ""
        assert cfg.wiseman.startup_wait_sec == 15

    def test_checklist_facility_routing_array_raises(self, tmp_path: Path) -> None:
        """Issue #27 続編 B: TOML ``facility_routing = []`` (空 list) は TypeError。

        旧コード ``if routing_data: ... isinstance check`` は空 list を falsy 判定で
        if 分岐に入らず silent 通過させていた (Codex 致命的指摘)。
        """
        toml_content = """\
[checklist]
facility_routing = []
"""
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content, encoding="utf-8")

        with pytest.raises(TypeError, match=r"facility_routing\] must be a table"):
            load_config(config_file)

    def test_checklist_facility_routing_false_raises(self, tmp_path: Path) -> None:
        """TOML ``facility_routing = false`` も TypeError (旧コードでは silent 通過)。"""
        toml_content = """\
[checklist]
facility_routing = false
"""
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content, encoding="utf-8")

        with pytest.raises(TypeError, match=r"facility_routing\] must be a table"):
            load_config(config_file)

    def test_checklist_report_staff_zero_raises(self, tmp_path: Path) -> None:
        """TOML ``report_staff = 0`` も TypeError (falsy int の silent 通過防止)。"""
        toml_content = """\
[checklist]
report_staff = 0
"""
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content, encoding="utf-8")

        with pytest.raises(TypeError, match=r"report_staff\] must be a table"):
            load_config(config_file)

    def test_checklist_xlsx_path_cache_string_raises(self, tmp_path: Path) -> None:
        """TOML ``xlsx_path_cache = "not-a-dict"`` は TypeError。"""
        toml_content = """\
[checklist]
xlsx_path_cache = "not-a-dict"
"""
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content, encoding="utf-8")

        with pytest.raises(TypeError, match=r"xlsx_path_cache\] must be a table"):
            load_config(config_file)

    def test_checklist_empty_routing_table_passes(self, tmp_path: Path) -> None:
        """TOML ``facility_routing = {}`` (空 dict 明示) は OK (空 dict として構築)。"""
        toml_content = """\
[checklist]
facility_routing = {}
"""
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content, encoding="utf-8")

        cfg = load_config(config_file)
        assert cfg.checklist.facility_routing == {}

    def test_default_toml_loads_after_section_type_guards(self) -> None:
        """既存 ``config/default.toml`` が section 型ガード追加後も読み込めること (regression)。"""
        cfg = load_config(Path("config/default.toml"))
        assert isinstance(cfg, AppConfig)

    def test_checklist_xlsx_path_cache_array_raises(self, tmp_path: Path) -> None:
        """Codex review (PR #261): xlsx_path_cache = [] (空 list) も TypeError。

        他 sibling (facility_routing, report_staff) と対称性確保。
        """
        toml_content = """\
[checklist]
xlsx_path_cache = []
"""
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content, encoding="utf-8")

        with pytest.raises(TypeError, match=r"xlsx_path_cache\] must be a table"):
            load_config(config_file)

    def test_pdf_merge_facility_aliases_array_raises(self, tmp_path: Path) -> None:
        """Codex PR #261 review 致命的残存: facility_aliases = [] が silent 通過していた。

        旧 ``_coerce_facility_aliases`` の ``dict(aliases_data).items()`` は
        ``[]`` を ``dict([])`` で ``{}`` 化していた。本 PR で先頭に
        ``_require_section_table`` を入れて fail-close する。
        """
        toml_content = """\
[pdf_merge]
facility_aliases = []
"""
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content, encoding="utf-8")

        with pytest.raises(TypeError, match=r"facility_aliases\] section must be a table"):
            load_config(config_file)

    def test_pdf_merge_facility_aliases_string_raises(self, tmp_path: Path) -> None:
        """同上: facility_aliases = "string" も TypeError。"""
        toml_content = """\
[pdf_merge]
facility_aliases = "not-a-table"
"""
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content, encoding="utf-8")

        with pytest.raises(TypeError, match=r"facility_aliases\] section must be a table"):
            load_config(config_file)

    # ------------------------------------------------------------------
    # Issue #27 続編 D (silent-failure-hunter rating 6):
    # reports section の inline isinstance を _require_section_table に統一 +
    # user_name_bbox を _require_section_table でラップして named error 化。
    # ------------------------------------------------------------------

    def test_reports_section_array_raises(self, tmp_path: Path) -> None:
        """TOML ``reports = []`` も他 section と同じ ``_require_section_table`` 経路。"""
        toml_content = "reports = []\n"
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content, encoding="utf-8")

        with pytest.raises(TypeError, match=r"\[reports\] section must be a table"):
            load_config(config_file)

    def test_reports_section_string_raises(self, tmp_path: Path) -> None:
        """TOML ``reports = "bad"`` も named ``[reports] section`` で TypeError。

        Issue #150 で導入されたエラーパス。続編 D で他 section と message 統一。
        """
        toml_content = 'reports = "bad"\n'
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content, encoding="utf-8")

        with pytest.raises(TypeError, match=r"\[reports\] section must be a table"):
            load_config(config_file)

    def test_reports_section_integer_raises(self, tmp_path: Path) -> None:
        """TOML ``reports = 0`` (falsy int) も silent 通過させず TypeError。"""
        toml_content = "reports = 0\n"
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content, encoding="utf-8")

        with pytest.raises(TypeError, match=r"\[reports\] section must be a table"):
            load_config(config_file)

    def test_reports_targets_non_list_raises(self, tmp_path: Path) -> None:
        """TOML ``[reports]\\ntargets = "bad"`` は inline list check で TypeError。"""
        toml_content = """\
[reports]
targets = "bad"
"""
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content, encoding="utf-8")

        with pytest.raises(TypeError, match=r"\[reports\]\.targets must be a list"):
            load_config(config_file)

    def test_reports_targets_element_non_dict_raises(self, tmp_path: Path) -> None:
        """TOML ``targets = ["bad"]`` の element 型違反は named ``[reports].targets[i]``。"""
        toml_content = """\
[reports]
targets = ["bad-entry-not-a-table"]
"""
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content, encoding="utf-8")

        with pytest.raises(
            TypeError, match=r"\[reports\]\.targets\[0\] must be a table"
        ):
            load_config(config_file)

    def test_user_name_bbox_array_raises_named_error(self, tmp_path: Path) -> None:
        """Issue #27 続編 D: TOML ``user_name_bbox = []`` は named error で TypeError。

        旧コード ``UserNameBBox(**bbox_data)`` は generic
        ``TypeError: argument of type 'list' is not a mapping`` を raise し、
        どの section の問題か特定できなかった。``_require_section_table`` 経由で
        ``[pdf_merge.user_name_bbox]`` が明示される。
        """
        toml_content = """\
[pdf_merge]
user_name_bbox = []
"""
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content, encoding="utf-8")

        with pytest.raises(
            TypeError, match=r"\[pdf_merge\.user_name_bbox\] section must be a table"
        ):
            load_config(config_file)

    def test_user_name_bbox_string_raises_named_error(self, tmp_path: Path) -> None:
        """``user_name_bbox = "bad"`` も named error で TypeError。"""
        toml_content = """\
[pdf_merge]
user_name_bbox = "not-a-bbox"
"""
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content, encoding="utf-8")

        with pytest.raises(
            TypeError, match=r"\[pdf_merge\.user_name_bbox\] section must be a table"
        ):
            load_config(config_file)

    def test_user_name_bbox_falsy_int_raises_named_error(self, tmp_path: Path) -> None:
        """``user_name_bbox = 0`` (falsy int) も silent 通過させず named error。"""
        toml_content = """\
[pdf_merge]
user_name_bbox = 0
"""
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content, encoding="utf-8")

        with pytest.raises(
            TypeError, match=r"\[pdf_merge\.user_name_bbox\] section must be a table"
        ):
            load_config(config_file)

    def test_user_name_bbox_empty_table_uses_defaults(self, tmp_path: Path) -> None:
        """``[pdf_merge.user_name_bbox]`` (空 table) は default 値で構築できること (regression)。"""
        toml_content = """\
[pdf_merge.user_name_bbox]
"""
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content, encoding="utf-8")

        cfg = load_config(config_file)
        # UserNameBBox default 値で構築されること
        assert cfg.pdf_merge.user_name_bbox.dpi == 200  # default dpi

    def test_whitespace_endpoint_in_toml_keeps_unconfigured(self, tmp_path: Path) -> None:
        """Issue #152: TOML の空白文字列のみ endpoint_url は ``is_configured=False``。

        手書き編集で ``endpoint_url = "   "`` が永続化されたケースでも、
        load_config 経由で構築した dataclass の ``is_configured`` が False を
        返すこと (HTTP 呼出時 runtime 失敗ではなく起動時 gate で disable)。
        """
        toml_content = """\
[ocr_backend]
endpoint_url = "   "
api_key = "valid-key"
"""
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content, encoding="utf-8")

        cfg = load_config(config_file)
        assert cfg.ocr_backend.is_configured is False

    def test_default_toml_loads_successfully(self) -> None:
        """既存 config/default.toml が新検証下でも回帰なく読める（regression guard）。"""
        config = load_config(Path("config/default.toml"))
        assert isinstance(config, AppConfig)


class TestSaKeyPathResolution:
    """SA キーパスの絶対化ロジック検証 (実機 exe 配布レイアウトでの重複防止)。"""

    def test_resolves_sibling_when_value_is_filename_only(
        self, tmp_path: Path
    ) -> None:
        cfg_dir = tmp_path / "any"
        cfg_dir.mkdir()
        cfg_path = cfg_dir / "default.toml"
        cfg_path.write_text(
            '[gcp]\nservice_account_key_path = "sa-key.json"\n', encoding="utf-8"
        )
        config = load_config(cfg_path)
        assert config.gcp.service_account_key_path == str(
            (cfg_dir / "sa-key.json").resolve()
        )

    def test_avoids_duplicate_config_segment_for_distribution_layout(
        self, tmp_path: Path
    ) -> None:
        """実機 exe 配布レイアウト ($HOME/wiseman-hub/config/default.toml) で
        TOML 値 "config/sa-key.json" が config/config/sa-key.json に二重化
        されない (本番障害再現テスト)。"""
        dist_root = tmp_path / "wiseman-hub"
        cfg_dir = dist_root / "config"
        cfg_dir.mkdir(parents=True)
        cfg_path = cfg_dir / "default.toml"
        cfg_path.write_text(
            '[gcp]\nservice_account_key_path = "config/sa-key.json"\n',
            encoding="utf-8",
        )
        config = load_config(cfg_path)
        # 期待: $tmp/wiseman-hub/config/sa-key.json (重複なし)
        expected = (dist_root / "config" / "sa-key.json").resolve()
        assert config.gcp.service_account_key_path == str(expected)

    def test_keeps_absolute_path_unchanged(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "default.toml"
        abs_key = tmp_path / "external" / "sa-key.json"
        cfg_path.write_text(
            f'[gcp]\nservice_account_key_path = "{abs_key.as_posix()}"\n',
            encoding="utf-8",
        )
        config = load_config(cfg_path)
        # _resolve_sa_key_path は str(Path) を返す = OS native 区切り
        # （Windows: "C:\\..\\sa-key.json" / POSIX: "/.../sa-key.json"）
        assert config.gcp.service_account_key_path == str(abs_key)

    def test_empty_value_remains_empty(self, tmp_path: Path) -> None:
        """GCP 機能未使用環境では空文字列のままにする (既存運用維持)。"""
        cfg_path = tmp_path / "default.toml"
        cfg_path.write_text(
            '[gcp]\nservice_account_key_path = ""\n', encoding="utf-8"
        )
        config = load_config(cfg_path)
        assert config.gcp.service_account_key_path == ""


class TestChecklistStaffPathExtension:
    """T1: report_staff suggest_patterns + xlsx_path_cache の TOML 往復・検証。"""

    def test_load_suggest_patterns(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "cfg.toml"
        cfg_path.write_text(
            """\
[checklist.report_staff."宮下"]
base_dir = "\\\\\\\\Tera-station\\\\share\\\\PT 宮下"
suggest_patterns = [
    "リハ経過報告書/令和*年/リハ経過報告書*{month}月*.xlsx",
]
""",
            encoding="utf-8",
        )
        cfg = load_config(cfg_path)
        entry = cfg.checklist.report_staff["宮下"]
        assert entry.base_dir == "\\\\Tera-station\\share\\PT 宮下"
        assert entry.suggest_patterns == [
            "リハ経過報告書/令和*年/リハ経過報告書*{month}月*.xlsx",
        ]
        # deprecated フィールドは空のまま
        assert entry.year_subfolder_template == ""
        assert entry.file_template == ""

    def test_load_legacy_template_only_entry(self, tmp_path: Path) -> None:
        """後方互換: 旧 *_template のみの entry が動く（suggest_patterns 未指定）。"""
        cfg_path = tmp_path / "cfg.toml"
        cfg_path.write_text(
            """\
[checklist.report_staff."宮下"]
base_dir = "\\\\\\\\Tera-station\\\\share\\\\PT 宮下"
year_subfolder_template = "リハ経過報告書\\\\令和{era}年"
file_template = "リハ経過報告書 (宮下) {month}月 .xlsx"
""",
            encoding="utf-8",
        )
        cfg = load_config(cfg_path)
        entry = cfg.checklist.report_staff["宮下"]
        assert entry.suggest_patterns == []
        assert entry.year_subfolder_template == "リハ経過報告書\\令和{era}年"
        assert entry.file_template == "リハ経過報告書 (宮下) {month}月 .xlsx"

    def test_suggest_patterns_must_be_list(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "cfg.toml"
        cfg_path.write_text(
            """\
[checklist.report_staff."宮下"]
base_dir = "/x"
suggest_patterns = "not-a-list"
""",
            encoding="utf-8",
        )
        with pytest.raises(TypeError, match="suggest_patterns must be a list"):
            load_config(cfg_path)

    def test_suggest_patterns_elements_must_be_str(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "cfg.toml"
        cfg_path.write_text(
            """\
[checklist.report_staff."宮下"]
base_dir = "/x"
suggest_patterns = ["ok", 123]
""",
            encoding="utf-8",
        )
        with pytest.raises(TypeError, match="elements must be strings"):
            load_config(cfg_path)

    def test_load_xlsx_path_cache(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "cfg.toml"
        cfg_path.write_text(
            """\
[checklist.xlsx_path_cache]
"宮下:2026:3" = "\\\\\\\\Tera-station\\\\share\\\\PT 宮下\\\\xx.xlsx"
"小島:2026:3" = "\\\\\\\\Tera-station\\\\share\\\\PT 小島\\\\yy.xlsx"
""",
            encoding="utf-8",
        )
        cfg = load_config(cfg_path)
        cache = cfg.checklist.xlsx_path_cache
        assert cache["宮下:2026:3"] == "\\\\Tera-station\\share\\PT 宮下\\xx.xlsx"
        assert cache["小島:2026:3"] == "\\\\Tera-station\\share\\PT 小島\\yy.xlsx"

    def test_xlsx_path_cache_must_be_table(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "cfg.toml"
        cfg_path.write_text(
            """\
[checklist]
xlsx_path_cache = "not-a-table"
""",
            encoding="utf-8",
        )
        with pytest.raises(TypeError, match="xlsx_path_cache.*must be a table"):
            load_config(cfg_path)

    def test_xlsx_path_cache_values_must_be_str(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "cfg.toml"
        cfg_path.write_text(
            """\
[checklist.xlsx_path_cache]
"宮下:2026:3" = 12345
""",
            encoding="utf-8",
        )
        with pytest.raises(TypeError, match="xlsx_path_cache values must be strings"):
            load_config(cfg_path)

    def test_save_roundtrip_preserves_suggest_patterns_and_cache(
        self, tmp_path: Path
    ) -> None:
        """save_config → load_config で suggest_patterns と xlsx_path_cache が完全保持。"""
        cfg = AppConfig()
        cfg.checklist = ChecklistConfig(
            report_staff={
                "宮下": ReportStaffEntry(
                    base_dir="\\\\Tera-station\\share\\PT 宮下",
                    suggest_patterns=[
                        "リハ経過報告書/令和*年/リハ経過報告書*{month}月*.xlsx",
                    ],
                ),
                "小島": ReportStaffEntry(
                    base_dir="\\\\Tera-station\\share\\PT 小島",
                    suggest_patterns=[
                        "リハ経過報告書(新)/経過報告書*令和*{month}月(最新)*.xlsx",
                    ],
                ),
            },
            xlsx_path_cache={
                "宮下:2026:3": "\\\\Tera-station\\share\\PT 宮下\\a.xlsx",
                "小島:2026:3": "\\\\Tera-station\\share\\PT 小島\\b.xlsx",
            },
        )
        target = tmp_path / "out.toml"
        save_config(cfg, target, create_if_missing=True)
        reloaded = load_config(target)
        assert reloaded.checklist.report_staff["宮下"].suggest_patterns == [
            "リハ経過報告書/令和*年/リハ経過報告書*{month}月*.xlsx",
        ]
        assert reloaded.checklist.report_staff["小島"].suggest_patterns == [
            "リハ経過報告書(新)/経過報告書*令和*{month}月(最新)*.xlsx",
        ]
        assert reloaded.checklist.xlsx_path_cache == {
            "宮下:2026:3": "\\\\Tera-station\\share\\PT 宮下\\a.xlsx",
            "小島:2026:3": "\\\\Tera-station\\share\\PT 小島\\b.xlsx",
        }

    def test_quoted_key_with_space_roundtrip(self, tmp_path: Path) -> None:
        """半角スペース含む担当者名（"PT 宮下" 等）が tomlkit で quoted key として
        save/load round-trip 可能であることを検証（evaluator 指摘 H5 対策）。

        実機で `[checklist.report_staff."PT 宮下"]` のように使われる前提だが、
        コード上は `ChecklistRow.staff` が「宮下」のように prefix 抜きの値を持つので
        実装上は staff キーにスペースが入らないケースが主。ただし将来「OT 林」のような
        実態に近い使い方をされる場合に備えて round-trip を保証する。
        """
        cfg = AppConfig()
        cfg.checklist = ChecklistConfig(
            report_staff={
                "PT 宮下": ReportStaffEntry(
                    base_dir="\\\\Tera-station\\share\\PT 宮下",
                    suggest_patterns=["x/{month}.xlsx"],
                ),
                "OT 小林": ReportStaffEntry(
                    base_dir="\\\\Tera-station\\share\\OT小林",
                    suggest_patterns=["y/{era}.xlsx"],
                ),
            },
            xlsx_path_cache={
                "PT 宮下:2026:3": "\\\\Tera-station\\share\\PT 宮下\\a.xlsx",
            },
        )
        target = tmp_path / "out.toml"
        save_config(cfg, target, create_if_missing=True)
        text = target.read_text(encoding="utf-8")
        # quoted key で書かれていること
        assert '"PT 宮下"' in text
        assert '"OT 小林"' in text
        # round-trip
        reloaded = load_config(target)
        assert "PT 宮下" in reloaded.checklist.report_staff
        assert "OT 小林" in reloaded.checklist.report_staff
        assert reloaded.checklist.report_staff["PT 宮下"].suggest_patterns == [
            "x/{month}.xlsx",
        ]
        assert reloaded.checklist.xlsx_path_cache == {
            "PT 宮下:2026:3": "\\\\Tera-station\\share\\PT 宮下\\a.xlsx",
        }

    def test_suggest_patterns_empty_string_is_type_error(self, tmp_path: Path) -> None:
        """suggest_patterns = "" (空文字) は list 型違反として弾く（Codex M6 対策）。"""
        cfg_path = tmp_path / "cfg.toml"
        cfg_path.write_text(
            """\
[checklist.report_staff."宮下"]
base_dir = "/x"
suggest_patterns = ""
""",
            encoding="utf-8",
        )
        with pytest.raises(TypeError, match="suggest_patterns must be a list"):
            load_config(cfg_path)

    def test_save_roundtrip_with_legacy_template_entry(self, tmp_path: Path) -> None:
        """旧 *_template のみのエントリも save_config 経由で TOML 往復可能。"""
        cfg = AppConfig()
        cfg.checklist = ChecklistConfig(
            report_staff={
                "宮下": ReportStaffEntry(
                    base_dir="\\\\Tera-station\\share\\PT 宮下",
                    year_subfolder_template="リハ経過報告書\\令和{era}年",
                    file_template="リハ経過報告書 (宮下) {month}月 .xlsx",
                ),
            },
        )
        target = tmp_path / "out.toml"
        save_config(cfg, target, create_if_missing=True)
        reloaded = load_config(target)
        entry = reloaded.checklist.report_staff["宮下"]
        assert entry.suggest_patterns == []
        assert entry.year_subfolder_template == "リハ経過報告書\\令和{era}年"
        assert entry.file_template == "リハ経過報告書 (宮下) {month}月 .xlsx"


class TestChecklistConfigDeprecationWarning:
    """ChecklistConfig.monitoring_subfolder の legacy 値検出 (PR #233 後の救済)。

    本田様 PC 等で旧 default 値 ``08.運動器機能向上計画書`` / ``10.運動器機能向上計画書``
    が TOML に保存されている場合、PR #233 (substring match) の自動吸収が
    効かない。__post_init__ で検出 → logger.warning することで運用上気付ける。
    """

    def test_legacy_value_with_08_prefix_emits_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """旧 default ``08.運動器機能向上計画書`` で WARNING 発火。"""
        with caplog.at_level(logging.WARNING, logger="wiseman_hub.config"):
            ChecklistConfig(monitoring_subfolder="08.運動器機能向上計画書")
        assert any(
            "08.運動器機能向上計画書" in record.getMessage()
            and "運動器機能向上計画書" in record.getMessage()
            for record in caplog.records
        )

    def test_legacy_value_with_10_prefix_emits_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """業務問題の発端 ``10.運動器機能向上計画書`` も legacy 扱いで WARNING。"""
        with caplog.at_level(logging.WARNING, logger="wiseman_hub.config"):
            ChecklistConfig(monitoring_subfolder="10.運動器機能向上計画書")
        assert any(
            "10.運動器機能向上計画書" in record.getMessage()
            for record in caplog.records
        )

    def test_canonical_value_does_not_warn(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """新 default ``運動器機能向上計画書`` (canonical) は WARNING 出ない。"""
        with caplog.at_level(logging.WARNING, logger="wiseman_hub.config"):
            ChecklistConfig(monitoring_subfolder="運動器機能向上計画書")
        assert not any(
            "monitoring_subfolder" in record.getMessage()
            for record in caplog.records
        )

    def test_substring_absorbable_variant_does_not_warn(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """substring match で吸収可能なバリアント (``運動器機能向上計画書(過去分)``)
        は legacy 扱いせず WARNING 出ない。canonical name 設定は維持し、folder 側の
        揺らぎは substring match で吸収する設計のため、設定値としての WARNING は
        canonical name 完全不一致の固定 legacy 値に絞る。
        """
        with caplog.at_level(logging.WARNING, logger="wiseman_hub.config"):
            ChecklistConfig(monitoring_subfolder="運動器機能向上計画書(過去分)")
        assert not any(
            "monitoring_subfolder" in record.getMessage()
            for record in caplog.records
        )

    def test_default_construction_does_not_warn(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """引数なしの ``ChecklistConfig()`` (= 新 default 値) は WARNING 出ない。

        既存の数百件のテストが ``ChecklistConfig()`` を使っているため、
        default 構築で warning が出ないことを保証する (テスト騒音防止)。
        """
        with caplog.at_level(logging.WARNING, logger="wiseman_hub.config"):
            ChecklistConfig()
        assert not any(
            "monitoring_subfolder" in record.getMessage()
            for record in caplog.records
        )
