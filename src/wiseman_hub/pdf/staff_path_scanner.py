"""担当者フォルダ配下の xlsx 候補スキャナー。

ReportStaffEntry.suggest_patterns に基づき NAS 上の xlsx を抽出する。担当者ごとに
命名規則が大きく異なる前提（PT 宮下の末尾空白揺れ、PT 木塚の年フォルダ年度サフィックス
+ スペース、PT 小島の新旧 2 系統など）に対応するため、glob は ``Path.glob()``
ではなく ``Path.iterdir()`` + Unicode-aware regex で実装する。

設計判断:
    - SMB / UNC パス上の不可視文字 (NFC/NFD 正規化) + 全角/半角揺れ対策で
      ``text_norm.normalize_for_path`` (NFKC) で正規化してから regex match
      (PR-γ v2: 旧 ``NFC`` のみから ``NFKC`` に変更、全角→半角統一が効くように)
    - ``~$*.xlsx`` Office 一時ファイルは常に除外
    - 再帰 ``**`` はサポートしない（YAGNI、命名規則が固定なら 3-4 階層で十分）
    - パターン分割は ``/`` 区切り（Windows ``\\`` は呼び出し側で正規化）
    - ワイルドカード文字は ``*`` のみ（``?`` は不要、``[...]`` は不要）

PII 配慮:
    候補絶対パスはログに出さない。件数と reject reason のみログ。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from wiseman_hub.config import ReportStaffEntry, is_path_configured
from wiseman_hub.utils.text_norm import normalize_for_path

logger = logging.getLogger(__name__)


# 走査時に無視する一時ファイル
_OFFICE_LOCK_PREFIX = "~$"

# 走査対象拡張子
_XLSX_SUFFIX = ".xlsx"


def western_to_reiwa(year: int) -> int:
    """西暦 → 令和年（2019 = R1）。`checklist_c.western_to_reiwa` と同等の式。"""
    return year - 2018


def _normalize(s: str) -> str:
    """SMB 上の NFC/NFD 揺れ + 半角/全角揺れを吸収して比較する。

    PR-γ v2: ``NFC`` → ``NFKC`` に変更 (``text_norm.normalize_for_path`` 経由)。
    NFC のみでは全角→半角・半角カナ→全角カナ等の互換変換が効かず、フォルダ名の
    全角空白/半角空白揺れ (例: ``リハ経過報告書 令和8年`` vs ``リハ経過報告書　令和8年``)
    を吸収できなかった。

    ``normalize_for_path`` は空白を保持する (フォルダ名内空白は意味あり)。
    """
    return normalize_for_path(s)


def _is_temp_file(name: str) -> bool:
    return name.startswith(_OFFICE_LOCK_PREFIX)


def _segment_to_regex(segment: str) -> re.Pattern[str]:
    """glob セグメント（"令和*年", "*{month}月*.xlsx" 等）を re.Pattern に変換。

    `*` 以外の特殊文字は re.escape で literal 扱い、`*` のみ `.*` に展開する。
    """
    parts = segment.split("*")
    escaped = ".*".join(re.escape(p) for p in parts)
    return re.compile(f"^{escaped}$")


def _expand_template_vars(pattern: str, era: int, month: int) -> str:
    """``{era}`` ``{month}`` を数値展開する。他の波括弧は保持。"""
    return pattern.replace("{era}", str(era)).replace("{month}", str(month))


def _walk_pattern(
    current: Path, segments: list[re.Pattern[str]]
) -> list[Path]:
    """残り segments を current 直下から再帰的にマッチして xlsx を返す。"""
    if not segments:
        return []
    head, *rest = segments
    if not current.exists() or not current.is_dir():
        return []
    matches: list[Path] = []
    try:
        children = list(current.iterdir())
    except OSError as exc:
        # NAS 切断・権限不足等は warning に留め空リストを返す
        logger.warning("iterdir failed at %s: %s", current.name, type(exc).__name__)
        return []
    for child in children:
        name = _normalize(child.name)
        if not head.match(name):
            continue
        if not rest:
            # 最終 segment：xlsx ファイルのみを候補化
            if (
                child.is_file()
                and name.lower().endswith(_XLSX_SUFFIX)
                and not _is_temp_file(name)
            ):
                matches.append(child)
        else:
            if child.is_dir():
                matches.extend(_walk_pattern(child, rest))
    return matches


def scan_candidates(
    entry: ReportStaffEntry, year: int, month: int
) -> list[Path]:
    """suggest_patterns から候補 xlsx を全て抽出（重複は path 単位で排除）。

    パターン展開順:
        1. ``{era}`` ``{month}`` を数値置換
        2. ``/`` で分割した各 segment を regex 化
        3. base_dir から再帰的に matching
        4. 結果を path 順に sorted（決定的順序）
    """
    # Issue #27 続編 G Phase 3b: entry.base_dir は Path 型に移行済。
    # Path("") は `bool()` で True (Path(".") と等価) なので is_path_configured で gate。
    if not is_path_configured(entry.base_dir) or not entry.suggest_patterns:
        return []
    base = entry.base_dir
    era = western_to_reiwa(year)
    seen: set[Path] = set()
    results: list[Path] = []
    for pattern in entry.suggest_patterns:
        expanded = _expand_template_vars(pattern, era, month)
        # POSIX-like 区切り。Windows backslash は呼び出し側で / に統一
        segments = [_segment_to_regex(seg) for seg in expanded.split("/") if seg]
        if not segments:
            continue
        for path in _walk_pattern(base, segments):
            if path in seen:
                continue
            seen.add(path)
            results.append(path)
    return sorted(results)


def scan_fallback(base_dir: Path, max_depth: int = 3) -> list[Path]:
    """suggest_patterns ヒットなし時のフォールバック。base_dir 直下を浅く全 walk。

    Office 一時ファイル ``~$*.xlsx`` 除外、xlsx 以外除外、深さ ``max_depth`` まで。
    """
    if not base_dir.exists() or not base_dir.is_dir():
        return []
    results: list[Path] = []

    def _walk(current: Path, remaining_depth: int) -> None:
        if remaining_depth < 0:
            return
        try:
            children = list(current.iterdir())
        except OSError as exc:
            logger.warning("fallback iterdir failed: %s", type(exc).__name__)
            return
        for child in children:
            name = _normalize(child.name)
            if child.is_file() and name.lower().endswith(_XLSX_SUFFIX):
                if not _is_temp_file(name):
                    results.append(child)
            elif child.is_dir() and remaining_depth > 0:
                _walk(child, remaining_depth - 1)

    _walk(base_dir, max_depth)
    return sorted(results)


def build_folder_tree(
    base_dir: Path, max_depth: int = 3
) -> dict[str, Any]:
    """レビュー UI 用のフォルダツリー dict を生成。

    返却形式:
        {"name": str, "path": str, "is_dir": bool, "children": [...]}

    ファイルは xlsx のみ children に含める（Office 一時ファイル除外）。
    """
    def _build(current: Path, remaining_depth: int) -> dict[str, Any]:
        node: dict[str, Any] = {
            "name": _normalize(current.name),
            "path": str(current),
            "is_dir": current.is_dir(),
            "children": [],
        }
        if not current.is_dir() or remaining_depth <= 0:
            return node
        try:
            children = sorted(current.iterdir())
        except OSError as exc:
            logger.warning("tree iterdir failed: %s", type(exc).__name__)
            return node
        for child in children:
            name = _normalize(child.name)
            if child.is_file():
                if not name.lower().endswith(_XLSX_SUFFIX):
                    continue
                if _is_temp_file(name):
                    continue
                node["children"].append(
                    {
                        "name": name,
                        "path": str(child),
                        "is_dir": False,
                        "children": [],
                    }
                )
            elif child.is_dir():
                node["children"].append(_build(child, remaining_depth - 1))
        return node

    if not base_dir.exists():
        return {"name": "", "path": str(base_dir), "is_dir": False, "children": []}
    return _build(base_dir, max_depth)
