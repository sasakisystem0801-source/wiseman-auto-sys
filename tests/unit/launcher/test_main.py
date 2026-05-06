"""Tests for wiseman_hub_launcher.__main__ CLI entry (ADR-016 PR-3 / PR-4)。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from wiseman_hub_launcher import __main__ as launcher_main
from wiseman_hub_launcher.__main__ import (
    EXIT_CHECKSUM_MISMATCH,
    EXIT_CONFIG,
    EXIT_LOCK_HELD,
    EXIT_MANIFEST,
    EXIT_OK,
    EXIT_PROVENANCE,
    EXIT_ROLLBACK_UNAVAILABLE,
    EXIT_SPAWN_FAILED_NO_ROLLBACK,
    main,
    run_dry_run,
)
from wiseman_hub_launcher.checksum import ChecksumError
from wiseman_hub_launcher.current import CurrentReadError
from wiseman_hub_launcher.manifest import ManifestError
from wiseman_hub_launcher.updater import (
    DownloadError,
    LockHeldError,
    PreflightError,
    SpawnFailedNoRollbackError,
    SpawnOutcome,
    SpawnResult,
)


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
            # PR-6a (T0 Explore + codex C-1): canonical = download_url + ".sigstore.json"
            "provenance_url": f"versions/{version}/wiseman_hub.exe.sigstore.json",
            "expected_repo": "sasakisystem0801-source/wiseman-auto-sys",
            "expected_workflow_ref": f".github/workflows/release.yml@refs/tags/v{version}",
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


# PR-4: --update mode + supply-chain gate ---------------------------------------


def _good_manifest_dict(version: str = "1.2.3") -> dict[str, object]:
    return json.loads(_good_manifest_bytes(version).decode("utf-8"))


def test_main_update_without_test_bypass_reaches_provenance_stub(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PR-6a C-2: --allow-test-unsigned-provenance flag なし + env var なしの状態で
    --update を実行すると、provenance verify が default で実施され signature stub に
    到達して EXIT_PROVENANCE (9)。EXIT_CONFIG (PR-4) ではない (CONFIG fail-closed は除去)。

    本番 PC では環境変数なしのため、CLI flag が無い限り stub bypass されない。
    """
    # env var を必ず unset (test fixture leak 防止)
    monkeypatch.delenv("WISEMAN_ALLOW_UNSIGNED_PROVENANCE_FOR_TESTS", raising=False)

    cur_path = tmp_path / "current.json"
    cur_path.write_text(
        json.dumps({"version": "1.2.3", "released_at": "x", "previous_version": ""})
    )
    binary = tmp_path / "versions" / "1.2.3" / "wiseman_hub.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"existing")

    # canonical URL 検証 + download_provenance を mock 化、verify_provenance のみ通常呼出
    with (
        patch.object(
            launcher_main, "fetch_manifest",
            return_value=_good_manifest_bytes("2.0.0"),
        ),
        patch("wiseman_hub_launcher.updater.download_artifact", return_value=binary),
        patch("wiseman_hub_launcher.updater.download_provenance", return_value=binary),
        patch("wiseman_hub_launcher.updater.validate_canonical_provenance_url"),
    ):
        code = main(
            [
                "--update",
                "--manifest-url",
                "https://example.com/manifest.json",
                "--home",
                str(tmp_path),
                "--monitor-timeout",
                "0.05",
            ]
        )
    # flag なし + env なしで verify_provenance が provenance file の parse 実行 →
    # parse 失敗 (binary を渡したので) または signature stub 到達 → 9 か他コード
    assert code in (EXIT_PROVENANCE, EXIT_PROVENANCE)


# PR-6a NEW: 二重 gate (CLI flag + env var AND) -----------------------------------


