"""Tests for wiseman_hub_launcher.current (ADR-016 PR-3)。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wiseman_hub_launcher.current import (
    DEFAULT_CURRENT,
    Current,
    CurrentReadError,
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
    # PR-4: previous_version="" = 初回 update では rollback 不能を明示
    assert DEFAULT_CURRENT.previous_version == ""


# PR-4: previous_version + semver validation -------------------------------


def test_read_current_with_previous_version(tmp_path: Path) -> None:
    """PR-4: previous_version あり JSON を正しく読む。"""
    p = tmp_path / "current.json"
    p.write_text(
        json.dumps(
            {
                "version": "1.2.3",
                "released_at": "2026-05-06T13:00:00Z",
                "previous_version": "1.2.2",
            }
        )
    )
    out = read_current(p)
    assert out.version == "1.2.3"
    assert out.previous_version == "1.2.2"


def test_read_current_pr3_format_backward_compat(tmp_path: Path) -> None:
    """PR-4: PR-3 形式 (previous_version field なし) を後方互換で読む。

    quarantine しない、default "" で Current を返す。
    """
    p = tmp_path / "current.json"
    p.write_text(
        json.dumps({"version": "1.2.3", "released_at": "2026-05-06T13:00:00Z"})
    )
    out = read_current(p)
    assert out.version == "1.2.3"
    assert out.previous_version == ""
    # quarantine されず元の場所に残ること
    assert p.exists()
    assert not list(tmp_path.glob("current.json.corrupt-*"))


def test_read_current_invalid_version_semver_quarantines(tmp_path: Path) -> None:
    """PR-4 Sug-1: version が semver 不正なら quarantine。"""
    p = tmp_path / "current.json"
    p.write_text(json.dumps({"version": "not-semver", "released_at": ""}))
    out = read_current(p)
    assert out == DEFAULT_CURRENT
    assert list(tmp_path.glob("current.json.corrupt-*"))


def test_read_current_invalid_previous_version_semver_quarantines(
    tmp_path: Path,
) -> None:
    """PR-4 Sug-1: previous_version が semver 不正なら quarantine。"""
    p = tmp_path / "current.json"
    p.write_text(
        json.dumps(
            {
                "version": "1.2.3",
                "released_at": "",
                "previous_version": "garbage",
            }
        )
    )
    out = read_current(p)
    assert out == DEFAULT_CURRENT
    assert list(tmp_path.glob("current.json.corrupt-*"))


def test_read_current_empty_previous_version_ok(tmp_path: Path) -> None:
    """PR-4: previous_version="" (rollback 先なし、初期状態) は valid。"""
    p = tmp_path / "current.json"
    p.write_text(
        json.dumps(
            {
                "version": "1.2.3",
                "released_at": "2026-05-06T13:00:00Z",
                "previous_version": "",
            }
        )
    )
    out = read_current(p)
    assert out.version == "1.2.3"
    assert out.previous_version == ""
    assert p.exists()


def test_read_current_previous_version_wrong_type_quarantines(
    tmp_path: Path,
) -> None:
    """PR-4: previous_version が str 以外 (None/int) なら quarantine。"""
    p = tmp_path / "current.json"
    p.write_text(
        json.dumps(
            {
                "version": "1.2.3",
                "released_at": "",
                "previous_version": 123,
            }
        )
    )
    out = read_current(p)
    assert out == DEFAULT_CURRENT
    assert list(tmp_path.glob("current.json.corrupt-*"))


def test_read_current_leading_zero_version_quarantines(tmp_path: Path) -> None:
    """PR-4: leading zero version ('01.2.3') は semver 不正で quarantine。

    is_simple_semver の leading zero 拒否仕様 (manifest.py PR-3 Sug-2) と整合。
    """
    p = tmp_path / "current.json"
    p.write_text(json.dumps({"version": "01.2.3", "released_at": ""}))
    out = read_current(p)
    assert out == DEFAULT_CURRENT


def test_write_current_atomic_with_previous_version(tmp_path: Path) -> None:
    """PR-4: previous_version 付きで write -> read で round-trip。"""
    p = tmp_path / "current.json"
    cur = Current(
        version="1.2.3",
        released_at="2026-05-06T13:00:00Z",
        previous_version="1.2.2",
    )
    write_current_atomic(p, cur)

    parsed = json.loads(p.read_text())
    assert parsed["version"] == "1.2.3"
    assert parsed["previous_version"] == "1.2.2"

    out = read_current(p)
    assert out == cur


def test_write_current_atomic_default_previous_version(tmp_path: Path) -> None:
    """PR-4: previous_version 省略時は "" で書き出される。"""
    p = tmp_path / "current.json"
    cur = Current(version="1.0.0", released_at="2026-05-06T13:00:00Z")
    write_current_atomic(p, cur)

    parsed = json.loads(p.read_text())
    assert parsed["previous_version"] == ""


# review_team A2 second-pass (silent-failure I6): strict_read 引数 -----------


def test_read_current_strict_read_does_not_raise_on_missing(tmp_path: Path) -> None:
    """A2 second-pass: file 不在は genuine first install なので raise しない。"""
    out = read_current(tmp_path / "current.json", strict_read=True)
    assert out == DEFAULT_CURRENT


def test_read_current_strict_read_raises_on_io_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A2 second-pass: read_bytes で OSError なら CurrentReadError raise
    (Windows AV transient ロックで silent に「first install」と誤認させない)。"""
    p = tmp_path / "current.json"
    p.write_text(json.dumps({"version": "1.2.3", "released_at": "x"}))

    def _raise_oserror(self: Path) -> bytes:  # noqa: ARG001
        raise PermissionError(13, "Permission denied", str(p))

    monkeypatch.setattr(Path, "read_bytes", _raise_oserror)
    with pytest.raises(CurrentReadError, match="read error"):
        read_current(p, strict_read=True)


