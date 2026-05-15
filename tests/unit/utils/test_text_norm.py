"""``normalize_lookup_key`` の表記揺れ吸収テスト（PR-γ v1 → v2 仕様）。

業務責任者の運用継続性のため、lookup 用正規化が以下の表記揺れを吸収することを保証:

- 全角/半角空白の同一視
- **空白有無の同一視 (PR-γ v2 で追加、Session 78 実機デモで判明)**
- 全角/半角英数の同一視
- 全角/半角括弧の同一視
- 半角/全角カナの同一視

PR-γ v2 仕様変更: 「連続空白を半角 1 つに統一」→「**全空白を完全除去**」。
実機 (`姫路医療生活協同組合 あぼし` vs `姫路医療生活協同組合　あぼし` vs
`姫路医療生活協同組合あぼし`) で 3 パターン共存しており、業務責任者が
「あ、ここでスペース入れてた / 入れてなかった」を意識せず登録できる必要がある。

過剰正規化（大文字小文字統一・業務 noise 除去等）はしない契約は維持。
"""

from __future__ import annotations

import pytest

from wiseman_hub.utils.text_norm import normalize_lookup_key


class TestSpaceVariants:
    """全角空白 (\\u3000) / 半角空白 (\\u0020) / 空白なし の三者同一視 (PR-γ v2)。"""

    def test_full_width_space_removed(self) -> None:
        # PR-γ v2: NFKC で全角→半角空白に変換後、全空白を除去
        assert normalize_lookup_key("a　b") == "ab"

    def test_half_width_space_removed(self) -> None:
        assert normalize_lookup_key("a b") == "ab"

    def test_no_space_unchanged(self) -> None:
        assert normalize_lookup_key("ab") == "ab"

    def test_three_patterns_compare_equal(self) -> None:
        """全角 / 半角 / 空白なし の 3 パターンが全て同一視 (PR-γ v2 新規)。"""
        full = normalize_lookup_key("介護相談支援センター　LEBEN")
        half = normalize_lookup_key("介護相談支援センター LEBEN")
        none = normalize_lookup_key("介護相談支援センターLEBEN")
        assert full == half == none

    def test_pt_staff_name_three_patterns_equal(self) -> None:
        full = normalize_lookup_key("PT　宮下")
        half = normalize_lookup_key("PT 宮下")
        none = normalize_lookup_key("PT宮下")
        assert full == half == none


class TestSpaceCollapsing:
    """空白を完全除去 (PR-γ v2 仕様)。"""

    def test_consecutive_spaces_all_removed(self) -> None:
        assert normalize_lookup_key("a  b   c") == "abc"

    def test_leading_and_trailing_space_removed(self) -> None:
        assert normalize_lookup_key("  hello  ") == "hello"

    def test_tab_and_newline_removed(self) -> None:
        assert normalize_lookup_key("a\tb\nc") == "abc"

    def test_mixed_whitespace_all_removed(self) -> None:
        assert normalize_lookup_key("a 　\tb\n　c") == "abc"


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

    def test_pure_ascii_no_space_unchanged(self) -> None:
        assert normalize_lookup_key("helloworld") == "helloworld"


class TestRegressionCases:
    """過去 PR / 実機デモで実際に発生した表記揺れケースの regression 防止。"""

    @pytest.mark.parametrize(
        ("registered", "queried"),
        [
            # PR #184 (PR-γ v1): 半角空白版 vs 全角空白版
            ("介護相談支援センター LEBEN", "介護相談支援センター　LEBEN"),
            # PT 担当者名の表記揺れ（NAS フォルダ vs スプレッドシート登録）
            ("PT 宮下", "PT　宮下"),
            # PR-γ v2: 連続空白も全除去
            ("a b", "a  b"),
            # Session 78 実機デモで判明: 全角 vs 半角
            ("姫路医療生活協同組合 あぼし", "姫路医療生活協同組合　あぼし"),
            # Session 78 実機デモで判明: 空白あり vs 空白なし (PR-γ v2 新規対応)
            ("姫路医療生活協同組合 あぼし", "姫路医療生活協同組合あぼし"),
            ("姫路医療生活協同組合　あぼし", "姫路医療生活協同組合あぼし"),
        ],
    )
    def test_registered_and_queried_match_after_normalization(
        self, registered: str, queried: str
    ) -> None:
        assert normalize_lookup_key(registered) == normalize_lookup_key(queried)
