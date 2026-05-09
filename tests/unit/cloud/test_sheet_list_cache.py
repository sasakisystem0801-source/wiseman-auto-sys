"""シート一覧キャッシュ (PR-δ v1) のユニットテスト。

cache_dir_for / load / save の round-trip 動作と、破損ケース・edge case を検証。

Issue #238 Phase 1 (2026-05-09): load() の戻り値が ``CachedSheetList`` dataclass
化されたため既存 test を ``.names`` 属性アクセスに追従。``fetched_at`` の parse
動作と ``format_synced_at_label`` ヘルパーの新規 test を追加。
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

from wiseman_hub.cloud.sheet_list_cache import (
    CachedSheetList,
    cache_dir_for,
    format_synced_at_label,
    load,
    save,
)


class TestCacheDirFor:
    def test_derives_from_config_path(self, tmp_path: Path) -> None:
        cfg = tmp_path / "wiseman-hub" / "config" / "default.toml"
        result = cache_dir_for(cfg)
        assert result == tmp_path / "wiseman-hub" / "cache" / "sheets"


class TestRoundTrip:
    def test_save_then_load_returns_same_names(self, tmp_path: Path) -> None:
        names = ["25年12月", "26年1月", "26年2月", "26年3月"]
        save(tmp_path, "spread123", names)
        cached = load(tmp_path, "spread123")
        assert cached is not None
        assert cached.names == names

    def test_save_then_load_returns_fetched_at(self, tmp_path: Path) -> None:
        """save() で書いた fetched_at が load() で datetime として読める (Issue #238)。"""
        save(tmp_path, "spread123", ["25年12月"])
        cached = load(tmp_path, "spread123")
        assert cached is not None
        assert isinstance(cached.fetched_at, _dt.datetime)
        # save 直後の fetched_at は現在時刻に近い (5 秒以内)
        delta = _dt.datetime.now(tz=_dt.UTC) - cached.fetched_at
        assert abs(delta.total_seconds()) < 5

    def test_load_missing_returns_none(self, tmp_path: Path) -> None:
        assert load(tmp_path, "no_such_id") is None

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        nested = tmp_path / "deep" / "nested" / "cache"
        save(nested, "id1", ["a"])
        assert (nested / "id1.json").exists()

    def test_save_overwrites_existing(self, tmp_path: Path) -> None:
        save(tmp_path, "id1", ["old"])
        save(tmp_path, "id1", ["new1", "new2"])
        cached = load(tmp_path, "id1")
        assert cached is not None
        assert cached.names == ["new1", "new2"]


class TestRobustness:
    def test_load_corrupt_json_returns_none(self, tmp_path: Path) -> None:
        (tmp_path / "broken.json").write_text("{ this is not valid", encoding="utf-8")
        assert load(tmp_path, "broken") is None

    def test_load_invalid_schema_returns_none(self, tmp_path: Path) -> None:
        (tmp_path / "bad.json").write_text(
            json.dumps({"sheet_names": "not_a_list"}), encoding="utf-8"
        )
        assert load(tmp_path, "bad") is None

    def test_load_non_string_items_returns_none(self, tmp_path: Path) -> None:
        (tmp_path / "x.json").write_text(
            json.dumps({"sheet_names": ["valid", 123, "also"]}), encoding="utf-8"
        )
        assert load(tmp_path, "x") is None

    def test_empty_spreadsheet_id_load_is_none(self, tmp_path: Path) -> None:
        assert load(tmp_path, "") is None

    def test_empty_spreadsheet_id_save_is_noop(self, tmp_path: Path) -> None:
        save(tmp_path, "", ["a"])
        # ディレクトリすら作られない（save 内で早期 return）
        assert not (tmp_path).exists() or len(list(tmp_path.iterdir())) == 0

    def test_path_traversal_is_sanitized(self, tmp_path: Path) -> None:
        """spreadsheet_id に ``..`` 等の path traversal 文字が混入しても安全。"""
        save(tmp_path, "../../etc/passwd", ["x"])
        # 英数字以外を除去した結果、tmp_path 直下にファイルが残る
        files = list(tmp_path.glob("*.json"))
        assert len(files) == 1
        # 親ディレクトリへの脱出は起きていない
        assert all(tmp_path in f.parents or f.parent == tmp_path for f in files)


class TestFetchedAtBackwardCompat:
    """Issue #238 Phase 1: fetched_at 欠落 / 不正形式の後方互換テスト。"""

    def test_load_legacy_schema_without_fetched_at(self, tmp_path: Path) -> None:
        """旧 schema (fetched_at 欠落) は names だけ取得、fetched_at=None。"""
        (tmp_path / "legacy.json").write_text(
            json.dumps({"spreadsheet_id": "legacy", "sheet_names": ["a", "b"]}),
            encoding="utf-8",
        )
        cached = load(tmp_path, "legacy")
        assert cached is not None
        assert cached.names == ["a", "b"]
        assert cached.fetched_at is None

    def test_load_invalid_fetched_at_string_treats_as_none(
        self, tmp_path: Path
    ) -> None:
        """fetched_at が ISO8601 として parse 不能なら None フォールバック。"""
        (tmp_path / "bad_dt.json").write_text(
            json.dumps(
                {
                    "spreadsheet_id": "bad_dt",
                    "sheet_names": ["a"],
                    "fetched_at": "not-a-datetime",
                }
            ),
            encoding="utf-8",
        )
        cached = load(tmp_path, "bad_dt")
        assert cached is not None
        assert cached.names == ["a"]
        assert cached.fetched_at is None

    def test_load_non_string_fetched_at_treats_as_none(self, tmp_path: Path) -> None:
        """fetched_at が文字列でない (int 等) 場合も None フォールバック。"""
        (tmp_path / "int_dt.json").write_text(
            json.dumps(
                {
                    "spreadsheet_id": "int_dt",
                    "sheet_names": ["a"],
                    "fetched_at": 123456789,
                }
            ),
            encoding="utf-8",
        )
        cached = load(tmp_path, "int_dt")
        assert cached is not None
        assert cached.fetched_at is None


class TestPayloadFormat:
    def test_saved_json_contains_required_fields(self, tmp_path: Path) -> None:
        save(tmp_path, "id1", ["a", "b"])
        data = json.loads((tmp_path / "id1.json").read_text(encoding="utf-8"))
        assert data["spreadsheet_id"] == "id1"
        assert data["sheet_names"] == ["a", "b"]
        assert "fetched_at" in data
        # ISO 8601 形式
        assert "T" in data["fetched_at"]

    def test_unicode_preserved(self, tmp_path: Path) -> None:
        """日本語タブ名がエスケープされず保存される (ensure_ascii=False)。"""
        save(tmp_path, "id1", ["26年3月"])
        text = (tmp_path / "id1.json").read_text(encoding="utf-8")
        assert "26年3月" in text  # 日本語が直接出力される
        assert "\\u" not in text  # ensure_ascii=False が効いている


class TestFormatSyncedAtLabel:
    """Issue #238 Phase 1: format_synced_at_label の境界値テスト。"""

    def test_none_returns_unknown(self) -> None:
        now = _dt.datetime(2026, 5, 9, 14, 30, tzinfo=_dt.UTC)
        assert format_synced_at_label(None, now) == "不明"

    def test_just_now_under_60_seconds(self) -> None:
        now = _dt.datetime(2026, 5, 9, 14, 30, 30, tzinfo=_dt.UTC)
        fetched = _dt.datetime(2026, 5, 9, 14, 30, 0, tzinfo=_dt.UTC)
        # absolute 時刻は local tz 変換後の月/日 時:分
        local = fetched.astimezone()
        expected_abs = f"{local.month}/{local.day} {local.hour:02d}:{local.minute:02d}"
        assert format_synced_at_label(fetched, now) == f"{expected_abs} (たった今)"

    def test_minutes_ago(self) -> None:
        now = _dt.datetime(2026, 5, 9, 14, 33, tzinfo=_dt.UTC)
        fetched = _dt.datetime(2026, 5, 9, 14, 30, tzinfo=_dt.UTC)
        result = format_synced_at_label(fetched, now)
        assert "(3 分前)" in result

    def test_hours_ago(self) -> None:
        now = _dt.datetime(2026, 5, 9, 17, 30, tzinfo=_dt.UTC)
        fetched = _dt.datetime(2026, 5, 9, 14, 30, tzinfo=_dt.UTC)
        result = format_synced_at_label(fetched, now)
        assert "(3 時間前)" in result

    def test_days_ago(self) -> None:
        now = _dt.datetime(2026, 5, 12, 14, 30, tzinfo=_dt.UTC)
        fetched = _dt.datetime(2026, 5, 9, 14, 30, tzinfo=_dt.UTC)
        result = format_synced_at_label(fetched, now)
        assert "(3 日前)" in result

    def test_future_clock_skew(self) -> None:
        """now < fetched_at (時計ずれ等の異常系) は時刻同期確認中で表示。"""
        now = _dt.datetime(2026, 5, 9, 14, 30, tzinfo=_dt.UTC)
        fetched = _dt.datetime(2026, 5, 9, 14, 35, tzinfo=_dt.UTC)
        result = format_synced_at_label(fetched, now)
        assert "(時刻同期確認中)" in result

    def test_returns_cached_sheet_list_dataclass(self) -> None:
        """CachedSheetList は frozen dataclass で names + fetched_at を持つ。"""
        cached = CachedSheetList(
            names=["a", "b"],
            fetched_at=_dt.datetime(2026, 5, 9, 14, 30, tzinfo=_dt.UTC),
        )
        assert cached.names == ["a", "b"]
        assert cached.fetched_at == _dt.datetime(2026, 5, 9, 14, 30, tzinfo=_dt.UTC)
