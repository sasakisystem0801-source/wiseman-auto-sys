"""SheetListBinding helper のユニットテスト (Issue: B/C ダイアログ DRY 化)。

cache hit / miss / config_path=None / spreadsheet_id 未設定 / I/O 失敗 / 破損 JSON の
全経路と format_sync_label の各時間帯文言を検証する。

AC-1, AC-2, AC-8, AC-9 をカバー。
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import pytest

from wiseman_hub.cloud.sheet_list_cache import (
    cache_dir_for as _sheet_cache_dir_for,
)
from wiseman_hub.cloud.sheet_list_cache import (
    save as _save_sheet_cache,
)
from wiseman_hub.ui.sheet_list_binding import SheetListBinding


class _FakeCombo:
    """ttk.Combobox の最小 stub (values 設定と current() 受付のみ)。

    Tk runtime 不要なテストでも binding を検証できるよう、本テストでは
    本物の Combobox ではなくこの stub を使う (helper は dict-style assignment
    と .current(idx) しか呼ばない)。
    """

    def __init__(self) -> None:
        self._values: tuple[str, ...] = ()
        self._current: int | None = None

    def __setitem__(self, key: str, value: object) -> None:
        if key == "values":
            # tkinter は list でも tuple でも受け付けるが、内部的に tuple 化される。
            self._values = tuple(value)  # type: ignore[arg-type]
        else:
            raise KeyError(key)

    def current(self, index: int) -> None:
        self._current = index

    @property
    def values(self) -> tuple[str, ...]:
        return self._values

    @property
    def current_index(self) -> int | None:
        return self._current


def _make_config_path(tmp_path: Path) -> Path:
    """SheetListBinding が期待する cache_dir 階層を組み立てる。

    cache_dir_for は ``config_path.parent.parent / "cache" / "sheets"`` を返すため、
    config_path は 2 階層深くする必要がある。
    """
    cfg_dir = tmp_path / "wiseman-hub" / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    return cfg_dir / "default.toml"


class TestPopulateComboOnOpen:
    def test_returns_zero_when_config_path_is_none(self) -> None:
        """config_path=None の場合は no-op で 0 を返す (AC-8)。"""
        binding = SheetListBinding(None, lambda: "spread123")
        combo = _FakeCombo()
        result = binding.populate_combo_on_open(combo)
        assert result == 0
        assert combo.values == ()

    def test_returns_zero_when_spreadsheet_id_is_empty(
        self, tmp_path: Path
    ) -> None:
        """spreadsheet_id 未設定でも no-op で 0 を返す。"""
        cfg = _make_config_path(tmp_path)
        binding = SheetListBinding(cfg, lambda: "")
        combo = _FakeCombo()
        result = binding.populate_combo_on_open(combo)
        assert result == 0

    def test_returns_zero_when_cache_missing(self, tmp_path: Path) -> None:
        """cache 不在時は 0 を返し combo は変更しない。"""
        cfg = _make_config_path(tmp_path)
        binding = SheetListBinding(cfg, lambda: "spread123")
        combo = _FakeCombo()
        result = binding.populate_combo_on_open(combo)
        assert result == 0
        assert combo.values == ()

    def test_populates_combo_on_cache_hit(self, tmp_path: Path) -> None:
        """cache hit 時に combo を populate し末尾を選択 (AC-1)。"""
        cfg = _make_config_path(tmp_path)
        cache_dir = _sheet_cache_dir_for(cfg)
        _save_sheet_cache(
            cache_dir, "spread123", ["25年12月", "26年1月", "26年2月"]
        )
        binding = SheetListBinding(cfg, lambda: "spread123")
        combo = _FakeCombo()
        result = binding.populate_combo_on_open(combo)
        assert result == 3
        assert combo.values == ("25年12月", "26年1月", "26年2月")
        assert combo.current_index == 2

    def test_returns_zero_when_cache_names_empty(self, tmp_path: Path) -> None:
        """cache schema は valid だが names が空リストの場合は populate しない。"""
        cfg = _make_config_path(tmp_path)
        cache_dir = _sheet_cache_dir_for(cfg)
        # save() の引数を空リストで呼ぶ (edge case)
        _save_sheet_cache(cache_dir, "spread123", [])
        binding = SheetListBinding(cfg, lambda: "spread123")
        combo = _FakeCombo()
        result = binding.populate_combo_on_open(combo)
        assert result == 0


class TestSaveAfterFetch:
    def test_no_op_when_config_path_is_none(self) -> None:
        """config_path=None でも例外を出さず no-op (AC-8)。"""
        binding = SheetListBinding(None, lambda: "spread123")
        # 例外が出ないことだけ検証
        binding.save_after_fetch(["25年12月"])

    def test_no_op_when_spreadsheet_id_empty(self, tmp_path: Path) -> None:
        """spreadsheet_id 未設定でも例外を出さず no-op。"""
        cfg = _make_config_path(tmp_path)
        binding = SheetListBinding(cfg, lambda: "")
        binding.save_after_fetch(["25年12月"])
        # cache dir に何も書かれないことを確認
        cache_dir = _sheet_cache_dir_for(cfg)
        assert not cache_dir.exists() or not any(cache_dir.iterdir())

    def test_save_then_round_trip_via_read_fetched_at(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """save → read_fetched_at で round-trip 確認 (AC-2)。

        Evaluator MEDIUM 指摘対応: 旧版は壁時計 5 秒ウィンドウを使っており CI 高負荷
        時にフレーク可能性があった。``sheet_list_cache.save`` 内部の
        ``datetime.now`` を monkeypatch で固定し、ISO 文字列までを deterministic
        に検証する。
        """
        cfg = _make_config_path(tmp_path)
        fixed = _dt.datetime(2026, 5, 15, 14, 0, 0, tzinfo=_dt.UTC)

        class _FrozenDateTime(_dt.datetime):
            @classmethod
            def now(cls, tz: _dt.tzinfo | None = None) -> _dt.datetime:  # type: ignore[override]
                return fixed if tz is _dt.UTC else fixed.astimezone(tz)

        # sheet_list_cache.save が参照する datetime を差し替え
        from wiseman_hub.cloud import sheet_list_cache as _slc_module

        monkeypatch.setattr(_slc_module._dt, "datetime", _FrozenDateTime)

        binding = SheetListBinding(cfg, lambda: "spread123")
        binding.save_after_fetch(["25年12月", "26年1月"])
        ts = binding.read_fetched_at()
        # 完全一致 (5 秒ウィンドウなし、壁時計依存ゼロ)
        assert ts == fixed


class TestReadFetchedAt:
    def test_returns_none_when_config_path_is_none(self) -> None:
        binding = SheetListBinding(None, lambda: "spread123")
        assert binding.read_fetched_at() is None

    def test_returns_none_when_spreadsheet_id_empty(
        self, tmp_path: Path
    ) -> None:
        cfg = _make_config_path(tmp_path)
        binding = SheetListBinding(cfg, lambda: None)
        assert binding.read_fetched_at() is None

    def test_returns_none_when_cache_missing(self, tmp_path: Path) -> None:
        cfg = _make_config_path(tmp_path)
        binding = SheetListBinding(cfg, lambda: "spread123")
        assert binding.read_fetched_at() is None

    def test_returns_none_when_cache_corrupted(self, tmp_path: Path) -> None:
        """破損 JSON は warn-only で None を返す (AC-9)。"""
        cfg = _make_config_path(tmp_path)
        cache_dir = _sheet_cache_dir_for(cfg)
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "spread123.json").write_text(
            "not a valid json", encoding="utf-8"
        )
        binding = SheetListBinding(cfg, lambda: "spread123")
        assert binding.read_fetched_at() is None


class TestFormatSyncLabel:
    def test_unknown_when_cache_missing(self, tmp_path: Path) -> None:
        cfg = _make_config_path(tmp_path)
        binding = SheetListBinding(cfg, lambda: "spread123")
        label = binding.format_sync_label()
        assert label == "シート一覧 最終更新: 不明"

    def test_just_now_when_freshly_saved(self, tmp_path: Path) -> None:
        cfg = _make_config_path(tmp_path)
        binding = SheetListBinding(cfg, lambda: "spread123")
        binding.save_after_fetch(["26年1月"])
        label = binding.format_sync_label()
        assert "シート一覧 最終更新:" in label
        assert "たった今" in label

    def test_custom_prefix(self, tmp_path: Path) -> None:
        cfg = _make_config_path(tmp_path)
        binding = SheetListBinding(cfg, lambda: "spread123")
        binding.save_after_fetch(["26年1月"])
        label = binding.format_sync_label(prefix="シート同期")
        assert label.startswith("シート同期: ")

    def test_now_fn_injection_freezes_time(self, tmp_path: Path) -> None:
        """now_fn 注入で時刻を freeze できる (テスト容易性)。"""
        cfg = _make_config_path(tmp_path)
        # save 時刻を ISO で直接書く
        cache_dir = _sheet_cache_dir_for(cfg)
        cache_dir.mkdir(parents=True, exist_ok=True)
        fixed_fetched = _dt.datetime(
            2026, 5, 15, 14, 0, 0, tzinfo=_dt.UTC
        )
        payload = {
            "spreadsheet_id": "spread123",
            "sheet_names": ["26年1月"],
            "fetched_at": fixed_fetched.isoformat(),
        }
        (cache_dir / "spread123.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
        # 30 分後の now を注入 → 「30 分前」と表示されるはず
        fixed_now = fixed_fetched + _dt.timedelta(minutes=30)
        binding = SheetListBinding(
            cfg, lambda: "spread123", now_fn=lambda: fixed_now
        )
        label = binding.format_sync_label()
        assert "30 分前" in label


class TestFormatSyncLabelWithError:
    def test_appends_failure_marker(self, tmp_path: Path) -> None:
        """更新失敗時マーカー併記 (Issue #238 Phase 1 review HIGH-1 対応)。"""
        cfg = _make_config_path(tmp_path)
        binding = SheetListBinding(cfg, lambda: "spread123")
        binding.save_after_fetch(["26年1月"])
        label = binding.format_sync_label_with_error("ConnectionError")
        assert "※更新失敗 (ConnectionError)" in label
        # 既存 cache の fetched_at も併記される
        assert "シート一覧 最終更新:" in label

    def test_works_with_no_cache(self, tmp_path: Path) -> None:
        """cache 不在でも failure marker は表示される (「不明」+ マーカー)。"""
        cfg = _make_config_path(tmp_path)
        binding = SheetListBinding(cfg, lambda: "spread123")
        label = binding.format_sync_label_with_error("TimeoutError")
        assert "不明" in label
        assert "※更新失敗 (TimeoutError)" in label


class TestProviderIsCalledEachTime:
    """get_spreadsheet_id は毎呼出で問合せる (config 再読込で値変動を許容)。"""

    def test_provider_invoked_each_call(self, tmp_path: Path) -> None:
        cfg = _make_config_path(tmp_path)
        call_count = 0
        # provider が呼ばれる度に異なる ID を返す動作を確認
        ids = ["spread_old", "spread_old", "spread_new"]

        def _provider() -> str:
            nonlocal call_count
            value = ids[call_count]
            call_count += 1
            return value

        binding = SheetListBinding(cfg, _provider)
        binding.read_fetched_at()  # 1
        binding.read_fetched_at()  # 2
        binding.read_fetched_at()  # 3
        assert call_count == 3

    def test_provider_returns_none_treated_as_unset(
        self, tmp_path: Path
    ) -> None:
        """provider が None を返した場合も「未設定」扱い。"""
        cfg = _make_config_path(tmp_path)
        binding = SheetListBinding(cfg, lambda: None)
        assert binding.read_fetched_at() is None
        combo = _FakeCombo()
        assert binding.populate_combo_on_open(combo) == 0


# 既存 sheet_list_cache テストとの統合確認: 同じ cache を直接 save した後で
# binding 経由で read できる (後方互換)。
class TestBackwardCompatWithSheetListCache:
    def test_can_read_cache_written_by_direct_api(self, tmp_path: Path) -> None:
        cfg = _make_config_path(tmp_path)
        # 直接 save_after_fetch ではなく低レベル API で書く (既存コード経路)
        cache_dir = _sheet_cache_dir_for(cfg)
        _save_sheet_cache(cache_dir, "spread_legacy", ["25年12月", "26年1月"])
        binding = SheetListBinding(cfg, lambda: "spread_legacy")
        combo = _FakeCombo()
        result = binding.populate_combo_on_open(combo)
        assert result == 2
        ts = binding.read_fetched_at()
        assert ts is not None


# pytest collection error 回避のため明示エクスポート不要 (class ベースなので自動収集)。
__all__: list[str] = []


# 動作確認用 sanity check: 直接実行で簡易動作確認できるようにする (test ではない)
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
