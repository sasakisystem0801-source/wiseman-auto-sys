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
        """同姓 2 名は連番 suffix でユニーク化される（silent 上書き防止）。
        B/C ファイルが無いケースなので ambiguous_bc_skipped には入らない（A のみ）。"""
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

    def test_ambiguous_surname_fails_safe_on_bc_match(
        self, workspace: dict[str, Path]
    ) -> None:
        """同姓重複 fail-safe: A に同姓 2 名 + B/C 1 式 → 誤添付を防ぐため
        両者の B/C 添付を見送り A のみ出力。ambiguous_bc_skipped に記録。

        Codex セカンドオピニオン HIGH 指摘への対応（同じ B/C が 2 人に混入するのを
        構造的に防ぐ）。"""
        _make_pdf(
            workspace["a_pdf"],
            ["氏名 田中 太郎 様", "氏名 田中 花子 様"],
        )
        _make_pdf(workspace["plan_dir"] / "田中.pdf", ["計画書 田中"])
        _make_pdf(workspace["report_dir"] / "田中.pdf", ["経過 田中"])

        report = merge_facility(
            workspace["a_pdf"], workspace["facility_dir"], workspace["output_root"]
        )

        # 両エントリとも A のみ、B/C は添付されない
        entries = {e.user_key: e for e in report.success}
        assert entries["田中"].sources_used == ("A",)
        assert entries["田中_2"].sources_used == ("A",)
        assert "田中" in report.ambiguous_bc_skipped
        assert "田中_2" in report.ambiguous_bc_skipped
        # ambiguous_bc_skipped は独立カテゴリ: a_only / b_missing / c_missing には入らない
        assert "田中" not in report.a_only
        assert "田中" not in report.b_missing
        assert "田中" not in report.c_missing
        # 主眼は Phase 1 で両者の B/C 添付が回避されていること
        # （Phase 2 で 田中 が残余として処理されるかは実装依存）
        assert all(
            e.sources_used == ("A",)
            for e in (entries["田中"], entries["田中_2"])
        )

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

    def test_single_char_stem_does_not_misuse_match(
        self, workspace: dict[str, Path]
    ) -> None:
        """1 文字 stem（例: `田.pdf`）は「姓に含まれる」ルールでの誤マッチを起こさない。
        `田.pdf` が B にあっても、A 抽出姓「田中」に対して誤マッチしてはいけない。
        完全一致および「stem が姓を含む」ルールの方は許可（`田` が `田中` を含むことは
        真ではないため、これは元々発動しない）。"""
        _make_pdf(workspace["a_pdf"], ["氏名 田中 太郎 様"])
        _make_pdf(workspace["plan_dir"] / "田.pdf", ["計画書 田（1文字）"])
        workspace["report_dir"].mkdir(parents=True)

        report = merge_facility(
            workspace["a_pdf"], workspace["facility_dir"], workspace["output_root"]
        )

        # 田中 エントリは A のみ + B マッチせず（1 文字 stem 除外）
        tanaka = next(e for e in report.success if e.user_key == "田中")
        assert tanaka.sources_used == ("A",)
        assert "田中" in report.a_only  # B/C 両方無し扱い
        # 田.pdf は Phase 2 で残余として B のみエントリ化される
        ta_entry = [e for e in report.success if e.user_key == "田"]
        assert len(ta_entry) == 1
        assert ta_entry[0].sources_used == ("B",)

    def test_three_same_surname_sequential_suffixes(
        self, workspace: dict[str, Path]
    ) -> None:
        """同姓 3 名以上: `田中` / `田中_2` / `田中_3` と連番継続。"""
        _make_pdf(
            workspace["a_pdf"],
            [
                "氏名 田中 太郎 様",
                "氏名 田中 花子 様",
                "氏名 田中 次郎 様",
            ],
        )
        workspace["plan_dir"].mkdir(parents=True)
        workspace["report_dir"].mkdir(parents=True)

        report = merge_facility(
            workspace["a_pdf"], workspace["facility_dir"], workspace["output_root"]
        )

        keys = {e.user_key for e in report.success}
        assert keys == {"田中", "田中_2", "田中_3"}
        assert "田中_2" in report.name_conflicts
        assert "田中_3" in report.name_conflicts
        out = workspace["output_root"] / "きなり(メール)"
        assert (out / "田中.pdf").exists()
        assert (out / "田中_2.pdf").exists()
        assert (out / "田中_3.pdf").exists()

    def test_phase2_inverted_c_to_b_name_variation(
        self, workspace: dict[str, Path]
    ) -> None:
        """Phase 2 逆対称: B 側が姓のみ、C 側に【姓様】形式でも同一エントリに統合される。
        Phase 2 は B 主導でマッチを試みるが、「姓が stem を含む」ルール (len>=2) により
        B の `藤野` は C の `【藤野様】` にマッチする。"""
        _make_pdf(workspace["a_pdf"], ["氏名 荒木 千春 様"])
        _make_pdf(workspace["plan_dir"] / "藤野.pdf", ["計画書 藤野"])
        _make_pdf(workspace["report_dir"] / "【藤野様】.pdf", ["経過 藤野"])

        report = merge_facility(
            workspace["a_pdf"], workspace["facility_dir"], workspace["output_root"]
        )

        # 藤野エントリが 1 つだけ、B+C 結合されている
        fujino_entries = [e for e in report.success if "藤野" in e.user_key]
        assert len(fujino_entries) == 1
        assert fujino_entries[0].sources_used == ("B", "C")

    def test_pii_not_in_missing_lists(self, workspace: dict[str, Path]) -> None:
        """欠損リスト（a_only/a_missing/b_missing/c_missing/name_conflicts）には
        user_key（姓 or stem）のみが含まれ、full_name（フルネーム）は含まれない。"""
        _make_pdf(workspace["a_pdf"], ["氏名 荒木 千春 様"])
        workspace["plan_dir"].mkdir(parents=True)
        workspace["report_dir"].mkdir(parents=True)

        report = merge_facility(
            workspace["a_pdf"], workspace["facility_dir"], workspace["output_root"]
        )

        for field_name in (
            "a_only",
            "a_missing",
            "b_missing",
            "c_missing",
            "name_conflicts",
        ):
            values = getattr(report, field_name)
            for v in values:
                # full_name (荒木 千春 / 荒木 千春様) の名部分を含まない
                assert "千春" not in v, (
                    f"{field_name} contains full name fragment: {v}"
                )

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

    def test_multi_user_ordered_merge_verifies_page_content(
        self, workspace: dict[str, Path]
    ) -> None:
        """複数利用者の A を分割し、結合可能な B/C のみ **順番通り (A→B→C)** で
        再結合することを、出力 PDF の各ページ **内容レベル** まで検証する。

        シナリオ:
          塩津: A + B + C → 3 ページ、順序 A→B→C
          尾島: A + B + C → 3 ページ、順序 A→B→C
          藤野: A + B のみ → 2 ページ、順序 A→B（C 欠損）
          荒木: A + C のみ → 2 ページ、順序 A→C（B 欠損）
          日浦: A のみ → 1 ページ（B/C 両方欠損）

        各ページに `[SRC:A|B|C]` と利用者ごとに一意な姓タグを仕込み、
        他利用者の資料が混入していないことも同時に確認する。
        """
        # A.pdf: 5 ページ 5 利用者、氏名パターン + ソース/姓タグ
        _make_pdf(
            workspace["a_pdf"],
            [
                "氏名 塩津 美貴子 様 [SRC:A][USER:shiotsu]",
                "氏名 尾島 太郎 様 [SRC:A][USER:ojima]",
                "氏名 藤野 花子 様 [SRC:A][USER:fujino]",
                "氏名 荒木 千春 様 [SRC:A][USER:araki]",
                "氏名 日浦 太一 様 [SRC:A][USER:hiura]",
            ],
        )
        # B (運動機能向上計画書): 塩津 / 尾島 / 藤野 のみ（荒木・日浦は B なし）
        _make_pdf(
            workspace["plan_dir"] / "塩津.pdf",
            ["計画書 塩津 [SRC:B][USER:shiotsu]"],
        )
        _make_pdf(
            workspace["plan_dir"] / "尾島.pdf",
            ["計画書 尾島 [SRC:B][USER:ojima]"],
        )
        _make_pdf(
            workspace["plan_dir"] / "藤野.pdf",
            ["計画書 藤野 [SRC:B][USER:fujino]"],
        )
        # C (経過報告書): 塩津 / 尾島 / 荒木 のみ（藤野・日浦は C なし）
        _make_pdf(
            workspace["report_dir"] / "塩津.pdf",
            ["経過 塩津 [SRC:C][USER:shiotsu]"],
        )
        _make_pdf(
            workspace["report_dir"] / "尾島.pdf",
            ["経過 尾島 [SRC:C][USER:ojima]"],
        )
        _make_pdf(
            workspace["report_dir"] / "荒木.pdf",
            ["経過 荒木 [SRC:C][USER:araki]"],
        )

        report = merge_facility(
            workspace["a_pdf"], workspace["facility_dir"], workspace["output_root"]
        )

        # ---- レポートレベルの検証 ----
        entries = {e.user_key: e for e in report.success}
        assert set(entries.keys()) == {"塩津", "尾島", "藤野", "荒木", "日浦"}
        assert entries["塩津"].sources_used == ("A", "B", "C")
        assert entries["尾島"].sources_used == ("A", "B", "C")
        assert entries["藤野"].sources_used == ("A", "B")
        assert entries["荒木"].sources_used == ("A", "C")
        assert entries["日浦"].sources_used == ("A",)

        # 欠損カテゴリの排他性
        assert "藤野" in report.c_missing
        assert "荒木" in report.b_missing
        assert "日浦" in report.a_only
        assert "日浦" not in report.b_missing
        assert "日浦" not in report.c_missing
        # A は全員マッチしているので a_missing は空
        assert report.a_missing == ()
        # 氏名抽出は全ページ成功
        assert report.extraction_failed_pages == ()

        facility_out = workspace["output_root"] / "きなり(メール)"

        # ---- 出力 PDF の内容レベル検証（ページ順序 + 混入なし） ----
        def _page_texts(path: Path) -> list[str]:
            doc = fitz.open(path)
            try:
                return [doc[i].get_text() for i in range(doc.page_count)]
            finally:
                doc.close()

        expected = {
            "塩津": [("A", "shiotsu"), ("B", "shiotsu"), ("C", "shiotsu")],
            "尾島": [("A", "ojima"), ("B", "ojima"), ("C", "ojima")],
            "藤野": [("A", "fujino"), ("B", "fujino")],
            "荒木": [("A", "araki"), ("C", "araki")],
            "日浦": [("A", "hiura")],
        }
        other_users = {
            "塩津": ["ojima", "fujino", "araki", "hiura"],
            "尾島": ["shiotsu", "fujino", "araki", "hiura"],
            "藤野": ["shiotsu", "ojima", "araki", "hiura"],
            "荒木": ["shiotsu", "ojima", "fujino", "hiura"],
            "日浦": ["shiotsu", "ojima", "fujino", "araki"],
        }
        for user_key, per_page in expected.items():
            out_path = facility_out / f"{user_key}.pdf"
            assert out_path.exists(), f"{user_key} output missing"
            texts = _page_texts(out_path)
            assert len(texts) == len(per_page), (
                f"{user_key}: page count mismatch "
                f"(expected {len(per_page)}, got {len(texts)})"
            )
            for page_idx, (src, user_tag) in enumerate(per_page):
                page_text = texts[page_idx]
                # A→B→C の **順序** 保証
                assert f"[SRC:{src}]" in page_text, (
                    f"{user_key} page {page_idx}: "
                    f"expected [SRC:{src}], got text={page_text!r}"
                )
                # 正しい利用者の資料
                assert f"[USER:{user_tag}]" in page_text, (
                    f"{user_key} page {page_idx}: "
                    f"expected [USER:{user_tag}], got text={page_text!r}"
                )
                # 他利用者の資料混入なし
                for other in other_users[user_key]:
                    assert f"[USER:{other}]" not in page_text, (
                        f"{user_key} page {page_idx}: "
                        f"other user {other} leaked, text={page_text!r}"
                    )
