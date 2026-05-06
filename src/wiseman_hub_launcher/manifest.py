"""manifest.json fetch + parse + schema 検証 (ADR-016 PR-3 / PR-6a)。

manifest schema (ADR-004 v2 / ADR-016 §3 参照、PR-6a で expected_* 追加):
    {
        "current_version": "1.2.3",
        "minimum_version": "1.0.0",
        "download_url": "versions/1.2.3/wiseman_hub.exe",
        "checksum_sha256": "abc123...",                          (64 lowercase hex)
        "commit_sha": "f976b44...",                              (7-40 lowercase hex)
        "built_at": "2026-05-06T12:00:00Z",                      (ISO8601 UTC)
        "released_at": "2026-05-06T13:00:00Z",
        "provenance_url": "versions/1.2.3/wiseman_hub.exe.sigstore.json",  (PR-6a)
        "expected_repo": "sasakisystem0801-source/wiseman-auto-sys",       (PR-6a)
        "expected_workflow_ref":                                            (PR-6a)
            ".github/workflows/release.yml@refs/tags/v1.2.3",
        "release_notes": "...",                                  (任意、最大 4096)
        "force_update": false                                    (任意、bool)
    }

PR-6a (codex review threadId 019dfd9e I-2):
    expected_repo / expected_workflow_ref は表示/監査用に manifest にも記録するが、
    信頼根は launcher 埋め込み constant (`_supply_chain/policy.py` の
    LAUNCHER_EXPECTED_REPO 等)。両者の一致は `_supply_chain/provenance.py` で二重検証。

セキュリティ方針 (codex review threadId 019dfce6 反映):
    - manifest URL は **HTTPS 固定**（http/file/path scheme は ManifestError）
    - redirect 後の URL も HTTPS 固定（http への redirect 攻撃防御）
    - response body に上限（MAX_MANIFEST_BYTES = 1 MiB、DoS 防御）
    - download_url / provenance_url は GCS object key として **狭い文字集合**:
        ^[A-Za-z0-9._/-]+$、segment ごとに `""`/`"."`/`".."` 拒否、
        percent encoding / control char / whitespace / query / fragment 拒否
    - 最大長 path 256 chars、segment 64 chars
"""

from __future__ import annotations

import json
import logging
import re
import ssl
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
    "expected_repo",  # PR-6a (codex I-2: 表示/監査用、信頼根は launcher 埋め込み)
    "expected_workflow_ref",  # PR-6a
)

# PR-6a: expected_repo の形式 ("owner/repo"、各 segment は GitHub の規則準拠)
_GITHUB_OWNER_REPO_RE = re.compile(r"^[A-Za-z0-9._-]{1,39}/[A-Za-z0-9._-]{1,100}$")
# PR-6a: expected_workflow_ref の形式 (release.yml@refs/tags/vX.Y.Z 等)
_WORKFLOW_REF_RE = re.compile(
    r"^\.github/workflows/[A-Za-z0-9._-]+\.ya?ml@refs/(tags|heads)/[A-Za-z0-9._/-]+$"
)

_HEX_LOWER = frozenset("0123456789abcdef")
_PATH_ALLOWED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-")

# DoS 防御: manifest は数百 byte 想定、1 MiB 超は異常
MAX_MANIFEST_BYTES = 1 * 1024 * 1024
# path 全体・segment の最大長（GCS object key として実用十分）
MAX_PATH_LEN = 256
MAX_SEGMENT_LEN = 64
# release_notes の最大長（任意 field）
MAX_RELEASE_NOTES_LEN = 4096


def _is_sha256_lower_hex(s: str) -> bool:
    """64 文字、小文字 hex のみを許容（ADR-016 の checksum 形式制約）。"""
    if len(s) != 64:
        return False
    return all(c in _HEX_LOWER for c in s)


def _is_commit_sha_hex(s: str) -> bool:
    """7-40 文字、小文字 hex のみ（git short/full SHA、Sug-1）。"""
    if not (7 <= len(s) <= 40):
        return False
    return all(c in _HEX_LOWER for c in s)


def is_simple_semver(s: str) -> bool:
    """``major.minor.patch`` のみ許容（pre-release / build metadata は PR-4 で拡張）。

    各 part は 1 文字以上の digit、leading zero は拒否（"01.2.3" 等を拒否、Sug-2）。
    ただし "0" 単独は許容（"0.1.2" 等の major=0 は正当）。

    PR-4 で current.py からも reuse するため public（PR-3 では `_is_simple_semver`、
    PR-4 codex Suggestion 1 反映で rename）。
    """
    parts = s.split(".")
    if len(parts) != 3:
        return False
    for p in parts:
        if not p:
            return False
        if not p.isdigit():
            return False
        # leading zero 拒否（"01"、"007" を拒否、"0" は許容）
        if len(p) > 1 and p[0] == "0":
            return False
    return True


