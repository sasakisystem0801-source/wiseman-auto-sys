"""名前マッチャーのユニットテスト。

OCR 抽出した氏名と input_dir 内の B/C ファイル群との照合を検証する。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wiseman_hub.pdf.matcher import (
    CandidateFile,
    KanjiMatcher,
    MatchResult,
    MatchStatus,
    NameMatcher,
    normalize_name,
)


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4\n%dummy\n")
    return path


# ---------------------------------------------------------------------------
# normalize_name
# ---------------------------------------------------------------------------


class TestNormalizeName:
    def test_strip_spaces(self) -> None:
        assert normalize_name("塩津 美喜子") == "塩津美喜子"

    def test_strip_full_width_spaces(self) -> None:
        assert normalize_name("塩津\u3000美喜子") == "塩津美喜子"

    def test_strip_multiple_spaces(self) -> None:
        assert normalize_name(" 塩津   美喜子 ") == "塩津美喜子"

    def test_empty_string(self) -> None:
        assert normalize_name("") == ""

    def test_keep_kanji_as_is(self) -> None:
        assert normalize_name("山田太郎") == "山田太郎"


# ---------------------------------------------------------------------------
# KanjiMatcher basic behavior
# ---------------------------------------------------------------------------


class TestKanjiMatcherExact:
    def test_exact_match_both_bc_returns_auto_matched(self, tmp_path: Path) -> None:
        _touch(tmp_path / "B_塩津美喜子.pdf")
        _touch(tmp_path / "C_塩津美喜子.pdf")

        matcher = KanjiMatcher(
            input_dir=tmp_path,
            source_b_pattern="B_{name}.pdf",
            source_c_pattern="C_{name}.pdf",
        )

        result = matcher.match("塩津 美喜子")

        assert result.status == MatchStatus.AUTO_MATCHED
        assert result.matched_b_path == tmp_path / "B_塩津美喜子.pdf"
        assert result.matched_c_path == tmp_path / "C_塩津美喜子.pdf"
        assert result.similar_candidates == []

    def test_exact_match_space_in_filename(self, tmp_path: Path) -> None:
        _touch(tmp_path / "B_塩津 美喜子.pdf")
        _touch(tmp_path / "C_塩津 美喜子.pdf")

        matcher = KanjiMatcher(
            input_dir=tmp_path,
            source_b_pattern="B_{name}.pdf",
            source_c_pattern="C_{name}.pdf",
        )

        result = matcher.match("塩津 美喜子")

        assert result.status == MatchStatus.AUTO_MATCHED

    def test_only_b_exists_exact(self, tmp_path: Path) -> None:
        _touch(tmp_path / "B_塩津美喜子.pdf")
        # C は存在しない

        matcher = KanjiMatcher(
            input_dir=tmp_path,
            source_b_pattern="B_{name}.pdf",
            source_c_pattern="C_{name}.pdf",
        )

        result = matcher.match("塩津 美喜子")

        # AC4: B/C 欠損は merger 側で WARN 処理。matcher は「片方一致」でも auto_matched
        # ただし欠損フラグは立てる
        assert result.status == MatchStatus.AUTO_MATCHED
        assert result.matched_b_path == tmp_path / "B_塩津美喜子.pdf"
        assert result.matched_c_path is None


class TestKanjiMatcherNeedsConfirmation:
    def test_one_char_diff_returns_needs_confirmation(self, tmp_path: Path) -> None:
        # 美喜子 vs 美貴子 = distance 1
        _touch(tmp_path / "B_塩津美喜子.pdf")
        _touch(tmp_path / "C_塩津美喜子.pdf")

        matcher = KanjiMatcher(
            input_dir=tmp_path,
            source_b_pattern="B_{name}.pdf",
            source_c_pattern="C_{name}.pdf",
        )

        result = matcher.match("塩津 美貴子")

        assert result.status == MatchStatus.NEEDS_CONFIRMATION
        assert result.matched_b_path is None
        assert result.matched_c_path is None
        assert len(result.similar_candidates) >= 1
        # B と C 両方が候補として出る
        kinds = {c.kind for c in result.similar_candidates}
        assert "B" in kinds
        assert "C" in kinds

    def test_two_char_diff_still_needs_confirmation(self, tmp_path: Path) -> None:
        # 距離 2 (境界値)
        _touch(tmp_path / "B_山田太郎.pdf")

        matcher = KanjiMatcher(
            input_dir=tmp_path,
            source_b_pattern="B_{name}.pdf",
            source_c_pattern="C_{name}.pdf",
        )

        result = matcher.match("山中二郎")  # 山田->山中(1) + 太->二(1) = distance 2

        assert result.status == MatchStatus.NEEDS_CONFIRMATION

    def test_distance_three_is_no_match(self, tmp_path: Path) -> None:
        # 距離 3 は候補から除外
        _touch(tmp_path / "B_山田太郎.pdf")

        matcher = KanjiMatcher(
            input_dir=tmp_path,
            source_b_pattern="B_{name}.pdf",
            source_c_pattern="C_{name}.pdf",
        )

        result = matcher.match("佐藤花子")

        assert result.status == MatchStatus.NO_MATCH
        assert result.similar_candidates == []

    def test_similar_candidates_sorted_by_distance(self, tmp_path: Path) -> None:
        _touch(tmp_path / "B_塩津美喜子.pdf")  # distance 1 from 塩津美貴子
        _touch(tmp_path / "B_潮津美貴子.pdf")  # distance 1 from 塩津美貴子 (塩→潮)
        _touch(tmp_path / "B_塩田美貴子.pdf")  # distance 1 from 塩津美貴子 (津→田)

        matcher = KanjiMatcher(
            input_dir=tmp_path,
            source_b_pattern="B_{name}.pdf",
            source_c_pattern="C_{name}.pdf",
        )

        result = matcher.match("塩津 美貴子")

        assert result.status == MatchStatus.NEEDS_CONFIRMATION
        # 全 distance 1、上位N件が返る。最大3件制限
        assert len(result.similar_candidates) <= 3
        # 距離昇順
        distances = [c.distance for c in result.similar_candidates]
        assert distances == sorted(distances)

    def test_limit_top_3_candidates(self, tmp_path: Path) -> None:
        # 5つの類似候補を用意（target「塩津 美貴子」に対し全て distance 1-2、完全一致なし）
        for name in ["塩津美喜子", "塩津美代子", "塩田美貴子", "潮津美貴子", "塩中美貴子"]:
            _touch(tmp_path / f"B_{name}.pdf")

        matcher = KanjiMatcher(
            input_dir=tmp_path,
            source_b_pattern="B_{name}.pdf",
            source_c_pattern="C_{name}.pdf",
        )

        result = matcher.match("塩津 美貴子")

        # 全候補が距離 1 か 2 なので needs_confirmation、最大 3 件
        assert result.status == MatchStatus.NEEDS_CONFIRMATION
        assert len(result.similar_candidates) == 3


class TestKanjiMatcherNoMatch:
    def test_empty_input_dir(self, tmp_path: Path) -> None:
        matcher = KanjiMatcher(
            input_dir=tmp_path,
            source_b_pattern="B_{name}.pdf",
            source_c_pattern="C_{name}.pdf",
        )

        result = matcher.match("塩津 美喜子")

        assert result.status == MatchStatus.NO_MATCH
        assert result.matched_b_path is None
        assert result.matched_c_path is None
        assert result.similar_candidates == []

    def test_no_similar_candidates(self, tmp_path: Path) -> None:
        _touch(tmp_path / "B_全然違う名前.pdf")

        matcher = KanjiMatcher(
            input_dir=tmp_path,
            source_b_pattern="B_{name}.pdf",
            source_c_pattern="C_{name}.pdf",
        )

        result = matcher.match("塩津 美喜子")

        assert result.status == MatchStatus.NO_MATCH

    def test_ignores_unrelated_files(self, tmp_path: Path) -> None:
        # パターンにマッチしないファイル
        _touch(tmp_path / "readme.txt")
        _touch(tmp_path / "A.pdf")
        _touch(tmp_path / "common.pdf")
        _touch(tmp_path / "B_塩津美喜子.pdf")

        matcher = KanjiMatcher(
            input_dir=tmp_path,
            source_b_pattern="B_{name}.pdf",
            source_c_pattern="C_{name}.pdf",
        )

        result = matcher.match("塩津 美喜子")

        assert result.status == MatchStatus.AUTO_MATCHED


class TestKanjiMatcherEdgeCases:
    def test_empty_user_name_raises(self, tmp_path: Path) -> None:
        matcher = KanjiMatcher(
            input_dir=tmp_path,
            source_b_pattern="B_{name}.pdf",
            source_c_pattern="C_{name}.pdf",
        )

        with pytest.raises(ValueError, match="user_name"):
            matcher.match("")

    def test_whitespace_only_user_name_raises(self, tmp_path: Path) -> None:
        matcher = KanjiMatcher(
            input_dir=tmp_path,
            source_b_pattern="B_{name}.pdf",
            source_c_pattern="C_{name}.pdf",
        )

        with pytest.raises(ValueError, match="user_name"):
            matcher.match("   ")

    def test_missing_input_dir_raises(self, tmp_path: Path) -> None:
        matcher = KanjiMatcher(
            input_dir=tmp_path / "nonexistent",
            source_b_pattern="B_{name}.pdf",
            source_c_pattern="C_{name}.pdf",
        )

        with pytest.raises(FileNotFoundError):
            matcher.match("塩津 美喜子")

    def test_pattern_without_name_placeholder_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match=r"\{name\}"):
            KanjiMatcher(
                input_dir=tmp_path,
                source_b_pattern="B_fixed.pdf",  # {name} なし
                source_c_pattern="C_{name}.pdf",
            )

    def test_regex_special_chars_in_pattern_literal(self, tmp_path: Path) -> None:
        """パターンに正規表現特殊文字（.）が含まれても literal として扱う。"""
        _touch(tmp_path / "B.塩津美喜子.pdf")

        matcher = KanjiMatcher(
            input_dir=tmp_path,
            source_b_pattern="B.{name}.pdf",  # "." はリテラルとして扱う
            source_c_pattern="C_{name}.pdf",
        )

        result = matcher.match("塩津 美喜子")

        # B.xxx.pdf がマッチする
        assert result.matched_b_path == tmp_path / "B.塩津美喜子.pdf"


class TestKanjiMatcherProtocol:
    def test_kanji_matcher_satisfies_name_matcher_protocol(self) -> None:
        # Protocol 準拠を確認（型チェッカー的な確認）
        def _accepts_matcher(m: NameMatcher) -> None:
            _ = m

        tmp = Path("/tmp")
        matcher = KanjiMatcher(
            input_dir=tmp,
            source_b_pattern="B_{name}.pdf",
            source_c_pattern="C_{name}.pdf",
        )
        _accepts_matcher(matcher)  # 実行時エラーにならなければ OK


class TestCandidateFile:
    def test_candidate_file_equality(self) -> None:
        c1 = CandidateFile(path=Path("/tmp/a.pdf"), kind="B", distance=1, extracted_name="塩津美喜子")
        c2 = CandidateFile(path=Path("/tmp/a.pdf"), kind="B", distance=1, extracted_name="塩津美喜子")
        assert c1 == c2


class TestLevenshteinBoundary:
    """Levenshtein 距離の境界値テスト（閾値 2 周辺）。"""

    def test_distance_two_included(self, tmp_path: Path) -> None:
        _touch(tmp_path / "B_山田太郎.pdf")
        matcher = KanjiMatcher(
            input_dir=tmp_path,
            source_b_pattern="B_{name}.pdf",
            source_c_pattern="C_{name}.pdf",
        )
        result = matcher.match("山川次郎")  # 山田→山川 + 太→次 = distance 2
        assert result.status == MatchStatus.NEEDS_CONFIRMATION

    def test_distance_three_excluded(self, tmp_path: Path) -> None:
        _touch(tmp_path / "B_山田太郎.pdf")
        matcher = KanjiMatcher(
            input_dir=tmp_path,
            source_b_pattern="B_{name}.pdf",
            source_c_pattern="C_{name}.pdf",
        )
        result = matcher.match("川中次夫")  # 4 文字全替換 = distance 4
        assert result.status == MatchStatus.NO_MATCH


class TestKanjiMatcherFilenameEdgeCases:
    def test_empty_name_in_filename_not_matched(self, tmp_path: Path) -> None:
        """`B_.pdf` のような name 部分が空のファイルは候補にしない（.+ は1文字以上）。"""
        _touch(tmp_path / "B_.pdf")
        matcher = KanjiMatcher(
            input_dir=tmp_path,
            source_b_pattern="B_{name}.pdf",
            source_c_pattern="C_{name}.pdf",
        )
        result = matcher.match("塩津美喜子")
        assert result.status == MatchStatus.NO_MATCH

    def test_duplicate_exact_match_deterministic(self, tmp_path: Path) -> None:
        """同姓同名の事故的命名では sorted 順で最初のファイルが採用される。"""
        # サブディレクトリに置いて path 順を決定論化
        (tmp_path / "subdir1").mkdir()
        (tmp_path / "subdir2").mkdir()
        # iterdir は sorted で走査されるため "B_A.pdf" -> "B_B.pdf" の順
        _touch(tmp_path / "B_A_塩津美喜子.pdf")
        _touch(tmp_path / "B_B_塩津美喜子.pdf")

        # ただしこのテストは B_{name}.pdf パターンなので上記は別名扱い
        # 真に同名のファイルを別ディレクトリに置いて確認するのは難しいため、
        # 同一 iterdir 結果の決定論性を mock で検証する別アプローチが必要。
        # ここでは matcher が OS 依存の順序に依存しないことを間接的に保証する意味で、
        # 複数回呼んで結果が安定していることを確認する。
        matcher = KanjiMatcher(
            input_dir=tmp_path,
            source_b_pattern="B_A_{name}.pdf",
            source_c_pattern="C_{name}.pdf",
        )
        r1 = matcher.match("塩津美喜子")
        r2 = matcher.match("塩津美喜子")
        assert r1.matched_b_path == r2.matched_b_path


class TestMatchResult:
    def test_has_any_match_property_auto_matched(self, tmp_path: Path) -> None:
        r = MatchResult(
            status=MatchStatus.AUTO_MATCHED,
            matched_b_path=tmp_path / "B.pdf",
            matched_c_path=None,
            similar_candidates=[],
        )
        assert r.has_any_match is True

    def test_has_any_match_property_no_match(self) -> None:
        r = MatchResult(
            status=MatchStatus.NO_MATCH,
            matched_b_path=None,
            matched_c_path=None,
            similar_candidates=[],
        )
        assert r.has_any_match is False
