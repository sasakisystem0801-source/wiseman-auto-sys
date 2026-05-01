"""居宅 → FAX 事業所フォルダ 対照表の GCS 双方向同期。

設定ダイアログから「GCP へ送信」「GCP から取得」ボタン経由で呼ばれる最小機能。

GCS 配置:
    gs://<bucket>/mappings/facility-routing-latest.json

JSON フォーマット:
    {
      "version": "1",
      "generated_at": "2026-05-01T12:34:56+09:00",
      "mappings": {"居宅名": "FAX フォルダ名", ...}
    }

PII 配慮:
    居宅名・FAX フォルダ名はログに出さない（件数のみ）。

過去失敗対策（feedback_external_api_ok_actual_ng.md）:
    push 後の閉ループ確認は呼び出し元（settings_dialog._on_push_routing）で実施。
    本モジュールは push / pull の単一責務に留める。
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
from pathlib import Path
from typing import Any

from google.api_core import exceptions as gcs_exc
from google.auth import exceptions as auth_exc
from google.cloud import storage

from wiseman_hub.config import GcpConfig

logger = logging.getLogger(__name__)


MAPPING_BLOB_PATH = "mappings/facility-routing-latest.json"
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
    if not gcp.service_account_key_path.strip():
        missing.append("service_account_key_path")
    if missing:
        raise MappingConfigError(
            "GCP 設定が未入力です: " + ", ".join(missing)
        )
    sa_path = Path(gcp.service_account_key_path)
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


def _client(gcp: GcpConfig) -> storage.Client:
    """SA キー JSON を読んで storage.Client を構築する。

    過去失敗対策（codex review HIGH-1）:
        ``from_service_account_json`` は SA キー JSON が壊れている / 形式違い /
        private_key 不正の際に ``ValueError`` や ``GoogleAuthError`` を投げる。
        現状の上位 except 句では捕捉されず実機 crash の原因となるため、
        本関数で ``MappingConfigError``（設定不足カテゴリ）に変換する。
    """
    try:
        return storage.Client.from_service_account_json(
            gcp.service_account_key_path, project=gcp.project_id
        )
    except (ValueError, OSError, auth_exc.GoogleAuthError) as exc:
        raise MappingConfigError(
            f"SA キーを読み込めません: {type(exc).__name__}"
        ) from exc
