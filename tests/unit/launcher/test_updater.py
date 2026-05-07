"""Tests for wiseman_hub_launcher.updater (ADR-016 PR-4)。

カバレッジ範囲 (codex review threadId 019dfd43 反映):
    - C-2: lock acquire / release / stale 解除
    - C-4: preflight (initial / missing / existing)
    - D3': download_artifact (SHA-256 一致 / 不一致 / Content-Length cap / chunked cap /
            HTTPS / network error / dest_dir 自動作成)
    - D2': spawn_with_monitor (SUCCESS / OK_EARLY_EXIT / CRASH / OS_ERROR、
            timeout injection で test 高速化)
    - I-3: rollback_to_previous (basic / no previous / no binary / invalid semver /
            current.json 履歴クリア)
    - E2E: update_and_spawn (same version skip / no_spawn / full flow / checksum mismatch /
           crash → rollback success / crash → rollback also crash)
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import ssl
import time
import urllib.error
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from wiseman_hub_launcher.checksum import ChecksumError
from wiseman_hub_launcher.current import Current, write_current_atomic
from wiseman_hub_launcher.manifest import Sha256Hex, make_sha256hex
from wiseman_hub_launcher.updater import (
    DEFAULT_SPAWN_MONITOR_SEC,
    LOCK_STALE_SEC,
    MAX_ARTIFACT_BYTES,
    DownloadError,
    LockHeartbeat,
    LockHeldError,
    PreflightError,
    SpawnFailedNoRollbackError,
    SpawnOutcome,
    SpawnResult,
    acquire_lock,
    download_artifact,
    preflight,
    release_lock,
    rollback_to_previous,
    spawn_with_monitor,
    update_and_spawn,
)


@contextlib.contextmanager
def _bypass_provenance() -> Iterator[None]:
    """PR-6a: update_and_spawn 系テストで provenance verify 経路を完全 mock。

    既存 test (PR-4 由来) の SHA-256 / spawn / rollback 挙動を維持しつつ、
    本 PR-6a で追加された provenance download / claims verify / canonical URL
    検証を bypass。provenance 検証本体の test は test_provenance.py で追加。
    """
    with (
        patch("wiseman_hub_launcher.updater.verify_provenance"),
        patch("wiseman_hub_launcher.updater.download_provenance"),
        patch("wiseman_hub_launcher.updater.validate_canonical_provenance_url"),
    ):
        yield

# helpers ----------------------------------------------------------------------


def _make_response(payload: bytes, content_length: str | None = None) -> MagicMock:
    """urllib response の mock。read(n) で chunked iteration を simulate。"""
    resp = MagicMock()
    stream = io.BytesIO(payload)

    def _read(n: int = -1) -> bytes:
        return stream.read(n)

    resp.read = _read
    resp.headers = {"Content-Length": content_length or str(len(payload))}
    resp.close = MagicMock()
    return resp


def _sha256_hex(data: bytes) -> Sha256Hex:
    """Issue #209 PR2: Sha256Hex narrow + validating constructor を test fixture で exercise。"""
    return make_sha256hex(hashlib.sha256(data).hexdigest())


# C-2: lock --------------------------------------------------------------------


def test_acquire_lock_basic(tmp_path: Path) -> None:
    lock = tmp_path / "launcher.lock"
    fd = acquire_lock(lock)
    try:
        assert lock.exists()
        # pid が書かれていること
        assert str(os.getpid()).encode() in lock.read_bytes()
    finally:
        release_lock(fd, lock)


def test_acquire_lock_already_held(tmp_path: Path) -> None:
    lock = tmp_path / "launcher.lock"
    fd1 = acquire_lock(lock)
    try:
        with pytest.raises(LockHeldError, match="another launcher process"):
            acquire_lock(lock)
    finally:
        release_lock(fd1, lock)


def test_acquire_lock_stale_replaces(tmp_path: Path) -> None:
    """C-2: mtime > LOCK_STALE_SEC の lock は強制解除して再取得。"""
    lock = tmp_path / "launcher.lock"
    lock.write_text("99999\n")
    # mtime を古くする (LOCK_STALE_SEC + 100 秒前)
    old = time.time() - LOCK_STALE_SEC - 100
    os.utime(lock, (old, old))

    fd = acquire_lock(lock)
    try:
        # 再取得後の mtime は更新されている
        assert lock.stat().st_mtime > old + LOCK_STALE_SEC
    finally:
        release_lock(fd, lock)


def test_release_lock_idempotent(tmp_path: Path) -> None:
    lock = tmp_path / "launcher.lock"
    fd = acquire_lock(lock)
    release_lock(fd, lock)
    # 二度呼んでも例外は飛ばない (lock 不在でも OK)
    release_lock(fd, lock)
    assert not lock.exists()


# C-2 second-pass review (threadId 019dfd5d): LockHeartbeat -------------------


def test_lock_heartbeat_updates_mtime(tmp_path: Path) -> None:
    """C-2 second-pass: heartbeat が interval ごとに os.utime で mtime 更新。"""
    lock = tmp_path / "launcher.lock"
    lock.write_bytes(b"99999\n")
    # 古い mtime にバックデート
    old = time.time() - 100
    os.utime(lock, (old, old))

    hb = LockHeartbeat(lock, interval_sec=0.05)
    hb.start()
    time.sleep(0.18)  # 2-3 回の utime call が走る
    hb.stop()

    # mtime が old より十分新しくなっていること
    final = lock.stat().st_mtime
    assert final > old + 1.0


