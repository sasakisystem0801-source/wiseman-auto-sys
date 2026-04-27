"""facility_resolver のユニットテスト（PR2）。

誤配布防止のための安全マッチング戦略を網羅検証する。特に AC2-6（false positive
回避）と AC2-9（PII 保護）+ レビュー指摘 H-A〜H-D を厚めにテストする。

PII 防御方針: 本ファイルのテストデータには実在する介護施設名・利用者名を含めない。
すべて仮名（「サービスA」「USER_ALPHA」等）で構成し、CI ログ・PR diff 経由の
PII 漏洩経路を遮断する。
"""

from __future__ import annotations

import logging
from dataclasses import FrozenInstanceError

import pytest

from wiseman_hub.pdf.facility_resolver import (
    ResolveReason,
    ResolveResult,
    ResolveStatus,
    find_orphan_alias_canonicals,
    normalize_name,
    resolve_facility,
)

# ---------------------------------------------------------------------------
# normalize_name: NFKC 正規化（空白除去なし）
# ---------------------------------------------------------------------------


class TestNormalizeName:
    def test_empty_string_returns_empty(self) -> None:
        assert normalize_name("") == ""

    def test_nfkc_halfwidth_kana_to_fullwidth(self) -> None:
        assert normalize_name("ｱｲｳ") == normalize_name("アイウ")

    def test_nfkc_fullwidth_alnum_to_halfwidth(self) -> None:
        assert normalize_name("ＡＢＣ１２３") == "ABC123"

    def test_nfkc_fullwidth_brackets_to_halfwidth(self) -> None:
        assert normalize_name("サービス（拡張）") == "サービス(拡張)"

    def test_whitespace_preserved_not_stripped(self) -> None:
        """空白は除去せず保持（語境界として機能させるため、レビュー H-C 対応）。

        NFKC は全角スペース U+3000 を半角スペース " " に変換する標準動作だが、
        変換後も空白として残り、`_ALIAS_BOUNDARY_CHARS` で境界判定される。
        """
        assert normalize_name("サービス A") == "サービス A"
        # NFKC で全角スペース → 半角スペース変換、ただし空白として保持される
        assert normalize_name("サービス　A") == "サービス A"
        assert normalize_name("サー\tビス\nA") == "サー\tビス\nA"

    def test_idempotent(self) -> None:
        s = "ｻｰﾋﾞｽ A（拡張）"
        assert normalize_name(normalize_name(s)) == normalize_name(s)


# ---------------------------------------------------------------------------
# AC2-1: alias 一致が他のどのマッチより優先される
# ---------------------------------------------------------------------------


