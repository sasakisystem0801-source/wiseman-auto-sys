"""updater.py — wiseman_hub バイナリの download / spawn / rollback (ADR-016 PR-4)。

PR-4 で実装 (codex review threadId 019dfd43 反映後):
    - acquire_lock / release_lock: 多重起動排他 (C-2)
    - preflight: versions/{current.version}/wiseman_hub.exe 存在確認 (C-4)
    - download_artifact: HTTPS chunked + size cap + SHA-256 + atomic place (D3', I-1, I-2)
    - spawn_with_monitor: subprocess.Popen + timeout injection (D2', I-5)
    - rollback_to_previous: 旧版 spawn + 同じ monitor (I-3, I-4)
    - update_and_spawn: 主フロー (manifest → download → switch → spawn → rollback)

設計判断 (impl-plan で codex 承認済):
    - returncode != 0 のみ rollback、returncode == 0 早期終了は OK_EARLY_EXIT (D2')
    - download size cap = 300 MiB (I-1)
    - lock file = ~/wiseman-hub/launcher.lock (C-2)
    - timeout は引数注入で test 高速化 (I-5)
    - PR-6 で provenance 検証を本実装、PR-4 では呼ばない (D5、本番 update は
      `--allow-insecure-checksum-only` 必須の fail-closed)
"""

from __future__ import annotations

import contextlib
import enum
import logging
import os
import ssl
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .checksum import ChecksumError, verify_sha256
from .current import DEFAULT_CURRENT, Current, read_current, write_current_atomic
from .manifest import is_simple_semver

logger = logging.getLogger(__name__)


# I-1: download size cap (改竄 manifest や誤設定での DoS 防御)
MAX_ARTIFACT_BYTES = 300 * 1024 * 1024  # 300 MiB
_CHUNK = 1024 * 1024  # 1 MiB

# C-2: lock file の stale 判定 (mtime > 1h で強制解除)
LOCK_STALE_SEC = 3600

# D2': spawn 監視の default timeout (test では 0.05 等を渡す)
DEFAULT_SPAWN_MONITOR_SEC = 30.0

# release-prod bucket の public URL prefix (ADR-016 §1.1)
RELEASE_BUCKET_BASE = "https://storage.googleapis.com/wiseman-hub-release-prod/"


class UpdaterError(Exception):
    """updater 経路の base exception."""


class LockHeldError(UpdaterError):
    """C-2: 多重起動 (別 launcher が lock 保持中)。"""


class DownloadError(UpdaterError):
    """artifact download 失敗 (network / size cap / IO)。"""


class PreflightError(UpdaterError):
    """C-4: 初期配置不完全 / rollback 不能 (versions/X.Y.Z/ 不在等)。"""


class SpawnFailedNoRollbackError(UpdaterError):
    """I-3, I-4: 旧版 spawn も失敗 (rollback 後の業務継続不能、人間介入要)。"""


class SpawnResult(enum.Enum):
    """D2': 子プロセス起動の判定結果。"""

    SUCCESS = "success"
    """TimeoutExpired = monitor_timeout_sec 以上稼働 → 業務継続。"""

    OK_EARLY_EXIT = "ok_early_exit"
    """returncode == 0 で早期終了 (single-instance / 認証キャンセル / ユーザー閉じ)。"""

    CRASH = "crash"
    """returncode != 0 で早期終了 → rollback 対象。"""

    OS_ERROR = "os_error"
    """Popen 自体が OSError (旧版 spawn 失敗時は exit 7)。"""


@dataclass(frozen=True)
class SpawnOutcome:
    result: SpawnResult
    returncode: int | None  # SUCCESS / OS_ERROR は None、それ以外は実値


# C-2: lock --------------------------------------------------------------------


def _is_stale_lock(lock_path: Path, now: float | None = None) -> bool:
    """lock file の mtime が LOCK_STALE_SEC を超えていれば stale。"""
    try:
        mtime = lock_path.stat().st_mtime
    except OSError:
        return False
    age = (now if now is not None else time.time()) - mtime
    return age > LOCK_STALE_SEC