def test_lock_heartbeat_stop_idempotent(tmp_path: Path) -> None:
    """stop を 2 回呼んでも例外なし。"""
    lock = tmp_path / "launcher.lock"
    lock.write_bytes(b"x")
    hb = LockHeartbeat(lock, interval_sec=10.0)
    hb.start()
    hb.stop()
    hb.stop()  # no-op


def test_lock_heartbeat_start_idempotent(tmp_path: Path) -> None:
    """start を 2 回呼んでも 1 thread のみ起動。"""
    lock = tmp_path / "launcher.lock"
    lock.write_bytes(b"x")
    hb = LockHeartbeat(lock, interval_sec=10.0)
    hb.start()
    thread1 = hb._thread  # noqa: SLF001 — test 観測のため
    hb.start()  # 2 回目は no-op
    assert hb._thread is thread1  # noqa: SLF001
    hb.stop()


def test_lock_heartbeat_stops_on_missing_lock(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """heartbeat 中に lock file が消えたら error ログを出して thread が break する
    (review_team A1 second-pass: FileNotFoundError は致命的、即 break)。"""
    import logging  # noqa: PLC0415

    lock = tmp_path / "launcher.lock"
    lock.write_bytes(b"x")
    hb = LockHeartbeat(lock, interval_sec=0.03)

    with caplog.at_level(logging.WARNING, logger="wiseman_hub_launcher.updater"):
        hb.start()
        time.sleep(0.04)
        lock.unlink()  # heartbeat 進行中に削除
        time.sleep(0.20)  # 次の utime で FileNotFoundError
        hb.stop()

    assert any(
        "lock file disappeared during heartbeat" in r.message
        for r in caplog.records
    )


def test_lock_heartbeat_retries_transient_oserror(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A1 second-pass: 連続 OSError 3 回まで retry、3 回目で break。

    transient な AV / NAS blip は MAX_FAILURES (=3) 回まで heartbeat 継続。
    """
    import logging  # noqa: PLC0415

    lock = tmp_path / "launcher.lock"
    lock.write_bytes(b"x")

    call_count = {"n": 0}
    real_utime = os.utime

    def _flaky_utime(p: object, *args: object, **kwargs: object) -> None:
        call_count["n"] += 1
        # 1, 2, 3 回目で連続 OSError → 3 回目で break (max_failures=3)
        if call_count["n"] <= 3:
            raise OSError(13, "AV holding")  # PermissionError-ish
        real_utime(p, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("wiseman_hub_launcher._runtime.lock.os.utime", _flaky_utime)

    hb = LockHeartbeat(lock, interval_sec=0.02)
    with caplog.at_level(logging.WARNING, logger="wiseman_hub_launcher.updater"):
        hb.start()
        time.sleep(0.20)  # 2-3 失敗で break
        hb.stop()

    # transient retry warn が少なくとも 1 回 log されている
    assert any(
        "transient failure" in r.message for r in caplog.records
    )
    # 3 回失敗で break (consecutively) が log されている
    assert any(
        "consecutively" in r.message for r in caplog.records
    )


# C-4: preflight ---------------------------------------------------------------


def test_preflight_initial_version_warns_no_raise(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """C-4: current.version='0.0.0' は raise しないが WARN ログ。"""
    cur = Current(version="0.0.0", released_at="", previous_version="")
    with caplog.at_level("WARNING"):
        preflight(cur, tmp_path / "versions")
    assert any("rollback unavailable" in r.message for r in caplog.records)


def test_preflight_missing_binary_raises(tmp_path: Path) -> None:
    cur = Current(version="1.2.3", released_at="", previous_version="")
    with pytest.raises(PreflightError, match="current binary missing"):
        preflight(cur, tmp_path / "versions")


def test_preflight_existing_binary_ok(tmp_path: Path) -> None:
    cur = Current(version="1.2.3", released_at="", previous_version="")
    versions_dir = tmp_path / "versions"
    binary = versions_dir / "1.2.3" / "wiseman_hub.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"fake")
    preflight(cur, versions_dir)  # raise しない


# D3': download_artifact ------------------------------------------------------


def test_download_artifact_basic(tmp_path: Path) -> None:
    payload = b"binary content here"
    sha = _sha256_hex(payload)
    dest = tmp_path / "versions" / "1.2.3"

    with patch(
        "wiseman_hub_launcher._supply_chain.download.open_https_get",
        return_value=_make_response(payload),
    ):
        out = download_artifact(
            "https://example.com/wiseman_hub.exe", dest, sha
        )
    assert out == dest / "wiseman_hub.exe"
    assert out.read_bytes() == payload


def test_download_artifact_creates_dest_dir(tmp_path: Path) -> None:
    payload = b"x"
    sha = _sha256_hex(payload)
    dest = tmp_path / "versions" / "9.9.9"
    assert not dest.exists()

    with patch(
        "wiseman_hub_launcher._supply_chain.download.open_https_get",
        return_value=_make_response(payload),
    ):
        download_artifact("https://example.com/x.exe", dest, sha)
    assert dest.is_dir()


def test_download_artifact_sha256_mismatch(tmp_path: Path) -> None:
    """AC-2: SHA-256 不一致で ChecksumError、temp 削除、final 不在。"""
    payload = b"binary content"
    wrong_sha = make_sha256hex("0" * 64)
    dest = tmp_path / "versions" / "1.2.3"

    with patch(
        "wiseman_hub_launcher._supply_chain.download.open_https_get",
        return_value=_make_response(payload),
    ), pytest.raises(ChecksumError, match="SHA-256 mismatch"):
        download_artifact("https://example.com/x.exe", dest, wrong_sha)

    # final 不在
    assert not (dest / "wiseman_hub.exe").exists()
    # temp 残骸なし
    residue = list(dest.glob(".artifact.*.tmp"))
    assert residue == []


def test_download_artifact_size_cap_content_length(tmp_path: Path) -> None:
    """I-1: Content-Length が cap 超なら事前拒否。"""
    payload = b"x"
    sha = _sha256_hex(payload)
    dest = tmp_path / "versions" / "1.2.3"

    big = str(MAX_ARTIFACT_BYTES + 1)
    with patch(
        "wiseman_hub_launcher._supply_chain.download.open_https_get",
        return_value=_make_response(payload, content_length=big),
    ), pytest.raises(DownloadError, match="Content-Length"):
        download_artifact("https://example.com/x.exe", dest, sha)


def test_download_artifact_size_cap_chunked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """I-1: Content-Length 偽装でも chunked 累計で cap 超過時は中断。

    Important 5 (threadId 019dfd5d) 反映: 300MiB 確保は CI メモリを浪費するため
    monkeypatch で cap を 1KiB に縮めて検証。

    PR-6a: download_artifact が _supply_chain.download.MAX_ARTIFACT_BYTES を参照するので、
    そちらを monkeypatch する (updater.py 側の re-export 値だけ変えても効かない)。
    """
    monkeypatch.setattr(
        "wiseman_hub_launcher._supply_chain.download.MAX_ARTIFACT_BYTES", 1024
    )

    payload = b"a" * 2048  # 2KiB > 1KiB cap
    sha = _sha256_hex(payload)
    dest = tmp_path / "versions" / "1.2.3"

    # Content-Length を 0 に偽装、chunked cap で検知させる
    resp = _make_response(payload, content_length="0")
    with patch(
        "wiseman_hub_launcher._supply_chain.download.open_https_get", return_value=resp
    ), pytest.raises(DownloadError, match="exceeds"):
        download_artifact("https://example.com/x.exe", dest, sha)

    # temp 削除確認
    residue = list(dest.glob(".artifact.*.tmp"))
    assert residue == []


def test_download_artifact_https_required(tmp_path: Path) -> None:
    dest = tmp_path / "versions" / "1.2.3"
    with pytest.raises(DownloadError, match="HTTPS"):
        download_artifact("http://example.com/x.exe", dest, make_sha256hex("0" * 64))


def test_download_artifact_network_error(tmp_path: Path) -> None:
    """network error → DownloadError + temp 削除。"""
    dest = tmp_path / "versions" / "1.2.3"

    def _raise_url_error(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401, ARG001
        raise urllib.error.URLError("connection refused")

    with patch(
        "wiseman_hub_launcher._supply_chain._http.urllib.request.urlopen",
        side_effect=_raise_url_error,
    ), pytest.raises(DownloadError, match="URL error"):
        download_artifact("https://example.com/x.exe", dest, make_sha256hex("0" * 64))


def test_download_artifact_rejects_https_to_http_redirect(tmp_path: Path) -> None:
    """I-2 second-pass (threadId 019dfd5d): redirect 後 URL が HTTPS でなければ
    DownloadError ("non-HTTPS scheme")。manifest.py の redirect 防御と同等を artifact 側にも。
    """
    payload = b"x"
    sha = _sha256_hex(payload)
    dest = tmp_path / "versions" / "1.2.3"

    resp = _make_response(payload)
    resp.geturl = MagicMock(return_value="http://attacker.com/x.exe")

    with patch(
        "wiseman_hub_launcher._supply_chain._http.urllib.request.urlopen", return_value=resp
    ), pytest.raises(DownloadError, match="non-HTTPS"):
        download_artifact("https://example.com/x.exe", dest, sha)


def test_download_artifact_accepts_https_to_https_redirect(tmp_path: Path) -> None:
    """B1/C2 second-pass (threadId pr-test-analyzer): https → https の正当な
    redirect (例: GCS CDN) は許容、download 成功する。"""
    payload = b"redirected binary"
    sha = _sha256_hex(payload)
    dest = tmp_path / "versions" / "1.2.3"

    resp = _make_response(payload)
    resp.geturl = MagicMock(return_value="https://cdn.example.com/redirected/x.exe")

    with patch(
        "wiseman_hub_launcher._supply_chain._http.urllib.request.urlopen", return_value=resp
    ):
        out = download_artifact("https://example.com/x.exe", dest, sha)
    assert out == dest / "wiseman_hub.exe"
    assert out.read_bytes() == payload


def test_download_artifact_via_real_https_helper_path(tmp_path: Path) -> None:
    """B1 second-pass: happy path で open_https_get (HTTPS 検証 + redirect 検証 +
    例外正規化) を bypass せずに実呼び出し、SUCCESS path を end-to-end で検証。

    PR-7 で _open_https_get (private) → _supply_chain._http.open_https_get (public helper)
    に rename + module 移動。test 名と docstring も新名に同期 (review I-4 反映)。
    """
    payload = b"binary via real https helper"
    sha = _sha256_hex(payload)
    dest = tmp_path / "versions" / "1.2.3"

    resp = _make_response(payload)
    resp.geturl = MagicMock(return_value="https://example.com/x.exe")

    with patch(
        "wiseman_hub_launcher._supply_chain._http.urllib.request.urlopen", return_value=resp
    ):
        out = download_artifact("https://example.com/x.exe", dest, sha)
    assert out.read_bytes() == payload
    # open_https_get が close() を呼んだことを検証 (cleanup 動作確認)
    assert resp.close.called


# D2': spawn_with_monitor -----------------------------------------------------


def test_spawn_with_monitor_success_long_running(tmp_path: Path) -> None:
    """SUCCESS: TimeoutExpired (timeout 内に終了しない)。"""
    fake_proc = MagicMock()
    import subprocess  # noqa: PLC0415 — local import for monkeypatch scope

    fake_proc.wait.side_effect = subprocess.TimeoutExpired(cmd="x", timeout=0.05)

    binary = tmp_path / "wiseman_hub.exe"
    binary.write_bytes(b"fake")

    with patch(
        "wiseman_hub_launcher._runtime.spawn.subprocess.Popen", return_value=fake_proc
    ):
        out = spawn_with_monitor(binary, monitor_timeout_sec=0.05)
    assert out.result == SpawnResult.SUCCESS
    assert out.returncode is None


def test_spawn_with_monitor_early_zero_exit_no_rollback(tmp_path: Path) -> None:
    """C-1: returncode==0 早期終了は OK_EARLY_EXIT (rollback しない)。"""
    fake_proc = MagicMock()
    fake_proc.wait.return_value = 0

    binary = tmp_path / "wiseman_hub.exe"
    binary.write_bytes(b"fake")

    with patch(
        "wiseman_hub_launcher._runtime.spawn.subprocess.Popen", return_value=fake_proc
    ):
        out = spawn_with_monitor(binary, monitor_timeout_sec=0.05)
    assert out.result == SpawnResult.OK_EARLY_EXIT
    assert out.returncode == 0


def test_spawn_with_monitor_crash(tmp_path: Path) -> None:
    """returncode != 0 → CRASH。"""
    fake_proc = MagicMock()
    fake_proc.wait.return_value = 1

    binary = tmp_path / "wiseman_hub.exe"
    binary.write_bytes(b"fake")

    with patch(
        "wiseman_hub_launcher._runtime.spawn.subprocess.Popen", return_value=fake_proc
    ):
        out = spawn_with_monitor(binary, monitor_timeout_sec=0.05)
    assert out.result == SpawnResult.CRASH
    assert out.returncode == 1


def test_spawn_with_monitor_os_error(tmp_path: Path) -> None:
    """I-4: Popen 自体が OSError → OS_ERROR。"""
    binary = tmp_path / "missing.exe"

    with patch(
        "wiseman_hub_launcher._runtime.spawn.subprocess.Popen",
        side_effect=OSError("no such file"),
    ):
        out = spawn_with_monitor(binary, monitor_timeout_sec=0.05)
    assert out.result == SpawnResult.OS_ERROR
    assert out.returncode is None


# rollback ---------------------------------------------------------------------


def _setup_versions(tmp_path: Path, *versions: str) -> Path:
    """versions/X.Y.Z/wiseman_hub.exe を seed する。"""
    versions_dir = tmp_path / "versions"
    for v in versions:
        d = versions_dir / v
        d.mkdir(parents=True, exist_ok=True)
        (d / "wiseman_hub.exe").write_bytes(b"fake")
    return versions_dir


def test_rollback_to_previous_basic(tmp_path: Path) -> None:
    """previous_version + binary あり → 旧版 spawn (SUCCESS)。"""
    versions_dir = _setup_versions(tmp_path, "1.2.2", "1.2.3")
    cur_path = tmp_path / "current.json"
    write_current_atomic(
        cur_path,
        Current(version="1.2.3", released_at="x", previous_version="1.2.2"),
    )

    fake_proc = MagicMock()
    import subprocess  # noqa: PLC0415

    fake_proc.wait.side_effect = subprocess.TimeoutExpired(cmd="x", timeout=0.05)

    with patch(
        "wiseman_hub_launcher._runtime.spawn.subprocess.Popen", return_value=fake_proc
    ):
        out = rollback_to_previous(cur_path, versions_dir, monitor_timeout_sec=0.05)
    assert out.result == SpawnResult.SUCCESS

    # current.json は previous_version="1.2.2" に書き換わり、履歴は失念
    parsed = json.loads(cur_path.read_text())
    assert parsed["version"] == "1.2.2"
    assert parsed["previous_version"] == ""


def test_rollback_to_previous_no_previous(tmp_path: Path) -> None:
    """previous_version="" → PreflightError (rollback 不能)。"""
    versions_dir = _setup_versions(tmp_path, "1.2.3")
    cur_path = tmp_path / "current.json"
    write_current_atomic(
        cur_path,
        Current(version="1.2.3", released_at="x", previous_version=""),
    )
    with pytest.raises(PreflightError, match="rollback unavailable"):
        rollback_to_previous(cur_path, versions_dir)


def test_rollback_to_previous_no_binary(tmp_path: Path) -> None:
    """previous_version あるが binary 不在 → PreflightError。"""
    versions_dir = _setup_versions(tmp_path, "1.2.3")  # 1.2.2 は seed しない
    cur_path = tmp_path / "current.json"
    write_current_atomic(
        cur_path,
        Current(version="1.2.3", released_at="x", previous_version="1.2.2"),
    )
    with pytest.raises(PreflightError, match="not found"):
        rollback_to_previous(cur_path, versions_dir)


def test_rollback_to_previous_non_semver(tmp_path: Path) -> None:
    """previous_version が semver 不正 → PreflightError。

    注: read_current が previous_version を semver 検証するため通常はここに到達しない
    (corrupt JSON は quarantine + DEFAULT)。本テストは defensive guard を直接検証。
    """
    versions_dir = _setup_versions(tmp_path, "1.2.3")
    cur_path = tmp_path / "current.json"
    # write_current_atomic は invariant を信頼するので、garbage を直接書く
    cur_path.write_text(
        json.dumps(
            {
                "version": "1.2.3",
                "released_at": "x",
                "previous_version": "garbage",
            }
        )
    )
    # read_current が quarantine するので DEFAULT_CURRENT が返る → previous_version=""
    # → 結果として PreflightError "rollback unavailable: previous_version=''"
    with pytest.raises(PreflightError, match="rollback unavailable"):
        rollback_to_previous(cur_path, versions_dir)


# update_and_spawn (E2E) -------------------------------------------------------


def _good_manifest(version: str = "1.2.3", checksum: str | None = None) -> dict[str, Any]:
    return {
        "current_version": version,
        "minimum_version": "1.0.0",
        "download_url": f"versions/{version}/wiseman_hub.exe",
        "checksum_sha256": checksum or ("a" * 64),
        "commit_sha": "f976b44",
        "built_at": "2026-05-06T12:00:00Z",
        "released_at": "2026-05-06T13:00:00Z",
        # PR-6a (T0 Explore + codex C-1): canonical = download_url + ".sigstore.json"
        "provenance_url": f"versions/{version}/wiseman_hub.exe.sigstore.json",
        # PR-6a: expected_repo / expected_workflow_ref 必須化
        "expected_repo": "sasakisystem0801-source/wiseman-auto-sys",
        "expected_workflow_ref": f".github/workflows/release.yml@refs/tags/v{version}",
    }


def test_update_and_spawn_uses_explicit_current_path(tmp_path: Path) -> None:
    """I-1 second-pass (threadId 019dfd5d): current_path 引数で home_dir 外の
    current.json を使うケース (canary/test override)。"""
    custom_current = tmp_path / "elsewhere" / "custom_current.json"
    custom_current.parent.mkdir()
    write_current_atomic(
        custom_current,
        Current(version="1.2.3", released_at="x", previous_version=""),
    )
    _setup_versions(tmp_path, "1.2.3")

    fake_proc = MagicMock()
    import subprocess  # noqa: PLC0415

    fake_proc.wait.side_effect = subprocess.TimeoutExpired(cmd="x", timeout=0.05)

    with _bypass_provenance(), patch(
        "wiseman_hub_launcher._runtime.spawn.subprocess.Popen", return_value=fake_proc
    ):
        out = update_and_spawn(
            _good_manifest("1.2.3"),
            tmp_path,
            current_path=custom_current,
            monitor_timeout_sec=0.05,
        )
    assert out.result == SpawnResult.SUCCESS


def test_update_and_spawn_same_version_skips_download(tmp_path: Path) -> None:
    """AC-4: manifest 同版 → download skip、既存版 spawn。"""
    _setup_versions(tmp_path, "1.2.3")
    cur_path = tmp_path / "current.json"
    write_current_atomic(
        cur_path, Current(version="1.2.3", released_at="x", previous_version="")
    )

    fake_proc = MagicMock()
    import subprocess  # noqa: PLC0415

    fake_proc.wait.side_effect = subprocess.TimeoutExpired(cmd="x", timeout=0.05)

    with _bypass_provenance(), patch(
        "wiseman_hub_launcher._runtime.spawn.subprocess.Popen", return_value=fake_proc
    ), patch("wiseman_hub_launcher.updater.download_artifact") as dl:
        out = update_and_spawn(
            _good_manifest("1.2.3"), tmp_path, monitor_timeout_sec=0.05
        )
    assert out.result == SpawnResult.SUCCESS
    dl.assert_not_called()


def test_update_and_spawn_no_spawn_returns_success(tmp_path: Path) -> None:
    """AC-6: --no-spawn は download + 切替まで、spawn しない。"""
    payload = b"new binary"
    sha = _sha256_hex(payload)
    cur_path = tmp_path / "current.json"
    write_current_atomic(
        cur_path, Current(version="1.0.0", released_at="x", previous_version="")
    )

    with _bypass_provenance(), patch(
        "wiseman_hub_launcher._supply_chain.download.open_https_get",
        return_value=_make_response(payload),
    ), patch(
        "wiseman_hub_launcher._runtime.spawn.subprocess.Popen"
    ) as popen_mock:
        out = update_and_spawn(
            _good_manifest("1.2.3", sha),
            tmp_path,
            monitor_timeout_sec=0.05,
            no_spawn=True,
        )
    assert out.result == SpawnResult.SUCCESS
    popen_mock.assert_not_called()
    # current.json は新版に切替済
    parsed = json.loads(cur_path.read_text())
    assert parsed["version"] == "1.2.3"
    assert parsed["previous_version"] == "1.0.0"
    # binary も配置済
    assert (tmp_path / "versions" / "1.2.3" / "wiseman_hub.exe").exists()


def test_update_and_spawn_emits_phase_log_failure_fingerprint(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """PR-7 review C-2 反映: download 失敗時に download_failed fingerprint が出る。

    silent-failure-hunter Critical C-2: success path のみ phase log 出力では
    triage で「どこで止まったか」が不明。失敗 phase でも fingerprint 必須。
    """
    cur_path = tmp_path / "current.json"
    write_current_atomic(
        cur_path, Current(version="1.0.0", released_at="x", previous_version="")
    )
    # checksum 不一致を発生させる payload
    payload = b"new binary"
    wrong_sha = make_sha256hex("0" * 64)

    caplog.set_level("INFO", logger="wiseman_hub_launcher.updater")
    with (
        _bypass_provenance(),
        patch(
            "wiseman_hub_launcher._supply_chain.download.open_https_get",
            return_value=_make_response(payload),
        ),
        pytest.raises(ChecksumError),
    ):
        update_and_spawn(
            _good_manifest("1.2.3", wrong_sha), tmp_path, monitor_timeout_sec=0.05
        )

    phase_logs = [r.message for r in caplog.records if "launcher_phase" in r.message]
    # download_start 後に download_failed が必ず出る
    assert any('"phase": "download_start"' in m for m in phase_logs)
    assert any(
        '"phase": "download_failed"' in m and '"error_class": "ChecksumError"' in m
        for m in phase_logs
    ), f"missing download_failed fingerprint with ChecksumError (records: {phase_logs!r})"
    # download_complete は出ない (失敗のため)
    assert not any('"phase": "download_complete"' in m for m in phase_logs)


def test_update_and_spawn_emits_phase_log_fingerprints(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """PR-7 AC5: update_and_spawn 各 phase で構造化 JSON 1 行 log が出る。

    silent-failure 残対応: 失敗時に「どこで止まったか」を機械可読化。
    expected phase: read_current / download_start / download_complete /
    current_switched / spawn_start / spawn_complete (or rollback_start)。
    """
    payload = b"new binary for log fingerprint test"
    sha = _sha256_hex(payload)
    cur_path = tmp_path / "current.json"
    write_current_atomic(
        cur_path, Current(version="1.0.0", released_at="x", previous_version="")
    )

    fake_proc = MagicMock()
    import subprocess  # noqa: PLC0415

    fake_proc.wait.side_effect = subprocess.TimeoutExpired(cmd="x", timeout=0.05)

    caplog.set_level("INFO", logger="wiseman_hub_launcher.updater")
    with _bypass_provenance(), patch(
        "wiseman_hub_launcher._supply_chain.download.open_https_get",
        return_value=_make_response(payload),
    ), patch(
        "wiseman_hub_launcher._runtime.spawn.subprocess.Popen", return_value=fake_proc
    ):
        update_and_spawn(
            _good_manifest("1.2.3", sha), tmp_path, monitor_timeout_sec=0.05
        )

    phase_logs = [r.message for r in caplog.records if "launcher_phase" in r.message]
    expected_phases = (
        "read_current",
        "download_start",
        "download_complete",
        "current_switched",
        "spawn_start",
        "spawn_complete",
    )
    for expected in expected_phases:
        # JSON 1 行に phase=<name> を含む
        assert any(
            f'"phase": "{expected}"' in m for m in phase_logs
        ), f"missing phase log: {expected} (records: {phase_logs!r})"
    # version も log に乗ること (triage 用)
    assert any('"new_version": "1.2.3"' in m for m in phase_logs)


@pytest.mark.parametrize(
    ("urlopen_side_effect", "expected_substr"),
    [
        # PR-7 review C-3 反映: tautology から実装の例外マッピング検証へ。
        # _supply_chain/_http.py:50-72 の 6 系統 except が DownloadError 文字列に
        # 「kind を区別する固有 prefix」を載せていることを実 raise で検証。
        # 1. HTTPError → "fetch HTTP error: <code>"
        (
            urllib.error.HTTPError(
                url="https://x", code=503, msg="Service Unavailable", hdrs=None, fp=None  # type: ignore[arg-type]
            ),
            "fetch HTTP error: 503",
        ),
        # 2. URLError(ConnectionRefusedError) → "fetch URL error: <reason class>"
        (
            urllib.error.URLError(reason=ConnectionRefusedError("conn refused")),
            "fetch URL error: ConnectionRefusedError",
        ),
        # 3. TimeoutError → "fetch timed out"
        (TimeoutError("timed out"), "fetch timed out"),
        # 4. SSLError → "fetch SSL error: <type name>"
        (ssl.SSLError("CERTIFICATE_VERIFY_FAILED"), "fetch SSL error: SSLError"),
        # 5. ConnectionError → "fetch network error: <type name>"
        (
            ConnectionResetError("conn reset"),
            "fetch network error: ConnectionResetError",
        ),
    ],
)
def test_download_error_message_categorized_by_actual_exception(
    tmp_path: Path,
    urlopen_side_effect: BaseException,
    expected_substr: str,
) -> None:
    """PR-7 AC6 + review C-3 反映: DownloadError message で網羅的に kind 区別可能。

    実際に urlopen が各種例外を raise したときに、_supply_chain/_http.py の
    open_https_get() を経由して DownloadError として正規化され、message text に
    triage 用の固有 prefix が乗ることを検証。前バージョンは DownloadError(s)
    round-trip だけ検証する tautology だったので、本 PR で実装挙動検証に変更。
    """
    with patch(
        "wiseman_hub_launcher._supply_chain._http.urllib.request.urlopen",
        side_effect=urlopen_side_effect,
    ), pytest.raises(DownloadError) as exc_info:
        download_artifact("https://example.invalid/x.exe", tmp_path, make_sha256hex("0" * 64), timeout_sec=1)

    assert expected_substr in str(exc_info.value)


def test_download_error_size_cap_message_categorized(tmp_path: Path) -> None:
    """PR-7 AC6: artifact body size cap 超過時の message に 'exceeds' prefix。"""
    # 1 MiB chunked stream で MAX_ARTIFACT_BYTES (300 MiB) を超えるシナリオは
    # test 時間がかかるので、Content-Length header で先制 reject される経路を検証。
    resp = MagicMock()
    resp.read = MagicMock(return_value=b"")
    resp.headers = {"Content-Length": str(MAX_ARTIFACT_BYTES + 1)}
    resp.close = MagicMock()
    resp.geturl = MagicMock(return_value="https://example.invalid/x.exe")

    with patch(
        "wiseman_hub_launcher._supply_chain._http.urllib.request.urlopen",
        return_value=resp,
    ), pytest.raises(DownloadError, match="exceeds"):
        download_artifact("https://example.invalid/x.exe", tmp_path, make_sha256hex("0" * 64), timeout_sec=1)


def test_update_and_spawn_invokes_verify_provenance(tmp_path: Path) -> None:
    """PR-7 AC4: update_and_spawn が verify_provenance を実際に呼ぶことを確認 (integration)。

    既存 test は _bypass_provenance で 3 関数を patch するだけで、updater が
    本当に verify_provenance を呼んでいるか保証していなかった。本 test は
    download/canonical URL は bypass、verify_provenance のみ spy で呼出回数 + 引数を検証。
    """
    payload = b"new binary for integration test"
    sha = _sha256_hex(payload)
    cur_path = tmp_path / "current.json"
    write_current_atomic(
        cur_path, Current(version="1.0.0", released_at="x", previous_version="")
    )

    fake_proc = MagicMock()
    import subprocess  # noqa: PLC0415

    fake_proc.wait.side_effect = subprocess.TimeoutExpired(cmd="x", timeout=0.05)

    with patch(
        "wiseman_hub_launcher.updater.verify_provenance"
    ) as mock_verify, patch(
        "wiseman_hub_launcher.updater.download_provenance"
    ), patch(
        "wiseman_hub_launcher.updater.validate_canonical_provenance_url"
    ), patch(
        "wiseman_hub_launcher._supply_chain.download.open_https_get",
        return_value=_make_response(payload),
    ), patch(
        "wiseman_hub_launcher._runtime.spawn.subprocess.Popen", return_value=fake_proc
    ):
        update_and_spawn(
            _good_manifest("1.2.3", sha),
            tmp_path,
            monitor_timeout_sec=0.05,
        )

    # AC4: update_and_spawn から verify_provenance が確かに呼ばれた
    assert mock_verify.call_count == 1
    # 呼出引数: artifact_path / provenance_path / expected_sha256 / expected_version
    # PR-6 後半: bypass 引数完全削除、signature 検証は sigstore-python 委譲で default 有効
    call = mock_verify.call_args
    assert call.kwargs.get("expected_sha256") == sha
    assert call.kwargs.get("expected_version") == "1.2.3"


def test_update_and_spawn_full_flow_success(tmp_path: Path) -> None:
    """AC-1: download → switch → spawn 30s 経過 → SUCCESS。"""
    payload = b"new binary"
    sha = _sha256_hex(payload)
    cur_path = tmp_path / "current.json"
    write_current_atomic(
        cur_path, Current(version="1.0.0", released_at="x", previous_version="")
    )

    fake_proc = MagicMock()
    import subprocess  # noqa: PLC0415

    fake_proc.wait.side_effect = subprocess.TimeoutExpired(cmd="x", timeout=0.05)

    with _bypass_provenance(), patch(
        "wiseman_hub_launcher._supply_chain.download.open_https_get",
        return_value=_make_response(payload),
    ), patch(
        "wiseman_hub_launcher._runtime.spawn.subprocess.Popen", return_value=fake_proc
    ):
        out = update_and_spawn(
            _good_manifest("1.2.3", sha), tmp_path, monitor_timeout_sec=0.05
        )
    assert out.result == SpawnResult.SUCCESS

    parsed = json.loads(cur_path.read_text())
    assert parsed["version"] == "1.2.3"
    assert parsed["previous_version"] == "1.0.0"


def test_update_and_spawn_checksum_mismatch_no_switch(tmp_path: Path) -> None:
    """AC-2: SHA-256 不一致 → ChecksumError、current.json 切替なし。"""
    payload = b"new binary"
    wrong_sha = make_sha256hex("0" * 64)
    cur_path = tmp_path / "current.json"
    write_current_atomic(
        cur_path, Current(version="1.0.0", released_at="x", previous_version="")
    )

    with _bypass_provenance(), patch(
        "wiseman_hub_launcher._supply_chain.download.open_https_get",
        return_value=_make_response(payload),
    ), pytest.raises(ChecksumError):
        update_and_spawn(
            _good_manifest("1.2.3", wrong_sha), tmp_path, monitor_timeout_sec=0.05
        )

    # current.json 切替なし
    parsed = json.loads(cur_path.read_text())
    assert parsed["version"] == "1.0.0"


def test_update_and_spawn_crash_then_rollback_success(tmp_path: Path) -> None:
    """AC-3: 新版 crash → rollback → 旧版 spawn 成功 → SUCCESS。"""
    payload = b"new binary"
    sha = _sha256_hex(payload)

    _setup_versions(tmp_path, "1.0.0")  # 旧版を seed
    cur_path = tmp_path / "current.json"
    write_current_atomic(
        cur_path, Current(version="1.0.0", released_at="x", previous_version="")
    )

    fake_proc_crash = MagicMock()
    fake_proc_crash.wait.return_value = 1  # 新版 crash

    fake_proc_rollback = MagicMock()
    import subprocess  # noqa: PLC0415

    fake_proc_rollback.wait.side_effect = subprocess.TimeoutExpired(
        cmd="x", timeout=0.05
    )

    popen_calls = [fake_proc_crash, fake_proc_rollback]
    with _bypass_provenance(), patch(
        "wiseman_hub_launcher._supply_chain.download.open_https_get",
        return_value=_make_response(payload),
    ), patch(
        "wiseman_hub_launcher._runtime.spawn.subprocess.Popen",
        side_effect=lambda *a, **kw: popen_calls.pop(0),  # noqa: ARG005
    ):
        out = update_and_spawn(
            _good_manifest("1.2.3", sha), tmp_path, monitor_timeout_sec=0.05
        )
    assert out.result == SpawnResult.SUCCESS

    # rollback 後は version=1.0.0、previous=""
    parsed = json.loads(cur_path.read_text())
    assert parsed["version"] == "1.0.0"
    assert parsed["previous_version"] == ""


def test_update_and_spawn_crash_then_rollback_also_crashes(tmp_path: Path) -> None:
    """新版 + 旧版とも crash → SpawnFailedNoRollbackError (caller で exit 7)。"""
    payload = b"new binary"
    sha = _sha256_hex(payload)
    _setup_versions(tmp_path, "1.0.0")
    cur_path = tmp_path / "current.json"
    write_current_atomic(
        cur_path, Current(version="1.0.0", released_at="x", previous_version="")
    )

    fake_new = MagicMock()
    fake_new.wait.return_value = 1
    fake_old = MagicMock()
    fake_old.wait.return_value = 9
    popen_calls = [fake_new, fake_old]

    with _bypass_provenance(), patch(
        "wiseman_hub_launcher._supply_chain.download.open_https_get",
        return_value=_make_response(payload),
    ), patch(
        "wiseman_hub_launcher._runtime.spawn.subprocess.Popen",
        side_effect=lambda *a, **kw: popen_calls.pop(0),  # noqa: ARG005
    ), pytest.raises(SpawnFailedNoRollbackError, match="both new"):
        update_and_spawn(
            _good_manifest("1.2.3", sha), tmp_path, monitor_timeout_sec=0.05
        )


def test_update_and_spawn_crash_with_no_previous_raises_preflight(
    tmp_path: Path,
) -> None:
    """新版 crash + previous_version="" (初回 update) → PreflightError → caller で exit 6。"""
    payload = b"new binary"
    sha = _sha256_hex(payload)
    cur_path = tmp_path / "current.json"
    # current.version="0.0.0" (初期値) で update 開始 → previous_version="" の状態
    # 実装上 cur.version != "0.0.0" でないと previous_version は "" のまま
    # ここでは current.version="0.0.0" → 新版 download → 切替後 previous_version=""
    write_current_atomic(
        cur_path, Current(version="0.0.0", released_at="", previous_version="")
    )

    fake_new = MagicMock()
    fake_new.wait.return_value = 1  # 新版 crash

    with _bypass_provenance(), patch(
        "wiseman_hub_launcher._supply_chain.download.open_https_get",
        return_value=_make_response(payload),
    ), patch(
        "wiseman_hub_launcher._runtime.spawn.subprocess.Popen", return_value=fake_new
    ), pytest.raises(PreflightError, match="rollback unavailable"):
        update_and_spawn(
            _good_manifest("1.2.3", sha), tmp_path, monitor_timeout_sec=0.05
        )


# misc -------------------------------------------------------------------------


def test_default_spawn_monitor_sec_is_30() -> None:
    """ADR-016 §2 起動フロー 7「30 秒以内 crash → rollback」と整合。"""
    assert DEFAULT_SPAWN_MONITOR_SEC == 30.0


def test_spawn_outcome_is_frozen() -> None:
    out = SpawnOutcome(result=SpawnResult.SUCCESS, returncode=None)
    with pytest.raises((AttributeError, Exception)):  # frozen dataclass
        out.returncode = 99  # type: ignore[misc]
