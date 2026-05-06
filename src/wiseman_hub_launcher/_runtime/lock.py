"""C-2 多重起動排他: O_CREAT|O_EXCL lock + heartbeat (ADR-016 PR-4 → PR-6a で分離)。

PR-4 までの `updater.py` から分離 (PR-6a / codex C-3 反映、`_runtime/` subpackage)。

設計判断 (PR-4 codex review threadId 019dfd43 / 019dfd5d 反映):
    - O_CREAT|O_EXCL|O_WRONLY で Windows でも動く atomic creation
    - mtime > LOCK_STALE_SEC で stale 強制解除
    - LockHeartbeat で long-running download 中の自己 stale 化防止
    - heartbeat の OSError は MAX_FAILURES (3) まで retry、FileNotFoundError は即 break
    - PR-6a (codex Important I-3 review_team A4 second-pass): context manager 化
"""

from __future__ import annotations

import contextlib
import logging
import os
import threading
import time
from pathlib import Path
from types import TracebackType

logger = logging.getLogger(__name__)


# C-2: lock file の stale 判定 (mtime > 1h で強制解除)
LOCK_STALE_SEC = 3600
# C-2 second-pass review (threadId 019dfd5d): heartbeat で長時間 download 中の
# 自己 stale 化を防止 (60s 間隔で os.utime、stale 判定の 1/60)
LOCK_HEARTBEAT_SEC = 60.0


class LockHeldError(Exception):
    """C-2: 多重起動 (別 launcher が lock 保持中)。"""


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
        except FileNotFoundError:
            # Suggestion 1 (threadId 019dfd5d): 並行 stale 削除で他 process が
            # 先に unlink 済の場合は無視して acquire へ進む
            pass
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
    except OSError as e:
        # silent-failure HIGH 4 反映: errno を log に残して debugging 可能化
        # (pid write 失敗は lock 取得自体は成功なので非 fatal、ただし「誰が lock を
        # 握っているか」の特定が困難になるため errno は必須)
        logger.warning(
            "lock pid write failed (non-fatal): %s errno=%s",
            type(e).__name__,
            e.errno,
        )
    return fd


def release_lock(fd: int, lock_path: Path) -> None:
    """acquire_lock で得た fd を解放し lock file を削除する。"""
    with contextlib.suppress(OSError):
        os.close(fd)
    try:
        lock_path.unlink(missing_ok=True)
    except OSError as e:
        logger.warning("lock release failed: %s", type(e).__name__)


class LockHeartbeat:
    """C-2 second-pass review (threadId 019dfd5d): lock 保持中の long-running
    download で mtime を定期更新し、自己 stale 化 (LOCK_STALE_SEC 超で他 process に
    「stale」扱いされる) を防ぐ daemon thread。

    PR-6a (codex review_team Important type-design): context manager 化。

    Usage:
        with LockHeartbeat(lock_path):
            # long-running operation
            ...
        # 後方互換 (start/stop 直接呼び出し):
        hb = LockHeartbeat(lock_path)
        hb.start()
        try:
            ...
        finally:
            hb.stop()
    """

    def __init__(
        self,
        lock_path: Path,
        interval_sec: float = LOCK_HEARTBEAT_SEC,
    ) -> None:
        self._path = lock_path
        self._interval = interval_sec
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="lock-heartbeat", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        # review_team A1 second-pass (silent-failure C3): 1 回の OSError で break
        # すると lock が stale 化し、並行 update で current.json + binary 破壊リスク。
        # transient (AV / NAS blip) は MAX_FAILURES まで retry、致命的 (file 消失)
        # は即 break。
        max_failures = 3
        consecutive_failures = 0
        while not self._stop.wait(self._interval):
            try:
                os.utime(self._path)
                consecutive_failures = 0
            except FileNotFoundError as e:
                logger.error(
                    "lock file disappeared during heartbeat (%s); aborting",
                    type(e).__name__,
                )
                break
            except OSError as e:
                consecutive_failures += 1
                if consecutive_failures >= max_failures:
                    logger.error(
                        "lock heartbeat failed %d/%d consecutively (%s errno=%s); "
                        "aborting heartbeat — lock will become stale",
                        consecutive_failures,
                        max_failures,
                        type(e).__name__,
                        e.errno,
                    )
                    break
                logger.warning(
                    "lock heartbeat utime transient failure (%d/%d): %s errno=%s",
                    consecutive_failures,
                    max_failures,
                    type(e).__name__,
                    e.errno,
                )

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def __enter__(self) -> LockHeartbeat:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.stop()
