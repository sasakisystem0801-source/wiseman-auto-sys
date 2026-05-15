"""文字列の表記揺れを吸収する正規化レイヤー。

業務責任者がスプレッドシートに登録する居宅名 / 担当者名 / 利用者名は表記揺れが多い:

- 全角空白 (``\\u3000``) vs 半角空白 (``\\u0020``) vs **空白なし** (PR-γ v2)
- 全角英数字 vs 半角英数字
- 全角括弧 ``（）`` vs 半角括弧 ``()``
- 半角カタカナ vs 全角カタカナ

これらを毎回個別 dict key 追加で対応するのは持続不可能。lookup 時に共通正規化を
通すことで「同一視」を業務責任者の意識から外す。

## PR-γ v2 (Session 78 実機デモ後): 全空白除去仕様への変更

実機デモで ``姫路医療生活協同組合 あぼし`` (半角空白) vs
``姫路医療生活協同組合　あぼし`` (全角空白) vs ``姫路医療生活協同組合あぼし``
(空白なし) の 3 パターン共存が判明。PR-γ v1 の「連続空白を半角 1 つに統一」
仕様では空白あり/なしを救えなかったため、本リビジョンで **全空白除去** に変更。

業務上の正当性: 居宅名・事業所名・人名は「スペースの入れ方は本質ではない」
という業務感覚があり、空白完全除去で問題ない（既に ``matcher.normalize_name``
で人名照合は同仕様で運用していた、PR-γ v2 で lookup 側も統一）。

## 関数の使い分け

- ``normalize_lookup_key``: NFKC + 全空白除去。居宅名 / 担当者名 / 人名 / sheet 名
  等の同一視 lookup 全般。本ファイル群の主用途。
- ``normalize_for_path``: NFKC のみ、空白保持。フォルダ名 / ファイル名比較用
  (``staff_path_scanner`` 等で SMB NFC/NFD 揺れ + 全角/半角揺れの吸収)。

``facility_resolver.normalize_name`` は alias / 部分一致で「語境界」が必要な
別仕様のため本ファイルでは公開しない。statically 1 関数のためインライン維持。

## 統合した既存関数 (PR-γ v2 で集約)

- ``matcher.normalize_name`` (NFKC + 空白除去) → ``normalize_lookup_key`` と同等、import で統一
- ``checklist_b._normalize_name`` (NFKC **欠落** + 空白除去) → NFKC 加算でバグ修正
- ``checklist_c._normalize_name`` (NFKC **欠落** + 空白除去) → NFKC 加算でバグ修正
- ``staff_path_scanner._normalize`` (**NFC** + 空白保持) → ``normalize_for_path`` に
  分離し NFKC に修正 (全角→半角効くように)

``facility_resolver.normalize_name`` は語境界保持仕様で別系統のため統合対象外。
"""

from __future__ import annotations

import re
import unicodedata

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_lookup_key(s: str) -> str:
    """lookup 用の表記揺れ吸収正規化 (PR-γ v2: 全空白除去)。

    手順:

    1. Unicode NFKC: 全角英数 → 半角、全角 ``（）`` → 半角 ``()``、半角カナ → 全角カナ、
       全角空白 (``\\u3000``) → 半角空白 (``\\u0020``) 等
    2. **全空白 (``\\s+`` 全種類) を完全除去** (PR-γ v2、PR-γ v1 の「半角 1 つに統一」
       から変更、Session 78 実機デモで空白有無揺れ判明のため)
    3. 空文字列はそのまま空文字列を返す

    用途: ``ChecklistConfig.facility_routing`` / ``report_staff`` の lookup、
    人名照合 (``matcher.normalize_name``) 、シート名照合
    (``checklist_b/c._normalize_name``) 等の lookup 系全般。

    保存時 (``load_config``) と参照時 (``plan_b_placement`` / ``plan_c_placement``)
    の両方で本関数を通すことで、業務責任者が表記揺れを意識せず登録・運用できる。
    """
    if not s:
        return s
    return _WHITESPACE_RE.sub("", unicodedata.normalize("NFKC", s))


def normalize_for_path(name: str) -> str:
    """ファイル/フォルダ名比較用の正規化 (NFKC のみ、空白保持)。

    用途: ``staff_path_scanner`` の ``Path.iterdir()`` 結果と suggest_patterns の
    比較等、Windows ファイル名上の NFC/NFD 揺れ + 半角/全角揺れの吸収。

    ``normalize_lookup_key`` との違い: 空白を保持する。フォルダ名/ファイル名に
    空白が含まれる場合（例: ``リハ経過報告書 令和8年``）、空白も意味ある区切り
    として扱うため除去しない。

    PR-γ v2 で ``staff_path_scanner._normalize`` (NFC のみ) を NFKC に修正。
    """
    if not name:
        return name
    return unicodedata.normalize("NFKC", name)
