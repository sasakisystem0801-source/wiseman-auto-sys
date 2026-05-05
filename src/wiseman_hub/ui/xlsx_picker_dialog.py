"""担当者 xlsx 候補から 1 件を選ぶレビュー UI モーダル。

C ダイアログで NEEDS_REVIEW 行をダブルクリックすると開く。

機能:
    1. 候補 xlsx リスト（``xlsx_candidates``）を Listbox で提示
       - ``target_year``/``target_month`` 指定時は対象月パターンに絞り込み（誤選択防止）
    2. 「フォルダから選択」で base_dir 配下の Treeview に切り替えて任意 .xlsx を選択
    3. 「この選択を記憶」チェックで cache 永続化を要求
    4. 「現在の選択値」を下部に明示表示（OK で記録される xlsx を目視確認可能）
    5. 候補 / Treeview のうち最後に操作した側を OK 時に採用（先行クリックの影響回避）
    6. 未選択時は OK ボタン disabled（誤選択ガード）
    7. OK / キャンセル

戻り値:
    ``get_result() -> (selected_path: Path | None, remember: bool)``
    キャンセル時は ``(None, False)``。

設計判断:
    - 自動確定はしない: 候補 1 件でも必ずユーザーが OK を押すフローにする
      （介護記録誤配置リスクの構造的対策）
    - **初期選択は持たせない**: 旧仕様の ``selection_set(0)`` は誤選択源
      （フォルダから選んだのに候補先頭が記録される事案発生のため廃止）
    - **Listbox / Treeview の優先順位は「後勝ち」**: 旧仕様の「候補 Listbox が常に優先」を廃止
"""

from __future__ import annotations

import logging
import re
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Any, Literal

logger = logging.getLogger(__name__)


_LastActive = Literal["listbox", "tree"] | None


def _matches_target_month(
    path: Path, target_year: int | None, target_month: int | None
) -> bool:
    """候補パスが対象 (year, month) を含むか粗判定。

    対応パターン:
        - ``令和{era}年`` および ``{month}月`` 両方を含む
        - ``R{era}.{month}`` の連結（例: ``R8.3``）
        - ``令和{era}年{month}月`` の連結
        - 対象未指定（year/month が None）の場合は常に True

    Wiseman 業務側の xlsx 命名は担当者ごとに揺れるため、
    厳密マッチではなく「対象月 / 対象年 / 西暦も含む or-条件」のゆるい絞り込み。
    フィルタの目的は「**確実に違う月を排除する**」ことで、
    残った候補の最終確認はユーザーに委ねる。
    """
    if target_year is None or target_month is None:
        return True
    # 令和 = 西暦 - 2018
    era = target_year - 2018
    s = str(path)
    # 強い手がかり: R{era}.{month} 連結（例: R8.3）
    if re.search(rf"R{era}\.{target_month}\b", s):
        return True
    # 令和{era}年 + {month}月 が両方含まれる
    has_era = (
        f"令和{era}年" in s
        or f"令和{era:02d}年" in s
        or f"R{era}年" in s
        or f"R{era:02d}年" in s
    )
    has_month = f"{target_month}月" in s or f"{target_month:02d}月" in s
    if has_era and has_month:
        return True
    # 西暦 + {month}月（例: 2026年3月）
    return bool(f"{target_year}年" in s and has_month)


