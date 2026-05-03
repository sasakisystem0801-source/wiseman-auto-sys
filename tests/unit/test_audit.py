"""T5: 監査ログ JSON Lines の追記テスト。"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

from wiseman_hub.audit import append_audit_record


def test_append_creates_jsonl_with_timestamp(tmp_path: Path) -> None:
    fixed = _dt.datetime(2026, 5, 4, 12, 30, tzinfo=_dt.UTC)
    path = append_audit_record(
        log_dir=str(tmp_path),
        kind="c_placement",
        record={"user": "テスト 太郎", "status": "success"},
        now=fixed,
    )
    assert path is not None
    assert path.name == "c_placement_2026-05-04.jsonl"
    content = path.read_text(encoding="utf-8").strip()
    record = json.loads(content)
    assert record["user"] == "テスト 太郎"
    assert record["status"] == "success"
    assert record["timestamp"].startswith("2026-05-04T")


def test_append_multiple_records_appends(tmp_path: Path) -> None:
    fixed = _dt.datetime(2026, 5, 4, 9, 0, tzinfo=_dt.UTC)
    append_audit_record(str(tmp_path), "c_placement", {"i": 1}, now=fixed)
    append_audit_record(str(tmp_path), "c_placement", {"i": 2}, now=fixed)
    path = tmp_path / "audit" / "c_placement_2026-05-04.jsonl"
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["i"] == 1
    assert json.loads(lines[1])["i"] == 2


def test_append_no_log_dir_returns_none(tmp_path: Path) -> None:
    """log_dir 空文字なら no-op で None 返却（既存運用との互換性）。"""
    result = append_audit_record(log_dir="", kind="c_placement", record={})
    assert result is None


def test_append_creates_audit_subdir(tmp_path: Path) -> None:
    """audit/ サブディレクトリが自動作成される。"""
    sub = tmp_path / "logs"
    sub.mkdir()
    path = append_audit_record(str(sub), "c_placement", {"x": 1})
    assert path is not None
    assert path.parent.name == "audit"
    assert path.parent.exists()
