"""PlacementConfirmDialog の dry-run / 行選択（PR-ζ v1）。

検証点:
    - 初期状態で全件選択
    - ドライランボタン → proceed=True, dry_run=True, selected_indices=全件
    - 実配置ボタン → proceed=True, dry_run=False
    - キャンセル → proceed=False, selected_indices=[]
    - 全解除後にドライラン押下 → 何も起きない（0 件選択ガード）
    - 部分選択 → selected_indices に正しい index
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path

import pytest

from wiseman_hub.cloud.sheets import ChecklistRow
from wiseman_hub.pdf.checklist_c import CPlacementResult, CPlacementStatus
from wiseman_hub.ui.placement_confirm_dialog import PlacementConfirmDialog


def _make_results(tmp_path: Path, n: int = 3) -> list[CPlacementResult]:
    out: list[CPlacementResult] = []
    for i in range(n):
        row = ChecklistRow(
            name=f"利用者{i}",
            monitoring_raw="",
            staff="宮下",
            facility=f"居宅{i}",
        )
        r = CPlacementResult(row=row)
        r.status = CPlacementStatus.PENDING
        r.xlsx_path = tmp_path / f"x{i}.xlsx"
        r.sheet_name = f"利用者{i}"
        r.target_pdf = tmp_path / "out" / f"利用者{i}.pdf"
        out.append(r)
    return out


@pytest.mark.tk_required
class TestPlacementConfirmDialog:
    def test_initial_state_all_selected(self, tmp_path: Path) -> None:
        root = tk.Tk()
        try:
            results = _make_results(tmp_path, 3)
            dlg = PlacementConfirmDialog(root, results)
            sel = dlg._tree.selection()
            assert len(sel) == 3
            dlg.get_toplevel().destroy()
        finally:
            root.destroy()

    def test_dry_run_button_proceeds_with_dry_run_true(self, tmp_path: Path) -> None:
        root = tk.Tk()
        try:
            results = _make_results(tmp_path, 3)
            dlg = PlacementConfirmDialog(root, results)
            dlg._on_dry_run()
            assert dlg.get_proceed() is True
            assert dlg.get_dry_run() is True
            assert dlg.get_selected_indices() == [0, 1, 2]
        finally:
            root.destroy()

    def test_real_run_button_proceeds_with_dry_run_false(
        self, tmp_path: Path
    ) -> None:
        root = tk.Tk()
        try:
            results = _make_results(tmp_path, 3)
            dlg = PlacementConfirmDialog(root, results)
            dlg._on_real_run()
            assert dlg.get_proceed() is True
            assert dlg.get_dry_run() is False
            assert dlg.get_selected_indices() == [0, 1, 2]
        finally:
            root.destroy()

    def test_cancel_returns_no_proceed(self, tmp_path: Path) -> None:
        root = tk.Tk()
        try:
            results = _make_results(tmp_path, 3)
            dlg = PlacementConfirmDialog(root, results)
            dlg._on_cancel()
            assert dlg.get_proceed() is False
            assert dlg.get_selected_indices() == []
        finally:
            root.destroy()

    def test_select_none_then_dry_run_is_blocked(self, tmp_path: Path) -> None:
        """全解除後の dry-run 押下は 0 件ガードで何もしない（dialog 残存）。"""
        root = tk.Tk()
        try:
            results = _make_results(tmp_path, 3)
            dlg = PlacementConfirmDialog(root, results)
            dlg._on_select_none()
            dlg._on_dry_run()
            assert dlg.get_proceed() is False  # 進まない
            top = dlg.get_toplevel()
            assert top.winfo_exists()
            top.destroy()
        finally:
            root.destroy()

    def test_partial_selection_returns_subset_indices(self, tmp_path: Path) -> None:
        """1 件だけ選択 → selected_indices にその index のみ。"""
        root = tk.Tk()
        try:
            results = _make_results(tmp_path, 3)
            dlg = PlacementConfirmDialog(root, results)
            # 全解除 → index=1 のみ選択
            dlg._on_select_none()
            dlg._tree.selection_set("1")
            dlg._on_dry_run()
            assert dlg.get_selected_indices() == [1]
            assert dlg.get_dry_run() is True
        finally:
            root.destroy()

    def test_select_all_button_restores_full_selection(
        self, tmp_path: Path
    ) -> None:
        root = tk.Tk()
        try:
            results = _make_results(tmp_path, 4)
            dlg = PlacementConfirmDialog(root, results)
            dlg._on_select_none()
            assert len(dlg._tree.selection()) == 0
            dlg._on_select_all()
            assert len(dlg._tree.selection()) == 4
            dlg.get_toplevel().destroy()
        finally:
            root.destroy()
