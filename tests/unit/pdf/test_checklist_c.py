"""T1: CPlacementStatus / CPlacementResult dataclass 拡張テスト。
T3: resolve_xlsx (cache + scanner + 後方互換) + plan_c_placement 統合テスト。
"""

from __future__ import annotations

from pathlib import Path

from wiseman_hub.cloud.sheets import ChecklistRow
from wiseman_hub.config import ChecklistConfig, ReportStaffEntry
from wiseman_hub.pdf.checklist_c import (
    CPlacementResult,
    CPlacementStatus,
    cache_key,
    plan_c_placement,
    resolve_xlsx,
)


def _row(name: str = "テスト 太郎", staff: str = "宮下", facility: str = "事業所A") -> ChecklistRow:
    return ChecklistRow(name=name, monitoring_raw=None, staff=staff, facility=facility)


def test_status_enum_includes_needs_review() -> None:
    assert CPlacementStatus.NEEDS_REVIEW.value == "needs_review"
    # 既存ステータスは保たれている
    assert CPlacementStatus.PENDING.value == "pending"
    assert CPlacementStatus.SUCCESS.value == "success"
    assert CPlacementStatus.SKIPPED_NO_XLSX.value == "skipped_no_xlsx"


def test_result_default_fields_include_new_lists() -> None:
    """新規追加した xlsx_candidates / rejected_candidates / folder_tree がデフォルト初期化される。"""
    result = CPlacementResult(row=_row())
    assert result.xlsx_candidates == []
    assert result.rejected_candidates == {}
    assert result.folder_tree is None
    # 既存フィールドも維持
    assert result.sheet_candidates == []
    assert result.message == ""


def test_result_can_record_candidates_and_rejections() -> None:
    cand1 = Path("/x/a.xlsx")
    cand2 = Path("/x/b.xlsx")
    rejected = Path("/x/east_other.xlsx")
    result = CPlacementResult(
        row=_row(staff="木塚"),
        status=CPlacementStatus.NEEDS_REVIEW,
        xlsx_candidates=[cand1, cand2],
        rejected_candidates={rejected: "staff_token_mismatch"},
        message="複数候補",
    )
    assert result.status == CPlacementStatus.NEEDS_REVIEW
    assert result.xlsx_candidates == [cand1, cand2]
    assert result.rejected_candidates[rejected] == "staff_token_mismatch"


def test_result_can_record_folder_tree() -> None:
    """候補ゼロ時にレビュー UI へ渡すフォルダツリーが保持される。"""
    tree = {
        "name": "PT 宮下",
        "path": "\\\\Tera-station\\share\\PT 宮下",
        "is_dir": True,
        "children": [
            {
                "name": "リハ経過報告書",
                "path": "\\\\Tera-station\\share\\PT 宮下\\リハ経過報告書",
                "is_dir": True,
                "children": [],
            },
        ],
    }
    result = CPlacementResult(
        row=_row(),
        status=CPlacementStatus.NEEDS_REVIEW,
        folder_tree=tree,
        message="候補なし、フォルダから選択してください",
    )
    assert result.folder_tree is not None
    assert result.folder_tree["name"] == "PT 宮下"
    assert result.folder_tree["children"][0]["name"] == "リハ経過報告書"


# ---------- T3: resolve_xlsx ----------


def _entry_with_xlsx(tmp_path: Path) -> tuple[ReportStaffEntry, Path]:
    """テスト用 PT 宮下 fixture を作って ReportStaffEntry を返す。"""
    base = tmp_path / "PT 宮下"
    (base / "リハ経過報告書" / "令和8年").mkdir(parents=True)
    xlsx = base / "リハ経過報告書" / "令和8年" / "リハ経過報告書（宮下）3月    .xlsx"
    xlsx.write_text("")
    entry = ReportStaffEntry(
        base_dir=base,
        suggest_patterns=["リハ経過報告書/令和{era}年/リハ経過報告書*{month}月*.xlsx"],
    )
    return entry, xlsx


def test_cache_key_format() -> None:
    assert cache_key("宮下", 2026, 3) == "宮下:2026:3"


def test_resolve_xlsx_cache_hit_returns_pending(tmp_path: Path) -> None:
    entry, xlsx = _entry_with_xlsx(tmp_path)
    cache = {"宮下:2026:3": str(xlsx)}
    result = resolve_xlsx("宮下", entry, 2026, 3, cache)
    assert result.status == CPlacementStatus.PENDING
    assert result.xlsx_path == xlsx


def test_resolve_xlsx_cache_stale_falls_through(tmp_path: Path) -> None:
    entry, _ = _entry_with_xlsx(tmp_path)
    cache = {"宮下:2026:3": str(tmp_path / "missing" / "stale.xlsx")}
    result = resolve_xlsx("宮下", entry, 2026, 3, cache)
    # cache stale で fall through、suggest_patterns で候補発見
    assert result.status == CPlacementStatus.NEEDS_REVIEW
    assert len(result.candidates) == 1


