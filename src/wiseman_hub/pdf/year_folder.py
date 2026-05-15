"""年フォルダ (R<年> / 令和{era}年) の表記揺れ吸収ロジック共通モジュール。

PR-R<年>-C (Session 78): B (Issue #282, PR #283) で実装した R<年> フォルダ名の
表記揺れ吸収ロジックを共通化し、C 側 (suggest_patterns 経由のフォルダ走査) でも
同じ吸収を効かせる。

## 業務背景

業務責任者が NAS 上に作るフォルダ名は表記揺れが多い:

- ``R7`` / ``R７`` / ``Ｒ7`` / ``Ｒ７`` (全角/半角ミックス)
- ``R 7`` / ``R　7`` (半角/全角スペース挿入)
- ``R.7`` / ``R-7`` (区切り文字挿入)
- ``r7`` (小文字)
- ``令和7年`` / ``令和07年`` (年号形式、半角/2桁ゼロパディング)

これらを毎回個別正規表現で対応するのは持続不可能。NFKC 正規化 + 共通 regex で
B/C 両方の機能から呼び出せるようにする。

## 関数の使い分け

- ``western_to_reiwa(year)``: 西暦 → 令和年の単純計算 (2019 = R1)
- ``parse_year_folder_name(name)``: フォルダ名から年数値を抽出 (R7 / 令和7年 等)、
  非該当なら ``None``
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final

# R<年> フォルダ名の表記揺れ吸収用正規表現 (NFKC 正規化後にマッチ判定)。
# NFKC で半角化された後の "R7" / "R 7" / "R.7" / "R-7" / "r7" をカバー。
# (原文 "R７" / "Ｒ7" / "Ｒ７" / "R　7" は NFKC で "R7" / "R 7" に正規化される)
_R_YEAR_RE: Final = re.compile(r"^[Rr][\s.\-]*(\d+)$")

# 令和{era}年 形式の正規表現 (NFKC 後)。"令和7年" / "令和07年" 等。
_REIWA_YEAR_RE: Final = re.compile(r"^令和\s*(\d+)\s*年$")


def western_to_reiwa(year: int) -> int:
    """西暦 → 令和年（2019 = R1）。

    PR-R<年>-C: B (``checklist_b.western_to_reiwa``) と C
    (``checklist_c.western_to_reiwa``) で重複実装されていた式を 1 本化。
    """
    return year - 2018


def parse_year_folder_name(name: str) -> int | None:
    """フォルダ名から年数値を抽出。表記揺れを吸収。

    対応する表記揺れ:
        - R7 / R７ / Ｒ7 / Ｒ７ (全角/半角ミックス) → 7
        - R 7 / R　7 (半角/全角スペース挿入) → 7
        - R.7 / R-7 (区切り文字挿入) → 7
        - r7 (小文字) → 7
        - 令和7年 / 令和07年 / 令和　7　年 (年号形式) → 7

    実装: ``unicodedata.normalize("NFKC", ...)`` で全角→半角統一後、
    R<年> または 令和<年>年 正規表現で年数値を抽出。

    PR-R<年>-C: B の ``checklist_b._parse_year_folder_name`` を共通モジュールに
    切り出し、C の ``staff_path_scanner`` フォルダ走査でも利用可能に。

    Returns:
        int (年数値、例: ``7``) または None (R<年> / 令和<年>年 形式として解釈不能)
    """
    nfkc = unicodedata.normalize("NFKC", name.strip())

    # R<年> 形式 (R7 / r7 / R.7 / R 7 等)
    m = _R_YEAR_RE.match(nfkc)
    if m is not None:
        return int(m.group(1))

    # 令和<年>年 形式
    m = _REIWA_YEAR_RE.match(nfkc)
    if m is not None:
        return int(m.group(1))

    return None
