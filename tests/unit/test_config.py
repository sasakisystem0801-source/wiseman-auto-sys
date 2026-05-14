"""設定ローダーのユニットテスト"""

import dataclasses
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
    GcpConfig,
    OcrBackendConfig,
    PdfMergeConfig,
    ReportStaffEntry,
    ReportTarget,
    ScheduleConfig,
    UpdaterConfig,
    UserNameBBox,
    WisemanConfig,
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
    # Issue #27 続編 G §4: exe_path は Path 型
    assert config.wiseman.exe_path == Path("C:\\test\\wiseman.exe")
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
    # Issue #27 続編 G Phase 2a: input_dir / output_dir は Path 型
    assert config.pdf_merge.input_dir == Path("C:\\Users\\test\\input")
    assert config.pdf_merge.output_dir == Path("C:\\Users\\test\\output")
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
        # Issue #27 続編 E Phase 2/3b: AppConfig + PdfMergeConfig は frozen=True、replace() 経由。
        cfg = replace(
            cfg,
            pdf_merge=replace(
                cfg.pdf_merge,
                input_dir=Path("/tmp/in"),
                output_dir=Path("/tmp/out"),
                source_a_filename="A.pdf",
            ),
        )
        # Issue #27 続編 E Phase 1: OcrBackendConfig は frozen=True。
        cfg = replace(cfg, ocr_backend=replace(cfg.ocr_backend, endpoint_url="https://example.com", api_key="xyz"))
        target = tmp_path / "new.toml"
        save_config(cfg, target, create_if_missing=True)

        assert target.exists()
        reloaded = load_config(target)
        assert reloaded.log_level == "WARNING"
        assert reloaded.pdf_merge.input_dir == Path("/tmp/in")
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
        cfg = replace(cfg, pdf_merge=replace(cfg.pdf_merge, input_dir=Path("/new/in")))
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
        # Issue #27 続編 E Phase 1/2/3b: UserNameBBox / PdfMergeConfig / AppConfig 全て frozen=True。
        cfg = replace(
            cfg,
            pdf_merge=replace(
                cfg.pdf_merge,
                user_name_bbox=UserNameBBox(x0=11.0, y0=22.0, x1=333.0, y1=44.0, dpi=250),
            ),
        )
        target = tmp_path / "bbox.toml"
        save_config(cfg, target, create_if_missing=True)

        reloaded = load_config(target)
        assert reloaded.pdf_merge.user_name_bbox.x0 == 11.0
        assert reloaded.pdf_merge.user_name_bbox.y0 == 22.0
        assert reloaded.pdf_merge.user_name_bbox.x1 == 333.0
        assert reloaded.pdf_merge.user_name_bbox.y1 == 44.0
        assert reloaded.pdf_merge.user_name_bbox.dpi == 250

    def test_save_reports_targets_list(self, tmp_path: Path) -> None:
        """複数の [[reports.targets]] が正しく書き戻される。

        Issue #27 続編 F Phase 1: ``output_format`` を ``Literal["csv"]`` に
        絞り込んだため、本テストは csv 固定で複数 target のラウンドトリップを
        確認する形に変更 (旧 "xlsx" 値は許容集合外で ``ValueError``)。将来 xlsx/pdf
        を追加する際は ``OutputFormat`` Literal の拡張が前段となる。
        """
        from wiseman_hub.config import ReportTarget

        cfg = AppConfig()
        cfg.reports.append(
            ReportTarget(name="報告書1", menu_path=["A", "B"], output_format="csv")
        )
        cfg.reports.append(
            ReportTarget(name="報告書2", menu_path=["X"], output_format="csv")
        )

        target = tmp_path / "reports.toml"
        save_config(cfg, target, create_if_missing=True)

        reloaded = load_config(target)
        assert len(reloaded.reports) == 2
        assert reloaded.reports[0].name == "報告書1"
        assert reloaded.reports[0].menu_path == ["A", "B"]
        assert reloaded.reports[1].name == "報告書2"
        assert reloaded.reports[1].menu_path == ["X"]
        assert reloaded.reports[1].output_format == "csv"

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
        # Issue #27 続編 E Phase 2: WisemanConfig は frozen=True、replace() 経由。
        cfg = replace(cfg, wiseman=replace(cfg.wiseman, startup_wait_sec=25))
        save_config(cfg, target)

        reloaded = load_config(target)
        assert reloaded.wiseman.startup_wait_sec == 25
        # Issue #27 続編 G §4: exe_path は Path 型
        assert reloaded.wiseman.exe_path == Path("C:\\foo.exe")

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
        cfg = replace(cfg, pdf_merge=replace(cfg.pdf_merge, facility_root_dir="//Tera-station/share/03.FAX(事業所)"))
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
        cfg = replace(cfg, pdf_merge=replace(cfg.pdf_merge, facility_root_dir="/srv/facility"))
        save_config(cfg, target)
        reloaded = load_config(target)

        # 既存フィールドが変わらないこと（Partial Update 検証）
        assert reloaded.pdf_merge.input_dir == Path("/in")
        assert reloaded.pdf_merge.output_dir == Path("/out")
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
        cfg = replace(cfg, pdf_merge=replace(cfg.pdf_merge, concat_order=("C", "A", "B")))
        save_config(cfg, target)

        reloaded = load_config(target)
        assert reloaded.pdf_merge.concat_order == ("C", "A", "B")

    # --- ex_source_dir (.ex_ ファイル取込元フォルダ) ---

    def test_ex_source_dir_default_empty(self) -> None:
        """新規 AppConfig() で ex_source_dir はデフォルト空文字列（未設定状態）。"""
        cfg = AppConfig()
        assert cfg.pdf_merge.ex_source_dir == Path("")

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
            == Path("C:\\Users\\sasak\\OneDrive\\デスクトップ\\本田様")
        )

    def test_save_ex_source_dir_roundtrip(self, tmp_path: Path) -> None:
        """ex_source_dir の save → load ラウンドトリップ。日本語パス含む。"""
        cfg = AppConfig()
        cfg = replace(
            cfg,
            pdf_merge=replace(
                cfg.pdf_merge,
                ex_source_dir=Path("C:\\Users\\sasak\\OneDrive\\デスクトップ\\本田様"),
            ),
        )
        target = tmp_path / "roundtrip_ex.toml"
        save_config(cfg, target, create_if_missing=True)

        reloaded = load_config(target)
        assert (
            reloaded.pdf_merge.ex_source_dir
            == Path("C:\\Users\\sasak\\OneDrive\\デスクトップ\\本田様")
        )

    def test_ex_source_dir_unset_when_section_missing(self, tmp_path: Path) -> None:
        """[pdf_merge] セクションがない TOML でも ex_source_dir は "" を返す。"""
        target = tmp_path / "nopdfmerge_ex.toml"
        target.write_text('[app]\nversion = "1.0.0"\n', encoding="utf-8")

        cfg = load_config(target)
        assert cfg.pdf_merge.ex_source_dir == Path("")

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
        cfg = replace(cfg, pdf_merge=replace(cfg.pdf_merge, ex_source_dir=Path("/srv/ex_source")))
        save_config(cfg, target)
        reloaded = load_config(target)

        # 既存フィールドが変わらないこと（Partial Update 検証）
        assert reloaded.pdf_merge.input_dir == Path("/in")
        assert reloaded.pdf_merge.output_dir == Path("/out")
        assert reloaded.pdf_merge.source_a_filename == "A.pdf"
        assert reloaded.pdf_merge.source_d_filename == "D.pdf"
        assert reloaded.pdf_merge.source_b_pattern == "B_{name}.pdf"
        assert reloaded.pdf_merge.source_c_pattern == "C_{name}.pdf"
        assert reloaded.pdf_merge.concat_order == ("A", "C", "B")
        assert reloaded.pdf_merge.facility_root_dir == "/srv/facility"
        assert reloaded.pdf_merge.user_name_bbox.x0 == 11.0
        assert reloaded.pdf_merge.user_name_bbox.dpi == 250
        # 新フィールドが反映されること
        assert reloaded.pdf_merge.ex_source_dir == Path("/srv/ex_source")

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
        cfg = replace(
            cfg,
            pdf_merge=replace(
                cfg.pdf_merge,
                facility_aliases={
                    "本田デイケア": ["本田DC", "本田デイ"],
                    "きなり(メール)※持参": ["きなり"],
                },
            ),
        )
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
        cfg = replace(cfg, pdf_merge=replace(cfg.pdf_merge, facility_aliases={"本田デイケア": ["本田DC"]}))
        save_config(cfg, target)
        reloaded = load_config(target)

        # 既存フィールドが変わらないこと
        assert reloaded.pdf_merge.input_dir == Path("/in")
        assert reloaded.pdf_merge.output_dir == Path("/out")
        assert reloaded.pdf_merge.source_a_filename == "A.pdf"
        assert reloaded.pdf_merge.source_d_filename == "D.pdf"
        assert reloaded.pdf_merge.source_b_pattern == "B_{name}.pdf"
        assert reloaded.pdf_merge.source_c_pattern == "C_{name}.pdf"
        assert reloaded.pdf_merge.concat_order == ("A", "C", "B")
        assert reloaded.pdf_merge.facility_root_dir == "/srv/facility"
        assert reloaded.pdf_merge.ex_source_dir == Path("/srv/ex")
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
        cfg = replace(cfg, pdf_merge=replace(cfg.pdf_merge, facility_aliases={"本田デイケア": ["本田DC"]}))
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

        cfg = replace(cfg, pdf_merge=replace(cfg.pdf_merge, facility_aliases={}))
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
        # Issue #27 続編 E Phase 1/2/3b: UserNameBBox / PdfMergeConfig / AppConfig 全て frozen=True、
        # bbox + aliases を 1 つの replace() で同時更新する。
        cfg = replace(
            cfg,
            pdf_merge=replace(
                cfg.pdf_merge,
                user_name_bbox=replace(cfg.pdf_merge.user_name_bbox, x0=99.0),
                facility_aliases={
                    "本田デイケア": ["本田DC", "本田デイ"],
                    "きなり": ["きなり訪問"],
                },
            ),
        )
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
        cfg = replace(cfg, pdf_merge=replace(cfg.pdf_merge, input_dir=Path("/private/施設A/patient/山田太郎")))

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


