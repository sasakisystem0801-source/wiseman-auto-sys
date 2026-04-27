"""事業所名 resolver（誤配布防止のための安全マッチング）。

ファイル名（例: ``"2025年04月_本田デイケア_提供実績.ex_"``）と事業所フォルダ名群の
照合を行い、振り分け先を決定する純粋ロジック。UI / I/O から完全独立で、入力に対し
``ResolveResult`` を返すだけの関数として実装する（テスト容易性最優先）。

## マッチング戦略（厳格、誤配布防止）

`facility_aliases` と部分一致をどう扱うかが本モジュールの核心。`双方向部分一致 +
最長一致` のような素朴な戦略は false positive を生み介護現場の業務事故（別事業所
への誤配布）を引き起こすため、以下の優先順序で評価する:

1. **alias 一致**: 以下を **すべて** 満たす場合に CONFIRMED:
   (a) ``canonical`` が ``facility_names`` に **実在** する（HIGH-1 対応）
   (b) ``aliases[canonical]`` のいずれかが正規化ファイル名に **語境界付き** で出現
       （HIGH-2 対応、短 alias の誤ヒット遮断）
   (c) 上記を満たす canonical が **ただ 1 つ** のとき → ``CONFIRMED (ALIAS_MATCH)``。
       複数 canonical が hit したら ``AMBIGUOUS (AMBIGUOUS_ALIAS)`` で手動振り分けに回す
2. **正規化完全一致**: 正規化後のファイル名と等しい事業所名が
   - 1 件 → ``CONFIRMED (EXACT_MATCH)``
   - 2 件以上（正規化で同一になる別フォルダが混在）→ ``AMBIGUOUS (AMBIGUOUS_EXACT)``
3. **部分一致（一意）**: 事業所名がファイル名に **語境界付き** 部分一致し、候補が 1 つだけ
   → ``CONFIRMED (PARTIAL_UNIQUE)``
4. **部分一致（最長優位）**: 候補複数だが最長候補と次長候補の差が
   ``_PARTIAL_MATCH_DOMINANCE_THRESHOLD`` 文字以上 → ``CONFIRMED (PARTIAL_DOMINANT)``
5. **AMBIGUOUS**: 候補複数で差が閾値未満 → ``ResolveStatus.AMBIGUOUS (AMBIGUOUS_PARTIAL)``、
   UI で手動選択
6. **UNMATCHED**: 候補ゼロ → ``ResolveStatus.UNMATCHED``（細分 reason は下記参照）

## 正規化規則

- NFKC 正規化（半角カナ ⇔ 全角カナ統一、半角英数 ⇔ 全角英数統一、（）⇔ () 統一）
- **空白は除去しない**（半角・全角・タブ・改行は語境界として機能させる）

空白除去は当初設計に含めていたが、レビューで「空白を除去すると ALIAS_BOUNDARY_CHARS
に含めた半角スペースが境界として機能しない」設計矛盾が判明したため廃止。事業所名や
ファイル名の空白の有無は別物として扱う（誤配布回避を優先、業務影響は事業所名固定運用
で限定的）。

## PII 保護

ファイル名・事業所名・別名は介護現場では機密扱いとなる場合があるため、本モジュールは
**ログ出力を一切行わない**。

入力検証ポリシー:
- ``filename`` が空文字列・空白のみ → ``UNMATCHED (EMPTY_FILENAME)`` を返す（例外なし）
- ``facility_names`` が空 list → ``UNMATCHED (EMPTY_FACILITY_LIST)`` を返す（例外なし）
- 上記以外の型違反入力（``None`` / 非 list / 非 str など）は **呼び出し元の責務**
  として扱う（防御的に握りつぶさず ``AttributeError`` 等を伝播させる）

呼び出し元で結果を扱う際にも、PII を含む文字列を直接ログに出さない責務を負う。

## alias 辞書の前提

本モジュールは ``facility_aliases`` が ``config._validate_facility_aliases`` で
以下を検証済みであることを前提とする（PII 含むため再検証はしない）:
1. canonical key が非空
2. alias 配列内の文字列が非空
3. 同一 canonical 内で alias 重複なし
4. 異なる canonical 間で alias グローバル一意
5. alias が他 canonical 名と衝突しない

ただし、上記 #4 の前提が万一破られた場合（外部からの動的 alias 注入等）でも、
resolver 自体は防御策として **alias 一致が複数 canonical を返したら AMBIGUOUS**
とする（H-A 対応）。設定不整合（alias の canonical が facility_names に不在）は
``find_orphan_alias_canonicals`` ヘルパーで呼び出し元が事前検出できる。

## 入力パスの扱い

``filename`` には **拡張子付きファイル名のみ** を渡す（絶対パス・相対パス不可）。
パス区切り文字（``/`` / ``\\``）は ``_ALIAS_BOUNDARY_CHARS`` に含まれるため、誤って
フルパスを渡すと親ディレクトリ名で誤マッチする。呼び出し元で ``Path.name`` を必ず使う
責務を負う（PR3 ex_extractor 統合時に保証）。
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

# alias / canonical name がファイル名に部分一致する際、前後にあれば「語境界」と
# 判定する文字。ASCII 記号 + NFKC 正規化済 半角化記号 + 半角/全角空白類を含む。
# 含まれていない隣接文字（日本語、英数字、※「」等の日本語記号）が前後にあると
# 誤ヒット扱いで skip し、短い alias が無関係な事業所名の一部と一致する誤配布パス
# を遮断する。日本語固有の記号は語境界対象外（保守性優先、PR5 実機検証後の追加検討）。
_ALIAS_BOUNDARY_CHARS: frozenset[str] = frozenset(
    "_-. ()/[]{}\\,;:!?#@&%+=*~|<>'\"`" + "\t\n\r　"
)


class ResolveStatus(StrEnum):
    """resolve_facility の判定結果ステータス。

    CONFIRMED: 振り分け先確定（自動振り分け可）
    AMBIGUOUS: 候補複数で曖昧（手動選択必要）
    UNMATCHED: 候補なし（手動振り分け or スキップ）
    """

    CONFIRMED = "confirmed"
    AMBIGUOUS = "ambiguous"
    UNMATCHED = "unmatched"


class ResolveReason(StrEnum):
    """CONFIRMED / AMBIGUOUS / UNMATCHED に至った具体的な理由。

    UI 表示・テスト判別・PII 安全な統計ログ出力に使う。各 reason は特定の status と
    1:1 対応し、``ResolveResult.__post_init__`` で組み合わせ整合性が強制される。
    """

    # CONFIRMED 系
    ALIAS_MATCH = "alias_match"
    EXACT_MATCH = "exact_match"
    PARTIAL_UNIQUE = "partial_unique"
    PARTIAL_DOMINANT = "partial_dominant"
    # AMBIGUOUS 系
    AMBIGUOUS_ALIAS = "ambiguous_alias"  # alias 一致で複数 canonical hit
    AMBIGUOUS_EXACT = "ambiguous_exact"  # 正規化完全一致で複数 facility hit
    AMBIGUOUS_PARTIAL = "ambiguous_partial"  # 部分一致で複数候補 + 差不十分
    # UNMATCHED 系（細分化で呼び出し元が原因区別可能に）
    NO_CANDIDATE = "no_candidate"  # マッチ候補ゼロ（純粋にどれにも当たらない）
    EMPTY_FILENAME = "empty_filename"  # filename 空 / 空白のみ
    EMPTY_FACILITY_LIST = "empty_facility_list"  # facility_names 空


# reason ごとに対応する status を 1:1 で定義（__post_init__ で整合性強制）
_REASON_TO_STATUS: dict[ResolveReason, ResolveStatus] = {
    ResolveReason.ALIAS_MATCH: ResolveStatus.CONFIRMED,
    ResolveReason.EXACT_MATCH: ResolveStatus.CONFIRMED,
    ResolveReason.PARTIAL_UNIQUE: ResolveStatus.CONFIRMED,
    ResolveReason.PARTIAL_DOMINANT: ResolveStatus.CONFIRMED,
    ResolveReason.AMBIGUOUS_ALIAS: ResolveStatus.AMBIGUOUS,
    ResolveReason.AMBIGUOUS_EXACT: ResolveStatus.AMBIGUOUS,
    ResolveReason.AMBIGUOUS_PARTIAL: ResolveStatus.AMBIGUOUS,
    ResolveReason.NO_CANDIDATE: ResolveStatus.UNMATCHED,
    ResolveReason.EMPTY_FILENAME: ResolveStatus.UNMATCHED,
    ResolveReason.EMPTY_FACILITY_LIST: ResolveStatus.UNMATCHED,
}


@dataclass(frozen=True)
class ResolveResult:
    """resolve_facility の戻り値。

    Attributes:
        status: CONFIRMED / AMBIGUOUS / UNMATCHED
        matched_facility: CONFIRMED 時のみ非 None。事業所フォルダ名（正規化前の元文字列）
        candidates: AMBIGUOUS 時の選択肢リスト（**長さ降順** で UI プルダウン表示順を保証）。
            CONFIRMED 時は 1 要素 (matched_facility のみ)、UNMATCHED 時は空 tuple
        reason: 判定根拠（テスト・UI 表示・PII 安全なログ出力用）

    不変条件は ``__post_init__`` で runtime 強制（外部から不正組み合わせの構築不可）:
        - reason に対応する status が ``_REASON_TO_STATUS`` と一致
        - CONFIRMED ⇒ matched_facility 非 None かつ candidates == (matched_facility,)
        - AMBIGUOUS ⇒ matched_facility None かつ len(candidates) >= 2
        - UNMATCHED ⇒ matched_facility None かつ candidates == ()
    """

    status: ResolveStatus
    matched_facility: str | None
    candidates: tuple[str, ...]
    reason: ResolveReason

    def __post_init__(self) -> None:
        # PII 保護: 例外メッセージには status / reason 名のみ含め、施設名は出さない
        expected_status = _REASON_TO_STATUS.get(self.reason)
        if expected_status is None:
            raise ValueError(f"Unknown reason: {self.reason}")
        if expected_status is not self.status:
            raise ValueError(
                f"reason {self.reason} requires status {expected_status}, "
                f"got {self.status}"
            )
        if self.status is ResolveStatus.CONFIRMED:
            if self.matched_facility is None:
                raise ValueError("CONFIRMED requires matched_facility")
            if self.candidates != (self.matched_facility,):
                raise ValueError(
                    "CONFIRMED requires candidates == (matched_facility,)"
                )
        elif self.status is ResolveStatus.AMBIGUOUS:
            if self.matched_facility is not None:
                raise ValueError("AMBIGUOUS forbids matched_facility")
            if len(self.candidates) < 2:
                raise ValueError("AMBIGUOUS requires >= 2 candidates")
        else:  # UNMATCHED
            if self.matched_facility is not None:
                raise ValueError("UNMATCHED forbids matched_facility")
            if self.candidates:
                raise ValueError("UNMATCHED requires empty candidates")

    @property
    def is_auto_distributable(self) -> bool:
        """そのまま無確認で振り分けてよいか（UI 統合用の単一判定ポイント）。

        呼び出し元（PR4 UI）が `if r.matched_facility is not None:` のような Optional
        チェックではなく、本プロパティで分岐することで、AMBIGUOUS と UNMATCHED の
        混同による誤配布を構造的に防ぐ。
        """
        return self.status is ResolveStatus.CONFIRMED

    @property
    def needs_manual_selection(self) -> bool:
        """AMBIGUOUS で候補リストから手動選択が必要。"""
        return self.status is ResolveStatus.AMBIGUOUS

    @property
    def needs_manual_input(self) -> bool:
        """UNMATCHED で全事業所プルダウン or スキップが必要。"""
        return self.status is ResolveStatus.UNMATCHED

    # --- factory メソッド（resolver 内の構築を一本化、不正組み合わせ防止） ---

    @classmethod
    def confirmed(cls, facility: str, reason: ResolveReason) -> ResolveResult:
        """CONFIRMED の組み立てを一本化（呼び出し元で reason ↔ status 不整合を防ぐ）。"""
        return cls(
            status=ResolveStatus.CONFIRMED,
            matched_facility=facility,
            candidates=(facility,),
            reason=reason,
        )

    @classmethod
    def ambiguous(
        cls, candidates: tuple[str, ...], reason: ResolveReason
    ) -> ResolveResult:
        """AMBIGUOUS の組み立てを一本化（candidates >=2 を __post_init__ で強制）。"""
        return cls(
            status=ResolveStatus.AMBIGUOUS,
            matched_facility=None,
            candidates=candidates,
            reason=reason,
        )

    @classmethod
    def unmatched(cls, reason: ResolveReason) -> ResolveResult:
        """UNMATCHED の組み立てを一本化（細分 reason で原因区別可能に）。"""
        return cls(
            status=ResolveStatus.UNMATCHED,
            matched_facility=None,
            candidates=(),
            reason=reason,
        )


def normalize_name(name: str) -> str:
    """事業所名・別名・ファイル名を比較可能な形に正規化する。

    - NFKC: 半角カナ → 全角カナ、半角英数 → 全角英数、（）→ () 等
    - 空白は **除去しない**（語境界として機能させる）

    冪等性: ``normalize_name(normalize_name(s)) == normalize_name(s)``
    """
    if not name:
        return ""
    return unicodedata.normalize("NFKC", name)


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
    if needle_len > haystack_len:
        return False
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


def find_orphan_alias_canonicals(
    facility_names: list[str], aliases: dict[str, list[str]]
) -> list[str]:
    """alias 辞書に登録されているが ``facility_names`` に実在しない canonical を返す。

    呼び出し元（PR4 UI）が起動時 / 設定変更時に呼び、設定不整合（alias 設定だけ残って
    実フォルダがリネーム/削除された）を警告バナー等で運用者に通知する用途。

    silent skip だけでは alias 機能が密かに死んでいることに気付けない問題への対策
    （silent-failure-hunter HIGH-2 対応）。
    """
    facility_set = set(facility_names)
    return [canonical for canonical in aliases if canonical not in facility_set]


def resolve_facility(
    filename: str,
    facility_names: list[str],
    aliases: dict[str, list[str]],
) -> ResolveResult:
    """ファイル名と事業所フォルダ名群から振り分け先を決定する。

    Args:
        filename: 振り分け対象のファイル名（拡張子含む、絶対パス不可、Path.name 推奨）。
            空文字列・空白のみの場合は ``UNMATCHED (EMPTY_FILENAME)`` を返す
        facility_names: 振り分け先候補の事業所フォルダ名リスト。
            空リストなら ``UNMATCHED (EMPTY_FACILITY_LIST)``
        aliases: ``config._validate_facility_aliases`` で検証済みの別名辞書。
            ``{canonical: [alias1, alias2, ...]}`` 形式

    Returns:
        ``ResolveResult``。``is_auto_distributable`` / ``needs_manual_selection``
        / ``needs_manual_input`` プロパティで UI 分岐を構造的に表現可能
    """
    if not filename:
        return ResolveResult.unmatched(ResolveReason.EMPTY_FILENAME)
    if not facility_names:
        return ResolveResult.unmatched(ResolveReason.EMPTY_FACILITY_LIST)

    normalized_filename = normalize_name(filename)
    if not normalized_filename or not normalized_filename.strip():
        return ResolveResult.unmatched(ResolveReason.EMPTY_FILENAME)

    facility_name_set = set(facility_names)

    # Step 1: alias 一致（最優先、手動登録された明示的マッピング）
    # 安全要件:
    #   (a) alias の canonical が facility_names に実在する（実フォルダ存在検証）
    #   (b) alias 文字列がファイル名に「語境界付き」で出現する（短 alias 誤ヒット防止）
    #   (c) 複数 canonical が hit したら AMBIGUOUS（H-A 対応）
    alias_hit_canonicals: list[str] = []
    for canonical, alias_list in aliases.items():
        if canonical not in facility_name_set:
            continue  # alias 設定だけ残って実フォルダが消えたケースを安全に skip
        for alias in alias_list:
            normalized_alias = normalize_name(alias)
            if not normalized_alias:
                continue
            if _is_word_bounded(normalized_filename, normalized_alias):
                alias_hit_canonicals.append(canonical)
                break  # 同一 canonical 内で複数 alias hit しても 1 回のみ追加
    if len(alias_hit_canonicals) == 1:
        return ResolveResult.confirmed(
            alias_hit_canonicals[0], ResolveReason.ALIAS_MATCH
        )
    if len(alias_hit_canonicals) >= 2:
        # dict 順保持 + 重複排除（alias 一意性 contract が破られた場合の防御）
        unique_canonicals = tuple(dict.fromkeys(alias_hit_canonicals))
        if len(unique_canonicals) >= 2:
            return ResolveResult.ambiguous(
                unique_canonicals, ResolveReason.AMBIGUOUS_ALIAS
            )
        # 全て同一 canonical（防御的、通常発生しない）
        return ResolveResult.confirmed(
            unique_canonicals[0], ResolveReason.ALIAS_MATCH
        )

    # Step 2: 正規化完全一致（ファイル名そのものが事業所名と等しい）
    # 正規化で同一になる別フォルダが複数ある場合は AMBIGUOUS（H-B 対応）
    exact_matches: list[str] = []
    for canonical in facility_names:
        if normalize_name(canonical) == normalized_filename:
            exact_matches.append(canonical)
    if len(exact_matches) == 1:
        return ResolveResult.confirmed(exact_matches[0], ResolveReason.EXACT_MATCH)
    if len(exact_matches) >= 2:
        return ResolveResult.ambiguous(
            tuple(dict.fromkeys(exact_matches)), ResolveReason.AMBIGUOUS_EXACT
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
        return ResolveResult.unmatched(ResolveReason.NO_CANDIDATE)

    if len(matches) == 1:
        return ResolveResult.confirmed(matches[0][0], ResolveReason.PARTIAL_UNIQUE)

    # 複数候補: 長さ降順で安定ソート（タイブレーカは元順序保持）
    matches.sort(key=lambda x: -x[1])
    longest_len = matches[0][1]
    second_len = matches[1][1]
    if longest_len - second_len >= _PARTIAL_MATCH_DOMINANCE_THRESHOLD:
        return ResolveResult.confirmed(matches[0][0], ResolveReason.PARTIAL_DOMINANT)

    # AMBIGUOUS: 候補複数で差が閾値未満 → 全候補を長さ降順で返して手動振り分け
    return ResolveResult.ambiguous(
        tuple(c for c, _ in matches), ResolveReason.AMBIGUOUS_PARTIAL
    )
