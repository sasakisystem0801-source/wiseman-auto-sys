"""事業所名 resolver（誤配布防止のための安全マッチング）。

ファイル名（例: ``"2025年04月_本田デイケア_提供実績.ex_"``）と事業所フォルダ名群の
照合を行い、振り分け先を決定する純粋ロジック。UI / I/O から完全独立で、入力に対し
``ResolveResult`` を返すだけの関数として実装する（テスト容易性最優先）。

## マッチング戦略（厳格、誤配布防止）

`facility_aliases` と部分一致をどう扱うかが本モジュールの核心。`双方向部分一致 +
最長一致` のような素朴な戦略は false positive を生み介護現場の業務事故（別事業所
への誤配布）を引き起こすため、以下の優先順序で評価する:

1. **alias 一致**: ``aliases[canonical]`` のいずれかが正規化ファイル名に含まれる
   → ``CONFIRMED (reason=ALIAS_MATCH)``。最優先。手動登録された別名は意図的な
   マッピングなので、部分一致ロジックを完全にバイパスする
2. **正規化完全一致**: 正規化後のファイル名が事業所名そのものと等しい
   → ``CONFIRMED (reason=EXACT_MATCH)``。実用上はレアケースだが、PR4 で「事業所
   名そのもの」を入力する手動 UI と整合させるために分離して記録
3. **部分一致（一意）**: 事業所名がファイル名に部分一致し、かつ候補が 1 つだけ
   → ``CONFIRMED (reason=PARTIAL_UNIQUE)``
4. **部分一致（最長優位）**: 候補複数だが最長候補と次長候補の差が
   ``_PARTIAL_MATCH_DOMINANCE_THRESHOLD`` 文字以上 → ``CONFIRMED (reason=PARTIAL_DOMINANT)``
5. **AMBIGUOUS**: 候補複数で差が閾値未満 → ``ResolveStatus.AMBIGUOUS``、UI で手動選択
6. **UNMATCHED**: 候補ゼロ → ``ResolveStatus.UNMATCHED``、UI でスキップ or 全事業所
   からのプルダウン選択

## 正規化規則

- NFKC 正規化（半角カナ ⇔ 全角カナ統一、半角英数 ⇔ 全角英数統一、（）⇔ () 統一）
- 空白除去（半角・全角・タブ・改行・キャリッジリターン）

## PII 保護

ファイル名・事業所名・別名は介護現場では機密扱いとなる場合があるため、本モジュールは
**ログ出力を一切行わない**。例外も投げない（不正入力は無効値として扱い ``UNMATCHED``
を返す）。呼び出し元で結果を扱う際にも、PII を含む文字列を直接ログに出さない責務を負う。

## alias 辞書の前提

本モジュールは ``facility_aliases`` が ``config._validate_facility_aliases`` で検証
済みであることを前提とする（global 一意性、空文字列なし、key/canonical 衝突なし）。
この前提を破った辞書を渡された場合の挙動は未定義（実装上は最初に hit した alias を
返すが、検証が config 層で行われる契約）。
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from enum import StrEnum

# 部分一致で「最長候補が他候補より十分差がある」と判定する閾値（文字単位）。
# 2 文字差があれば最長一致を採用、未満なら AMBIGUOUS で手動振り分けに回す。
# この値は false positive と false negative のトレードオフを決める。
# 大きくするほど安全（誤配布が減る）が UI の手動操作が増える。
_PARTIAL_MATCH_DOMINANCE_THRESHOLD: int = 2

# 正規化で除去する空白類（半角スペース、全角スペース、タブ、改行、CR）
_WHITESPACE_CHARS: str = " 　\t\n\r"

# alias / canonical name がファイル名に部分一致する際、前後にあれば「語境界」と
# 判定する文字。ファイル名における事業所名の典型的な区切りを網羅する。
# 含まれていない隣接文字（日本語・英数字）が前後にあると誤ヒット扱いで skip し、
# 短い alias が無関係な事業所名の一部と一致する誤配布パスを遮断する。
_ALIAS_BOUNDARY_CHARS: frozenset[str] = frozenset(
    "_-. ()/[]{}\\,;:!?#@&%+=*~|<>'\"`"
)


class ResolveStatus(StrEnum):
    """resolve_facility の判定結果ステータス。"""

    CONFIRMED = "confirmed"  # 振り分け先確定（自動振り分け可）
    AMBIGUOUS = "ambiguous"  # 候補複数で曖昧（手動選択必要）
    UNMATCHED = "unmatched"  # 候補なし（手動振り分け or スキップ）


class ResolveReason(StrEnum):
    """CONFIRMED / AMBIGUOUS / UNMATCHED に至った具体的な理由（UI 表示・テスト判別用）。"""

    ALIAS_MATCH = "alias_match"  # alias 一致による CONFIRMED
    EXACT_MATCH = "exact_match"  # 正規化完全一致による CONFIRMED
    PARTIAL_UNIQUE = "partial_unique"  # 部分一致一意による CONFIRMED
    PARTIAL_DOMINANT = "partial_dominant"  # 部分一致最長（差≥閾値）による CONFIRMED
    AMBIGUOUS_PARTIAL = "ambiguous_partial"  # 部分一致複数で差不十分
    NO_CANDIDATE = "no_candidate"  # マッチ候補ゼロ


@dataclass(frozen=True)
class ResolveResult:
    """resolve_facility の戻り値。

    Attributes:
        status: CONFIRMED / AMBIGUOUS / UNMATCHED
        matched_facility: CONFIRMED 時のみ非 None。事業所フォルダ名（正規化前の元文字列）
        candidates: AMBIGUOUS 時の選択肢リスト（UI プルダウン用）。CONFIRMED 時は 1 要素、
            UNMATCHED 時は空 tuple
        reason: 判定根拠（テスト・UI 表示・PII 安全なログ出力用）
    """

    status: ResolveStatus
    matched_facility: str | None
    candidates: tuple[str, ...]
    reason: ResolveReason


def normalize_name(name: str) -> str:
    """事業所名・別名・ファイル名を比較可能な形に正規化する。

    - NFKC: 半角カナ → 全角カナ、半角英数 → 全角英数、（）→ () 等
    - 空白除去: 半角・全角・タブ・改行・CR

    冪等性: ``normalize_name(normalize_name(s)) == normalize_name(s)``
    """
    if not name:
        return ""
    normalized = unicodedata.normalize("NFKC", name)
    for ws in _WHITESPACE_CHARS:
        normalized = normalized.replace(ws, "")
    return normalized


def _unmatched_no_candidate() -> ResolveResult:
    """候補なし UNMATCHED の sentinel result（複数経路で再利用）。"""
    return ResolveResult(
        status=ResolveStatus.UNMATCHED,
        matched_facility=None,
        candidates=(),
        reason=ResolveReason.NO_CANDIDATE,
    )


def _is_word_bounded(haystack: str, needle: str) -> bool:
    """needle が haystack 内に少なくとも 1 箇所「語境界」付きで出現するか。

    語境界 = 前後の文字が _ALIAS_BOUNDARY_CHARS のいずれかに含まれる、または
    文字列の開始/終端である。これにより短い alias / canonical name が無関係な
    事業所名の一部に偶然一致する誤配布パスを遮断する。

    例:
        - haystack="2025_本田DC_提供.ex_", needle="本田DC" → True (前後 _ で囲まれる)
        - haystack="山田デイサービス.ex_", needle="デイ" → False (前後が日本語、語境界なし)
    """
    if not needle:
        return False
    needle_len = len(needle)
    haystack_len = len(haystack)
    pos = 0
    while pos <= haystack_len - needle_len:
        idx = haystack.find(needle, pos)
        if idx < 0:
            return False
        before_ok = idx == 0 or haystack[idx - 1] in _ALIAS_BOUNDARY_CHARS
        end_idx = idx + needle_len
        after_ok = end_idx == haystack_len or haystack[end_idx] in _ALIAS_BOUNDARY_CHARS
        if before_ok and after_ok:
            return True
        pos = idx + 1
    return False


def resolve_facility(
    filename: str,
    facility_names: list[str],
    aliases: dict[str, list[str]],
) -> ResolveResult:
    """ファイル名と事業所フォルダ名群から振り分け先を決定する。

    Args:
        filename: 振り分け対象のファイル名（拡張子含む、絶対パス不可）。空文字列・
            空白のみの場合は UNMATCHED を返す
        facility_names: 振り分け先候補の事業所フォルダ名リスト。空リストなら UNMATCHED
        aliases: ``config._validate_facility_aliases`` で検証済みの別名辞書。
            ``{canonical: [alias1, alias2, ...]}`` 形式

    Returns:
        ``ResolveResult``。status と reason の組み合わせで判定根拠が分かる
    """
    if not filename or not facility_names:
        return _unmatched_no_candidate()

    normalized_filename = normalize_name(filename)
    if not normalized_filename:
        return _unmatched_no_candidate()

    facility_name_set = set(facility_names)

    # Step 1: alias 一致（最優先、手動登録された明示的マッピング）
    # 安全要件:
    #   (a) alias の canonical が facility_names に実在する（実フォルダ存在検証）
    #   (b) alias 文字列がファイル名に「語境界付き」で出現する（短 alias 誤ヒット防止）
    for canonical, alias_list in aliases.items():
        if canonical not in facility_name_set:
            continue  # alias 設定だけ残って実フォルダが消えたケースを安全に無視
        for alias in alias_list:
            normalized_alias = normalize_name(alias)
            if not normalized_alias:
                continue
            if _is_word_bounded(normalized_filename, normalized_alias):
                return ResolveResult(
                    status=ResolveStatus.CONFIRMED,
                    matched_facility=canonical,
                    candidates=(canonical,),
                    reason=ResolveReason.ALIAS_MATCH,
                )

    # Step 2: 正規化完全一致（ファイル名そのものが事業所名と等しいレアケース）
    for canonical in facility_names:
        if normalize_name(canonical) == normalized_filename:
            return ResolveResult(
                status=ResolveStatus.CONFIRMED,
                matched_facility=canonical,
                candidates=(canonical,),
                reason=ResolveReason.EXACT_MATCH,
            )

    # Step 3: 部分一致（事業所名がファイル名に substring として含まれる）
    # 双方向ではなく一方向のみ（事業所名 ⊂ ファイル名）+ 語境界要求。
    # 逆方向（ファイル名 ⊂ 事業所名）は通常ファイル名が日付・記号付きで長いため起こらず、
    # 許すと false positive を増やす。語境界要求で短い canonical の誤ヒットも遮断。
    matches: list[tuple[str, int]] = []
    for canonical in facility_names:
        normalized_canonical = normalize_name(canonical)
        if normalized_canonical and _is_word_bounded(
            normalized_filename, normalized_canonical
        ):
            matches.append((canonical, len(normalized_canonical)))

    if not matches:
        return _unmatched_no_candidate()

    if len(matches) == 1:
        return ResolveResult(
            status=ResolveStatus.CONFIRMED,
            matched_facility=matches[0][0],
            candidates=(matches[0][0],),
            reason=ResolveReason.PARTIAL_UNIQUE,
        )

    # 複数候補: 長さ降順で安定ソート（タイブレーカは元順序保持）
    matches.sort(key=lambda x: -x[1])
    longest_len = matches[0][1]
    second_len = matches[1][1]
    if longest_len - second_len >= _PARTIAL_MATCH_DOMINANCE_THRESHOLD:
        return ResolveResult(
            status=ResolveStatus.CONFIRMED,
            matched_facility=matches[0][0],
            candidates=(matches[0][0],),
            reason=ResolveReason.PARTIAL_DOMINANT,
        )

    # AMBIGUOUS: 候補複数で差が閾値未満 → 全候補を返して手動振り分け
    return ResolveResult(
        status=ResolveStatus.AMBIGUOUS,
        matched_facility=None,
        candidates=tuple(c for c, _ in matches),
        reason=ResolveReason.AMBIGUOUS_PARTIAL,
    )