class TestFrozenInstanceImmutability:
    """Issue #27 続編 E Phase 1: ``UserNameBBox`` / ``OcrBackendConfig`` frozen 化検証。

    PR #258 type-design-analyzer rating 7 指摘対応。post-construction mutation
    (``cfg.endpoint_url = "  "`` 等) で ``__post_init__`` 型ガードを bypass する
    経路を構造的に防ぐため両 dataclass を ``frozen=True`` 化する。本クラスは:
      1. 各フィールドへの post-construction 代入が ``FrozenInstanceError`` で拒否される
      2. ``replace()`` 経由の新インスタンス生成は ``__post_init__`` を再発火する
    を固定する。
    """

    @pytest.mark.parametrize(
        "field_name,new_value",
        [
            ("x0", 99.0),
            ("y0", 99.0),
            ("x1", 99.0),
            ("y1", 99.0),
            ("dpi", 250),
        ],
    )
    def test_user_name_bbox_frozen_field_assignment_raises(
        self, field_name: str, new_value: object
    ) -> None:
        """UserNameBBox の各フィールドへの post-construction 代入は FrozenInstanceError。"""
        from dataclasses import FrozenInstanceError

        bbox = UserNameBBox(x0=10.0, y0=20.0, x1=100.0, y1=50.0, dpi=200)
        with pytest.raises(FrozenInstanceError):
            setattr(bbox, field_name, new_value)

    @pytest.mark.parametrize(
        "field_name,new_value",
        [
            ("endpoint_url", "https://x"),
            ("api_key", "x"),
            ("timeout_sec", 60),
            ("max_retries", 5),
        ],
    )
    def test_ocr_backend_config_frozen_field_assignment_raises(
        self, field_name: str, new_value: object
    ) -> None:
        """OcrBackendConfig の各フィールドへの post-construction 代入は FrozenInstanceError。"""
        from dataclasses import FrozenInstanceError

        cfg = OcrBackendConfig(endpoint_url="https://example.com", api_key="abc")
        with pytest.raises(FrozenInstanceError):
            setattr(cfg, field_name, new_value)

    def test_user_name_bbox_replace_reapplies_post_init_validation(self) -> None:
        """replace() で新規構築時に __post_init__ が再評価される (反転 bbox は拒否)。"""
        bbox = UserNameBBox(x0=10.0, y0=20.0, x1=100.0, y1=50.0, dpi=200)
        # 反転 (x0 >= x1) は __post_init__ の不変条件違反で ValueError
        with pytest.raises(ValueError, match=r"x0 .* must be less than x1"):
            replace(bbox, x1=5.0)

    def test_ocr_backend_config_replace_reapplies_post_init_validation(self) -> None:
        """replace() で新規構築時に __post_init__ 型ガードが再評価される。"""
        cfg = OcrBackendConfig(endpoint_url="https://example.com", api_key="abc")
        # bool は int サブクラスでもガード対象
        with pytest.raises(TypeError, match="timeout_sec must be int"):
            replace(cfg, timeout_sec=True)  # type: ignore[arg-type]

    # --- Issue #27 続編 E Phase 2: PdfMergeConfig + WisemanConfig frozen 化 ---

    @pytest.mark.parametrize(
        "field_name,new_value",
        [
            ("exe_path", "C:/new.exe"),
            ("startup_wait_sec", 30),
            ("window_title_pattern", ".*new.*"),
        ],
    )
    def test_wiseman_config_frozen_field_assignment_raises(
        self, field_name: str, new_value: object
    ) -> None:
        """WisemanConfig の各フィールドへの post-construction 代入は FrozenInstanceError。"""
        cfg = WisemanConfig(exe_path=Path("C:/wiseman.exe"))
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(cfg, field_name, new_value)

    def test_wiseman_config_replace_reapplies_post_init_validation(self) -> None:
        """replace() で新規構築時に __post_init__ 型ガードが再評価される。"""
        cfg = WisemanConfig(exe_path=Path("C:/wiseman.exe"))
        # bool は int サブクラスでもガード対象 (silent: True == 1 で startup_wait_sec=True
        # が sleep 経路で動作してしまう問題を起動時に弾く)
        with pytest.raises(TypeError, match="startup_wait_sec must be int"):
            replace(cfg, startup_wait_sec=True)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "field_name,new_value",
        [
            ("input_dir", "/new/in"),
            ("output_dir", "/new/out"),
            ("source_a_filename", "X.pdf"),
            ("source_d_filename", "Y.pdf"),
            ("source_b_pattern", "B2_{name}.pdf"),
            ("source_c_pattern", "C2_{name}.pdf"),
            ("concat_order", ("C", "B", "A")),
            ("facility_root_dir", "/new/facility"),
            ("ex_source_dir", "/new/ex"),
            ("facility_aliases", {"X": ["Y"]}),
        ],
    )
    def test_pdf_merge_config_frozen_field_assignment_raises(
        self, field_name: str, new_value: object
    ) -> None:
        """PdfMergeConfig の各フィールドへの post-construction 代入は FrozenInstanceError。"""
        cfg = PdfMergeConfig()
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(cfg, field_name, new_value)

    def test_pdf_merge_config_replace_reapplies_post_init_validation(self) -> None:
        """replace() で新規構築時に __post_init__ 不変条件チェックが再評価される。"""
        cfg = PdfMergeConfig()
        # concat_order 重複は __post_init__ の不変条件違反で ValueError
        with pytest.raises(ValueError, match="duplicates"):
            replace(cfg, concat_order=("A", "A"))

    def test_pdf_merge_config_user_name_bbox_replace_reapplies_validation(self) -> None:
        """ネストした UserNameBBox の replace 経由更新でも不変条件が再評価される。"""
        cfg = PdfMergeConfig()
        # bbox 反転は UserNameBBox.__post_init__ の不変条件違反
        with pytest.raises(ValueError, match=r"x0 .* must be less than x1"):
            replace(
                cfg,
                user_name_bbox=UserNameBBox(x0=100.0, y0=20.0, x1=50.0, y1=80.0),
            )

    # --- Issue #27 続編 E Phase 3a: 残 6 dataclass frozen 化 ---

    @pytest.mark.parametrize(
        "field_name,new_value",
        [("enabled", True), ("cron", "0 9 * * *")],
    )
    def test_schedule_config_frozen_field_assignment_raises(
        self, field_name: str, new_value: object
    ) -> None:
        """ScheduleConfig の各フィールドへの post-construction 代入は FrozenInstanceError。"""
        from wiseman_hub.config import ScheduleConfig

        cfg = ScheduleConfig()
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(cfg, field_name, new_value)

    def test_schedule_config_replace_reapplies_post_init_validation(self) -> None:
        """replace() で __post_init__ 型ガードが再評価される。"""
        from wiseman_hub.config import ScheduleConfig

        cfg = ScheduleConfig()
        with pytest.raises(TypeError, match="cron must be str"):
            replace(cfg, cron=123)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "field_name,new_value",
        [
            ("name", "new-report"),
            ("menu_path", ["A", "B"]),
            ("output_format", "xlsx"),
        ],
    )
    def test_report_target_frozen_field_assignment_raises(
        self, field_name: str, new_value: object
    ) -> None:
        """ReportTarget の各フィールドへの post-construction 代入は FrozenInstanceError。"""
        from wiseman_hub.config import ReportTarget

        cfg = ReportTarget()
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(cfg, field_name, new_value)

    def test_report_target_replace_reapplies_post_init_validation(self) -> None:
        """replace() で menu_path に str を渡したら TypeError (list[str] 期待)。"""
        from wiseman_hub.config import ReportTarget

        cfg = ReportTarget()
        with pytest.raises(TypeError, match="menu_path must be list"):
            replace(cfg, menu_path="not-a-list")  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "field_name,new_value",
        [
            ("project_id", "x"),
            ("bucket_name", "x"),
            ("data_bucket_name", "x"),
            ("release_bucket_name", "x"),
            ("service_account_key_path", "x"),
            ("region", "asia-northeast2"),
        ],
    )
    def test_gcp_config_frozen_field_assignment_raises(
        self, field_name: str, new_value: object
    ) -> None:
        """GcpConfig の各フィールドへの post-construction 代入は FrozenInstanceError。"""
        from wiseman_hub.config import GcpConfig

        cfg = GcpConfig()
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(cfg, field_name, new_value)

    def test_gcp_config_replace_reapplies_post_init_validation(self) -> None:
        """replace() で project_id に int を渡したら TypeError。"""
        from wiseman_hub.config import GcpConfig

        cfg = GcpConfig()
        with pytest.raises(TypeError, match="project_id must be str"):
            replace(cfg, project_id=42)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "field_name,new_value",
        [
            ("enabled", True),
            ("check_interval_hours", 24),
            ("release_bucket", "x"),
        ],
    )
    def test_updater_config_frozen_field_assignment_raises(
        self, field_name: str, new_value: object
    ) -> None:
        """UpdaterConfig の各フィールドへの post-construction 代入は FrozenInstanceError。"""
        from wiseman_hub.config import UpdaterConfig

        cfg = UpdaterConfig()
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(cfg, field_name, new_value)

    def test_updater_config_replace_reapplies_post_init_validation(self) -> None:
        """replace() で check_interval_hours に bool を渡したら TypeError (int サブクラス除外)。"""
        from wiseman_hub.config import UpdaterConfig

        cfg = UpdaterConfig()
        with pytest.raises(TypeError, match="check_interval_hours must be int"):
            replace(cfg, check_interval_hours=True)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "field_name,new_value",
        [
            ("base_dir", "/x"),
            ("suggest_patterns", ["a.xlsx"]),
            ("year_subfolder_template", "x"),
            ("file_template", "x"),
        ],
    )
    def test_report_staff_entry_frozen_field_assignment_raises(
        self, field_name: str, new_value: object
    ) -> None:
        """ReportStaffEntry の各フィールドへの post-construction 代入は FrozenInstanceError。"""
        cfg = ReportStaffEntry()
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(cfg, field_name, new_value)

    def test_report_staff_entry_replace_reapplies_post_init_validation(self) -> None:
        """replace() で suggest_patterns に str を渡したら TypeError。"""
        cfg = ReportStaffEntry()
        with pytest.raises(TypeError, match="suggest_patterns must be list"):
            replace(cfg, suggest_patterns="not-a-list")  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "field_name,new_value",
        [
            ("spreadsheet_id", "x"),
            ("karte_root", "x"),
            ("monitoring_subfolder", "x"),
            ("fax_root", "x"),
            ("b_output_subfolder", "x"),
            ("c_output_subfolder", "x"),
            ("facility_routing", {"x": "y"}),
            ("report_staff", {"x": ReportStaffEntry()}),
            ("xlsx_path_cache", {"x": "y"}),
        ],
    )
    def test_checklist_config_frozen_field_assignment_raises(
        self, field_name: str, new_value: object
    ) -> None:
        """ChecklistConfig の各フィールドへの post-construction 代入は FrozenInstanceError。"""
        cfg = ChecklistConfig()
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(cfg, field_name, new_value)

    def test_checklist_config_replace_reapplies_post_init_validation(self) -> None:
        """replace() で facility_routing に list を渡したら TypeError (dict 期待)。"""
        cfg = ChecklistConfig()
        with pytest.raises(TypeError, match="facility_routing must be dict"):
            replace(cfg, facility_routing=["x", "y"])  # type: ignore[arg-type]

    # --- Issue #27 続編 E Phase 3b: AppConfig (root) frozen 化 ---

    @pytest.mark.parametrize(
        "field_name,new_value",
        [
            # 直下 str field
            ("version", "9.9.9"),
            ("log_level", "DEBUG"),
            ("log_dir", "/tmp/x"),
            # 直下 list field
            ("reports", []),
            # ネスト dataclass field (参照差し替えの阻止のみ確認、内部 mutation は別議論)
            ("wiseman", WisemanConfig(exe_path=Path("C:/x.exe"))),
            ("schedule", ScheduleConfig()),
            ("gcp", GcpConfig()),
            ("updater", UpdaterConfig()),
            ("ocr_backend", OcrBackendConfig()),
            ("pdf_merge", PdfMergeConfig()),
            ("checklist", ChecklistConfig()),
        ],
    )
    def test_app_config_frozen_field_assignment_raises(
        self, field_name: str, new_value: object
    ) -> None:
        """AppConfig 直下 11 フィールドへの post-construction 代入は FrozenInstanceError。

        ``cfg.pdf_merge = replace(...)`` のような旧パターンが構造的に阻止され、
        ``cfg = replace(cfg, pdf_merge=replace(cfg.pdf_merge, ...))`` への移行を
        強制する (Issue #27 続編 E Phase 3b の core invariant)。
        """
        cfg = AppConfig()
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(cfg, field_name, new_value)

    def test_app_config_replace_reapplies_post_init_validation(self) -> None:
        """replace() で version に int を渡したら TypeError (str 期待)。

        AppConfig 自身の ``__post_init__`` 型ガード (``_check_str``) が replace
        経由でも再評価される regression guard。
        """
        cfg = AppConfig()
        with pytest.raises(TypeError, match="AppConfig.version must be str"):
            replace(cfg, version=123)  # type: ignore[arg-type]

    def test_app_config_replace_nested_dataclass_reapplies_validation(self) -> None:
        """ネスト dataclass の replace 階層構造でも各層 __post_init__ が再評価される。

        Phase 3b の主要パターン (``cfg = replace(cfg, pdf_merge=replace(cfg.pdf_merge, ...))``)
        が動作することと、ネスト側 dataclass の不変条件違反が浮上することを確認。
        """
        cfg = AppConfig()
        # bbox 反転は UserNameBBox.__post_init__ の不変条件違反、
        # PdfMergeConfig.replace -> AppConfig.replace の階層で伝播する
        with pytest.raises(ValueError, match=r"x0 .* must be less than x1"):
            replace(
                cfg,
                pdf_merge=replace(
                    cfg.pdf_merge,
                    user_name_bbox=UserNameBBox(x0=100.0, y0=20.0, x1=50.0, y1=80.0),
                ),
            )

    def test_app_config_reports_list_content_mutation_not_blocked(self) -> None:
        """``cfg.reports.append(...)`` は frozen=True でも阻止されない (docstring 既述)。

        ``AppConfig.reports`` は ``list[ReportTarget]`` 型のため、参照差し替え
        (``cfg.reports = [...]``) は阻止できるが list 内容変更 (append/pop) は
        対象外。これは仕様であり、umbrella §1 で type を ``tuple`` に変える別議論
        として扱う旨を docstring に明記済み。本テストは仕様 regression guard。
        """
        cfg = AppConfig()
        # list mutation は raise しない (cfg.reports 参照は差し替わらない)
        cfg.reports.append(ReportTarget(name="ad-hoc"))
        assert len(cfg.reports) == 1
        assert cfg.reports[0].name == "ad-hoc"


