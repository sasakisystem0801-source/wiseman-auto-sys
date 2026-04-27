"""TOML設定ファイルのローダー / セーバー"""

from __future__ import annotations

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]
import logging
import os
from dataclasses import asdict, dataclass, field
from glob import glob
from pathlib import Path
from typing import Any

import tomlkit
from tomlkit import TOMLDocument
from tomlkit.items import InlineTable, Table

from wiseman_hub.utils.atomic_io import write_bytes_atomically

logger = logging.getLogger(__name__)

TableLike = Table | InlineTable
_TABLE_LIKE_TYPES: tuple[type, ...] = (Table, InlineTable)


def _require_table(container: Any, key: str) -> TableLike:
    """container[key] が table (Block or Inline) であることを保証して返す。

    TOML スキーマ違反（例: section が整数や文字列）を TypeError で明示する。
    """
    item = container[key]
    if not isinstance(item, _TABLE_LIKE_TYPES):
        raise TypeError(f"TOML key '{key}' is not a table (got {type(item).__name__})")
    assert isinstance(item, (Table, InlineTable))
    return item


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
    """PDF分割・条件付き再結合機能の設定。

    facility_root_dir: 事業所ルートフォルダ（複数事業所を一括処理する起点）。
        配下に `{事業所名}/{運動機能向上計画書,経過報告書}/` 構造を持つ親ディレクトリ。
        新ダイアログ FacilityRootManagerDialog（W4）で永続化する。
        既存の input_dir / output_dir 等とは独立（旧 Phase A/B フローは無関係）。
    ex_source_dir: .ex_ ファイル（WinSFX32 LZH 自己解凍EXE）の取込元フォルダ。
        ex_extractor 機能（PR1-5）で `.ex_ → PDF 抽出 → facility_root_dir 配下事業所
        フォルダへ振り分け` の起点として使う。facility_root_dir と同レベルの永続設定で、
        ダイアログ初回起動時にユーザーが選択 → 次回以降は保存値を表示。
    facility_aliases: facility_resolver で使う事業所名の別名辞書（PR2 で追加）。
        正式フォルダ名（key）に対する別名・略称・旧名称（value 配列）を保持し、
        ファイル名と事業所フォルダの照合で最優先一致として参照される。誤配布防止のため
        部分一致系より明示 alias 一致を優先する設計（ADR-014 参照予定）。
        例: {"本田デイケア": ["本田DC", "本田デイ"]}
    """

    input_dir: str = ""
    output_dir: str = ""
    source_a_filename: str = ""
    source_d_filename: str = ""
    source_b_pattern: str = "B_{name}.pdf"
    source_c_pattern: str = "C_{name}.pdf"
    concat_order: list[str] = field(default_factory=lambda: ["A", "B", "C"])
    user_name_bbox: UserNameBBox = field(default_factory=UserNameBBox)
    facility_root_dir: str = ""
    ex_source_dir: str = ""
    facility_aliases: dict[str, list[str]] = field(default_factory=dict)


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
    aliases_data = pdf_merge_data.pop("facility_aliases", {})
    # TOML の dict[str, list[str]] を素直な Python dict に正規化（tomllib は通常 dict 化済）
    facility_aliases: dict[str, list[str]] = {
        str(k): list(v) for k, v in dict(aliases_data).items()
    }
    pdf_merge = PdfMergeConfig(
        **pdf_merge_data,
        user_name_bbox=UserNameBBox(**bbox_data),
        facility_aliases=facility_aliases,
    )

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


# AppConfig に新フィールド追加時は対応する tuple に追記すること（save_config のラウンドトリップ対象）
_APP_FIELDS: tuple[str, ...] = ("version", "log_level", "log_dir")
_SCALAR_SECTIONS: tuple[str, ...] = ("wiseman", "schedule", "gcp", "updater", "ocr_backend")


def _update_table_from_dataclass(doc: TOMLDocument, section: str, data: dict[str, Any]) -> None:
    """既存テーブルを in-place 更新（コメント維持）、存在しなければ新規追加。

    標準ブロック記法 `[section]` およびインラインテーブル `section = {...}` の両方に対応。
    """
    if section in doc:
        table = _require_table(doc, section)
        for key, value in data.items():
            table[key] = value
    else:
        doc[section] = data


