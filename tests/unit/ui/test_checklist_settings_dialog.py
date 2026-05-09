"""ChecklistSettingsDialog の TOML フラグメント round-trip テスト。

PR #179 (PR-α v3) で追加された ``suggest_patterns`` を設定ダイアログ経由で
読み書きできることを保証する（regression 防止）。

PR #179 までは `_staff_to_toml` / `_parse_staff_toml` が `suggest_patterns` を
扱わないため、設定ダイアログを開いて保存すると永続化済みの suggest_patterns が
消える事故が起きうる。本テストはその修正を固定する。
"""

from __future__ import annotations

import pytest

from wiseman_hub.config import ReportStaffEntry
from wiseman_hub.ui.checklist_settings_dialog import (
    _parse_staff_toml,
    _staff_to_toml,
)


class TestStaffTomlRoundTrip:
    def test_suggest_patterns_round_trip_preserves_list(self) -> None:
        original = {
            "宮下": ReportStaffEntry(
                base_dir="\\\\Tera-station\\share\\PT 宮下",
                suggest_patterns=[
                    "リハ経過報告書/令和{era}年/リハ経過報告書*{month}月*.xlsx",
                ],
            ),
        }
        text = _staff_to_toml(original)
        roundtrip = _parse_staff_toml(text)
        assert roundtrip["宮下"].base_dir == original["宮下"].base_dir
        assert roundtrip["宮下"].suggest_patterns == original["宮下"].suggest_patterns

    def test_multi_staff_with_multiple_patterns(self) -> None:
        original = {
            "小島": ReportStaffEntry(
                base_dir="\\\\Tera-station\\share\\PT 小島",
                suggest_patterns=[
                    "リハ経過報告書(新)/経過報告書*令和{era}年{month}月*.xlsx",
                    "リハ経過報告書(旧)/令和{era}年度/経過報告書*{month}月*.xlsx",
                ],
            ),
            "OT 小林": ReportStaffEntry(
                base_dir="\\\\Tera-station\\share\\OT小林",
                suggest_patterns=["経過報告書/R{era}/*{month}月*.xlsx"],
            ),
        }
        text = _staff_to_toml(original)
        roundtrip = _parse_staff_toml(text)
        assert set(roundtrip.keys()) == {"小島", "OT 小林"}
        assert roundtrip["小島"].suggest_patterns == original["小島"].suggest_patterns
        assert roundtrip["OT 小林"].suggest_patterns == original["OT 小林"].suggest_patterns

    def test_empty_suggest_patterns_emits_empty_list(self) -> None:
        original = {
            "test": ReportStaffEntry(base_dir="C:/x", suggest_patterns=[]),
        }
        text = _staff_to_toml(original)
        assert "suggest_patterns = []" in text
        roundtrip = _parse_staff_toml(text)
        assert roundtrip["test"].suggest_patterns == []

    def test_deprecated_fields_preserved_when_non_empty(self) -> None:
        """旧 MVP 互換: year_subfolder_template / file_template が非空なら保持。"""
        original = {
            "legacy": ReportStaffEntry(
                base_dir="C:/legacy",
                suggest_patterns=[],
                year_subfolder_template="令和{era}年",
                file_template="経過報告書*{month}月*.xlsx",
            ),
        }
        text = _staff_to_toml(original)
        roundtrip = _parse_staff_toml(text)
        assert roundtrip["legacy"].year_subfolder_template == "令和{era}年"
        assert roundtrip["legacy"].file_template == "経過報告書*{month}月*.xlsx"

    def test_deprecated_fields_omitted_when_empty(self) -> None:
        """新規入力では deprecated フィールドが空なら出力しない（dump 結果が読みやすい）。"""
        original = {
            "new": ReportStaffEntry(
                base_dir="C:/x",
                suggest_patterns=["a/*.xlsx"],
            ),
        }
        text = _staff_to_toml(original)
        assert "year_subfolder_template" not in text
        assert "file_template" not in text

    def test_quoted_key_with_space_round_trip(self) -> None:
        """key にスペース・特殊文字を含むケース（"PT 宮下" など）の round-trip。"""
        original = {
            "PT 宮下": ReportStaffEntry(
                base_dir="C:/x",
                suggest_patterns=["a/*.xlsx"],
            ),
        }
        text = _staff_to_toml(original)
        roundtrip = _parse_staff_toml(text)
        assert "PT 宮下" in roundtrip
        assert roundtrip["PT 宮下"].suggest_patterns == ["a/*.xlsx"]


class TestStaffTomlValidation:
    def test_suggest_patterns_must_be_list(self) -> None:
        bad = '["x"]\nbase_dir = "C:/x"\nsuggest_patterns = "not a list"\n'
        with pytest.raises(TypeError, match="suggest_patterns must be a list"):
            _parse_staff_toml(bad)

    def test_suggest_patterns_elements_must_be_strings(self) -> None:
        bad = '["x"]\nbase_dir = "C:/x"\nsuggest_patterns = [1, 2]\n'
        with pytest.raises(TypeError, match="elements must be strings"):
            _parse_staff_toml(bad)

    def test_empty_text_returns_empty_dict(self) -> None:
        assert _parse_staff_toml("") == {}
        assert _parse_staff_toml("   \n  ") == {}


