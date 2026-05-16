"""ChecklistCDialog の `_on_row_double_click` dispatch routing 契約テスト (Issue #314)。

Tk を起動せず ``ChecklistCDialog.__new__`` + ``MagicMock`` で属性を差し替え、
status による分岐ルーティングのみを検証する。``_open_staff_picker_for_review`` /
``_open_picker_for_review`` の本体は Tk Toplevel を生成するため別途 xfail / 実機
検証で扱う。dispatch のみテストすることで CI Linux ヘッドレスで回帰検出可能にする。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from wiseman_hub.cloud.sheets import ChecklistRow
from wiseman_hub.pdf.checklist_c import CPlacementResult, CPlacementStatus
from wiseman_hub.ui.checklist_c_dialog import ChecklistCDialog


def _make_dlg_with_results(results: list[CPlacementResult]) -> ChecklistCDialog:
    """Tk なしで dispatch ルーティング検証用の dlg instance を組み立てる。

    ``__new__`` で ``__init__`` を呼ばずに生 instance を作り、dispatch に必要な
    属性のみ MagicMock で埋める。本物の Tk Toplevel / ttk.Treeview は使わない。
    """
    dlg = ChecklistCDialog.__new__(ChecklistCDialog)
    dlg._tree = MagicMock()  # type: ignore[attr-defined]
    dlg._tree.selection.return_value = ("0",)
    dlg._results = results  # type: ignore[attr-defined]
    dlg._open_staff_picker_for_review = MagicMock()  # type: ignore[attr-defined]
    dlg._open_picker_for_review = MagicMock()  # type: ignore[attr-defined]
    return dlg


def _row(name: str = "テスト 太郎", staff: str = "宮下") -> ChecklistRow:
    return ChecklistRow(name=name, monitoring_raw=None, staff=staff, facility="事業所A")


def test_dispatch_needs_review_staff_routes_to_staff_picker() -> None:
    """NEEDS_REVIEW_STAFF → _open_staff_picker_for_review が呼ばれる (Issue #314)。

    xlsx picker は呼ばれない (staff 確定後に xlsx 解決が走る順序のため)。
    """
    result = CPlacementResult(
        row=_row(staff="小島/木塚"),
        status=CPlacementStatus.NEEDS_REVIEW_STAFF,
        staff_candidates=["小島", "木塚"],
    )
    dlg = _make_dlg_with_results([result])
    dlg._on_row_double_click(None)

    dlg._open_staff_picker_for_review.assert_called_once_with(0, result)
    dlg._open_picker_for_review.assert_not_called()


def test_dispatch_needs_review_routes_to_xlsx_picker_unchanged() -> None:
    """既存 NEEDS_REVIEW → _open_picker_for_review (xlsx picker)。regression 防止。

    Issue #314 で staff picker 分岐を追加したが、xlsx 選択待ち状態の挙動は
    変更しない。staff_picker_for_review は呼ばれない。
    """
    result = CPlacementResult(
        row=_row(),
        status=CPlacementStatus.NEEDS_REVIEW,
        xlsx_candidates=[Path("/share/a.xlsx")],
    )
    dlg = _make_dlg_with_results([result])
    dlg._on_row_double_click(None)

    dlg._open_picker_for_review.assert_called_once_with(0, result)
    dlg._open_staff_picker_for_review.assert_not_called()


def test_dispatch_pending_does_not_open_any_picker() -> None:
    """PENDING など xlsx_path 確定済の行はピッカーを開かない (フォルダ open 経路)。

    target_pdf / xlsx_path 両方 None にして ``target is None`` early return を
    狙う (folder.exists() / messagebox の副作用を本テストでは遮断、Tk 初期化
    していない環境で messagebox 呼出が hang する事案の予防)。ピッカーが
    呼ばれないことのみ検証する。
    """
    result = CPlacementResult(
        row=_row(),
        status=CPlacementStatus.PENDING,
        xlsx_path=None,
        target_pdf=None,
    )
    dlg = _make_dlg_with_results([result])
    dlg._on_row_double_click(None)

    dlg._open_picker_for_review.assert_not_called()
    dlg._open_staff_picker_for_review.assert_not_called()


def test_dispatch_no_selection_is_noop() -> None:
    """Treeview 未選択 → no-op (どのピッカーも開かない)。"""
    result = CPlacementResult(
        row=_row(),
        status=CPlacementStatus.NEEDS_REVIEW_STAFF,
        staff_candidates=["小島", "木塚"],
    )
    dlg = _make_dlg_with_results([result])
    dlg._tree.selection.return_value = ()  # 選択なし
    dlg._on_row_double_click(None)

    dlg._open_picker_for_review.assert_not_called()
    dlg._open_staff_picker_for_review.assert_not_called()
