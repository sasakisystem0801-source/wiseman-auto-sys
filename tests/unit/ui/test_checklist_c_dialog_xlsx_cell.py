"""C ダイアログ Treeview の xlsx 列フォーマッタ ``_format_xlsx_cell`` の契約テスト。

5 状態分岐 (xlsx_path 確定 / NEEDS_REVIEW × {0,1,N} 件 / SKIPPED 系) と
xlsx_path が立っているときの優先順位を Tk なしで網羅する。Treeview 表示を
UI dialog instance ごと立ち上げず純粋関数として検証することで、
分岐網羅 + ヘッドレス CI 実行 + 回帰検出強度を両立する。
"""

from __future__ import annotations

from pathlib import Path

from wiseman_hub.cloud.sheets import ChecklistRow
from wiseman_hub.pdf.checklist_c import CPlacementResult, CPlacementStatus
from wiseman_hub.ui.checklist_c_dialog import _format_xlsx_cell


def _row(name: str = "テスト 太郎") -> ChecklistRow:
    return ChecklistRow(name=name, monitoring_raw=None, staff="宮下", facility="事業所A")


def test_xlsx_cell_shows_basename_when_path_resolved() -> None:
    """PENDING / SUCCESS など xlsx_path 確定済の行は basename を表示。"""
    result = CPlacementResult(
        row=_row(),
        status=CPlacementStatus.PENDING,
        xlsx_path=Path("/share/PT 宮下/リハ経過報告書/令和8年/report.xlsx"),
    )
    assert _format_xlsx_cell(result) == "report.xlsx"


def test_xlsx_cell_shows_basename_for_success_too() -> None:
    """SUCCESS でも xlsx_path が確定済なら basename。"""
    result = CPlacementResult(
        row=_row(),
        status=CPlacementStatus.SUCCESS,
        xlsx_path=Path("/share/report-success.xlsx"),
    )
    assert _format_xlsx_cell(result) == "report-success.xlsx"


def test_xlsx_cell_shows_basename_for_single_candidate() -> None:
    """NEEDS_REVIEW で候補 1 件: basename を出す (ほぼ確定状態の可視化)。"""
    cand = Path("/share/PT 平瀬/リハ経過報告書/令和8年/新経過報告書 R8.3.xlsx")
    result = CPlacementResult(
        row=_row(),
        status=CPlacementStatus.NEEDS_REVIEW,
        xlsx_candidates=[cand],
    )
    assert _format_xlsx_cell(result) == "新経過報告書 R8.3.xlsx"


def test_xlsx_cell_shows_count_for_multiple_candidates() -> None:
    """NEEDS_REVIEW で候補 N 件 (N>=2): 件数表示。"""
    result = CPlacementResult(
        row=_row(),
        status=CPlacementStatus.NEEDS_REVIEW,
        xlsx_candidates=[
            Path("/share/a.xlsx"),
            Path("/share/b.xlsx"),
            Path("/share/c.xlsx"),
        ],
    )
    assert _format_xlsx_cell(result) == "(3 件候補)"


def test_xlsx_cell_shows_no_candidates_label_when_empty() -> None:
    """NEEDS_REVIEW で候補ゼロ: 「(候補なし)」明示 (空欄回避)。"""
    result = CPlacementResult(
        row=_row(),
        status=CPlacementStatus.NEEDS_REVIEW,
        xlsx_candidates=[],
    )
    assert _format_xlsx_cell(result) == "(候補なし)"


def test_xlsx_cell_empty_for_skipped_no_facility() -> None:
    """居宅未登録は xlsx_path/candidates が無くて当然なので空欄。"""
    result = CPlacementResult(
        row=_row(),
        status=CPlacementStatus.SKIPPED_NO_FACILITY,
    )
    assert _format_xlsx_cell(result) == ""


def test_xlsx_cell_empty_for_skipped_no_staff() -> None:
    result = CPlacementResult(
        row=_row(),
        status=CPlacementStatus.SKIPPED_NO_STAFF,
    )
    assert _format_xlsx_cell(result) == ""


def test_xlsx_cell_empty_for_skipped_no_xlsx() -> None:
    """xlsx 不在 (base_dir 不在等) は xlsx_path=None なので空欄。"""
    result = CPlacementResult(
        row=_row(),
        status=CPlacementStatus.SKIPPED_NO_XLSX,
    )
    assert _format_xlsx_cell(result) == ""


def test_xlsx_cell_basename_takes_precedence_over_candidates() -> None:
    """xlsx_path が立っていれば NEEDS_REVIEW 以外の状態でも候補件数より basename を優先する。

    候補リスト残りつつ status 変化したような中間状態でも UI 表示が崩れないことを確認。
    """
    result = CPlacementResult(
        row=_row(),
        status=CPlacementStatus.PENDING,
        xlsx_path=Path("/share/picked.xlsx"),
        xlsx_candidates=[
            Path("/share/picked.xlsx"),
            Path("/share/other.xlsx"),
        ],
    )
    assert _format_xlsx_cell(result) == "picked.xlsx"


# Issue #314: NEEDS_REVIEW_STAFF (担当者複数) の xlsx 列表示テスト
# staff 確定後に xlsx 解決が走るため、この状態では人数情報のみを表示する。


def test_xlsx_cell_shows_staff_count_for_needs_review_staff_full_hit() -> None:
    """NEEDS_REVIEW_STAFF で全員 mapping 登録済: 「(担当者 N 名)」を表示。

    message に "未登録あり" マーカーがなければ全員登録済とみなす。
    """
    result = CPlacementResult(
        row=_row(),
        status=CPlacementStatus.NEEDS_REVIEW_STAFF,
        staff_candidates=["小島", "木塚"],
        message="2 名から担当者を選択してください",
    )
    assert _format_xlsx_cell(result) == "(担当者 2 名)"


def test_xlsx_cell_shows_partial_hit_marker_for_needs_review_staff() -> None:
    """NEEDS_REVIEW_STAFF で一部 mapping 未登録: 「(担当者 N 名 / 未登録あり)」を表示。

    message に "未登録あり" が含まれていれば部分 hit と判断、UI で警戒可視化。
    """
    result = CPlacementResult(
        row=_row(),
        status=CPlacementStatus.NEEDS_REVIEW_STAFF,
        staff_candidates=["小島", "木塚", "宮下"],
        message="3 名中 2 名のみ登録済 (未登録あり: 木塚)、登録済から選択してください",
    )
    assert _format_xlsx_cell(result) == "(担当者 3 名 / 未登録あり)"


def test_xlsx_cell_needs_review_staff_with_single_candidate() -> None:
    """NEEDS_REVIEW_STAFF で 1 名のみ (まれ): 「(担当者 1 名)」を表示。

    通常 1 名なら NEEDS_REVIEW_STAFF にせず自動確定するが、UI 防御のため
    フォーマッタが 1 名でも崩れず描画できることを保証する。
    """
    result = CPlacementResult(
        row=_row(),
        status=CPlacementStatus.NEEDS_REVIEW_STAFF,
        staff_candidates=["小島"],
        message="1 名から担当者を選択してください",
    )
    assert _format_xlsx_cell(result) == "(担当者 1 名)"