class TestAliasPriority:
    def test_ac2_1_alias_match_takes_priority_over_partial(self) -> None:
        """alias 一致は部分一致より優先 → ALIAS_MATCH で確定。"""
        result = resolve_facility(
            filename="サービスADC_提供実績.ex_",
            facility_names=["サービスA", "訪問BX"],
            aliases={"サービスA": ["サービスADC", "サービスA短"]},
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.matched_facility == "サービスA"
        assert result.reason == ResolveReason.ALIAS_MATCH

    def test_ac2_1_alias_match_uses_normalized_comparison(self) -> None:
        """半角全角混在で alias マッチ。"""
        result = resolve_facility(
            filename="ｻｰﾋﾞｽADC_提供実績.ex_",
            facility_names=["サービスA"],
            aliases={"サービスA": ["サービスADC"]},
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.matched_facility == "サービスA"
        assert result.reason == ResolveReason.ALIAS_MATCH

    def test_alias_match_returns_canonical_not_alias_string(self) -> None:
        """matched_facility は canonical (フォルダ名)、alias 文字列ではない。"""
        result = resolve_facility(
            filename="サービスADC_提供実績.ex_",
            facility_names=["サービスA"],
            aliases={"サービスA": ["サービスADC"]},
        )
        assert result.matched_facility == "サービスA"
        assert result.matched_facility != "サービスADC"

    def test_alias_check_runs_before_exact_match(self) -> None:
        """alias 検査は完全一致検査より前に走る（順序保証）。"""
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
        result = resolve_facility(
            filename="ｱｲｳ", facility_names=["アイウ"], aliases={}
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.matched_facility == "アイウ"
        assert result.reason == ResolveReason.EXACT_MATCH

    def test_ac2_2_exact_match_with_brackets(self) -> None:
        result = resolve_facility(
            filename="サービス(拡張)",
            facility_names=["サービス（拡張）"],
            aliases={},
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.matched_facility == "サービス（拡張）"
        assert result.reason == ResolveReason.EXACT_MATCH

    def test_exact_match_distinguishes_whitespace_difference(self) -> None:
        """空白の有無は別物として扱う（H-C 対応: 空白を境界文字化したため）。"""
        # 「サー ビス」と「サービス」は別事業所として扱われる
        result = resolve_facility(
            filename="サー ビス A",
            facility_names=["サービスA"],
            aliases={},
        )
        # 正規化後も空白は残るので EXACT_MATCH 不成立、部分一致も成立しない
        assert result.status == ResolveStatus.UNMATCHED


# ---------------------------------------------------------------------------
# AC2-3〜AC2-5: 部分一致（語境界要求あり）
# ---------------------------------------------------------------------------


class TestPartialMatch:
    def test_ac2_3_unique_partial_match_confirmed(self) -> None:
        """事業所名がファイル名に語境界付きで一意に部分一致 → PARTIAL_UNIQUE。"""
        result = resolve_facility(
            filename="2025年04月_サービスA_提供実績.ex_",
            facility_names=["サービスA", "訪問BX", "クリニックC"],
            aliases={},
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.matched_facility == "サービスA"
        assert result.reason == ResolveReason.PARTIAL_UNIQUE

    def test_ac2_4_long_winner_with_two_char_diff_confirmed(self) -> None:
        """ファイル名に複数の独立した事業所名が含まれ、最長候補が次長より 2 文字以上長い
        → CONFIRMED (PARTIAL_DOMINANT)。"""
        result = resolve_facility(
            filename="サービスA_クリニックC2提供_実績.ex_",
            facility_names=["サービスA", "クリニックC2提供"],
            aliases={},
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.matched_facility == "クリニックC2提供"
        assert result.reason == ResolveReason.PARTIAL_DOMINANT

    def test_ac2_5_close_partial_match_returns_ambiguous(self) -> None:
        """ファイル名に複数の独立事業所名が含まれ、最長と次長の差が 0 文字（同長）
        → AMBIGUOUS（差 < 2 文字）。"""
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
        """境界値: 差がちょうど 2 文字 → CONFIRMED (PARTIAL_DOMINANT)。"""
        result = resolve_facility(
            filename="ABCD_EFGHIJ_provided.ex_",
            facility_names=["ABCD", "EFGHIJ"],
            aliases={},
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.matched_facility == "EFGHIJ"
        assert result.reason == ResolveReason.PARTIAL_DOMINANT

    def test_ambiguous_candidates_sorted_by_length_descending(self) -> None:
        """AMBIGUOUS の candidates は長さ降順で UI プルダウン表示順を保証。"""
        result = resolve_facility(
            filename="ABCD_EFGH_IJK_提供.ex_",
            facility_names=["ABCD", "IJK", "EFGH"],
            aliases={},
        )
        # ABCD(4), EFGH(4), IJK(3) → 全部マッチ、最長 4 と次長 4 で差 0 → AMBIGUOUS
        assert result.status == ResolveStatus.AMBIGUOUS
        # 長さ降順保証: 最初の 2 つは長さ 4、最後は長さ 3
        assert len(result.candidates[0]) == 4
        assert len(result.candidates[1]) == 4
        assert len(result.candidates[2]) == 3


# ---------------------------------------------------------------------------
# AC2-6: False positive 回避（最重要 KPI: 介護現場の誤配布回避）
# ---------------------------------------------------------------------------


class TestFalsePositiveAvoidance:
    """似た事業所名混在環境で誤配布が起きないことを保証する。

    旧 docstring に「本田デイケア」等の実名残置があったが H-F 対応で全削除。
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
        """ファイル名「サービスA_提供実績.ex_」+ 4 事業所混在 → 「サービスA」のみマッチ。

        - 「サービスA」: 後ろ "_" で語境界 OK
        - 「サービスA（拡張）」「サービスA東」: ファイル名に「（拡張）」「東」がない
        - 「夜間サービスA」: ファイル名に「夜間」がない
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
        """ファイル名「サービスA東_提供実績.ex_」+ 4 事業所混在 → 「サービスA東」のみマッチ。

        新ロジック（語境界要求）:
        - 「サービスA」: 直後「東」(日本語) → 語境界なし → 候補から除外
        - 「サービスA東」: 後ろ "_" → 語境界 OK
        - 「サービスA（拡張）」「夜間サービスA」: ファイル名に出現せず候補化しない

        旧設計（語境界なし）では両方候補で AMBIGUOUS だったが、HIGH-2 対応で日本語
        隣接の substring を弾く設計に強化。
        """
        result = resolve_facility(
            filename="サービスA東_提供実績.ex_",
            facility_names=similar_facilities,
            aliases={},
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.matched_facility == "サービスA東"
        assert result.reason == ResolveReason.PARTIAL_UNIQUE

    def test_ac2_6_dominant_match_promoted_when_diff_two_chars(
        self, similar_facilities: list[str]
    ) -> None:
        """ファイル名に複数事業所名が独立出現、最長と次長の差 2 → PARTIAL_DOMINANT。

        ファイル名「サービスA_夜間サービスA_合同_提供.ex_」:
        - 「サービスA」(5): "_サービスA_" で出現、語境界 OK
        - 「夜間サービスA」(7): "_夜間サービスA_" で出現、語境界 OK
        - 差 7 - 5 = 2 → CONFIRMED 「夜間サービスA」（旧テスト名 ambiguous_when... を改名）
        """
        result = resolve_facility(
            filename="サービスA_夜間サービスA_合同_提供.ex_",
            facility_names=similar_facilities,
            aliases={},
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.matched_facility == "夜間サービスA"
        assert result.reason == ResolveReason.PARTIAL_DOMINANT

    def test_ac2_6_alias_overrides_potential_ambiguity(
        self, similar_facilities: list[str]
    ) -> None:
        """alias 登録があれば部分一致経路をバイパスして確定する。"""
        result = resolve_facility(
            filename="サービスA東_提供実績.ex_",
            facility_names=similar_facilities,
            aliases={"サービスA東": ["サービスA東"]},
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.matched_facility == "サービスA東"
        assert result.reason == ResolveReason.ALIAS_MATCH

    def test_ac2_6_unrelated_long_filename_no_candidate(
        self, similar_facilities: list[str]
    ) -> None:
        """4 事業所いずれにも一致しない → UNMATCHED (NO_CANDIDATE)。"""
        result = resolve_facility(
            filename="無関係事業者_提供実績.ex_",
            facility_names=similar_facilities,
            aliases={},
        )
        assert result.status == ResolveStatus.UNMATCHED
        assert result.reason == ResolveReason.NO_CANDIDATE


# ---------------------------------------------------------------------------
# H-A: alias 経路で複数 canonical hit → AMBIGUOUS_ALIAS（誤配布防止）
# ---------------------------------------------------------------------------


class TestAliasMultipleCanonicalHit:
    """[H-A 対応] 異なる canonical の alias が同一ファイル名にヒットした場合、
    dict 順で先勝ちせず AMBIGUOUS_ALIAS を返して手動振り分けに回す。

    PR1 _validate_facility_aliases は alias の global 一意性を強制するが、value 側
    の正規化後衝突や動的 alias 注入の経路で破られる可能性に対する resolver 側の防御。
    """

    def test_h_a_two_aliases_from_different_canonicals_match_filename(self) -> None:
        """ファイル名「A短_B短_提供.ex_」+ alias `{"施設A": ["A短"], "施設B": ["B短"]}`
        → 両方の canonical がマッチ → AMBIGUOUS_ALIAS。
        """
        result = resolve_facility(
            filename="A短_B短_提供.ex_",
            facility_names=["施設A", "施設B"],
            aliases={"施設A": ["A短"], "施設B": ["B短"]},
        )
        assert result.status == ResolveStatus.AMBIGUOUS
        assert result.reason == ResolveReason.AMBIGUOUS_ALIAS
        assert set(result.candidates) == {"施設A", "施設B"}

    def test_h_a_single_canonical_with_multiple_alias_hits_remains_confirmed(
        self,
    ) -> None:
        """同じ canonical の複数 alias がヒットしても AMBIGUOUS にならない。"""
        result = resolve_facility(
            filename="A短_A別名_提供.ex_",
            facility_names=["施設A"],
            aliases={"施設A": ["A短", "A別名"]},
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.matched_facility == "施設A"
        assert result.reason == ResolveReason.ALIAS_MATCH


# ---------------------------------------------------------------------------
# H-B: 正規化完全一致の複数 hit → AMBIGUOUS_EXACT
# ---------------------------------------------------------------------------


class TestExactMatchMultipleHit:
    """[H-B 対応] 正規化後に同一文字列となる事業所名が複数あれば AMBIGUOUS_EXACT。"""

    def test_h_b_normalized_duplicate_facility_names_returns_ambiguous_exact(
        self,
    ) -> None:
        """`["サービスA", "サービスＡ"]`（半角/全角の A）両方とも normalize で同一
        → AMBIGUOUS_EXACT で先勝ち回避。"""
        result = resolve_facility(
            filename="サービスA",
            facility_names=["サービスA", "サービスＡ"],  # 後者は全角 Ａ
            aliases={},
        )
        assert result.status == ResolveStatus.AMBIGUOUS
        assert result.reason == ResolveReason.AMBIGUOUS_EXACT
        assert set(result.candidates) == {"サービスA", "サービスＡ"}


# ---------------------------------------------------------------------------
# H-D: ResolveResult `__post_init__` で不変条件強制
# ---------------------------------------------------------------------------


class TestResolveResultInvariants:
    """[H-D 対応] 外部から不正な status × matched_facility × candidates × reason の
    組み合わせを構築できないことを保証。"""

    def test_h_d_confirmed_without_matched_facility_raises(self) -> None:
        with pytest.raises(ValueError, match="CONFIRMED requires matched_facility"):
            ResolveResult(
                status=ResolveStatus.CONFIRMED,
                matched_facility=None,
                candidates=(),
                reason=ResolveReason.ALIAS_MATCH,
            )

    def test_h_d_confirmed_with_wrong_candidates_raises(self) -> None:
        with pytest.raises(ValueError, match="candidates"):
            ResolveResult(
                status=ResolveStatus.CONFIRMED,
                matched_facility="A",
                candidates=("A", "B"),  # CONFIRMED は (A,) でなければならない
                reason=ResolveReason.ALIAS_MATCH,
            )

    def test_h_d_ambiguous_with_matched_facility_raises(self) -> None:
        with pytest.raises(ValueError, match="AMBIGUOUS forbids matched_facility"):
            ResolveResult(
                status=ResolveStatus.AMBIGUOUS,
                matched_facility="A",
                candidates=("A", "B"),
                reason=ResolveReason.AMBIGUOUS_PARTIAL,
            )

    def test_h_d_ambiguous_with_single_candidate_raises(self) -> None:
        with pytest.raises(ValueError, match="AMBIGUOUS requires >= 2 candidates"):
            ResolveResult(
                status=ResolveStatus.AMBIGUOUS,
                matched_facility=None,
                candidates=("A",),
                reason=ResolveReason.AMBIGUOUS_PARTIAL,
            )

    def test_h_d_unmatched_with_matched_facility_raises(self) -> None:
        with pytest.raises(ValueError, match="UNMATCHED forbids matched_facility"):
            ResolveResult(
                status=ResolveStatus.UNMATCHED,
                matched_facility="A",
                candidates=(),
                reason=ResolveReason.NO_CANDIDATE,
            )

    def test_h_d_reason_status_mismatch_raises(self) -> None:
        """reason ALIAS_MATCH (CONFIRMED 系) に status UNMATCHED → ValueError。"""
        with pytest.raises(ValueError, match="requires status"):
            ResolveResult(
                status=ResolveStatus.UNMATCHED,
                matched_facility=None,
                candidates=(),
                reason=ResolveReason.ALIAS_MATCH,
            )


# ---------------------------------------------------------------------------
# is_auto_distributable / needs_manual_* プロパティ（PR4 UI 統合用）
# ---------------------------------------------------------------------------


class TestResolveResultProperties:
    def test_is_auto_distributable_true_for_confirmed(self) -> None:
        r = ResolveResult.confirmed("A", ResolveReason.ALIAS_MATCH)
        assert r.is_auto_distributable is True
        assert r.needs_manual_selection is False
        assert r.needs_manual_input is False

    def test_needs_manual_selection_true_for_ambiguous(self) -> None:
        r = ResolveResult.ambiguous(("A", "B"), ResolveReason.AMBIGUOUS_PARTIAL)
        assert r.is_auto_distributable is False
        assert r.needs_manual_selection is True
        assert r.needs_manual_input is False

    def test_needs_manual_input_true_for_unmatched(self) -> None:
        r = ResolveResult.unmatched(ResolveReason.NO_CANDIDATE)
        assert r.is_auto_distributable is False
        assert r.needs_manual_selection is False
        assert r.needs_manual_input is True


# ---------------------------------------------------------------------------
# AC2-7: 候補なしは UNMATCHED（細分 reason）
# ---------------------------------------------------------------------------


class TestUnmatched:
    def test_ac2_7_no_candidate_returns_unmatched_with_reason(self) -> None:
        result = resolve_facility(
            filename="無関係なファイル名.ex_",
            facility_names=["サービスA", "訪問BX"],
            aliases={},
        )
        assert result.status == ResolveStatus.UNMATCHED
        assert result.matched_facility is None
        assert result.candidates == ()
        assert result.reason == ResolveReason.NO_CANDIDATE

    def test_empty_facility_list_returns_unmatched_with_distinct_reason(self) -> None:
        """事業所名リスト空 → EMPTY_FACILITY_LIST（NO_CANDIDATE と区別、設定エラー検出用）。"""
        result = resolve_facility(
            filename="サービスA_提供実績.ex_",
            facility_names=[],
            aliases={"サービスA": ["サービスADC"]},
        )
        assert result.status == ResolveStatus.UNMATCHED
        assert result.reason == ResolveReason.EMPTY_FACILITY_LIST


# ---------------------------------------------------------------------------
# AC2-8: 境界値・不正入力でクラッシュしない
# ---------------------------------------------------------------------------


class TestBoundaryValues:
    def test_empty_filename_returns_unmatched_empty_filename_reason(self) -> None:
        result = resolve_facility("", ["サービスA"], {})
        assert result.status == ResolveStatus.UNMATCHED
        assert result.reason == ResolveReason.EMPTY_FILENAME

    def test_whitespace_only_filename_returns_unmatched(self) -> None:
        result = resolve_facility("   　\t\n", ["サービスA"], {})
        assert result.status == ResolveStatus.UNMATCHED
        assert result.reason == ResolveReason.EMPTY_FILENAME

    def test_special_chars_in_filename_no_crash(self) -> None:
        result = resolve_facility(
            filename="!@#$%^&*()_+={}[]|\\:;'\"<>?,./~`",
            facility_names=["サービスA"],
            aliases={},
        )
        assert result.status == ResolveStatus.UNMATCHED

    def test_very_long_filename_no_crash(self) -> None:
        """極端に長いファイル名（10000+α 文字）でクラッシュしない、語境界で囲む。"""
        long_name = ("X" * 10000) + "_サービスA_" + ("Y" * 10000)
        result = resolve_facility(long_name, ["サービスA"], {})
        assert result.status == ResolveStatus.CONFIRMED

    def test_empty_facility_name_in_list_skipped(self) -> None:
        """事業所名リストに空文字列が含まれていても無視されてクラッシュしない。"""
        result = resolve_facility(
            "サービスA_提供実績.ex_", ["", "サービスA", ""], {}
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.matched_facility == "サービスA"

    def test_empty_alias_list_skipped_falls_through_to_partial(self) -> None:
        """alias 配列が空でも crash せず、部分一致 step に fall-through する。"""
        result = resolve_facility(
            filename="サービスA_提供実績.ex_",
            facility_names=["サービスA"],
            aliases={"サービスA": []},  # 空 list
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.reason == ResolveReason.PARTIAL_UNIQUE


# ---------------------------------------------------------------------------
# AC2-9: PII 保護（ログ・stdout・stderr ゼロ、テストデータ仮名化）
# ---------------------------------------------------------------------------


class TestPiiProtection:
    def test_ac2_9_resolve_facility_emits_no_log_or_print(
        self,
        caplog: pytest.LogCaptureFixture,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """resolve_facility はログ出力・print・stderr 書き込みを一切行わない。

        caplog（全 logger NOTSET）+ capsys で print/sys.stderr も検出する。
        将来 debug 用 print 混入を CI で防ぐ強化版。
        """
        with caplog.at_level(logging.NOTSET):  # 全 logger 全 level 捕捉
            resolve_facility(
                filename="サービスA_USER_ALPHA_提供実績.ex_",
                facility_names=["サービスA", "サービスA東"],
                aliases={"サービスA": ["サービスADC"]},
            )
        assert caplog.records == []
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""

    def test_ac2_9_no_exception_raised_for_invalid_filenames(self) -> None:
        for bad in ["", " ", "\t", "\n", "　"]:
            result = resolve_facility(bad, ["サービスA"], {})
            assert result.status == ResolveStatus.UNMATCHED


# ---------------------------------------------------------------------------
# AC2-10: alias 辞書の前提 + HIGH-1（canonical 実在検証）
# ---------------------------------------------------------------------------


class TestAliasContract:
    def test_ac2_10_empty_alias_dict_works_normally(self) -> None:
        result = resolve_facility(
            "サービスA_提供実績.ex_", ["サービスA"], {}
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.reason == ResolveReason.PARTIAL_UNIQUE

    def test_high_1_alias_canonical_not_in_facility_names_returns_unmatched(self) -> None:
        """[HIGH-1] alias の canonical が facility_names に不在 → 当該 alias を skip
        して最終的に UNMATCHED。

        旧設計: CONFIRMED「サービスA」を返していた → 存在しないフォルダへの書き込み発生
        新設計: skip → 部分一致も成立せず UNMATCHED で誤配布パスを構造的排除
        """
        result = resolve_facility(
            filename="サービスADC_提供実績.ex_",
            facility_names=["訪問BX"],
            aliases={"サービスA": ["サービスADC"]},
        )
        assert result.status == ResolveStatus.UNMATCHED
        assert result.matched_facility is None

    def test_high_1_partial_alias_some_canonicals_missing(self) -> None:
        """alias 辞書に複数 canonical があり、一部だけ実在する場合は実在する canonical の
        alias のみが評価対象。"""
        result = resolve_facility(
            filename="訪問BXDC_提供実績.ex_",
            facility_names=["訪問BX"],
            aliases={
                "サービスA": ["訪問BXDC"],  # canonical 不在 → skip
                "訪問BX": ["訪問BXDC"],  # canonical 実在 → ヒット
            },
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.matched_facility == "訪問BX"
        assert result.reason == ResolveReason.ALIAS_MATCH


# ---------------------------------------------------------------------------
# HIGH-2: 短 alias / 短 canonical 名の語境界要求
# ---------------------------------------------------------------------------


class TestWordBoundaryProtection:
    """[HIGH-2] 短い alias / canonical 名が無関係な事業所名の一部と偶然一致する
    ことによる誤配布を防ぐ語境界要求のテスト群。"""

    def test_high_2_short_alias_not_matched_when_japanese_adjacent(self) -> None:
        """alias 「デイ」がファイル名「夜間デイサービスB_提供.ex_」に含まれるが、
        前後「夜間」「サ」(日本語) で語境界なし → UNMATCHED。"""
        result = resolve_facility(
            filename="夜間デイサービスB_提供.ex_",
            facility_names=["サービスA"],
            aliases={"サービスA": ["デイ"]},
        )
        assert result.status == ResolveStatus.UNMATCHED

    def test_high_2_short_alias_matched_when_word_bounded(self) -> None:
        """短い alias でも語境界（_, スペース等）で囲まれていれば ALIAS_MATCH 成立。"""
        result = resolve_facility(
            filename="2025_デイ_提供.ex_",
            facility_names=["サービスA"],
            aliases={"サービスA": ["デイ"]},
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.reason == ResolveReason.ALIAS_MATCH

    def test_high_2_short_canonical_not_matched_when_japanese_adjacent(self) -> None:
        """短い canonical name が他事業所名の一部に含まれていても、日本語隣接で
        語境界なし → 不一致。"""
        result = resolve_facility(
            filename="夜間サービスA東_提供.ex_",
            facility_names=["サービスA"],
            aliases={},
        )
        assert result.status == ResolveStatus.UNMATCHED

    def test_high_2_alias_at_filename_start_word_bounded(self) -> None:
        result = resolve_facility(
            filename="サービスADC_提供.ex_",
            facility_names=["サービスA"],
            aliases={"サービスA": ["サービスADC"]},
        )
        assert result.status == ResolveStatus.CONFIRMED

    def test_high_2_alias_at_filename_end_word_bounded(self) -> None:
        result = resolve_facility(
            filename="2025年_サービスADC.ex_",
            facility_names=["サービスA"],
            aliases={"サービスA": ["サービスADC"]},
        )
        assert result.status == ResolveStatus.CONFIRMED

    def test_high_2_alias_with_alphanumeric_adjacent_skipped(self) -> None:
        """alias 「DC」+ ファイル名「ABCDC_提供.ex_」→ DC の前「C」(英数字) で語境界なし
        → ALIAS 不成立 → UNMATCHED（alias step がたしかに skip された証）。"""
        result = resolve_facility(
            filename="ABCDC_提供.ex_",
            facility_names=["サービスA"],
            aliases={"サービスA": ["DC"]},
        )
        assert result.status == ResolveStatus.UNMATCHED

    def test_high_2_whitespace_works_as_boundary(self) -> None:
        """空白（半角・全角・タブ）が語境界として機能する（H-C 対応の効果検証）。"""
        # 半角スペース
        r1 = resolve_facility(
            "2025 サービスA 提供.ex_", ["サービスA"], {}
        )
        assert r1.status == ResolveStatus.CONFIRMED
        # 全角スペース
        r2 = resolve_facility(
            "2025　サービスA　提供.ex_", ["サービスA"], {}
        )
        assert r2.status == ResolveStatus.CONFIRMED


# ---------------------------------------------------------------------------
# find_orphan_alias_canonicals: 設定不整合検出ヘルパー（silent-failure HIGH-2 対応）
# ---------------------------------------------------------------------------


class TestFindOrphanAliasCanonicals:
    def test_returns_canonical_not_in_facility_names(self) -> None:
        orphans = find_orphan_alias_canonicals(
            facility_names=["サービスA"],
            aliases={"サービスA": ["A短"], "削除済み施設": ["X短"]},
        )
        assert orphans == ["削除済み施設"]

    def test_empty_when_all_canonicals_exist(self) -> None:
        orphans = find_orphan_alias_canonicals(
            facility_names=["サービスA", "訪問BX"],
            aliases={"サービスA": ["A短"], "訪問BX": ["BX短"]},
        )
        assert orphans == []

    def test_empty_when_aliases_empty(self) -> None:
        assert find_orphan_alias_canonicals(["サービスA"], {}) == []


# ---------------------------------------------------------------------------
# ResolveResult 型の不変性（frozen + tuple）
# ---------------------------------------------------------------------------


class TestResolveResultImmutability:
    def test_resolve_result_is_frozen(self) -> None:
        result = resolve_facility(
            "サービスA_提供実績.ex_", ["サービスA"], {}
        )
        with pytest.raises(FrozenInstanceError):
            result.status = ResolveStatus.UNMATCHED  # type: ignore[misc]

    def test_candidates_is_tuple_not_list(self) -> None:
        result = resolve_facility(
            "サービスA_訪問BXY_提供.ex_", ["サービスA", "訪問BXY"], {}
        )
        assert isinstance(result.candidates, tuple)


# ---------------------------------------------------------------------------
# 実運用シナリオの統合検証（仮名版）
# ---------------------------------------------------------------------------


class TestRealWorldScenarios:
    def test_facility_name_with_special_chars(self) -> None:
        """記号付き事業所名のマッチング。記号「(配送)+特殊」は仮想パターン。"""
        result = resolve_facility(
            filename="特殊フォルダ(配送)+特殊_提供実績.ex_",
            facility_names=["特殊フォルダ(配送)+特殊", "訪問BX"],
            aliases={},
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.matched_facility == "特殊フォルダ(配送)+特殊"

    def test_alias_short_form_matches_long_canonical(self) -> None:
        result = resolve_facility(
            filename="2025_短縮_提供実績.ex_",
            facility_names=["特殊フォルダ(配送)+特殊"],
            aliases={"特殊フォルダ(配送)+特殊": ["短縮"]},
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.matched_facility == "特殊フォルダ(配送)+特殊"
        assert result.reason == ResolveReason.ALIAS_MATCH

    def test_filename_with_year_month_prefix(self) -> None:
        result = resolve_facility(
            filename="2025年04月_サービスA_提供実績.ex_",
            facility_names=["サービスA", "訪問BX", "クリニックC"],
            aliases={},
        )
        assert result.status == ResolveStatus.CONFIRMED
        assert result.matched_facility == "サービスA"