# ---------------------------------------------------------------------------
# Phase 2-α (Issue #238) review 反映 (pr-test 3.1 rating 7):
# _record_sync_timestamp 呼び出し位置を直接検証する pure-logic test。
# Tk 不要 (関数を直接 import + 副作用ファイルの存在確認だけ)。
# ---------------------------------------------------------------------------


class TestRecordSyncTimestamp:
    """Phase 2-α (Issue #238): sync timestamp 記録の呼び出し位置検証。

    PR レビューで指摘された通り、push_routing / pull_routing / pull_report_staff の
    成功時に **だけ** ``_record_sync_timestamp`` が呼ばれることを保証する。
    将来の refactor で呼び出し位置が誤って verification 前に移動した場合、Launcher の
    sync_summary が「失敗した同期」を「成功」と誤認する regression を防ぐ。

    完全な GCS push/pull のモックは別 PR (Phase 2-β / 3) で対応予定。本 test は
    helper 関数 ``_record_sync_timestamp`` の単体動作を pure-logic で fix する。
    """

    def _make_config_path(self, tmp_path):  # type: ignore[no-untyped-def]
        cfg = tmp_path / "wiseman-hub" / "config" / "default.toml"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text("", encoding="utf-8")
        return cfg

    def test_record_sync_timestamp_writes_under_sync_cache_dir(
        self, tmp_path,
    ) -> None:  # type: ignore[no-untyped-def]
        """`_record_sync_timestamp(config_path, name)` 呼出で
        ``<config_parent_parent>/cache/sync/<name>.json`` が作成される。"""
        from wiseman_hub.cloud.sync_label import (
            read_sync_timestamp,
            sync_cache_dir_for,
        )
        from wiseman_hub.ui.checklist_settings_dialog import (
            _record_sync_timestamp,
        )

        cfg = self._make_config_path(tmp_path)
        _record_sync_timestamp(cfg, "mapping_routing")

        sync_dir = sync_cache_dir_for(cfg)
        json_path = sync_dir / "mapping_routing.json"
        assert json_path.exists()
        # 書き込まれた timestamp が tz-aware で読み出せる
        ts = read_sync_timestamp(sync_dir, "mapping_routing")
        assert ts is not None and ts.tzinfo is not None

    @pytest.mark.parametrize("name", ["mapping_routing", "report_staff"])
    def test_record_sync_timestamp_per_name_isolated(
        self, tmp_path, name: str,
    ) -> None:  # type: ignore[no-untyped-def]
        """name ごとに別ファイルに書かれる (mapping_routing と report_staff の混線無し)。"""
        from wiseman_hub.cloud.sync_label import sync_cache_dir_for
        from wiseman_hub.ui.checklist_settings_dialog import (
            _record_sync_timestamp,
        )

        cfg = self._make_config_path(tmp_path)
        _record_sync_timestamp(cfg, name)

        sync_dir = sync_cache_dir_for(cfg)
        assert (sync_dir / f"{name}.json").exists()
        # 他の name のファイルは作成されない
        other = "report_staff" if name == "mapping_routing" else "mapping_routing"
        assert not (sync_dir / f"{other}.json").exists()

    def test_record_sync_timestamp_invalid_name_raises(
        self, tmp_path,
    ) -> None:  # type: ignore[no-untyped-def]
        """write_sync_timestamp の name validation が _record_sync_timestamp 経由でも有効。

        将来 caller が誤って path traversal を含む name を渡しても構造的に弾かれる。
        """
        from wiseman_hub.ui.checklist_settings_dialog import (
            _record_sync_timestamp,
        )

        cfg = self._make_config_path(tmp_path)
        with pytest.raises(ValueError):
            _record_sync_timestamp(cfg, "../traversal")

    def test_handler_calls_record_at_correct_position_in_source(self) -> None:
        """source code static check: 3 成功 path の直前に
        ``_record_sync_timestamp`` 呼出が存在する。

        将来の refactor で呼出位置が verification 前 / error path に移動した場合の
        regression を防ぐ source-level test。完全な mock 経路の test は Phase 2-β。
        """
        from pathlib import Path

        src = (
            Path(__file__).parent.parent.parent.parent
            / "src"
            / "wiseman_hub"
            / "ui"
            / "checklist_settings_dialog.py"
        ).read_text(encoding="utf-8")
        # 3 箇所の成功 path で _record_sync_timestamp が呼ばれている
        assert src.count('_record_sync_timestamp(self._config_path, ') == 3
        # 各成功 path で showinfo の直前に置かれている
        assert (
            '_record_sync_timestamp(self._config_path, "mapping_routing")'
            in src
        )
        assert (
            '_record_sync_timestamp(self._config_path, "report_staff")'
            in src
        )