def _update_pdf_merge(doc: TOMLDocument, pdf_merge: PdfMergeConfig) -> None:
    """[pdf_merge] とネスト [pdf_merge.user_name_bbox] / [pdf_merge.facility_aliases] を書き戻す。

    ネスト table を持つ field（user_name_bbox, facility_aliases）は親 table のスカラ
    フィールド更新とは独立に書き出す。スカラフィールドの更新でネスト table を上書き
    しないよう、ネスト系は ``pdf_merge_dict`` から事前に pop する。

    facility_aliases は dict[str, list[str]] の動的キーを持つため、tomlkit.table() を
    新規作成して全 key を入れ直す（既存 alias を完全置換）。空辞書の場合は alias table
    自体を削除し、TOML から `[pdf_merge.facility_aliases]` セクションが消えるようにする。
    """
    bbox = asdict(pdf_merge.user_name_bbox)
    aliases = pdf_merge.facility_aliases
    pdf_merge_dict = asdict(pdf_merge)
    pdf_merge_dict.pop("user_name_bbox", None)
    pdf_merge_dict.pop("facility_aliases", None)

    if "pdf_merge" in doc:
        table = _require_table(doc, "pdf_merge")
        for key, value in pdf_merge_dict.items():
            table[key] = value
        if "user_name_bbox" in table:
            bbox_table = _require_table(table, "user_name_bbox")
            for key, value in bbox.items():
                bbox_table[key] = value
        else:
            table["user_name_bbox"] = bbox
        _set_facility_aliases(table, aliases)
    else:
        new_table = tomlkit.table()
        for key, value in pdf_merge_dict.items():
            new_table[key] = value
        new_table["user_name_bbox"] = bbox
        _set_facility_aliases(new_table, aliases)
        doc["pdf_merge"] = new_table


def _set_facility_aliases(
    pdf_merge_table: TableLike, aliases: dict[str, list[str]]
) -> None:
    """[pdf_merge.facility_aliases] を完全置換する（既存 alias は全削除）。

    空辞書の場合はセクション自体を TOML から削除し、未設定状態と同じ TOML 表現にする。
    """
    if "facility_aliases" in pdf_merge_table:
        del pdf_merge_table["facility_aliases"]
    if not aliases:
        return
    aliases_table = tomlkit.table()
    for facility_name, alias_list in aliases.items():
        aliases_table[facility_name] = list(alias_list)
    pdf_merge_table["facility_aliases"] = aliases_table


def _update_reports(doc: TOMLDocument, reports: list[ReportTarget]) -> None:
    """[[reports.targets]] 配列を書き戻す。

    既存の targets 配列はインラインコメントごと置換される（要素間の書式保持は未対応）。
    """
    targets_data = [asdict(t) for t in reports]
    if "reports" in doc:
        reports_table = _require_table(doc, "reports")
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


def _sweep_stale_tmp(path: Path) -> None:
    """同じ path 用に過去のクラッシュで残った tmp ファイルを削除する。

    API key やパスを含むため、平文 tmp 残置を防ぐ。unlink に失敗したファイルは
    warning も出さない（ログに tmp パスが乗るのを避けるため、件数のみ記録）。
    """
    pattern = str(path.parent / f"{path.name}.*.tmp")
    stale = glob(pattern)
    failed = 0
    for p in stale:
        try:
            os.unlink(p)
        except OSError:
            failed += 1
    if failed:
        logger.warning("Failed to remove %d stale tmp file(s) in config directory", failed)


def save_config(cfg: AppConfig, path: Path, *, create_if_missing: bool = False) -> None:
    """AppConfig を TOML に書き戻す。

    既存ファイルがあれば tomlkit でパースして値だけ更新し、コメント・空行を維持する。
    書き込みは tempfile + os.replace で atomic（クラッシュ時の partial write を防止）。

    既存ファイルがない場合の挙動は `create_if_missing` で制御する:
    - False（既定）: FileNotFoundError を呼び出し元に伝播。誤 path の silent 新規作成を防ぐ
    - True: 新規 TOMLDocument を作成して書き出し、親ディレクトリも自動作成する

    排他制御は行わない（単一プロセスからの呼び出しを前提）。複数プロセスが同じ path に
    同時書き込みした場合は「最後の os.replace 勝ち」になる。
    既存 [[reports.targets]] 配列内のコメントは置換時に失われる（要素間書式の保持は未対応）。
    """
    try:
        with path.open("r", encoding="utf-8") as f:
            doc = tomlkit.parse(f.read())
    except FileNotFoundError:
        if not create_if_missing:
            raise
        logger.warning("Config file not found at %s, creating new document", path)
        path.parent.mkdir(parents=True, exist_ok=True)
        doc = tomlkit.document()

    # API key / PII を含む平文 tmp がクラッシュ時に残ることがあるため、書き込み前に掃除
    _sweep_stale_tmp(path)

    app_data = {field: getattr(cfg, field) for field in _APP_FIELDS}
    _update_table_from_dataclass(doc, "app", app_data)

    for section in _SCALAR_SECTIONS:
        _update_table_from_dataclass(doc, section, asdict(getattr(cfg, section)))

    _update_pdf_merge(doc, cfg.pdf_merge)
    _update_reports(doc, cfg.reports)

    # tomlkit.dumps が例外を投げる場合は payload 生成前に伝播し、target は保持される。
    # tmp cleanup と PII を出さないログは atomic_io 側の責務（module docstring 参照）。
    payload = tomlkit.dumps(doc).encode("utf-8")
    write_bytes_atomically(path, payload, prefix=path.name + ".")