def acquire_lock(lock_path: Path) -> int:
    """O_CREAT | O_EXCL | O_WRONLY で lock fd を取得 (Windows でも動作)。

    既存 lock が stale (mtime > LOCK_STALE_SEC) なら unlink + 警告ログ後に再取得試行。

    Returns:
        lock の file descriptor (release_lock(fd, lock_path) で解放)

    Raises:
        LockHeldError: 別 process が active な lock を保持中、または acquire 失敗
    """
    if lock_path.exists() and _is_stale_lock(lock_path):
        logger.warning(
            "stale lock detected (mtime > %ds), removing: %s",
            LOCK_STALE_SEC,
            lock_path.name,
        )
        try:
            lock_path.unlink()
        except OSError as e:
            raise LockHeldError(
                f"stale lock removal failed: {type(e).__name__}"
            ) from e

    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as e:
        raise LockHeldError(
            f"another launcher process is running (lock={lock_path.name})"
        ) from e
    except OSError as e:
        raise LockHeldError(f"lock acquire failed: {type(e).__name__}") from e

    try:
        os.write(fd, f"{os.getpid()}\n".encode())
    except OSError:
        logger.warning("lock pid write failed (non-fatal)")
    return fd


def release_lock(fd: int, lock_path: Path) -> None:
    """acquire_lock で得た fd を解放し lock file を削除する。"""
    with contextlib.suppress(OSError):
        os.close(fd)
    try:
        lock_path.unlink(missing_ok=True)
    except OSError as e:
        logger.warning("lock release failed: %s", type(e).__name__)


# C-4: preflight ---------------------------------------------------------------


def preflight(current: Current, versions_dir: Path) -> None:
    """C-4: 業務継続可能性の事前確認。

    1. current.version が DEFAULT_CURRENT.version ("0.0.0") = 初期値
       → rollback 不能を WARN ログするが raise はしない (初回 update 自体は許可)
    2. それ以外で versions/{current.version}/wiseman_hub.exe が不在
       → PreflightError raise (caller で exit 6 ROLLBACK_UNAVAILABLE)

    seed runbook 反映は ADR-016 §2.2 (PR-5 改訂タスク、本 PR では runbook 改訂なし)。
    """
    if current.version == DEFAULT_CURRENT.version:
        logger.warning(
            "current.version is initial (%s): rollback unavailable for first update",
            DEFAULT_CURRENT.version,
        )
        return

    expected = versions_dir / current.version / "wiseman_hub.exe"
    if not expected.is_file():
        raise PreflightError(
            f"current binary missing: versions/{current.version}/wiseman_hub.exe"
        )


# Download ---------------------------------------------------------------------


def _open_https_get(url: str, *, timeout_sec: int) -> Any:  # noqa: ANN401
    """HTTPS GET 接続を開く (download stream 用)。

    Returns:
        urllib response (caller が close する)。
        型を Any にしているのは urllib の internal 型が安定 public でないため。
    """
    if not isinstance(url, str) or not url.startswith("https://"):
        raise DownloadError("artifact URL must use HTTPS scheme")
    req = urllib.request.Request(url, method="GET")
    try:
        return urllib.request.urlopen(req, timeout=timeout_sec)  # noqa: S310
    except urllib.error.HTTPError as e:
        raise DownloadError(f"artifact fetch HTTP error: {e.code}") from e
    except urllib.error.URLError as e:
        raise DownloadError(
            f"artifact fetch URL error: {type(e.reason).__name__}"
        ) from e
    except TimeoutError as e:
        raise DownloadError("artifact fetch timed out") from e
    except ssl.SSLError as e:
        raise DownloadError(f"artifact fetch SSL error: {type(e).__name__}") from e
    except (ConnectionError, OSError) as e:
        raise DownloadError(
            f"artifact fetch network error: {type(e).__name__}"
        ) from e