def _is_iso8601_utc_z(s: str) -> bool:
    """built_at / released_at の ISO8601 UTC Z 形式判定（Sug-1）。

    許容: "2026-05-06T12:00:00Z" / "2026-05-06T12:00:00.123Z" 等
    最低限 datetime.fromisoformat で parse でき、末尾 Z または +00:00 終端。
    """
    from datetime import datetime  # 関数内 import で stdlib only 維持

    if not s.endswith(("Z", "+00:00")):
        return False
    candidate = s[:-1] + "+00:00" if s.endswith("Z") else s
    try:
        datetime.fromisoformat(candidate)
    except (ValueError, TypeError):
        return False
    return True


class ManifestError(Exception):
    """manifest 取得・parse・schema 検証の失敗。"""


class ManifestPathTraversalError(ManifestError):
    """download_url / provenance_url が GCS bucket 内相対 path を逸脱した場合。"""


def _ensure_https(url: str, *, label: str = "manifest URL") -> None:
    """url が HTTPS であることを検証する（C-1: HTTPS 固定）。

    Raises:
        ManifestError: https:// 以外（http://, file://, javascript:, ローカル path、空文字列 等）
    """
    if not isinstance(url, str) or not url.startswith("https://"):
        raise ManifestError(f"{label} must use HTTPS scheme")