def test_resolve_xlsx_candidates_returns_needs_review(tmp_path: Path) -> None:
    entry, xlsx = _entry_with_xlsx(tmp_path)
    cache: dict[str, str] = {}
    result = resolve_xlsx("宮下", entry, 2026, 3, cache)
    # 候補単独でも自動確定しない（NEEDS_REVIEW）
    assert result.status == CPlacementStatus.NEEDS_REVIEW
    assert result.candidates == [xlsx]


def test_resolve_xlsx_legacy_template_fallback(tmp_path: Path) -> None:
    """suggest_patterns 空 + 旧 *_template が完全 path を生成する場合は PENDING。"""
    base = tmp_path / "PT 宮下"
    (base / "リハ経過報告書" / "令和8年").mkdir(parents=True)
    xlsx = base / "リハ経過報告書" / "令和8年" / "report.xlsx"
    xlsx.write_text("")
    entry = ReportStaffEntry(
        base_dir=base,
        suggest_patterns=[],
        year_subfolder_template="リハ経過報告書/令和{era}年",
        file_template="report.xlsx",
    )
    cache: dict[str, str] = {}
    result = resolve_xlsx("宮下", entry, 2026, 3, cache)
    assert result.status == CPlacementStatus.PENDING
    assert result.xlsx_path == xlsx


def test_resolve_xlsx_no_candidates_returns_folder_tree(tmp_path: Path) -> None:
    base = tmp_path / "PT 宮下"
    (base / "リハ経過報告書").mkdir(parents=True)
    # xlsx 不在
    entry = ReportStaffEntry(
        base_dir=base,
        suggest_patterns=["リハ経過報告書/令和{era}年/*.xlsx"],
    )
    result = resolve_xlsx("宮下", entry, 2026, 3, cache={})
    assert result.status == CPlacementStatus.NEEDS_REVIEW
    assert result.folder_tree is not None
    assert result.folder_tree["name"] == "PT 宮下"


def test_resolve_xlsx_missing_base_dir_returns_skipped(tmp_path: Path) -> None:
    entry = ReportStaffEntry(
        base_dir=tmp_path / "nowhere",
        suggest_patterns=["x/y.xlsx"],
    )
    result = resolve_xlsx("宮下", entry, 2026, 3, cache={})
    assert result.status == CPlacementStatus.SKIPPED_NO_XLSX


def test_resolve_xlsx_empty_base_dir_returns_skipped() -> None:
    entry = ReportStaffEntry(base_dir=Path(""), suggest_patterns=["x.xlsx"])
    result = resolve_xlsx("宮下", entry, 2026, 3, cache={})
    assert result.status == CPlacementStatus.SKIPPED_NO_XLSX


# ---------- T3: plan_c_placement 統合 ----------


def _checklist_cfg(
    tmp_path: Path,
    *,
    cache: dict[str, str] | None = None,
    routing: dict[str, str] | None = None,
    suggest: list[str] | None = None,
) -> tuple[ChecklistConfig, Path]:
    fax_root = tmp_path / "FAX"
    fax_root.mkdir()
    base = tmp_path / "PT 宮下"
    (base / "リハ経過報告書" / "令和8年").mkdir(parents=True)
    xlsx = base / "リハ経過報告書" / "令和8年" / "リハ経過報告書（宮下）3月    .xlsx"
    xlsx.write_text("")
    entry = ReportStaffEntry(
        base_dir=base,
        suggest_patterns=suggest
        or ["リハ経過報告書/令和{era}年/リハ経過報告書*{month}月*.xlsx"],
    )
    cfg = ChecklistConfig(
        fax_root=fax_root,
        c_output_subfolder="経過報告書",
        facility_routing=routing or {"事業所A": "事業所A_FAX"},
        report_staff={"宮下": entry},
        xlsx_path_cache=cache or {},
    )
    return cfg, xlsx


def test_plan_c_placement_skipped_no_facility(tmp_path: Path) -> None:
    cfg, _ = _checklist_cfg(tmp_path, routing={})
    rows = [ChecklistRow(name="X", monitoring_raw=None, staff="宮下", facility="未登録居宅")]
    results = plan_c_placement(rows, cfg, 2026, 3)
    assert results[0].status == CPlacementStatus.SKIPPED_NO_FACILITY


def test_plan_c_placement_normalizes_facility_lookup(tmp_path: Path) -> None:
    """PR-γ v1: 全角空白入力（スプレッドシート）が半角空白登録の routing にマッチ。

    実機 Phase 3 で「介護相談支援センター　LEBEN」(全角空白) が
    「介護相談支援センター LEBEN」(半角空白) で登録された routing と
    マッチしなかった事象 (regression case) を固定する。
    """
    from wiseman_hub.utils.text_norm import normalize_lookup_key

    cfg, _ = _checklist_cfg(
        tmp_path,
        routing={
            normalize_lookup_key("介護相談支援センター LEBEN"): "LEBEN(メール)",
        },
    )
    rows = [
        ChecklistRow(
            name="X",
            monitoring_raw=None,
            staff="宮下",
            facility="介護相談支援センター　LEBEN",  # 全角空白
        )
    ]
    results = plan_c_placement(rows, cfg, 2026, 3)
    # 居宅未登録判定にならない（lookup 正規化が効いている）
    assert results[0].status != CPlacementStatus.SKIPPED_NO_FACILITY


