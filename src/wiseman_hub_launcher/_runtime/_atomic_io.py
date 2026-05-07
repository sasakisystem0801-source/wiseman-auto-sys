"""atomic file replace + directory fsync helper (PR-7、code-simplifier I-2 反映)。

PR-3 / PR-4 までは ``current.write_current_atomic`` と
``_supply_chain.download._atomic_place`` が dir fsync の Windows-only suppression を
独立実装していたが、boilerplate が ~20 LOC 重複していたため共通化した (PR-7 タスク B)。

設計方針:
    - ``os.replace`` (atomic rename、Windows でも保証) + 親 dir fsync (POSIX 永続化)
    - dir open / fsync の OSError は **Windows のみ debug suppress**、POSIX (mac/Linux/NAS)
      では errno 付き warning ログで ENOSPC / EIO / EROFS 等の書込み完全性 failure を可視化
    - ADR-016 §1.2 階層: OS-level IO 抽象として ``_runtime/`` 配下に配置
      (lock / spawn と同階層)
"""

from __future__ import annotations

import contextlib
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def atomic_replace_and_fsync_dir(
    tmp_path: Path, final_path: Path, dest_dir: Path
) -> None:
    """tmp_path を final_path に atomic replace + 親 dir fsync。

    呼び出し側が事前に tmp_path への write + ``os.fsync(file_fd)`` を完了している前提
    (file 内容の永続化は caller 責務、本関数は **rename + directory entry 永続化** に専念)。

    Args:
        tmp_path: 既に書き込み + file fsync 済の tmp file
        final_path: 配置先 (atomic replace 対象)
        dest_dir: final_path の親 directory (dir fsync 対象)

    Raises:
        OSError: ``os.replace`` 失敗 (filesystem 異常 / cross-device / 権限)。
            **dir fsync の OSError は raise せず log 記録のみ** (rename 自体は成功している)
    """
    os.replace(tmp_path, final_path)
    _fsync_dir_best_effort(dest_dir)


def _fsync_dir_best_effort(dest_dir: Path) -> None:
    """親ディレクトリを fsync する (POSIX rename 永続化、Windows では no-op)。

    silent-failure HIGH 3 反映: Windows のみ debug suppress、POSIX では warning ログで
    errno を残して ENOSPC / EIO / EROFS 等を debug 可能化。本関数は raise しない
    (caller の atomic replace 自体は成功しており、dir fsync 失敗は recoverable なため)。
    """
    try:
        dir_fd = os.open(str(dest_dir), os.O_RDONLY)
    except OSError as e:
        if sys.platform == "win32":
            logger.debug("dir fsync skipped on Windows (open): %s", type(e).__name__)
        else:
            logger.warning(
                "dir fsync open failed: %s errno=%s filename=%s",
                type(e).__name__,
                e.errno,
                e.filename,
            )
        return
    try:
        os.fsync(dir_fd)
    except OSError as e:
        if sys.platform == "win32":
            logger.debug("dir fsync skipped on Windows: %s", type(e).__name__)
        else:
            logger.warning(
                "dir fsync failed: %s errno=%s",
                type(e).__name__,
                e.errno,
            )
    finally:
        with contextlib.suppress(OSError):
            os.close(dir_fd)
