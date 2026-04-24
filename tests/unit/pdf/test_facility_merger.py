"""facility_merger.py のテスト (TDD)."""

from __future__ import annotations

from pathlib import Path

import fitz  # type: ignore[import-untyped]
import pytest

from wiseman_hub.pdf.facility_merger import (
    PLAN_DIR_NAME,
    REPORT_DIR_NAME,
    FacilityMergeReport,
    merge_facility,
)


def _make_pdf(path: Path, pages_text: list[str]) -> None:
    """各ページに指定テキストを含む PDF を生成。"""
    doc = fitz.open()
    try:
        for text in pages_text:
            page = doc.new_page(width=595, height=842)
            page.insert_text((50, 100), text, fontsize=11, fontname="japan-s")
        path.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(path))
    finally:
        doc.close()


def _page_count(path: Path) -> int:
    doc = fitz.open(path)
    try:
        return doc.page_count
    finally:
        doc.close()


@pytest.fixture
def workspace(tmp_path: Path) -> dict[str, Path]:
    """テスト用のフォルダ構造を用意する。"""
    facility_dir = tmp_path / "きなり(メール)"
    plan_dir = facility_dir / PLAN_DIR_NAME
    report_dir = facility_dir / REPORT_DIR_NAME
    a_pdf = tmp_path / "提供実績.pdf"
    output_root = tmp_path / "output"
    return {
        "facility_dir": facility_dir,
        "plan_dir": plan_dir,
        "report_dir": report_dir,
        "a_pdf": a_pdf,
        "output_root": output_root,
    }