class TestLiteralValidation:
    """Issue #27 続編 F Phase 1: LogLevel + OutputFormat Literal 化の値域検証。

    既存 ``ConcatSourceLetter`` パターン (Literal + frozenset + __post_init__ 検証)
    を ``AppConfig.log_level`` と ``ReportTarget.output_format`` に展開した結果、
    旧 ``_check_str`` のみでは素通りしていた誤値 ("info" 小文字 / "DEBUGGING" /
    "xlsx") が起動時 ``ValueError`` で弾かれることを保証する。
    """

    # ---- _check_literal helper 単体 ----

    def test_check_literal_passes_for_allowed_value(self) -> None:
        from wiseman_hub.config import VALID_LOG_LEVELS, _check_literal

        _check_literal("dummy", "INFO", VALID_LOG_LEVELS)  # raises nothing

    def test_check_literal_raises_for_disallowed_value(self) -> None:
        from wiseman_hub.config import VALID_LOG_LEVELS, _check_literal

        with pytest.raises(ValueError, match="not in allowed set"):
            _check_literal("dummy", "TRACE", VALID_LOG_LEVELS)

    def test_check_literal_error_message_includes_field_name(self) -> None:
        """エラー文言にフィールド名が含まれ、デバッグ時の特定が容易なことを保証。"""
        from wiseman_hub.config import VALID_OUTPUT_FORMATS, _check_literal

        with pytest.raises(ValueError, match="ReportTarget.output_format"):
            _check_literal("ReportTarget.output_format", "xlsx", VALID_OUTPUT_FORMATS)

    # ---- AppConfig.log_level ----

    def test_app_config_default_log_level_is_valid(self) -> None:
        """デフォルト 'INFO' は許容集合に含まれる (回帰防止)。"""
        cfg = AppConfig()
        assert cfg.log_level == "INFO"

    @pytest.mark.parametrize(
        "level",
        ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    )
    def test_app_config_accepts_all_valid_log_levels(self, level: str) -> None:
        cfg = AppConfig(log_level=level)  # type: ignore[arg-type]
        assert cfg.log_level == level

    @pytest.mark.parametrize(
        "invalid",
        ["info", "DEBUGGING", "TRACE", "NOTSET", "VERBOSE", ""],
    )
    def test_app_config_rejects_invalid_log_level(self, invalid: str) -> None:
        with pytest.raises(ValueError, match="AppConfig.log_level"):
            AppConfig(log_level=invalid)  # type: ignore[arg-type]

    # ---- ReportTarget.output_format ----

    def test_report_target_default_output_format_is_valid(self) -> None:
        target = ReportTarget()
        assert target.output_format == "csv"

    def test_report_target_accepts_csv(self) -> None:
        target = ReportTarget(name="X", menu_path=["a"], output_format="csv")
        assert target.output_format == "csv"

    @pytest.mark.parametrize(
        "invalid",
        ["xlsx", "pdf", "CSV", "tsv", ""],
    )
    def test_report_target_rejects_invalid_output_format(self, invalid: str) -> None:
        with pytest.raises(ValueError, match="ReportTarget.output_format"):
            ReportTarget(name="X", menu_path=["a"], output_format=invalid)  # type: ignore[arg-type]

    # ---- frozenset の中身検証 (Literal alias と single source of truth で一致) ----

    def test_valid_log_levels_matches_literal_args(self) -> None:
        """``VALID_LOG_LEVELS`` が ``LogLevel`` Literal の引数集合と完全一致。"""
        from typing import get_args

        from wiseman_hub.config import VALID_LOG_LEVELS, LogLevel

        assert frozenset(get_args(LogLevel)) == VALID_LOG_LEVELS

    def test_valid_output_formats_matches_literal_args(self) -> None:
        from typing import get_args

        from wiseman_hub.config import VALID_OUTPUT_FORMATS, OutputFormat

        assert frozenset(get_args(OutputFormat)) == VALID_OUTPUT_FORMATS


