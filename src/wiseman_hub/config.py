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
from typing import Any, Literal, get_args

import tomlkit
from tomlkit import TOMLDocument
from tomlkit.items import InlineTable, Table

from wiseman_hub.utils.atomic_io import write_bytes_atomically

logger = logging.getLogger(__name__)

TableLike = Table | InlineTable
_TABLE_LIKE_TYPES: tuple[type, ...] = (Table, InlineTable)

ConcatSourceLetter = Literal["A", "B", "C"]
# concat_order の語彙は ``ConcatSourceLetter`` を single source of truth として導出する。
# D は ``source_d_filename`` 経由で末尾に追加される別系統のため、concat_order には含めない。
VALID_CONCAT_LETTERS: frozenset[ConcatSourceLetter] = frozenset(get_args(ConcatSourceLetter))


def _default_concat_order() -> list[ConcatSourceLetter]:
    return ["A", "B", "C"]


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
    """OCRバックエンド（Cloud Runプロキシ）設定。詳細はADR-008参照。

    不変条件:
        - timeout_sec > 0（HTTP リクエストタイムアウトは正の整数のみ）
        - max_retries >= 0（再試行回数は非負）
    endpoint_url / api_key は「未設定」状態を許容（``is_configured`` で判定）。
    """

    endpoint_url: str = ""
    api_key: str = ""
    timeout_sec: int = 30
    max_retries: int = 3

    def __post_init__(self) -> None:
        if self.timeout_sec <= 0:
            raise ValueError(
                f"OcrBackendConfig.timeout_sec must be positive: {self.timeout_sec}"
            )
        if self.max_retries < 0:
            raise ValueError(
                f"OcrBackendConfig.max_retries must be non-negative: {self.max_retries}"
            )

    @property
    def is_configured(self) -> bool:
        """endpoint_url と api_key の両方が設定済みなら True（OCR 呼び出し可能）。"""
        return bool(self.endpoint_url and self.api_key)


@dataclass
class UserNameBBox:
    """利用者名が印字される固定矩形（PDFページ座標、ポイント単位）。

    不変条件:
        - dpi > 0（OCR 解像度は正の整数のみ、常時必須）
        - configured 時のみ x0 < x1 かつ y0 < y1（反転 bbox は OCR 切り出しで空画像になる）

    「未設定」状態（4 座標がすべて 0.0）は許容する。``AppConfig`` のデフォルト
    インスタンス化で例外が出ないようにするため、座標未入力時は不変条件チェックを skip。
    ``is_configured`` で運用側から判定する。
    """

    x0: float = 0.0
    y0: float = 0.0
    x1: float = 0.0
    y1: float = 0.0
    dpi: int = 200

    def __post_init__(self) -> None:
        if self.dpi <= 0:
            raise ValueError(f"UserNameBBox.dpi must be positive: {self.dpi}")
        # 「未設定」判定は座標 4 値が全 0 で固定（is_configured の定義変更に依存しない）。
        if self.x0 == 0.0 and self.y0 == 0.0 and self.x1 == 0.0 and self.y1 == 0.0:
            return
        if self.x0 >= self.x1:
            raise ValueError(
                f"UserNameBBox: x0 ({self.x0}) must be less than x1 ({self.x1})"
            )
        if self.y0 >= self.y1:
            raise ValueError(
                f"UserNameBBox: y0 ({self.y0}) must be less than y1 ({self.y1})"
            )

    @property
    def is_configured(self) -> bool:
        """4 座標いずれかが非ゼロなら configured（bbox が定義済み）。"""
        return any(v != 0.0 for v in (self.x0, self.y0, self.x1, self.y1))


