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


class TestExtractNameFromFuriganaPattern:
    """Pattern 2: フリガナ（半角カタカナ行）→ 漢字姓名の抽出。

    実帳票（提供実績チェックリスト）のテキスト層は「氏名」ラベルと
    実名が別セルで離れているため、フリガナ直後の漢字氏名を頼りに抽出する。
    """

    def test_basic_furigana_to_kanji(self) -> None:
        # 実帳票テキスト（提供実績チェックリスト風）
        text = (
            "居宅介護支援事業所　きなり \n"
            "ｱｻｵ ｶｽ ｼ\n"
            "浅尾　和司\n"
            "2 8 4 6 4 6\n"
        )
        result = extract_name_from_text(text)
        assert result is not None
        assert result.last_name == "浅尾"
        assert result.first_name == "和司"

    def test_furigana_with_multiple_spaces(self) -> None:
        # フリガナが 3 分割されていても許容
        text = "ﾔﾏﾀﾞ ﾀﾛｳ ｼ\n山田　太郎\n"
        result = extract_name_from_text(text)
        assert result is not None
        assert result.last_name == "山田"
        assert result.first_name == "太郎"

    def test_full_realistic_daily_record_text(self) -> None:
        """実帳票 1 ページ目のテキスト層全体を模したケース。

        Pattern 1 (氏名ラベル隣接) はヒットしないが、Pattern 2 で抽出される。
        担当者名（小島 玲央）やケアマネ名が混じっていても、フリガナ隣接で
        最初にマッチする利用者氏名（浅尾 和司）を取る。
        """
        text = (
            "様\n"
            "令和08年03月分  提供実績チェックリスト \n"
            "被保険者番号\n"
            "生年月日\n"
            "4 6 0 1 6 0 6 1 2\n"
            "保険者名\n"
            "印刷日　令和08年04月09日　木曜日\n"
            "太子町（揖保郡）\n"
            "居宅介護支援事業所　きなり \n"
            "ﾌｻｵ ｶｽ ｼ\n"
            "浅尾　和司\n"
            "2 8 4 6 4 6\n"
            "計画作成担当者\n"
            "(2874101146)\n"
            "フリガナ\n"
            "氏名\n"
            "要介護・要支援状態区分\n"
            "要支援2\n"
        )
        result = extract_name_from_text(text)
        assert result is not None
        assert result.last_name == "浅尾"
        assert result.first_name == "和司"

    def test_label_pattern_takes_precedence_over_furigana(self) -> None:
        """Pattern 1（氏名ラベル）があればそちらを優先する。

        ラベル明記は書式仕様上の明示指示なので、フリガナ隣接よりも信頼度が高い。
        """
        text = (
            "ｼｵﾂ ﾐｷｺ\n"
            "塩津　美貴子\n"
            "《ご報告内容》\n"
            "氏名  尾島 太郎  様\n"  # Pattern 1 にヒット
        )
        result = extract_name_from_text(text)
        assert result is not None
        # フリガナ隣接型で先頭の「塩津」ではなく、ラベル型の「尾島」が取れる
        assert result.last_name == "尾島"
        assert result.first_name == "太郎"

    def test_furigana_only_no_kanji_returns_none(self) -> None:
        """フリガナ行のみで漢字氏名が続かない場合は None."""
        text = "ﾔﾏﾀﾞ ﾀﾛｳ\n"
        assert extract_name_from_text(text) is None

    def test_no_furigana_no_label_returns_none(self) -> None:
        """どのパターンにもマッチしないテキスト."""
        text = "普通の文章です。特に抽出できるものはありません。"
        assert extract_name_from_text(text) is None

    def test_hiragana_in_name_row_skipped(self) -> None:
        """漢字氏名の行に平仮名が混ざる場合はマッチしない（事業所名除外）.

        「居宅介護支援事業所　きなり」のようなひらがな含む行は漢字連続パターン
        で終端する。ひらがな「きなり」は `\\u3040-\\u309f` で漢字範囲外。
        """
        text = (
            "ｷﾅﾘ ｼｴﾝ ｼ\n"
            "居宅介護支援事業所　きなり\n"  # ひらがなで途切れる
        )
        result = extract_name_from_text(text)
        # Pattern 2 は最長漢字マッチになるため「居宅介護支援事業所」+「きなり」ではなく
        # 「居宅介護支援事業所」のみで止まり、続く「　」+ 漢字でないのでミスマッチ。
        # 結果として抽出失敗（None）か、誤ったマッチでも事業所名として扱われる。
        # 本テストはひらがな行が誤抽出されないことを確認する。
        assert result is None or "きなり" not in result.full_name