class TestCoerceConcatOrder:
    """Issue #27 続編 E Phase 2: ``_coerce_concat_order()`` helper 単体検証。

    旧 ``PdfMergeConfig.__post_init__`` 内の ``self.concat_order = tuple(...)``
    自己代入を本 helper に外出ししたため、tuple 化 + 値域検証の責務を
    集約した独立した関数として動作することを検証する。
    """

    def test_coerces_list_to_tuple(self) -> None:
        """list 入力を tuple に正規化して返す。"""
        from wiseman_hub.config import _coerce_concat_order

        result = _coerce_concat_order(["A", "B", "C"])
        assert result == ("A", "B", "C")
        assert isinstance(result, tuple)

    def test_passes_through_tuple_input(self) -> None:
        """tuple 入力はそのまま値が保持される (型は同じ tuple)。"""
        from wiseman_hub.config import _coerce_concat_order

        result = _coerce_concat_order(("A", "C", "B"))
        assert result == ("A", "C", "B")
        assert isinstance(result, tuple)

    def test_rejects_empty_input(self) -> None:
        """空入力 (list / tuple 問わず) は ValueError。"""
        from wiseman_hub.config import _coerce_concat_order

        with pytest.raises(ValueError, match="must not be empty"):
            _coerce_concat_order([])
        with pytest.raises(ValueError, match="must not be empty"):
            _coerce_concat_order(())

    def test_rejects_unknown_letter(self) -> None:
        """VALID_CONCAT_LETTERS 外の letter は ValueError。"""
        from wiseman_hub.config import _coerce_concat_order

        with pytest.raises(ValueError, match="unknown source"):
            _coerce_concat_order(["A", "X"])

    def test_rejects_duplicates(self) -> None:
        """同一 letter の重複は ValueError (B 二重添付事故防止)。"""
        from wiseman_hub.config import _coerce_concat_order

        with pytest.raises(ValueError, match="duplicates"):
            _coerce_concat_order(["A", "B", "A"])


