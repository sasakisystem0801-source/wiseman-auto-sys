"""runtime subpackage — lock + spawn (ADR-016 PR-6a で updater.py から分離)。

constraint: ADR-016 §1.2 で `_runtime/` ≤ 250 LOC。
"""

from __future__ import annotations

from .lock import (
    LOCK_HEARTBEAT_SEC,
    LOCK_STALE_SEC,
    LockHeartbeat,
    LockHeldError,
    acquire_lock,
    release_lock,
)
from .spawn import (
    DEFAULT_SPAWN_MONITOR_SEC,
    SpawnFailedNoRollbackError,
    SpawnOutcome,
    SpawnResult,
    spawn_with_monitor,
)

__all__ = [
    "DEFAULT_SPAWN_MONITOR_SEC",
    "LOCK_HEARTBEAT_SEC",
    "LOCK_STALE_SEC",
    "LockHeartbeat",
    "LockHeldError",
    "SpawnFailedNoRollbackError",
    "SpawnOutcome",
    "SpawnResult",
    "acquire_lock",
    "release_lock",
    "spawn_with_monitor",
]
