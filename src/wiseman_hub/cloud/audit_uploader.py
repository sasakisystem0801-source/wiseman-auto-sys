"""audit log の GCS upload（ADR-016 Phase 2）。

local の append-only audit JSONL を spool として扱い、各 record を **per-record
object** で GCS にアップロードする。content hash ベースの object 名により、
リトライによる重複 upload は同名 object として収束し冪等。upload 済 record は
sidecar `.uploaded` ファイルにハッシュを追記して追跡し、次回 scan ではスキップ。

ローカル spool 配置（既存 audit.py と整合）:
    {log_dir}/audit/{kind}_{YYYY-MM-DD}.jsonl       # 既存 append-only ログ
    {log_dir}/audit/{kind}_{YYYY-MM-DD}.uploaded    # 新規 sidecar (1 行 1 hash)

GCS object パス:
    gs://{data_bucket}/audit/{kind}/{YYYY-MM-DD}/{sha256[:32]}.json

ADR-016 Critical C-1 (bucket 分離) / Nice-to-have 1 (spool + retry) 対応。

設計判断:
    - **per-record object**: GCS は append できないため、record 単位で別 object 化
    - **content hash 名**: SHA-256 の先頭 32 hex を file 名にし、同一 record が
      何度 upload されても同名 object として収束 (objectCreator で 412 → 治癒扱い)
    - **sidecar marker**: jsonl 自体は touch しない（audit.py の append 排他に干渉
      しない）。並行 append + 並行 upload を許容
    - **scan 単位の最小粒度**: 1 file = 1 process_jsonl()。失敗しても次 file は処理
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any

from google.api_core import exceptions as gcs_exc
from google.cloud import storage

from wiseman_hub.config import GcpConfig

logger = logging.getLogger(__name__)

_AUDIT_SUBDIR = "audit"
_UPLOADED_SUFFIX = ".uploaded"
_GCS_TIMEOUT_SEC = 30
_DEFAULT_INTERVAL_SEC = 300  # 5 分

# audit jsonl ファイル名: {kind}_{YYYY-MM-DD}.jsonl
_JSONL_NAME_RE = re.compile(r"^(?P<kind>[a-z0-9_]+)_(?P<date>\d{4}-\d{2}-\d{2})\.jsonl$")


class AuditUploadConfigError(Exception):
    """GCP 設定不足など、upload 開始前に弾く設定不備。"""


class AuditUploadError(Exception):
    """GCS API エラー / ネットワーク / 認証エラーを統合。"""


def _validate_gcp(gcp: GcpConfig) -> None:
    """GcpConfig の必須項目を検証する（過去失敗対策、mapping_sync.py と同パターン）。"""
    missing: list[str] = []
    if not gcp.project_id.strip():
        missing.append("project_id")
    if not gcp.effective_data_bucket.strip():
        missing.append("data_bucket_name (or bucket_name)")
    if not gcp.service_account_key_path.strip():
        missing.append("service_account_key_path")
    if missing:
        raise AuditUploadConfigError(
            f"GCP config missing required fields: {', '.join(missing)}"
        )
    sa_path = Path(gcp.service_account_key_path)
    if not sa_path.exists():
        raise AuditUploadConfigError(
            f"service_account_key_path not found: {sa_path}"
        )


def _client(gcp: GcpConfig) -> storage.Client:
    """GCS client factory（テストでは patch される）。"""
    return storage.Client.from_service_account_json(
        gcp.service_account_key_path, project=gcp.project_id
    )


def _content_hash(record_line: str) -> str:
    """record JSONL 1 行から SHA-256 hex を計算（先頭 32 文字を返す）。

    完全な hash 衝突は天文学的確率なので 32 hex (128 bit) で実用上十分。
    object 名長を抑えて GCS 経由のリスト負荷を軽減する。
    """
    return hashlib.sha256(record_line.encode("utf-8")).hexdigest()[:32]


def _read_uploaded_hashes(marker: Path) -> set[str]:
    """sidecar `.uploaded` ファイルから upload 済 hash 集合を読む。"""
    if not marker.exists():
        return set()
    try:
        return {
            line.strip()
            for line in marker.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
    except OSError as exc:
        logger.warning("uploaded marker read failed: %s (%s)", marker.name, type(exc).__name__)
        return set()


def _append_uploaded_hash(marker: Path, content_hash: str) -> None:
    """sidecar `.uploaded` に 1 hash を追記。"""
    try:
        with open(marker, "a", encoding="utf-8") as f:
            f.write(content_hash + "\n")
    except OSError as exc:
        logger.warning(
            "uploaded marker append failed: %s (%s)",
            marker.name,
            type(exc).__name__,
        )


def _gcs_object_name(kind: str, date_str: str, content_hash: str) -> str:
    """GCS object path を組み立てる。"""
    return f"audit/{kind}/{date_str}/{content_hash}.json"


def _upload_one(
    bucket: Any,
    object_name: str,
    record_line: str,
) -> bool:
    """単一 record を GCS に upload する。

    Returns:
        True = 新規 upload 成功、False = すでに存在（412 PreconditionFailed として治癒扱い）

    Raises:
        AuditUploadError: その他のネットワーク / 権限エラー
    """
    blob = bucket.blob(object_name)
    try:
        # if_generation_match=0 は「object が存在しない場合のみ create」を意味する
        # （objectCreator + condition 環境では 412 で同名 object 上書きを拒否）。
        # 既存 object を「治癒」扱いにすることで idempotent retry を実現。
        blob.upload_from_string(
            record_line.rstrip("\n"),
            content_type="application/json; charset=utf-8",
            timeout=_GCS_TIMEOUT_SEC,
            if_generation_match=0,
        )
        return True
    except gcs_exc.PreconditionFailed:
        # 既存 object と同名 → 既に upload 済 → 成功扱い
        return False
    except (gcs_exc.GoogleAPIError, OSError) as exc:
        raise AuditUploadError(f"upload failed: {type(exc).__name__}") from exc


def process_jsonl(
    jsonl_path: Path,
    gcp: GcpConfig,
    *,
    client: storage.Client | None = None,
) -> tuple[int, int, int]:
    """1 つの audit jsonl を upload 対象 record に分解し GCS にアップロード。

    Args:
        jsonl_path: 対象の audit jsonl ファイル。
        gcp: GCP 接続設定。
        client: テスト時の mock クライアント。未指定なら ``_client(gcp)``。

    Returns:
        (uploaded, skipped, errors) のタプル。
        - uploaded: 新規 GCS upload 成功した record 数
        - skipped: 既に upload 済（sidecar 存在 or 412）でスキップした数
        - errors: ネットワーク等で失敗した数（次回 scan で retry）
    """
    m = _JSONL_NAME_RE.match(jsonl_path.name)
    if not m:
        logger.warning("audit jsonl filename does not match pattern: %s", jsonl_path.name)
        return (0, 0, 0)
    kind = m.group("kind")
    date_str = m.group("date")
    marker = jsonl_path.with_suffix(".uploaded")
    uploaded_hashes = _read_uploaded_hashes(marker)

    cli = client or _client(gcp)
    bucket = cli.bucket(gcp.effective_data_bucket)

    uploaded = skipped = errors = 0
    try:
        lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        logger.warning(
            "audit jsonl read failed: %s (%s)",
            jsonl_path.name,
            type(exc).__name__,
        )
        return (0, 0, 0)

    for line in lines:
        line = line.strip()
        if not line:
            continue
        h = _content_hash(line)
        if h in uploaded_hashes:
            skipped += 1
            continue
        object_name = _gcs_object_name(kind, date_str, h)
        try:
            is_new = _upload_one(bucket, object_name, line)
        except AuditUploadError as exc:
            logger.warning(
                "audit upload error (%s/%s): %s",
                kind,
                date_str,
                exc,
            )
            errors += 1
            # ネットワーク系 error は break して次 scan で retry
            # （途中まで sidecar 更新するのは OK）
            break
        if is_new:
            uploaded += 1
        else:
            skipped += 1
        _append_uploaded_hash(marker, h)

    return (uploaded, skipped, errors)


def scan_and_upload(
    log_dir: str,
    gcp: GcpConfig,
    *,
    client: storage.Client | None = None,
) -> dict[str, int]:
    """log_dir/audit/ 配下の全 jsonl を scan して GCS にアップロード。

    Args:
        log_dir: AppConfig.log_dir。空文字なら no-op。
        gcp: GCP 接続設定。
        client: テスト用 mock。

    Returns:
        集計 dict: ``{"files": N, "uploaded": M, "skipped": K, "errors": E}``
    """
    if not log_dir:
        return {"files": 0, "uploaded": 0, "skipped": 0, "errors": 0}
    audit_dir = Path(log_dir) / _AUDIT_SUBDIR
    if not audit_dir.exists():
        return {"files": 0, "uploaded": 0, "skipped": 0, "errors": 0}

    _validate_gcp(gcp)
    cli = client or _client(gcp)

    total_uploaded = total_skipped = total_errors = 0
    files = sorted(audit_dir.glob("*.jsonl"))
    for jsonl in files:
        uploaded, skipped, errors = process_jsonl(jsonl, gcp, client=cli)
        total_uploaded += uploaded
        total_skipped += skipped
        total_errors += errors

    if total_uploaded or total_errors:
        logger.info(
            "audit upload: %d files, %d uploaded, %d skipped, %d errors",
            len(files),
            total_uploaded,
            total_skipped,
            total_errors,
        )
    return {
        "files": len(files),
        "uploaded": total_uploaded,
        "skipped": total_skipped,
        "errors": total_errors,
    }


def start_audit_uploader(
    log_dir: str,
    gcp: GcpConfig,
    *,
    interval_sec: int = _DEFAULT_INTERVAL_SEC,
) -> threading.Thread | None:
    """audit upload を起動時 + 定期実行する daemon thread を起動。

    起動条件:
        - ``log_dir`` が設定されていること
        - ``gcp.effective_data_bucket`` が設定されていること
        - ``gcp.service_account_key_path`` のファイルが存在すること

    上記いずれかが満たされない場合は warning を出して thread を起動せず ``None`` を返す
    （audit ローカル書込は継続、GCS upload のみ無効）。

    Args:
        log_dir: AppConfig.log_dir。
        gcp: GCP 接続設定。
        interval_sec: scan 間隔（秒）。本番は 300 (5 分)、テストは短く設定可。

    Returns:
        起動した daemon thread。起動条件未達なら ``None``。
    """
    try:
        _validate_gcp(gcp)
    except AuditUploadConfigError as exc:
        logger.warning("audit uploader disabled: %s", exc)
        return None
    if not log_dir:
        logger.warning("audit uploader disabled: log_dir not set")
        return None

    def _loop() -> None:
        while True:
            try:
                scan_and_upload(log_dir, gcp)
            except AuditUploadConfigError as exc:
                logger.warning("audit uploader config error: %s", exc)
            except Exception:  # noqa: BLE001  (daemon thread, never let it die)
                logger.exception("audit uploader run failed")
            time.sleep(interval_sec)

    t = threading.Thread(target=_loop, name="audit_uploader", daemon=True)
    t.start()
    logger.info(
        "audit uploader started: log_dir=%s, bucket=%s, interval=%ds",
        log_dir,
        gcp.effective_data_bucket,
        interval_sec,
    )
    return t
