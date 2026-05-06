"""Tests for wiseman_hub_launcher.manifest (ADR-016 PR-3)。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from wiseman_hub_launcher.manifest import (
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
    ["1.2", "1.2.3.4", "v1.2.3", "1.2.3-rc1", "abc"],
)
def test_validate_manifest_invalid_semver(bad_version: str) -> None:
    m = _good_manifest()
    m["current_version"] = bad_version
    with pytest.raises(ManifestError, match="must be semver"):
        validate_manifest(m)


# Path traversal defenses --------------------------------------------------

@pytest.mark.parametrize(
    "bad_url",
    [
        "https://evil.example.com/payload.exe",   # absolute https
        "http://evil.example.com/payload.exe",    # absolute http
        "file:///etc/passwd",                       # absolute file://
        "javascript:alert(1)",                      # arbitrary scheme
        "/etc/passwd",                              # leading /
        "../../etc/passwd",                         # parent traversal
        "versions/../../etc/passwd",                # nested traversal
        "versions/1.2.3/..",                        # trailing ..
        "versions\\1.2.3\\wiseman.exe",            # backslash
        "/versions/1.2.3/wiseman.exe",              # leading slash
        "",                                         # empty
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


# fetch_manifest -----------------------------------------------------------

def test_fetch_manifest_http_200() -> None:
    fake_resp = MagicMock()
    fake_resp.status = 200
    fake_resp.read.return_value = b'{"hello":"world"}'
    fake_resp.__enter__ = MagicMock(return_value=fake_resp)
    fake_resp.__exit__ = MagicMock(return_value=None)

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
    fake_resp = MagicMock()
    fake_resp.status = 204
    fake_resp.read.return_value = b""
    fake_resp.__enter__ = MagicMock(return_value=fake_resp)
    fake_resp.__exit__ = MagicMock(return_value=None)

    with (
        patch("wiseman_hub_launcher.manifest.urllib.request.urlopen", return_value=fake_resp),
        pytest.raises(ManifestError, match="non-200"),
    ):
        fetch_manifest("https://example.com/manifest.json")