class TestPdfMergeConfigValidation:
    """PdfMergeConfig.concat_order の Literal + 検証。"""

    def test_default_concat_order_valid(self) -> None:
        cfg = PdfMergeConfig()
        assert cfg.concat_order == ("A", "B", "C")

    def test_concat_order_subset_valid(self) -> None:
        """部分集合（例: A,C のみ）も許容。"""
        cfg = PdfMergeConfig(concat_order=("A", "C"))
        assert cfg.concat_order == ("A", "C")

    def test_concat_order_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            PdfMergeConfig(concat_order=())

    @pytest.mark.parametrize(
        ("invalid_order", "reason"),
        [
            (("A", "B", "C", "D"), "D は source_d_filename 経由で末尾追加される別系統"),
            (("A", "X"), "未知の letter"),
            (("a", "b"), "大文字小文字違い（'a' != 'A'）"),
        ],
        ids=["d-rejected", "unknown-letter", "lowercase"],
    )
    def test_concat_order_unknown_value_raises(
        self, invalid_order: tuple[str, ...], reason: str
    ) -> None:
        # Literal 不一致は runtime ではブロックされないため cast でテスト
        with pytest.raises(ValueError, match="unknown source"):
            PdfMergeConfig(
                concat_order=cast("tuple[ConcatSourceLetter, ...]", invalid_order)
            )

    def test_concat_order_duplicate_raises(self) -> None:
        with pytest.raises(ValueError, match="duplicates"):
            PdfMergeConfig(concat_order=("A", "B", "A"))

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

    def test_post_init_rejects_list_input_with_type_error(self) -> None:
        """Issue #27 続編 E Phase 2: frozen=True 化で __post_init__ の自己代入
        ``self.concat_order = tuple(...)`` が不可になったため、list 直接渡しは
        TypeError で fail-fast する。

        list / tuple coerce は ``_coerce_concat_order()`` helper の責務に切り出され、
        呼出側 (load_config / settings.py / 直接構築テスト) が tuple を渡す前提に
        切り替わった。誤って list を直接渡したコードは silent fallback せず起動時に
        止まる契約を担保する。
        """
        # cast は意図的な型嘘（runtime 型ガードを検証する目的）
        with pytest.raises(TypeError, match="must be tuple"):
            PdfMergeConfig(
                concat_order=cast(
                    "tuple[ConcatSourceLetter, ...]", ["A", "B", "C"]
                )
            )

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

    def test_iadd_blocked_by_frozen_dataclass(self) -> None:
        """Issue #27 続編 E Phase 2: ``frozen=True`` 化により、Issue #151 で残って
        いた ``cfg.concat_order += (...,)`` 経路 (tuple は __iadd__ なしのため
        ``cfg.concat_order = cfg.concat_order + (...,)`` に fall back し、
        __post_init__ を経由せず値域検証 bypass) が **dataclass.FrozenInstanceError**
        で構造的に阻止される。defensive layer (``_validate_concat_order``) 頼みの
        運用安全性から、型レベル阻止に昇格した契約を担保する。
        """
        cfg = PdfMergeConfig()
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.concat_order += (cast(ConcatSourceLetter, "X"),)


