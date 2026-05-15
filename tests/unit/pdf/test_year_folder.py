"""年フォルダ表記揺れ吸収の共通モジュールテスト (PR-R<年>-C)。

B (``checklist_b._parse_year_folder_name``、PR #283) で実装した表記揺れ吸収
ロジックを共通化した ``pdf/year_folder.py`` のテスト。B/C 両方の機能から呼び出せる
共通 API として動作することを保証する。

業務上の重要性: 業務責任者が NAS 上で作るフォルダ名は表記揺れが激しく
(``R7`` / ``Ｒ７`` / ``R 7`` / ``令和7年`` 等)、B でも C でも同じ吸収ロジックが
必要。重複実装を維持すると片方だけ修正されて挙動差が出る (PR #308 で発覚した
B/C resolve_facility 不整合と同じ問題)。
"""

from __future__ import annotations

import pytest

from wiseman_hub.pdf.year_folder import parse_year_folder_name, western_to_reiwa


class TestWesternToReiwa:
    """西暦 → 令和年の単純計算。"""

    def test_2019_is_r1(self) -> None:
        assert western_to_reiwa(2019) == 1

    def test_2025_is_r7(self) -> None:
        assert western_to_reiwa(2025) == 7

    def test_2026_is_r8(self) -> None:
        assert western_to_reiwa(2026) == 8


class TestParseYearFolderName:
    """フォルダ名から年数値を抽出。表記揺れを吸収。"""

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            # 基本パターン
            ("R7", 7),
            ("R8", 8),
            ("R07", 7),  # ゼロパディング
            # 全角/半角ミックス (NFKC 後同一)
            ("R７", 7),
            ("Ｒ7", 7),
            ("Ｒ７", 7),
            # スペース挿入
            ("R 7", 7),
            ("R　7", 7),  # 全角スペース
            # 区切り文字
            ("R.7", 7),
            ("R-7", 7),
            # 小文字
            ("r7", 7),
            # 令和<年>年 形式
            ("令和7年", 7),
            ("令和07年", 7),
            ("令和8年", 8),
            # 令和形式 + スペース
            ("令和 7年", 7),
            ("令和7 年", 7),
        ],
    )
    def test_valid_year_folder_patterns(self, name: str, expected: int) -> None:
        assert parse_year_folder_name(name) == expected

    @pytest.mark.parametrize(
        "name",
        [
            "",  # 空文字
            "R",  # 数字なし
            "7",  # R なし
            "RR7",  # R 連続
            "X7",  # 別アルファベット
            "経過報告書",  # 全く別の文字列
            "令和年",  # 数字なし
            "令和7",  # 「年」抜け
            "R7月",  # 「月」付き (年フォルダではない)
            "リハ経過報告書",
            "(さんわ)三和太郎",  # 利用者フォルダ
        ],
    )
    def test_non_year_folder_returns_none(self, name: str) -> None:
        assert parse_year_folder_name(name) is None

    def test_strip_whitespace(self) -> None:
        """前後の空白は trim される。"""
        assert parse_year_folder_name("  R7  ") == 7
        assert parse_year_folder_name("\tR7\n") == 7

    def test_full_and_half_width_equivalent(self) -> None:
        """全角と半角の組み合わせは全て同一結果。"""
        results = [
            parse_year_folder_name("R7"),
            parse_year_folder_name("R７"),
            parse_year_folder_name("Ｒ7"),
            parse_year_folder_name("Ｒ７"),
            parse_year_folder_name("r7"),
        ]
        assert all(r == 7 for r in results)
