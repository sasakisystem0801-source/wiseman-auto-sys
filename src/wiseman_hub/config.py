"""TOML設定ファイルのローダー / セーバー"""

from __future__ import annotations

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]
import contextlib
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import tomlkit
from tomlkit import TOMLDocument
from tomlkit.items import Table


@dataclass
class WisemanConfig:
    exe_path: str = ""  # ワイズマンSPの実行ファイルパス
    startup_wait_sec: int = 15  # 起動・ドングル認証待機秒数
    window_title_pattern: str = ".*管理システム SP.*"  # メインウィンドウのタイトルパターン


@dataclass
class ScheduleConfig:
    enabled: bool = False
    cron: str = "0 8 * * *"


@dataclass
class ReportTarget:
    name: str = ""
    menu_path: list[str] = field(default_factory=list)
    output_format: str = "csv"


@dataclass
class GcpConfig:
    project_id: str = ""
    bucket_name: str = ""
    service_account_key_path: str = ""
    region: str = "asia-northeast1"


@dataclass
class UpdaterConfig:
    enabled: bool = False
    check_interval_hours: int = 1
    release_bucket: str = ""


@dataclass
class OcrBackendConfig:
    """OCRバックエンド（Cloud Runプロキシ）設定。詳細はADR-008参照。"""

    endpoint_url: str = ""
    api_key: str = ""
    timeout_sec: int = 30
    max_retries: int = 3


@dataclass
class UserNameBBox:
    """利用者名が印字される固定矩形（PDFページ座標、ポイント単位）。"""

    x0: float = 0.0
    y0: float = 0.0
    x1: float = 0.0
    y1: float = 0.0
    dpi: int = 200


@dataclass
class PdfMergeConfig:
    """PDF分割・条件付き再結合機能の設定。"""

    input_dir: str = ""
    output_dir: str = ""
    source_a_filename: str = ""
    source_d_filename: str = ""
    source_b_pattern: str = "B_{name}.pdf"
    source_c_pattern: str = "C_{name}.pdf"
    concat_order: list[str] = field(default_factory=lambda: ["A", "B", "C"])
    user_name_bbox: UserNameBBox = field(default_factory=UserNameBBox)


@dataclass
class AppConfig:
    version: str = "0.1.0"
    log_level: str = "INFO"
    log_dir: str = ""
    wiseman: WisemanConfig = field(default_factory=WisemanConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    reports: list[ReportTarget] = field(default_factory=list)
    gcp: GcpConfig = field(default_factory=GcpConfig)
    updater: UpdaterConfig = field(default_factory=UpdaterConfig)
    ocr_backend: OcrBackendConfig = field(default_factory=OcrBackendConfig)
    pdf_merge: PdfMergeConfig = field(default_factory=PdfMergeConfig)


def load_config(path: Path | None = None) -> AppConfig:
    """TOML設定ファイルを読み込んでAppConfigを返す。"""
    if path is None:
        path = Path("config/default.toml")

    if not path.exists():
        return AppConfig()

    with open(path, "rb") as f:
        data: dict[str, Any] = tomllib.load(f)

    app_data = data.get("app", {})
    wiseman_data = data.get("wiseman", {})
    schedule_data = data.get("schedule", {})
    gcp_data = data.get("gcp", {})
    updater_data = data.get("updater", {})
    ocr_backend_data = data.get("ocr_backend", {})
    pdf_merge_data = dict(data.get("pdf_merge", {}))

    reports: list[ReportTarget] = []
    for target in data.get("reports", {}).get("targets", []):
        reports.append(ReportTarget(**target))

    bbox_data = pdf_merge_data.pop("user_name_bbox", {})
    pdf_merge = PdfMergeConfig(**pdf_merge_data, user_name_bbox=UserNameBBox(**bbox_data))

    return AppConfig(
        version=app_data.get("version", "0.1.0"),
        log_level=app_data.get("log_level", "INFO"),
        log_dir=app_data.get("log_dir", ""),
        wiseman=WisemanConfig(**wiseman_data),
        schedule=ScheduleConfig(**schedule_data),
        reports=reports,
        gcp=GcpConfig(**gcp_data),
        updater=UpdaterConfig(**updater_data),
        ocr_backend=OcrBackendConfig(**ocr_backend_data),
        pdf_merge=pdf_merge,
    )


_SCALAR_SECTIONS: tuple[str, ...] = ("wiseman", "schedule", "gcp", "updater", "ocr_backend")


def _update_table_from_dataclass(doc: TOMLDocument, section: str, data: dict[str, Any]) -> None:
    """既存テーブルを in-place 更新（コメント維持）、存在しなければ新規追加。"""
    if section in doc:
        table = doc[section]
        assert isinstance(table, Table)
        for key, value in data.items():
            table[key] = value
    else:
        doc[section] = data


def _update_pdf_merge(doc: TOMLDocument, pdf_merge: PdfMergeConfig) -> None:
    """[pdf_merge] とネスト [pdf_merge.user_name_bbox] を書き戻す。"""
    bbox = asdict(pdf_merge.user_name_bbox)
    pdf_merge_dict = asdict(pdf_merge)
    pdf_merge_dict.pop("user_name_bbox", None)

    if "pdf_merge" in doc:
        table = doc["pdf_merge"]
        assert isinstance(table, Table)
        for key, value in pdf_merge_dict.items():
            table[key] = value
        if "user_name_bbox" in table:
            bbox_table = table["user_name_bbox"]
            assert isinstance(bbox_table, Table)
            for key, value in bbox.items():
                bbox_table[key] = value
        else:
            table["user_name_bbox"] = bbox
    else:
        new_table = tomlkit.table()
        for key, value in pdf_merge_dict.items():
            new_table[key] = value
        new_table["user_name_bbox"] = bbox
        doc["pdf_merge"] = new_table


def _update_reports(doc: TOMLDocument, reports: list[ReportTarget]) -> None:
    """[[reports.targets]] 配列を書き戻す。"""
    targets_data = [asdict(t) for t in reports]
    if "reports" in doc:
        reports_table = doc["reports"]
        assert isinstance(reports_table, Table)
        reports_table["targets"] = targets_data
    else:
        reports_table = tomlkit.table()
        aot = tomlkit.aot()
        for t in targets_data:
            tbl = tomlkit.table()
            for key, value in t.items():
                tbl[key] = value
            aot.append(tbl)
        reports_table["targets"] = aot
        doc["reports"] = reports_table


def save_config(cfg: AppConfig, path: Path) -> None:
    """AppConfig を TOML に書き戻す。

    既存ファイルがあれば tomlkit でパースして値だけ更新し、コメント・空行を維持する。
    存在しない場合は新規 TOMLDocument を生成。書き込みは tempfile + os.replace で atomic。
    親ディレクトリが存在しない場合は自動作成する。
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with path.open("r", encoding="utf-8") as f:
            doc = tomlkit.parse(f.read())
    except FileNotFoundError:
        doc = tomlkit.document()

    app_data = {"version": cfg.version, "log_level": cfg.log_level, "log_dir": cfg.log_dir}
    _update_table_from_dataclass(doc, "app", app_data)

    for section in _SCALAR_SECTIONS:
        _update_table_from_dataclass(doc, section, asdict(getattr(cfg, section)))

    _update_pdf_merge(doc, cfg.pdf_merge)
    _update_reports(doc, cfg.reports)

    fd, tmp_path = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(tomlkit.dumps(doc))
        os.replace(tmp_path, path)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_path)
        raise
