"""シート一覧キャッシュ (PR-δ v1) のユニットテスト。

cache_dir_for / load / save の round-trip 動作と、破損ケース・edge case を検証。
"""

from __future__ import annotations

import json
from pathlib import Path

from wiseman_hub.cloud.sheet_list_cache import cache_dir_for, load, save


class TestCacheDirFor:
    def test_derives_from_config_path(self, tmp_path: Path) -> None:
        cfg = tmp_path / "wiseman-hub" / "config" / "default.toml"
        result = cache_dir_for(cfg)
        assert result == tmp_path / "wiseman-hub" / "cache" / "sheets"


class TestRoundTrip:
    def test_save_then_load_returns_same_names(self, tmp_path: Path) -> None:
        names = ["25年12月", "26年1月", "26年2月", "26年3月"]
        save(tmp_path, "spread123", names)
        assert load(tmp_path, "spread123") == names

    def test_load_missing_returns_none(self, tmp_path: Path) -> None:
        assert load(tmp_path, "no_such_id") is None

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        nested = tmp_path / "deep" / "nested" / "cache"
        save(nested, "id1", ["a"])
        assert (nested / "id1.json").exists()

    def test_save_overwrites_existing(self, tmp_path: Path) -> None:
        save(tmp_path, "id1", ["old"])
        save(tmp_path, "id1", ["new1", "new2"])
        assert load(tmp_path, "id1") == ["new1", "new2"]


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
