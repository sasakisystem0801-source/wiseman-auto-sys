"""Tests for wiseman_hub_launcher.manifest (ADR-016 PR-3)。"""

from __future__ import annotations

import json
import ssl
from unittest.mock import MagicMock, patch

import pytest

from wiseman_hub_launcher.manifest import (
    MAX_MANIFEST_BYTES,
    ManifestError,
    ManifestPathTraversalError,
    fetch_manifest,
    parse_manifest,
    validate_manifest,
)


def _good_manifest() -> dict[str, object]:
    return {
        "current_version": "1.2.3",
        "minimum_version": "1.0.0",
        "download_url": "versions/1.2.3/wiseman_hub.exe",
        "checksum_sha256": "a" * 64,
        "commit_sha": "f976b44",
        "built_at": "2026-05-06T12:00:00Z",
        "released_at": "2026-05-06T13:00:00Z",
        "provenance_url": "versions/1.2.3/provenance.intoto.jsonl",
        "release_notes": "first release",
        "force_update": False,
    }


def _make_fake_resp(
    body: bytes,
    *,
    status: int = 200,
    final_url: str = "https://example.com/manifest.json",
) -> MagicMock:
    """fetch_manifest 用の MagicMock urlopen response factory。"""
    fake_resp = MagicMock()
    fake_resp.status = status
    fake_resp.read.return_value = body
    fake_resp.geturl.return_value = final_url
    fake_resp.__enter__ = MagicMock(return_value=fake_resp)
    fake_resp.__exit__ = MagicMock(return_value=None)
    return fake_resp


# parse_manifest -----------------------------------------------------------

def test_parse_manifest_normal() -> None:
    raw = json.dumps(_good_manifest()).encode("utf-8")
    parsed = parse_manifest(raw)
    assert parsed["current_version"] == "1.2.3"


def test_parse_manifest_invalid_json() -> None:
    with pytest.raises(ManifestError, match="not valid JSON"):
        parse_manifest(b"{not json")


def test_parse_manifest_invalid_utf8() -> None:
    with pytest.raises(ManifestError, match="not valid UTF-8"):
        parse_manifest(b"\xff\xfe\xfd")


def test_parse_manifest_top_level_not_dict() -> None:
    with pytest.raises(ManifestError, match="must be object"):
        parse_manifest(b"[1, 2, 3]")


# validate_manifest -------------------------------------------------------

def test_validate_manifest_normal() -> None:
    validate_manifest(_good_manifest())  # should not raise


@pytest.mark.parametrize(
    "missing_field",
    [
        "current_version",
        "minimum_version",
        "download_url",
        "checksum_sha256",
        "commit_sha",
        "built_at",
        "released_at",
        "provenance_url",
    ],
)
def test_validate_manifest_missing_required(missing_field: str) -> None:
    m = _good_manifest()
    del m[missing_field]
    with pytest.raises(ManifestError, match=f"missing required field: {missing_field}"):
        validate_manifest(m)


def test_validate_manifest_field_not_string() -> None:
    m = _good_manifest()
    m["current_version"] = 123  # type: ignore[assignment]
    with pytest.raises(ManifestError, match="must be string"):
        validate_manifest(m)


@pytest.mark.parametrize(
    "bad_checksum",
    [
        "tooshort",
        "A" * 64,  # uppercase rejected
        "g" * 64,  # not hex
        "a" * 63,  # 63 chars
        "a" * 65,  # 65 chars
    ],
)
def test_validate_manifest_invalid_checksum(bad_checksum: str) -> None:
    m = _good_manifest()
    m["checksum_sha256"] = bad_checksum
    with pytest.raises(ManifestError, match="64 lowercase hex"):
        validate_manifest(m)


