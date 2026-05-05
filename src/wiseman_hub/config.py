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
from wiseman_hub.utils.text_norm import normalize_lookup_key

logger = logging.getLogger(__name__)

TableLike = Table | InlineTable
_TABLE_LIKE_TYPES: tuple[type, ...] = (Table, InlineTable)

ConcatSourceLetter = Literal["A", "B", "C"]
# concat_order の語彙は ``ConcatSourceLetter`` を single source of truth として導出する。
# D は ``source_d_filename`` 経由で末尾に追加される別系統のため、concat_order には含めない。
VALID_CONCAT_LETTERS: frozenset[ConcatSourceLetter] = frozenset(get_args(ConcatSourceLetter))


def _default_concat_order() -> tuple[ConcatSourceLetter, ...]:
    return ("A", "B", "C")


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
    concat_order: tuple[ConcatSourceLetter, ...] = field(default_factory=_default_concat_order)
    user_name_bbox: UserNameBBox = field(default_factory=UserNameBBox)
    facility_root_dir: str = ""
    ex_source_dir: str = ""
    facility_aliases: dict[str, list[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """concat_order の不変条件を検証する。

        TOML 由来の値は ``list[str]`` で渡るため runtime 検証で値域を担保する。
        Literal 型注釈は静的検査（mypy）で API 直接呼び出し時のタイポを catch する用途。

        Issue #151: 型注釈を tuple に変更したが、TOML / settings.py / 既存テスト
        経由で list が渡る経路が残るため、ここで tuple 化して mutation bypass
        (``cfg.concat_order.append("X")`` 等で __post_init__ 検証を迂回する経路)
        を構造的に防ぐ。dataclass は型強制しないため、呼出側の漏れを fail-safe に
        吸収する責務を __post_init__ に集約する。

        ``facility_aliases`` の検証は ``load_config`` 側の ``_validate_facility_aliases`` が
        担うため、ここでは触らない（dataclass 単体生成では検証されない既存設計を維持）。
        """
        if not isinstance(self.concat_order, tuple):
            self.concat_order = tuple(self.concat_order)
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
class ReportStaffEntry:
    """C(経過報告書) 用に、担当者ごとの xlsx 配置ルールを定義する。

    base_dir: 担当者フォルダの絶対パス（例: ``\\\\Tera-station\\share\\PT 宮下``）
    suggest_patterns: 候補 xlsx を絞り込む glob 風パターン（``{era}``/``{month}`` 埋め込み可）。
        複数指定可能で、上から順に試行され、いずれかに該当する xlsx を全て候補とする。
        パターン階層は ``/`` 区切り、ワイルドカード ``*`` のみサポート（再帰 ``**`` 不可）。
        例（PT 宮下）: ``["リハ経過報告書/令和*年/リハ経過報告書*{month}月*.xlsx"]``
        例（PT 木塚）: ``["経過報告書/令和*年度*/経過報告書*木塚*{month}月*.xlsx"]``
        空 list の場合は year_subfolder_template/file_template にフォールバック（後方互換）。

    year_subfolder_template / file_template:
        旧 MVP 互換フィールド（deprecated、suggest_patterns が空の場合のみ使用）。
        新規入力では suggest_patterns を使うこと。
    """

    base_dir: str = ""
    suggest_patterns: list[str] = field(default_factory=list)
    # deprecated（後方互換、suggest_patterns 空時のフォールバック）
    year_subfolder_template: str = ""
    file_template: str = ""


@dataclass
class ChecklistConfig:
    """スプレッドシート連携 B/C PDF 自動配置機能の設定（MVP）。

    spreadsheet_id: Google Drive 上の xlsx file id
    karte_root: B 用カルテルート（``\\\\Tera-station\\share\\02.カルテ``）
    monitoring_subfolder: 利用者フォルダ配下のモニタリング書類サブフォルダ名
    fax_root: 出力先 FAX 事業所ルート（``\\\\Tera-station\\share\\03.FAX(事業所)``）
    b_output_subfolder: FAX 事業所フォルダ配下の B 出力サブフォルダ名（運動機能向上計画書）
    c_output_subfolder: FAX 事業所フォルダ配下の C 出力サブフォルダ名（経過報告書）
    facility_routing: 居宅名（スプレッドシート O 列） → FAX 事業所フォルダ名 の辞書
    report_staff: 担当者名 → ReportStaffEntry の辞書（C 用 xlsx パス解決）
    xlsx_path_cache: 確定済み xlsx パスのキャッシュ。キー形式は ``"{staff}:{year}:{month}"``
        （例: ``"宮下:2026:3"``）、値は xlsx の絶対パス文字列。レビュー UI で
        ユーザーが選択した結果を永続化し、次回以降は cache hit で自動解決する。
        cache stale（path 不在）時はミスして再 scan する。
    """

    spreadsheet_id: str = "18RPsg3Ya0r7djQVzED5KAa5KyhbB9YRm"
    karte_root: str = "\\\\Tera-station\\share\\02.カルテ"
    monitoring_subfolder: str = "08.運動器機能向上計画書"
    fax_root: str = "\\\\Tera-station\\share\\03.FAX(事業所)"
    b_output_subfolder: str = "運動機能向上計画書"
    c_output_subfolder: str = "経過報告書"
    facility_routing: dict[str, str] = field(default_factory=dict)
    report_staff: dict[str, ReportStaffEntry] = field(default_factory=dict)
    xlsx_path_cache: dict[str, str] = field(default_factory=dict)


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
    checklist: ChecklistConfig = field(default_factory=ChecklistConfig)


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


def _coerce_report_staff_entry(staff_name: str, entry_data: dict[str, Any]) -> ReportStaffEntry:
    """TOML の checklist.report_staff.<name> table を ReportStaffEntry に強制変換する。

    suggest_patterns は list[str] の正規化:
        - キー存在 + 値が list でない → TypeError（空文字 ``""`` も不正、Codex review M6 対策）
        - 要素が str でない → TypeError
        - 空 list ``[]`` は正当（旧 *_template フォールバック対象）
    deprecated フィールド（year_subfolder_template / file_template）は str 強制。
    PII 配慮: 例外メッセージに担当者名は含めるが（運用上トラブルシュートに必要）、
    パス値は含めない（NAS 構造はログ送信先で機密扱いになる）。
    """
    suggest_patterns: list[str] = []
    if "suggest_patterns" in entry_data:
        suggest_data = entry_data.pop("suggest_patterns")
        if not isinstance(suggest_data, list):
            raise TypeError(
                f"checklist.report_staff.{staff_name}.suggest_patterns must be a list of strings; "
                f"got {type(suggest_data).__name__}"
            )
        for element in suggest_data:
            if not isinstance(element, str):
                raise TypeError(
                    f"checklist.report_staff.{staff_name}.suggest_patterns elements must be strings; "
                    f"got {type(element).__name__}"
                )
            suggest_patterns.append(element)
    return ReportStaffEntry(suggest_patterns=suggest_patterns, **entry_data)


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


def _resolve_sa_key_path(key_path_str: str, config_path: Path) -> str:
    """SA キーパスを絶対パスに解決する。

    - 絶対パスならそのまま返す
    - 相対パスの場合の起点:
        - 通常: ``config_path.parent`` （TOML の隣を見る）
        - ただし TOML 値が ``config/...`` 始まりかつ ``config_path`` 自身が
            ``config/`` 配下にある場合は、重複を避けるため一段上の
            ``config_path.parent.parent`` を起点にする
            （TOML 値はプロジェクトルート起点で書かれている既存運用に追従）
    - 空文字列はそのまま返す（GCP 機能未使用環境を許容）
    """
    if not key_path_str:
        return key_path_str
    p = Path(key_path_str)
    if p.is_absolute():
        return str(p)
    base = config_path.parent
    if (
        base.name == "config"
        and p.parts
        and p.parts[0] == "config"
    ):
        base = base.parent
    return str((base / p).resolve())


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
    gcp_data = dict(data.get("gcp", {}))
    if "service_account_key_path" in gcp_data:
        gcp_data["service_account_key_path"] = _resolve_sa_key_path(
            gcp_data["service_account_key_path"], path
        )
    updater_data = data.get("updater", {})
    ocr_backend_data = data.get("ocr_backend", {})
    pdf_merge_data = dict(data.get("pdf_merge", {}))

    # Issue #150 (PR #157 codex セカンドオピニオン High): TOML として合法な
    # `reports = "bad"` 等の型違反は元実装で AttributeError を raise していたため
    # __main__.main() の (OSError, ValueError, TypeError) 捕捉から漏れて exit code 1
    # に落ちていた。設定形状エラーは exit code 2 (config error) 扱いに寄せるべく、
    # `_coerce_facility_aliases` と同じく TypeError で fail-fast する。
    reports_section = data.get("reports", {})
    if not isinstance(reports_section, dict):
        raise TypeError(
            f"[reports] section must be a table; "
            f"got {type(reports_section).__name__}"
        )
    targets = reports_section.get("targets", [])
    if not isinstance(targets, list):
        raise TypeError(
            f"[reports].targets must be a list; got {type(targets).__name__}"
        )
    reports: list[ReportTarget] = []
    for target in targets:
        if not isinstance(target, dict):
            raise TypeError(
                f"[reports].targets entries must be tables; "
                f"got {type(target).__name__}"
            )
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

    checklist_data = dict(data.get("checklist", {}))
    routing_data = checklist_data.pop("facility_routing", {})
    staff_data = checklist_data.pop("report_staff", {})
    cache_data = checklist_data.pop("xlsx_path_cache", {})
    facility_routing: dict[str, str] = {}
    if routing_data:
        if not isinstance(routing_data, dict):
            raise TypeError(
                f"[checklist.facility_routing] must be a table; "
                f"got {type(routing_data).__name__}"
            )
        for key, value in routing_data.items():
            if not isinstance(value, str):
                raise TypeError(
                    "checklist.facility_routing values must be strings"
                )
            # PR-γ v1: lookup 表記揺れ吸収のため key は normalize_lookup_key
            # を通して保存する（全角/半角空白・全角/半角英数・括弧等を統一）
            facility_routing[normalize_lookup_key(str(key))] = value
    report_staff: dict[str, ReportStaffEntry] = {}
    if staff_data:
        if not isinstance(staff_data, dict):
            raise TypeError(
                f"[checklist.report_staff] must be a table; "
                f"got {type(staff_data).__name__}"
            )
        for staff_name, entry_data in staff_data.items():
            if not isinstance(entry_data, dict):
                raise TypeError(
                    "checklist.report_staff entries must be tables"
                )
            normalized_entry = _coerce_report_staff_entry(
                str(staff_name), dict(entry_data)
            )
            # PR-γ v1: 同上、staff key も lookup 正規化
            report_staff[normalize_lookup_key(str(staff_name))] = normalized_entry
    xlsx_path_cache: dict[str, str] = {}
    if cache_data:
        if not isinstance(cache_data, dict):
            raise TypeError(
                f"[checklist.xlsx_path_cache] must be a table; "
                f"got {type(cache_data).__name__}"
            )
        for key, value in cache_data.items():
            if not isinstance(value, str):
                raise TypeError(
                    "checklist.xlsx_path_cache values must be strings"
                )
            xlsx_path_cache[str(key)] = value
    checklist = ChecklistConfig(
        **checklist_data,
        facility_routing=facility_routing,
        report_staff=report_staff,
        xlsx_path_cache=xlsx_path_cache,
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
        checklist=checklist,
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


def _update_checklist(doc: TOMLDocument, checklist: ChecklistConfig) -> None:
    """[checklist] とネスト dict（facility_routing / report_staff / xlsx_path_cache）を書き戻す。

    動的キー dict は pdf_merge と同じく完全置換する。report_staff entry の suggest_patterns
    は list[str] のため tomlkit.array() で構築する。
    """
    routing = dict(checklist.facility_routing)
    staff = {
        name: asdict(entry) for name, entry in checklist.report_staff.items()
    }
    cache = dict(checklist.xlsx_path_cache)
    checklist_dict = asdict(checklist)
    checklist_dict.pop("facility_routing", None)
    checklist_dict.pop("report_staff", None)
    checklist_dict.pop("xlsx_path_cache", None)

    def _build_routing_table() -> Table:
        routing_table = tomlkit.table()
        for k, v in routing.items():
            routing_table[k] = v
        return routing_table

    def _build_staff_table() -> Table:
        staff_table = tomlkit.table()
        for name, entry in staff.items():
            inner = tomlkit.table()
            for k, v in entry.items():
                if isinstance(v, list):
                    arr = tomlkit.array()
                    for element in v:
                        arr.append(element)
                    inner[k] = arr
                else:
                    inner[k] = v
            staff_table[name] = inner
        return staff_table

    def _build_cache_table() -> Table:
        cache_table = tomlkit.table()
        for k, v in cache.items():
            cache_table[k] = v
        return cache_table

    if "checklist" in doc:
        table = _require_table(doc, "checklist")
        for key, value in checklist_dict.items():
            table[key] = value
        for nested in ("facility_routing", "report_staff", "xlsx_path_cache"):
            if nested in table:
                del table[nested]
        if routing:
            table["facility_routing"] = _build_routing_table()
        if staff:
            table["report_staff"] = _build_staff_table()
        if cache:
            table["xlsx_path_cache"] = _build_cache_table()
    else:
        new_table = tomlkit.table()
        for key, value in checklist_dict.items():
            new_table[key] = value
        if routing:
            new_table["facility_routing"] = _build_routing_table()
        if staff:
            new_table["report_staff"] = _build_staff_table()
        if cache:
            new_table["xlsx_path_cache"] = _build_cache_table()
        doc["checklist"] = new_table


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
    _update_checklist(doc, cfg.checklist)
    _update_reports(doc, cfg.reports)

    # tomlkit.dumps が例外を投げる場合は payload 生成前に伝播し、target は保持される。
    # tmp cleanup と PII を出さないログは atomic_io 側の責務（module docstring 参照）。
    payload = tomlkit.dumps(doc).encode("utf-8")
    write_bytes_atomically(path, payload, prefix=path.name + ".")
