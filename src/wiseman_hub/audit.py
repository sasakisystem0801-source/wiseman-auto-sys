"""配置操作の監査ログ。

C 経過報告書の配置成功・失敗を 1 日 1 ファイルの JSON Lines 形式で記録する。
log_dir 未設定 (空文字) の場合は no-op（既存運用との互換性のため）。

ファイル形式:
    ``<log_dir>/audit/c_placement_<YYYY-MM-DD>.jsonl``
    各行に 1 record (json.dumps + \\n) を append のみで書く。

排他制御:
    同一プロセス内の並行 append は ``threading.Lock`` で行単位 atomic を保証する。
    複数プロセス（exe 多重起動 / 将来のスケジューラ併用）への対策は Phase 2 で
    検討（lock file 等）。現状の単独 GUI 運用では同一プロセス排他で十分。

PII 配慮:
    record の内容は呼び出し側で組み立てる。本モジュールは構造的なログ書き出しのみで
    PII 判定はしない。Tera-station NAS 上の絶対パス・利用者氏名は介護現場運用で
    日常的にログに出ているため、操作監査としては許容される（ADR-007 の運用方針）。
    保持期間・削除手順は staff-path-cache-runbook.md 参照。
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import threading
from pathlib import Path
from typing import Any

from wiseman_hub.config import is_path_configured

logger = logging.getLogger(__name__)

_AUDIT_SUBDIR = "audit"

# 同一プロセス内の append 排他（Codex review HIGH-2 対策）
# 複数プロセス対策は Phase 2 (lock file / msvcrt.locking)
_APPEND_LOCK = threading.Lock()


def _audit_path(log_dir: Path, kind: str, day: _dt.date) -> Path:
    return log_dir / _AUDIT_SUBDIR / f"{kind}_{day.isoformat()}.jsonl"


def append_audit_record(
    log_dir: Path,
    kind: str,
    record: dict[str, Any],
    *,
    now: _dt.datetime | None = None,
) -> Path | None:
    """JSON Lines 形式で 1 record を追記する。log_dir 未設定なら何もしない。

    Args:
        log_dir: ``AppConfig.log_dir`` の値 (Path 型)。空 Path
            (``Path("")`` = ``Path(".")``) は未設定 sentinel として no-op で None 返却。
            Issue #27 続編 G §4: str → Path 移行。
        kind: ログ種別（``c_placement`` 等）。ファイル名 prefix。
        record: 追記する dict。``timestamp`` を自動付与する。
        now: テスト時の固定時刻。未指定なら現在時刻。

    Returns:
        書き込んだファイル path。log_dir 未設定なら None。
    """
    # Issue #27 続編 G §4: 未設定 sentinel は is_path_configured で集約判定。
    if not is_path_configured(log_dir):
        return None
    base = log_dir
    timestamp = now or _dt.datetime.now(_dt.UTC).astimezone()
    payload = {**record, "timestamp": timestamp.isoformat()}
    target = _audit_path(base, kind, timestamp.date())
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    # threading.Lock で同一プロセス並行 append から行を保護
    with _APPEND_LOCK:
        try:
            with open(target, "a", encoding="utf-8") as f:
                f.write(line)
        except OSError as exc:
            logger.warning("audit append failed: %s (%s)", target.name, type(exc).__name__)
            return None
    return target
