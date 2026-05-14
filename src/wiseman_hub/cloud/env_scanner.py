"""ローカル環境スキャン → GCS アップロード（MVP）。

目的:
    AI による居宅マッピング自動生成のため、Windows 実機の `\\Tera-station\\
    share\\03.FAX(事業所)` 配下のフォルダ名一覧を GCS にアップロードする。
    AI 側 (`gcloud storage cat`) で読み取り、スプレッドシートの居宅名と
    機械的にマッチングさせる。

PII 配慮:
    本 MVP では事業所フォルダ名のみをスキャン (FAX 送信先カテゴリ、PII なし)。
    `\\02.カルテ\\` 等の利用者氏名を含むパスは対象外 (後続検討)。

アップロード先:
    `gs://<bucket>/nas-snapshots/fax-folders-<YYYYMMDD-HHMMSS>.json`

JSON 構造:
    {
      "timestamp": "2026-05-01T12:34:56+09:00",
      "fax_root": "\\\\Tera-station\\share\\03.FAX(事業所)",
      "folders": ["LEBEN(メール)", ...],
      "count": 47
    }
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from google.cloud import storage

from wiseman_hub.config import GcpConfig

logger = logging.getLogger(__name__)


_SNAPSHOT_PREFIX = "nas-snapshots"


@dataclass(frozen=True)
class ScanResult:
    """スキャン結果のサマリ (UI 表示用)。"""

    folder_count: int
    gcs_uri: str
    timestamp: str


def scan_fax_folders(fax_root: Path) -> list[str]:
    """FAX 事業所ルート直下のフォルダ名一覧を返す (1 階層のみ)。

    シンボリックリンクは無視、隠しフォルダ (`.` 始まり) は除外。
    """
    if not fax_root.exists():
        raise FileNotFoundError(f"fax_root not found: {fax_root}")
    if not fax_root.is_dir():
        raise NotADirectoryError(f"fax_root is not a directory: {fax_root}")
    folders: list[str] = []
    for p in fax_root.iterdir():
        try:
            if not p.is_dir():
                continue
        except OSError as exc:
            logger.warning(
                "is_dir check failed for entry: %s", type(exc).__name__
            )
            continue
        if p.name.startswith("."):
            continue
        folders.append(p.name)
    return sorted(folders)


def upload_snapshot(
    gcp: GcpConfig, fax_root: Path, folders: list[str]
) -> ScanResult:
    """フォルダ名一覧を JSON 化して GCS にアップロードする。"""
    # Issue #27 続編 G §4: service_account_key_path は Path 型、google-cloud-storage は str 要求
    client = storage.Client.from_service_account_json(
        str(gcp.service_account_key_path), project=gcp.project_id
    )
    bucket = client.bucket(gcp.bucket_name)
    now = _dt.datetime.now(_dt.UTC).astimezone()
    ts_human = now.strftime("%Y%m%d-%H%M%S")
    blob_name = f"{_SNAPSHOT_PREFIX}/fax-folders-{ts_human}.json"
    payload = {
        "timestamp": now.isoformat(),
        "fax_root": str(fax_root),
        "folders": folders,
        "count": len(folders),
    }
    blob = bucket.blob(blob_name)
    blob.upload_from_string(
        json.dumps(payload, ensure_ascii=False, indent=2),
        content_type="application/json; charset=utf-8",
    )
    uri = f"gs://{gcp.bucket_name}/{blob_name}"
    logger.info("env_scanner: uploaded %d folders to %s", len(folders), uri)
    return ScanResult(
        folder_count=len(folders), gcs_uri=uri, timestamp=now.isoformat()
    )


def scan_and_upload(gcp: GcpConfig, fax_root: Path) -> ScanResult:
    """スキャン → GCS アップロードを 1 操作で実行する高水準 API。"""
    folders = scan_fax_folders(fax_root)
    return upload_snapshot(gcp, fax_root, folders)