def _read_to_temp_with_cap(resp: Any, fd: int) -> int:  # noqa: ANN401
    """resp から fd へ chunked 書込し、累計バイト数を返す (I-1: cap)。

    fd は os.fdopen で wrap して fsync 後に close される。caller は fd を再 close しない。
    """
    total = 0
    with os.fdopen(fd, "wb") as f:
        while True:
            chunk = resp.read(_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_ARTIFACT_BYTES:
                raise DownloadError(
                    f"artifact body exceeds {MAX_ARTIFACT_BYTES} bytes"
                )
            f.write(chunk)
        f.flush()
        os.fsync(f.fileno())
    return total


def download_artifact(
    artifact_url: str,
    dest_dir: Path,
    expected_sha256: str,
    *,
    timeout_sec: int = 60,
) -> Path:
    """artifact を dest_dir に download し SHA-256 検証して atomic 配置する (D3', I-1, I-2)。

    手順:
        1. dest_dir.mkdir(parents=True, exist_ok=True)
        2. tempfile.mkstemp(dir=dest_dir) で temp 作成 (Windows 置換可、I-2)
        3. Content-Length 事前検査 (I-1)
        4. chunked write、累計バイト数が MAX_ARTIFACT_BYTES 超で中断 (I-1)
        5. verify_sha256 (定数時間比較)
        6. os.replace で {dest_dir}/wiseman_hub.exe に atomic 配置
        7. 失敗時は temp 削除

    Returns:
        配置された artifact の絶対 path

    Raises:
        DownloadError: HTTPS / size cap / IO
        ChecksumError: SHA-256 不一致
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    final_path = dest_dir / "wiseman_hub.exe"

    fd, tmp_name = tempfile.mkstemp(prefix=".artifact.", suffix=".tmp", dir=str(dest_dir))
    tmp_path = Path(tmp_name)
    fd_owned = True

    success = False
    try:
        resp = _open_https_get(artifact_url, timeout_sec=timeout_sec)
        try:
            try:
                content_length = int(resp.headers.get("Content-Length", "0") or "0")
            except (ValueError, TypeError):
                content_length = 0
            if content_length > MAX_ARTIFACT_BYTES:
                raise DownloadError(
                    f"artifact Content-Length {content_length} exceeds "
                    f"{MAX_ARTIFACT_BYTES} bytes"
                )

            _read_to_temp_with_cap(resp, fd)
            fd_owned = False  # _read_to_temp_with_cap が fd を close した
        finally:
            with contextlib.suppress(AttributeError, OSError):
                resp.close()

        if not verify_sha256(tmp_path, expected_sha256):
            raise ChecksumError(
                f"artifact SHA-256 mismatch (expected {expected_sha256[:8]}...)"
            )

        os.replace(tmp_path, final_path)
        success = True
    except OSError as e:
        if not isinstance(e, (DownloadError, ChecksumError)):
            raise DownloadError(f"artifact write error: {type(e).__name__}") from e
        raise
    finally:
        if fd_owned:
            with contextlib.suppress(OSError):
                os.close(fd)
        if not success:
            with contextlib.suppress(OSError):
                tmp_path.unlink(missing_ok=True)

    return final_path


# Spawn + monitor --------------------------------------------------------------


def spawn_with_monitor(
    binary_path: Path,
    *,
    monitor_timeout_sec: float = DEFAULT_SPAWN_MONITOR_SEC,
) -> SpawnOutcome:
    """子プロセスを起動し timeout 内の挙動で SpawnOutcome を返す (D2', I-5)。

    判定:
        - subprocess.TimeoutExpired (timeout 経過、process 継続) → SUCCESS
        - returncode == 0 (timeout 内に正常終了) → OK_EARLY_EXIT (rollback しない、C-1)
        - returncode != 0 (timeout 内に crash) → CRASH (rollback 対象)
        - Popen 自体が OSError → OS_ERROR (旧版 spawn 失敗時は exit 7)

    SUCCESS の場合、launcher は 0 で exit するため子は孤児化する。Windows では
    DETACHED_PROCESS / CREATE_NEW_PROCESS_GROUP を渡すとより明示的に切り離せるが、
    PR-4 では default 挙動 (parent exit で孤児化) で十分とする。
    """
    try:
        proc = subprocess.Popen([str(binary_path)])  # noqa: S603
    except OSError as e:
        logger.error(
            "spawn failed (OSError): %s -> %s", binary_path.name, type(e).__name__
        )
        return SpawnOutcome(result=SpawnResult.OS_ERROR, returncode=None)

    try:
        rc = proc.wait(timeout=monitor_timeout_sec)
    except subprocess.TimeoutExpired:
        return SpawnOutcome(result=SpawnResult.SUCCESS, returncode=None)

    if rc == 0:
        logger.warning(
            "child exited 0 within %.1fs (single-instance / cancel etc.); "
            "treating as OK_EARLY_EXIT, no rollback",
            monitor_timeout_sec,
        )
        return SpawnOutcome(result=SpawnResult.OK_EARLY_EXIT, returncode=0)

    logger.error("child crashed (returncode=%s) within %.1fs", rc, monitor_timeout_sec)
    return SpawnOutcome(result=SpawnResult.CRASH, returncode=rc)


# Rollback ---------------------------------------------------------------------


def rollback_to_previous(
    current_path: Path,
    versions_dir: Path,
    *,
    monitor_timeout_sec: float = DEFAULT_SPAWN_MONITOR_SEC,
) -> SpawnOutcome:
    """current.json の previous_version で旧版 spawn (I-3, I-4)。

    手順:
        1. current.json を読む
        2. previous_version が "" / non-semver → PreflightError (caller で exit 6)
        3. versions/{previous_version}/wiseman_hub.exe 不在 → PreflightError
        4. current.json を {version: previous_version, previous_version: "", ...} に
           atomic write (履歴は 1 段保持なので前々版は失念)
        5. spawn_with_monitor で旧版起動

    Returns:
        旧版起動の SpawnOutcome (caller は SUCCESS/OK_EARLY_EXIT → exit 0、
        CRASH/OS_ERROR → exit 7)。
    """
    cur = read_current(current_path)
    prev_ver = cur.previous_version
    if not prev_ver or not is_simple_semver(prev_ver):
        raise PreflightError(
            f"rollback unavailable: previous_version={prev_ver!r}"
        )

    prev_binary = versions_dir / prev_ver / "wiseman_hub.exe"
    if not prev_binary.is_file():
        raise PreflightError(
            f"rollback unavailable: versions/{prev_ver}/wiseman_hub.exe not found"
        )

    new_current = Current(
        version=prev_ver,
        released_at=cur.released_at,
        previous_version="",
    )
    write_current_atomic(current_path, new_current)
    logger.info("rolled back current.json to version=%s", prev_ver)

    return spawn_with_monitor(prev_binary, monitor_timeout_sec=monitor_timeout_sec)


# Main flow --------------------------------------------------------------------


def update_and_spawn(
    manifest: dict[str, object],
    home_dir: Path,
    *,
    monitor_timeout_sec: float = DEFAULT_SPAWN_MONITOR_SEC,
    no_spawn: bool = False,
) -> SpawnOutcome:
    """主フロー: manifest から決まる新版を download → switch → spawn → rollback。

    Args:
        manifest: validate_manifest 通過後の dict
        home_dir: $HOME/wiseman-hub (current.json + versions/ + lock の親)
        monitor_timeout_sec: spawn_with_monitor の timeout (test では小さい値)
        no_spawn: True なら download + current.json 切替まで、spawn しない (AC-6)

    Returns:
        最終的な SpawnOutcome (no_spawn=True の場合は SUCCESS sentinel)

    Raises:
        DownloadError / ChecksumError / PreflightError / SpawnFailedNoRollbackError
    """
    current_path = home_dir / "current.json"
    versions_dir = home_dir / "versions"

    cur = read_current(current_path)

    new_ver = manifest["current_version"]
    download_url = manifest["download_url"]
    checksum = manifest["checksum_sha256"]
    released_at = manifest["released_at"]
    assert isinstance(new_ver, str)  # noqa: S101 — manifest validated upstream
    assert isinstance(download_url, str)  # noqa: S101
    assert isinstance(checksum, str)  # noqa: S101
    assert isinstance(released_at, str)  # noqa: S101

    if cur.version == new_ver:
        logger.info("already at version %s, skipping download", new_ver)
        if no_spawn:
            return SpawnOutcome(result=SpawnResult.SUCCESS, returncode=None)
        existing = versions_dir / cur.version / "wiseman_hub.exe"
        if not existing.is_file():
            raise PreflightError(f"binary missing for current version: {existing.name}")
        return spawn_with_monitor(existing, monitor_timeout_sec=monitor_timeout_sec)

    new_dir = versions_dir / new_ver
    artifact_url = RELEASE_BUCKET_BASE + download_url
    new_binary = download_artifact(artifact_url, new_dir, checksum, timeout_sec=60)
    logger.info("downloaded version %s to %s", new_ver, new_binary.name)

    new_current = Current(
        version=new_ver,
        released_at=released_at,
        previous_version=cur.version if cur.version != DEFAULT_CURRENT.version else "",
    )
    write_current_atomic(current_path, new_current)
    logger.info("switched current.json to version %s", new_ver)

    if no_spawn:
        return SpawnOutcome(result=SpawnResult.SUCCESS, returncode=None)

    outcome = spawn_with_monitor(new_binary, monitor_timeout_sec=monitor_timeout_sec)

    if outcome.result in (SpawnResult.SUCCESS, SpawnResult.OK_EARLY_EXIT):
        return outcome

    logger.warning("new version spawn failed (%s), rolling back", outcome.result.value)
    rollback_outcome = rollback_to_previous(
        current_path, versions_dir, monitor_timeout_sec=monitor_timeout_sec
    )
    if rollback_outcome.result in (SpawnResult.SUCCESS, SpawnResult.OK_EARLY_EXIT):
        return rollback_outcome

    raise SpawnFailedNoRollbackError(
        f"both new ({outcome.returncode}) and previous "
        f"({rollback_outcome.returncode}) versions failed to spawn"
    )