@pytest.mark.parametrize(
    "bad_version",
    [
        "1.2",
        "1.2.3.4",
        "v1.2.3",
        "1.2.3-rc1",
        "abc",
        "01.2.3",   # Sug-2: leading zero
        "1.02.3",
        "1.2.03",
        "001.2.3",  # Sug-2: multiple leading zeros
    ],
)
def test_validate_manifest_invalid_semver(bad_version: str) -> None:
    m = _good_manifest()
    m["current_version"] = bad_version
    with pytest.raises(ManifestError, match="must be semver"):
        validate_manifest(m)


def test_validate_manifest_zero_major_allowed() -> None:
    """0 単独 (major=0 等) は許容（leading zero とは区別、Sug-2）。"""
    m = _good_manifest()
    m["current_version"] = "0.1.2"
    m["minimum_version"] = "0.0.0"
    validate_manifest(m)  # should not raise


# Sug-1: schema 拡張 (commit_sha / built_at / force_update / release_notes)
@pytest.mark.parametrize(
    "bad_commit",
    [
        "abc",          # 3 chars (< 7)
        "f" * 41,       # 41 chars (> 40)
        "F" * 7,        # uppercase
        "g" * 7,        # not hex
        "f976b4z",      # mixed non-hex
    ],
)
def test_validate_manifest_invalid_commit_sha(bad_commit: str) -> None:
    m = _good_manifest()
    m["commit_sha"] = bad_commit
    with pytest.raises(ManifestError, match="commit_sha must be 7-40"):
        validate_manifest(m)


@pytest.mark.parametrize(
    "bad_ts",
    [
        "2026-05-06",                        # date only
        "2026-05-06T12:00:00",               # no TZ
        "2026-05-06T12:00:00+09:00",         # JST not allowed (UTC only)
        "not a date",
        "",
    ],
)
def test_validate_manifest_invalid_built_at(bad_ts: str) -> None:
    m = _good_manifest()
    m["built_at"] = bad_ts
    with pytest.raises(ManifestError, match="built_at must be ISO8601 UTC"):
        validate_manifest(m)


def test_validate_manifest_force_update_not_bool() -> None:
    m = _good_manifest()
    m["force_update"] = "true"  # str ではなく bool 必須
    with pytest.raises(ManifestError, match="force_update must be bool"):
        validate_manifest(m)


def test_validate_manifest_release_notes_too_long() -> None:
    m = _good_manifest()
    m["release_notes"] = "x" * 4097
    with pytest.raises(ManifestError, match="release_notes exceeds"):
        validate_manifest(m)


def test_validate_manifest_optional_fields_omitted() -> None:
    """force_update / release_notes は任意 field、欠落しても OK。"""
    m = _good_manifest()
    m.pop("release_notes")
    m.pop("force_update")
    validate_manifest(m)  # should not raise


# Path traversal defenses (C-2 強化版) -------------------------------------

@pytest.mark.parametrize(
    "bad_url",
    [
        # 既存
        "https://evil.example.com/payload.exe",
        "http://evil.example.com/payload.exe",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "/etc/passwd",
        "../../etc/passwd",
        "versions/../../etc/passwd",
        "versions/1.2.3/..",
        "versions\\1.2.3\\wiseman.exe",
        "/versions/1.2.3/wiseman.exe",
        "",
        # C-2 (codex review threadId 019dfce6) 新規 vector
        "versions/1.2.3/wiseman.exe?gen=1",          # query string
        "versions/1.2.3/wiseman.exe#frag",           # fragment
        "versions/%2e%2e/evil.exe",                  # percent-encoded ..
        "versions/%2f/evil.exe",                     # percent-encoded /
        "versions/./wiseman.exe",                    # single-dot segment
        "versions//wiseman.exe",                     # empty segment
        " versions/1.2.3/wiseman.exe",               # leading whitespace
        "versions/1.2.3/wiseman.exe ",               # trailing whitespace
        "versions/ 1.2.3/wiseman.exe",               # internal whitespace
        "versions/1.2.3/wiseman.exe\n",              # trailing newline
        "versions/1.2.3/wiseman.exe\t",              # tab
        "versions/1.2.3/\x00wiseman.exe",            # null byte
        "versions/1.2.3/\x7fwiseman.exe",            # DEL
        "x" * 257,                                    # 257 chars (> MAX_PATH_LEN)
        "versions/" + ("a" * 65) + "/wiseman.exe",   # segment > 64 chars
        "versions/1.2.3/wiseman.exe@gen=1",          # @
        "versions/1.2.3/wiseman.exe&foo=bar",        # &
        "versions/1.2.3/日本語.exe",                  # 非 ASCII
    ],
)
def test_validate_manifest_path_traversal_download_url(bad_url: str) -> None:
    m = _good_manifest()
    m["download_url"] = bad_url
    with pytest.raises(ManifestPathTraversalError):
        validate_manifest(m)


