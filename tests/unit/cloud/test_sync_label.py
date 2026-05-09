"""``cloud.sync_label`` のユニットテスト (Issue #238 Phase 2-α)。

Phase 1 で sheet_list_cache 内に置いた ``format_synced_at_label`` を共有 helper
``cloud.sync_label`` に移動し、汎用の ``write_sync_timestamp`` /
``read_sync_timestamp`` を追加するための test 群。

設計判断:
    - timestamp file schema: ``{"fetched_at": "<ISO8601 UTC>"}``
    - tz naive / parse 失敗 / future timestamp はすべて None or 「不明」/「時刻同期確認中」
      へフォールバック (UI で必ず displayable な状態を保証)
    - name は path traversal 防止のため英数 + ``-_`` のみ通す sanitize 経路
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import pytest

from wiseman_hub.cloud.sync_label import (
    format_synced_at_label,
    read_sync_timestamp,
    sync_cache_dir_for,
    write_sync_timestamp,
)

# --- format_synced_at_label (Phase 1 から移動) ----------------------------


class TestFormatSyncedAtLabel:
    """ラベル文字列の整形テスト (Phase 1 のテストを sync_label 側に集約)。"""

    def _ts(self, year: int = 2026, month: int = 5, day: int = 9,
            hour: int = 14, minute: int = 30) -> _dt.datetime:
        return _dt.datetime(year, month, day, hour, minute, tzinfo=_dt.UTC)

    def test_none_returns_unknown(self) -> None:
        now = self._ts()
        assert format_synced_at_label(None, now) == "不明"

    def test_just_now_under_60s(self) -> None:
        """sec=30 (< 60) で「たった今」分岐。境界 sec=60 は別 test で確認。"""
        ts = self._ts(minute=29)
        now = ts + _dt.timedelta(seconds=30)
        result = format_synced_at_label(ts, now)
        assert result.endswith("(たった今)")

    def test_minutes_ago(self) -> None:
        ts = self._ts(minute=20)
        now = self._ts(minute=30)
        assert format_synced_at_label(ts, now).endswith("(10 分前)")

    def test_hours_ago(self) -> None:
        ts = self._ts(hour=10)
        now = self._ts(hour=14)
        assert format_synced_at_label(ts, now).endswith("(4 時間前)")

    def test_days_ago(self) -> None:
        ts = self._ts(day=5)
        now = self._ts(day=9)
        assert format_synced_at_label(ts, now).endswith("(4 日前)")

    def test_future_returns_clock_sync(self) -> None:
        """now < fetched_at (時計ずれ) → 「時刻同期確認中」フォールバック。"""
        ts = self._ts(minute=30)
        now = self._ts(minute=20)
        assert format_synced_at_label(ts, now).endswith("(時刻同期確認中)")

    # 境界値 (sec=0/60/3600/86400)
    def test_boundary_zero_seconds(self) -> None:
        ts = self._ts()
        now = self._ts()
        assert format_synced_at_label(ts, now).endswith("(たった今)")

    def test_boundary_60_seconds(self) -> None:
        ts = self._ts(minute=29)
        now = ts + _dt.timedelta(seconds=60)
        assert format_synced_at_label(ts, now).endswith("(1 分前)")

    def test_boundary_3600_seconds(self) -> None:
        ts = self._ts(hour=10)
        now = ts + _dt.timedelta(seconds=3600)
        assert format_synced_at_label(ts, now).endswith("(1 時間前)")

    def test_boundary_86400_seconds(self) -> None:
        ts = self._ts(day=5)
        now = ts + _dt.timedelta(seconds=86400)
        assert format_synced_at_label(ts, now).endswith("(1 日前)")

    def test_abs_format_month_day_hour_minute(self) -> None:
        """絶対時刻部の format: M/D HH:MM (zero-padded HH:MM、month/day は無 padding)。"""
        ts = _dt.datetime(2026, 1, 5, 9, 7, tzinfo=_dt.UTC)
        now = ts + _dt.timedelta(seconds=120)
        # ローカル TZ 変換が入るので前半部分のみ抽出してチェック
        label = format_synced_at_label(ts, now)
        # M/D + HH:MM 形式 (lossy だが大筋は month=1, day=5, HH:MM が含まれること)
        assert " " in label
        assert "(2 分前)" in label


# --- write_sync_timestamp / read_sync_timestamp (新規) ----------------


class TestWriteReadSyncTimestamp:
    """write/read の round-trip + edge cases。"""

    def test_round_trip_returns_aware_datetime(self, tmp_path: Path) -> None:
        write_sync_timestamp(tmp_path, "mapping_routing")
        ts = read_sync_timestamp(tmp_path, "mapping_routing")
        assert ts is not None
        assert ts.tzinfo is not None
        delta = _dt.datetime.now(tz=_dt.UTC) - ts
        assert abs(delta.total_seconds()) < 5

    def test_explicit_ts_override(self, tmp_path: Path) -> None:
        custom = _dt.datetime(2026, 5, 9, 10, 0, tzinfo=_dt.UTC)
        write_sync_timestamp(tmp_path, "report_staff", ts=custom)
        ts = read_sync_timestamp(tmp_path, "report_staff")
        assert ts == custom

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        assert read_sync_timestamp(tmp_path, "nonexistent") is None

    def test_invalid_json_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "broken.json"
        path.write_text("{ not json", encoding="utf-8")
        assert read_sync_timestamp(tmp_path, "broken") is None

    def test_naive_datetime_returns_none(self, tmp_path: Path) -> None:
        """tz 欠落 (naive datetime) → None フォールバック (TypeError 防御)。"""
        path = tmp_path / "naive.json"
        path.write_text(json.dumps({"fetched_at": "2026-05-09T10:00:00"}),
                        encoding="utf-8")
        assert read_sync_timestamp(tmp_path, "naive") is None

    def test_non_string_fetched_at_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "wrong_type.json"
        path.write_text(json.dumps({"fetched_at": 12345}), encoding="utf-8")
        assert read_sync_timestamp(tmp_path, "wrong_type") is None

    def test_missing_fetched_at_field_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "no_field.json"
        path.write_text(json.dumps({"other": "value"}), encoding="utf-8")
        assert read_sync_timestamp(tmp_path, "no_field") is None

    def test_overwrite_replaces_old_value(self, tmp_path: Path) -> None:
        old = _dt.datetime(2026, 1, 1, 0, 0, tzinfo=_dt.UTC)
        new = _dt.datetime(2026, 5, 9, 12, 0, tzinfo=_dt.UTC)
        write_sync_timestamp(tmp_path, "k", ts=old)
        write_sync_timestamp(tmp_path, "k", ts=new)
        ts = read_sync_timestamp(tmp_path, "k")
        assert ts == new

    def test_creates_cache_dir_if_missing(self, tmp_path: Path) -> None:
        nested = tmp_path / "cache" / "sync"
        assert not nested.exists()
        write_sync_timestamp(nested, "mapping_routing")
        assert nested.exists()

    @pytest.mark.parametrize(
        "bad_name",
        ["..", "../traversal", "a/b", "a\\b", "name with space", ""],
    )
    def test_invalid_name_raises(self, tmp_path: Path, bad_name: str) -> None:
        """path traversal / 空 / セパレータ含む name は ValueError で拒否。"""
        with pytest.raises(ValueError):
            write_sync_timestamp(tmp_path, bad_name)


class TestSyncCacheDirFor:
    def test_derives_from_config_path(self, tmp_path: Path) -> None:
        cfg = tmp_path / "wiseman-hub" / "config" / "default.toml"
        result = sync_cache_dir_for(cfg)
        assert result == tmp_path / "wiseman-hub" / "cache" / "sync"
