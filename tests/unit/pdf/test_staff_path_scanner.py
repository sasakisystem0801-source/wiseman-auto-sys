"""T2: scan_candidates / scan_fallback / build_folder_tree の挙動テスト。

5 担当者（OT 小林 / PT 宮下 / PT 小島 / PT 平瀬 / PT 木塚）の NAS 上の命名規則カオス
を tmp_path で再現し、suggest_patterns から正しく候補抽出できることを確認する。

UNC パスは macOS では使えないため tmp_path で代替。実機検証は T8 で実施。
"""

from __future__ import annotations

from pathlib import Path

from wiseman_hub.config import ReportStaffEntry
from wiseman_hub.pdf.staff_path_scanner import (
    build_folder_tree,
    scan_candidates,
    scan_fallback,
    western_to_reiwa,
)


def test_western_to_reiwa() -> None:
    assert western_to_reiwa(2019) == 1
    assert western_to_reiwa(2026) == 8


# ---------- 担当者ごとの fixture ----------


def _make_miyashita(base: Path) -> Path:
    """PT 宮下: リハ経過報告書\\令和{era}年\\リハ経過報告書（宮下）{month}月{空白N個}.xlsx"""
    root = base / "PT 宮下"
    (root / "リハ経過報告書" / "令和7年").mkdir(parents=True)
    (root / "リハ経過報告書" / "令和8年").mkdir(parents=True)
    # R7 = 末尾空白 1 個、R8 = 末尾空白 4 個
    (root / "リハ経過報告書" / "令和7年" / "リハ経過報告書（宮下）3月 .xlsx").write_text("")
    (root / "リハ経過報告書" / "令和8年" / "リハ経過報告書（宮下）3月    .xlsx").write_text("")
    # 別月
    (root / "リハ経過報告書" / "令和8年" / "リハ経過報告書（宮下）2月    .xlsx").write_text("")
    # 一時ファイル（除外されるべき）
    (root / "リハ経過報告書" / "令和8年" / "~$リハ経過報告書（宮下）3月.xlsx").write_text("")
    return root


def _make_kizuka(base: Path) -> Path:
    """PT 木塚: 経過報告書\\令和{era}年度 経過報告書\\経過報告書 木塚R{era}.{month}月 .xlsx
    + 別利用者「東浦」混在ファイルも置く（hard reject 確認用）。
    """
    root = base / "PT 木塚"
    (root / "経過報告書" / "令和8年度 経過報告書").mkdir(parents=True)
    (root / "経過報告書" / "令和7年度 経過報告書").mkdir(parents=True)
    (root / "経過報告書" / "令和8年度 経過報告書" / "経過報告書 木塚R8.3月 .xlsx").write_text("")
    (root / "経過報告書" / "令和7年度 経過報告書" / "経過報告書 木塚R7.3月 .xlsx").write_text("")
    # 東浦混在（担当者違いのファイル）
    (root / "経過報告書" / "令和7年度 経過報告書" / "経過報告書 東浦R7.3月.xlsx").write_text("")
    return root


def _make_kojima(base: Path) -> Path:
    """PT 小島: リハ経過報告書(新)\\経過報告書 令和{era}年{month}月(最新).xlsx
    + (旧) 系統 + (最新) なし候補も置く。
    """
    root = base / "PT 小島"
    (root / "リハ経過報告書(新)").mkdir(parents=True)
    (root / "リハ経過報告書(旧)" / "令和6年度").mkdir(parents=True)
    (root / "リハ経過報告書(新)" / "経過報告書 令和8年3月  .xlsx").write_text("")
    (root / "リハ経過報告書(新)" / "経過報告書 令和8年3月(最新).xlsx").write_text("")
    (root / "リハ経過報告書(新)" / "経過報告書 令和8年3月(最新)- .xlsx").write_text("")
    # (旧) 系統に同月の xlsx（hard reject 対象、suggest_patterns で (新) のみ走査）
    (root / "リハ経過報告書(旧)" / "令和6年度" / "経過報告書 令和8年3月.xlsx").write_text("")
    return root


def _make_hirase(base: Path) -> Path:
    """PT 平瀬: リハ経過報告書\\令和{era}年\\新経過報告書 {month}月{空白}.xlsx (担当者名なし)"""
    root = base / "PT 平瀬"
    (root / "リハ経過報告書" / "令和8年").mkdir(parents=True)
    (root / "リハ経過報告書" / "令和8年" / "新経過報告書 3月    .xlsx").write_text("")
    return root


