"""manifest.json fetch + parse + schema 検証 (ADR-016 PR-3)。

manifest schema (ADR-004 v2 / ADR-016 §3 参照):
    {
        "current_version": "1.2.3",
        "minimum_version": "1.0.0",
        "download_url": "versions/1.2.3/wiseman_hub.exe",
        "checksum_sha256": "abc123...",                  (64 hex)
        "commit_sha": "f976b44...",
        "built_at": "2026-05-06T12:00:00Z",
        "released_at": "2026-05-06T13:00:00Z",
        "provenance_url": "versions/1.2.3/provenance.intoto.jsonl",
        "release_notes": "...",
        "force_update": false
    }

セキュリティ方針:
    - download_url / provenance_url は **GCS bucket 内の相対 path のみ** を許容
    - 絶対 URL / 先頭 / / .. / backslash は path traversal として拒否（fail-fast）
    - HTTPS 以外の manifest URL も呼出側で拒否（auth は urllib.request HTTPS のみ）
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

# 必須 field（schema 不一致は fail-fast）
_REQUIRED_FIELDS: tuple[str, ...] = (
    "current_version",
    "minimum_version",
    "download_url",
    "checksum_sha256",
    "commit_sha",
    "built_at",
    "released_at",
    "provenance_url",
)

_HEX_LOWER = frozenset("0123456789abcdef")
_SCHEME_FIRST = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
_SCHEME_REST = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+.-")


def _is_sha256_lower_hex(s: str) -> bool:
    """64 文字、小文字 hex のみを許容（ADR-016 の checksum 形式制約）。"""
    if len(s) != 64:
        return False
    return all(c in _HEX_LOWER for c in s)


def _is_simple_semver(s: str) -> bool:
    """``major.minor.patch`` のみ許容（pre-release / build metadata は PR-4 で拡張）。"""
    parts = s.split(".")
    if len(parts) != 3:
        return False
    for p in parts:
        if not p:
            return False
        if not p.isdigit():
            return False
    return True


def _has_url_scheme(s: str) -> bool:
    """``scheme:`` 形式の絶対 URL かを判定（http:, https:, file:, javascript: 等すべて検出）。

    RFC 3986 の scheme 文法: ALPHA *( ALPHA / DIGIT / "+" / "-" / "." )
    最初の `:` までに含まれる文字がすべて scheme 文法に従い、最低 1 文字以上あれば scheme とみなす。
    """
    idx = s.find(":")
    if idx <= 0:
        return False
    head = s[:idx]
    if head[0] not in _SCHEME_FIRST:
        return False
    return all(c in _SCHEME_REST for c in head)


class ManifestError(Exception):
    """manifest 取得・parse・schema 検証の失敗。"""


class ManifestPathTraversalError(ManifestError):
    """download_url / provenance_url が GCS bucket 内相対 path を逸脱した場合。"""


def fetch_manifest(manifest_url: str, *, timeout_sec: int = 30) -> bytes:
    """HTTPS GET で manifest を fetch する（stdlib urllib.request のみ）。

    auth は不要（release-prod bucket は public read 前提、ADR-016 §1.1）。
    HTTP error / timeout / network error はすべて ManifestError に正規化する。

    Raises:
        ManifestError: HTTP error, timeout, URL error, 200 以外 status
    """
    req = urllib.request.Request(manifest_url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:  # noqa: S310
            # status は urllib では code 属性（200 OK 以外は HTTPError として上に来るが念のため）
            status = getattr(resp, "status", 200)
            if status != 200:
                raise ManifestError(f"manifest fetch returned non-200 status: {status}")
            return bytes(resp.read())
    except urllib.error.HTTPError as e:
        raise ManifestError(f"manifest fetch HTTP error: {e.code}") from e
    except urllib.error.URLError as e:
        # timeout は URLError(reason=socket.timeout(...)) として来る
        raise ManifestError(f"manifest fetch URL error: {type(e.reason).__name__}") from e
    except TimeoutError as e:
        raise ManifestError("manifest fetch timed out") from e


def parse_manifest(raw: bytes) -> dict[str, object]:
    """manifest bytes を JSON parse する。

    Raises:
        ManifestError: JSON 破損、または top-level が dict でない
    """
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as e:
        raise ManifestError("manifest is not valid UTF-8") from e
    except json.JSONDecodeError as e:
        raise ManifestError(f"manifest is not valid JSON: {type(e).__name__}") from e
    if not isinstance(parsed, dict):
        raise ManifestError(f"manifest top-level must be object, got {type(parsed).__name__}")
    return parsed


def _validate_relative_path(value: str, *, field: str) -> None:
    """download_url / provenance_url が安全な GCS 相対 path であることを検証。

    禁止:
        - 絶対 URL (`http://...`, `https://...`, `file://...`, 任意 `scheme:`)
        - 先頭 `/` または `\\`（絶対 path 化を防ぐ）
        - backslash を含む（Windows path 区切り混入防止）
        - `..` を含む path segment（親ディレクトリ traversal）
        - 空文字列
    """
    if not value:
        raise ManifestPathTraversalError(f"{field} is empty")
    if "\\" in value:
        raise ManifestPathTraversalError(f"{field} contains backslash")
    if value.startswith("/"):
        raise ManifestPathTraversalError(f"{field} starts with '/'")
    if _has_url_scheme(value):
        raise ManifestPathTraversalError(f"{field} contains scheme (must be relative path)")
    # path segment 単位で .. を拒否（"foo/../bar" も "../bar" もすべて拒否）
    for seg in value.split("/"):
        if seg == "..":
            raise ManifestPathTraversalError(f"{field} contains '..' segment")


def validate_manifest(manifest: dict[str, object]) -> None:
    """manifest schema を fail-fast で検証する。

    検証項目:
        - 必須 field が全て存在し str である
        - current_version / minimum_version が semver 形式
        - checksum_sha256 が 64 hex（小文字）
        - download_url / provenance_url が GCS bucket 内相対 path（path traversal 防御）

    Raises:
        ManifestError: 必須欠落、型不一致、checksum 形式不正、semver 不正
        ManifestPathTraversalError: download_url / provenance_url が relative path 制約違反
    """
    for field in _REQUIRED_FIELDS:
        if field not in manifest:
            raise ManifestError(f"manifest missing required field: {field}")
        if not isinstance(manifest[field], str):
            raise ManifestError(f"manifest field '{field}' must be string")

    checksum = manifest["checksum_sha256"]
    assert isinstance(checksum, str)  # noqa: S101 — 直前で isinstance 検証済み、mypy narrow
    if not _is_sha256_lower_hex(checksum):
        raise ManifestError("checksum_sha256 must be 64 lowercase hex characters")

    for ver_field in ("current_version", "minimum_version"):
        ver = manifest[ver_field]
        assert isinstance(ver, str)  # noqa: S101
        if not _is_simple_semver(ver):
            raise ManifestError(f"{ver_field} must be semver (major.minor.patch): {ver!r}")

    for url_field in ("download_url", "provenance_url"):
        url_val = manifest[url_field]
        assert isinstance(url_val, str)  # noqa: S101
        _validate_relative_path(url_val, field=url_field)
