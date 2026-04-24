"""text_name_extractor.py のテスト (TDD: RED → GREEN → Refactor)."""

from __future__ import annotations

import fitz

from wiseman_hub.pdf.text_name_extractor import (
    extract_name_from_page,
    extract_name_from_text,
)


class TestExtractNameFromText:
    """`extract_name_from_text`: 文字列から氏名を抽出。"""

    def test_basic_pattern_ascii_space(self) -> None:
        text = "氏名  塩津 美貴子  様"
        result = extract_name_from_text(text)
        assert result is not None
        assert result.last_name == "塩津"
        assert result.first_name == "美貴子"
        assert result.full_name == "塩津 美貴子"

    def test_basic_pattern_fullwidth_space(self) -> None:
        # 全角スペースが挟まるケース
        text = "氏名　塩津　美貴子　様"
        result = extract_name_from_text(text)
        assert result is not None
        assert result.last_name == "塩津"
        assert result.first_name == "美貴子"

    def test_mixed_space(self) -> None:
        text = "氏名 塩津　美貴子 様"
        result = extract_name_from_text(text)
        assert result is not None
        assert result.last_name == "塩津"

    def test_with_surrounding_text(self) -> None:
        # 実際の帳票では前後に色んなテキストが混ざる
        text = (
            "令和08年03月分 提供実績チェックリスト\n"
            "利用者コード 0000000192 予\n"
            "保険者番号 284646\n"
            "氏名  荒木 千春  様  年齢 70歳 性別 女\n"
            "ささき整形外科デイケアセンター"
        )
        result = extract_name_from_text(text)
        assert result is not None
        assert result.last_name == "荒木"
        assert result.first_name == "千春"

    def test_multiple_names_picks_first_labeled(self) -> None:
        # 経過報告書のように「宛先」と「対象利用者」が両方存在する
        # 「氏名」ラベルが付くのは対象利用者側のみ
        text = (
            "居宅介護支援事業所 きなり\n"
            "市川 拓郎 様\n"  # 宛先（ラベルなし）
            "ささき整形外科デイケアセンター\n"
            "《ご報告内容》\n"
            "氏名  塩津 美貴子  様\n"  # 対象利用者
        )
        result = extract_name_from_text(text)
        assert result is not None
        assert result.last_name == "塩津"
        assert result.first_name == "美貴子"

    def test_returns_none_when_no_name(self) -> None:
        text = "このテキストには氏名情報が含まれていません"
        assert extract_name_from_text(text) is None

    def test_returns_none_on_empty(self) -> None:
        assert extract_name_from_text("") is None

    def test_name_with_middle_space_variation(self) -> None:
        # 姓と名の間が複数空白
        text = "氏名  尾島   太郎  様"
        result = extract_name_from_text(text)
        assert result is not None
        assert result.last_name == "尾島"
        assert result.first_name == "太郎"


class TestExtractNameFromPage:
    """`extract_name_from_page`: fitz.Page から氏名抽出。"""

    def test_extracts_from_real_page(self) -> None:
        doc = fitz.open()
        try:
            page = doc.new_page(width=595, height=842)
            page.insert_text(
                (50, 100), "氏名 塩津 美貴子 様", fontsize=11, fontname="japan-s"
            )
            result = extract_name_from_page(page)
            assert result is not None
            assert result.last_name == "塩津"
            assert result.first_name == "美貴子"
        finally:
            doc.close()

    def test_returns_none_on_blank_page(self) -> None:
        doc = fitz.open()
        try:
            doc.new_page(width=595, height=842)
            page = doc[0]
            assert extract_name_from_page(page) is None
        finally:
            doc.close()
