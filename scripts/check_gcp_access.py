"""SA キーで GCS への read/write/delete が成立するかを end-to-end 検証する smoke。

過去失敗対策（codex review HIGH-2）:
    個人アカウント基準の `gcloud storage ls` では SA に同等権限あると断定できない。
    本スクリプトは SA キー本体で `storage.Client` を構築し、対象 bucket の
    ``mappings/_health-check.json`` に対して write → read → delete を実行して
    GREEN を出すことで、push_routing / pull_routing が走る前提を確認する。

実行:
    uv run python scripts/check_gcp_access.py <sa_key_path> <bucket_name> [project_id]

終了コード:
    0 = ALL GREEN
    1 = いずれかのフェーズで失敗
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HEALTH_CHECK_BLOB = "mappings/_health-check.json"


def main() -> int:
    if len(sys.argv) < 3:
        print(
            "Usage: python scripts/check_gcp_access.py <sa_key_path> "
            "<bucket_name> [project_id]"
        )
        return 1
    sa_key_path = Path(sys.argv[1])
    bucket_name = sys.argv[2]
    project_id = sys.argv[3] if len(sys.argv) >= 4 else None

    if not sa_key_path.exists():
        print(f"[FAIL] SA キー不在: {sa_key_path.name}")
        return 1

    # Phase 1: SA キーで Client 構築
    try:
        from google.auth import exceptions as auth_exc
        from google.cloud import storage
    except ImportError as exc:
        print(f"[FAIL] google-cloud-storage 未インストール: {exc}")
        return 1

    try:
        client = storage.Client.from_service_account_json(
            str(sa_key_path), project=project_id
        )
    except (ValueError, OSError, auth_exc.GoogleAuthError) as exc:
        print(f"[FAIL] from_service_account_json: {type(exc).__name__}: {exc}")
        return 1

    # client_email 表示（identity 確認、private key は出さない）
    try:
        with sa_key_path.open(encoding="utf-8") as f:
            key_data = json.load(f)
        client_email = key_data.get("client_email", "<unknown>")
    except (OSError, json.JSONDecodeError):
        client_email = "<unreadable>"
    print(f"[OK]   from_service_account_json: {client_email}")

    # Phase 2: bucket 存在確認
    try:
        bucket = client.bucket(bucket_name)
        if not bucket.exists():
            print(f"[FAIL] bucket exists: {bucket_name} not found or no access")
            return 1
    except Exception as exc:  # noqa: BLE001 — diagnostic boundary
        print(f"[FAIL] bucket exists: {type(exc).__name__}: {exc}")
        return 1
    print(f"[OK]   bucket exists: {bucket_name}")

    # Phase 3: write smoke
    blob = bucket.blob(HEALTH_CHECK_BLOB)
    try:
        blob.upload_from_string(
            '{"smoke":"ok"}',
            content_type="application/json; charset=utf-8",
            timeout=30.0,
        )
    except Exception as exc:  # noqa: BLE001 — diagnostic boundary
        print(f"[FAIL] write smoke: {type(exc).__name__}: {exc}")
        return 1
    print(f"[OK]   write smoke: gs://{bucket_name}/{HEALTH_CHECK_BLOB}")

    # Phase 4: read smoke
    try:
        body = blob.download_as_bytes(timeout=30.0)
    except Exception as exc:  # noqa: BLE001 — diagnostic boundary
        print(f"[FAIL] read smoke: {type(exc).__name__}: {exc}")
        return 1
    print(f"[OK]   read smoke: {body!r}")

    # Phase 5: delete smoke
    try:
        blob.delete(timeout=30.0)
    except Exception as exc:  # noqa: BLE001 — diagnostic boundary
        print(f"[FAIL] delete smoke: {type(exc).__name__}: {exc}")
        return 1
    print("[OK]   delete smoke: removed")

    print("ALL GREEN — SA can read/write/delete in mappings/ prefix")
    return 0


if __name__ == "__main__":
    sys.exit(main())