def _make_kobayashi(base: Path) -> Path:
    """OT 小林: 経過報告書\\R{era}\\??? (xlsx 名は実機未確認、テストは仮名)"""
    root = base / "OT小林"
    (root / "経過報告書" / "R8").mkdir(parents=True)
    (root / "経過報告書" / "R8" / "経過報告書R8.3月.xlsx").write_text("")
    return root


# ---------- scan_candidates ----------


def test_scan_candidates_miyashita_picks_only_target_year(tmp_path: Path) -> None:
    """PT 宮下: 令和8年の 3 月分のみ候補化、令和7年や 2 月は除外。"""
    base = _make_miyashita(tmp_path)
    entry = ReportStaffEntry(
        base_dir=base,
        suggest_patterns=["リハ経過報告書/令和{era}年/リハ経過報告書*{month}月*.xlsx"],
    )
    cands = scan_candidates(entry, year=2026, month=3)
    assert len(cands) == 1
    assert cands[0].name == "リハ経過報告書（宮下）3月    .xlsx"


def test_scan_candidates_miyashita_no_match_for_other_year(tmp_path: Path) -> None:
    """テンプレで `令和{era}年` 固定なら R7 fixture は year=2025 でしかヒットしない。"""
    base = _make_miyashita(tmp_path)
    entry = ReportStaffEntry(
        base_dir=base,
        suggest_patterns=["リハ経過報告書/令和{era}年/リハ経過報告書*{month}月*.xlsx"],
    )
    cands = scan_candidates(entry, year=2025, month=3)
    assert len(cands) == 1
    assert cands[0].name == "リハ経過報告書（宮下）3月 .xlsx"


def test_scan_candidates_excludes_office_lock_file(tmp_path: Path) -> None:
    base = _make_miyashita(tmp_path)
    entry = ReportStaffEntry(
        base_dir=base,
        suggest_patterns=["リハ経過報告書/令和{era}年/*.xlsx"],
    )
    cands = scan_candidates(entry, year=2026, month=3)
    names = [p.name for p in cands]
    assert all(not n.startswith("~$") for n in names)


def test_scan_candidates_kizuka_includes_higashiura_for_review(
    tmp_path: Path,
) -> None:
    """PT 木塚: glob `*木塚*` で絞らず `*` のみ使うと東浦も candidate になる。
    候補に入った時点でレビュー UI で人間が選択する設計（hard rejectは T3 のスコアリング外）。
    """
    base = _make_kizuka(tmp_path)
    entry = ReportStaffEntry(
        base_dir=base,
        suggest_patterns=["経過報告書/令和{era}年度 経過報告書/*{month}月*.xlsx"],
    )
    cands = scan_candidates(entry, year=2025, month=3)
    names = [p.name for p in cands]
    # R7 年フォルダにある 木塚 + 東浦 の両方が候補に上がる
    assert "経過報告書 木塚R7.3月 .xlsx" in names
    assert "経過報告書 東浦R7.3月.xlsx" in names


def test_scan_candidates_kizuka_filtered_by_staff_token(tmp_path: Path) -> None:
    """suggest_patterns に `*木塚*` を含めれば東浦は弾ける。"""
    base = _make_kizuka(tmp_path)
    entry = ReportStaffEntry(
        base_dir=base,
        suggest_patterns=[
            "経過報告書/令和{era}年度 経過報告書/*木塚*{month}月*.xlsx",
        ],
    )
    cands = scan_candidates(entry, year=2025, month=3)
    names = [p.name for p in cands]
    assert names == ["経過報告書 木塚R7.3月 .xlsx"]


def test_scan_candidates_kojima_excludes_old_system(tmp_path: Path) -> None:
    """PT 小島: suggest_patterns で (新) フォルダ限定なら (旧) の同月 xlsx は混入しない。"""
    base = _make_kojima(tmp_path)
    entry = ReportStaffEntry(
        base_dir=base,
        suggest_patterns=[
            "リハ経過報告書(新)/経過報告書*令和{era}年{month}月*.xlsx",
        ],
    )
    cands = scan_candidates(entry, year=2026, month=3)
    names = [p.name for p in cands]
    # (新) 配下の 3 候補（無印 / (最新) / (最新)-）はすべて拾い、(旧) は混入しない
    assert len(cands) == 3
    assert all("(旧)" not in str(p) for p in cands)
    assert "経過報告書 令和8年3月  .xlsx" in names
    assert "経過報告書 令和8年3月(最新).xlsx" in names


def test_scan_candidates_hirase_no_staff_token_in_filename(tmp_path: Path) -> None:
    base = _make_hirase(tmp_path)
    entry = ReportStaffEntry(
        base_dir=base,
        suggest_patterns=["リハ経過報告書/令和{era}年/新経過報告書 {month}月*.xlsx"],
    )
    cands = scan_candidates(entry, year=2026, month=3)
    assert len(cands) == 1
    assert cands[0].name == "新経過報告書 3月    .xlsx"


