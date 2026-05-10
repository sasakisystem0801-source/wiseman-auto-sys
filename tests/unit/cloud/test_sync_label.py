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
        ok = write_sync_timestamp(tmp_path, "mapping_routing")
        # Phase 2-β (F1): 成功時は True を返す
        assert ok is True
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

    def test_naive_ts_raises(self, tmp_path: Path) -> None:
        """review 反映 (code-reviewer I-1 rating 7): naive datetime は構造的に reject。

        ``read_sync_timestamp`` が naive を None フォールバックする設計と対称性を取る
        ため、書込側でも naive を受け入れない。
        """
        naive = _dt.datetime(2026, 5, 9, 10, 0)  # tz=None
        assert naive.tzinfo is None
        with pytest.raises(ValueError, match="timezone-aware"):
            write_sync_timestamp(tmp_path, "k", ts=naive)

    def test_mkdir_oserror_returns_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """review 反映 (evaluator AC-7 + Phase 2-β F1): mkdir OSError は warn + False。"""
        import logging
        readonly_dir = tmp_path / "readonly_cache"

        def _raise_oserror(*args: object, **kwargs: object) -> None:
            raise PermissionError("simulated readonly")

        monkeypatch.setattr(Path, "mkdir", _raise_oserror)
        with caplog.at_level(logging.WARNING):
            # raise しないことが契約 (UI 進行を止めない)
            ok = write_sync_timestamp(readonly_dir, "mapping_routing")
        # Phase 2-β (F1): I/O 失敗は False を返す (caller が warn ログ可能)
        assert ok is False
        # ファイルは書かれていない
        assert not (readonly_dir / "mapping_routing.json").exists()
        # warning ログが出ている
        assert any("mkdir failed" in rec.message for rec in caplog.records)

    def test_write_oserror_returns_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """review 反映 (evaluator AC-7 + Phase 2-β F1): write_text OSError は warn + False。"""
        import logging

        def _raise_oserror(*args: object, **kwargs: object) -> None:
            raise PermissionError("simulated write failure")

        monkeypatch.setattr(Path, "write_text", _raise_oserror)
        with caplog.at_level(logging.WARNING):
            ok = write_sync_timestamp(tmp_path, "mapping_routing")
        # Phase 2-β (F1): write 失敗も False を返す
        assert ok is False
        assert any("write failed" in rec.message for rec in caplog.records)

    def test_explicit_ts_returns_true(self, tmp_path: Path) -> None:
        """Phase 2-β (F1): explicit ts override 経路でも success → True。"""
        custom = _dt.datetime(2026, 5, 9, 10, 0, tzinfo=_dt.UTC)
        ok = write_sync_timestamp(tmp_path, "report_staff", ts=custom)
        assert ok is True

    def test_cache_dir_path_is_file_returns_false(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Issue #246 (Phase 3 P1-2 rating 8): cache_dir が file の場合は False。

        Windows 配布固有 fail mode:
            - PyInstaller 配布先で別ユーザー権限により cache_dir 名と同名の file
              が作成されている場合
            - インストール時の atomic_replace で file → directory 置換が失敗した残骸
            - 手動でユーザーが cache_dir 名と同名の file を作成した場合

        ``Path.mkdir(parents=True, exist_ok=True)`` は対象が file として存在する
        と ``FileExistsError`` (``OSError`` サブクラス) を raise するため、
        ``write_sync_timestamp`` 内の ``except OSError`` で捕捉され False を返す。

        本 test は ``test_mkdir_oserror_returns_false`` (monkeypatch) の補完で、
        実際の filesystem 状態を作って behavioral に検証する。
        """
        import logging
        file_path = tmp_path / "blocking_file_at_cache_dir_path"
        file_path.write_text("pre-existing user file", encoding="utf-8")
        assert file_path.is_file()

        with caplog.at_level(logging.WARNING):
            ok = write_sync_timestamp(file_path, "mapping_routing")

        # Phase 2-β (F1) 契約: I/O 失敗は False を返す (raise しない)
        assert ok is False
        # 既存 file は破壊されない
        assert file_path.is_file()
        assert file_path.read_text(encoding="utf-8") == "pre-existing user file"
        # warning ログが出ている (mkdir failed 経路)
        assert any("mkdir failed" in rec.message for rec in caplog.records)


class TestSyncCacheDirFor:
    def test_derives_from_config_path(self, tmp_path: Path) -> None:
        cfg = tmp_path / "wiseman-hub" / "config" / "default.toml"
        result = sync_cache_dir_for(cfg)
        assert result == tmp_path / "wiseman-hub" / "cache" / "sync"
