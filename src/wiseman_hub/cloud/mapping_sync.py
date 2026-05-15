"""居宅 → FAX 事業所フォルダ 対照表 / 担当者マッピングの GCS 双方向同期。

設定ダイアログから「GCP へ送信」「GCP から取得」ボタン経由で呼ばれる最小機能。

GCS 配置:
    gs://<bucket>/mappings/facility-routing-latest.json   # 居宅 → FAX フォルダ
    gs://<bucket>/mappings/report-staff-latest.json       # 担当者 → ReportStaffEntry (PR-β v1)

居宅マッピング JSON フォーマット:
    {
      "version": "1",
      "generated_at": "2026-05-01T12:34:56+09:00",
      "mappings": {"居宅名": "FAX フォルダ名", ...}
    }

担当者マッピング JSON フォーマット (PR-β v1):
    {
      "version": "1",
      "generated_at": "...",
      "staff": {
        "宮下": {
          "base_dir": "\\\\Tera-station\\share\\PT 宮下",
          "suggest_patterns": ["リハ経過報告書/令和{era}年/..."]
        },
        ...
      }
    }

PII 配慮:
    居宅名・FAX フォルダ名・担当者名・xlsx パスはログに出さない（件数のみ）。

過去失敗対策（feedback_external_api_ok_actual_ng.md）:
    push 後の閉ループ確認は呼び出し元（settings_dialog._on_push_routing 等）で実施。
    本モジュールは push / pull の単一責務に留める。
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
from typing import Any

from google.api_core import exceptions as gcs_exc
from google.auth import exceptions as auth_exc
from google.cloud import storage

from wiseman_hub.config import GcpConfig, ReportStaffEntry, coerce_path, is_path_configured

logger = logging.getLogger(__name__)


MAPPING_BLOB_PATH = "mappings/facility-routing-latest.json"
REPORT_STAFF_BLOB_PATH = "mappings/report-staff-latest.json"
SCHEMA_VERSION = "1"

# GCS 操作のソフトタイムアウト（秒）。ネットワーク不調で UI が無限フリーズするのを防ぐ。
_GCS_TIMEOUT_SEC = 30.0


class MappingSyncError(Exception):
    """対照表同期の失敗を表す統合例外。"""


class MappingNotFoundError(MappingSyncError):
    """GCS 上に対照表がまだ存在しない（初回利用時の典型ケース）。"""


class MappingConfigError(MappingSyncError):
    """GcpConfig の必須項目が欠落（呼び出し元での GCP 機能利用前検証用）。"""


def _validate_gcp(gcp: GcpConfig) -> None:
    """push/pull に必要な GcpConfig 設定の存在を事前検証する。

    過去失敗対策: bucket_name / project_id / service_account_key_path の
    空のまま GCS API を叩くと 4XX が返り、ユーザーに不親切なメッセージが出る。
    """
    missing: list[str] = []
    if not gcp.project_id.strip():
        missing.append("project_id")
    if not gcp.bucket_name.strip():
        missing.append("bucket_name")
    # Issue #27 続編 G §4: service_account_key_path は Path 型、is_sa_key_configured で空判定
    if not gcp.is_sa_key_configured:
        missing.append("service_account_key_path")
    if missing:
        raise MappingConfigError(
            "GCP 設定が未入力です: " + ", ".join(missing)
        )
    sa_path = gcp.service_account_key_path
    if not sa_path.exists():
        # 過去失敗対策（feedback_project_runtime_paths.md）:
        # 絶対パスをそのまま messagebox に出すとユーザー名が露出する。
        # ファイル名のみ表示し、フルパスはログには出さない。
        raise MappingConfigError(
            f"SA キーが見つかりません: {sa_path.name}"
        )


def push_routing(gcp: GcpConfig, routing: dict[str, str]) -> str:
    """対照表 dict を JSON 化して GCS にアップロードし、GCS URI を返す。

    Raises:
        MappingConfigError: GCP 設定不足
        MappingSyncError: 認証 / ネットワーク / 権限エラーを統合
    """
    _validate_gcp(gcp)
    now = _dt.datetime.now(_dt.UTC).astimezone()
    payload: dict[str, Any] = {
        "version": SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "mappings": dict(routing),
    }
    client = _client(gcp)  # MappingConfigError は上位で別ハンドリング
    try:
        bucket = client.bucket(gcp.bucket_name)
        blob = bucket.blob(MAPPING_BLOB_PATH)
        blob.upload_from_string(
            json.dumps(payload, ensure_ascii=False, indent=2),
            content_type="application/json; charset=utf-8",
            timeout=_GCS_TIMEOUT_SEC,
        )
    except (gcs_exc.GoogleAPIError, OSError) as exc:
        logger.error("mapping push failed: %s", type(exc).__name__)
        raise MappingSyncError(f"push failed: {type(exc).__name__}") from exc

    uri = f"gs://{gcp.bucket_name}/{MAPPING_BLOB_PATH}"
    logger.info("mapping push: %d entries -> %s", len(routing), uri)
    return uri


def pull_routing(gcp: GcpConfig) -> dict[str, str]:
    """GCS から最新対照表を取得して dict[str, str] で返す。

    Raises:
        MappingConfigError: GCP 設定不足
        MappingNotFoundError: blob 不在（初回利用時）
        MappingSyncError: 認証 / ネットワーク / 権限 / 不正 JSON エラーを統合
    """
    _validate_gcp(gcp)
    client = _client(gcp)  # MappingConfigError は上位で別ハンドリング
    try:
        bucket = client.bucket(gcp.bucket_name)
        blob = bucket.blob(MAPPING_BLOB_PATH)
        body = blob.download_as_bytes(timeout=_GCS_TIMEOUT_SEC)
    except gcs_exc.NotFound as exc:
        raise MappingNotFoundError(
            "対照表が GCS にまだ登録されていません"
        ) from exc
    except (gcs_exc.GoogleAPIError, OSError) as exc:
        logger.error("mapping pull failed: %s", type(exc).__name__)
        raise MappingSyncError(f"pull failed: {type(exc).__name__}") from exc

    try:
        payload: Any = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MappingSyncError(f"invalid JSON: {type(exc).__name__}") from exc

    if not isinstance(payload, dict):
        raise MappingSyncError("payload is not a JSON object")
    # 過去失敗対策（codex review MEDIUM-4）: 旧/別フォーマット混入を弾く
    version = payload.get("version")
    if version != SCHEMA_VERSION:
        raise MappingSyncError(
            f"unsupported schema version: {version!r} (expected {SCHEMA_VERSION!r})"
        )
    mappings = payload.get("mappings")
    if not isinstance(mappings, dict):
        raise MappingSyncError("payload.mappings is not an object")
    result: dict[str, str] = {}
    for k, v in mappings.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise MappingSyncError("mappings entry must be str -> str")
        result[k] = v
    logger.info("mapping pull: %d entries", len(result))
    return result


def push_report_staff(
    gcp: GcpConfig, staff: dict[str, ReportStaffEntry]
) -> str:
    """担当者マッピング dict を JSON 化して GCS にアップロードし、GCS URI を返す（PR-β v1）。

    Raises:
        MappingConfigError: GCP 設定不足
        MappingSyncError: 認証 / ネットワーク / 権限エラーを統合
    """
    _validate_gcp(gcp)
    now = _dt.datetime.now(_dt.UTC).astimezone()
    payload: dict[str, Any] = {
        "version": SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        # Issue #27 続編 G Phase 3b: entry.base_dir は Path 型に移行済。GCS JSON
        # contract は str 維持のため canonical sentinel pattern で str 変換 (未設定
        # Path("") は "" に正規化し、過去 JSON 形式との後方互換を保つ)。
        "staff": {
            name: {
                "base_dir": str(entry.base_dir) if is_path_configured(entry.base_dir) else "",
                "suggest_patterns": list(entry.suggest_patterns),
            }
            for name, entry in staff.items()
        },
    }
    client = _client(gcp)
    try:
        bucket = client.bucket(gcp.bucket_name)
        blob = bucket.blob(REPORT_STAFF_BLOB_PATH)
        blob.upload_from_string(
            json.dumps(payload, ensure_ascii=False, indent=2),
            content_type="application/json; charset=utf-8",
            timeout=_GCS_TIMEOUT_SEC,
        )
    except (gcs_exc.GoogleAPIError, OSError) as exc:
        logger.error("report_staff push failed: %s", type(exc).__name__)
        raise MappingSyncError(f"push failed: {type(exc).__name__}") from exc

    uri = f"gs://{gcp.bucket_name}/{REPORT_STAFF_BLOB_PATH}"
    logger.info("report_staff push: %d entries -> %s", len(staff), uri)
    return uri


def pull_report_staff(gcp: GcpConfig) -> dict[str, ReportStaffEntry]:
    """GCS から最新担当者マッピングを取得して dict[str, ReportStaffEntry] で返す（PR-β v1）。

    Raises:
        MappingConfigError: GCP 設定不足
        MappingNotFoundError: blob 不在（初回利用時）
        MappingSyncError: 認証 / ネットワーク / 権限 / 不正 JSON エラーを統合
    """
    _validate_gcp(gcp)
    client = _client(gcp)
    try:
        bucket = client.bucket(gcp.bucket_name)
        blob = bucket.blob(REPORT_STAFF_BLOB_PATH)
        body = blob.download_as_bytes(timeout=_GCS_TIMEOUT_SEC)
    except gcs_exc.NotFound as exc:
        raise MappingNotFoundError(
            "担当者マッピングが GCS にまだ登録されていません"
        ) from exc
    except (gcs_exc.GoogleAPIError, OSError) as exc:
        logger.error("report_staff pull failed: %s", type(exc).__name__)
        raise MappingSyncError(f"pull failed: {type(exc).__name__}") from exc

    try:
        payload: Any = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MappingSyncError(f"invalid JSON: {type(exc).__name__}") from exc

    if not isinstance(payload, dict):
        raise MappingSyncError("payload is not a JSON object")
    version = payload.get("version")
    if version != SCHEMA_VERSION:
        raise MappingSyncError(
            f"unsupported schema version: {version!r} (expected {SCHEMA_VERSION!r})"
        )
    staff_raw = payload.get("staff")
    if not isinstance(staff_raw, dict):
        raise MappingSyncError("payload.staff is not an object")
    result: dict[str, ReportStaffEntry] = {}
    for name, entry in staff_raw.items():
        if not isinstance(name, str):
            raise MappingSyncError("staff key must be str")
        if not isinstance(entry, dict):
            raise MappingSyncError(f"staff[{name}] must be an object")
        base_dir = entry.get("base_dir", "")
        if not isinstance(base_dir, str):
            raise MappingSyncError(f"staff[{name}].base_dir must be str")
        suggest_raw = entry.get("suggest_patterns", [])
        if not isinstance(suggest_raw, list):
            raise MappingSyncError(
                f"staff[{name}].suggest_patterns must be a list"
            )
        suggest_patterns: list[str] = []
        for element in suggest_raw:
            if not isinstance(element, str):
                raise MappingSyncError(
                    f"staff[{name}].suggest_patterns elements must be str"
                )
            suggest_patterns.append(element)
        # Issue #27 続編 G Phase 3b: JSON contract は str だが ReportStaffEntry は
        # Path 型必須化のため coerce_path 経由 (空白 strip → 未設定 sentinel)。
        result[name] = ReportStaffEntry(
            base_dir=coerce_path(
                f"report_staff_pull.{name}.base_dir",
                base_dir,
                echo_value=False,
            ),
            suggest_patterns=suggest_patterns,
        )
    logger.info("report_staff pull: %d entries", len(result))
    return result


def _client(gcp: GcpConfig) -> storage.Client:
    """SA キー JSON を読んで storage.Client を構築する。

    過去失敗対策（codex review HIGH-1）:
        ``from_service_account_json`` は SA キー JSON が壊れている / 形式違い /
        private_key 不正の際に ``ValueError`` や ``GoogleAuthError`` を投げる。
        現状の上位 except 句では捕捉されず実機 crash の原因となるため、
        本関数で ``MappingConfigError``（設定不足カテゴリ）に変換する。
    """
    try:
        # Issue #27 続編 G §4: service_account_key_path は Path 型、google-cloud-storage は str 要求
        return storage.Client.from_service_account_json(
            str(gcp.service_account_key_path), project=gcp.project_id
        )
    except (ValueError, OSError, auth_exc.GoogleAuthError) as exc:
        raise MappingConfigError(
            f"SA キーを読み込めません: {type(exc).__name__}"
        ) from exc
