"""TOML設定ファイルのローダー"""

from __future__ import annotations

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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
