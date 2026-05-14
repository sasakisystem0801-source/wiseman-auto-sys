"""TOML設定ファイルのローダー / セーバー"""

from __future__ import annotations

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]
import logging
import math
import os
from dataclasses import asdict, dataclass, field
from glob import glob
from pathlib import Path
from typing import Any, Final, Literal, get_args

import tomlkit
from tomlkit import TOMLDocument
from tomlkit.items import InlineTable, Table

from wiseman_hub.utils.atomic_io import write_bytes_atomically
from wiseman_hub.utils.text_norm import normalize_lookup_key

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 型ガード helper (Issue #27 §2 水平展開)
#
# 各 dataclass の ``__post_init__`` から呼び出して、TOML パーサ経由 + 直接構築
# 双方の経路で型違反を起動時 ``TypeError`` で fail-close する。値違反 (range)
# は ``ValueError`` と区別する。
#
# 設計判断:
#   - ``bool`` は ``int`` サブクラスのため明示除外 (``isinstance(True, int)==True``
#     ですり抜けるため)
#   - PII 隠蔽: ``echo_value=False`` を指定するとエラーメッセージから値を除外
#     (api_key / spreadsheet_id / SA key path 等の秘密情報フィールド向け)
#   - エラーメッセージに ``type(v).__name__`` は常時含める (デバッグ可読性確保)
# ---------------------------------------------------------------------------


def _check_str(name: str, value: object, *, echo_value: bool = True) -> None:
    """型が ``str`` でなければ ``TypeError``。

    ``echo_value=False`` で値を ``{v!r}`` で出さない (PII 防御)。
    """
    if not isinstance(value, str):
        suffix = f": {value!r}" if echo_value else ""
        raise TypeError(
            f"{name} must be str, got {type(value).__name__}{suffix}"
        )


def _check_int(name: str, value: object) -> None:
    """型が ``int`` (bool 除く) でなければ ``TypeError``。

    bool は ``int`` サブクラスのため明示除外。``True == 1`` で後続の値範囲
    チェック (e.g. ``v <= 0``) や ``time.sleep(v)`` 経路をすり抜ける。
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(
            f"{name} must be int, got {type(value).__name__}: {value!r}"
        )


def _check_bool(name: str, value: object) -> None:
    """型が ``bool`` でなければ ``TypeError``。"""
    if not isinstance(value, bool):
        raise TypeError(
            f"{name} must be bool, got {type(value).__name__}: {value!r}"
        )


def _check_list_of_str(name: str, value: object) -> None:
    """``list[str]`` でなければ ``TypeError`` (要素まで検査)。"""
    if not isinstance(value, list):
        raise TypeError(
            f"{name} must be list, got {type(value).__name__}: {value!r}"
        )
    for i, item in enumerate(value):
        if not isinstance(item, str):
            raise TypeError(
                f"{name}[{i}] must be str, got "
                f"{type(item).__name__}: {item!r}"
            )


_UNSET_PATH_MARKER: Final[str] = "."
# Issue #27 続編 G §4: ``Path("") == Path()`` は ``str()`` 化すると ``.`` になる。
# これを「未設定 sentinel」として扱う規約。consumer が ``Path(".")`` を意図的に
# 設定値として書いた場合も未設定と判定される既知挙動 (umbrella 続編 G の Phase 2
# 以降で ``Optional[Path]`` への移行を検討)。


def is_path_configured(p: object) -> bool:
    """``Path`` が未設定 sentinel でなければ True。

    Issue #27 続編 G §4: 3 dataclass プロパティ + ``audit`` / ``audit_uploader``
    consumer 内で共通利用。sentinel 判定を 1 箇所に集約することで、将来 sentinel
    規約 (例: ``Optional[Path]`` 化) を変更しても呼出側 6+ 箇所を grep で追跡可能。

    判定基準 (Codex review Medium 反映、空白 Path も網羅):
        - ``Path("")`` (= ``Path(".")``) → False (未設定)
        - ``Path(".")`` 明示 → False (current dir は意図的にも sentinel と区別不能、
          Phase 2 で ``Optional[Path]`` 移行検討の根拠)
        - ``Path(" ")`` / ``Path("\\t")`` 等空白だけ → False (dataclass 直接構築
          経路でも sentinel 規約を一致させる)
        - 非空 Path → True

    Codex review Medium 対応 (非 Path defensive): 引数型を ``object`` に拡張し、
    ``None`` / str / その他の非 Path 入力は ``False`` を返す (consumer guard 用途
    に安全側で倒す)。legacy caller が ``append_audit_record(None, ...)`` 等を直接
    呼んでも、後段 TypeError ではなく no-op 経路に入り business 動作を維持する。
    """
    if not isinstance(p, Path):
        return False
    stripped = str(p).strip()
    return bool(stripped) and stripped != _UNSET_PATH_MARKER


def _check_path(name: str, value: object, *, echo_value: bool = True) -> None:
    """型が concrete ``pathlib.Path`` でなければ ``TypeError`` (Issue #27 続編 G §4)。

    str を Path に移行する dataclass フィールド (exe_path / log_dir / sa key path 等)
    で使用。空 Path (``Path("")`` = ``Path(".")``) は「未設定 sentinel」として
    許容し、consumer 側で ``is_configured`` プロパティで判定する規約。

    **PurePath subclass の取扱 (Codex review Low 対応)**: ``PurePosixPath`` /
    ``PureWindowsPath`` は ``isinstance(value, Path) == False`` で拒否される
    (concrete Path のみ受付)。実機 OS で path 操作 (``.exists()`` / ``.resolve()``)
    する dataclass 用途では PurePath を意図的に弾く設計。テスト fixture や OS 非依存
    な path 表現を扱う場合は呼出側で ``Path(str(pure_path))`` に変換すること。

    ``echo_value=False`` で値を ``{v!r}`` で出さない (PII 防御、SA key path 等)。
    """
    if not isinstance(value, Path):
        suffix = f": {value!r}" if echo_value else ""
        raise TypeError(
            f"{name} must be Path, got {type(value).__name__}{suffix}"
        )


def coerce_path(name: str, raw: Any, *, echo_value: bool = True) -> Path:
    """TOML から読まれる str / 既に Path / 未指定を Path に正規化する (Issue #27 続編 G §4)。

    load_config 内 + UI 経路 (``ui/settings.py`` form_to_config) で各 path
    フィールドの coerce に使用。``None`` / 空文字列 / 空白のみの文字列はすべて
    ``Path("")`` (未設定 sentinel) に正規化する。

    Codex review Medium 対応: ``Path`` 入力でも ``str(p).strip()`` が空 (e.g.
    ``Path(" ")``) なら ``Path("")`` (未設定) に正規化。これにより:
        - TOML 経路: str → strip → Path("") (旧挙動)
        - 直接構築経路: Path(" ") → strip → Path("") (Codex Medium 追加)
        - UI 経路: form.strip 後 → coerce_path → Path("")
    の全経路で sentinel 規約が一致する。

    型違反 (int / bool / list 等) は ``TypeError`` で fail-close。frozen dataclass
    の ``__post_init__`` ガードでも捕捉されるが、load_config 層で先に検出すると
    エラーメッセージが TOML パス起点で出せて actionable。
    """
    if raw is None:
        return Path("")
    if isinstance(raw, Path):
        # Path(" ") 等の空白だけの Path も未設定 sentinel に正規化 (Codex Medium 対応)。
        if not str(raw).strip():
            return Path("")
        return raw
    if isinstance(raw, bool) or not isinstance(raw, str):
        suffix = f": {raw!r}" if echo_value else ""
        raise TypeError(
            f"{name} must be str (TOML) or Path, got {type(raw).__name__}{suffix}"
        )
    stripped = raw.strip()
    if not stripped:
        return Path("")
    return Path(stripped)


def _check_dict_str_to_str(name: str, value: object) -> None:
    """``dict[str, str]`` でなければ ``TypeError`` (キー/値とも検査)。"""
    if not isinstance(value, dict):
        raise TypeError(
            f"{name} must be dict, got {type(value).__name__}: {value!r}"
        )
    for k, v in value.items():
        if not isinstance(k, str):
            raise TypeError(
                f"{name} key must be str, got {type(k).__name__}: {k!r}"
            )
        if not isinstance(v, str):
            raise TypeError(
                f"{name}[{k!r}] must be str, got {type(v).__name__}: {v!r}"
            )


def _require_section_table(name: str, value: Any) -> dict[str, Any]:
    """TOML section が dict (table) でなければ ``TypeError`` (#27 続編 B)。

    旧 load_config では ``dict(data.get("gcp", {}))`` 等で section 値を
    強制変換していたが、これは ``gcp = []`` を ``dict([])`` で ``{}`` 化して
    silent 通過させる経路があった (Codex review PR #260 致命的 1 反映)。
    本関数で section の型を起動時に厳格化し、配下 dataclass の
    ``__post_init__`` 型ガード設計を load_config 層で **無効化させない**。
    """
    if not isinstance(value, dict):
        raise TypeError(
            f"[{name}] section must be a table (TOML inline/block table), "
            f"got {type(value).__name__}: {value!r}"
        )
    return value


TableLike = Table | InlineTable
_TABLE_LIKE_TYPES: tuple[type, ...] = (Table, InlineTable)

ConcatSourceLetter = Literal["A", "B", "C"]
# concat_order の語彙は ``ConcatSourceLetter`` を single source of truth として導出する。
# D は ``source_d_filename`` 経由で末尾に追加される別系統のため、concat_order には含めない。
VALID_CONCAT_LETTERS: frozenset[ConcatSourceLetter] = frozenset(get_args(ConcatSourceLetter))

# Issue #27 続編 F Phase 1: 離散集合制約フィールドの Literal 化。
# 同じ ``Literal[...] + VALID_*`` パターンで mypy 静的検査と ``__post_init__`` 検証を統一する。

# AppConfig.log_level: Python ``logging`` 標準 5 値。誤値 ("info" / "DEBUGGING") は
# 起動時 ValueError で弾く (旧: ``_check_str`` のみで型はチェックするが値域は素通り)。
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
VALID_LOG_LEVELS: frozenset[LogLevel] = frozenset(get_args(LogLevel))

# ReportTarget.output_format: 現状運用 (RPA 経由 Wiseman CSV エクスポート) は csv 単一。
# 将来 xlsx/pdf 等を追加する際は本 Literal 拡張が起点 (Single source of truth)。
OutputFormat = Literal["csv"]
VALID_OUTPUT_FORMATS: frozenset[OutputFormat] = frozenset(get_args(OutputFormat))


def _check_literal(name: str, value: object, allowed: frozenset[Any]) -> None:
    """Literal 型フィールドの値域検証 helper。

    ``__post_init__`` から呼び、許容集合外の値を ``ValueError`` で弾く。``_check_str``
    との違いは「値域までチェックする」こと。先に str 型を ``_check_str`` で固めてから
    本 helper で値域を絞る使い方を想定。
    """
    if value not in allowed:
        raise ValueError(
            f"{name}: {value!r} is not in allowed set {sorted(allowed)}"
        )


def _default_concat_order() -> tuple[ConcatSourceLetter, ...]:
    return ("A", "B", "C")


def _coerce_concat_order(raw: Any) -> tuple[ConcatSourceLetter, ...]:
    """``concat_order`` を tuple 化し、空 / unknown / duplicate を ``ValueError`` で弾く。

    Issue #27 続編 E Phase 2 (PR #258 type-design-analyzer rating 7 対応):
        ``PdfMergeConfig`` を ``frozen=True`` 化するため、旧 ``__post_init__`` 内
        の ``self.concat_order = tuple(self.concat_order)`` 自己代入を本関数に
        外出しする。frozen dataclass の ``__init__`` 自動生成では ``__post_init__``
        での自己代入は ``FrozenInstanceError`` になり、``object.__setattr__`` 経由
        の bypass は型保証を黒魔術で迂回する黒い手段になるため採らない。

    呼出パターン:
        - ``load_config`` の TOML 経由 ``list[str]`` → tuple coerce
        - ``ui/settings.py`` の ``parsed_concat`` (form parser 出力、既に tuple)
        - 直接構築テストの ``concat_order=["A","B","C"]`` → tuple coerce

    値域検証:
        - 空 tuple は禁止 (最低 1 letter)
        - ``VALID_CONCAT_LETTERS`` 外の文字は禁止
        - 同一 letter の重複は禁止 (B が 2 回現れて B PDF を 2 重添付する事故防止)
    """
    coerced = tuple(raw)
    if not coerced:
        raise ValueError("PdfMergeConfig.concat_order must not be empty")
    unknown = [s for s in coerced if s not in VALID_CONCAT_LETTERS]
    if unknown:
        raise ValueError(
            f"PdfMergeConfig.concat_order contains unknown source(s): {unknown}; "
            f"valid letters are {sorted(VALID_CONCAT_LETTERS)}"
        )
    if len(coerced) != len(set(coerced)):
        raise ValueError(
            f"PdfMergeConfig.concat_order contains duplicates: {coerced}"
        )
    return coerced


def _require_table(container: Any, key: str) -> TableLike:
    """container[key] が table (Block or Inline) であることを保証して返す。

    TOML スキーマ違反（例: section が整数や文字列）を TypeError で明示する。
    """
    item = container[key]
    if not isinstance(item, _TABLE_LIKE_TYPES):
        raise TypeError(f"TOML key '{key}' is not a table (got {type(item).__name__})")
    assert isinstance(item, (Table, InlineTable))
    return item


@dataclass(frozen=True)
class WisemanConfig:
    """Wiseman SP 本体起動・ウィンドウ識別設定。

    Issue #27 続編 E Phase 2 (PR #258 type-design-analyzer rating 7 対応):
        ``frozen=True`` 化により post-construction mutation
        (``cfg.exe_path = "  "`` 等) で ``__post_init__`` 型ガードを bypass する
        経路を構造的に防ぐ。フィールド更新は ``replace()`` 経由 (UI 設定保存等)
        に統一する。

    Issue #27 続編 G Phase 1 (§4 Path 型移行):
        ``exe_path`` を ``str`` → ``Path`` に移行。``Path("")`` (= ``Path(".")``)
        を未設定 sentinel として扱い、``is_exe_configured`` プロパティで判定。
        consumer は ``Path(cfg.exe_path)`` の重複ラップを除去できる。external API
        (subprocess / pywinauto.Application.start) へは ``str(cfg.exe_path)`` で
        境界変換する。
    """

    exe_path: Path = field(default_factory=Path)  # ワイズマンSPの実行ファイルパス
    startup_wait_sec: int = 15  # 起動・ドングル認証待機秒数
    window_title_pattern: str = ".*管理システム SP.*"  # メインウィンドウのタイトルパターン

    def __post_init__(self) -> None:
        _check_path("WisemanConfig.exe_path", self.exe_path)
        _check_int("WisemanConfig.startup_wait_sec", self.startup_wait_sec)
        _check_str("WisemanConfig.window_title_pattern", self.window_title_pattern)

    @property
    def is_exe_configured(self) -> bool:
        """exe_path が未設定 sentinel でなければ True (Issue #27 続編 G §4)。

        consumer は ``cfg.exe_path / "file"`` 等の path 演算前に本プロパティで
        guard することで、未設定 Path との誤演算を防ぐ。判定ロジックは
        ``is_path_configured`` に集約 (sentinel 規約変更時の追従点を 1 箇所に)。
        """
        return is_path_configured(self.exe_path)


@dataclass(frozen=True)
class ScheduleConfig:
    """スケジューラ起動設定。

    Issue #27 続編 E Phase 3a (PR #258 type-design-analyzer rating 7 対応):
        ``frozen=True`` 化により post-construction mutation で ``__post_init__``
        型ガードを bypass する経路を構造的に防ぐ。フィールド更新は ``replace()``
        経由に統一する。
    """

    enabled: bool = False
    cron: str = "0 8 * * *"

    def __post_init__(self) -> None:
        _check_bool("ScheduleConfig.enabled", self.enabled)
        _check_str("ScheduleConfig.cron", self.cron)


@dataclass(frozen=True)
class ReportTarget:
    """個別レポート抽出ターゲット定義。

    Issue #27 続編 E Phase 3a: ``frozen=True`` 化により post-construction mutation
    で ``__post_init__`` 型ガードを bypass する経路を構造的に防ぐ。フィールド更新
    は ``replace()`` 経由に統一する。

    なお ``AppConfig.reports`` は ``list[ReportTarget]`` のため、list 自体の
    要素追加/削除 (``cfg.reports.append(...)``) は frozen 化の対象外 (list の
    内容変更を防ぐには ``AppConfig`` 側の type を ``tuple`` に変える別議論が必要)。
    """

    name: str = ""
    menu_path: list[str] = field(default_factory=list)
    output_format: OutputFormat = "csv"

    def __post_init__(self) -> None:
        _check_str("ReportTarget.name", self.name)
        _check_list_of_str("ReportTarget.menu_path", self.menu_path)
        _check_str("ReportTarget.output_format", self.output_format)
        _check_literal(
            "ReportTarget.output_format", self.output_format, VALID_OUTPUT_FORMATS
        )


@dataclass(frozen=True)
class GcpConfig:
    """GCP 接続設定。

    Issue #27 続編 E Phase 3a (PR #258 type-design-analyzer rating 7 対応):
        ``frozen=True`` 化により post-construction mutation で ``__post_init__``
        型ガードを bypass する経路を構造的に防ぐ。フィールド更新は ``replace()``
        経由に統一する。

    ADR-016 で bucket を data 用と release 用に分離する方針となったため、
    ``data_bucket_name`` / ``release_bucket_name`` を新規追加した。
    旧 ``bucket_name`` は backward compat 用に残置し、新フィールドが空の場合の
    fallback として使われる（``effective_data_bucket`` / ``effective_release_bucket``
    プロパティ経由）。

    **現在の利用状況（重要、Phase 2 時点）:**
        - ``audit_uploader`` (PR #198) は ``effective_data_bucket`` を経由するため、
          ``data_bucket_name`` 設定後は新 bucket に向く
        - **既存** ``cloud/mapping_sync.py`` / ``cloud/storage.py`` /
          ``cloud/env_scanner.py`` は ``gcp.bucket_name`` を **直接参照中**。
          これらの移行は ADR-016 Phase 4 以降の別 PR で実施する
        - したがって本 Phase 2 では **``bucket_name`` を空にしてはいけない**。
          単一 bucket 運用を続ける場合は ``bucket_name`` を残し、
          ``data_bucket_name`` は未設定（fallback で同一 bucket）で OK
        - ADR-016 Phase 4 以降で全モジュールを ``effective_*_bucket`` 経由に移行後、
          初めて ``bucket_name`` を空にできる

    **新規運用への移行ガイダンス（Phase 4 以降想定）:**
        - ``data_bucket_name = "wiseman-hub-data-prod"``  (audit / cache)
        - ``release_bucket_name = "wiseman-hub-release-prod"``  (exe / manifest / sbom)
        - ``bucket_name = ""`` （全モジュールが ``effective_*_bucket`` に移行後のみ）
    """

    project_id: str = ""
    bucket_name: str = ""  # backward compat: 旧 mapping_sync が直接参照
    data_bucket_name: str = ""  # ADR-016: audit / cache 用
    release_bucket_name: str = ""  # ADR-016: exe / manifest / sbom 用
    service_account_key_path: Path = field(default_factory=Path)
    region: str = "asia-northeast1"

    def __post_init__(self) -> None:
        _check_str("GcpConfig.project_id", self.project_id)
        _check_str("GcpConfig.bucket_name", self.bucket_name)
        _check_str("GcpConfig.data_bucket_name", self.data_bucket_name)
        _check_str("GcpConfig.release_bucket_name", self.release_bucket_name)
        # SA key path 自体は秘密ではないが key file 内容を推測されるリスクを
        # 下げるため PII 隠蔽 (defensive)。Issue #27 続編 G Phase 1: str → Path 移行。
        _check_path(
            "GcpConfig.service_account_key_path",
            self.service_account_key_path,
            echo_value=False,
        )
        _check_str("GcpConfig.region", self.region)

    @property
    def is_sa_key_configured(self) -> bool:
        """service_account_key_path が未設定 sentinel でなければ True。

        Issue #27 続編 G §4: google-auth ライブラリ呼出前の guard として
        consumer 側で本プロパティで先に check する規約。判定ロジックは
        ``is_path_configured`` に集約。
        """
        return is_path_configured(self.service_account_key_path)

    @property
    def effective_data_bucket(self) -> str:
        """data bucket 名（ADR-016 新フィールド優先、空なら旧 bucket_name）。"""
        return self.data_bucket_name or self.bucket_name

    @property
    def effective_release_bucket(self) -> str:
        """release bucket 名（ADR-016 新フィールド優先、空なら旧 bucket_name）。"""
        return self.release_bucket_name or self.bucket_name


@dataclass(frozen=True)
class UpdaterConfig:
    """自動アップデータ設定 (ADR-004)。

    Issue #27 続編 E Phase 3a: ``frozen=True`` 化により post-construction mutation
    で ``__post_init__`` 型ガードを bypass する経路を構造的に防ぐ。フィールド更新
    は ``replace()`` 経由に統一する。
    """

    enabled: bool = False
    check_interval_hours: int = 1
    release_bucket: str = ""

    def __post_init__(self) -> None:
        _check_bool("UpdaterConfig.enabled", self.enabled)
        _check_int("UpdaterConfig.check_interval_hours", self.check_interval_hours)
        _check_str("UpdaterConfig.release_bucket", self.release_bucket)


@dataclass(frozen=True)
class OcrBackendConfig:
    """OCRバックエンド（Cloud Runプロキシ）設定。詳細はADR-008参照。

    Issue #27 続編 E Phase 1 (PR #258 type-design-analyzer rating 7 対応):
        ``frozen=True`` 化により post-construction mutation
        (``cfg.endpoint_url = "  "`` 等) で ``__post_init__`` 型ガードを
        bypass する経路を構造的に防ぐ。フィールド更新は ``replace()`` 経由
        (UI 設定保存等) に統一する。

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
        _check_str("OcrBackendConfig.endpoint_url", self.endpoint_url)
        # api_key は秘密情報のため PII 防御で値を出さない
        _check_str("OcrBackendConfig.api_key", self.api_key, echo_value=False)
        _check_int("OcrBackendConfig.timeout_sec", self.timeout_sec)
        _check_int("OcrBackendConfig.max_retries", self.max_retries)
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
        """endpoint_url と api_key の両方が設定済みなら True（OCR 呼び出し可能）。

        Issue #152: 空白文字列のみ (``"   "`` / ``"\\t\\n"`` 等) は ``False`` 扱い。
        HTTP 呼び出し時の runtime 失敗を起動時 gate で防ぐ。
        """
        return bool(self.endpoint_url.strip() and self.api_key.strip())


@dataclass(frozen=True)
class UserNameBBox:
    """利用者名が印字される固定矩形（PDFページ座標、ポイント単位）。

    Issue #27 続編 E Phase 1 (PR #258 type-design-analyzer rating 7 対応):
        ``frozen=True`` 化により post-construction mutation
        (``bbox.x0 = float('nan')`` 等) で ``__post_init__`` 不変条件チェック
        を bypass する経路を構造的に防ぐ。フィールド更新は ``replace()`` 経由
        (UI 設定保存等) に統一する。

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
        # 座標は float field だが TOML で ``x0 = 10`` の int リテラルも許容するため
        # ``isinstance(v, (int, float))`` で受ける。bool は int サブクラスのため
        # ``math.isfinite(True) == True`` / ``True == 1`` で silent 通過するため
        # 別判定で除外する (_check_int / _check_str の helper 化対象外)。
        for name, v in (("x0", self.x0), ("y0", self.y0), ("x1", self.x1), ("y1", self.y1)):
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise TypeError(
                    f"UserNameBBox.{name} must be int or float, got "
                    f"{type(v).__name__}: {v!r}"
                )
        _check_int("UserNameBBox.dpi", self.dpi)
        if self.dpi <= 0:
            raise ValueError(f"UserNameBBox.dpi must be positive: {self.dpi}")
        # Issue #152: NaN/inf を弾く。NaN は ``x0 >= x1`` 比較が常に False となり、
        # 後続の不変条件チェック (x0<x1, y0<y1) をすり抜けて silent fail する。
        # 「未設定 return」より **前** に置く必要がある — NaN は ``v == 0.0`` も
        # False のため未設定判定にも引っ掛からず、return しないまま比較段に進む。
        for name, v in (("x0", self.x0), ("y0", self.y0), ("x1", self.x1), ("y1", self.y1)):
            if not math.isfinite(v):
                raise ValueError(f"UserNameBBox.{name} must be finite (no NaN/inf): {v}")
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


@dataclass(frozen=True)
class PdfMergeConfig:
    """PDF分割・条件付き再結合機能の設定。

    Issue #27 続編 E Phase 2 (PR #258 type-design-analyzer rating 7 対応):
        ``frozen=True`` 化により post-construction mutation
        (``cfg.concat_order = ("X",)`` 等) で ``__post_init__`` 不変条件チェック
        を bypass する経路を構造的に防ぐ。フィールド更新は ``replace()`` 経由
        (UI 設定保存等) に統一する。

        旧 ``__post_init__`` 内の ``self.concat_order = tuple(self.concat_order)``
        自己代入は ``_coerce_concat_order()`` helper に外出しした。呼出側で
        TOML / form parser / 直接構築のすべてが tuple を渡す責務を負う。

    facility_root_dir: 事業所ルートフォルダ（複数事業所を一括処理する起点）。
        配下に `{事業所名}/{運動機能向上計画書,経過報告書}/` 構造を持つ親ディレクトリ。
        既存の input_dir / output_dir 等とは独立（旧 Phase A/B フローは無関係）。
        ADR-013 で導入。
    ex_source_dir: .ex_ ファイル（WinSFX32 LZH 自己解凍EXE）の取込元フォルダ。
        ex_extractor 機能で `.ex_ → PDF 抽出 → facility_root_dir 配下事業所フォルダ
        へ振り分け` の起点として使う。未設定 (``Path("")``) は consumer 側で
        ``is_path_configured`` チェック必須（既存 facility_root_dir / input_dir 等と
        同じ Path 規約、Issue #27 続編 G Phase 2a/2b で str → Path に統一）。
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

    # Issue #27 続編 G Phase 2a/2b: input_dir / output_dir / ex_source_dir / facility_root_dir
    # を Path 化完了。source_*_filename / source_*_pattern は ファイル名 / glob パターン
    # であり Path 化対象外 (str 維持)。
    input_dir: Path = field(default_factory=Path)
    output_dir: Path = field(default_factory=Path)
    source_a_filename: str = ""
    source_d_filename: str = ""
    source_b_pattern: str = "B_{name}.pdf"
    source_c_pattern: str = "C_{name}.pdf"
    concat_order: tuple[ConcatSourceLetter, ...] = field(default_factory=_default_concat_order)
    user_name_bbox: UserNameBBox = field(default_factory=UserNameBBox)
    facility_root_dir: Path = field(default_factory=Path)
    ex_source_dir: Path = field(default_factory=Path)
    facility_aliases: dict[str, list[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """concat_order の不変条件を検証する。

        Issue #27 続編 E Phase 2 (frozen 化):
            旧実装の ``self.concat_order = tuple(self.concat_order)`` 自己代入は
            frozen dataclass では不可。tuple 化責務は ``_coerce_concat_order()``
            helper に外出しし、呼出側 (load_config / settings.py / 直接構築テスト)
            が tuple を渡す前提に切り替えた。本 ``__post_init__`` は **入力が tuple
            であることを確認した上で値域検証のみ実施** する fail-safe 層に役割変更。

            ``_coerce_concat_order()`` を経由しない直接構築で list 等が渡った場合は
            ``TypeError`` を起動時に raise し、silent fallback を作らない。

        ``facility_aliases`` の検証は ``load_config`` 側の ``_validate_facility_aliases``
        が担うため、ここでは触らない（dataclass 単体生成では検証されない既存設計を維持）。
        """
        # Issue #27 続編 G Phase 2a/2b: path field 4 件を型ガード。
        _check_path("PdfMergeConfig.input_dir", self.input_dir)
        _check_path("PdfMergeConfig.output_dir", self.output_dir)
        _check_path("PdfMergeConfig.ex_source_dir", self.ex_source_dir)
        _check_path("PdfMergeConfig.facility_root_dir", self.facility_root_dir)
        if not isinstance(self.concat_order, tuple):
            raise TypeError(
                f"PdfMergeConfig.concat_order must be tuple "
                f"(use _coerce_concat_order() for list inputs), "
                f"got {type(self.concat_order).__name__}: {self.concat_order!r}"
            )
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


@dataclass(frozen=True)
class ReportStaffEntry:
    """C(経過報告書) 用に、担当者ごとの xlsx 配置ルールを定義する。

    Issue #27 続編 E Phase 3a: ``frozen=True`` 化により post-construction mutation
    で ``__post_init__`` 型ガードを bypass する経路を構造的に防ぐ。フィールド更新
    は ``replace()`` 経由に統一する。

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

    def __post_init__(self) -> None:
        _check_str("ReportStaffEntry.base_dir", self.base_dir)
        _check_list_of_str("ReportStaffEntry.suggest_patterns", self.suggest_patterns)
        _check_str("ReportStaffEntry.year_subfolder_template", self.year_subfolder_template)
        _check_str("ReportStaffEntry.file_template", self.file_template)


# PR #233 substring match 化以前の旧 default 値。本田様 PC 等で TOML に保存
# された旧値が PR #233 の自動吸収を bypass する事故防止のため、ChecklistConfig
# 構築時に検出して logger.warning で気付ける仕組みを提供する。
# canonical name (= "運動器機能向上計画書") を含む他のバリアントは folder 側の
# 揺らぎとして substring match が吸収するため、設定値としての legacy 検出は
# 完全一致の固定値に絞る (= 過剰警告防止)。
_LEGACY_MONITORING_SUBFOLDERS: Final[frozenset[str]] = frozenset({
    "08.運動器機能向上計画書",
    "10.運動器機能向上計画書",
})


@dataclass(frozen=True)
class ChecklistConfig:
    """スプレッドシート連携 B/C PDF 自動配置機能の設定（MVP）。

    Issue #27 続編 E Phase 3a: ``frozen=True`` 化により post-construction mutation
    で ``__post_init__`` 型ガードを bypass する経路を構造的に防ぐ。フィールド更新
    は ``replace()`` 経由に統一する。

    なお ``facility_routing`` / ``report_staff`` / ``xlsx_path_cache`` は
    ``dict[str, ...]`` のため、dict 自体の内容変更 (``cfg.facility_routing["X"] = "Y"``)
    は frozen 化の対象外 (参照差し替え ``cfg.facility_routing = {...}`` のみ阻止)。
    値内容の immutability が必要なら ``frozenmap`` 等の不変 dict 型への移行を別途検討する。

    spreadsheet_id: Google Drive 上の xlsx file id
    karte_root: B 用カルテルート（``\\\\Tera-station\\share\\02.カルテ``）
    monitoring_subfolder: 利用者フォルダ配下のモニタリング書類サブフォルダ名
        (canonical name のみ、Issue #monitoring-substring 2026-05-09)。
        substring match で `08.<canonical>` / `10.<canonical>` / prefix なし /
        `<canonical>(過去分)` 等の揺らぎを吸収する。default は
        ``"運動器機能向上計画書"``。
        ``__post_init__`` で ``_LEGACY_MONITORING_SUBFOLDERS`` (旧 default 値)
        を検出して ``logger.warning`` で気付ける (PR #233 後の救済)。
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
    monitoring_subfolder: str = "運動器機能向上計画書"
    fax_root: str = "\\\\Tera-station\\share\\03.FAX(事業所)"
    b_output_subfolder: str = "運動機能向上計画書"
    c_output_subfolder: str = "経過報告書"
    facility_routing: dict[str, str] = field(default_factory=dict)
    report_staff: dict[str, ReportStaffEntry] = field(default_factory=dict)
    xlsx_path_cache: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """型ガード (#27 §2 水平展開) + legacy ``monitoring_subfolder`` 検出。

        型ガードを先に走らせ、その後 legacy 値の WARNING 検出を続ける
        (PR #233 (2026-05-09) で導入した既存挙動を保持)。

        legacy WARNING: PR #233 で ``monitoring_subfolder`` の運用を
        canonical name + substring match に変更した。本田様 PC 等で旧 default
        値が保存済 TOML に残ると新ロジックの prefix/suffix 自動吸収が効かない
        ため、構築時に検出して ``logger.warning`` で気付ける。
        現時点でも値そのものは動作するため (完全一致 prefix で 1 件だけ HIT する
        運用は維持)、エラーではなく WARNING にする。
        """
        # spreadsheet_id は Google Drive file id (URL 推測可能) のため PII 隠蔽
        _check_str(
            "ChecklistConfig.spreadsheet_id",
            self.spreadsheet_id,
            echo_value=False,
        )
        _check_str("ChecklistConfig.karte_root", self.karte_root)
        _check_str("ChecklistConfig.monitoring_subfolder", self.monitoring_subfolder)
        _check_str("ChecklistConfig.fax_root", self.fax_root)
        _check_str("ChecklistConfig.b_output_subfolder", self.b_output_subfolder)
        _check_str("ChecklistConfig.c_output_subfolder", self.c_output_subfolder)
        _check_dict_str_to_str(
            "ChecklistConfig.facility_routing", self.facility_routing
        )
        # report_staff は dict[str, ReportStaffEntry] (dataclass 値) なので直接検査
        if not isinstance(self.report_staff, dict):
            raise TypeError(
                f"ChecklistConfig.report_staff must be dict, got "
                f"{type(self.report_staff).__name__}: {self.report_staff!r}"
            )
        for k, v in self.report_staff.items():
            if not isinstance(k, str):
                raise TypeError(
                    f"ChecklistConfig.report_staff key must be str, got "
                    f"{type(k).__name__}: {k!r}"
                )
            if not isinstance(v, ReportStaffEntry):
                raise TypeError(
                    f"ChecklistConfig.report_staff[{k!r}] must be ReportStaffEntry, "
                    f"got {type(v).__name__}"
                )
        _check_dict_str_to_str(
            "ChecklistConfig.xlsx_path_cache", self.xlsx_path_cache
        )

        if self.monitoring_subfolder in _LEGACY_MONITORING_SUBFOLDERS:
            logger.warning(
                "monitoring_subfolder='%s' is a legacy value. "
                "PR #233 (2026-05-09) introduced substring matching, so set this "
                "to the canonical name '運動器機能向上計画書' to enable "
                "automatic absorption of prefix/suffix variants "
                "(e.g. '10.運動器機能向上計画書', '運動器機能向上計画書(過去分)'). "
                "Current value still works for exact prefix match but bypasses the new behavior.",
                self.monitoring_subfolder,
            )


@dataclass(frozen=True)
class AppConfig:
    """アプリケーション全体の設定 (root)。

    Issue #27 続編 E Phase 3b (PR #258 type-design-analyzer rating 7 対応):
        ``frozen=True`` 化により **直下フィールドの参照差し替え** を構造的に防ぐ。
        ``cfg.pdf_merge = ...`` / ``cfg.version = ...`` 等の attribute 代入は
        ``FrozenInstanceError`` で拒否され、結果として post-construction で
        ``__post_init__`` 型ガードを bypass する経路が閉鎖される。
        フィールド更新は ``replace()`` 経由に統一し、ネスト dataclass の更新は
        ``cfg = replace(cfg, pdf_merge=replace(cfg.pdf_merge, input_dir=...))``
        形式で行う。

    **frozen 化の対象外 (mutable leaf の内容変更)**:
        ``reports`` は ``list[ReportTarget]`` 型のため、参照差し替え
        (``cfg.reports = [...]``) は阻止できるが、list 内容変更
        (``cfg.reports.append(...)`` / ``cfg.reports[0] = ...``) は阻止できない。
        ``ReportTarget.menu_path`` の list も同様 (Phase 3a で frozen=True 化済だが
        leaf list は別)。完全 immutability が必要なら type を
        ``tuple[ReportTarget, ...]`` に変える別議論が必要 (umbrella §1 Literal 拡張
        側で扱う)。

    本 docstring の表現は PR #272 Codex review Low 指摘に基づき、「型ガード
    bypass を構造的に防ぐ」を「直下フィールドの参照差し替えを防ぐ」に絞って
    記載 (mutable leaf の内容変更まで防げると誤解されないように)。
    """

    version: str = "0.1.0"
    log_level: LogLevel = "INFO"
    log_dir: Path = field(default_factory=Path)
    wiseman: WisemanConfig = field(default_factory=WisemanConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    reports: list[ReportTarget] = field(default_factory=list)
    gcp: GcpConfig = field(default_factory=GcpConfig)
    updater: UpdaterConfig = field(default_factory=UpdaterConfig)
    ocr_backend: OcrBackendConfig = field(default_factory=OcrBackendConfig)
    pdf_merge: PdfMergeConfig = field(default_factory=PdfMergeConfig)
    checklist: ChecklistConfig = field(default_factory=ChecklistConfig)

    def __post_init__(self) -> None:
        """AppConfig 自体の str field + reports list 要素を型ガード。

        ネスト dataclass (wiseman/schedule/gcp/...) は各々の ``__post_init__`` で
        守られるが、``AppConfig`` 直下の ``version`` / ``log_level`` / ``log_dir`` /
        ``reports`` は本層で守る (silent-failure-hunter PR #260 review 反映)。
        """
        _check_str("AppConfig.version", self.version)
        _check_str("AppConfig.log_level", self.log_level)
        _check_literal("AppConfig.log_level", self.log_level, VALID_LOG_LEVELS)
        # Issue #27 続編 G Phase 1: log_dir を str → Path 移行。
        _check_path("AppConfig.log_dir", self.log_dir)
        if not isinstance(self.reports, list):
            raise TypeError(
                f"AppConfig.reports must be list, got "
                f"{type(self.reports).__name__}: {self.reports!r}"
            )
        for i, item in enumerate(self.reports):
            if not isinstance(item, ReportTarget):
                raise TypeError(
                    f"AppConfig.reports[{i}] must be ReportTarget, got "
                    f"{type(item).__name__}"
                )

    @property
    def is_log_dir_configured(self) -> bool:
        """log_dir が未設定 sentinel でなければ True (Issue #27 続編 G §4)。

        audit ログ / cloud uploader 等の consumer は本プロパティ、または
        ``log_dir`` を単体で受け取る関数では ``is_path_configured(log_dir)`` で guard。
        """
        return is_path_configured(self.log_dir)


def _coerce_facility_aliases(aliases_data: Any) -> dict[str, list[str]]:
    """TOML の facility_aliases section を ``dict[str, list[str]]`` に強制変換する。

    型違反（value が list でない、要素が str でない）は ``TypeError`` で fail-fast する。
    PII 防御で例外メッセージには key/value の生値を含めず、構造的な型情報のみ出す
    （介護現場の事業所名・別名はログ送信先で機密扱いになる場合がある）。

    Issue #27 続編 B (Codex PR #261 review 致命的残存): section 自体の型を
    ``_require_section_table`` で先頭で守る。旧 ``dict(aliases_data).items()`` は
    ``facility_aliases = []`` を ``dict([])`` で ``{}`` 化、silent 通過していた。
    """
    aliases_data = _require_section_table("pdf_merge.facility_aliases", aliases_data)
    coerced: dict[str, list[str]] = {}
    for key, value in aliases_data.items():
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


def _resolve_sa_key_path(key_path: Path, config_path: Path) -> Path:
    """SA キーパスを絶対パスに解決する (Issue #27 続編 G §4: str → Path 移行)。

    - 絶対パスならそのまま返す
    - 相対パスの場合の起点:
        - 通常: ``config_path.parent`` （TOML の隣を見る）
        - ただし TOML 値が ``config/...`` 始まりかつ ``config_path`` 自身が
            ``config/`` 配下にある場合は、重複を避けるため一段上の
            ``config_path.parent.parent`` を起点にする
            （TOML 値はプロジェクトルート起点で書かれている既存運用に追従）
    - 空 Path (``Path("")`` = ``Path(".")``) はそのまま返す (GCP 機能未使用環境を許容)

    Issue #27 続編 G Phase 1: 引数・戻り値とも ``str`` → ``Path``。空 sentinel
    の判定は ``str(key_path) == "."`` で行う (``Path("") == Path(".")``)。
    """
    if str(key_path) == ".":
        return key_path
    if key_path.is_absolute():
        return key_path
    base = config_path.parent
    if (
        base.name == "config"
        and key_path.parts
        and key_path.parts[0] == "config"
    ):
        base = base.parent
    return (base / key_path).resolve()


def load_config(path: Path | None = None) -> AppConfig:
    """TOML設定ファイルを読み込んでAppConfigを返す。"""
    if path is None:
        path = Path("config/default.toml")

    if not path.exists():
        return AppConfig()

    with open(path, "rb") as f:
        data: dict[str, Any] = tomllib.load(f)

    # Issue #27 続編 B (Codex PR #260 review 致命的 1): 各 section 値を
    # ``_require_section_table`` で厳格化。旧 ``dict(data.get(...))`` は
    # ``gcp = []`` 等を ``{}`` 化して silent 通過させていた。
    app_data = dict(_require_section_table("app", data.get("app", {})))
    wiseman_data = dict(_require_section_table("wiseman", data.get("wiseman", {})))
    schedule_data = _require_section_table("schedule", data.get("schedule", {}))
    gcp_data = dict(_require_section_table("gcp", data.get("gcp", {})))
    if "service_account_key_path" in gcp_data:
        # Issue #27 続編 G Phase 1: TOML str → Path coerce (空白 strip → 空 Path)
        # coerce_path で None/空白を Path("") に正規化し、_resolve_sa_key_path で
        # 絶対パスに展開する。型違反 (int 等) は coerce_path が TypeError raise。
        gcp_data["service_account_key_path"] = _resolve_sa_key_path(
            coerce_path(
                "gcp.service_account_key_path",
                gcp_data["service_account_key_path"],
                echo_value=False,
            ),
            path,
        )
    updater_data = _require_section_table("updater", data.get("updater", {}))
    ocr_backend_data = _require_section_table(
        "ocr_backend", data.get("ocr_backend", {})
    )
    pdf_merge_data = dict(
        _require_section_table("pdf_merge", data.get("pdf_merge", {}))
    )

    # Issue #150 (PR #157 codex セカンドオピニオン High): TOML として合法な
    # `reports = "bad"` 等の型違反は元実装で AttributeError を raise していたため
    # __main__.main() の (OSError, ValueError, TypeError) 捕捉から漏れて exit code 1
    # に落ちていた。設定形状エラーは exit code 2 (config error) 扱いに寄せるべく、
    # `_coerce_facility_aliases` と同じく TypeError で fail-fast する。
    # Issue #27 続編 D: 他の 8 section と同じく ``_require_section_table`` に
    # 統一する (silent-failure-hunter rating 6)。
    reports_section = _require_section_table("reports", data.get("reports", {}))
    targets = reports_section.get("targets", [])
    if not isinstance(targets, list):
        raise TypeError(
            f"[reports].targets must be a list; got {type(targets).__name__}"
        )
    reports: list[ReportTarget] = []
    for i, target in enumerate(targets):
        if not isinstance(target, dict):
            raise TypeError(
                f"[reports].targets[{i}] must be a table; "
                f"got {type(target).__name__}: {target!r}"
            )
        reports.append(ReportTarget(**target))

    # Issue #27 続編 D: ``pop`` の戻り値を ``_require_section_table`` で守る。
    # 旧コード ``UserNameBBox(**bbox_data)`` は ``user_name_bbox = []`` 等で
    # generic ``TypeError: argument of type 'list' is not a mapping`` を raise し、
    # どの section の問題か分からなかった (silent-failure-hunter rating 6)。
    bbox_data = _require_section_table(
        "pdf_merge.user_name_bbox", pdf_merge_data.pop("user_name_bbox", {})
    )
    aliases_data = pdf_merge_data.pop("facility_aliases", {})
    facility_aliases = _coerce_facility_aliases(aliases_data)
    _validate_facility_aliases(facility_aliases)
    # Issue #27 続編 E Phase 2: PdfMergeConfig が frozen=True 化されたため、
    # __post_init__ の自己代入 ``self.concat_order = tuple(...)`` を廃止し、
    # TOML 経由の ``list[str]`` を ``_coerce_concat_order()`` で tuple 化して
    # コンストラクタに渡す。TOML に concat_order キーが無い場合は default factory 任せ。
    if "concat_order" in pdf_merge_data:
        pdf_merge_data["concat_order"] = _coerce_concat_order(
            pdf_merge_data["concat_order"]
        )
    # Issue #27 続編 G Phase 2a/2b: TOML str → Path coerce (空白 strip → 未設定 sentinel)。
    # 型違反 (int / bool / list 等) は coerce_path が TypeError raise (起動時 fail-close)。
    for path_field in ("input_dir", "output_dir", "ex_source_dir", "facility_root_dir"):
        if path_field in pdf_merge_data:
            pdf_merge_data[path_field] = coerce_path(
                f"pdf_merge.{path_field}", pdf_merge_data[path_field]
            )
    pdf_merge = PdfMergeConfig(
        **pdf_merge_data,
        user_name_bbox=UserNameBBox(**bbox_data),
        facility_aliases=facility_aliases,
    )

    checklist_data = dict(
        _require_section_table("checklist", data.get("checklist", {}))
    )
    routing_data = checklist_data.pop("facility_routing", {})
    staff_data = checklist_data.pop("report_staff", {})
    cache_data = checklist_data.pop("xlsx_path_cache", {})

    # Issue #27 続編 B (Codex PR #260 review): isinstance 判定を ``if routing_data:``
    # の **前** に置く。旧コード ``if routing_data: ... isinstance check`` は
    # ``routing_data = []`` (空 list) / ``false`` / ``0`` が falsy で if 分岐に
    # 入らないため silent 通過する経路があった。
    if not isinstance(routing_data, dict):
        raise TypeError(
            f"[checklist.facility_routing] must be a table; "
            f"got {type(routing_data).__name__}: {routing_data!r}"
        )
    facility_routing: dict[str, str] = {}
    for key, value in routing_data.items():
        if not isinstance(value, str):
            raise TypeError(
                "checklist.facility_routing values must be strings"
            )
        # PR-γ v1: lookup 表記揺れ吸収のため key は normalize_lookup_key
        # を通して保存する（全角/半角空白・全角/半角英数・括弧等を統一）
        facility_routing[normalize_lookup_key(str(key))] = value

    if not isinstance(staff_data, dict):
        raise TypeError(
            f"[checklist.report_staff] must be a table; "
            f"got {type(staff_data).__name__}: {staff_data!r}"
        )
    report_staff: dict[str, ReportStaffEntry] = {}
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

    if not isinstance(cache_data, dict):
        raise TypeError(
            f"[checklist.xlsx_path_cache] must be a table; "
            f"got {type(cache_data).__name__}: {cache_data!r}"
        )
    xlsx_path_cache: dict[str, str] = {}
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

    # Issue #27 続編 G Phase 1: AppConfig.log_dir / WisemanConfig.exe_path を
    # str → Path coerce。空白 strip → Path("") (未設定 sentinel)。型違反は
    # coerce_path が TypeError raise (起動時 fail-close)。
    if "exe_path" in wiseman_data:
        wiseman_data["exe_path"] = coerce_path(
            "wiseman.exe_path", wiseman_data["exe_path"]
        )

    return AppConfig(
        version=app_data.get("version", "0.1.0"),
        log_level=app_data.get("log_level", "INFO"),
        log_dir=coerce_path("app.log_dir", app_data.get("log_dir", "")),
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


def stringify_paths_recursive(obj: Any) -> Any:
    """ネスト dict / list / tuple 内の ``Path`` を再帰的に str に正規化する。

    Issue #27 続編 G Phase 2a (evaluator MEDIUM 対応):
        ``_stringify_path_values`` は shallow only (Phase 1 evaluator MEDIUM 対応で
        ``_update_pdf_merge`` / ``_update_checklist`` の **各 nested asdict** に
        別個適用する方針)。一方、``pdf/session.py`` の ``json.dumps(config_snapshot)``
        経路では ``asdict(AppConfig)`` の **任意深度** nested 構造 (wiseman /
        gcp / pdf_merge / checklist / 等) が渡される。これらに対しても TOML 規約
        (未設定 Path → ``""``、設定済み → ``str(path)``) を適用するため、再帰版を
        config.py に集約する。

    判定:
        - ``Path`` のうち未設定 sentinel (``is_path_configured == False``) → ``""``
        - ``Path`` のうち設定済み → ``str(path)``
        - ``dict`` / ``list`` / ``tuple`` → 各要素を再帰展開 (tuple は JSON 互換性
          のため list に変換)
        - その他 (str / int / bool / float / None) → そのまま返す

    consumer: ``session.py`` の ``_to_dict`` 経由で ``config_snapshot`` の Path を
    境界変換する。``save_config`` 経路は ``_stringify_path_values`` (shallow) で
    各 section ごとに処理しているため別。
    """
    if isinstance(obj, Path):
        return "" if not is_path_configured(obj) else str(obj)
    if isinstance(obj, dict):
        return {k: stringify_paths_recursive(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [stringify_paths_recursive(v) for v in obj]
    if isinstance(obj, tuple):
        return [stringify_paths_recursive(v) for v in obj]
    return obj


def _stringify_path_values(data: dict[str, Any]) -> dict[str, Any]:
    """``Path`` 値を ``str`` に正規化する (Issue #27 続編 G §4: TOML 書き込み境界)。

    ``asdict()`` は Path をそのまま (Path オブジェクトのまま) 返すため、tomlkit
    に直接渡すと TOML 不正値になる。本 helper で str 変換し、save_config の
    Path → str ラウンドトリップ責務をここに集約する。

    Path 以外の値はそのまま返す。

    **未設定 Path の書出規約 (Codex review High 対応)**:
        ``Path("")`` (= ``Path(".")``) を ``str()`` 化すると ``"."`` になり、
        TOML に ``log_dir = "."`` として保存されると **「カレントディレクトリ指定」
        と誤解される silent 互換性劣化** を招く (旧バージョンへのダウングレード /
        手動 TOML 編集 / 将来の外部ツール経由)。本 helper では未設定 Path を
        空文字列 ``""`` に書き戻し、旧 str 時代の TOML 表現を保つ。

    **CAUTION (shallow only)**: ネスト dict / list / dataclass の中の Path は
    変換**されない**。Phase 2 以降で nested dataclass (例: ``ReportStaffEntry.base_dir``)
    に Path field を追加する場合、呼出側 (``_update_pdf_merge`` / ``_update_checklist``)
    で **各ネスト level の asdict() 結果に対しても本 helper を適用** すること。
    現 Phase 1 では ``_update_pdf_merge`` / ``_update_checklist`` で防御的に
    各 nested asdict に通している (Phase 2 silent fail 予防、evaluator MEDIUM 対応)。
    """
    result: dict[str, Any] = {}
    for k, v in data.items():
        if isinstance(v, Path):
            result[k] = "" if not is_path_configured(v) else str(v)
        else:
            result[k] = v
    return result


def _update_table_from_dataclass(doc: TOMLDocument, section: str, data: dict[str, Any]) -> None:
    """既存テーブルを in-place 更新（コメント維持）、存在しなければ新規追加。

    標準ブロック記法 `[section]` およびインラインテーブル `section = {...}` の両方に対応。

    Issue #27 続編 G Phase 1: Path 値を str に変換してから書き込み (tomlkit 互換)。
    """
    data = _stringify_path_values(data)
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
    bbox = _stringify_path_values(asdict(pdf_merge.user_name_bbox))
    aliases = pdf_merge.facility_aliases
    pdf_merge_dict = asdict(pdf_merge)
    pdf_merge_dict.pop("user_name_bbox", None)
    pdf_merge_dict.pop("facility_aliases", None)
    # Issue #27 続編 G §4 (evaluator MEDIUM 対応): Phase 2 で本 dataclass の path
    # field を Path 化した際に ``asdict()`` が Path をそのまま tomlkit に渡して
    # silent fail する経路を防ぐ。現 Phase 1 では PdfMergeConfig に Path field なし
    # で no-op だが、防御的に境界変換を入れる。bbox も dpi 等が将来 Path 化される
    # 想定はないが対称性のため通す。
    pdf_merge_dict = _stringify_path_values(pdf_merge_dict)

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
    # Issue #27 続編 G §4 (evaluator MEDIUM 対応): Phase 2/3 で ReportStaffEntry や
    # ChecklistConfig の path field (base_dir / karte_root / fax_root 等) を Path 化
    # した際に ``asdict()`` 経由で Path が tomlkit に直渡しされる silent fail を防ぐ。
    # 現 Phase 1 では no-op (path field なし) だが、防御的に境界変換を通す。
    staff = {
        name: _stringify_path_values(asdict(entry))
        for name, entry in checklist.report_staff.items()
    }
    cache = dict(checklist.xlsx_path_cache)
    checklist_dict = _stringify_path_values(asdict(checklist))
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
