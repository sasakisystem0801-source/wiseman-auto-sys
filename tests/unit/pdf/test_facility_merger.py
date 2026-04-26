"""facility_merger.py のテスト (新仕様: 事業所単位 1 ファイル ABCABC 連結)."""

from __future__ import annotations

from pathlib import Path

import fitz  # type: ignore[import-untyped]
import pytest

from wiseman_hub.pdf.facility_merger import (
    PLAN_DIR_NAME,
    REPORT_DIR_NAME,
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


class TestMergeFacilityNewSpec:
    """新仕様: 事業所単位 1 ファイル ABCABC 連結（ABC 全揃いのみ、A 出現順）。

    - 出力: `{output_root}/{facility_name}/{facility_name}.pdf` の **単一ファイル**
    - 連結対象: A + B + C 全て揃っている利用者のみ（A単独/A+B/A+C/B+C は除外）
    - 連結順序: A.pdf のページ出現順（業務上は五十音順想定）
    - 同姓重複 fail-safe は維持（該当者は ABC 全揃いでも除外）
    """

    def test_writes_single_facility_pdf_only(
        self, workspace: dict[str, Path]
    ) -> None:
        """出力 dir には `{facility_name}.pdf` 1 ファイルのみ生成され、
        旧仕様の `{user_key}.pdf` は作られない。"""
        _make_pdf(
            workspace["a_pdf"],
            ["氏名 塩津 美貴子 様", "氏名 尾島 太郎 様"],
        )
        _make_pdf(workspace["plan_dir"] / "塩津.pdf", ["計画書 塩津"])
        _make_pdf(workspace["plan_dir"] / "尾島.pdf", ["計画書 尾島"])
        _make_pdf(workspace["report_dir"] / "塩津.pdf", ["経過 塩津"])
        _make_pdf(workspace["report_dir"] / "尾島.pdf", ["経過 尾島"])

        merge_facility(
            workspace["a_pdf"],
            workspace["facility_dir"],
            workspace["output_root"],
        )

        facility_out = workspace["output_root"] / "きなり(メール)"
        out_files = sorted(p.name for p in facility_out.glob("*.pdf"))
        assert out_files == ["きなり(メール).pdf"], (
            f"Expected only facility pdf, got {out_files}"
        )

    def test_full_set_users_concatenated_in_a_order(
        self, workspace: dict[str, Path]
    ) -> None:
        """ABC 全揃いの利用者を A.pdf 出現順で `A1+B1+C1+A2+B2+C2+A3+B3+C3` 連結。

        合成タグ `[SRC:X][USER:Y]` で各ページのソース種別と利用者を内容レベル検証。
        """
        _make_pdf(
            workspace["a_pdf"],
            [
                "氏名 塩津 美貴子 様 [SRC:A][USER:shiotsu]",
                "氏名 尾島 太郎 様 [SRC:A][USER:ojima]",
                "氏名 藤野 花子 様 [SRC:A][USER:fujino]",
            ],
        )
        _make_pdf(
            workspace["plan_dir"] / "塩津.pdf",
            ["計画書 [SRC:B][USER:shiotsu]"],
        )
        _make_pdf(
            workspace["plan_dir"] / "尾島.pdf",
            ["計画書 [SRC:B][USER:ojima]"],
        )
        _make_pdf(
            workspace["plan_dir"] / "藤野.pdf",
            ["計画書 [SRC:B][USER:fujino]"],
        )
        _make_pdf(
            workspace["report_dir"] / "塩津.pdf",
            ["経過 [SRC:C][USER:shiotsu]"],
        )
        _make_pdf(
            workspace["report_dir"] / "尾島.pdf",
            ["経過 [SRC:C][USER:ojima]"],
        )
        _make_pdf(
            workspace["report_dir"] / "藤野.pdf",
            ["経過 [SRC:C][USER:fujino]"],
        )

        merge_facility(
            workspace["a_pdf"],
            workspace["facility_dir"],
            workspace["output_root"],
        )

        facility_pdf = (
            workspace["output_root"] / "きなり(メール)" / "きなり(メール).pdf"
        )
        assert facility_pdf.exists()
        assert _page_count(facility_pdf) == 9

        doc = fitz.open(facility_pdf)
        try:
            texts = [doc[i].get_text() for i in range(doc.page_count)]
        finally:
            doc.close()

        expected_order = [
            ("A", "shiotsu"), ("B", "shiotsu"), ("C", "shiotsu"),
            ("A", "ojima"), ("B", "ojima"), ("C", "ojima"),
            ("A", "fujino"), ("B", "fujino"), ("C", "fujino"),
        ]
        for page_idx, (src, user) in enumerate(expected_order):
            assert f"[SRC:{src}]" in texts[page_idx], (
                f"page {page_idx}: expected [SRC:{src}], got {texts[page_idx]!r}"
            )
            assert f"[USER:{user}]" in texts[page_idx], (
                f"page {page_idx}: expected [USER:{user}], got {texts[page_idx]!r}"
            )

    def test_partial_users_excluded_from_facility_file(
        self, workspace: dict[str, Path]
    ) -> None:
        """ABC 不揃い（A単独/A+B/A+C/B+C）は出力 PDF に含まれない（除外）。

        塩津のみ A+B+C 全揃い → 出力には塩津 3 ページのみ、他 4 名は完全除外。
        """
        _make_pdf(
            workspace["a_pdf"],
            [
                "氏名 塩津 美貴子 様 [USER:shiotsu]",
                "氏名 尾島 太郎 様 [USER:ojima]",
                "氏名 藤野 花子 様 [USER:fujino]",
                "氏名 荒木 千春 様 [USER:araki]",
            ],
        )
        # B: 塩津 + 尾島 + asao（A にない）
        _make_pdf(workspace["plan_dir"] / "塩津.pdf", ["計画書 [USER:shiotsu]"])
        _make_pdf(workspace["plan_dir"] / "尾島.pdf", ["計画書 [USER:ojima]"])
        _make_pdf(workspace["plan_dir"] / "asao.pdf", ["計画書 [USER:asao]"])
        # C: 塩津 + 藤野 + asao
        _make_pdf(workspace["report_dir"] / "塩津.pdf", ["経過 [USER:shiotsu]"])
        _make_pdf(workspace["report_dir"] / "藤野.pdf", ["経過 [USER:fujino]"])
        _make_pdf(workspace["report_dir"] / "asao.pdf", ["経過 [USER:asao]"])

        merge_facility(
            workspace["a_pdf"],
            workspace["facility_dir"],
            workspace["output_root"],
        )

        facility_pdf = (
            workspace["output_root"] / "きなり(メール)" / "きなり(メール).pdf"
        )
        assert facility_pdf.exists()
        # 塩津 (A+B+C) のみ = 3 ページ
        assert _page_count(facility_pdf) == 3, (
            f"Expected 3 pages (A+B+C 塩津 only), got {_page_count(facility_pdf)}"
        )

        doc = fitz.open(facility_pdf)
        try:
            all_text = "".join(
                doc[i].get_text() for i in range(doc.page_count)
            )
        finally:
            doc.close()

        assert "[USER:shiotsu]" in all_text
        for excluded in ("ojima", "fujino", "araki", "asao"):
            assert f"[USER:{excluded}]" not in all_text, (
                f"Excluded user {excluded} should not appear in facility pdf"
            )

    def test_excluded_users_recorded_in_report_categories(
        self, workspace: dict[str, Path]
    ) -> None:
        """除外利用者は report の各カテゴリに記録（既存フィールド名維持）。

        - 塩津: A+B+C → success に含まれる
        - 荒木: A のみ → a_only
        - 尾島: A+B（C 欠損）→ c_missing
        - 藤野: A+C（B 欠損）→ b_missing
        - asao: B+C（A なし）→ a_missing
        """
        _make_pdf(
            workspace["a_pdf"],
            [
                "氏名 塩津 美貴子 様",
                "氏名 尾島 太郎 様",
                "氏名 藤野 花子 様",
                "氏名 荒木 千春 様",
            ],
        )
        _make_pdf(workspace["plan_dir"] / "塩津.pdf", ["計画書"])
        _make_pdf(workspace["plan_dir"] / "尾島.pdf", ["計画書"])
        _make_pdf(workspace["plan_dir"] / "asao.pdf", ["計画書"])
        _make_pdf(workspace["report_dir"] / "塩津.pdf", ["経過"])
        _make_pdf(workspace["report_dir"] / "藤野.pdf", ["経過"])
        _make_pdf(workspace["report_dir"] / "asao.pdf", ["経過"])

        report = merge_facility(
            workspace["a_pdf"],
            workspace["facility_dir"],
            workspace["output_root"],
        )

        merged_keys = {e.user_key for e in report.success}
        assert merged_keys == {"塩津"}, (
            f"Expected only 塩津 merged, got {merged_keys}"
        )
        assert "荒木" in report.a_only
        assert "尾島" in report.c_missing
        assert "藤野" in report.b_missing
        assert "asao" in report.a_missing

    def test_no_full_set_produces_no_output(
        self, workspace: dict[str, Path]
    ) -> None:
        """ABC 全揃い 0 名 → 出力ファイル作られない、success 空。"""
        _make_pdf(workspace["a_pdf"], ["氏名 荒木 千春 様"])
        workspace["plan_dir"].mkdir(parents=True)
        workspace["report_dir"].mkdir(parents=True)

        report = merge_facility(
            workspace["a_pdf"],
            workspace["facility_dir"],
            workspace["output_root"],
        )

        facility_pdf = (
            workspace["output_root"] / "きなり(メール)" / "きなり(メール).pdf"
        )
        assert not facility_pdf.exists(), (
            "Facility pdf should not be created when no full ABC users"
        )
        assert report.success == ()
        assert "荒木" in report.a_only

    def test_ambiguous_surname_excluded_even_with_full_set(
        self, workspace: dict[str, Path]
    ) -> None:
        """同姓重複 fail-safe 維持: 該当姓は ABC 全揃いに見えても除外、
        ambiguous_bc_skipped に記録、出力 PDF には含まれない。"""
        _make_pdf(
            workspace["a_pdf"],
            [
                "氏名 田中 太郎 様",
                "氏名 田中 花子 様",
                "氏名 塩津 美貴子 様",
            ],
        )
        _make_pdf(workspace["plan_dir"] / "田中.pdf", ["計画書 田中"])
        _make_pdf(workspace["plan_dir"] / "塩津.pdf", ["計画書 塩津"])
        _make_pdf(workspace["report_dir"] / "田中.pdf", ["経過 田中"])
        _make_pdf(workspace["report_dir"] / "塩津.pdf", ["経過 塩津"])

        report = merge_facility(
            workspace["a_pdf"],
            workspace["facility_dir"],
            workspace["output_root"],
        )

        merged_keys = {e.user_key for e in report.success}
        assert "塩津" in merged_keys
        assert all("田中" not in k for k in merged_keys)
        assert any("田中" in k for k in report.ambiguous_bc_skipped)

        facility_pdf = (
            workspace["output_root"] / "きなり(メール)" / "きなり(メール).pdf"
        )
        # 塩津 A+B+C = 3 ページのみ（田中は除外）
        assert _page_count(facility_pdf) == 3

    def test_success_entries_share_facility_output_path(
        self, workspace: dict[str, Path]
    ) -> None:
        """全 success entry の output_path は事業所単位ファイル `{facility_name}.pdf`
        を指し、sources_used は ("A", "B", "C") で統一される（API 契約 / AC-5）。"""
        _make_pdf(
            workspace["a_pdf"],
            ["氏名 塩津 美貴子 様", "氏名 尾島 太郎 様"],
        )
        _make_pdf(workspace["plan_dir"] / "塩津.pdf", ["計画書 塩津"])
        _make_pdf(workspace["plan_dir"] / "尾島.pdf", ["計画書 尾島"])
        _make_pdf(workspace["report_dir"] / "塩津.pdf", ["経過 塩津"])
        _make_pdf(workspace["report_dir"] / "尾島.pdf", ["経過 尾島"])

        report = merge_facility(
            workspace["a_pdf"],
            workspace["facility_dir"],
            workspace["output_root"],
        )

        expected_path = (
            workspace["output_root"] / "きなり(メール)" / "きなり(メール).pdf"
        )
        assert len(report.success) == 2
        for entry in report.success:
            # 全 entry が同じ事業所単位ファイルを指す（旧仕様のような利用者別パスではない）
            assert entry.output_path == expected_path, (
                f"Entry {entry.user_key} output_path={entry.output_path} "
                f"!= expected {expected_path}"
            )
            assert entry.sources_used == ("A", "B", "C")

    def test_facility_pdf_filename_matches_facility_dir_name(
        self, workspace: dict[str, Path]
    ) -> None:
        """出力ファイル名 = facility_dir 名そのまま (`{facility_name}.pdf`)。"""
        _make_pdf(workspace["a_pdf"], ["氏名 塩津 美貴子 様"])
        _make_pdf(workspace["plan_dir"] / "塩津.pdf", ["計画書"])
        _make_pdf(workspace["report_dir"] / "塩津.pdf", ["経過"])

        report = merge_facility(
            workspace["a_pdf"],
            workspace["facility_dir"],
            workspace["output_root"],
        )

        facility_name = workspace["facility_dir"].name  # "きなり(メール)"
        expected = (
            workspace["output_root"] / facility_name / f"{facility_name}.pdf"
        )
        assert expected.exists()
        assert report.facility_name == facility_name


class TestMergeFacilityRobustness:
    """異常系・準正常系・PII 防御。"""

    def test_extraction_failed_page_recorded(
        self, workspace: dict[str, Path]
    ) -> None:
        """A ページ内に氏名パターンが無い場合: extraction_failed_pages に記録、出力なし。"""
        _make_pdf(workspace["a_pdf"], ["このページは氏名情報を含みません"])
        workspace["plan_dir"].mkdir(parents=True)
        workspace["report_dir"].mkdir(parents=True)

        report = merge_facility(
            workspace["a_pdf"],
            workspace["facility_dir"],
            workspace["output_root"],
        )

        assert 0 in report.extraction_failed_pages
        assert report.success == ()
        facility_pdf = (
            workspace["output_root"] / "きなり(メール)" / "きなり(メール).pdf"
        )
        assert not facility_pdf.exists()

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

    def test_partial_name_match_brackets_full_set(
        self, workspace: dict[str, Path]
    ) -> None:
        """ファイル名ゆらぎ吸収: `【藤野様】.pdf` を A 抽出姓「藤野」とマッチ。
        ABC 全揃いなら出力 PDF に含まれる。"""
        _make_pdf(workspace["a_pdf"], ["氏名 藤野 次郎 様"])
        _make_pdf(workspace["plan_dir"] / "【藤野様】.pdf", ["計画書 藤野"])
        _make_pdf(workspace["report_dir"] / "藤野.pdf", ["経過 藤野"])

        report = merge_facility(
            workspace["a_pdf"],
            workspace["facility_dir"],
            workspace["output_root"],
        )

        merged_keys = {e.user_key for e in report.success}
        assert "藤野" in merged_keys
        facility_pdf = (
            workspace["output_root"] / "きなり(メール)" / "きなり(メール).pdf"
        )
        assert _page_count(facility_pdf) == 3

    def test_facility_dir_without_subfolders(self, tmp_path: Path) -> None:
        """B/C サブフォルダ両方なし: 全利用者除外、出力ファイル無し。"""
        facility_dir = tmp_path / "minimal"
        facility_dir.mkdir()
        a_pdf = tmp_path / "a.pdf"
        _make_pdf(a_pdf, ["氏名 田中 一郎 様"])
        output_root = tmp_path / "out"

        report = merge_facility(a_pdf, facility_dir, output_root)

        assert "田中" in report.a_only
        assert report.success == ()
        facility_pdf = output_root / "minimal" / "minimal.pdf"
        assert not facility_pdf.exists()

    def test_pii_not_in_categorized_lists(
        self, workspace: dict[str, Path]
    ) -> None:
        """除外カテゴリリストには user_key（姓）のみ、full_name の名部分は含まれない。"""
        _make_pdf(workspace["a_pdf"], ["氏名 荒木 千春 様"])
        workspace["plan_dir"].mkdir(parents=True)
        workspace["report_dir"].mkdir(parents=True)

        report = merge_facility(
            workspace["a_pdf"],
            workspace["facility_dir"],
            workspace["output_root"],
        )

        for field_name in (
            "a_only",
            "a_missing",
            "b_missing",
            "c_missing",
            "name_conflicts",
            "ambiguous_bc_skipped",
        ):
            values = getattr(report, field_name)
            for v in values:
                assert "千春" not in v, (
                    f"{field_name} contains full name fragment: {v}"
                )

    def test_excluded_categories_are_mutually_exclusive(
        self, workspace: dict[str, Path]
    ) -> None:
        """A 単独 (a_only) の利用者は b_missing / c_missing に重複計上されない。"""
        _make_pdf(workspace["a_pdf"], ["氏名 荒木 千春 様"])
        workspace["plan_dir"].mkdir(parents=True)
        workspace["report_dir"].mkdir(parents=True)

        report = merge_facility(
            workspace["a_pdf"],
            workspace["facility_dir"],
            workspace["output_root"],
        )

        assert "荒木" in report.a_only
        assert "荒木" not in report.b_missing
        assert "荒木" not in report.c_missing
        assert "荒木" not in report.a_missing

    def test_bc_dirs_missing_recorded_when_subfolders_absent(
        self, tmp_path: Path
    ) -> None:
        """B/C サブフォルダ自体が不在の場合、bc_dirs_missing に記録される
        （NW 一時断・タイポ等で全利用者が silent 除外になる重大警告ケース）。"""
        facility_dir = tmp_path / "facility_no_subfolders"
        facility_dir.mkdir()
        a_pdf = tmp_path / "a.pdf"
        _make_pdf(a_pdf, ["氏名 田中 一郎 様"])
        output_root = tmp_path / "out"

        report = merge_facility(a_pdf, facility_dir, output_root)

        assert PLAN_DIR_NAME in report.bc_dirs_missing
        assert REPORT_DIR_NAME in report.bc_dirs_missing
        # 全利用者除外
        assert "田中" in report.a_only
        assert report.success == ()

    def test_save_atomically_failure_keeps_success_empty(
        self, workspace: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`_save_atomically` 失敗時、success リストには **誰も登録されない**
        （旧構造の「書込前 append」による silent failure 誤報告を防ぐ）。"""
        _make_pdf(workspace["a_pdf"], ["氏名 塩津 美貴子 様"])
        _make_pdf(workspace["plan_dir"] / "塩津.pdf", ["計画書"])
        _make_pdf(workspace["report_dir"] / "塩津.pdf", ["経過"])

        # _save_atomically を例外送出にモンキーパッチ
        from wiseman_hub.pdf import facility_merger as fm
        from wiseman_hub.pdf.merger import PdfMergeError

        def boom(*_args: object, **_kwargs: object) -> None:
            raise PdfMergeError("simulated write failure")

        monkeypatch.setattr(fm, "_save_atomically", boom)

        with pytest.raises(PdfMergeError):
            merge_facility(
                workspace["a_pdf"],
                workspace["facility_dir"],
                workspace["output_root"],
            )

    def test_single_char_stem_does_not_misuse_match(
        self, workspace: dict[str, Path]
    ) -> None:
        """1 文字 stem（例: `田.pdf`）は誤マッチを起こさず、田中は a_only に分類される。"""
        _make_pdf(workspace["a_pdf"], ["氏名 田中 太郎 様"])
        _make_pdf(workspace["plan_dir"] / "田.pdf", ["計画書 田（1文字）"])
        workspace["report_dir"].mkdir(parents=True)

        report = merge_facility(
            workspace["a_pdf"],
            workspace["facility_dir"],
            workspace["output_root"],
        )

        # 田中 は B マッチ失敗 + C なし → a_only
        assert "田中" in report.a_only
        # 田.pdf は A にマッチしない → a_missing
        assert "田" in report.a_missing
        # 出力ファイル無し
        facility_pdf = (
            workspace["output_root"] / "きなり(メール)" / "きなり(メール).pdf"
        )
        assert not facility_pdf.exists()