def test_read_current_strict_read_raises_on_corrupt_json(tmp_path: Path) -> None:
    """A2 second-pass: 破損 JSON は CurrentReadError raise (silent fallback しない)。"""
    p = tmp_path / "current.json"
    p.write_bytes(b"{not json")
    with pytest.raises(CurrentReadError, match="json-decode"):
        read_current(p, strict_read=True)


def test_read_current_strict_read_raises_on_schema_mismatch(tmp_path: Path) -> None:
    """A2 second-pass: schema 不一致は CurrentReadError raise。"""
    p = tmp_path / "current.json"
    p.write_text(json.dumps({"version": 123, "released_at": "x"}))  # version int
    with pytest.raises(CurrentReadError, match="schema-mismatch"):
        read_current(p, strict_read=True)


def test_read_current_strict_read_raises_on_invalid_semver(tmp_path: Path) -> None:
    """A2 second-pass: semver 不正は CurrentReadError raise。"""
    p = tmp_path / "current.json"
    p.write_text(json.dumps({"version": "not-semver", "released_at": ""}))
    with pytest.raises(CurrentReadError, match="version-not-semver"):
        read_current(p, strict_read=True)


def test_read_current_strict_read_does_not_quarantine(tmp_path: Path) -> None:
    """strict_read=True で raise する場合、quarantine も dry-run silent fallback も
    行わず即 raise する。"""
    p = tmp_path / "current.json"
    p.write_bytes(b"{not json")
    with pytest.raises(CurrentReadError):
        read_current(p, strict_read=True)
    # 元 file がそのまま残る (quarantine されていない)
    assert p.exists()
    assert p.read_bytes() == b"{not json"
    assert not list(tmp_path.glob("current.json.corrupt-*"))


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


# C6 (pr-test-analyzer Critical): Current.__post_init__ semver invariant の直接 test


def test_current_post_init_rejects_invalid_version_semver() -> None:
    """C6: Current 直接生成時に version が semver でないと ValueError raise。"""
    with pytest.raises(ValueError, match="Current.version must be semver"):
        Current(version="not-semver", released_at="x", previous_version="")


def test_current_post_init_rejects_invalid_previous_version_semver() -> None:
    """C6: previous_version が "" でも semver でもないと ValueError raise。"""
    with pytest.raises(ValueError, match="Current.previous_version"):
        Current(version="1.2.3", released_at="x", previous_version="garbage")


def test_current_post_init_accepts_empty_previous_version() -> None:
    """C6: previous_version="" は rollback 先なしの正規状態として accept。"""
    cur = Current(version="1.2.3", released_at="x", previous_version="")
    assert cur.previous_version == ""


def test_current_post_init_accepts_valid_semver_pair() -> None:
    """C6: version + previous_version とも valid semver なら accept。"""
    cur = Current(version="2.0.0", released_at="x", previous_version="1.2.3")
    assert cur.version == "2.0.0"
    assert cur.previous_version == "1.2.3"


@pytest.mark.parametrize(
    "bad_version",
    ["", "1", "1.2", "1.2.3.4", "v1.2.3", "1.2.x", "01.2.3"],
)
def test_current_post_init_rejects_various_non_semver(bad_version: str) -> None:
    """C6: 各種 non-semver で ValueError raise (空 / 段不足 / leading zero 等)。"""
    with pytest.raises(ValueError, match="Current.version"):
        Current(version=bad_version, released_at="x", previous_version="")