@pytest.mark.parametrize(
    "bad_url",
    [
        "https://evil.example.com/p.intoto.jsonl",
        "../../etc/passwd",
        "/abs/path",
        "versions\\1.2.3\\p.intoto.jsonl",
        "versions/1.2.3/p?gen=1",
        "versions/%2e%2e/evil.jsonl",
    ],
)
def test_validate_manifest_path_traversal_provenance_url(bad_url: str) -> None:
    m = _good_manifest()
    m["provenance_url"] = bad_url
    with pytest.raises(ManifestPathTraversalError):
        validate_manifest(m)


def test_validate_manifest_relative_subpath_allowed() -> None:
    m = _good_manifest()
    m["download_url"] = "versions/2.0.0/sub/dir/wiseman_hub.exe"
    m["provenance_url"] = "versions/2.0.0/sub/dir/provenance.intoto.jsonl"
    validate_manifest(m)  # should not raise


def test_validate_manifest_max_path_len_boundary() -> None:
    """ちょうど 256 chars は OK、257 chars は NG（boundary）。"""
    m = _good_manifest()
    seg64 = "a" * 64
    # 64 + 1 + 64 + 1 + 64 + 1 + 61 = 256 ちょうど
    candidate = seg64 + "/" + seg64 + "/" + seg64 + "/" + ("z" * 61)
    assert len(candidate) == 256
    m["download_url"] = candidate
    validate_manifest(m)  # 256 ちょうどは OK


# fetch_manifest -----------------------------------------------------------

def test_fetch_manifest_http_200() -> None:
    fake_resp = _make_fake_resp(b'{"hello":"world"}')
    with patch("wiseman_hub_launcher.manifest.urllib.request.urlopen", return_value=fake_resp):
        out = fetch_manifest("https://example.com/manifest.json")
    assert out == b'{"hello":"world"}'


def test_fetch_manifest_http_error() -> None:
    import urllib.error

    err = urllib.error.HTTPError(
        url="https://example.com/manifest.json",
        code=404,
        msg="Not Found",
        hdrs=None,  # type: ignore[arg-type]
        fp=None,
    )
    with (
        patch("wiseman_hub_launcher.manifest.urllib.request.urlopen", side_effect=err),
        pytest.raises(ManifestError, match="HTTP error: 404"),
    ):
        fetch_manifest("https://example.com/manifest.json")


def test_fetch_manifest_url_error() -> None:
    import urllib.error

    err = urllib.error.URLError(reason=ConnectionRefusedError("conn refused"))
    with (
        patch("wiseman_hub_launcher.manifest.urllib.request.urlopen", side_effect=err),
        pytest.raises(ManifestError, match="URL error"),
    ):
        fetch_manifest("https://example.com/manifest.json")


def test_fetch_manifest_timeout() -> None:
    with (
        patch(
            "wiseman_hub_launcher.manifest.urllib.request.urlopen",
            side_effect=TimeoutError("timed out"),
        ),
        pytest.raises(ManifestError, match="timed out"),
    ):
        fetch_manifest("https://example.com/manifest.json", timeout_sec=1)


def test_fetch_manifest_non_200_status() -> None:
    fake_resp = _make_fake_resp(b"", status=204)
    with (
        patch("wiseman_hub_launcher.manifest.urllib.request.urlopen", return_value=fake_resp),
        pytest.raises(ManifestError, match="non-200"),
    ):
        fetch_manifest("https://example.com/manifest.json")


