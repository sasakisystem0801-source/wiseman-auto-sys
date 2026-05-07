"""manifest.json 生成スクリプト (ADR-016 PR-6 後半)。

GitHub Actions release.yml から呼出され、versions/X.Y.Z/ に upload 済の artifact
について manifest.json を atomic 生成する。

入力:
    --version X.Y.Z (semver、必須)
    --commit-sha (40 hex、必須)
    --tag v1.2.3 (必須、release.yml 側で stable check 済前提)
    --output PATH (manifest.json 出力先、必須)
    --dist-dir DIR (sha256 計算対象、default: dist/)
    --minimum-version X.Y.Z (任意、default 0.0.1、launcher 側 minimum_version 用)

manifest 内の URL は GCS bucket 相対 path (`versions/X.Y.Z/...`)。bucket 名は
launcher 側 `RELEASE_BUCKET_BASE` constant で組立てるため本 script では不要。

出力:
    ManifestData TypedDict 互換の JSON (src/wiseman_hub_launcher/manifest.py 参照)
    sbom_url / sbom_sha256 を含む (PR-6 後半 S1 反映)
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

EXPECTED_REPO = "sasakisystem0801-source/wiseman-auto-sys"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _now_iso8601_utc() -> str:
    return dt.datetime.now(tz=dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="generate_manifest")
    parser.add_argument("--version", required=True, help="semver X.Y.Z (no v prefix)")
    parser.add_argument("--commit-sha", required=True, help="40-char hex commit sha")
    parser.add_argument("--tag", required=True, help="git tag name (e.g. v1.2.3)")
    parser.add_argument("--output", required=True, type=Path, help="manifest output path")
    parser.add_argument("--dist-dir", type=Path, default=Path("dist"))
    parser.add_argument("--minimum-version", default="0.0.1")
    args = parser.parse_args(argv)

    version: str = args.version
    if not version or version.startswith("v"):
        print(f"ERROR: --version must be plain semver (no v prefix), got: {version!r}", file=sys.stderr)
        return 2

    exe_path = args.dist_dir / "wiseman_hub.exe"
    sbom_path = args.dist_dir / "sbom.json"
    if not exe_path.exists():
        print(f"ERROR: exe not found: {exe_path}", file=sys.stderr)
        return 2
    if not sbom_path.exists():
        print(f"ERROR: sbom not found: {sbom_path}", file=sys.stderr)
        return 2

    exe_sha = _sha256_file(exe_path)
    sbom_sha = _sha256_file(sbom_path)
    now = _now_iso8601_utc()
    workflow_ref = f".github/workflows/release.yml@refs/tags/{args.tag}"

    manifest = {
        "current_version": version,
        "minimum_version": args.minimum_version,
        "download_url": f"versions/{version}/wiseman_hub.exe",
        "checksum_sha256": exe_sha,
        "commit_sha": args.commit_sha.lower(),
        "built_at": now,
        "released_at": now,
        "provenance_url": f"versions/{version}/wiseman_hub.exe.sigstore.json",
        "expected_repo": EXPECTED_REPO,
        "expected_workflow_ref": workflow_ref,
        "sbom_url": f"versions/{version}/sbom.json",
        "sbom_sha256": sbom_sha,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(
        f"manifest written: {args.output} "
        f"(version={version}, exe_sha={exe_sha[:16]}..., sbom_sha={sbom_sha[:16]}...)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