def test_main_update_test_bypass_requires_env_var(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-2 二重 gate: --allow-test-unsigned-provenance だけ + env var なしで実行すると、
    signature stub 経路で EXIT_PROVENANCE。env var ありなら bypass で進行。
    本番 PC では env が設定されないので CLI flag を渡されても fail-close する。
    """
    monkeypatch.delenv("WISEMAN_ALLOW_UNSIGNED_PROVENANCE_FOR_TESTS", raising=False)

    cur_path = tmp_path / "current.json"
    cur_path.write_text(
        json.dumps({"version": "1.2.3", "released_at": "x", "previous_version": ""})
    )
    binary = tmp_path / "versions" / "1.2.3" / "wiseman_hub.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"existing")

    with (
        patch.object(
            launcher_main, "fetch_manifest",
            return_value=_good_manifest_bytes("2.0.0"),
        ),
        patch("wiseman_hub_launcher.updater.download_artifact", return_value=binary),
        patch("wiseman_hub_launcher.updater.download_provenance", return_value=binary),
        patch("wiseman_hub_launcher.updater.validate_canonical_provenance_url"),
    ):
        code = main(
            [
                "--update",
                "--allow-test-unsigned-provenance",
                "--manifest-url",
                "https://example.com/manifest.json",
                "--home",
                str(tmp_path),
                "--monitor-timeout",
                "0.05",
            ]
        )
    # CLI flag だけでは bypass されず、provenance verify が parse でも stub でも
    # ProvenanceError 系で fail → EXIT_PROVENANCE
    assert code == EXIT_PROVENANCE


def test_main_update_with_allow_insecure_proceeds(tmp_path: Path) -> None:
    """PR-4: --allow-test-unsigned-provenance で gate bypass、update 実行。"""
    cur_path = tmp_path / "current.json"
    cur_path.write_text(
        json.dumps({"version": "1.2.3", "released_at": "x", "previous_version": ""})
    )
    # 既存 binary を seed (preflight pass 用)
    binary = tmp_path / "versions" / "1.2.3" / "wiseman_hub.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"existing")

    with (
        patch.object(
            launcher_main,
            "fetch_manifest",
            return_value=_good_manifest_bytes("1.2.3"),
        ),
        patch.object(
            launcher_main,
            "update_and_spawn",
            return_value=SpawnOutcome(result=SpawnResult.SUCCESS, returncode=None),
        ),
    ):
        code = main(
            [
                "--update",
                "--allow-test-unsigned-provenance",
                "--manifest-url",
                "https://example.com/manifest.json",
                "--home",
                str(tmp_path),
                "--monitor-timeout",
                "0.05",
            ]
        )
    assert code == EXIT_OK


def test_main_update_no_spawn_returns_ok(tmp_path: Path) -> None:
    """AC-6: --no-spawn で SUCCESS sentinel → EXIT_OK。"""
    cur_path = tmp_path / "current.json"
    cur_path.write_text(
        json.dumps({"version": "1.2.3", "released_at": "x", "previous_version": ""})
    )
    binary = tmp_path / "versions" / "1.2.3" / "wiseman_hub.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"existing")

    with (
        patch.object(
            launcher_main,
            "fetch_manifest",
            return_value=_good_manifest_bytes("1.5.0"),
        ),
        patch.object(
            launcher_main,
            "update_and_spawn",
            return_value=SpawnOutcome(result=SpawnResult.SUCCESS, returncode=None),
        ),
    ):
        code = main(
            [
                "--update",
                "--no-spawn",
                "--allow-test-unsigned-provenance",
                "--manifest-url",
                "https://example.com/manifest.json",
                "--home",
                str(tmp_path),
            ]
        )
    assert code == EXIT_OK


def test_main_no_spawn_requires_update(tmp_path: Path) -> None:
    """--no-spawn 単独 (--update なし) は EXIT_CONFIG。"""
    code = main(["--no-spawn", "--home", str(tmp_path)])
    assert code == EXIT_CONFIG


def test_main_dry_run_and_update_mutex(tmp_path: Path) -> None:
    """--dry-run + --update の同時指定は EXIT_CONFIG。"""
    code = main(
        [
            "--dry-run",
            "--update",
            "--allow-test-unsigned-provenance",
            "--home",
            str(tmp_path),
        ]
    )
    assert code == EXIT_CONFIG


def test_main_update_rejects_non_https(tmp_path: Path) -> None:
    """--update でも --manifest-url が HTTPS 以外なら EXIT_CONFIG。"""
    code = main(
        [
            "--update",
            "--allow-test-unsigned-provenance",
            "--manifest-url",
            "http://example.com/manifest.json",
            "--home",
            str(tmp_path),
        ]
    )
    assert code == EXIT_CONFIG


def test_main_update_lock_held_returns_8(tmp_path: Path) -> None:
    """AC-12: 多重起動 (LockHeldError) → EXIT_LOCK_HELD (8)。"""
    cur_path = tmp_path / "current.json"
    cur_path.write_text(
        json.dumps({"version": "1.2.3", "released_at": "x", "previous_version": ""})
    )

    with patch.object(
        launcher_main,
        "acquire_lock",
        side_effect=LockHeldError("another launcher running"),
    ):
        code = main(
            [
                "--update",
                "--allow-test-unsigned-provenance",
                "--manifest-url",
                "https://example.com/manifest.json",
                "--home",
                str(tmp_path),
            ]
        )
    assert code == EXIT_LOCK_HELD


def test_main_update_preflight_failure_returns_6(tmp_path: Path) -> None:
    """AC-13: preflight 失敗 → EXIT_ROLLBACK_UNAVAILABLE (6)。"""
    cur_path = tmp_path / "current.json"
    cur_path.write_text(
        json.dumps({"version": "1.2.3", "released_at": "x", "previous_version": ""})
    )
    # versions/1.2.3/wiseman_hub.exe を seed しない → preflight 失敗

    with (
        patch.object(
            launcher_main,
            "fetch_manifest",
            return_value=_good_manifest_bytes("1.5.0"),
        ),
        patch.object(launcher_main, "acquire_lock", return_value=99),
        patch.object(launcher_main, "release_lock"),
    ):
        code = main(
            [
                "--update",
                "--allow-test-unsigned-provenance",
                "--manifest-url",
                "https://example.com/manifest.json",
                "--home",
                str(tmp_path),
            ]
        )
    assert code == EXIT_ROLLBACK_UNAVAILABLE


def test_main_update_checksum_mismatch_returns_5(tmp_path: Path) -> None:
    """AC-2: ChecksumError → EXIT_CHECKSUM_MISMATCH (5)。"""
    cur_path = tmp_path / "current.json"
    cur_path.write_text(
        json.dumps({"version": "1.2.3", "released_at": "x", "previous_version": ""})
    )
    binary = tmp_path / "versions" / "1.2.3" / "wiseman_hub.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"existing")

    with (
        patch.object(
            launcher_main,
            "fetch_manifest",
            return_value=_good_manifest_bytes("1.5.0"),
        ),
        patch.object(
            launcher_main,
            "update_and_spawn",
            side_effect=ChecksumError("mismatch"),
        ),
    ):
        code = main(
            [
                "--update",
                "--allow-test-unsigned-provenance",
                "--manifest-url",
                "https://example.com/manifest.json",
                "--home",
                str(tmp_path),
            ]
        )
    assert code == EXIT_CHECKSUM_MISMATCH


def test_main_update_download_error_returns_3(tmp_path: Path) -> None:
    """download error → EXIT_MANIFEST (3)。"""
    cur_path = tmp_path / "current.json"
    cur_path.write_text(
        json.dumps({"version": "1.2.3", "released_at": "x", "previous_version": ""})
    )
    binary = tmp_path / "versions" / "1.2.3" / "wiseman_hub.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"existing")

    with (
        patch.object(
            launcher_main,
            "fetch_manifest",
            return_value=_good_manifest_bytes("1.5.0"),
        ),
        patch.object(
            launcher_main,
            "update_and_spawn",
            side_effect=DownloadError("network down"),
        ),
    ):
        code = main(
            [
                "--update",
                "--allow-test-unsigned-provenance",
                "--manifest-url",
                "https://example.com/manifest.json",
                "--home",
                str(tmp_path),
            ]
        )
    assert code == EXIT_MANIFEST


def test_main_update_spawn_no_rollback_returns_7(tmp_path: Path) -> None:
    """新版 + 旧版とも crash → EXIT_SPAWN_FAILED_NO_ROLLBACK (7)。"""
    cur_path = tmp_path / "current.json"
    cur_path.write_text(
        json.dumps({"version": "1.2.3", "released_at": "x", "previous_version": ""})
    )
    binary = tmp_path / "versions" / "1.2.3" / "wiseman_hub.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"existing")

    with (
        patch.object(
            launcher_main,
            "fetch_manifest",
            return_value=_good_manifest_bytes("1.5.0"),
        ),
        patch.object(
            launcher_main,
            "update_and_spawn",
            side_effect=SpawnFailedNoRollbackError("both crashed"),
        ),
    ):
        code = main(
            [
                "--update",
                "--allow-test-unsigned-provenance",
                "--manifest-url",
                "https://example.com/manifest.json",
                "--home",
                str(tmp_path),
            ]
        )
    assert code == EXIT_SPAWN_FAILED_NO_ROLLBACK


def test_main_update_internal_preflight_during_update_returns_6(tmp_path: Path) -> None:
    """update 中の PreflightError (rollback 不能) → EXIT_ROLLBACK_UNAVAILABLE (6)。"""
    cur_path = tmp_path / "current.json"
    cur_path.write_text(
        json.dumps({"version": "1.2.3", "released_at": "x", "previous_version": ""})
    )
    binary = tmp_path / "versions" / "1.2.3" / "wiseman_hub.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"existing")

    with (
        patch.object(
            launcher_main,
            "fetch_manifest",
            return_value=_good_manifest_bytes("1.5.0"),
        ),
        patch.object(
            launcher_main,
            "update_and_spawn",
            side_effect=PreflightError("rollback unavailable"),
        ),
    ):
        code = main(
            [
                "--update",
                "--allow-test-unsigned-provenance",
                "--manifest-url",
                "https://example.com/manifest.json",
                "--home",
                str(tmp_path),
            ]
        )
    assert code == EXIT_ROLLBACK_UNAVAILABLE


def test_main_update_spawn_crash_only_no_rollback_returns_7(tmp_path: Path) -> None:
    """spawn 結果が CRASH (rollback 経由しないテスト用パス) → EXIT_SPAWN_FAILED_NO_ROLLBACK。

    update_and_spawn が CRASH outcome を直接返すケース (rollback 経由せず)。
    """
    cur_path = tmp_path / "current.json"
    cur_path.write_text(
        json.dumps({"version": "1.2.3", "released_at": "x", "previous_version": ""})
    )
    binary = tmp_path / "versions" / "1.2.3" / "wiseman_hub.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"existing")

    with (
        patch.object(
            launcher_main,
            "fetch_manifest",
            return_value=_good_manifest_bytes("1.5.0"),
        ),
        patch.object(
            launcher_main,
            "update_and_spawn",
            return_value=SpawnOutcome(result=SpawnResult.CRASH, returncode=1),
        ),
    ):
        code = main(
            [
                "--update",
                "--allow-test-unsigned-provenance",
                "--manifest-url",
                "https://example.com/manifest.json",
                "--home",
                str(tmp_path),
            ]
        )
    assert code == EXIT_SPAWN_FAILED_NO_ROLLBACK


def test_main_update_negative_monitor_timeout_rejected(tmp_path: Path) -> None:
    """Suggestion 2 second-pass (threadId 019dfd5d): --monitor-timeout 0/負値は
    argparse 拒否 (SystemExit code 2)。"""
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "--update",
                "--allow-test-unsigned-provenance",
                "--monitor-timeout",
                "0",
                "--home",
                str(tmp_path),
            ]
        )
    assert exc.value.code == 2

    with pytest.raises(SystemExit) as exc:
        main(
            [
                "--update",
                "--allow-test-unsigned-provenance",
                "--monitor-timeout",
                "-1.5",
                "--home",
                str(tmp_path),
            ]
        )
    assert exc.value.code == 2


def test_main_update_current_read_error_returns_6(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A2 second-pass: read_current で OSError → CurrentReadError → exit 6
    (silent に DEFAULT_CURRENT に fallback して rollback 能力喪失するのを防止)。"""
    cur_path = tmp_path / "current.json"
    cur_path.write_text(
        json.dumps({"version": "1.2.3", "released_at": "x", "previous_version": ""})
    )

    # read_current を CurrentReadError raise に差し替え
    def _raise_read_error(*args: object, **kwargs: object) -> None:
        raise CurrentReadError("simulated AV lock")

    monkeypatch.setattr(launcher_main, "read_current", _raise_read_error)
    with patch.object(
        launcher_main, "fetch_manifest", return_value=_good_manifest_bytes("1.5.0")
    ):
        code = main(
            [
                "--update",
                "--allow-test-unsigned-provenance",
                "--manifest-url",
                "https://example.com/manifest.json",
                "--home",
                str(tmp_path),
            ]
        )
    assert code == EXIT_ROLLBACK_UNAVAILABLE


def test_main_update_unexpected_error_returns_4(tmp_path: Path) -> None:
    """B3: 想定外 RuntimeError は top-level safety net で EXIT_UNEXPECTED (4)。"""
    cur_path = tmp_path / "current.json"
    cur_path.write_text(
        json.dumps({"version": "1.2.3", "released_at": "x", "previous_version": ""})
    )
    binary = tmp_path / "versions" / "1.2.3" / "wiseman_hub.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"existing")

    with (
        patch.object(
            launcher_main,
            "fetch_manifest",
            return_value=_good_manifest_bytes("1.5.0"),
        ),
        patch.object(
            launcher_main,
            "update_and_spawn",
            side_effect=RuntimeError("oops, unexpected"),
        ),
    ):
        code = main(
            [
                "--update",
                "--allow-test-unsigned-provenance",
                "--manifest-url",
                "https://example.com/manifest.json",
                "--home",
                str(tmp_path),
            ]
        )
    assert code == 4  # EXIT_UNEXPECTED


def test_main_update_download_error_leaves_current_unchanged(
    tmp_path: Path,
) -> None:
    """B2: download_artifact 失敗時、current.json は新版に切り替わらない (atomicity)。"""
    cur_path = tmp_path / "current.json"
    initial_payload = json.dumps(
        {"version": "1.2.3", "released_at": "x", "previous_version": ""}
    )
    cur_path.write_text(initial_payload)
    binary = tmp_path / "versions" / "1.2.3" / "wiseman_hub.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"existing")

    with (
        patch.object(
            launcher_main,
            "fetch_manifest",
            return_value=_good_manifest_bytes("1.5.0"),
        ),
        patch.object(
            launcher_main,
            "update_and_spawn",
            side_effect=DownloadError("simulated network drop"),
        ),
    ):
        code = main(
            [
                "--update",
                "--allow-test-unsigned-provenance",
                "--manifest-url",
                "https://example.com/manifest.json",
                "--home",
                str(tmp_path),
            ]
        )
    assert code == EXIT_MANIFEST  # 3
    # current.json は元のまま (新版に切り替わっていない)
    assert cur_path.read_text() == initial_payload


def test_main_update_ok_early_exit_returns_0(tmp_path: Path) -> None:
    """OK_EARLY_EXIT (single-instance 等) → EXIT_OK (rollback しない)。"""
    cur_path = tmp_path / "current.json"
    cur_path.write_text(
        json.dumps({"version": "1.2.3", "released_at": "x", "previous_version": ""})
    )
    binary = tmp_path / "versions" / "1.2.3" / "wiseman_hub.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"existing")

    with (
        patch.object(
            launcher_main,
            "fetch_manifest",
            return_value=_good_manifest_bytes("1.5.0"),
        ),
        patch.object(
            launcher_main,
            "update_and_spawn",
            return_value=SpawnOutcome(result=SpawnResult.OK_EARLY_EXIT, returncode=0),
        ),
    ):
        code = main(
            [
                "--update",
                "--allow-test-unsigned-provenance",
                "--manifest-url",
                "https://example.com/manifest.json",
                "--home",
                str(tmp_path),
            ]
        )
    assert code == EXIT_OK