# C-1: HTTPS 固定 + redirect 検証 -----------------------------------------

@pytest.mark.parametrize(
    "bad_url",
    [
        "http://example.com/manifest.json",
        "file:///etc/passwd",
        "ftp://example.com/manifest.json",
        "/local/path/manifest.json",
        "manifest.json",
        "",
    ],
)
def test_fetch_manifest_rejects_non_https(bad_url: str) -> None:
    """C-1: HTTPS 以外の入力 URL は ManifestError で拒否（urlopen に渡さない）。"""
    with (
        patch("wiseman_hub_launcher.manifest.urllib.request.urlopen") as urlopen_mock,
        pytest.raises(ManifestError, match="HTTPS"),
    ):
        fetch_manifest(bad_url)
    urlopen_mock.assert_not_called()  # urlopen に渡さず即拒否


def test_fetch_manifest_rejects_redirect_to_http() -> None:
    """C-1: redirect 後の URL が http:// なら拒否（downgrade 攻撃防御）。"""
    fake_resp = _make_fake_resp(
        b'{"x":1}',
        final_url="http://evil.example.com/manifest.json",  # downgrade redirect
    )
    with (
        patch("wiseman_hub_launcher.manifest.urllib.request.urlopen", return_value=fake_resp),
        pytest.raises(ManifestError, match="non-HTTPS"),
    ):
        fetch_manifest("https://example.com/manifest.json")


# I-1: DoS cap (response 上限) ---------------------------------------------

def test_fetch_manifest_rejects_oversized_response() -> None:
    """I-1: 1 MiB 超の response は ManifestError で拒否。"""
    oversized = b"x" * (MAX_MANIFEST_BYTES + 1)
    fake_resp = _make_fake_resp(oversized)
    with (
        patch("wiseman_hub_launcher.manifest.urllib.request.urlopen", return_value=fake_resp),
        pytest.raises(ManifestError, match="exceeds.*bytes"),
    ):
        fetch_manifest("https://example.com/manifest.json")


def test_fetch_manifest_at_max_size_ok() -> None:
    """I-1: ちょうど 1 MiB は OK（boundary）。"""
    at_max = b"x" * MAX_MANIFEST_BYTES
    fake_resp = _make_fake_resp(at_max)
    with patch("wiseman_hub_launcher.manifest.urllib.request.urlopen", return_value=fake_resp):
        out = fetch_manifest("https://example.com/manifest.json")
    assert len(out) == MAX_MANIFEST_BYTES


# I-2: SSL/socket/network 例外の正規化 -------------------------------------

def test_fetch_manifest_ssl_error() -> None:
    """I-2: ssl.SSLError は ManifestError に正規化。"""
    err = ssl.SSLError("bad cert")
    with (
        patch("wiseman_hub_launcher.manifest.urllib.request.urlopen", side_effect=err),
        pytest.raises(ManifestError, match="SSL error"),
    ):
        fetch_manifest("https://example.com/manifest.json")


def test_fetch_manifest_socket_timeout() -> None:
    """I-2: socket.timeout (Python 3.10+ では TimeoutError alias) を ManifestError に正規化。"""
    # socket.timeout は Python 3.10+ で TimeoutError alias、I-2 の意図は同じ
    with (
        patch(
            "wiseman_hub_launcher.manifest.urllib.request.urlopen",
            side_effect=TimeoutError("sock timeout"),
        ),
        pytest.raises(ManifestError, match="timed out"),
    ):
        fetch_manifest("https://example.com/manifest.json")


def test_fetch_manifest_connection_refused() -> None:
    """I-2: ConnectionRefusedError は ManifestError に正規化。"""
    err = ConnectionRefusedError("refused")
    with (
        patch("wiseman_hub_launcher.manifest.urllib.request.urlopen", side_effect=err),
        pytest.raises(ManifestError, match="network error"),
    ):
        fetch_manifest("https://example.com/manifest.json")
