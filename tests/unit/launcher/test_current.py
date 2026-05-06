"""Tests for wiseman_hub_launcher.current (ADR-016 PR-3)。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wiseman_hub_launcher.current import (
    DEFAULT_CURRENT,
    Current,
    read_current,
    write_current_atomic,
)


def test_read_current_missing_file_returns_default(tmp_path: Path) -> None:
    out = read_current(tmp_path / "current.json")
    assert out == DEFAULT_CURRENT
    assert out.version == "0.0.0"
    assert out.released_at == ""


def test_read_current_normal(tmp_path: Path) -> None:
    p = tmp_path / "current.json"
    p.write_text(json.dumps({"version": "1.2.3", "released_at": "2026-05-06T13:00:00Z"}))
    out = read_current(p)
    assert out.version == "1.2.3"
    assert out.released_at == "2026-05-06T13:00:00Z"


def test_read_current_corrupt_json_quarantines_and_defaults(tmp_path: Path) -> None:
    p = tmp_path / "current.json"
    p.write_bytes(b"{not json")
    out = read_current(p)
    assert out == DEFAULT_CURRENT
    # original file should be quarantined (renamed)
    assert not p.exists()
    quarantines = list(tmp_path.glob("current.json.corrupt-*"))
    assert len(quarantines) == 1
    # quarantined file should still contain original payload
    assert quarantines[0].read_bytes() == b"{not json"


def test_read_current_invalid_utf8_quarantines(tmp_path: Path) -> None:
    p = tmp_path / "current.json"
    p.write_bytes(b"\xff\xfe\xfd")
    out = read_current(p)
    assert out == DEFAULT_CURRENT
    assert list(tmp_path.glob("current.json.corrupt-*"))


def test_read_current_not_a_dict_quarantines(tmp_path: Path) -> None:
    p = tmp_path / "current.json"
    p.write_text(json.dumps([1, 2, 3]))
    out = read_current(p)
    assert out == DEFAULT_CURRENT
    assert list(tmp_path.glob("current.json.corrupt-*"))


def test_read_current_schema_mismatch_quarantines(tmp_path: Path) -> None:
    p = tmp_path / "current.json"
    p.write_text(json.dumps({"version": 123, "released_at": "x"}))  # version not str
    out = read_current(p)
    assert out == DEFAULT_CURRENT
    assert list(tmp_path.glob("current.json.corrupt-*"))


def test_read_current_missing_field_quarantines(tmp_path: Path) -> None:
    p = tmp_path / "current.json"
    p.write_text(json.dumps({"version": "1.0.0"}))  # missing released_at
    out = read_current(p)
    assert out == DEFAULT_CURRENT
    assert list(tmp_path.glob("current.json.corrupt-*"))


def test_write_current_atomic_basic(tmp_path: Path) -> None:
    p = tmp_path / "current.json"
    cur = Current(version="2.0.0", released_at="2026-06-01T00:00:00Z")
    write_current_atomic(p, cur)

    assert p.exists()
    parsed = json.loads(p.read_text())
    assert parsed["version"] == "2.0.0"
    assert parsed["released_at"] == "2026-06-01T00:00:00Z"


def test_write_current_atomic_overwrites_existing(tmp_path: Path) -> None:
    p = tmp_path / "current.json"
    p.write_text(json.dumps({"version": "1.0.0", "released_at": ""}))

    cur = Current(version="1.5.0", released_at="2026-06-15T00:00:00Z")
    write_current_atomic(p, cur)

    parsed = json.loads(p.read_text())
    assert parsed["version"] == "1.5.0"


def test_write_current_atomic_no_tmp_residue(tmp_path: Path) -> None:
    p = tmp_path / "current.json"
    cur = Current(version="3.0.0", released_at="2026-07-01T00:00:00Z")
    write_current_atomic(p, cur)
    # tmp ファイル (.current.*.tmp) が残らないこと
    residue = list(tmp_path.glob(".current.*.tmp"))
    assert residue == []


def test_write_current_atomic_round_trip(tmp_path: Path) -> None:
    p = tmp_path / "current.json"
    cur = Current(version="1.2.3", released_at="2026-05-06T13:00:00Z")
    write_current_atomic(p, cur)

    out = read_current(p)
    assert out == cur


def test_write_current_atomic_missing_parent_dir(tmp_path: Path) -> None:
    p = tmp_path / "no" / "such" / "dir" / "current.json"
    cur = Current(version="1.0.0", released_at="")
    with pytest.raises(FileNotFoundError, match="parent directory"):
        write_current_atomic(p, cur)


def test_default_current_matches_contract() -> None:
    assert DEFAULT_CURRENT.version == "0.0.0"
    assert DEFAULT_CURRENT.released_at == ""


# I-3: dry-run 副作用ゼロ ---------------------------------------------------

def test_read_current_no_quarantine_when_dry_run(tmp_path: Path) -> None:
    """I-3: quarantine_corrupt=False で破損ファイルを rename しない。"""
    p = tmp_path / "current.json"
    p.write_bytes(b"{not json")
    out = read_current(p, quarantine_corrupt=False)
    assert out == DEFAULT_CURRENT
    # 破損ファイルはそのまま残る
    assert p.exists()
    assert p.read_bytes() == b"{not json"
    # quarantine ファイルは作られない
    assert not list(tmp_path.glob("current.json.corrupt-*"))


def test_read_current_no_quarantine_for_invalid_utf8(tmp_path: Path) -> None:
    p = tmp_path / "current.json"
    p.write_bytes(b"\xff\xfe\xfd")
    out = read_current(p, quarantine_corrupt=False)
    assert out == DEFAULT_CURRENT
    assert p.exists()


def test_read_current_no_quarantine_for_not_dict(tmp_path: Path) -> None:
    p = tmp_path / "current.json"
    p.write_text(json.dumps([1, 2, 3]))
    out = read_current(p, quarantine_corrupt=False)
    assert out == DEFAULT_CURRENT
    assert p.exists()


def test_read_current_no_quarantine_for_schema_mismatch(tmp_path: Path) -> None:
    p = tmp_path / "current.json"
    p.write_text(json.dumps({"version": 123, "released_at": "x"}))
    out = read_current(p, quarantine_corrupt=False)
    assert out == DEFAULT_CURRENT
    assert p.exists()


# I-4: quarantine 名衝突回避 ------------------------------------------------

def test_quarantine_name_collision_resistant(tmp_path: Path) -> None:
    """I-4: 連続して corrupt read しても quarantine ファイル名が衝突しない。"""
    p = tmp_path / "current.json"
    quarantine_count = 5

    for _ in range(quarantine_count):
        p.write_bytes(b"{not json")
        read_current(p)

    quarantines = list(tmp_path.glob("current.json.corrupt-*"))
    # microseconds + pid + token_hex で衝突は実用上ゼロ
    assert len(quarantines) == quarantine_count, (
        f"expected {quarantine_count} unique quarantines, got {len(quarantines)}: "
        f"{[q.name for q in quarantines]}"
    )


# I-5: machine-specific path 隠蔽 -------------------------------------------

def test_read_current_default_log_no_full_path(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """I-5: verbose=False (default) では full path をログに出さない。"""
    import logging

    p = tmp_path / "current.json"  # not exists
    with caplog.at_level(logging.INFO, logger="wiseman_hub_launcher.current"):
        read_current(p)
    # full path は INFO ログに出ない
    full_path_str = str(p)
    for record in caplog.records:
        assert full_path_str not in record.getMessage(), (
            f"machine-specific path leaked: {record.getMessage()}"
        )


def test_read_current_verbose_log_includes_full_path(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """I-5: verbose=True なら full path を出す（debug 用途）。"""
    import logging

    p = tmp_path / "current.json"  # not exists
    with caplog.at_level(logging.INFO, logger="wiseman_hub_launcher.current"):
        read_current(p, verbose=True)
    full_path_str = str(p)
    found = any(full_path_str in record.getMessage() for record in caplog.records)
    assert found, "verbose=True should include full path in INFO log"
