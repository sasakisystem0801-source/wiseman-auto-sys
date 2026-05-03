"""C (経過報告書) PDF 自動配置ダイアログ（MVP）。

スプレッドシートから月選択 → 担当者ありの行抽出 → 担当者→ xlsx パス解決 →
xlsx の利用者シートを 1 ページ目だけ PDF 化 → FAX 事業所配下に配置。
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
    select_c_rows,
)
from wiseman_hub.config import AppConfig, save_config
from wiseman_hub.pdf.checklist_c import (
    CPlacementResult,
    CPlacementStatus,
    apply_xlsx_selection,
    cache_key,
    execute_c_placement,
    plan_c_placement,
)
from wiseman_hub.pdf.excel_com import create_exporter
from wiseman_hub.ui.placement_confirm_dialog import PlacementConfirmDialog
from wiseman_hub.ui.xlsx_picker_dialog import XlsxPickerDialog

logger = logging.getLogger(__name__)


_STATUS_LABEL: dict[CPlacementStatus, str] = {
    CPlacementStatus.PENDING: "実行待ち",
    CPlacementStatus.SUCCESS: "成功",
    CPlacementStatus.NEEDS_REVIEW: "▶ 要レビュー（ダブルクリックで選択）",
    CPlacementStatus.SKIPPED_NO_FACILITY: "⚠ 居宅マッピング未登録",
    CPlacementStatus.SKIPPED_NO_STAFF: "⚠ 担当者マッピング未登録",
    CPlacementStatus.SKIPPED_NO_XLSX: "⚠ xlsx 不在",
    CPlacementStatus.SKIPPED_NO_SHEET: "⚠ 利用者シート未発見",
    CPlacementStatus.SKIPPED_AMBIGUOUS_SHEET: "⚠ シート候補複数",
    CPlacementStatus.ERROR: "✗ エラー",
}

_SHEET_NAME_RE = re.compile(r"^(\d{2})年(\d{1,2})月$")


def _sheet_name_to_year_month(name: str) -> tuple[int, int] | None:
    m = _SHEET_NAME_RE.match(name)
    if not m:
        return None
    return (2000 + int(m.group(1)), int(m.group(2)))


class ChecklistCDialog:
    """C 自動配置ダイアログ（Toplevel）。"""

    def __init__(
        self, parent: tk.Tk | tk.Toplevel | tk.Misc, config: AppConfig, config_path: Path | None = None
    ) -> None:
        self._config = config
        self._config_path = config_path
        self._top = tk.Toplevel(parent)
        self._top.title("C: 経過報告書 自動配置")
        self._top.geometry("780x520")
        self._top.transient(parent)  # type: ignore[arg-type]
        self._top.grab_set()

        self._results: list[CPlacementResult] = []
        self._xlsx_bytes: bytes = b""
        self._build_ui()

    def get_toplevel(self) -> tk.Toplevel:
        return self._top

    def _build_ui(self) -> None:
        top = self._top
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
        self._tree.column("message", width=240)
        self._tree.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(mid, orient="vertical", command=self._tree.yview)
        scroll.pack(side="right", fill="y")
        self._tree.configure(yscrollcommand=scroll.set)
        self._tree.bind("<Double-1>", self._on_row_double_click)

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
        year, month = ym
        try:
            rows = parse_sheet(self._xlsx_bytes, sheet)
        except Exception as exc:
            messagebox.showerror("解析失敗", f"{type(exc).__name__}: {exc}")
            return
        c_rows = select_c_rows(rows)
        self._results = plan_c_placement(c_rows, self._config.checklist, year, month)
        self._refresh_tree()
        ready = sum(1 for r in self._results if r.status == CPlacementStatus.PENDING)
        self._status_var.set(f"対象 {len(self._results)} 件 / 実行可能 {ready} 件")
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
        # NEEDS_REVIEW 行は xlsx 選択モーダルを開く
        if r.status == CPlacementStatus.NEEDS_REVIEW:
            self._open_picker_for_review(idx, r)
            return
        # それ以外（PENDING/SUCCESS 等）は対象フォルダを開く
        target = r.target_pdf or r.xlsx_path
        if target is None:
            return
        folder = target.parent
        if not folder.exists():
            messagebox.showinfo("フォルダ未作成", str(folder))
            return
        _open_folder(folder)

    def _open_picker_for_review(self, idx: int, r: CPlacementResult) -> None:
        """NEEDS_REVIEW 行のレビュー UI を開き、選択結果を CPlacementResult に反映する。"""
        title_context = (
            f"{r.row.staff} / {r.row.name} / {r.row.facility}"
        )
        picker = XlsxPickerDialog(
            parent=self._top,
            candidates=r.xlsx_candidates,
            folder_tree=r.folder_tree,
            title_context=title_context,
        )
        picker.get_toplevel().wait_window()
        selected, remember = picker.get_result()
        if selected is None:
            self._status_var.set("選択キャンセル")
            return

        # 先に result を選択 xlsx で再評価（in-place）してから cache 判断
        # 重要: シート未発見等で SKIPPED になった選択は cache に残してはいけない
        # （次回 cache hit で誤った xlsx を自動使用するリスク防止 / Codex review HIGH-1）
        apply_xlsx_selection(r, selected, self._config.checklist)
        self._refresh_tree()
        self._update_exec_button()

        # cache 永続化は status=PENDING（シート検査も通った）場合のみ
        if (
            remember
            and r.status == CPlacementStatus.PENDING
            and self._config_path is not None
        ):
            year, month = self._current_year_month()
            if year is not None and month is not None:
                key = cache_key(r.row.staff, year, month)
                self._config.checklist.xlsx_path_cache[key] = str(selected)
                try:
                    save_config(self._config, self._config_path)
                except OSError as exc:
                    logger.warning("save_config failed: %s", type(exc).__name__)
                    messagebox.showwarning(
                        "キャッシュ保存失敗",
                        f"選択は反映しますが永続化に失敗: {type(exc).__name__}",
                        parent=self._top,
                    )

        if r.status == CPlacementStatus.PENDING:
            self._status_var.set(f"{r.row.name}: 選択完了 → 実行待ち")
        else:
            self._status_var.set(f"{r.row.name}: {_STATUS_LABEL.get(r.status, r.status.value)}")

    def _current_year_month(self) -> tuple[int | None, int | None]:
        """現在選択中の対象月から (year, month) を取り出す（cache_key 用）。"""
        sheet = self._month_var.get()
        ym = _sheet_name_to_year_month(sheet)
        if ym is None:
            return None, None
        return ym

    def _update_exec_button(self) -> None:
        ready = sum(1 for r in self._results if r.status == CPlacementStatus.PENDING)
        total = len(self._results)
        self._status_var.set(f"対象 {total} 件 / 実行可能 {ready} 件")
        self._exec_btn.configure(state="normal" if ready > 0 else "disabled")

    def _on_execute(self) -> None:
        # PENDING 行を抽出して詳細確認
        pending = [r for r in self._results if r.status == CPlacementStatus.PENDING]
        if not pending:
            messagebox.showinfo("対象なし", "実行可能な行がありません")
            return
        # 配置前確認: 全件を Treeview で提示（HIGH-3 対策、業務安全性）
        confirm = PlacementConfirmDialog(parent=self._top, pending_results=pending)
        confirm.get_toplevel().wait_window()
        if not confirm.get_proceed():
            self._status_var.set("配置キャンセル")
            return
        self._exec_btn.configure(state="disabled")
        self._status_var.set("Excel 経由で PDF 化中...")
        self._top.update_idletasks()

        def _bg() -> None:
            try:
                exporter = create_exporter()
                execute_c_placement(
                    self._results, exporter, log_dir=self._config.log_dir
                )
            except Exception:
                logger.exception("execute_c_placement failed")
            self._top.after(0, self._on_execute_done)

        threading.Thread(target=_bg, daemon=True).start()

    def _on_execute_done(self) -> None:
        self._refresh_tree()
        success = sum(1 for r in self._results if r.status == CPlacementStatus.SUCCESS)
        self._status_var.set(f"配置完了: 成功 {success} 件")
        self._exec_btn.configure(state="disabled")


def _open_folder(folder: Path) -> None:
    try:
        if sys.platform == "win32":
            subprocess.run(["explorer", str(folder)], check=False)
        elif sys.platform == "darwin":
            subprocess.run(["open", str(folder)], check=False)
        else:
            subprocess.run(["xdg-open", str(folder)], check=False)
    except OSError:
        logger.exception("Failed to open folder")