def test_scan_candidates_kobayashi_R_prefix(tmp_path: Path) -> None:
    base = _make_kobayashi(tmp_path)
    entry = ReportStaffEntry(
        base_dir=base,
        suggest_patterns=["経過報告書/R{era}/*{month}月*.xlsx"],
    )
    cands = scan_candidates(entry, year=2026, month=3)
    assert len(cands) == 1


def test_scan_candidates_empty_patterns_returns_empty(tmp_path: Path) -> None:
    """suggest_patterns 空なら scan_fallback / template フォールバックは scan_candidates の責務外。"""
    base = _make_miyashita(tmp_path)
    entry = ReportStaffEntry(base_dir=base, suggest_patterns=[])
    assert scan_candidates(entry, year=2026, month=3) == []


def test_scan_candidates_no_base_dir(tmp_path: Path) -> None:
    entry = ReportStaffEntry(base_dir=Path(""), suggest_patterns=["x/y.xlsx"])
    assert scan_candidates(entry, year=2026, month=3) == []


def test_scan_candidates_dedup_across_patterns(tmp_path: Path) -> None:
    """複数 suggest_patterns が同一ファイルにマッチしても結果は dedup される。"""
    base = _make_miyashita(tmp_path)
    entry = ReportStaffEntry(
        base_dir=base,
        suggest_patterns=[
            "リハ経過報告書/令和{era}年/リハ経過報告書*{month}月*.xlsx",
            "リハ経過報告書/令和{era}年/*{month}月*.xlsx",  # より広い、同じファイルにヒット
        ],
    )
    cands = scan_candidates(entry, year=2026, month=3)
    assert len(cands) == 1


# ---------- scan_fallback ----------


def test_scan_fallback_collects_all_xlsx_within_depth(tmp_path: Path) -> None:
    base = _make_kizuka(tmp_path)
    cands = scan_fallback(base, max_depth=3)
    assert len(cands) == 3  # 木塚 R7/R8 + 東浦 R7
    assert all(p.suffix == ".xlsx" for p in cands)


def test_scan_fallback_excludes_office_lock(tmp_path: Path) -> None:
    base = _make_miyashita(tmp_path)
    cands = scan_fallback(base, max_depth=3)
    assert all(not p.name.startswith("~$") for p in cands)


def test_scan_fallback_respects_max_depth(tmp_path: Path) -> None:
    """max_depth=1 では深さ 2 の xlsx は拾えない。"""
    base = _make_miyashita(tmp_path)
    cands = scan_fallback(base, max_depth=1)
    # PT 宮下 fixture の xlsx は base/リハ経過報告書/令和X年/xx.xlsx (深さ 3)
    assert cands == []


def test_scan_fallback_missing_dir_returns_empty(tmp_path: Path) -> None:
    assert scan_fallback(tmp_path / "nonexistent") == []


# ---------- build_folder_tree ----------


def test_build_folder_tree_structure(tmp_path: Path) -> None:
    base = _make_miyashita(tmp_path)
    tree = build_folder_tree(base, max_depth=3)
    assert tree["name"] == "PT 宮下"
    assert tree["is_dir"] is True
    # 直下に "リハ経過報告書"
    sub_names = [c["name"] for c in tree["children"]]
    assert "リハ経過報告書" in sub_names


def test_build_folder_tree_excludes_non_xlsx_files(tmp_path: Path) -> None:
    base = tmp_path / "PT テスト"
    (base / "sub").mkdir(parents=True)
    (base / "sub" / "x.xlsx").write_text("")
    (base / "sub" / "x.docx").write_text("")
    (base / "sub" / "~$x.xlsx").write_text("")
    tree = build_folder_tree(base, max_depth=2)
    sub = next(c for c in tree["children"] if c["name"] == "sub")
    leaf_names = [c["name"] for c in sub["children"]]
    assert "x.xlsx" in leaf_names
    assert "x.docx" not in leaf_names
    assert "~$x.xlsx" not in leaf_names


def test_build_folder_tree_max_depth(tmp_path: Path) -> None:
    """max_depth=1 では孫以降を展開しない。"""
    base = _make_miyashita(tmp_path)
    tree = build_folder_tree(base, max_depth=1)
    sub = next(c for c in tree["children"] if c["name"] == "リハ経過報告書")
    # depth=1 では「リハ経過報告書」の下まで展開、その下（令和X年）は子なし
    grandchildren = sub["children"]
    for gc in grandchildren:
        # 令和X年 の中身は展開されない (children == [])
        assert gc["children"] == []