class TestMergeFacility:
    """merge_facility の正常系・準正常系。"""

    def test_merge_all_three_present(self, workspace: dict[str, Path]) -> None:
        """A ページ + B + C 全て揃ってる利用者は 3 者結合される。"""
        _make_pdf(
            workspace["a_pdf"],
            [
                "令和08年03月分 提供実績チェックリスト 氏名 塩津 美貴子 様",
                "令和08年03月分 提供実績チェックリスト 氏名 尾島 太郎 様",
            ],
        )
        _make_pdf(workspace["plan_dir"] / "塩津.pdf", ["運動器機能向上計画書 塩津"])
        _make_pdf(workspace["plan_dir"] / "尾島.pdf", ["運動器機能向上計画書 尾島"])
        _make_pdf(workspace["report_dir"] / "塩津.pdf", ["経過報告書 塩津 1", "塩津 2"])
        _make_pdf(workspace["report_dir"] / "尾島.pdf", ["経過報告書 尾島"])

        report = merge_facility(
            workspace["a_pdf"], workspace["facility_dir"], workspace["output_root"]
        )

        assert isinstance(report, FacilityMergeReport)
        assert report.facility_name == "きなり(メール)"
        # 2 利用者とも全ソース揃い
        entries_by_key = {e.user_key: e for e in report.success}
        assert set(entries_by_key.keys()) == {"塩津", "尾島"}
        assert entries_by_key["塩津"].sources_used == ("A", "B", "C")
        assert entries_by_key["尾島"].sources_used == ("A", "B", "C")

        # 出力ファイル存在 + ページ数
        shiotsu_out = workspace["output_root"] / "きなり(メール)" / "塩津.pdf"
        ojima_out = workspace["output_root"] / "きなり(メール)" / "尾島.pdf"
        assert shiotsu_out.exists()
        assert ojima_out.exists()
        # 塩津: A 1 + B 1 + C 2 = 4 ページ
        assert _page_count(shiotsu_out) == 4
        # 尾島: A 1 + B 1 + C 1 = 3 ページ
        assert _page_count(ojima_out) == 3

    def test_plan_missing_warn_but_merge_a_and_c(
        self, workspace: dict[str, Path]
    ) -> None:
        """B 欠損: A + C のみ結合、report.b_missing に記録。"""
        _make_pdf(workspace["a_pdf"], ["氏名 日浦 太一 様"])
        # B なし
        workspace["plan_dir"].mkdir(parents=True)
        _make_pdf(workspace["report_dir"] / "日浦.pdf", ["経過報告書 日浦"])

        report = merge_facility(
            workspace["a_pdf"], workspace["facility_dir"], workspace["output_root"]
        )

        assert "日浦" in report.b_missing
        entries = {e.user_key: e for e in report.success}
        assert entries["日浦"].sources_used == ("A", "C")
        out = workspace["output_root"] / "きなり(メール)" / "日浦.pdf"
        assert out.exists()
        assert _page_count(out) == 2  # A 1 + C 1

    def test_report_missing_warn_but_merge_a_and_b(
        self, workspace: dict[str, Path]
    ) -> None:
        """C 欠損: A + B のみ結合、report.c_missing に記録。"""
        _make_pdf(workspace["a_pdf"], ["氏名 藤野 花子 様"])
        _make_pdf(workspace["plan_dir"] / "藤野.pdf", ["運動器機能向上計画書 藤野"])
        workspace["report_dir"].mkdir(parents=True)

        report = merge_facility(
            workspace["a_pdf"], workspace["facility_dir"], workspace["output_root"]
        )

        assert "藤野" in report.c_missing
        entries = {e.user_key: e for e in report.success}
        assert entries["藤野"].sources_used == ("A", "B")
        out = workspace["output_root"] / "きなり(メール)" / "藤野.pdf"
        assert _page_count(out) == 2

    def test_a_only_no_bc_files(self, workspace: dict[str, Path]) -> None:
        """A にはあるが B/C 両方なし: A のみ出力。"""
        _make_pdf(workspace["a_pdf"], ["氏名 荒木 千春 様"])
        workspace["plan_dir"].mkdir(parents=True)
        workspace["report_dir"].mkdir(parents=True)

        report = merge_facility(
            workspace["a_pdf"], workspace["facility_dir"], workspace["output_root"]
        )

        assert "荒木" in report.a_only
        entries = {e.user_key: e for e in report.success}
        assert entries["荒木"].sources_used == ("A",)
        out = workspace["output_root"] / "きなり(メール)" / "荒木.pdf"
        assert _page_count(out) == 1

    def test_bc_only_without_a_match(self, workspace: dict[str, Path]) -> None:
        """B/C にはあるが A の抽出氏名とマッチしない: B + C のみ出力。"""
        # A は別の利用者のみ（荒木）、B/C には 塩津.pdf のみ
        _make_pdf(workspace["a_pdf"], ["氏名 荒木 千春 様"])
        _make_pdf(workspace["plan_dir"] / "塩津.pdf", ["計画書 塩津"])
        _make_pdf(workspace["report_dir"] / "塩津.pdf", ["経過 塩津"])

        report = merge_facility(
            workspace["a_pdf"], workspace["facility_dir"], workspace["output_root"]
        )

        # A のみ: 荒木 / B+C: 塩津
        keys = {e.user_key: e for e in report.success}
        assert "荒木" in keys
        assert keys["荒木"].sources_used == ("A",)
        assert "塩津" in keys
        assert keys["塩津"].sources_used == ("B", "C")
        assert "塩津" in report.a_missing

        # 両方出力されていること
        assert (workspace["output_root"] / "きなり(メール)" / "荒木.pdf").exists()
        assert (workspace["output_root"] / "きなり(メール)" / "塩津.pdf").exists()

    def test_extraction_failed_page_recorded(
        self, workspace: dict[str, Path]
    ) -> None:
        """A ページ内に氏名パターンが無い場合: extraction_failed_pages に記録、出力なし。"""
        # 氏名パターン不在
        _make_pdf(workspace["a_pdf"], ["このページは氏名情報を含みません"])
        workspace["plan_dir"].mkdir(parents=True)
        workspace["report_dir"].mkdir(parents=True)

        report = merge_facility(
            workspace["a_pdf"], workspace["facility_dir"], workspace["output_root"]
        )

        assert 0 in report.extraction_failed_pages
        assert report.success == ()

    def test_partial_name_match_fujino_with_brackets(
        self, workspace: dict[str, Path]
    ) -> None:
        """ファイル名ゆらぎ: 【藤野様】.pdf が A 抽出姓 '藤野' とマッチする。"""
        _make_pdf(workspace["a_pdf"], ["氏名 藤野 次郎 様"])
        _make_pdf(workspace["plan_dir"] / "【藤野様】.pdf", ["計画書 藤野"])
        workspace["report_dir"].mkdir(parents=True)

        report = merge_facility(
            workspace["a_pdf"], workspace["facility_dir"], workspace["output_root"]
        )

        entries = {e.user_key: e for e in report.success}
        assert "藤野" in entries
        assert entries["藤野"].sources_used == ("A", "B")

    def test_facility_dir_without_subfolders(self, tmp_path: Path) -> None:
        """B/C サブフォルダ両方なし: A のみ扱いで各ページを出力。"""
        facility_dir = tmp_path / "minimal"
        facility_dir.mkdir()
        a_pdf = tmp_path / "a.pdf"
        _make_pdf(a_pdf, ["氏名 田中 一郎 様"])
        output_root = tmp_path / "out"

        report = merge_facility(a_pdf, facility_dir, output_root)

        entries = {e.user_key: e for e in report.success}
        assert entries["田中"].sources_used == ("A",)
        assert (output_root / "minimal" / "田中.pdf").exists()

    def test_source_a_pdf_not_found(self, workspace: dict[str, Path]) -> None:
        """A.pdf が存在しない: FileNotFoundError。"""
        workspace["facility_dir"].mkdir(parents=True)
        with pytest.raises(FileNotFoundError):
            merge_facility(
                workspace["a_pdf"],
                workspace["facility_dir"],
                workspace["output_root"],
            )

    def test_facility_dir_not_exists(self, tmp_path: Path) -> None:
        """facility_dir が存在しない: FileNotFoundError。"""
        a = tmp_path / "a.pdf"
        _make_pdf(a, ["氏名 田中 一郎 様"])
        with pytest.raises(FileNotFoundError):
            merge_facility(a, tmp_path / "no_such_dir", tmp_path / "out")

    def test_same_surname_conflict_generates_suffix(
        self, workspace: dict[str, Path]
    ) -> None:
        """同姓 2 名は連番 suffix でユニーク化される（silent 上書き防止）。"""
        _make_pdf(
            workspace["a_pdf"],
            ["氏名 田中 太郎 様", "氏名 田中 花子 様"],
        )
        workspace["plan_dir"].mkdir(parents=True)
        workspace["report_dir"].mkdir(parents=True)

        report = merge_facility(
            workspace["a_pdf"], workspace["facility_dir"], workspace["output_root"]
        )

        user_keys = [e.user_key for e in report.success]
        assert "田中" in user_keys
        assert "田中_2" in user_keys
        assert "田中_2" in report.name_conflicts
        # 両方のファイルが別々に存在
        facility_out = workspace["output_root"] / "きなり(メール)"
        assert (facility_out / "田中.pdf").exists()
        assert (facility_out / "田中_2.pdf").exists()

    def test_phase2_resolves_bc_name_variation(
        self, workspace: dict[str, Path]
    ) -> None:
        """Phase 2: A にない利用者で B に『【藤野様】.pdf』、C に『藤野.pdf』のゆらぎも
        同一人物として結合される（2 出力にならない）。"""
        _make_pdf(workspace["a_pdf"], ["氏名 荒木 千春 様"])
        _make_pdf(workspace["plan_dir"] / "【藤野様】.pdf", ["計画書 藤野"])
        _make_pdf(workspace["report_dir"] / "藤野.pdf", ["経過 藤野"])

        report = merge_facility(
            workspace["a_pdf"], workspace["facility_dir"], workspace["output_root"]
        )

        # 藤野は 1 エントリのみ、B+C で結合
        fujino_entries = [e for e in report.success if "藤野" in e.user_key]
        assert len(fujino_entries) == 1
        assert fujino_entries[0].sources_used == ("B", "C")

    def test_a_only_not_double_counted_in_missing(
        self, workspace: dict[str, Path]
    ) -> None:
        """A のみ（B/C 両方なし）の利用者は b_missing/c_missing に重複計上されない。"""
        _make_pdf(workspace["a_pdf"], ["氏名 荒木 千春 様"])
        workspace["plan_dir"].mkdir(parents=True)
        workspace["report_dir"].mkdir(parents=True)

        report = merge_facility(
            workspace["a_pdf"], workspace["facility_dir"], workspace["output_root"]
        )

        assert "荒木" in report.a_only
        # 排他: a_only に入ったら b_missing / c_missing には入らない
        assert "荒木" not in report.b_missing
        assert "荒木" not in report.c_missing
