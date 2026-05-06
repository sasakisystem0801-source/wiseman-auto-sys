"""D2' 子プロセス起動 + 4 状態判定 (ADR-016 PR-4 → PR-6a で分離)。

PR-6a (codex review_team type-design Critical): SpawnOutcome を factory classmethods
で生成、invariant violation は __post_init__ で raise。
"""

from __future__ import annotations

import enum
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


# D2': spawn 監視の default timeout (test では 0.05 等を渡す)
DEFAULT_SPAWN_MONITOR_SEC = 30.0


class SpawnFailedNoRollbackError(Exception):
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


# rollback 候補ではない結果集合の実体化
NON_ROLLBACK_RESULTS: frozenset[SpawnResult] = frozenset(
    {SpawnResult.SUCCESS, SpawnResult.OK_EARLY_EXIT}
)


@dataclass(frozen=True)
class SpawnOutcome:
    """spawn 結果 + invariant 強制 (PR-6a codex type-design Critical)。

    factory classmethods (success / crash / os_error / ok_early_exit) で生成すること。
    直接 `SpawnOutcome(result=..., returncode=...)` で生成しても、__post_init__ が
    invalid combo を ValueError で reject する。

    Invariant:
        - SUCCESS: returncode is None
        - OK_EARLY_EXIT: returncode == 0
        - CRASH: returncode is int and != 0
        - OS_ERROR: returncode is None
    """

    result: SpawnResult
    returncode: int | None  # SUCCESS / OS_ERROR は None、それ以外は実値

    def __post_init__(self) -> None:
        rc = self.returncode
        if self.result is SpawnResult.SUCCESS and rc is not None:
            raise ValueError(f"SUCCESS requires returncode=None, got {rc!r}")
        if self.result is SpawnResult.OK_EARLY_EXIT and rc != 0:
            raise ValueError(f"OK_EARLY_EXIT requires returncode=0, got {rc!r}")
        if self.result is SpawnResult.CRASH and (rc is None or rc == 0):
            raise ValueError(f"CRASH requires returncode!=0 int, got {rc!r}")
        if self.result is SpawnResult.OS_ERROR and rc is not None:
            raise ValueError(f"OS_ERROR requires returncode=None, got {rc!r}")

    @classmethod
    def success(cls) -> SpawnOutcome:
        return cls(result=SpawnResult.SUCCESS, returncode=None)

    @classmethod
    def ok_early_exit(cls) -> SpawnOutcome:
        return cls(result=SpawnResult.OK_EARLY_EXIT, returncode=0)

    @classmethod
    def crash(cls, rc: int) -> SpawnOutcome:
        if rc == 0:
            raise ValueError(f"crash() requires non-zero returncode, got {rc!r}")
        return cls(result=SpawnResult.CRASH, returncode=rc)

    @classmethod
    def os_error(cls) -> SpawnOutcome:
        return cls(result=SpawnResult.OS_ERROR, returncode=None)

    def is_rollback_candidate(self) -> bool:
        """rollback 対象 (CRASH / OS_ERROR) なら True。"""
        return self.result not in NON_ROLLBACK_RESULTS


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
        return SpawnOutcome.os_error()

    try:
        rc = proc.wait(timeout=monitor_timeout_sec)
    except subprocess.TimeoutExpired:
        return SpawnOutcome.success()

    if rc == 0:
        logger.warning(
            "child exited 0 within %.1fs (single-instance / cancel etc.); "
            "treating as OK_EARLY_EXIT, no rollback",
            monitor_timeout_sec,
        )
        return SpawnOutcome.ok_early_exit()

    logger.error("child crashed (returncode=%s) within %.1fs", rc, monitor_timeout_sec)
    return SpawnOutcome.crash(rc)