class TestDataclassTypeGuards:
    """Issue #27 続編 A: 7 dataclass の ``__post_init__`` 型ガード水平展開。

    各 dataclass の代表的フィールドで bool/str/None/list/dict 型違反が
    ``TypeError`` で起動時拒否されることを検証。
    helper 単位の網羅テストは TestTypeGuardHelpers で別途実施。
    """

    # --- WisemanConfig --------------------------------------------------
    def test_wiseman_non_path_exe_path_raises(self) -> None:
        # Issue #27 続編 G §4: exe_path は Path 型、str は TypeError
        with pytest.raises(TypeError, match="WisemanConfig.exe_path must be Path"):
            from wiseman_hub.config import WisemanConfig
            WisemanConfig(exe_path=123)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="WisemanConfig.exe_path must be Path"):
            from wiseman_hub.config import WisemanConfig
            WisemanConfig(exe_path="C:/wiseman.exe")  # type: ignore[arg-type]

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
        """PII 防御: service_account_key_path の TypeError に値を含めない。

        Issue #27 続編 G §4: SA key path は Path 型、list は TypeError。
        """
        from wiseman_hub.config import GcpConfig
        sensitive_marker = "should_not_appear_in_message"
        with pytest.raises(TypeError) as exc_info:
            GcpConfig(service_account_key_path=[sensitive_marker])  # type: ignore[arg-type]
        assert sensitive_marker not in str(exc_info.value)
        assert "service_account_key_path must be Path" in str(exc_info.value)

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
        # Issue #27 続編 G §4: exe_path は Path 型
        assert isinstance(cfg.wiseman.exe_path, Path)
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
        # Issue #27 続編 G §4: exe_path は Path 型、未設定は Path("") (= Path("."))
        assert cfg.wiseman.exe_path == Path("")
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

    def test_reports_targets_element_index_non_zero_in_message(self, tmp_path: Path) -> None:
        """pr-test / silent-failure rating 7: ``enumerate`` 経路を index 1 で固定。

        旧 ``[reports].targets entries must be tables`` は位置情報がなく、
        複数 entry のうちどれが壊れているか分からなかった。新メッセージ
        ``[reports].targets[1] must be a table`` で index ≥ 1 にも index が
        正しく付くことを assert する。``enumerate`` を将来うっかり ``range`` に
        差し替えた等のリグレッションを検知する。
        """
        # inline syntax: [{valid dict}, "bad"] で index 1 を非 dict にする
        toml_content = """\
[reports]
targets = [{name = "ok"}, "bad-entry-at-index-1"]
"""
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content, encoding="utf-8")

        with pytest.raises(
            TypeError, match=r"\[reports\]\.targets\[1\] must be a table"
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
        # Issue #27 続編 G §4: service_account_key_path は Path 型
        assert config.gcp.service_account_key_path == (cfg_dir / "sa-key.json").resolve()

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
        # Issue #27 続編 G §4: service_account_key_path は Path 型
        expected = (dist_root / "config" / "sa-key.json").resolve()
        assert config.gcp.service_account_key_path == expected

    def test_keeps_absolute_path_unchanged(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "default.toml"
        abs_key = tmp_path / "external" / "sa-key.json"
        cfg_path.write_text(
            f'[gcp]\nservice_account_key_path = "{abs_key.as_posix()}"\n',
            encoding="utf-8",
        )
        config = load_config(cfg_path)
        # Issue #27 続編 G §4: service_account_key_path は Path 型 (絶対 path をそのまま保持)
        assert config.gcp.service_account_key_path == abs_key

    def test_empty_value_remains_empty(self, tmp_path: Path) -> None:
        """GCP 機能未使用環境では未設定 Path (Path("") = Path(".")) のまま (既存運用維持)。

        Issue #27 続編 G §4: 空文字列 → Path("") に正規化。is_sa_key_configured で
        consumer 側が未設定判定する規約。
        """
        cfg_path = tmp_path / "default.toml"
        cfg_path.write_text(
            '[gcp]\nservice_account_key_path = ""\n', encoding="utf-8"
        )
        config = load_config(cfg_path)
        assert config.gcp.service_account_key_path == Path("")
        assert config.gcp.is_sa_key_configured is False


class TestIssue27PathMigration:
    """Issue #27 続編 G Phase 1: str → Path 型移行の検証。

    対象: WisemanConfig.exe_path / GcpConfig.service_account_key_path /
    AppConfig.log_dir の 3 field。is_configured 系プロパティ・coerce_path /
    _check_path helper・load / save の str ⇄ Path 境界変換を網羅。
    """

    # --- is_path_configured (module-level helper) ---

    def test_is_path_configured_empty_path_is_false(self) -> None:
        """Path("") は未設定 sentinel (Path(".") と等価) で is_path_configured=False。"""
        from wiseman_hub.config import is_path_configured
        assert is_path_configured(Path("")) is False

    def test_is_path_configured_dot_path_is_false(self) -> None:
        """Path(".") (current dir 明示) も sentinel と区別不能で False。

        Phase 2 で Optional[Path] 移行を検討する根拠となる既知挙動の固定。
        """
        from wiseman_hub.config import is_path_configured
        assert is_path_configured(Path(".")) is False

    def test_is_path_configured_no_arg_path_is_false(self) -> None:
        """Path() (no-arg) も Path("") と等価で False。"""
        from wiseman_hub.config import is_path_configured
        assert is_path_configured(Path()) is False

    def test_is_path_configured_absolute_path_is_true(self) -> None:
        from wiseman_hub.config import is_path_configured
        assert is_path_configured(Path("/tmp/foo")) is True

    def test_is_path_configured_relative_path_is_true(self) -> None:
        from wiseman_hub.config import is_path_configured
        assert is_path_configured(Path("relative/path")) is True

    # --- is_exe_configured (WisemanConfig) ---

    def test_is_exe_configured_false_for_default(self) -> None:
        """default WisemanConfig() は is_exe_configured=False (空 Path sentinel)。"""
        cfg = WisemanConfig()
        assert cfg.is_exe_configured is False
        assert str(cfg.exe_path) == "."

    def test_is_exe_configured_true_for_set_path(self) -> None:
        """非空 Path は is_exe_configured=True。"""
        cfg = WisemanConfig(exe_path=Path("C:/wiseman.exe"))
        assert cfg.is_exe_configured is True

    def test_is_exe_configured_false_for_empty_path(self) -> None:
        """Path("") は Path(".") と等価で is_exe_configured=False (未設定 sentinel)。"""
        cfg = WisemanConfig(exe_path=Path(""))
        assert cfg.is_exe_configured is False

    # --- is_sa_key_configured (GcpConfig) ---

    def test_is_sa_key_configured_false_for_default(self) -> None:
        cfg = GcpConfig()
        assert cfg.is_sa_key_configured is False

    def test_is_sa_key_configured_true_for_set_path(self, tmp_path: Path) -> None:
        cfg = GcpConfig(service_account_key_path=tmp_path / "sa.json")
        assert cfg.is_sa_key_configured is True

    # --- is_log_dir_configured (AppConfig) ---

    def test_is_log_dir_configured_false_for_default(self) -> None:
        cfg = AppConfig()
        assert cfg.is_log_dir_configured is False

    def test_is_log_dir_configured_true_for_set_path(self, tmp_path: Path) -> None:
        cfg = AppConfig(log_dir=tmp_path)
        assert cfg.is_log_dir_configured is True

    # --- coerce_path helper (load_config 内部、TOML str → Path) ---

    def testcoerce_path_none_returns_empty(self) -> None:
        """None 入力は Path("") (未設定 sentinel)。"""
        from wiseman_hub.config import coerce_path
        result = coerce_path("test.field", None)
        assert result == Path("")
        assert str(result) == "."

    def testcoerce_path_empty_string_returns_empty(self) -> None:
        from wiseman_hub.config import coerce_path
        result = coerce_path("test.field", "")
        assert result == Path("")

    def testcoerce_path_whitespace_only_returns_empty(self) -> None:
        """空白だけの文字列は Path("") (未設定扱い、TOML 手書き編集対策)。"""
        from wiseman_hub.config import coerce_path
        result = coerce_path("test.field", "   \t  ")
        assert result == Path("")

    def testcoerce_path_strips_whitespace(self) -> None:
        """前後空白は strip してから Path 化 (TOML 手書き編集の typo 救済)。"""
        from wiseman_hub.config import coerce_path
        result = coerce_path("test.field", "  /tmp/foo  ")
        assert result == Path("/tmp/foo")

    def testcoerce_path_passthrough_path_input(self) -> None:
        """既に Path インスタンスならそのまま返す (idempotent)。"""
        from wiseman_hub.config import coerce_path
        original = Path("/tmp/foo")
        result = coerce_path("test.field", original)
        assert result is original

    def testcoerce_path_rejects_int(self) -> None:
        """型違反 (int) は TypeError で起動時 fail-close。"""
        from wiseman_hub.config import coerce_path
        with pytest.raises(TypeError, match="must be str.*Path"):
            coerce_path("test.field", 123)

    def testcoerce_path_rejects_bool(self) -> None:
        """bool (int サブクラス) は明示除外 (silent: True == 1 で str 経路すり抜け防止)。"""
        from wiseman_hub.config import coerce_path
        with pytest.raises(TypeError, match="must be str.*Path"):
            coerce_path("test.field", True)

    def testcoerce_path_rejects_list(self) -> None:
        from wiseman_hub.config import coerce_path
        with pytest.raises(TypeError, match="must be str.*Path"):
            coerce_path("test.field", ["a", "b"])

    def testcoerce_path_pii_echo_value_false(self) -> None:
        """echo_value=False で TypeError メッセージに値を出さない (PII 防御)。"""
        from wiseman_hub.config import coerce_path
        sensitive = "should_not_appear_in_message"
        with pytest.raises(TypeError) as exc_info:
            coerce_path("test.field", [sensitive], echo_value=False)
        assert sensitive not in str(exc_info.value)

    # --- load_config の str → Path 変換 (e2e) ---

    def test_load_config_coerces_exe_path_to_path(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "cfg.toml"
        cfg_path.write_text(
            '[wiseman]\nexe_path = "C:/wiseman.exe"\n', encoding="utf-8"
        )
        cfg = load_config(cfg_path)
        assert isinstance(cfg.wiseman.exe_path, Path)
        assert cfg.wiseman.exe_path == Path("C:/wiseman.exe")
        assert cfg.wiseman.is_exe_configured is True

    def test_load_config_coerces_log_dir_to_path(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "cfg.toml"
        cfg_path.write_text(
            '[app]\nlog_dir = "/var/log/wiseman"\n', encoding="utf-8"
        )
        cfg = load_config(cfg_path)
        assert isinstance(cfg.log_dir, Path)
        assert cfg.log_dir == Path("/var/log/wiseman")
        assert cfg.is_log_dir_configured is True

    def test_load_config_empty_exe_path_is_unset(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "cfg.toml"
        cfg_path.write_text(
            '[wiseman]\nexe_path = ""\n', encoding="utf-8"
        )
        cfg = load_config(cfg_path)
        assert cfg.wiseman.exe_path == Path("")
        assert cfg.wiseman.is_exe_configured is False

    def test_load_config_whitespace_exe_path_is_unset(self, tmp_path: Path) -> None:
        """TOML 手書き編集で空白のみが入っても未設定扱い (起動時正規化)。"""
        cfg_path = tmp_path / "cfg.toml"
        cfg_path.write_text(
            '[wiseman]\nexe_path = "   "\n', encoding="utf-8"
        )
        cfg = load_config(cfg_path)
        assert cfg.wiseman.exe_path == Path("")
        assert cfg.wiseman.is_exe_configured is False

    def test_load_config_rejects_non_string_exe_path(self, tmp_path: Path) -> None:
        """TOML で int を渡すと coerce_path 経由で TypeError (silent fail 防止)。"""
        cfg_path = tmp_path / "cfg.toml"
        cfg_path.write_text(
            '[wiseman]\nexe_path = 123\n', encoding="utf-8"
        )
        with pytest.raises(TypeError, match="exe_path must be str.*Path"):
            load_config(cfg_path)

    # --- save_config の Path → str ラウンドトリップ ---

    def test_save_config_round_trip_preserves_paths(self, tmp_path: Path) -> None:
        """Path 型 field を save → load しても Path 値が保たれる (ラウンドトリップ整合)。"""
        cfg_path = tmp_path / "cfg.toml"
        cfg_path.write_text(
            '[wiseman]\nexe_path = ""\n[app]\nlog_dir = ""\n',
            encoding="utf-8",
        )
        cfg = load_config(cfg_path)
        # Path 値を更新
        new_cfg = replace(
            cfg,
            log_dir=Path("/var/log/test"),
            wiseman=replace(cfg.wiseman, exe_path=Path("C:/Wiseman/app.exe")),
        )
        save_config(new_cfg, cfg_path)

        reloaded = load_config(cfg_path)
        assert reloaded.wiseman.exe_path == Path("C:/Wiseman/app.exe")
        assert reloaded.log_dir == Path("/var/log/test")
        assert isinstance(reloaded.wiseman.exe_path, Path)
        assert isinstance(reloaded.log_dir, Path)

    def test_save_config_writes_path_as_string(self, tmp_path: Path) -> None:
        """TOML 出力は str 表現 (tomlkit は Path オブジェクトを直接受け取れないため境界変換が必須)。"""
        cfg_path = tmp_path / "cfg.toml"
        cfg_path.write_text(
            '[app]\nlog_dir = ""\n', encoding="utf-8"
        )
        cfg = load_config(cfg_path)
        new_cfg = replace(cfg, log_dir=Path("/var/log/test"))
        save_config(new_cfg, cfg_path)

        # 文字列として TOML に書かれていることを直接確認 (Path repr ではない)
        content = cfg_path.read_text(encoding="utf-8")
        assert 'log_dir = "/var/log/test"' in content
        # Path 型の repr (e.g. "PosixPath('/var/log/test')") が混入していないこと
        assert "PosixPath" not in content
        assert "WindowsPath" not in content

    # --- Codex review High 対応: 未設定 Path の TOML 書出は "" を保つ ---

    def test_save_config_unset_path_written_as_empty_string(
        self, tmp_path: Path
    ) -> None:
        """未設定 Path (Path("") = Path(".")) は TOML に '""' で書かれる (旧 str 互換)。

        Codex review High: ``str(Path(""))`` は ``"."`` だが、TOML に
        ``log_dir = "."`` で保存されると旧版ダウングレード / 手動編集で
        「カレントディレクトリ指定」と誤解される silent 互換性劣化を防ぐ。
        """
        cfg_path = tmp_path / "cfg.toml"
        cfg_path.write_text(
            '[app]\nlog_dir = "/initial/path"\n[wiseman]\nexe_path = "C:/Wiseman.exe"\n',
            encoding="utf-8",
        )
        cfg = load_config(cfg_path)
        # path を全て未設定状態に戻す
        cleared_cfg = replace(
            cfg,
            log_dir=Path(""),
            wiseman=replace(cfg.wiseman, exe_path=Path("")),
        )
        save_config(cleared_cfg, cfg_path)

        content = cfg_path.read_text(encoding="utf-8")
        assert 'log_dir = ""' in content
        assert 'exe_path = ""' in content
        # 旧 silent 劣化バグ: '"."' が書かれていないこと
        assert 'log_dir = "."' not in content
        assert 'exe_path = "."' not in content

        # ラウンドトリップで未設定状態が保たれること
        reloaded = load_config(cfg_path)
        assert reloaded.is_log_dir_configured is False
        assert reloaded.wiseman.is_exe_configured is False

    # --- Codex review Medium 対応: is_path_configured の非 Path defensive ---

    def test_is_path_configured_none_is_false(self) -> None:
        """None 入力は False (legacy caller の defensive guard)。

        Codex review Medium: 旧 caller が None / "" を直接渡しても、
        後段 TypeError ではなく no-op (False) で安全側に倒す。
        """
        from wiseman_hub.config import is_path_configured
        assert is_path_configured(None) is False

    def test_is_path_configured_empty_string_is_false(self) -> None:
        from wiseman_hub.config import is_path_configured
        assert is_path_configured("") is False

    def test_is_path_configured_non_path_string_is_false(self) -> None:
        """非 Path str 入力は False (型ヒント違反時 defensive)。"""
        from wiseman_hub.config import is_path_configured
        assert is_path_configured("/tmp/foo") is False

    # --- Codex review Medium 対応: coerce_path で空白 Path も正規化 ---

    def test_coerce_path_whitespace_only_path_normalized(self) -> None:
        """Path(" ") 等の空白だけの Path は未設定 sentinel に正規化。

        Codex review Medium: TOML 経路では str strip で空白除去されるが、
        直接構築経路 (Path(" ") を渡す) でも sentinel 規約を一致させる。
        """
        from wiseman_hub.config import coerce_path
        result = coerce_path("test.field", Path(" "))
        assert result == Path("")
        from wiseman_hub.config import is_path_configured
        assert is_path_configured(result) is False

    def test_coerce_path_passthrough_non_empty_path(self) -> None:
        """非空 Path は idempotent (passthrough)。"""
        from wiseman_hub.config import coerce_path
        original = Path("/tmp/foo")
        result = coerce_path("test.field", original)
        assert result is original


class TestIssue27PathMigrationPhase2a:
    """Issue #27 続編 G Phase 2a: PdfMergeConfig.input_dir / output_dir / ex_source_dir 移行。"""

    def test_pdf_merge_config_default_paths_are_unset(self) -> None:
        """default PdfMergeConfig は 3 path field すべて未設定 sentinel。"""
        from wiseman_hub.config import PdfMergeConfig, is_path_configured

        cfg = PdfMergeConfig()
        assert isinstance(cfg.input_dir, Path)
        assert isinstance(cfg.output_dir, Path)
        assert isinstance(cfg.ex_source_dir, Path)
        assert is_path_configured(cfg.input_dir) is False
        assert is_path_configured(cfg.output_dir) is False
        assert is_path_configured(cfg.ex_source_dir) is False

    def test_pdf_merge_config_rejects_str_input_dir(self) -> None:
        """str を直接渡すと TypeError (Path 専用化)。"""
        from wiseman_hub.config import PdfMergeConfig

        with pytest.raises(TypeError, match="input_dir must be Path"):
            PdfMergeConfig(input_dir="/tmp/foo")  # type: ignore[arg-type]

    def test_pdf_merge_config_rejects_str_output_dir(self) -> None:
        from wiseman_hub.config import PdfMergeConfig

        with pytest.raises(TypeError, match="output_dir must be Path"):
            PdfMergeConfig(output_dir="/tmp/out")  # type: ignore[arg-type]

    def test_pdf_merge_config_rejects_str_ex_source_dir(self) -> None:
        from wiseman_hub.config import PdfMergeConfig

        with pytest.raises(TypeError, match="ex_source_dir must be Path"):
            PdfMergeConfig(ex_source_dir="/tmp/ex")  # type: ignore[arg-type]

    def test_load_config_coerces_pdf_merge_paths(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "cfg.toml"
        cfg_path.write_text(
            '[pdf_merge]\n'
            'input_dir = "/tmp/in"\n'
            'output_dir = "/tmp/out"\n'
            'ex_source_dir = "/srv/ex"\n',
            encoding="utf-8",
        )
        cfg = load_config(cfg_path)
        assert cfg.pdf_merge.input_dir == Path("/tmp/in")
        assert cfg.pdf_merge.output_dir == Path("/tmp/out")
        assert cfg.pdf_merge.ex_source_dir == Path("/srv/ex")

    def test_load_config_whitespace_pdf_merge_paths_are_unset(
        self, tmp_path: Path
    ) -> None:
        """TOML 手書き編集での空白だけの値は未設定扱い (coerce_path 経由)。"""
        cfg_path = tmp_path / "cfg.toml"
        cfg_path.write_text(
            '[pdf_merge]\n'
            'input_dir = "   "\n'
            'output_dir = "\\t"\n'
            'ex_source_dir = ""\n',
            encoding="utf-8",
        )
        cfg = load_config(cfg_path)
        from wiseman_hub.config import is_path_configured
        assert is_path_configured(cfg.pdf_merge.input_dir) is False
        assert is_path_configured(cfg.pdf_merge.output_dir) is False
        assert is_path_configured(cfg.pdf_merge.ex_source_dir) is False

    def test_save_config_pdf_merge_paths_round_trip(self, tmp_path: Path) -> None:
        """PdfMergeConfig path 3 件の save → load ラウンドトリップ。"""
        cfg_path = tmp_path / "cfg.toml"
        cfg_path.write_text(
            '[pdf_merge]\ninput_dir = ""\noutput_dir = ""\nex_source_dir = ""\n',
            encoding="utf-8",
        )
        cfg = load_config(cfg_path)
        new_cfg = replace(
            cfg,
            pdf_merge=replace(
                cfg.pdf_merge,
                input_dir=Path("/var/in"),
                output_dir=Path("/var/out"),
                ex_source_dir=Path("/srv/ex"),
            ),
        )
        save_config(new_cfg, cfg_path)

        reloaded = load_config(cfg_path)
        assert reloaded.pdf_merge.input_dir == Path("/var/in")
        assert reloaded.pdf_merge.output_dir == Path("/var/out")
        assert reloaded.pdf_merge.ex_source_dir == Path("/srv/ex")

    # --- stringify_paths_recursive (Phase 2a evaluator MEDIUM 対応) ---

    def test_stringify_paths_recursive_unset_path_becomes_empty_string(self) -> None:
        """未設定 Path は "" に変換 (TOML save_config と同じ規約)。"""
        from wiseman_hub.config import stringify_paths_recursive
        assert stringify_paths_recursive(Path("")) == ""
        assert stringify_paths_recursive(Path(".")) == ""

    def test_stringify_paths_recursive_configured_path_becomes_str(self) -> None:
        from wiseman_hub.config import stringify_paths_recursive
        assert stringify_paths_recursive(Path("/tmp/foo")) == str(Path("/tmp/foo"))

    def test_stringify_paths_recursive_nested_dict(self) -> None:
        """ネスト dict 内の Path も再帰的に変換 (session.config_snapshot 経路)。"""
        from wiseman_hub.config import stringify_paths_recursive
        nested = {
            "pdf_merge": {
                "input_dir": Path(""),
                "output_dir": Path("/var/out"),
                "non_path": "literal",
                "concat_order": ("A", "B"),
            },
            "version": "1.0",
        }
        result = stringify_paths_recursive(nested)
        assert result["pdf_merge"]["input_dir"] == ""
        assert result["pdf_merge"]["output_dir"] == str(Path("/var/out"))
        assert result["pdf_merge"]["non_path"] == "literal"
        # tuple は JSON 互換のため list に変換
        assert result["pdf_merge"]["concat_order"] == ["A", "B"]
        assert result["version"] == "1.0"

    def test_stringify_paths_recursive_list_of_dicts(self) -> None:
        from wiseman_hub.config import stringify_paths_recursive
        data = [{"path": Path("/a")}, {"path": Path("")}]
        result = stringify_paths_recursive(data)
        assert result == [{"path": str(Path("/a"))}, {"path": ""}]

    def test_stringify_paths_recursive_passthrough_primitive(self) -> None:
        from wiseman_hub.config import stringify_paths_recursive
        assert stringify_paths_recursive(42) == 42
        assert stringify_paths_recursive("string") == "string"
        assert stringify_paths_recursive(True) is True
        assert stringify_paths_recursive(None) is None

    def test_load_config_rejects_non_string_pdf_merge_path(
        self, tmp_path: Path
    ) -> None:
        """TOML で int / bool 等を渡すと coerce_path 経由で TypeError (silent fail 防止)。"""
        cfg_path = tmp_path / "cfg.toml"
        cfg_path.write_text(
            '[pdf_merge]\ninput_dir = 123\n', encoding="utf-8"
        )
        with pytest.raises(TypeError, match="input_dir must be str.*Path"):
            load_config(cfg_path)

    def test_save_config_unset_pdf_merge_paths_written_as_empty(
        self, tmp_path: Path
    ) -> None:
        """未設定 Path は TOML に "" で書き戻し (Phase 1 と同じ silent 互換性劣化防御)。"""
        cfg_path = tmp_path / "cfg.toml"
        cfg_path.write_text(
            '[pdf_merge]\ninput_dir = "/initial"\noutput_dir = "/initial"\n'
            'ex_source_dir = "/initial"\n',
            encoding="utf-8",
        )
        cfg = load_config(cfg_path)
        cleared = replace(
            cfg,
            pdf_merge=replace(
                cfg.pdf_merge,
                input_dir=Path(""),
                output_dir=Path(""),
                ex_source_dir=Path(""),
            ),
        )
        save_config(cleared, cfg_path)

        content = cfg_path.read_text(encoding="utf-8")
        assert 'input_dir = ""' in content
        assert 'output_dir = ""' in content
        assert 'ex_source_dir = ""' in content
        # 旧 silent 劣化バグ: '"."' が書かれていないこと
        assert 'input_dir = "."' not in content
        assert 'output_dir = "."' not in content
        assert 'ex_source_dir = "."' not in content


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
        # Issue #27 続編 E Phase 3b: AppConfig + ChecklistConfig 共に frozen=True、
        # コンストラクタ経由で構築する。
        cfg = AppConfig(
            checklist=ChecklistConfig(
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
            ),
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
        # Issue #27 続編 E Phase 3b: AppConfig + ChecklistConfig は frozen=True。
        cfg = AppConfig(
            checklist=ChecklistConfig(
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
            ),
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
        # Issue #27 続編 E Phase 3b: AppConfig + ChecklistConfig は frozen=True。
        cfg = AppConfig(
            checklist=ChecklistConfig(
                report_staff={
                    "宮下": ReportStaffEntry(
                        base_dir="\\\\Tera-station\\share\\PT 宮下",
                        year_subfolder_template="リハ経過報告書\\令和{era}年",
                        file_template="リハ経過報告書 (宮下) {month}月 .xlsx",
                    ),
                },
            ),
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
