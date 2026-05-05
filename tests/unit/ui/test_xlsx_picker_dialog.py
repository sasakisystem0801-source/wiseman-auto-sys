"""XlsxPickerDialog のユニットテスト。

PR-ε v1 で導入した以下の構造的誤選択防止機構を検証する:
    1. 初期状態で候補は無選択 (旧 ``selection_set(0)`` 廃止)
    2. OK ボタンは未選択時 disabled
    3. 「最後に操作した側」優先 (Listbox / Treeview の後勝ち)
    4. ``target_year``/``target_month`` フィルタで対象月以外の候補を排除
    5. ``_matches_target_month`` の各種命名規則対応 (R{era}.{month} / 令和{era}年{month}月 / 西暦)
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path

import pytest

from wiseman_hub.ui.xlsx_picker_dialog import (
    XlsxPickerDialog,
    _matches_target_month,
)


class TestMatchesTargetMonth:
    """``_matches_target_month`` の命名規則カバレッジ。"""

    def test_no_target_returns_true(self) -> None:
        """対象未指定時はフィルタ無効 (既存呼出の後方互換)。"""
        p = Path(r"\\nas\share\anything.xlsx")
        assert _matches_target_month(p, None, None) is True

    def test_r_era_month_concat(self) -> None:
        """R{era}.{month} 連結（小林スタイル: R8.3）。"""
        p = Path(r"\\nas\share\OT小林\経過報告書\R8\経過報告書 R8.3.xlsx")
        assert _matches_target_month(p, 2026, 3) is True
        # 月が違えば除外
        p2 = Path(r"\\nas\share\OT小林\経過報告書\R8\経過報告書 R8.2.xlsx")
        assert _matches_target_month(p2, 2026, 3) is False

    def test_reiwa_era_year_and_month(self) -> None:
        """令和{era}年 + {month}月 が両方含まれる（宮下スタイル）。"""
        p = Path(r"\\nas\share\PT 宮下\令和8年\リハ経過報告書 3月.xlsx")
        assert _matches_target_month(p, 2026, 3) is True
        # 令和6年10月（平瀬の旧仕様で誤マッチした例）は対象外
        p2 = Path(r"\\nas\share\PT 平瀬\令和6年\新経過報告書 10月.xlsx")
        assert _matches_target_month(p2, 2026, 3) is False

    def test_seireki_year_and_month(self) -> None:
        """西暦 + {month}月（小島スタイル: 令和8年3月 + 令和8年=2026年）。"""
        p = Path(r"\\nas\share\PT 小島\経過報告書 令和8年3月(最新) - .xlsx")
        assert _matches_target_month(p, 2026, 3) is True

    def test_kizuka_style(self) -> None:
        """木塚スタイル: 経過報告書 木塚R8.3月.xlsx。"""
        p = Path(r"\\nas\share\PT 木塚\経過報告書\令和8年度 経過報告書\経過報告書 木塚R8.3月.xlsx")
        assert _matches_target_month(p, 2026, 3) is True

    def test_year_alone_does_not_match_without_month(self) -> None:
        """年のみで月が一致しなければ除外（強制 AND 条件）。"""
        p = Path(r"\\nas\share\PT 平瀬\令和8年\新経過報告書 11月.xlsx")
        assert _matches_target_month(p, 2026, 3) is False

    def test_month_alone_does_not_match_without_era(self) -> None:
        """月のみで年がなければ除外（誤マッチ防止）。"""
        # 令和や R8 や 2026 を含まない汎用パス
        p = Path(r"C:\misc\folder\report 3月.xlsx")
        assert _matches_target_month(p, 2026, 3) is False


@pytest.mark.tk_required
class TestXlsxPickerDialog:
    """ダイアログの構造的誤選択防止機構の動作確認。"""

    def _make(self, root: tk.Tk, **kwargs: object) -> XlsxPickerDialog:
        defaults = {
            "candidates": [
                Path(r"\\nas\share\PT X\令和6年\new 10月.xlsx"),
                Path(r"\\nas\share\PT X\令和8年\new 3月.xlsx"),
            ],
            "folder_tree": None,
        }
        defaults.update(kwargs)
        return XlsxPickerDialog(parent=root, **defaults)  # type: ignore[arg-type]

    def test_no_initial_selection(self) -> None:
        """初期状態で候補 Listbox は無選択（旧 selection_set(0) 廃止確認）。"""
        root = tk.Tk()
        try:
            dialog = self._make(root)
            assert dialog._cand_list.curselection() == ()  # type: ignore[no-untyped-call]
            dialog.get_toplevel().destroy()
        finally:
            root.destroy()

    def test_ok_disabled_when_no_selection(self) -> None:
        """初期状態で OK ボタン disabled（誤選択ガード）。"""
        root = tk.Tk()
        try:
            dialog = self._make(root)
            assert str(dialog._ok_btn.cget("state")) == "disabled"
            dialog.get_toplevel().destroy()
        finally:
            root.destroy()

    def test_ok_does_nothing_without_selection(self) -> None:
        """未選択で OK 押下しても確定しない（destroy も走らない）。"""
        root = tk.Tk()
        try:
            dialog = self._make(root)
            top = dialog.get_toplevel()
            dialog._on_ok()
            assert dialog.get_result() == (None, True)
            assert top.winfo_exists()
            top.destroy()
        finally:
            root.destroy()

    def test_listbox_click_records_listbox_path(self) -> None:
        """Listbox クリック → OK で Listbox の選択が記録される。"""
        root = tk.Tk()
        try:
            cands = [Path("a.xlsx"), Path("b.xlsx")]
            dialog = XlsxPickerDialog(
                parent=root, candidates=cands, folder_tree=None
            )
            dialog._cand_list.selection_set(1)
            dialog._on_listbox_select(None)
            assert str(dialog._ok_btn.cget("state")) == "normal"
            dialog._on_ok()
            sel, _ = dialog.get_result()
            assert sel == Path("b.xlsx")
        finally:
            root.destroy()

    def test_tree_click_overrides_listbox(self) -> None:
        """Listbox 選択後に Treeview をクリック → Treeview 優先（後勝ち、誤選択源 #2 解消）。"""
        root = tk.Tk()
        try:
            tree = {
                "name": "root",
                "path": "",
                "children": [
                    {
                        "name": "target.xlsx",
                        "path": r"\\nas\target.xlsx",
                        "children": [],
                    }
                ],
            }
            dialog = XlsxPickerDialog(
                parent=root,
                candidates=[Path("wrong.xlsx")],
                folder_tree=tree,
            )
            # 1. まず Listbox をクリック (旧仕様ではこちらが OK で記録された)
            dialog._cand_list.selection_set(0)
            dialog._on_listbox_select(None)
            assert dialog._last_active == "listbox"
            # 2. その後 Treeview の xlsx をクリック
            children = dialog._tree.get_children("")
            xlsx_node = dialog._tree.get_children(children[0])[0]
            dialog._tree.selection_set(xlsx_node)
            dialog._on_tree_select(None)
            assert dialog._last_active == "tree"
            # 3. OK で記録されるのは Treeview 側
            dialog._on_ok()
            sel, _ = dialog.get_result()
            assert sel == Path(r"\\nas\target.xlsx")
        finally:
            root.destroy()

    def test_target_month_filters_candidates(self) -> None:
        """target_year/month 指定で候補一覧が対象月パターンのみに絞られる。"""
        root = tk.Tk()
        try:
            cands = [
                Path(r"\\nas\PT 平瀬\令和6年\new 10月.xlsx"),  # 除外
                Path(r"\\nas\PT 平瀬\令和8年\new 3月.xlsx"),  # 採用
                Path(r"\\nas\PT 平瀬\令和8年\new R8.3.xlsx"),  # 採用
                Path(r"\\nas\PT 平瀬\令和8年\new 11月.xlsx"),  # 除外
            ]
            dialog = XlsxPickerDialog(
                parent=root,
                candidates=cands,
                folder_tree=None,
                target_year=2026,
                target_month=3,
            )
            assert len(dialog._candidates) == 2
            assert all(
                ("3月" in str(p) or "R8.3" in str(p)) for p in dialog._candidates
            )
            # 全 4 件中 2 件にフィルタされた旨が表示される
            dialog.get_toplevel().destroy()
        finally:
            root.destroy()

    def test_cancel_returns_none(self) -> None:
        """キャンセルで (None, False) を返す。"""
        root = tk.Tk()
        try:
            dialog = self._make(root)
            dialog._on_cancel()
            assert dialog.get_result() == (None, False)
        finally:
            root.destroy()
