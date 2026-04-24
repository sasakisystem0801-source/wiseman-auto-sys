"""PDF ページのテキスト層から利用者氏名を抽出する。

Wiseman 系帳票（提供実績チェックリスト / 運動機能向上計画書 / 利用経過報告書）は
電子出力 PDF でテキスト層を含むため、OCR 不要で `page.get_text()` から氏名を取得できる。

## 複数パターンのフォールバック戦略

実帳票のレイアウトは書類ごとに異なり、テキスト層の文字列順序も PDF の
レンダリング実装によってセル順・行順が変わる。単一の正規表現では拾えないため、
優先順に複数パターンを試行する:

1. **Pattern 1 (ラベル隣接型)**: `氏名 姓 名 様`
   運動機能向上計画書 / 利用経過報告書の「氏名」ラベル直後に実名が続くケース。

2. **Pattern 2 (フリガナ隣接型)**: フリガナ行（半角カタカナ）の直後に漢字姓名
   提供実績チェックリストのように「氏名」ラベルと実名が別セルで離れている
   帳票構造に対応。帳票上段の利用者氏名欄で、フリガナと漢字氏名が上下に
   並ぶレイアウトを頼りに抽出する。

いずれのパターンも他者氏名（ケアマネ宛先、担当者名等）の誤抽出を避けるため、
ラベル or フリガナとの位置関係に依存する。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

import fitz

# Pattern 1: 「氏名 姓 名 様」ラベル隣接型
# 姓・名に使える文字: 空白・様・句読点以外。
_NAME_PATTERN_LABEL: Final[re.Pattern[str]] = re.compile(
    r"氏名[\s　]*([^\s　様]+)[\s　]+([^\s　様]+)[\s　]*様"
)

# Pattern 2: フリガナ（半角カタカナ行）の直後に漢字姓名
# 半角カタカナ: U+FF66-FF9F (ｦ-ﾟ)
# 漢字: U+4E00-9FA5 + 々(U+3005)
# 要件:
#   - フリガナ行は半角カタカナ 2+ 文字、スペースで姓名区切りあり得る
#   - 直後の改行を挟んで「漢字1+ + 全角/半角スペース + 漢字1+」= 姓名
#   - 漢字連続のみで、ひらがな・カタカナ混在（事業所名など）は除外
_NAME_PATTERN_FURIGANA: Final[re.Pattern[str]] = re.compile(
    r"[ｦ-ﾟ][ｦ-ﾟ\s]*[ｦ-ﾟ]\s*\n"
    r"([\u4e00-\u9fa5々]+)[\s\u3000]+([\u4e00-\u9fa5々]+)"
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
    """テキストから氏名を抽出する（複数パターンのフォールバック）。

    試行順:
      1. Pattern 1 (ラベル隣接型): `氏名 姓 名 様`
      2. Pattern 2 (フリガナ隣接型): 半角カタカナ行 → 漢字姓名

    複数マッチする場合は最初の一致を返す（通常は 1 ページ 1 利用者）。
    いずれのパターンも他者氏名（宛先ケアマネ名、担当者名）の誤抽出を避ける設計。
    """
    if not text:
        return None

    # Pattern 1 優先: 「氏名 姓 名 様」が書式仕様上最も信頼できる
    match = _NAME_PATTERN_LABEL.search(text)
    if match is not None:
        return ExtractedName(last_name=match.group(1), first_name=match.group(2))

    # Pattern 2 フォールバック: フリガナ行 + 改行 + 漢字姓名
    match = _NAME_PATTERN_FURIGANA.search(text)
    if match is not None:
        return ExtractedName(last_name=match.group(1), first_name=match.group(2))

    return None


def extract_name_from_page(page: fitz.Page) -> ExtractedName | None:
    """`fitz.Page` からテキストを取得して氏名抽出する。

    テキスト層が存在しないページ（スキャン画像のみ）では None を返す。
    """
    text = page.get_text()
    return extract_name_from_text(text)
