"""配置操作の監査ログ。

C 経過報告書の配置成功・失敗を 1 日 1 ファイルの JSON Lines 形式で記録する。
log_dir 未設定 (空文字) の場合は no-op（既存運用との互換性のため）。

ファイル形式:
    ``<log_dir>/audit/c_placement_<YYYY-MM-DD>.jsonl``
    各行に 1 record (json.dumps + \n) を append のみで書く。

PII 配慮:
    record の内容は呼び出し側で組み立てる。本モジュールは構造的なログ書き出しのみで
    PII 判定はしない。Tera-station NAS 上の絶対パス・利用者氏名は介護現場運用で
    日常的にログに出ているため、操作監査としては許容される（ADR-007 の運用方針）。
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_AUDIT_SUBDIR = "audit"


def _audit_path(log_dir: Path, kind: str, day: _dt.date) -> Path:
    return log_dir / _AUDIT_SUBDIR / f"{kind}_{day.isoformat()}.jsonl"


def append_audit_record(
    log_dir: str,
    kind: str,
    record: dict[str, Any],
    *,
    now: _dt.datetime | None = None,
) -> Path | None:
    """JSON Lines 形式で 1 record を追記する。log_dir 未設定なら何もしない。

    Args:
        log_dir: AppConfig.log_dir の値。空文字なら no-op で None 返却。
        kind: ログ種別（``c_placement`` 等）。ファイル名 prefix。
        record: 追記する dict。``timestamp`` を自動付与する。
        now: テスト時の固定時刻。未指定なら現在時刻。

    Returns:
        書き込んだファイル path。log_dir 未設定なら None。
    """
    if not log_dir:
        return None
    base = Path(log_dir)
    timestamp = now or _dt.datetime.now(_dt.UTC).astimezone()
    payload = {**record, "timestamp": timestamp.isoformat()}
    target = _audit_path(base, kind, timestamp.date())
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    try:
        with open(target, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError as exc:
        logger.warning("audit append failed: %s (%s)", target.name, type(exc).__name__)
        return None
    return target
