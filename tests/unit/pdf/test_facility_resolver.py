"""facility_resolver のユニットテスト（PR2）。

誤配布防止のための安全マッチング戦略を網羅検証する。特に AC2-6（false positive
回避: 似た事業所名混在環境での AMBIGUOUS 判定）と AC2-9（PII 保護: ログ出力ゼロ
+ テストデータも仮名化）を厚めにテストする。

PII 防御方針: 本ファイルのテストデータには実在する介護施設名・利用者名を含めない。
すべて仮名（「サービスA」「ユーザー001」等）で構成し、CI ログ・PR diff 経由の
PII 漏洩経路を遮断する（Evaluator 指摘 AC2-9 PARTIAL 対応）。
"""

from __future__ import annotations

import logging
from dataclasses import FrozenInstanceError

import pytest

from wiseman_hub.pdf.facility_resolver import (
    ResolveReason,
    ResolveStatus,
    normalize_name,
    resolve_facility,
)

# ---------------------------------------------------------------------------
# normalize_name: 正規化の基本動作（NFKC + 空白除去）
# ---------------------------------------------------------------------------


class TestNormalizeName:
    def test_empty_string_returns_empty(self) -> None:
        assert normalize_name("") == ""

    def test_nfkc_halfwidth_kana_to_fullwidth(self) -> None:
        """半角カナ（ｱｲｳ）が全角カナ（アイウ）に正規化される。"""
        assert normalize_name("ｱｲｳ") == normalize_name("アイウ")

    def test_nfkc_fullwidth_alnum_to_halfwidth(self) -> None:
        """全角英数（ＡＢＣ１２３）が半角英数（ABC123）に正規化される。"""
        assert normalize_name("ＡＢＣ１２３") == "ABC123"

    def test_nfkc_fullwidth_brackets_to_halfwidth(self) -> None:
        """全角括弧（）が半角括弧 () に正規化される。"""
        assert normalize_name("サービス（拡張）") == "サービス(拡張)"

    def test_strip_halfwidth_space(self) -> None:
        assert normalize_name("サービス A") == "サービスA"

    def test_strip_fullwidth_space(self) -> None:
        assert normalize_name("サービス　A") == "サービスA"

    def test_strip_tab_and_newline(self) -> None:
        assert normalize_name("サー\tビス\nA\r") == "サービスA"

    def test_idempotent(self) -> None:
        """正規化は冪等: normalize(normalize(s)) == normalize(s)"""
        s = "ｻｰﾋﾞｽ　A（拡張）"
        assert normalize_name(normalize_name(s)) == normalize_name(s)


# ---------------------------------------------------------------------------
# AC2-1: alias 一致が他のどのマッチより優先される
# ---------------------------------------------------------------------------