def fetch_manifest(manifest_url: str, *, timeout_sec: int = 30) -> bytes:
    """HTTPS GET で manifest を fetch する（stdlib urllib.request のみ）。

    auth は不要（release-prod bucket は public read 前提、ADR-016 §1.1）。
    HTTP error / timeout / network / SSL error はすべて ManifestError に正規化する。

    検証:
        - 入力 URL が HTTPS（C-1）
        - redirect 後の最終 URL も HTTPS（http への downgrade 攻撃防御）
        - response body は MAX_MANIFEST_BYTES 以内（I-1: DoS 防御）

    Raises:
        ManifestError: 上記検証失敗、HTTP error、timeout、URL/SSL/socket error、200 以外、size 超過
    """
    _ensure_https(manifest_url, label="manifest URL")
    req = urllib.request.Request(manifest_url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:  # noqa: S310
            # redirect 後の最終 URL も HTTPS であることを検証（C-1: redirect downgrade 防御）
            final_url = resp.geturl()
            if not final_url.startswith("https://"):
                raise ManifestError("manifest URL redirected to non-HTTPS scheme")

            status = getattr(resp, "status", 200)
            if status != 200:
                raise ManifestError(f"manifest fetch returned non-200 status: {status}")

            # I-1: response 上限を超えるかを `MAX+1` まで読んで判定
            body = resp.read(MAX_MANIFEST_BYTES + 1)
            if len(body) > MAX_MANIFEST_BYTES:
                raise ManifestError(
                    f"manifest body exceeds {MAX_MANIFEST_BYTES} bytes (DoS guard)"
                )
            return bytes(body)
    except urllib.error.HTTPError as e:
        raise ManifestError(f"manifest fetch HTTP error: {e.code}") from e
    except urllib.error.URLError as e:
        # timeout は URLError(reason=socket.timeout(...)) として来る
        raise ManifestError(f"manifest fetch URL error: {type(e.reason).__name__}") from e
    except TimeoutError as e:
        # Python 3.10+ では socket.timeout は TimeoutError の alias
        raise ManifestError("manifest fetch timed out") from e
    except ssl.SSLError as e:
        raise ManifestError(f"manifest fetch SSL error: {type(e).__name__}") from e
    except (ConnectionError, OSError) as e:
        # ConnectionRefusedError, ConnectionResetError, BrokenPipeError 等を包括
        raise ManifestError(f"manifest fetch network error: {type(e).__name__}") from e


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
    """download_url / provenance_url が安全な GCS 相対 path であることを検証 (C-2)。

    禁止 vector (codex review threadId 019dfce6 で網羅):
        - 空文字列
        - backslash（Windows path 区切り混入）
        - 先頭 `/`（絶対 path 化）
        - URL scheme（`http://...`、`file://...`、任意 `scheme:`）
        - `..` を含む path segment（親 traversal）
        - `.` を含む path segment（current dir traversal）
        - `""` 空 segment（`a//b`、先頭 `/`、末尾 `/`）
        - `%` を含む（percent encoding 経由の bypass: `%2e%2e`, `%2f` 等）
        - `?` query / `#` fragment（GCS object key には不要）
        - ASCII control char (0x00-0x1F, 0x7F)
        - whitespace（先頭・末尾・内部すべて）
        - `^[A-Za-z0-9._/-]+$` 範囲外の文字
        - 全体 256 文字超 / segment 64 文字超
    """
    if not value:
        raise ManifestPathTraversalError(f"{field} is empty")
    if len(value) > MAX_PATH_LEN:
        raise ManifestPathTraversalError(
            f"{field} exceeds {MAX_PATH_LEN} chars (got {len(value)})"
        )
    # 文字集合チェック（先に厳密化、% / ? / # / whitespace / control はここで一括拒否）
    for ch in value:
        if ch not in _PATH_ALLOWED:
            raise ManifestPathTraversalError(
                f"{field} contains disallowed character (codepoint U+{ord(ch):04X})"
            )
    # 文字集合チェックを通った時点で `\\` / `:` 等は既に拒否されているが、
    # 明示性のため下記も維持（防御の二重化、可読性向上）
    if "\\" in value:  # _PATH_ALLOWED で既に拒否されるが防御重複
        raise ManifestPathTraversalError(f"{field} contains backslash")
    if value.startswith("/"):
        raise ManifestPathTraversalError(f"{field} starts with '/'")
    # path segment 単位の検証
    for seg in value.split("/"):
        if seg == "":
            raise ManifestPathTraversalError(f"{field} contains empty segment")
        if seg in (".", ".."):
            raise ManifestPathTraversalError(f"{field} contains '{seg}' segment")
        if len(seg) > MAX_SEGMENT_LEN:
            raise ManifestPathTraversalError(
                f"{field} segment exceeds {MAX_SEGMENT_LEN} chars"
            )


def validate_manifest(manifest: dict[str, object]) -> None:
    """manifest schema を fail-fast で検証する (codex Sug-1 で field 拡張)。

    検証項目:
        - 必須 field が全て存在し str である
        - current_version / minimum_version が semver 形式（leading zero 拒否）
        - checksum_sha256 が 64 lowercase hex
        - commit_sha が 7-40 lowercase hex
        - built_at / released_at が ISO8601 UTC Z 形式
        - download_url / provenance_url が GCS bucket 内相対 path（path traversal 防御）
        - 任意 field: force_update が bool、release_notes が str + 長さ上限

    Raises:
        ManifestError: 必須欠落、型不一致、checksum/semver/datetime/commit_sha 形式不正
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

    commit_sha = manifest["commit_sha"]
    assert isinstance(commit_sha, str)  # noqa: S101
    if not _is_commit_sha_hex(commit_sha):
        raise ManifestError("commit_sha must be 7-40 lowercase hex characters")

    for ver_field in ("current_version", "minimum_version"):
        ver = manifest[ver_field]
        assert isinstance(ver, str)  # noqa: S101
        if not is_simple_semver(ver):
            raise ManifestError(f"{ver_field} must be semver (major.minor.patch): {ver!r}")

    for ts_field in ("built_at", "released_at"):
        ts = manifest[ts_field]
        assert isinstance(ts, str)  # noqa: S101
        if not _is_iso8601_utc_z(ts):
            raise ManifestError(f"{ts_field} must be ISO8601 UTC (Z or +00:00): {ts!r}")

    for url_field in ("download_url", "provenance_url"):
        url_val = manifest[url_field]
        assert isinstance(url_val, str)  # noqa: S101
        _validate_relative_path(url_val, field=url_field)

    # PR-6a: expected_repo / expected_workflow_ref を形式検証 (信頼根ではなく表示用)
    repo_val = manifest["expected_repo"]
    assert isinstance(repo_val, str)  # noqa: S101
    if not _GITHUB_OWNER_REPO_RE.match(repo_val):
        raise ManifestError(
            f"expected_repo must be 'owner/repo' format: {repo_val!r}"
        )

    wf_val = manifest["expected_workflow_ref"]
    assert isinstance(wf_val, str)  # noqa: S101
    if not _WORKFLOW_REF_RE.match(wf_val):
        raise ManifestError(
            f"expected_workflow_ref format invalid: {wf_val!r}"
        )

    # 任意 field: force_update (bool), release_notes (str + 長さ)
    if "force_update" in manifest and not isinstance(manifest["force_update"], bool):
        raise ManifestError("force_update must be bool when present")
    if "release_notes" in manifest:
        notes = manifest["release_notes"]
        if not isinstance(notes, str):
            raise ManifestError("release_notes must be string when present")
        if len(notes) > MAX_RELEASE_NOTES_LEN:
            raise ManifestError(
                f"release_notes exceeds {MAX_RELEASE_NOTES_LEN} chars (got {len(notes)})"
            )
