"""Google Cloud Storage クライアント - データアップロード"""

from __future__ import annotations

import logging
from pathlib import Path

from google.cloud import storage

from wiseman_hub.config import GcpConfig

logger = logging.getLogger(__name__)


def create_client(config: GcpConfig) -> storage.Client:
    """GCS クライアントを作成する。"""
    return storage.Client.from_service_account_json(
        config.service_account_key_path,
        project=config.project_id,
    )


def upload_file(config: GcpConfig, local_path: Path, remote_prefix: str = "uploads/") -> str:
    """ローカルファイルをGCSバケットにアップロードし、GCS URIを返す。"""
    client = create_client(config)
    bucket = client.bucket(config.bucket_name)

    blob_name = f"{remote_prefix}{local_path.name}"
    blob = bucket.blob(blob_name)

    logger.info("アップロード中: %s → gs://%s/%s", local_path, config.bucket_name, blob_name)
    blob.upload_from_filename(str(local_path))
    logger.info("アップロード完了: gs://%s/%s", config.bucket_name, blob_name)

    return f"gs://{config.bucket_name}/{blob_name}"


def upload_files(config: GcpConfig, local_paths: list[Path], remote_prefix: str = "uploads/") -> list[str]:
    """複数ファイルをGCSにアップロードする。"""
    uris: list[str] = []
    for path in local_paths:
        uri = upload_file(config, path, remote_prefix)
        uris.append(uri)
    return uris
