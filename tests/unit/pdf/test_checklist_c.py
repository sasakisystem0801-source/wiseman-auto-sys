"""T1 範囲: CPlacementStatus と CPlacementResult の dataclass / enum 拡張テスト。

T2/T3 で resolve_xlsx / plan_c_placement のロジックテストを追加する。
"""

from __future__ import annotations

from pathlib import Path

from wiseman_hub.cloud.sheets import ChecklistRow
from wiseman_hub.pdf.checklist_c import CPlacementResult, CPlacementStatus


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