def test_plan_c_placement_skipped_no_staff(tmp_path: Path) -> None:
    cfg, _ = _checklist_cfg(tmp_path)
    rows = [ChecklistRow(name="X", monitoring_raw=None, staff="未知担当者", facility="事業所A")]
    results = plan_c_placement(rows, cfg, 2026, 3)
    assert results[0].status == CPlacementStatus.SKIPPED_NO_STAFF


def test_plan_c_placement_needs_review_propagates_candidates(tmp_path: Path) -> None:
    """cache miss で candidates が CPlacementResult に伝搬。"""
    cfg, xlsx = _checklist_cfg(tmp_path)
    rows = [ChecklistRow(name="X", monitoring_raw=None, staff="宮下", facility="事業所A")]
    results = plan_c_placement(rows, cfg, 2026, 3)
    assert results[0].status == CPlacementStatus.NEEDS_REVIEW
    assert results[0].xlsx_candidates == [xlsx]
    # NEEDS_REVIEW 段階では target_pdf は確定しない
    assert results[0].target_pdf is None


# ---------- T4: apply_xlsx_selection ----------


def _make_xlsx_with_sheet(path: Path, sheet_names: list[str]) -> Path:
    """openpyxl で実 xlsx を生成（シート名一致のテスト用）。"""
    from openpyxl import Workbook

    wb = Workbook()
    # デフォルトシートを最初の名前で置き換え
    wb.active.title = sheet_names[0]
    for name in sheet_names[1:]:
        wb.create_sheet(name)
    wb.save(path)
    return path


def test_apply_xlsx_selection_sheet_match_sets_pending(tmp_path: Path) -> None:
    from wiseman_hub.pdf.checklist_c import apply_xlsx_selection

    fax_root = tmp_path / "FAX"
    fax_root.mkdir()
    cfg = ChecklistConfig(
        fax_root=fax_root,
        c_output_subfolder="経過報告書",
        facility_routing={"事業所A": "事業所A_FAX"},
    )
    xlsx = _make_xlsx_with_sheet(tmp_path / "x.xlsx", ["テスト 太郎", "他"])
    result = CPlacementResult(
        row=_row(name="テスト 太郎", staff="宮下", facility="事業所A"),
        status=CPlacementStatus.NEEDS_REVIEW,
        xlsx_candidates=[xlsx, tmp_path / "y.xlsx"],
        folder_tree={"name": "x"},
        message="prev",
    )
    apply_xlsx_selection(result, xlsx, cfg)
    assert result.status == CPlacementStatus.PENDING
    assert result.xlsx_path == xlsx
    assert result.sheet_name == "テスト 太郎"
    assert result.target_pdf == fax_root / "事業所A_FAX" / "経過報告書" / "テスト 太郎.pdf"
    # NEEDS_REVIEW 時のフィールドはクリア
    assert result.xlsx_candidates == []
    assert result.folder_tree is None
    assert result.message == ""


def test_apply_xlsx_selection_sheet_not_found(tmp_path: Path) -> None:
    from wiseman_hub.pdf.checklist_c import apply_xlsx_selection

    cfg = ChecklistConfig(
        fax_root=tmp_path,
        c_output_subfolder="経過報告書",
        facility_routing={"事業所A": "事業所A_FAX"},
    )
    xlsx = _make_xlsx_with_sheet(tmp_path / "x.xlsx", ["別人"])
    result = CPlacementResult(
        row=_row(name="テスト 太郎", staff="宮下", facility="事業所A"),
        status=CPlacementStatus.NEEDS_REVIEW,
    )
    apply_xlsx_selection(result, xlsx, cfg)
    assert result.status == CPlacementStatus.SKIPPED_NO_SHEET
    assert "別人" in result.sheet_candidates
    assert result.target_pdf is None


def test_apply_xlsx_selection_no_facility_routing(tmp_path: Path) -> None:
    from wiseman_hub.pdf.checklist_c import apply_xlsx_selection

    cfg = ChecklistConfig(
        fax_root=tmp_path, facility_routing={}, c_output_subfolder="経過報告書"
    )
    xlsx = _make_xlsx_with_sheet(tmp_path / "x.xlsx", ["テスト 太郎"])
    result = CPlacementResult(
        row=_row(name="テスト 太郎", staff="宮下", facility="未知居宅"),
        status=CPlacementStatus.NEEDS_REVIEW,
    )
    apply_xlsx_selection(result, xlsx, cfg)
    assert result.status == CPlacementStatus.SKIPPED_NO_FACILITY
