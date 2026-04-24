"""PDF ページのテキスト層から利用者氏名を抽出する。

Wiseman 系帳票（提供実績チェックリスト / 運動機能向上計画書 / 利用経過報告書）は
電子出力 PDF でテキスト層を含むため、OCR 不要で `page.get_text()` から氏名を取得できる。

抽出パターン: `氏名 {姓} {名} 様` （姓と名の間は半角/全角空白混在可）

経過報告書のように「宛先ケアマネ名」と「対象利用者名」が同一ページに存在する場合、
前者はラベル無しで記載されるため、「氏名」ラベル直後の氏名のみが抽出対象となる。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

import fitz

# 姓・名に使える文字: 空白・様・句読点以外。
# 実運用で必要十分な粒度として [^\s　様] を採用。
_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"氏名[\s　]*([^\s　様]+)[\s　]+([^\s　様]+)[\s　]*様"
)


@dataclass(frozen=True)
class ExtractedName:
    """抽出された氏名。"""

    last_name: str
    first_name: str

    @property
    def full_name(self) -> str:
        """姓と名を半角空白区切りで連結した表示用フルネーム。"""
        return f"{self.last_name} {self.first_name}"


def extract_name_from_text(text: str) -> ExtractedName | None:
    """テキストから `氏名 姓 名 様` パターンを抽出する。

    複数マッチする場合は最初の一致を返す（通常は 1 ページ 1 利用者）。
    ラベル無しの他者氏名（例: 経過報告書の宛先ケアマネ名）は対象外。
    """
    if not text:
        return None
    match = _NAME_PATTERN.search(text)
    if match is None:
        return None
    return ExtractedName(last_name=match.group(1), first_name=match.group(2))


def extract_name_from_page(page: fitz.Page) -> ExtractedName | None:
    """`fitz.Page` からテキストを取得して氏名抽出する。

    テキスト層が存在しないページ（スキャン画像のみ）では None を返す。
    """
    text = page.get_text()
    return extract_name_from_text(text)