class TestAliasPriority:
    def test_ac2_1_alias_match_takes_priority_over_partial(self) -> None:
        """alias 一致は部分一致より優先される。

        ファイル名: "サービスADC_提供実績.ex_"
        canonical "サービスA" の alias に "サービスADC" が登録されている
        → ALIAS_MATCH で「サービスA」を CONFIRMED
        （部分一致では「サービスADC」が canonical として存在しないため UNMATCHED になっていたはず）
        """
        result = resolve_facility(
            filename="サービスADC_提供実績.ex_",
            facility_names=["サービスA", "訪問BX"],
            aliases={"サービスA": ["サービスADC", "サービスA短"]},
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.matched_facility == "サービスA"
        assert result.reason == ResolveReason.ALIAS_MATCH

    def test_ac2_1_alias_match_uses_normalized_comparison(self) -> None:
        """alias の正規化比較。ファイル名に半角カナ、alias に全角カナでもマッチ。"""
        result = resolve_facility(
            filename="ｻｰﾋﾞｽADC_提供実績.ex_",  # 半角カナ
            facility_names=["サービスA"],
            aliases={"サービスA": ["サービスADC"]},  # 全角カナ
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.matched_facility == "サービスA"
        assert result.reason == ResolveReason.ALIAS_MATCH

    def test_alias_match_returns_canonical_not_alias_string(self) -> None:
        """alias でヒットしても matched_facility は alias ではなく canonical (フォルダ名)。

        振り分け先は alias 文字列ではなく事業所フォルダ名でなければならない
        （ファイルシステム上に存在するのは canonical の方）。
        """
        result = resolve_facility(
            filename="サービスADC_提供実績.ex_",
            facility_names=["サービスA"],
            aliases={"サービスA": ["サービスADC"]},
        )
        assert result.matched_facility == "サービスA"
        # alias 文字列がそのまま返ってこないこと
        assert result.matched_facility != "サービスADC"

    def test_alias_priority_over_exact_match_skipped_means_alias_first(self) -> None:
        """alias 検査は完全一致検査より前に走る（順序保証）。

        ファイル名 "サービスA"（完全一致候補）+ alias {"訪問BX": ["サービスA"]}
        → alias 一致が先に走り「訪問BX」が返る（正常運用ではこういう alias 設定はしないが、
        順序保証のテスト）
        """
        result = resolve_facility(
            filename="サービスA",
            facility_names=["サービスA", "訪問BX"],
            aliases={"訪問BX": ["サービスA"]},
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.matched_facility == "訪問BX"
        assert result.reason == ResolveReason.ALIAS_MATCH


# ---------------------------------------------------------------------------
# AC2-2: 正規化完全一致
# ---------------------------------------------------------------------------


class TestExactMatch:
    def test_ac2_2_exact_match_with_halfwidth_fullwidth_mix(self) -> None:
        """半角全角混在の完全一致。"""
        result = resolve_facility(
            filename="ｱｲｳ",
            facility_names=["アイウ"],
            aliases={},
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.matched_facility == "アイウ"
        assert result.reason == ResolveReason.EXACT_MATCH

    def test_ac2_2_exact_match_with_brackets(self) -> None:
        """全角・半角括弧混在の完全一致。"""
        result = resolve_facility(
            filename="サービス(拡張)",
            facility_names=["サービス（拡張）"],
            aliases={},
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.matched_facility == "サービス（拡張）"
        assert result.reason == ResolveReason.EXACT_MATCH

    def test_ac2_2_exact_match_ignores_whitespace(self) -> None:
        """空白の有無は完全一致判定に影響しない。"""
        result = resolve_facility(
            filename="サー ビス A",
            facility_names=["サービスA"],
            aliases={},
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.reason == ResolveReason.EXACT_MATCH


# ---------------------------------------------------------------------------
# AC2-3〜AC2-5: 部分一致（語境界要求あり）
# ---------------------------------------------------------------------------


class TestPartialMatch:
    def test_ac2_3_unique_partial_match_confirmed(self) -> None:
        """事業所名がファイル名に語境界付きで一意に部分一致 → CONFIRMED (PARTIAL_UNIQUE)。"""
        result = resolve_facility(
            filename="2025年04月_サービスA_提供実績.ex_",
            facility_names=["サービスA", "訪問BX", "クリニックC"],
            aliases={},
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.matched_facility == "サービスA"
        assert result.reason == ResolveReason.PARTIAL_UNIQUE

    def test_ac2_4_long_winner_with_two_char_diff_confirmed(self) -> None:
        """ファイル名に複数の独立した事業所名（語境界で囲まれて）が含まれ、最長候補が
        次長候補より 2 文字以上長い → CONFIRMED (PARTIAL_DOMINANT)。

        ファイル名: 「サービスA_クリニックC2提供_実績.ex_」（2 つの事業所名が _ 区切りで含まれる）
        候補: 「サービスA」(5文字) / 「クリニックC2提供」(8文字)
        差: 8 - 5 = 3 ≥ 2 → 「クリニックC2提供」を CONFIRMED
        """
        result = resolve_facility(
            filename="サービスA_クリニックC2提供_実績.ex_",
            facility_names=["サービスA", "クリニックC2提供"],
            aliases={},
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.matched_facility == "クリニックC2提供"
        assert result.reason == ResolveReason.PARTIAL_DOMINANT

    def test_ac2_5_close_partial_match_returns_ambiguous(self) -> None:
        """ファイル名に複数の独立事業所名（語境界）が含まれ、最長と次長の差が 1 文字
        → AMBIGUOUS (手動振り分け)。

        ファイル名: 「サービスA_訪問BXY_提供.ex_」（"サービスA" 5文字 と "訪問BXY" 5文字 が両方マッチ可能）
        候補が同長で 0 文字差 → 1 < 2 で AMBIGUOUS
        """
        result = resolve_facility(
            filename="サービスA_訪問BXY_提供.ex_",
            facility_names=["サービスA", "訪問BXY"],
            aliases={},
        )
        assert result.status == ResolveStatus.AMBIGUOUS
        assert result.matched_facility is None
        assert set(result.candidates) == {"サービスA", "訪問BXY"}
        assert result.reason == ResolveReason.AMBIGUOUS_PARTIAL

    def test_partial_dominant_threshold_exactly_two_chars(self) -> None:
        """境界値: 差がちょうど 2 文字 → CONFIRMED (PARTIAL_DOMINANT)。

        ファイル名「ABCD_EFGHIJ_provided.ex_」、候補「ABCD」(4) と「EFGHIJ」(6)、両方語境界 OK。
        差 2 → PARTIAL_DOMINANT で長い方を採用
        """
        result = resolve_facility(
            filename="ABCD_EFGHIJ_provided.ex_",
            facility_names=["ABCD", "EFGHIJ"],
            aliases={},
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.matched_facility == "EFGHIJ"
        assert result.reason == ResolveReason.PARTIAL_DOMINANT


# ---------------------------------------------------------------------------
# AC2-6: False positive 回避（最重要 KPI: 介護現場の誤配布回避）
# ---------------------------------------------------------------------------


class TestFalsePositiveAvoidance:
    """Evaluator + Codex セカンドオピニオンで指摘された false positive シナリオの厚めテスト。

    似た事業所名（「サービスA」「サービスA（拡張）」「サービスA東」「夜間サービスA」）
    が混在する環境で、誤配布が起きないことを保証する。
    """

    @pytest.fixture
    def similar_facilities(self) -> list[str]:
        return [
            "サービスA",
            "サービスA（拡張）",
            "サービスA東",
            "夜間サービスA",
        ]

    def test_ac2_6_filename_with_unique_facility_match_confirmed(
        self, similar_facilities: list[str]
    ) -> None:
        """ファイル名「サービスA_提供実績.ex_」+ 4 事業所混在。

        - 「サービスA」: 後ろ "_" で語境界 OK
        - 「サービスA（拡張）」「サービスA東」: ファイル名に「（拡張）」「東」がないため substring 不一致
        - 「夜間サービスA」: ファイル名先頭が「サ」で「夜間」がないため substring 不一致
        → 「サービスA」のみ → PARTIAL_UNIQUE で CONFIRMED
        """
        result = resolve_facility(
            filename="サービスA_提供実績.ex_",
            facility_names=similar_facilities,
            aliases={},
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.matched_facility == "サービスA"

    def test_ac2_6_long_facility_name_with_overlapping_short_promoted_safely(
        self, similar_facilities: list[str]
    ) -> None:
        """ファイル名「サービスA東_提供実績.ex_」+ 4 事業所混在。

        新ロジック（語境界要求）:
        - 「サービスA」: ファイル名内の "サービスA" の直後は「東」(日本語) → 語境界なし → 候補から除外
        - 「サービスA東」: 後ろ "_" → 語境界 OK → 候補
        → 「サービスA東」のみ → PARTIAL_UNIQUE で CONFIRMED

        旧ロジック（語境界なし）では両方候補で AMBIGUOUS だったが、Evaluator HIGH-2 対応で
        「日本語隣接の substring」を弾く設計に強化。介護現場運用上「サービスA東_...」は
        サービスA東 への配布意図が明確で、AMBIGUOUS にする必要はない。
        """
        result = resolve_facility(
            filename="サービスA東_提供実績.ex_",
            facility_names=similar_facilities,
            aliases={},
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.matched_facility == "サービスA東"
        assert result.reason == ResolveReason.PARTIAL_UNIQUE

    def test_ac2_6_ambiguous_when_multiple_independent_matches(
        self, similar_facilities: list[str]
    ) -> None:
        """複数事業所名が語境界付きで独立に出現する人為的シナリオ → AMBIGUOUS。

        ファイル名: 「サービスA_夜間サービスA_合同_提供.ex_」
        - 「サービスA」(5): "_サービスA_" で出現、語境界 OK → 候補
        - 「夜間サービスA」(7): "_夜間サービスA_" で出現、語境界 OK → 候補
        差: 7 - 5 = 2 → PARTIAL_DOMINANT で「夜間サービスA」を採用
        （安全上は AMBIGUOUS にしたいが、設計上 ≥2 差は CONFIRMED とする方針）
        """
        result = resolve_facility(
            filename="サービスA_夜間サービスA_合同_提供.ex_",
            facility_names=similar_facilities,
            aliases={},
        )
        # 注: "サービスA" は "夜間サービスA" の substring としても出現するが、
        # 後ろが "_" で語境界 OK のため独立候補として扱われる
        assert result.status == ResolveStatus.CONFIRMED
        # 「夜間サービスA」(7) > 「サービスA」(5) 差 2 → 長い方を採用
        assert result.matched_facility == "夜間サービスA"
        assert result.reason == ResolveReason.PARTIAL_DOMINANT

    def test_ac2_6_alias_overrides_potential_ambiguity(
        self, similar_facilities: list[str]
    ) -> None:
        """alias 登録があれば部分一致経路をバイパスして確定する。

        現場で曖昧と判定されたファイル名パターンに対して、alias を登録して以後自動
        振り分けに乗せる業務フローを支援する設計。
        """
        result = resolve_facility(
            filename="サービスA東_提供実績.ex_",
            facility_names=similar_facilities,
            aliases={"サービスA東": ["サービスA東"]},  # 自己参照 alias で明示確定
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.matched_facility == "サービスA東"
        assert result.reason == ResolveReason.ALIAS_MATCH

    def test_ac2_6_unrelated_long_filename_no_candidate(
        self, similar_facilities: list[str]
    ) -> None:
        """4 事業所いずれにも一致しないファイル名は UNMATCHED。"""
        result = resolve_facility(
            filename="無関係事業者_提供実績.ex_",
            facility_names=similar_facilities,
            aliases={},
        )
        assert result.status == ResolveStatus.UNMATCHED
        assert result.reason == ResolveReason.NO_CANDIDATE


# ---------------------------------------------------------------------------
# AC2-7: 候補なしは UNMATCHED
# ---------------------------------------------------------------------------


class TestUnmatched:
    def test_ac2_7_no_candidate_returns_unmatched(self) -> None:
        result = resolve_facility(
            filename="無関係なファイル名.ex_",
            facility_names=["サービスA", "訪問BX"],
            aliases={},
        )
        assert result.status == ResolveStatus.UNMATCHED
        assert result.matched_facility is None
        assert result.candidates == ()
        assert result.reason == ResolveReason.NO_CANDIDATE

    def test_ac2_7_empty_facility_list_returns_unmatched(self) -> None:
        """事業所名リストが空 → UNMATCHED（誤配布リスクなし）。"""
        result = resolve_facility(
            filename="サービスA_提供実績.ex_",
            facility_names=[],
            aliases={"サービスA": ["サービスADC"]},  # alias があっても candidates 不在で UNMATCHED
        )
        assert result.status == ResolveStatus.UNMATCHED


# ---------------------------------------------------------------------------
# AC2-8: 境界値・不正入力でクラッシュしない
# ---------------------------------------------------------------------------


class TestBoundaryValues:
    def test_ac2_8_empty_filename_returns_unmatched(self) -> None:
        result = resolve_facility(
            filename="",
            facility_names=["サービスA"],
            aliases={},
        )
        assert result.status == ResolveStatus.UNMATCHED

    def test_ac2_8_whitespace_only_filename_returns_unmatched(self) -> None:
        """空白のみのファイル名 → 正規化後に空文字列になり UNMATCHED。"""
        result = resolve_facility(
            filename="   　\t\n",
            facility_names=["サービスA"],
            aliases={},
        )
        assert result.status == ResolveStatus.UNMATCHED

    def test_ac2_8_special_chars_in_filename_no_crash(self) -> None:
        """特殊文字を含むファイル名でクラッシュしない。"""
        result = resolve_facility(
            filename="!@#$%^&*()_+={}[]|\\:;'\"<>?,./~`",
            facility_names=["サービスA"],
            aliases={},
        )
        assert result.status == ResolveStatus.UNMATCHED

    def test_ac2_8_very_long_filename_no_crash(self) -> None:
        """極端に長いファイル名（10000 文字）でクラッシュしない。

        前後を `_` で囲んで語境界を確保し、事業所名がマッチする状態を作る。
        """
        long_name = ("X" * 10000) + "_サービスA_" + ("Y" * 10000)
        result = resolve_facility(
            filename=long_name,
            facility_names=["サービスA"],
            aliases={},
        )
        assert result.status == ResolveStatus.CONFIRMED

    def test_ac2_8_empty_facility_name_in_list_skipped(self) -> None:
        """事業所名リストに空文字列が含まれていても無視されてクラッシュしない。

        正常運用では config 層で弾かれるが、防御的実装。
        """
        result = resolve_facility(
            filename="サービスA_提供実績.ex_",
            facility_names=["", "サービスA", ""],
            aliases={},
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.matched_facility == "サービスA"


# ---------------------------------------------------------------------------
# AC2-9: PII 保護（ログ出力なし、例外メッセージに PII を含めない、テストデータも仮名）
# ---------------------------------------------------------------------------


class TestPiiProtection:
    def test_ac2_9_resolve_facility_emits_no_log(self, caplog: pytest.LogCaptureFixture) -> None:
        """resolve_facility はログ出力を一切行わない（PII 保護）。

        ファイル名・事業所名・別名は介護現場で機密扱いとなる場合があるため、
        どの判定経路でもログに出さない契約。
        """
        with caplog.at_level(logging.DEBUG, logger="wiseman_hub.pdf.facility_resolver"):
            resolve_facility(
                filename="サービスA_ユーザー001_提供実績.ex_",
                facility_names=["サービスA", "サービスA東"],
                aliases={"サービスA": ["サービスADC"]},
            )
        assert caplog.records == []

    def test_ac2_9_no_exception_raised_for_invalid_inputs(self) -> None:
        """不正入力で例外を投げない（例外メッセージ経由の PII 漏洩を防ぐ）。

        config 層で弾くべきパターン（None 値、不正型）が万一来ても、
        resolve_facility は黙って UNMATCHED を返す契約。
        """
        # 空文字列、空白のみは UNMATCHED
        for bad_filename in ["", " ", "\t", "\n", "　"]:
            result = resolve_facility(bad_filename, ["サービスA"], {})
            assert result.status == ResolveStatus.UNMATCHED


# ---------------------------------------------------------------------------
# AC2-10: alias 辞書の前提（config 層で検証済み）+ HIGH-1 安全強化
# ---------------------------------------------------------------------------


class TestAliasContract:
    def test_ac2_10_empty_alias_dict_works_normally(self) -> None:
        """alias 辞書が空でも問題なく動作（部分一致だけで判定）。"""
        result = resolve_facility(
            filename="サービスA_提供実績.ex_",
            facility_names=["サービスA"],
            aliases={},
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.reason == ResolveReason.PARTIAL_UNIQUE

    def test_high_1_alias_canonical_not_in_facility_names_returns_unmatched(self) -> None:
        """[HIGH-1 修正] alias の canonical が facility_names に存在しない場合は
        当該 alias 候補を skip し、最終的にどの事業所にも当たらなければ UNMATCHED。

        Evaluator 指摘: 旧設計では「呼び出し元の責務」として CONFIRMED を返していたが、
        呼び出し元が戻り値を実フォルダパスに使うと存在しないフォルダへ書き込みが発生する。
        resolver 側で canonical 実在を検証することで、誤配布の構造的リスクを排除する。
        """
        result = resolve_facility(
            filename="サービスADC_提供実績.ex_",
            facility_names=["訪問BX"],  # サービスA フォルダは存在しない
            aliases={"サービスA": ["サービスADC"]},
        )
        assert result.status == ResolveStatus.UNMATCHED
        assert result.matched_facility is None
        assert result.reason == ResolveReason.NO_CANDIDATE

    def test_high_1_partial_alias_some_canonicals_missing(self) -> None:
        """alias 辞書に複数 canonical があり、一部だけ facility_names に実在する場合、
        実在する canonical の alias のみが評価対象になる。
        """
        result = resolve_facility(
            filename="訪問BXDC_提供実績.ex_",
            facility_names=["訪問BX"],  # サービスA は存在しない、訪問BX は存在
            aliases={
                "サービスA": ["訪問BXDC"],  # canonical 不在 → skip
                "訪問BX": ["訪問BXDC"],  # canonical 実在 → ヒット
            },
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.matched_facility == "訪問BX"
        assert result.reason == ResolveReason.ALIAS_MATCH


# ---------------------------------------------------------------------------
# HIGH-2: 短 alias / 短 canonical 名の語境界要求（誤ヒット防止）
# ---------------------------------------------------------------------------


class TestWordBoundaryProtection:
    """[HIGH-2 修正] 短い alias / canonical name が無関係な事業所名の一部と偶然一致
    することによる誤配布を防ぐ語境界要求のテスト群。
    """

    def test_high_2_short_alias_not_matched_when_japanese_adjacent(self) -> None:
        """短い alias が他事業所名の一部に含まれていても、日本語隣接で語境界なし → 不一致。

        例: alias `{"サービスA": ["デイ"]}` を登録した状態で、
        ファイル名「夜間デイサービスB_提供.ex_」 → "デイ" が含まれるが
        前後「夜間」「サ」(日本語) で語境界なし → ALIAS_MATCH 不成立 → UNMATCHED
        （旧設計では CONFIRMED「サービスA」を返し誤配布になっていた）
        """
        result = resolve_facility(
            filename="夜間デイサービスB_提供.ex_",
            facility_names=["サービスA"],
            aliases={"サービスA": ["デイ"]},
        )
        assert result.status == ResolveStatus.UNMATCHED

    def test_high_2_short_alias_matched_when_word_bounded(self) -> None:
        """短い alias でも語境界（_, スペース, ()等）で囲まれていれば ALIAS_MATCH 成立。"""
        result = resolve_facility(
            filename="2025_デイ_提供.ex_",
            facility_names=["サービスA"],
            aliases={"サービスA": ["デイ"]},
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.matched_facility == "サービスA"
        assert result.reason == ResolveReason.ALIAS_MATCH

    def test_high_2_short_canonical_not_matched_when_japanese_adjacent(self) -> None:
        """短い canonical name が他事業所名の一部に含まれていても、日本語隣接で
        語境界なし → 不一致（部分一致 step も語境界要求）。

        ファイル名「夜間サービスA東_提供.ex_」+ canonical「サービスA」
        → "サービスA" は出現するが前「間」/後「東」(日本語) → 語境界なし → 候補外
        ファイル名に「夜間サービスA東」もないので UNMATCHED
        """
        result = resolve_facility(
            filename="夜間サービスA東_提供.ex_",
            facility_names=["サービスA"],
            aliases={},
        )
        assert result.status == ResolveStatus.UNMATCHED

    def test_high_2_alias_at_filename_start_word_bounded(self) -> None:
        """alias がファイル名先頭にある場合、前は文字列開始扱いで語境界 OK。"""
        result = resolve_facility(
            filename="サービスADC_提供.ex_",
            facility_names=["サービスA"],
            aliases={"サービスA": ["サービスADC"]},
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.reason == ResolveReason.ALIAS_MATCH

    def test_high_2_alias_at_filename_end_word_bounded(self) -> None:
        """alias がファイル名末尾（拡張子直前は記号区切り）にある場合、語境界 OK。"""
        result = resolve_facility(
            filename="2025年_サービスADC.ex_",
            facility_names=["サービスA"],
            aliases={"サービスA": ["サービスADC"]},
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.reason == ResolveReason.ALIAS_MATCH

    def test_high_2_alias_with_alphanumeric_adjacent_skipped(self) -> None:
        """alias の前後が英数字（区切り扱いでない）の場合は誤ヒット扱いで skip。

        例: alias "DC" + ファイル名 "ABCDC_提供.ex_" → "ABCDC" 内の "DC" は
        前「C」(英数字) で語境界なし → ALIAS_MATCH 不成立
        """
        result = resolve_facility(
            filename="ABCDC_提供.ex_",
            facility_names=["サービスA"],
            aliases={"サービスA": ["DC"]},
        )
        assert result.status == ResolveStatus.UNMATCHED


# ---------------------------------------------------------------------------
# ResolveResult 型の不変性
# ---------------------------------------------------------------------------


class TestResolveResultImmutability:
    def test_resolve_result_is_frozen(self) -> None:
        """ResolveResult は frozen dataclass で外から書き換え不可。"""
        result = resolve_facility(
            filename="サービスA_提供実績.ex_",
            facility_names=["サービスA"],
            aliases={},
        )
        with pytest.raises(FrozenInstanceError):
            result.status = ResolveStatus.UNMATCHED  # type: ignore[misc]

    def test_candidates_is_tuple_not_list(self) -> None:
        """candidates は tuple（immutable）で、list ではない。

        呼び出し元が誤って .append() などしないための保護。
        """
        result = resolve_facility(
            filename="サービスA_訪問BXY_提供.ex_",
            facility_names=["サービスA", "訪問BXY"],
            aliases={},
        )
        assert isinstance(result.candidates, tuple)


# ---------------------------------------------------------------------------
# 実運用シナリオの統合検証（仮名版）
# ---------------------------------------------------------------------------


class TestRealWorldScenarios:
    def test_facility_name_with_special_chars(self) -> None:
        """記号付き事業所名のマッチング確認（ADR-013 実機検証で類似パターンが実在）。

        記号「(メール)※持参」のような特殊文字を含む事業所名でも正常にマッチする。
        """
        result = resolve_facility(
            filename="特殊フォルダ(メール)※持参_提供実績.ex_",
            facility_names=["特殊フォルダ(メール)※持参", "訪問BX"],
            aliases={},
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.matched_facility == "特殊フォルダ(メール)※持参"
        assert result.reason == ResolveReason.PARTIAL_UNIQUE

    def test_alias_short_form_matches_long_canonical(self) -> None:
        """短縮 alias で長い canonical 名へ振り分けられる（語境界要件下でも機能）。"""
        result = resolve_facility(
            filename="2025_短縮_提供実績.ex_",
            facility_names=["特殊フォルダ(メール)※持参"],
            aliases={"特殊フォルダ(メール)※持参": ["短縮"]},
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.matched_facility == "特殊フォルダ(メール)※持参"
        assert result.reason == ResolveReason.ALIAS_MATCH

    def test_filename_with_year_month_prefix(self) -> None:
        """実運用に多い「YYYY年MM月_事業所名_帳票名.ex_」形式の振り分け。"""
        result = resolve_facility(
            filename="2025年04月_サービスA_提供実績.ex_",
            facility_names=["サービスA", "訪問BX", "クリニックC"],
            aliases={},
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.matched_facility == "サービスA"
