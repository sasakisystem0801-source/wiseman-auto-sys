"""配置前確認ダイアログ（C 経過報告書配置のリリースゲート）。

Codex review HIGH-3 対策: 既存の messagebox.askyesno + 5 件サンプル表示では
6 件目以降の誤 cache / 誤出力が業務責任者に見えないため、Treeview で全件
（name / staff / xlsx_path / sheet_name / target_pdf）を提示してから OK 判定する。

設計判断:
    - スクロール可能な Treeview で件数に依存しない確認 UX
    - 列幅は xlsx_path / target_pdf を広めにして path 確認を最優先
    - cancel = 配置中止、OK = 続行
    - PII（利用者氏名・パス）はモーダル内のみで完結、外部送信なし

戻り値:
    ``proceed: bool``
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

        self._top = tk.Toplevel(parent)
        self._top.title(f"配置前確認: {len(self._results)} 件")
        self._top.geometry("960x500")
        if hasattr(parent, "winfo_toplevel"):
            self._top.transient(parent.winfo_toplevel())
        self._top.grab_set()

        self._build_ui()

    def get_toplevel(self) -> tk.Toplevel:
        return self._top

    def get_proceed(self) -> bool:
        return self._proceed

    def _build_ui(self) -> None:
        top = self._top

        head = ttk.Frame(top, padding=8)
        head.pack(fill="x")
        ttk.Label(
            head,
            text=(
                f"PENDING {len(self._results)} 件を配置します。"
                "全件の対象 xlsx と出力 PDF パスを確認してください。"
            ),
        ).pack(side="left")

        body = ttk.Frame(top, padding=8)
        body.pack(fill="both", expand=True)

        cols = ("name", "staff", "facility", "xlsx", "sheet", "target")
        tree = ttk.Treeview(body, columns=cols, show="headings", height=15)
        tree.heading("name", text="氏名")
        tree.heading("staff", text="担当")
        tree.heading("facility", text="居宅")
        tree.heading("xlsx", text="xlsx パス")
        tree.heading("sheet", text="シート")
        tree.heading("target", text="出力 PDF パス")
        tree.column("name", width=110)
        tree.column("staff", width=70)
        tree.column("facility", width=140)
        tree.column("xlsx", width=260)
        tree.column("sheet", width=100)
        tree.column("target", width=260)
        tree.pack(side="left", fill="both", expand=True)

        scroll_y = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
        scroll_y.pack(side="right", fill="y")
        tree.configure(yscrollcommand=scroll_y.set)

        for r in self._results:
            tree.insert(
                "",
                "end",
                values=(
                    r.row.name,
                    r.row.staff,
                    r.row.facility,
                    _path_or_blank(r.xlsx_path),
                    r.sheet_name or "",
                    _path_or_blank(r.target_pdf),
                ),
            )

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
        ttk.Button(bottom, text="配置を実行", command=self._on_ok).pack(
            side="right", padx=4
        )

    def _on_ok(self) -> None:
        self._proceed = True
        self._top.destroy()

    def _on_cancel(self) -> None:
        self._proceed = False
        self._top.destroy()
