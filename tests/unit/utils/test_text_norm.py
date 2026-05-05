"""``normalize_lookup_key`` の表記揺れ吸収テスト（PR-γ v1）。

業務責任者の運用継続性のため、lookup 用正規化が以下の表記揺れを吸収することを保証:

- 全角/半角空白の同一視
- 全角/半角英数の同一視
- 全角/半角括弧の同一視
- 連続/前後空白の正規化
- 半角/全角カナの同一視

過剰正規化（大文字小文字統一・業務 noise 除去等）はしない契約も固定。
"""

from __future__ import annotations

import pytest

from wiseman_hub.utils.text_norm import normalize_lookup_key


class TestSpaceVariants:
    """全角空白 (\\u3000) と半角空白 (\\u0020) の同一視。"""

    def test_full_width_space_becomes_half_width(self) -> None:
        # NFKC で 　 →   に変換される（標準仕様）
        assert normalize_lookup_key("a　b") == "a b"

    def test_full_width_and_half_width_space_compare_equal(self) -> None:
        full = normalize_lookup_key("介護相談支援センター　LEBEN")
        half = normalize_lookup_key("介護相談支援センター LEBEN")
        assert full == half

    def test_pt_staff_name_with_either_space_compare_equal(self) -> None:
        full = normalize_lookup_key("PT　宮下")
        half = normalize_lookup_key("PT 宮下")
        assert full == half


class TestSpaceCollapsing:
    def test_consecutive_spaces_collapse_to_single(self) -> None:
        assert normalize_lookup_key("a  b   c") == "a b c"

    def test_leading_and_trailing_space_trimmed(self) -> None:
        assert normalize_lookup_key("  hello  ") == "hello"

    def test_tab_and_newline_treated_as_space(self) -> None:
        assert normalize_lookup_key("a\tb\nc") == "a b c"


class TestAlphanumeric:
    """全角英数 → 半角英数（NFKC 標準）。"""

    def test_full_width_alphabet_becomes_half_width(self) -> None:
        assert normalize_lookup_key("ＬＥＢＥＮ") == "LEBEN"

    def test_full_width_digit_becomes_half_width(self) -> None:
        assert normalize_lookup_key("１２３") == "123"

    def test_full_and_half_width_alpha_compare_equal(self) -> None:
        assert normalize_lookup_key("ＡＢＣ") == normalize_lookup_key("ABC")


class TestParens:
    """全角括弧 → 半角括弧（NFKC 標準）。"""

    def test_full_width_parens_become_half_width(self) -> None:
        assert normalize_lookup_key("（メール）") == "(メール)"

    def test_full_and_half_width_parens_compare_equal(self) -> None:
        assert normalize_lookup_key("LEBEN（メール）") == normalize_lookup_key(
            "LEBEN(メール)"
        )


class TestKana:
    """半角カナ → 全角カナ（NFKC 標準）。"""

    def test_half_width_kana_becomes_full_width(self) -> None:
        # ｺｼﾞﾏ (U+FF7A U+FF7C U+FF9E U+FF8F) → コジマ (U+30B3 U+30B8 U+30DE)
        assert normalize_lookup_key("ｺｼﾞﾏ") == "コジマ"


class TestNoOverNormalization:
    """過剰正規化はしない契約（業務側の意味を保つ）。"""

    def test_case_is_preserved(self) -> None:
        assert normalize_lookup_key("LEBEN") != normalize_lookup_key("leben")
        assert normalize_lookup_key("LEBEN") == "LEBEN"
        assert normalize_lookup_key("leben") == "leben"

    def test_mail_suffix_is_preserved(self) -> None:
        assert "(メール)" in normalize_lookup_key("LEBEN(メール)")

    def test_business_noise_persists(self) -> None:
        """※持参 / FAX 等の業務 noise はそのまま保持（除去は別 PR で対応）。"""
        assert "※持参" in normalize_lookup_key("LEBEN(メール)※持参")
        assert "FAX" in normalize_lookup_key("ケアプラン正條（FAX）")


class TestEmptyAndIdempotent:
    def test_empty_string_returns_empty(self) -> None:
        assert normalize_lookup_key("") == ""

    def test_already_normalized_is_idempotent(self) -> None:
        s = "介護相談支援センター LEBEN"
        assert normalize_lookup_key(normalize_lookup_key(s)) == normalize_lookup_key(s)

    def test_pure_ascii_unchanged(self) -> None:
        assert normalize_lookup_key("hello world") == "hello world"


class TestRegressionCases:
    """C 機能業務化 Phase 3 で実際に発生した表記揺れケースの regression 防止。"""

    @pytest.mark.parametrize(
        ("registered", "queried"),
        [
            # PR #184 で投入した半角空白版が、スプレッドシート全角空白版に match する
            ("介護相談支援センター LEBEN", "介護相談支援センター　LEBEN"),
            # PT 担当者名の表記揺れ（NAS フォルダは半角空白、スプレッドシート登録時の揺れに耐える）
            ("PT 宮下", "PT　宮下"),
            # 連続空白
            ("a b", "a  b"),
        ],
    )
    def test_registered_and_queried_match_after_normalization(
        self, registered: str, queried: str
    ) -> None:
        assert normalize_lookup_key(registered) == normalize_lookup_key(queried)
