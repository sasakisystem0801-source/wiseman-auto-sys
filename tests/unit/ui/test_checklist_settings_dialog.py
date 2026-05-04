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
