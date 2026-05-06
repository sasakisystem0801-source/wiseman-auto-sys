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


def _normalize_line(raw: str) -> str:
    """audit jsonl の 1 行を正規化する。

    hash 計算と upload 内容の **両方でこの関数を必ず通す**ことで、二重正規化や
    片側だけの変更による silent regression を防ぐ（review C-1 対策）。

    正規化:
        - splitlines() で \\n / \\r\\n は除去済の前提だが、防衛的に strip()
        - BOM (U+FEFF) を除去（Windows メモ帳経由の編集対策）
    """
    return raw.strip().lstrip("﻿")


def _content_hash(record_line: str) -> str:
    """正規化済み record 1 行から SHA-256 hex を計算（先頭 32 文字を返す）。

    呼び出し元は ``_normalize_line`` を先に通すこと（hash 一貫性のため）。
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
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning(
            "uploaded marker read failed: %s (errno=%s, type=%s)",
            marker.name,
            getattr(exc, "errno", "n/a"),
            type(exc).__name__,
        )
        return set()


# sidecar `.uploaded` ファイルの並行 append 排他（review S-1 対策、設計の一貫性のため）
# 現状は単一 daemon thread のみが触るが、将来の多重起動に備えて Lock を明示。
_MARKER_LOCK = threading.Lock()


def _append_uploaded_hash(marker: Path, content_hash: str) -> bool:
    """sidecar `.uploaded` に 1 hash を追記。

    Returns:
        True = 追記成功、False = OSError で失敗（呼び出し元で retry storm 防止判断）
    """
    with _MARKER_LOCK:
        try:
            with open(marker, "a", encoding="utf-8") as f:
                f.write(content_hash + "\n")
            return True
        except OSError as exc:
            logger.warning(
                "uploaded marker append failed: %s (errno=%s, type=%s)",
                marker.name,
                getattr(exc, "errno", "n/a"),
                type(exc).__name__,
            )
            return False


def _gcs_object_name(kind: str, date_str: str, content_hash: str) -> str:
    """GCS object path を組み立てる。"""
    return f"audit/{kind}/{date_str}/{content_hash}.json"


def _upload_one(
    bucket: Any,
    object_name: str,
    record_line: str,
) -> bool:
    """単一 record を GCS に upload する。

    呼び出し元の責任で ``record_line`` は ``_normalize_line`` 済であること。
    本関数では追加正規化はしない（review C-1 対策、二重正規化禁止）。

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
            record_line,
            content_type="application/json; charset=utf-8",
            timeout=_GCS_TIMEOUT_SEC,
            if_generation_match=0,
        )
        return True
    except gcs_exc.PreconditionFailed:
        # 既存 object と同名 = 既に upload 済 → 成功扱い (idempotent retry)。
        # review C-2 対策: bucket 取り違え / hash collision を運用者が検出できるよう
        # warning ログを残す（content metadata 比較は将来 PR で追加検討）。
        logger.warning(
            "audit upload 412 PreconditionFailed (treated as already-uploaded): "
            "object=%s, size=%d bytes",
            object_name,
            len(record_line.encode("utf-8")),
        )
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
        raw_text = jsonl_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        # review I-3: UnicodeDecodeError も catch して当該 file を skip。
        # 1 file の不正 byte で他 file の処理を止めない。
        logger.warning(
            "audit jsonl read failed: %s (errno=%s, type=%s)",
            jsonl_path.name,
            getattr(exc, "errno", "n/a"),
            type(exc).__name__,
        )
        return (0, 0, 0)

    # review C-1 (partial line risk) 対策:
    # audit.py が append 中に process_jsonl が読むと、最終行が \n で終わって
    # いない partial line である可能性がある。末尾 \n が無ければ最終行を
    # 切り捨てて次回 scan に持ち越す（次回読込時には \n 完了してるはず）。
    if raw_text and not raw_text.endswith("\n"):
        # 末尾 \n が無い = まだ append 中 → 最終行を除外
        idx = raw_text.rfind("\n")
        if idx >= 0:
            raw_text = raw_text[: idx + 1]
        else:
            # 1 行のみで未完成 → 全 skip
            return (0, 0, 0)
    lines = raw_text.splitlines()

    for raw in lines:
        # review C-1: hash 計算と upload 内容の一貫性のため _normalize_line を経由
        line = _normalize_line(raw)
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
            # （途中まで sidecar 更新するのは OK、412 治癒で収束）
            break
        if is_new:
            uploaded += 1
        else:
            skipped += 1
        # review I-1 (sidecar OSError 永久 retry storm) 対策:
        # sidecar 書込失敗時は当該 file の処理を中止して次 scan に委ねる
        # （ただし次 scan でも同じ問題なら毎回 errors が増える、運用者が気づける）。
        if not _append_uploaded_hash(marker, h):
            errors += 1
            logger.warning(
                "sidecar write failed for %s, aborting file to avoid retry storm",
                marker.name,
            )
            break

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

    # review I-2 (early validation) 対策: audit dir 不存在でも GCP 設定不備は
    # fail-fast で検出する。dir 不存在の早期 return より前に validate を呼ぶ。
    _validate_gcp(gcp)

    audit_dir = Path(log_dir) / _AUDIT_SUBDIR
    if not audit_dir.exists():
        return {"files": 0, "uploaded": 0, "skipped": 0, "errors": 0}

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


# review C-3 (clean shutdown) 対策: daemon thread を割り込み可能にする。
# Event.wait は timeout 付きで割り込めるので time.sleep より優先。
# module-level のため複数 launcher 起動時は最後の Event が共有される（現状は
# launcher 単一起動前提なので問題なし）。
_shutdown_event = threading.Event()


def stop_audit_uploader() -> None:
    """audit uploader daemon thread に shutdown signal を送る。

    launcher 終了時 (Tk WM_DELETE_WINDOW callback 等) から呼び出すことで、
    5 分 sleep を中断して即座に最終 flush + thread 終了させる。
    """
    _shutdown_event.set()


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

    shutdown 経路:
        - 通常: ``stop_audit_uploader()`` 呼び出しで Event がセットされ、
          現在の sleep を中断して最終 flush 後 thread 終了
        - 強制: daemon=True なので main thread 終了で道連れに殺される
          （sleep 中の場合は最大 ``interval_sec`` 秒待ってから死亡）

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

    # 多重 start_audit_uploader 防止 + 前回 stop_audit_uploader の Event を reset
    _shutdown_event.clear()

    def _loop() -> None:
        while not _shutdown_event.is_set():
            try:
                scan_and_upload(log_dir, gcp)
            except AuditUploadConfigError as exc:
                logger.warning("audit uploader config error: %s", exc)
            except Exception:  # noqa: BLE001  (daemon thread, never let it die)
                logger.exception("audit uploader run failed")
            # Event.wait(timeout) は割り込み可能 sleep。
            # True 返却 = stop signaled → 即座に loop 抜けて最終 flush へ。
            if _shutdown_event.wait(timeout=interval_sec):
                break
        # 終了前に最後 1 回 flush（5 分間隔の最後の record を取りこぼさない）
        try:
            scan_and_upload(log_dir, gcp)
            logger.info("audit uploader: final flush completed")
        except Exception:  # noqa: BLE001
            logger.exception("audit uploader: final flush failed")

    t = threading.Thread(target=_loop, name="audit_uploader", daemon=True)
    t.start()
    logger.info(
        "audit uploader started: log_dir=%s, bucket=%s, interval=%ds",
        log_dir,
        gcp.effective_data_bucket,
        interval_sec,
    )
    return t
