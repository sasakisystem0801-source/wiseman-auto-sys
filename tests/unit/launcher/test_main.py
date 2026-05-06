"""Tests for wiseman_hub_launcher.__main__ CLI entry (ADR-016 PR-3)。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from wiseman_hub_launcher import __main__ as launcher_main
from wiseman_hub_launcher.__main__ import (
    EXIT_CONFIG,
    EXIT_MANIFEST,
    EXIT_OK,
    main,
    run_dry_run,
)
from wiseman_hub_launcher.manifest import ManifestError


def _good_manifest_bytes(version: str = "1.2.3") -> bytes:
    return json.dumps(
        {
            "current_version": version,
            "minimum_version": "1.0.0",
            "download_url": f"versions/{version}/wiseman_hub.exe",
            "checksum_sha256": "a" * 64,
            "commit_sha": "f976b44",
            "built_at": "2026-05-06T12:00:00Z",
            "released_at": "2026-05-06T13:00:00Z",
            "provenance_url": f"versions/{version}/provenance.intoto.jsonl",
            "release_notes": "test",
            "force_update": False,
        }
    ).encode("utf-8")


def test_main_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "wiseman_launcher" in out


def test_main_without_dry_run_returns_config_error(tmp_path: Path) -> None:
    code = main(["--current-path", str(tmp_path / "current.json")])
    assert code == EXIT_CONFIG


def test_main_dry_run_success(tmp_path: Path) -> None:
    cur_path = tmp_path / "current.json"
    cur_path.write_text(json.dumps({"version": "1.0.0", "released_at": "2026-01-01T00:00:00Z"}))

    with patch.object(launcher_main, "fetch_manifest", return_value=_good_manifest_bytes("1.2.3")):
        code = main(
            [
                "--dry-run",
                "--manifest-url",
                "https://example.com/manifest.json",
                "--current-path",
                str(cur_path),
            ]
        )
    assert code == EXIT_OK


def test_main_dry_run_fetch_failure(tmp_path: Path) -> None:
    with patch.object(
        launcher_main, "fetch_manifest", side_effect=ManifestError("network down")
    ):
        code = main(
            [
                "--dry-run",
                "--manifest-url",
                "https://example.com/manifest.json",
                "--current-path",
                str(tmp_path / "current.json"),
            ]
        )
    assert code == EXIT_MANIFEST


def test_main_dry_run_validation_failure(tmp_path: Path) -> None:
    bad = json.dumps({"current_version": "1.0.0"}).encode("utf-8")  # missing fields
    with patch.object(launcher_main, "fetch_manifest", return_value=bad):
        code = main(
            [
                "--dry-run",
                "--manifest-url",
                "https://example.com/manifest.json",
                "--current-path",
                str(tmp_path / "current.json"),
            ]
        )
    assert code == EXIT_MANIFEST


def test_run_dry_run_already_up_to_date(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    cur_path = tmp_path / "current.json"
    cur_path.write_text(json.dumps({"version": "1.2.3", "released_at": "2026-05-06T13:00:00Z"}))
    with (
        caplog.at_level("INFO"),
        patch.object(launcher_main, "fetch_manifest", return_value=_good_manifest_bytes("1.2.3")),
    ):
        code = run_dry_run("https://example.com/manifest.json", cur_path)
    assert code == EXIT_OK
    assert any("up-to-date" in r.message for r in caplog.records)


def test_run_dry_run_would_download(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    cur_path = tmp_path / "current.json"
    cur_path.write_text(json.dumps({"version": "1.0.0", "released_at": ""}))
    with (
        caplog.at_level("INFO"),
        patch.object(launcher_main, "fetch_manifest", return_value=_good_manifest_bytes("1.2.3")),
    ):
        code = run_dry_run("https://example.com/manifest.json", cur_path)
    assert code == EXIT_OK
    msgs = " ".join(r.message for r in caplog.records)
    assert "would download" in msgs


def test_run_dry_run_manifest_older_than_current(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    cur_path = tmp_path / "current.json"
    cur_path.write_text(json.dumps({"version": "2.0.0", "released_at": "2026-04-01T00:00:00Z"}))
    with (
        caplog.at_level("WARNING"),
        patch.object(launcher_main, "fetch_manifest", return_value=_good_manifest_bytes("1.2.3")),
    ):
        code = run_dry_run("https://example.com/manifest.json", cur_path)
    assert code == EXIT_OK
    assert any("older than current" in r.message for r in caplog.records)


# C-1: HTTPS 入口検証 (CLI レベル) -----------------------------------------

@pytest.mark.parametrize(
    "bad_url",
    [
        "http://example.com/manifest.json",
        "file:///etc/manifest.json",
        "ftp://example.com/manifest.json",
        "/local/manifest.json",
    ],
)
def test_main_dry_run_rejects_non_https_manifest_url(tmp_path: Path, bad_url: str) -> None:
    """C-1: --manifest-url が HTTPS 以外なら EXIT_CONFIG (manifest fetch には到達しない)。"""
    with patch.object(launcher_main, "fetch_manifest") as fetch_mock:
        code = main(
            [
                "--dry-run",
                "--manifest-url",
                bad_url,
                "--current-path",
                str(tmp_path / "current.json"),
            ]
        )
    assert code == EXIT_CONFIG
    fetch_mock.assert_not_called()  # fetch に渡さず即拒否


# I-3: dry-run の副作用ゼロ -------------------------------------------------

def test_dry_run_does_not_quarantine_corrupt_current(tmp_path: Path) -> None:
    """I-3: dry-run では破損 current.json を rename しない（副作用ゼロ）。"""
    cur_path = tmp_path / "current.json"
    cur_path.write_bytes(b"{not json")  # 破損

    with patch.object(launcher_main, "fetch_manifest", return_value=_good_manifest_bytes("1.0.0")):
        code = main(
            [
                "--dry-run",
                "--manifest-url",
                "https://example.com/manifest.json",
                "--current-path",
                str(cur_path),
            ]
        )
    # exit code は OK (DEFAULT_CURRENT で続行)
    assert code == EXIT_OK
    # 破損ファイルはそのまま残る (dry-run 副作用ゼロ)
    assert cur_path.exists()
    assert cur_path.read_bytes() == b"{not json"
    # quarantine ファイルは作られない
    assert not list(tmp_path.glob("current.json.corrupt-*"))
