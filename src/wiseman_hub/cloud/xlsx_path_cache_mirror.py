"""xlsx_path_cache の GCS ミラー（ADR-016 Phase 3 PR-2）。

業務責任者 PC で確定した ``xlsx_path_cache``（``checklist.xlsx_path_cache``）の
TOML 内容を、key 単位で GCS にミラーする。目的:

    1. PC 入替・config 巻き戻し時の cache 復旧
    2. Mac dev 機からの cache 状態 read-only 確認

GCS object 配置:
    gs://{data_bucket}/cache/xlsx_path/{sha256(key)[:32]}.json

object schema (alive entry):
    {
        "key": "宮下:2026:3",
        "xlsx_path": "\\\\Tera-station\\share\\PT 宮下\\...",
        "generated_at": "2026-05-06T05:23:11.123456+00:00",
        "machine_id": "<UUIDv4>",
        "config_revision": "<generated_at>:<base_config_sha256[:12]>",
        "base_config_sha256": "<64 hex>"
    }

object schema (tombstone, 削除時):
    {
        "key": "宮下:2026:3",
        "deleted_at": "2026-05-06T05:30:00+00:00",
        "machine_id": "...",
        "config_revision": "...",
        "base_config_sha256": "..."
    }
    ※ ``xlsx_path`` フィールドが**欠如**することで tombstone 判別する
      （明示的な ``deleted: true`` フラグより schema 上の対称性が高い）。

設計判断:
    - **per-key per-object**: object name に key の hash を使うことで latest-state を
      mirror。key を path に直接含めると PII （担当者名）が GCS object 名に出るため
      hash 化（audit_uploader.py の content hash と同じ手口）
    - **mutable overwrite (no if_generation_match)**: cache の最新状態を mirror する
      用途のため、ローカルの確定値を覆い得る挙動が必要。冪等 retry も同名 object
      への上書きで自然収束
    - **tombstone**: GCS の「object 削除」ではなく「``deleted_at`` 付き JSON で上書き」
      にすることで、過去履歴（generation 経由）と削除事実を両立。Bucket lifecycle
      で後から物理削除可能
    - **machine_id**: hostname/HW ID の代わりに UUIDv4 を ``~/wiseman-hub/machine_id``
      に永続化（PII 配慮、ADR-016 PII 5 年保持と整合）
    - **base_config_sha256**: save_config 後の TOML bytes 全体の hash。これにより
      「どの config 状態で書かれた entry か」を識別でき、巻き戻し時の差分検出が可能

並列 upload の race:
    本モジュールは per-key per-object のため、異なる key は完全独立。同一 key への
    並列 upload は GCS の last-writer-wins で自然解決（content hash 一致なら
    冪等、不一致なら新しい方が残る）。プロセス内競合は呼出側（UI）が逐次的に
    呼ぶため発生しない。
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import logging
import uuid
from pathlib import Path

from google.api_core import exceptions as gcs_exc
from google.cloud import storage

from wiseman_hub.config import GcpConfig

logger = logging.getLogger(__name__)

_OBJECT_PREFIX = "cache/xlsx_path"
_GCS_TIMEOUT_SEC = 30
_MACHINE_ID_PATH = Path.home() / "wiseman-hub" / "machine_id"


class XlsxPathCacheMirrorError(Exception):
    """GCS API / ネットワーク / 認証エラーを統合（呼出側は warn-only で扱う）。"""


def _validate_gcp(gcp: GcpConfig) -> list[str]:
    """GcpConfig の必須項目を検証して missing field 名のリストを返す。

    audit_uploader._validate_gcp と異なり、本モジュールは「失敗しても warn-only」
    の運用のため、raise せず list を返す。呼出側が空 list なら proceed する。
    """
    missing: list[str] = []
    if not gcp.project_id.strip():
        missing.append("project_id")
    if not gcp.effective_data_bucket.strip():
        missing.append("data_bucket_name (or bucket_name)")
    if not gcp.service_account_key_path.strip():
        missing.append("service_account_key_path")
    if not missing:
        sa_path = Path(gcp.service_account_key_path)
        if not sa_path.exists():
            missing.append("service_account_key_path (file not found)")
    return missing


def _client(gcp: GcpConfig) -> storage.Client:
    """GCS client factory（テストでは patch される）。"""
    return storage.Client.from_service_account_json(
        gcp.service_account_key_path, project=gcp.project_id
    )


def get_or_create_machine_id() -> str:
    """``~/wiseman-hub/machine_id`` から machine_id を読み出し、なければ UUIDv4 を生成。

    冪等: 同一 PC で複数回呼ばれても同じ ID が返る（再起動間で安定）。
    読み取り失敗時は ephemeral UUID を返し、warn ログを残す（運用継続優先）。

    PII 配慮:
        hostname / MAC アドレス / Windows machine GUID は使わず、必ず UUIDv4 を
        新規生成する（ADR-016 PII 5 年保持と整合）。
    """
    try:
        if _MACHINE_ID_PATH.exists():
            content = _MACHINE_ID_PATH.read_text(encoding="utf-8").strip()
            if content:
                return content
        # 新規生成 + 永続化
        new_id = str(uuid.uuid4())
        _MACHINE_ID_PATH.parent.mkdir(parents=True, exist_ok=True)
        _MACHINE_ID_PATH.write_text(new_id + "\n", encoding="utf-8")
        return new_id
    except OSError as exc:
        # 書き込み失敗 → ephemeral UUID を返す（次回起動時に再試行）
        logger.warning(
            "machine_id read/write failed (errno=%s, type=%s); using ephemeral UUID",
            getattr(exc, "errno", "n/a"),
            type(exc).__name__,
        )
        return str(uuid.uuid4())


def compute_base_config_sha256(config_path: Path) -> str:
    """``config_path`` の bytes 全体の SHA-256 hex（64 文字）を計算する。

    決定性:
        同一 file bytes に対して常に同じ hash を返す。改行コードや空白の違いも
        bytes 比較で反映される（TOML の論理同一は反映しない）。

    エラー時は空文字列を返す（呼出側で空判定可能）。
    """
    try:
        data = config_path.read_bytes()
    except OSError as exc:
        logger.warning(
            "config bytes read failed for sha256: %s (errno=%s, type=%s)",
            config_path.name,
            getattr(exc, "errno", "n/a"),
            type(exc).__name__,
        )
        return ""
    return hashlib.sha256(data).hexdigest()


def make_config_revision(generated_at: str, base_sha: str) -> str:
    """``{generated_at}:{base_config_sha256[:12]}`` の形式で revision 文字列を構築。

    base_sha が空文字列の場合は ``{generated_at}:`` で終端する（hash 失敗時の
    識別子として generated_at が機能、巻き戻し検出は劣化）。
    """
    return f"{generated_at}:{base_sha[:12]}"


def object_name_for(key: str) -> str:
    """key（``staff:year:month``）から GCS object 名を導出する。

    PII 配慮で key の生値は object 名に含めない（SHA-256 先頭 32 hex のみ）。
    32 hex = 128 bit で実用上衝突なし（audit_uploader と同じ方針）。
    """
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
    return f"{_OBJECT_PREFIX}/{digest}.json"


def _now_utc_iso() -> str:
    """UTC ISO8601 文字列（``+00:00`` 表記、microsecond 含む）を返す。"""
    return _dt.datetime.now(tz=_dt.UTC).isoformat()


def _build_alive_payload(
    key: str,
    xlsx_path: str,
    config_path: Path,
) -> dict[str, str]:
    """alive entry の payload dict を組み立てる。"""
    generated_at = _now_utc_iso()
    base_sha = compute_base_config_sha256(config_path)
    return {
        "key": key,
        "xlsx_path": xlsx_path,
        "generated_at": generated_at,
        "machine_id": get_or_create_machine_id(),
        "config_revision": make_config_revision(generated_at, base_sha),
        "base_config_sha256": base_sha,
    }


def _build_tombstone_payload(key: str, config_path: Path) -> dict[str, str]:
    """tombstone payload を組み立てる（``xlsx_path`` 欠如で削除判別）。"""
    deleted_at = _now_utc_iso()
    base_sha = compute_base_config_sha256(config_path)
    return {
        "key": key,
        "deleted_at": deleted_at,
        "machine_id": get_or_create_machine_id(),
        "config_revision": make_config_revision(deleted_at, base_sha),
        "base_config_sha256": base_sha,
    }


def _upload_payload(
    gcp: GcpConfig,
    key: str,
    payload: dict[str, str],
    *,
    client: storage.Client | None,
) -> bool:
    """payload を GCS にアップロード（mutable overwrite）。

    Returns:
        True = upload 成功、False = GCP 設定不足 / API エラー（warn-only）
    """
    missing = _validate_gcp(gcp)
    if missing:
        logger.warning(
            "xlsx_path_cache mirror skipped (gcp config missing): %s",
            ", ".join(missing),
        )
        return False

    obj_name = object_name_for(key)
    try:
        cli = client or _client(gcp)
        bucket = cli.bucket(gcp.effective_data_bucket)
        blob = bucket.blob(obj_name)
        # mutable overwrite (no if_generation_match)
        # 設計理由: latest-state mirror のため、ローカル確定値で常に上書きする。
        # 並列 upload race は GCS の last-writer-wins で自然解決。
        body = json.dumps(payload, ensure_ascii=False, indent=2)
        blob.upload_from_string(
            body,
            content_type="application/json; charset=utf-8",
            timeout=_GCS_TIMEOUT_SEC,
        )
        return True
    except (gcs_exc.GoogleAPIError, OSError) as exc:
        logger.warning(
            "xlsx_path_cache mirror upload failed: object=%s, type=%s",
            obj_name,
            type(exc).__name__,
        )
        return False


def upload_entry(
    key: str,
    xlsx_path: str,
    gcp: GcpConfig,
    *,
    config_path: Path,
    client: storage.Client | None = None,
) -> bool:
    """alive entry を GCS にミラー。

    Args:
        key: ``"{staff}:{year}:{month}"`` 形式（cache_key()）
        xlsx_path: 確定済の xlsx 絶対パス（UNC 等）
        gcp: GCP 接続設定。未設定（bucket 等空）なら no-op で warn ログのみ
        config_path: save_config() 直後の TOML パス（base_config_sha256 計算用）
        client: テスト用 mock client

    Returns:
        True = upload 成功、False = 設定不足 / API エラー
    """
    payload = _build_alive_payload(key, xlsx_path, config_path)
    return _upload_payload(gcp, key, payload, client=client)


def delete_entry(
    key: str,
    gcp: GcpConfig,
    *,
    config_path: Path,
    client: storage.Client | None = None,
) -> bool:
    """tombstone を GCS にミラー（``xlsx_path`` 欠如、``deleted_at`` 付き）。

    GCS object 自体は削除せず、tombstone JSON で上書きする。これにより:
        - 過去 generation 経由で履歴参照可能
        - bucket lifecycle で N 日後に物理削除する運用が可能
        - Mac CLI の ``--include-deleted`` で監査可能

    Returns:
        True = upload 成功、False = 設定不足 / API エラー
    """
    payload = _build_tombstone_payload(key, config_path)
    return _upload_payload(gcp, key, payload, client=client)


def fetch_one(
    key: str,
    gcp: GcpConfig,
    *,
    client: storage.Client | None = None,
) -> dict[str, str] | None:
    """単一 key の entry を GCS から取得。

    Returns:
        存在 + JSON parse 成功なら dict（alive / tombstone どちらも）。
        存在しない / GCP 設定不足 / API エラーなら None。

    呼出側は ``"xlsx_path"`` キーの有無で alive / tombstone を判別する。
    """
    missing = _validate_gcp(gcp)
    if missing:
        logger.warning(
            "xlsx_path_cache fetch skipped (gcp config missing): %s",
            ", ".join(missing),
        )
        return None
    obj_name = object_name_for(key)
    try:
        cli = client or _client(gcp)
        bucket = cli.bucket(gcp.effective_data_bucket)
        blob = bucket.blob(obj_name)
        if not blob.exists(timeout=_GCS_TIMEOUT_SEC):
            return None
        data = blob.download_as_bytes(timeout=_GCS_TIMEOUT_SEC)
    except (gcs_exc.GoogleAPIError, OSError) as exc:
        logger.warning(
            "xlsx_path_cache fetch_one failed: object=%s, type=%s",
            obj_name,
            type(exc).__name__,
        )
        return None
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        logger.warning(
            "xlsx_path_cache fetch_one parse failed: object=%s, type=%s",
            obj_name,
            type(exc).__name__,
        )
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def fetch_all(
    gcp: GcpConfig,
    *,
    client: storage.Client | None = None,
) -> list[dict[str, str]]:
    """``cache/xlsx_path/`` 配下の全 entry を取得（alive + tombstone）。

    Returns:
        各 entry の dict（パース成功分のみ）。alive / tombstone は呼出側で
        ``"xlsx_path"`` キーの有無で判別する。GCP 設定不足 / API エラー時は空 list。

    並列 upload の race:
        本関数は read-only で副作用なし。list_blobs と download の間に
        別 PC が upload しても snapshot として取得される（古い generation を
        読む可能性はあるが、Mac CLI 用途では許容）。
    """
    missing = _validate_gcp(gcp)
    if missing:
        logger.warning(
            "xlsx_path_cache fetch_all skipped (gcp config missing): %s",
            ", ".join(missing),
        )
        return []
    results: list[dict[str, str]] = []
    try:
        cli = client or _client(gcp)
        bucket = cli.bucket(gcp.effective_data_bucket)
        # prefix 指定で `cache/xlsx_path/` 配下のみ
        for blob in cli.list_blobs(
            bucket, prefix=_OBJECT_PREFIX + "/", timeout=_GCS_TIMEOUT_SEC
        ):
            try:
                data = blob.download_as_bytes(timeout=_GCS_TIMEOUT_SEC)
            except (gcs_exc.GoogleAPIError, OSError) as exc:
                logger.warning(
                    "xlsx_path_cache fetch_all blob download failed: name=%s, type=%s",
                    getattr(blob, "name", "?"),
                    type(exc).__name__,
                )
                continue
            try:
                parsed = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                logger.warning(
                    "xlsx_path_cache fetch_all parse failed: name=%s, type=%s",
                    getattr(blob, "name", "?"),
                    type(exc).__name__,
                )
                continue
            if isinstance(parsed, dict):
                results.append(parsed)
    except (gcs_exc.GoogleAPIError, OSError) as exc:
        logger.warning(
            "xlsx_path_cache fetch_all list_blobs failed: type=%s",
            type(exc).__name__,
        )
        return results  # 部分結果を返す（list 中断時の partial を許容）
    return results