class XlsxPickerDialog:
    def __init__(
        self,
        parent: tk.Misc,
        candidates: list[Path],
        folder_tree: dict[str, Any] | None,
        title_context: str = "",
        target_year: int | None = None,
        target_month: int | None = None,
    ) -> None:
        self._parent = parent
        self._all_candidates = list(candidates)
        # 対象月フィルタを通した表示用候補
        self._candidates: list[Path] = [
            p for p in self._all_candidates if _matches_target_month(p, target_year, target_month)
        ]
        self._target_year = target_year
        self._target_month = target_month
        self._folder_tree = folder_tree
        self._selected: Path | None = None
        self._remember: bool = True
        # 「最後に操作した側」を記録（後勝ち優先）
        self._last_active: _LastActive = None

        self._top = tk.Toplevel(parent)
        self._top.title(f"xlsx 選択: {title_context}" if title_context else "xlsx 選択")
        self._top.geometry("720x560")
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
        filtered_n = len(self._candidates)
        all_n = len(self._all_candidates)
        if self._target_year is not None and self._target_month is not None:
            era = self._target_year - 2018
            head_text = (
                f"対象月: 令和{era}年{self._target_month}月 "
                f"/ 候補 {filtered_n} 件（全 {all_n} 件中、対象月パターンで絞込）"
            )
        else:
            head_text = f"候補 {filtered_n} 件 / フォルダから選択も可能"
        ttk.Label(head, text=head_text).pack(side="left")

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
        # 旧仕様の `selection_set(0)` は意図しない初期選択を生み誤選択源だったため廃止
        self._cand_list.bind("<<ListboxSelect>>", self._on_listbox_select)
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
        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self._tree.bind("<Double-1>", lambda _e: self._on_tree_double_click())

        # 「現在の選択値」表示
        sel_frame = ttk.Frame(top, padding=(8, 0))
        sel_frame.pack(fill="x")
        self._current_var = tk.StringVar(
            value="現在の選択: (未選択 — 候補またはフォルダから選んでください)"
        )
        ttk.Label(
            sel_frame, textvariable=self._current_var, foreground="#0a5"
        ).pack(side="left", fill="x", expand=True)

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
        self._ok_btn = ttk.Button(bottom, text="OK", command=self._on_ok)
        self._ok_btn.pack(side="right", padx=4)
        # 初期状態は未選択 → OK 不可
        self._ok_btn.configure(state="disabled")

    def _populate_tree(self, node: dict[str, Any], parent: str) -> None:
        """folder_tree dict を Treeview に再帰的に展開。"""
        iid = self._tree.insert(
            parent,
            "end",
            text=node.get("name", ""),
            values=(node.get("path", ""),),
            open=parent == "",
        )
        for child in node.get("children", []):
            self._populate_tree(child, parent=iid)

    # ---- 選択状態の解決 ----

    def _resolve_current(self) -> Path | None:
        """``_last_active`` を尊重した上で、現在 OK で記録される Path を返す。"""
        if self._last_active == "tree":
            return self._tree_selected_xlsx()
        if self._last_active == "listbox":
            return self._listbox_selected_xlsx()
        # どちらもまだ操作されていない
        return None

    def _listbox_selected_xlsx(self) -> Path | None:
        sel = self._cand_list.curselection()  # type: ignore[no-untyped-call]
        if not sel:
            return None
        idx = int(sel[0])
        if 0 <= idx < len(self._candidates):
            return self._candidates[idx]
        return None

    def _tree_selected_xlsx(self) -> Path | None:
        sel = self._tree.selection()
        if not sel:
            return None
        item = self._tree.item(sel[0])
        path_str = item["values"][0] if item.get("values") else ""
        if not path_str or not str(path_str).lower().endswith(".xlsx"):
            return None
        return Path(str(path_str))

    def _refresh_current_label(self) -> None:
        cur = self._resolve_current()
        if cur is None:
            self._current_var.set(
                "現在の選択: (未選択 — 候補またはフォルダから選んでください)"
            )
            self._ok_btn.configure(state="disabled")
        else:
            src = "候補一覧" if self._last_active == "listbox" else "フォルダ"
            self._current_var.set(f"現在の選択 ({src}): {cur}")
            self._ok_btn.configure(state="normal")

    # ---- ハンドラ ----

    def _on_listbox_select(self, _event: object) -> None:
        if self._cand_list.curselection():  # type: ignore[no-untyped-call]
            self._last_active = "listbox"
            self._refresh_current_label()

    def _on_tree_select(self, _event: object) -> None:
        if self._tree.selection() and self._tree_selected_xlsx() is not None:
            self._last_active = "tree"
            self._refresh_current_label()

    def _on_tree_double_click(self) -> None:
        """Treeview で xlsx ファイルをダブルクリックしたら確定候補にする。"""
        path = self._tree_selected_xlsx()
        if path is None:
            return
        self._last_active = "tree"
        self._selected = path
        self._remember = bool(self._remember_var.get())
        self._top.destroy()

    def _on_ok(self) -> None:
        cur = self._resolve_current()
        if cur is None:
            return
        self._selected = cur
        self._remember = bool(self._remember_var.get())
        self._top.destroy()

    def _on_cancel(self) -> None:
        self._selected = None
        self._remember = False
        self._top.destroy()
