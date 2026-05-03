"""担当者 xlsx 候補から 1 件を選ぶレビュー UI モーダル。

C ダイアログで NEEDS_REVIEW 行をダブルクリックすると開く。

機能:
    1. 候補 xlsx リスト（``xlsx_candidates``）を Listbox で提示
    2. 「フォルダから選択」で base_dir 配下の Treeview に切り替えて任意 .xlsx を選択
    3. 「この選択を記憶」チェックで cache 永続化を要求
    4. OK / キャンセル

戻り値:
    ``get_result() -> (selected_path: Path | None, remember: bool)``
    キャンセル時は ``(None, False)``。

設計判断:
    - 自動確定はしない: 候補 1 件でも必ずユーザーが OK を押すフローにする
      （介護記録誤配置リスクの構造的対策）
    - Treeview ファイルブラウザは折りたたみ可能、初期は候補リスト Listbox を
      最前面に表示してクリック数を最小化
"""

from __future__ import annotations

import logging
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Any

logger = logging.getLogger(__name__)


class XlsxPickerDialog:
    def __init__(
        self,
        parent: tk.Misc,
        candidates: list[Path],
        folder_tree: dict[str, Any] | None,
        title_context: str = "",
    ) -> None:
        self._parent = parent
        self._candidates = list(candidates)
        self._folder_tree = folder_tree
        self._selected: Path | None = None
        self._remember: bool = True

        self._top = tk.Toplevel(parent)
        self._top.title(f"xlsx 選択: {title_context}" if title_context else "xlsx 選択")
        self._top.geometry("720x500")
        # transient は Wm | Tcl_Obj のみ許容、Misc を渡すケースがあるため広めに無視
        if hasattr(parent, "winfo_toplevel"):
            self._top.transient(parent.winfo_toplevel())
        self._top.grab_set()

        self._build_ui()

    def get_toplevel(self) -> tk.Toplevel:
        return self._top

    def get_result(self) -> tuple[Path | None, bool]:
        return self._selected, self._remember

    # ---- UI 構築 ----

    def _build_ui(self) -> None:
        top = self._top

        head = ttk.Frame(top, padding=8)
        head.pack(fill="x")
        ttk.Label(
            head,
            text=f"候補 {len(self._candidates)} 件 / フォルダから選択も可能",
        ).pack(side="left")

        body = ttk.Frame(top, padding=8)
        body.pack(fill="both", expand=True)

        # 候補 Listbox
        cand_frame = ttk.LabelFrame(body, text="候補一覧", padding=4)
        cand_frame.pack(fill="both", expand=True, pady=(0, 4))
        self._cand_list = tk.Listbox(cand_frame, height=8, exportselection=False)
        self._cand_list.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(
            cand_frame, orient="vertical", command=self._cand_list.yview
        )
        scroll.pack(side="right", fill="y")
        self._cand_list.configure(yscrollcommand=scroll.set)
        for path in self._candidates:
            self._cand_list.insert("end", str(path))
        if self._candidates:
            self._cand_list.selection_set(0)
        self._cand_list.bind("<Double-1>", lambda _e: self._on_ok())

        # フォルダブラウザ
        tree_frame = ttk.LabelFrame(
            body, text="フォルダから選択（候補にない場合）", padding=4
        )
        tree_frame.pack(fill="both", expand=True)
        self._tree = ttk.Treeview(tree_frame, show="tree", height=8)
        self._tree.pack(side="left", fill="both", expand=True)
        tscroll = ttk.Scrollbar(
            tree_frame, orient="vertical", command=self._tree.yview
        )
        tscroll.pack(side="right", fill="y")
        self._tree.configure(yscrollcommand=tscroll.set)
        if self._folder_tree:
            self._populate_tree(self._folder_tree, parent="")
        self._tree.bind("<Double-1>", lambda _e: self._on_tree_double_click())

        # 記憶チェック + ボタン
        bottom = ttk.Frame(top, padding=8)
        bottom.pack(fill="x")
        self._remember_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            bottom,
            text="この選択を記憶（次回以降は自動使用）",
            variable=self._remember_var,
        ).pack(side="left")
        ttk.Button(bottom, text="キャンセル", command=self._on_cancel).pack(
            side="right", padx=4
        )
        ttk.Button(bottom, text="OK", command=self._on_ok).pack(side="right", padx=4)

    def _populate_tree(self, node: dict[str, Any], parent: str) -> None:
        """folder_tree dict を Treeview に再帰的に展開。"""
        iid = self._tree.insert(
            parent,
            "end",
            text=node.get("name", ""),
            values=(node.get("path", ""),),
            open=parent == "",  # ルートのみ開いた状態
        )
        for child in node.get("children", []):
            self._populate_tree(child, parent=iid)

    # ---- ハンドラ ----

    def _on_tree_double_click(self) -> None:
        """Treeview で xlsx ファイルをダブルクリックしたら確定候補にする。"""
        sel = self._tree.selection()
        if not sel:
            return
        item = self._tree.item(sel[0])
        path_str = item["values"][0] if item.get("values") else ""
        if not path_str or not str(path_str).lower().endswith(".xlsx"):
            return
        self._selected = Path(str(path_str))
        self._remember = bool(self._remember_var.get())
        self._top.destroy()

    def _on_ok(self) -> None:
        # 候補 Listbox に選択があればそれを使う、なければ Treeview の選択
        sel = self._cand_list.curselection()  # type: ignore[no-untyped-call]
        if sel:
            idx = int(sel[0])
            self._selected = self._candidates[idx]
        else:
            tree_sel = self._tree.selection()
            if tree_sel:
                item = self._tree.item(tree_sel[0])
                path_str = item["values"][0] if item.get("values") else ""
                if path_str and str(path_str).lower().endswith(".xlsx"):
                    self._selected = Path(str(path_str))
        self._remember = bool(self._remember_var.get())
        self._top.destroy()

    def _on_cancel(self) -> None:
        self._selected = None
        self._remember = False
        self._top.destroy()
