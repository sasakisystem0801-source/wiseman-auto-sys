"""文字列の表記揺れを吸収する正規化レイヤー（lookup 用）。

業務責任者がスプレッドシートに登録する居宅名 / 担当者名は表記揺れが多い:

- 全角空白 (``\\u3000``) vs 半角空白 (``\\u0020``)
- 全角英数字 vs 半角英数字
- 全角括弧 ``（）`` vs 半角括弧 ``()``
- 前後 / 連続 空白
- 半角カタカナ vs 全角カタカナ

これらを毎回個別 dict key 追加で対応するのは持続不可能。lookup 時に共通正規化を
通すことで「同一視」を業務責任者の意識から外す。

スコープ:

- ``ChecklistConfig.facility_routing`` / ``report_staff`` の lookup
- 過剰正規化（大文字小文字統一・業務 noise 除去等）はしない:

  - 業務側が「LEBEN」「leben」を異なる事業所として扱う可能性を尊重
  - ``(メール)`` / ``※持参`` 等の業務 noise 除去は別 PR (PR-γ v3) で
    オプション化して導入する

既存の正規化関数 (``matcher.normalize_name`` / ``facility_resolver.normalize_name`` /
``staff_path_scanner._normalize_nfc`` / ``scripts.draft_facility_mapping.normalize_core``)
は本関数に統合候補だが、regression リスクのため別 PR (PR-γ v2) で対応する。
"""

from __future__ import annotations

import re
import unicodedata

_MULTI_SPACE = re.compile(r"\s+")


def normalize_lookup_key(s: str) -> str:
    """lookup 用の表記揺れ吸収正規化。

    手順:

    1. Unicode NFKC: 全角英数 → 半角、全角 ``（）`` → 半角 ``()``、
       半角カナ → 全角カナ、全角空白 (``\\u3000``) → 半角空白 (``\\u0020``) 等
    2. 連続空白（``\\s+`` 全種類）を単一の半角スペースに統一
    3. 前後の空白を trim
    4. 空文字列はそのまま空文字列を返す

    用途: ``ChecklistConfig.facility_routing`` / ``report_staff`` の lookup。
    保存時 (``load_config``) と参照時 (``plan_c_placement``) の両方で
    本関数を通すことで、業務責任者が表記揺れを意識せず登録・運用できる。
    """
    if not s:
        return s
    s = unicodedata.normalize("NFKC", s)
    s = _MULTI_SPACE.sub(" ", s).strip()
    return s
