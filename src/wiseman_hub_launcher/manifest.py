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
from typing import NotRequired, TypedDict, cast

from ._supply_chain._http import https_get_bounded

logger = logging.getLogger(__name__)


class ManifestData(TypedDict):
    """validate_manifest 通過後の manifest schema (PR-7、type narrow 用)。

    必須 field は all str、任意 field は NotRequired で表現。
    呼び出し側は `validated["checksum_sha256"]` 等で直接 str narrow され、
    `assert isinstance(..., str)` が不要になる (PR-7 AC3)。
    """

    current_version: str
    minimum_version: str
    download_url: str
    checksum_sha256: str
    commit_sha: str
    built_at: str
    released_at: str
    provenance_url: str
    expected_repo: str
    expected_workflow_ref: str
    release_notes: NotRequired[str]
    force_update: NotRequired[bool]


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
    """HTTPS GET で manifest を fetch する（PR-7 で _http.https_get_bounded に共通化）。

    auth は不要（release-prod bucket は public read 前提、ADR-016 §1.1）。
    HTTPS pin / redirect downgrade 防御 / DoS cap / 6 系統例外正規化は
    `_supply_chain._http.https_get_bounded` 側で実装。本関数は ManifestError
    label と上限値を渡すだけの薄い wrapper。

    Raises:
        ManifestError: HTTPS scheme / HTTP error / timeout / SSL / network / 200 以外 /
            MAX_MANIFEST_BYTES 超過のいずれか
    """
    _ensure_https(manifest_url, label="manifest URL")
    return https_get_bounded(
        manifest_url,
        timeout_sec=timeout_sec,
        max_bytes=MAX_MANIFEST_BYTES,
        error_class=ManifestError,
        label="manifest",
    )


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


def validate_manifest(manifest: dict[str, object]) -> ManifestData:
    """manifest schema を fail-fast で検証し、ManifestData として narrow 返却する (PR-7)。

    検証項目:
        - 必須 field が全て存在し str である
        - current_version / minimum_version が semver 形式（leading zero 拒否）
        - checksum_sha256 が 64 lowercase hex
        - commit_sha が 7-40 lowercase hex
        - built_at / released_at が ISO8601 UTC Z 形式
        - download_url / provenance_url が GCS bucket 内相対 path（path traversal 防御）
        - 任意 field: force_update が bool、release_notes が str + 長さ上限

    Returns:
        ManifestData: 全必須 field が str narrow 済の TypedDict (cast 経由)。
            呼び出し側は ``validated["checksum_sha256"]`` 等で直接 str として
            type narrow され、isinstance assert が不要 (PR-7 AC3)。

    Raises:
        ManifestError: 必須欠落、型不一致、checksum/semver/datetime/commit_sha 形式不正
        ManifestPathTraversalError: download_url / provenance_url が relative path 制約違反
    """
    for field in _REQUIRED_FIELDS:
        if field not in manifest:
            raise ManifestError(f"manifest missing required field: {field}")
        if not isinstance(manifest[field], str):
            raise ManifestError(f"manifest field '{field}' must be string")

    # 任意 field の型検証 (cast 前に isinstance 検証で narrow 不要にする)
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

    # ここまでで全必須 field が str、任意 field が型適合と確定 → cast で TypedDict narrow。
    # 以後の field-specific 検証は narrow 済の validated を参照することで
    # `assert isinstance(..., str)  # noqa: S101` 系を全廃 (AC3、PR-7 review I-5 反映で件数表記削除)
    validated = cast(ManifestData, manifest)

    if not _is_sha256_lower_hex(validated["checksum_sha256"]):
        raise ManifestError("checksum_sha256 must be 64 lowercase hex characters")

    if not _is_commit_sha_hex(validated["commit_sha"]):
        raise ManifestError("commit_sha must be 7-40 lowercase hex characters")

    for ver_field in ("current_version", "minimum_version"):
        ver = validated[ver_field]
        if not is_simple_semver(ver):
            raise ManifestError(f"{ver_field} must be semver (major.minor.patch): {ver!r}")

    for ts_field in ("built_at", "released_at"):
        ts = validated[ts_field]
        if not _is_iso8601_utc_z(ts):
            raise ManifestError(f"{ts_field} must be ISO8601 UTC (Z or +00:00): {ts!r}")

    for url_field in ("download_url", "provenance_url"):
        _validate_relative_path(validated[url_field], field=url_field)

    # PR-6a: expected_repo / expected_workflow_ref を形式検証 (信頼根ではなく表示用)
    if not _GITHUB_OWNER_REPO_RE.match(validated["expected_repo"]):
        raise ManifestError(
            f"expected_repo must be 'owner/repo' format: {validated['expected_repo']!r}"
        )

    if not _WORKFLOW_REF_RE.match(validated["expected_workflow_ref"]):
        raise ManifestError(
            f"expected_workflow_ref format invalid: {validated['expected_workflow_ref']!r}"
        )

    return validated
