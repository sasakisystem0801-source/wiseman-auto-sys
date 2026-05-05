"""配置前確認ダイアログ（C 経過報告書配置のリリースゲート）。

Codex review HIGH-3 対策: 既存の messagebox.askyesno + 5 件サンプル表示では
6 件目以降の誤 cache / 誤出力が業務責任者に見えないため、Treeview で全件
（name / staff / xlsx_path / sheet_name / target_pdf）を提示してから OK 判定する。

PR-ζ v1: dry-run + 行選択（少数件で動作テストしてから本番）
    - Treeview 多重選択（Ctrl/Shift + click、デフォルト全選択）
    - 「全選択 / 全解除」ボタンで補助
    - 「ドライラン（実 PDF 書込なし）」「実配置」の 2 ボタン
    - dry-run は実害ゼロで path / sheet 検査のみ実施

設計判断:
    - スクロール可能な Treeview で件数に依存しない確認 UX
    - 列幅は xlsx_path / target_pdf を広めにして path 確認を最優先
    - cancel = 配置中止、ドライラン / 実配置 = 続行
    - PII（利用者氏名・パス）はモーダル内のみで完結、外部送信なし

戻り値:
    ``proceed: bool`` — ドライランまたは実配置を実行する場合 True
    ``dry_run: bool`` — True ならドライラン、False なら実配置
    ``selected_indices: list[int]`` — 実行対象行のインデックス（pending_results 内）
"""

from __future__ import annotations

import logging
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wiseman_hub.pdf.checklist_c import CPlacementResult

logger = logging.getLogger(__name__)


def _path_or_blank(p: Path | None) -> str:
    return str(p) if p else ""


class PlacementConfirmDialog:
    """配置前確認モーダル。Tk Toplevel + Treeview で全件提示。"""

    def __init__(
        self, parent: tk.Misc, pending_results: list[CPlacementResult]
    ) -> None:
        self._parent = parent
        self._results = list(pending_results)
        self._proceed: bool = False
        self._dry_run: bool = False
        self._selected_indices: list[int] = []

        self._top = tk.Toplevel(parent)
        self._top.title(f"配置前確認: {len(self._results)} 件")
        self._top.geometry("980x540")
        if hasattr(parent, "winfo_toplevel"):
            self._top.transient(parent.winfo_toplevel())
        self._top.grab_set()

        self._build_ui()

    def get_toplevel(self) -> tk.Toplevel:
        return self._top

    def get_proceed(self) -> bool:
        return self._proceed

    def get_dry_run(self) -> bool:
        return self._dry_run

    def get_selected_indices(self) -> list[int]:
        return list(self._selected_indices)

    def _build_ui(self) -> None:
        top = self._top

        head = ttk.Frame(top, padding=8)
        head.pack(fill="x")
        ttk.Label(
            head,
            text=(
                f"PENDING {len(self._results)} 件のうち、"
                "選択した行のみ実行します（デフォルト全選択）。"
            ),
        ).pack(side="left")

        body = ttk.Frame(top, padding=8)
        body.pack(fill="both", expand=True)

        cols = ("name", "staff", "facility", "xlsx", "sheet", "target")
        # selectmode=extended で Ctrl/Shift + click による多重選択を許可
        self._tree = ttk.Treeview(
            body, columns=cols, show="headings", height=15, selectmode="extended"
        )
        self._tree.heading("name", text="氏名")
        self._tree.heading("staff", text="担当")
        self._tree.heading("facility", text="居宅")
        self._tree.heading("xlsx", text="xlsx パス")
        self._tree.heading("sheet", text="シート")
        self._tree.heading("target", text="出力 PDF パス")
        self._tree.column("name", width=110)
        self._tree.column("staff", width=70)
        self._tree.column("facility", width=140)
        self._tree.column("xlsx", width=260)
        self._tree.column("sheet", width=100)
        self._tree.column("target", width=260)
        self._tree.pack(side="left", fill="both", expand=True)

        scroll_y = ttk.Scrollbar(body, orient="vertical", command=self._tree.yview)
        scroll_y.pack(side="right", fill="y")
        self._tree.configure(yscrollcommand=scroll_y.set)

        for idx, r in enumerate(self._results):
            self._tree.insert(
                "",
                "end",
                iid=str(idx),
                values=(
                    r.row.name,
                    r.row.staff,
                    r.row.facility,
                    _path_or_blank(r.xlsx_path),
                    r.sheet_name or "",
                    _path_or_blank(r.target_pdf),
                ),
            )
        # デフォルト全選択（最初は全件 OK で確認しやすく、テスト時のみ絞る運用）
        self._tree.selection_set([str(i) for i in range(len(self._results))])
        self._tree.bind("<<TreeviewSelect>>", self._on_selection_change)

        # 選択補助 + 注意書き
        helper = ttk.Frame(top, padding=(8, 0))
        helper.pack(fill="x")
        ttk.Button(helper, text="全選択", command=self._on_select_all).pack(
            side="left", padx=2
        )
        ttk.Button(helper, text="全解除", command=self._on_select_none).pack(
            side="left", padx=2
        )
        self._sel_count_var = tk.StringVar(
            value=f"選択中: {len(self._results)} / {len(self._results)} 件"
        )
        ttk.Label(helper, textvariable=self._sel_count_var, foreground="#0a5").pack(
            side="left", padx=12
        )
        ttk.Label(
            helper,
            text="Ctrl/Shift + クリックで個別選択可。少数件でドライラン推奨。",
            foreground="#a06000",
        ).pack(side="left")

        # ボタン行
        bottom = ttk.Frame(top, padding=8)
        bottom.pack(fill="x")
        ttk.Label(
            bottom,
            text="※ 不正な path がある場合はキャンセルし、該当行をダブルクリックで再選択してください。",
            foreground="#a06000",
        ).pack(side="left")
        ttk.Button(bottom, text="キャンセル", command=self._on_cancel).pack(
            side="right", padx=4
        )
        # 実配置（破壊的）→ ドライラン（安全）の順で並べ、安全側を右端（OK 押下慣性ガード）
        ttk.Button(bottom, text="実配置を実行", command=self._on_real_run).pack(
            side="right", padx=4
        )
        ttk.Button(
            bottom, text="ドライラン（実書込なし）", command=self._on_dry_run
        ).pack(side="right", padx=4)

    def _on_selection_change(self, _event: object) -> None:
        n = len(self._tree.selection())
        total = len(self._results)
        self._sel_count_var.set(f"選択中: {n} / {total} 件")

    def _on_select_all(self) -> None:
        self._tree.selection_set([str(i) for i in range(len(self._results))])

    def _on_select_none(self) -> None:
        self._tree.selection_remove(self._tree.selection())

    def _capture_selection(self) -> bool:
        """現在の Treeview 選択を ``_selected_indices`` に保存。0 件なら False を返す。"""
        sel = self._tree.selection()
        self._selected_indices = sorted(int(iid) for iid in sel)
        return bool(self._selected_indices)

    def _on_dry_run(self) -> None:
        if not self._capture_selection():
            return
        self._proceed = True
        self._dry_run = True
        self._top.destroy()

    def _on_real_run(self) -> None:
        if not self._capture_selection():
            return
        self._proceed = True
        self._dry_run = False
        self._top.destroy()

    def _on_cancel(self) -> None:
        self._proceed = False
        self._dry_run = False
        self._selected_indices = []
        self._top.destroy()
