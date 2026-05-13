"""B (運動機能向上計画書/モニタリング) PDF 自動配置ダイアログ（MVP）。

スプレッドシートから月選択 → モニタリング日付ありの行抽出 → 居宅 → FAX 事業所
解決 → カルテから月別 PDF コピー → 配置。
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from wiseman_hub.cloud.sheets import (
    download_xlsx,
    list_sheet_names,
    parse_sheet,
    select_b_rows,
)
from wiseman_hub.config import AppConfig
from wiseman_hub.pdf.checklist_b import (
    PlacementResult,
    PlacementStatus,
    execute_placement,
    plan_b_placement,
)

logger = logging.getLogger(__name__)


_STATUS_LABEL: dict[PlacementStatus, str] = {
    PlacementStatus.PENDING: "実行待ち",
    PlacementStatus.SUCCESS: "成功",
    PlacementStatus.SKIPPED_NO_FACILITY: "⚠ 居宅マッピング未登録",
    PlacementStatus.SKIPPED_NO_USER_DIR: "⚠ 利用者フォルダ未発見",
    PlacementStatus.SKIPPED_NO_PDF: "⚠ 月別 PDF 不在",
    PlacementStatus.SKIPPED_AMBIGUOUS: "⚠ 候補複数（手動選択）",
    PlacementStatus.ERROR: "✗ エラー",
}

_SHEET_NAME_RE = re.compile(r"^(\d{2})年(\d{1,2})月$")


def _sheet_name_to_year_month(name: str) -> tuple[int, int] | None:
    """``26年4月`` → ``(2026, 4)``。マッチしなければ None。"""
    m = _SHEET_NAME_RE.match(name)
    if not m:
        return None
    yy = int(m.group(1))
    month = int(m.group(2))
    return (2000 + yy, month)


class ChecklistBDialog:
    """B 自動配置ダイアログ（Toplevel）。"""

    def __init__(
        self, parent: tk.Tk | tk.Toplevel | tk.Misc, config: AppConfig, config_path: Path | None = None
    ) -> None:
        self._config = config
        self._config_path = config_path
        self._top = tk.Toplevel(parent)
        self._top.title("B: 運動機能向上計画書 自動配置")
        self._top.geometry("780x520")
        self._top.transient(parent)  # type: ignore[arg-type]
        self._top.grab_set()

        self._results: list[PlacementResult] = []
        self._build_ui()

    def get_toplevel(self) -> tk.Toplevel:
        return self._top

    def _build_ui(self) -> None:
        top = self._top
        # 上段: 月選択 + 読込
        head = ttk.Frame(top, padding=8)
        head.pack(fill="x")
        ttk.Label(head, text="対象月:").pack(side="left")
        self._month_var = tk.StringVar()
        self._month_combo = ttk.Combobox(
            head, textvariable=self._month_var, state="readonly", width=12
        )
        self._month_combo.pack(side="left", padx=4)
        ttk.Button(head, text="シート一覧取得", command=self._on_load_sheets).pack(
            side="left", padx=4
        )
        ttk.Button(head, text="対象行を読込", command=self._on_load_rows).pack(
            side="left", padx=4
        )
        ttk.Button(head, text="設定...", command=self._on_open_settings).pack(
            side="right", padx=4
        )

        # 中段: 結果テーブル
        mid = ttk.Frame(top, padding=8)
        mid.pack(fill="both", expand=True)
        cols = ("name", "facility", "staff", "status", "message")
        self._tree = ttk.Treeview(mid, columns=cols, show="headings", height=14)
        self._tree.heading("name", text="氏名")
        self._tree.heading("facility", text="居宅")
        self._tree.heading("staff", text="担当")
        self._tree.heading("status", text="ステータス")
        self._tree.heading("message", text="詳細")
        self._tree.column("name", width=140)
        self._tree.column("facility", width=160)
        self._tree.column("staff", width=60)
        self._tree.column("status", width=160)
        # Issue #274 Phase 1: 詳細列を 240 → 500 に拡大、stretch=True で残幅も吸収。
        # UNC パス + 業務メッセージ (例: ``PDF 不在: \\Tera-station\share\...``) が
        # 1 行で読めるようにする。横スクロールバーで全文確認可能。
        self._tree.column("message", width=500, minwidth=240, stretch=True)
        # Issue #274 Phase 1: 横スクロールバーを下端に追加。pack の order が
        # 重要 (先に pack されたものから残スペースを占有) なので
        # hscroll(bottom) → vscroll(right) → tree(left, expand) の順。
        hscroll = ttk.Scrollbar(mid, orient="horizontal", command=self._tree.xview)
        hscroll.pack(side="bottom", fill="x")
        vscroll = ttk.Scrollbar(mid, orient="vertical", command=self._tree.yview)
        vscroll.pack(side="right", fill="y")
        self._tree.pack(side="left", fill="both", expand=True)
        self._tree.configure(
            yscrollcommand=vscroll.set, xscrollcommand=hscroll.set
        )
        self._tree.bind("<Double-1>", self._on_row_double_click)

        # 下段: ステータス + 実行/閉じる
        bottom = ttk.Frame(top, padding=8)
        bottom.pack(fill="x")
        self._status_var = tk.StringVar(value="シート一覧取得から開始してください")
        ttk.Label(bottom, textvariable=self._status_var).pack(side="left")
        ttk.Button(bottom, text="閉じる", command=self._top.destroy).pack(side="right")
        self._exec_btn = ttk.Button(
            bottom, text="配置を実行", command=self._on_execute, state="disabled"
        )
        self._exec_btn.pack(side="right", padx=4)

    def _on_open_settings(self) -> None:
        if self._config_path is None:
            messagebox.showinfo(
                "設定編集不可",
                "config_path が未指定のためダイアログから編集できません",
                parent=self._top,
            )
            return
        from wiseman_hub.config import load_config
        from wiseman_hub.ui.checklist_settings_dialog import (
            ChecklistSettingsDialog,
        )

        dlg = ChecklistSettingsDialog(
            parent=self._top, config=self._config, config_path=self._config_path
        )
        dlg.get_toplevel().wait_window()
        if dlg.saved():
            try:
                self._config = load_config(self._config_path)
                self._status_var.set("設定を再読込しました")
            except (OSError, ValueError, TypeError) as exc:
                messagebox.showerror(
                    "設定再読込失敗",
                    f"{type(exc).__name__}",
                    parent=self._top,
                )

    def _on_load_sheets(self) -> None:
        cfg = self._config.checklist
        if not cfg.spreadsheet_id:
            messagebox.showerror("設定不足", "設定でスプレッドシートIDを登録してください")
            return
        self._status_var.set("Drive API から xlsx をダウンロード中...")
        self._top.update_idletasks()

        def _bg() -> None:
            try:
                xlsx = download_xlsx(self._config.gcp, cfg.spreadsheet_id)
                names = list_sheet_names(xlsx)
                self._top.after(0, lambda: self._on_sheets_loaded(xlsx, names))
            except Exception as exc:
                err_type = type(exc).__name__
                self._top.after(0, lambda: self._on_load_error(err_type))

        threading.Thread(target=_bg, daemon=True).start()

    def _on_sheets_loaded(self, xlsx_bytes: bytes, sheet_names: list[str]) -> None:
        self._xlsx_bytes = xlsx_bytes
        self._month_combo["values"] = sheet_names
        if sheet_names:
            self._month_combo.current(len(sheet_names) - 1)
        self._status_var.set(f"シート一覧取得完了 ({len(sheet_names)} シート)")

    def _on_load_error(self, err_type: str) -> None:
        self._status_var.set(f"取得失敗: {err_type}")
        messagebox.showerror("読込エラー", f"スプレッドシート読込に失敗: {err_type}")

    def _on_load_rows(self) -> None:
        sheet = self._month_var.get()
        if not sheet:
            messagebox.showinfo("月未選択", "対象月を選択してください")
            return
        ym = _sheet_name_to_year_month(sheet)
        if ym is None:
            messagebox.showerror("シート名形式不正", f"対応外: {sheet}")
            return
        _, month = ym
        try:
            rows = parse_sheet(self._xlsx_bytes, sheet)
        except Exception as exc:
            messagebox.showerror("解析失敗", f"{type(exc).__name__}: {exc}")
            return
        b_rows = select_b_rows(rows)
        self._results = plan_b_placement(b_rows, self._config.checklist, month)
        self._refresh_tree()
        ready = sum(1 for r in self._results if r.status == PlacementStatus.PENDING)
        self._status_var.set(
            f"対象 {len(self._results)} 件 / 実行可能 {ready} 件"
        )
        self._exec_btn.configure(state="normal" if ready > 0 else "disabled")

    def _refresh_tree(self) -> None:
        for item in self._tree.get_children():
            self._tree.delete(item)
        for idx, r in enumerate(self._results):
            self._tree.insert(
                "",
                "end",
                iid=str(idx),
                values=(
                    r.row.name,
                    r.row.facility,
                    r.row.staff,
                    _STATUS_LABEL.get(r.status, r.status.value),
                    r.message,
                ),
            )

    def _on_row_double_click(self, _event: object) -> None:
        sel = self._tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        r = self._results[idx]
        # 親フォルダを開く（target_pdf があればその親、なければ source PDF の親）
        target = r.target_pdf or r.source_pdf
        if target is None:
            return
        folder = target.parent
        if not folder.exists():
            messagebox.showinfo("フォルダ未作成", str(folder))
            return
        _open_folder(folder)

    def _on_execute(self) -> None:
        if not messagebox.askyesno("実行確認", "PENDING 状態の行を配置します。続行しますか？"):
            return
        self._exec_btn.configure(state="disabled")
        self._status_var.set("配置中...")
        self._top.update_idletasks()

        def _bg() -> None:
            execute_placement(self._results)
            self._top.after(0, self._on_execute_done)

        threading.Thread(target=_bg, daemon=True).start()

    def _on_execute_done(self) -> None:
        self._refresh_tree()
        success = sum(1 for r in self._results if r.status == PlacementStatus.SUCCESS)
        self._status_var.set(f"配置完了: 成功 {success} 件")
        self._exec_btn.configure(state="disabled")


def _open_folder(folder: Path) -> None:
    """OS のファイルマネージャでフォルダを開く（best-effort）。"""
    try:
        if sys.platform == "win32":
            subprocess.run(["explorer", str(folder)], check=False)
        elif sys.platform == "darwin":
            subprocess.run(["open", str(folder)], check=False)
        else:
            subprocess.run(["xdg-open", str(folder)], check=False)
    except OSError:
        logger.exception("Failed to open folder")