@dataclass
class PdfMergeConfig:
    """PDF分割・条件付き再結合機能の設定。

    facility_root_dir: 事業所ルートフォルダ（複数事業所を一括処理する起点）。
        配下に `{事業所名}/{運動機能向上計画書,経過報告書}/` 構造を持つ親ディレクトリ。
        既存の input_dir / output_dir 等とは独立（旧 Phase A/B フローは無関係）。
        ADR-013 で導入。
    ex_source_dir: .ex_ ファイル（WinSFX32 LZH 自己解凍EXE）の取込元フォルダ。
        ex_extractor 機能で `.ex_ → PDF 抽出 → facility_root_dir 配下事業所フォルダ
        へ振り分け` の起点として使う。空文字列 ("") は未設定を意味し、consumer 側で
        空チェック必須（既存 facility_root_dir / input_dir 等と同じ str 規約）。
    facility_aliases: 事業所名の別名辞書。正式フォルダ名（key）に対する別名・略称・
        旧名称（value 配列）を保持し、ファイル名と事業所フォルダの照合で最優先一致
        として参照される。誤配布防止のため明示 alias 一致を部分一致系より優先する。
        例: {"本田デイケア": ["本田DC", "本田デイ"]}
        load_config 時に `_validate_facility_aliases` が以下を検証し、違反は raise:
            - key (正式名) が空文字列でない
            - value が list 型である（str を直接書くと文字単位分解されるため）
            - value 要素がすべて非空 str
            - 同じ list 内で alias 重複がない
            - 異なる事業所間で同じ alias が共有されていない（global 一意性）
            - alias が他事業所の正式名と一致しない（alias 一致と完全一致の衝突回避）
    """

    input_dir: str = ""
    output_dir: str = ""
    source_a_filename: str = ""
    source_d_filename: str = ""
    source_b_pattern: str = "B_{name}.pdf"
    source_c_pattern: str = "C_{name}.pdf"
    concat_order: list[ConcatSourceLetter] = field(default_factory=_default_concat_order)
    user_name_bbox: UserNameBBox = field(default_factory=UserNameBBox)
    facility_root_dir: str = ""
    ex_source_dir: str = ""
    facility_aliases: dict[str, list[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """concat_order の不変条件を検証する。

        TOML 由来の値は ``list[str]`` で渡るため runtime 検証で値域を担保する。
        Literal 型注釈は静的検査（mypy）で API 直接呼び出し時のタイポを catch する用途。

        ``facility_aliases`` の検証は ``load_config`` 側の ``_validate_facility_aliases`` が
        担うため、ここでは触らない（dataclass 単体生成では検証されない既存設計を維持）。
        """
        if not self.concat_order:
            raise ValueError("PdfMergeConfig.concat_order must not be empty")
        unknown = [s for s in self.concat_order if s not in VALID_CONCAT_LETTERS]
        if unknown:
            raise ValueError(
                f"PdfMergeConfig.concat_order contains unknown source(s): {unknown}; "
                f"valid letters are {sorted(VALID_CONCAT_LETTERS)}"
            )
        if len(self.concat_order) != len(set(self.concat_order)):
            raise ValueError(
                f"PdfMergeConfig.concat_order contains duplicates: {self.concat_order}"
            )


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


def _coerce_facility_aliases(aliases_data: Any) -> dict[str, list[str]]:
    """TOML の facility_aliases section を ``dict[str, list[str]]`` に強制変換する。

    型違反（value が list でない、要素が str でない）は ``TypeError`` で fail-fast する。
    PII 防御で例外メッセージには key/value の生値を含めず、構造的な型情報のみ出す
    （介護現場の事業所名・別名はログ送信先で機密扱いになる場合がある）。
    """
    coerced: dict[str, list[str]] = {}
    for key, value in dict(aliases_data).items():
        canonical = str(key)
        if not isinstance(value, list):
            raise TypeError(
                "facility_aliases value must be a list of strings; "
                f"got {type(value).__name__} for one entry"
            )
        normalized: list[str] = []
        for element in value:
            if not isinstance(element, str):
                raise TypeError(
                    "facility_aliases list elements must be strings; "
                    f"got {type(element).__name__}"
                )
            normalized.append(element)
        coerced[canonical] = normalized
    return coerced


def _validate_facility_aliases(aliases: dict[str, list[str]]) -> None:
    """事業所別名辞書の不変条件を検証する（介護現場の誤配布防止が最重要 KPI）。

    検証項目:
        1. 正式名 key が空文字列でない
        2. alias value 配列に空文字列が含まれない
        3. 同一事業所の配列内で alias が重複しない（無意味なノイズ）
        4. 異なる事業所間で同じ alias が共有されていない（global 一意性）
        5. alias が他事業所の正式名と一致しない（alias 一致と完全一致の衝突回避）

    自己参照（``{"X": [..., "X"]}``）は冗長だが誤配布リスクなしのため許容。

    違反時は ``ValueError`` で fail-fast。例外メッセージは構造的なエラー種別のみ
    含み、alias / 事業所名等の文字列は含めない（ADR-014 PII 防御 + Issue #150 の
    actionable error 経路を介した logger.error への漏洩防止）。具体的にどの alias が
    違反かは config TOML を直接確認する運用とする。
    """
    canonical_names = set(aliases.keys())
    seen_aliases: dict[str, str] = {}  # alias -> どの canonical に属しているか
    for canonical, alias_list in aliases.items():
        if not canonical:
            raise ValueError(
                "facility_aliases canonical name (key) must not be empty"
            )
        seen_in_facility: set[str] = set()
        for alias in alias_list:
            if not alias:
                raise ValueError(
                    "facility_aliases must not contain empty string alias"
                )
            if alias in seen_in_facility:
                raise ValueError(
                    "facility_aliases contains a duplicate alias within "
                    "the same facility"
                )
            seen_in_facility.add(alias)
            if alias == canonical:
                # 自己参照（冗長だが誤配布リスクなし）は許容、global 一意性チェックの対象外
                continue
            if alias in canonical_names:
                raise ValueError(
                    "facility_aliases contains an alias that conflicts with "
                    "another facility's canonical name"
                )
            if alias in seen_aliases:
                raise ValueError(
                    "facility_aliases contains an alias shared by multiple "
                    "facilities; aliases must be globally unique to prevent misrouting"
                )
            seen_aliases[alias] = canonical


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
    facility_aliases = _coerce_facility_aliases(aliases_data)
    _validate_facility_aliases(facility_aliases)
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

    ネスト table はスカラフィールドとは別ロジックで処理する 2 つの理由:
        1. ``asdict(pdf_merge)`` がネスト dataclass / dict を平坦化してしまい、スカラ
           更新ループ ``table[key] = value`` で TOML 表現が壊れる
        2. facility_aliases は動的キーを持つため、固定スキーマの dataclass 更新では
           扱えない（tomlkit.table() で新規構築する必要がある）

    そのため ``pdf_merge_dict`` から両ネスト field を pop してからスカラ更新を行い、
    ネスト系は専用ロジック（bbox は in-place 更新、aliases は完全置換）で処理する。
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

    先に既存 alias section を ``del`` してから（必要なら）新規 table を入れ直すことで、
    key 削除や rename を含む全変更パターンに 1 経路で対応する。

    制約: ``del`` した時点で alias section 内のユーザーコメント・空行は失われる
    （alias は dialog 経由での編集を前提とした設計）。section 外のコメント
    （[pdf_merge] 直下、bbox 内、ファイル冒頭等）は tomlkit により保持される。
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
