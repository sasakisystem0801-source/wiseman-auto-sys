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

from wiseman_hub.cloud.sheet_list_cache import (
    cache_dir_for as _sheet_cache_dir_for,
)
from wiseman_hub.cloud.sheet_list_cache import (
    load as _load_sheet_cache,
)
from wiseman_hub.cloud.sheet_list_cache import (
    save as _save_sheet_cache,
)
from wiseman_hub.cloud.sheets import (
    download_xlsx,
    list_sheet_names,
    parse_sheet,
    select_c_rows,
)
from wiseman_hub.cloud.xlsx_path_cache_mirror import (
    delete_entry_async as _mirror_delete_entry_async,
)
from wiseman_hub.cloud.xlsx_path_cache_mirror import (
    upload_entry_async as _mirror_upload_entry_async,
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
from wiseman_hub.ui.common import count_by_status, make_treeview_sortable
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

# サマリーラベル用の短縮形（status bar の幅制限内に複数件数を並べるため）
_STATUS_SHORT_LABEL: dict[CPlacementStatus, str] = {
    CPlacementStatus.PENDING: "実行待ち",
    CPlacementStatus.SUCCESS: "成功",
    CPlacementStatus.NEEDS_REVIEW: "要レビュー",
    CPlacementStatus.SKIPPED_NO_FACILITY: "⚠居宅未登録",
    CPlacementStatus.SKIPPED_NO_STAFF: "⚠担当者未登録",
    CPlacementStatus.SKIPPED_NO_XLSX: "⚠xlsx不在",
    CPlacementStatus.SKIPPED_NO_SHEET: "⚠シート未発見",
    CPlacementStatus.SKIPPED_AMBIGUOUS_SHEET: "⚠シート候補複数",
    CPlacementStatus.ERROR: "✗エラー",
}

# サマリー表示順（業務優先度: 残作業 → エラー系 → 完了）
_STATUS_SUMMARY_ORDER: list[str] = [
    "実行待ち",
    "要レビュー",
    "⚠居宅未登録",
    "⚠担当者未登録",
    "⚠xlsx不在",
    "⚠シート未発見",
    "⚠シート候補複数",
    "✗エラー",
    "成功",
]

# Treeview ステータス列 sort 用の優先度（業務優先度: 要対応が上、完了が下）
_STATUS_SORT_PRIORITY: dict[str, int] = {
    "▶ 要レビュー（ダブルクリックで選択）": 0,
    "⚠ 居宅マッピング未登録": 10,
    "⚠ 担当者マッピング未登録": 11,
    "⚠ xlsx 不在": 12,
    "⚠ 利用者シート未発見": 13,
    "⚠ シート候補複数": 14,
    "✗ エラー": 20,
    "実行待ち": 30,
    "成功": 90,
}


def _status_column_sort_key(cell: str) -> tuple[int, str]:
    """ステータス列の Treeview 表示文字列を業務優先度順に並べる sort key。"""
    return (_STATUS_SORT_PRIORITY.get(cell, 99), cell)

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
        # PR-δ v1: 起動時にローカル cache からシート一覧を即時 populate
        # （Drive API クリック必須だった UX を解消）
        self._try_load_sheet_cache()

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
        # PR-δ v1: 名称を「更新」に変更（cache からの初期 populate あり）
        ttk.Button(head, text="シート一覧更新", command=self._on_load_sheets).pack(
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
        # 右クリックメニュー: 誤投入された xlsx_path_cache を 1 クリックで削除
        # （PowerShell + notepad で TOML 直接編集していた業務責任者負担の解消）
        self._tree.bind("<Button-3>", self._on_row_right_click)
        # macOS では右クリックが Button-2 になる環境があるためフォールバック
        self._tree.bind("<Button-2>", self._on_row_right_click)

        # ヘッダークリックで sort（ステータス列のみ業務優先度順、他は文字列順）
        make_treeview_sortable(
            self._tree,
            cols,
            key_funcs={"status": _status_column_sort_key},
        )

        bottom = ttk.Frame(top, padding=8)
        bottom.pack(fill="x")
        self._status_var = tk.StringVar(value="対象月を選んで「対象行を読込」してください")
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
        # PR-δ v1: 次回起動時に即時 populate できるよう cache に永続化
        if self._config_path is not None:
            cache_dir = _sheet_cache_dir_for(self._config_path)
            _save_sheet_cache(
                cache_dir, self._config.checklist.spreadsheet_id, sheet_names
            )

    def _try_load_sheet_cache(self) -> None:
        """起動時に cache から sheet_names を populate（cache hit 時のみ）。

        cache miss / config_path 未指定 / spreadsheet_id 未設定 時は no-op。
        xlsx_bytes は cache していないため空のまま。「対象行を読込」時に
        必要なら自動 download される（_on_load_rows のフロー）。
        """
        if self._config_path is None:
            return
        spreadsheet_id = self._config.checklist.spreadsheet_id
        if not spreadsheet_id:
            return
        cache_dir = _sheet_cache_dir_for(self._config_path)
        cached = _load_sheet_cache(cache_dir, spreadsheet_id)
        if cached:
            self._month_combo["values"] = cached
            if cached:
                self._month_combo.current(len(cached) - 1)
            self._status_var.set(
                f"シート一覧 (キャッシュ {len(cached)} 件) - 最新化は「シート一覧更新」"
            )

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
        # PR-δ v1: cache hit で combo は埋まっているが xlsx_bytes が未取得な場合、
        # ここで透過的に download（業務責任者は「シート一覧更新」を意識せずに
        # 即「対象行を読込」できる）
        if not self._xlsx_bytes:
            self._status_var.set("xlsx をダウンロード中（初回 / キャッシュ後）...")
            self._top.update_idletasks()
            try:
                self._xlsx_bytes = download_xlsx(
                    self._config.gcp, self._config.checklist.spreadsheet_id
                )
            except Exception as exc:
                err_type = type(exc).__name__
                messagebox.showerror("ダウンロード失敗", f"{err_type}: {exc}")
                self._status_var.set(f"ダウンロード失敗: {err_type}")
                return
        try:
            rows = parse_sheet(self._xlsx_bytes, sheet)
        except Exception as exc:
            messagebox.showerror("解析失敗", f"{type(exc).__name__}: {exc}")
            return
        c_rows = select_c_rows(rows)
        self._results = plan_c_placement(c_rows, self._config.checklist, year, month)
        self._refresh_tree()
        ready = sum(1 for r in self._results if r.status == CPlacementStatus.PENDING)
        # ステータス別件数を集計してサマリー表示（0 件は省略、業務優先度順）
        counts = count_by_status(
            self._results,
            lambda r: _STATUS_SHORT_LABEL.get(r.status, r.status.value),
        )
        self._status_var.set(
            counts.to_summary_text(ordered_labels=_STATUS_SUMMARY_ORDER)
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

    def _on_row_right_click(self, event: object) -> None:
        """右クリックでコンテキストメニュー表示。誤投入 cache の 1 クリック undo 用。"""
        # クリック位置の行を選択状態に切り替え（普通の Tk Treeview の慣習）
        try:
            row_id = self._tree.identify_row(event.y)  # type: ignore[attr-defined]
        except (AttributeError, tk.TclError):
            return
        if not row_id:
            return
        self._tree.selection_set(row_id)
        idx = int(row_id)
        r = self._results[idx]

        # cache key が解決できない（年月未取得 / 担当者未登録）行はメニュー無効
        year, month = self._current_year_month()
        has_cache_entry = (
            year is not None
            and month is not None
            and r.row.staff
            and cache_key(r.row.staff, year, month) in self._config.checklist.xlsx_path_cache
        )

        menu = tk.Menu(self._top, tearoff=False)
        menu.add_command(
            label="キャッシュをクリア（要レビューに戻す）",
            command=lambda: self._clear_cache_for_row(idx),
            state="normal" if has_cache_entry else "disabled",
        )
        try:
            menu.tk_popup(event.x_root, event.y_root)  # type: ignore[attr-defined]
        finally:
            menu.grab_release()

    def _clear_cache_for_row(self, idx: int) -> None:
        """選択行の (staff, year, month) cache を削除し、行を再 plan して NEEDS_REVIEW に戻す。"""
        if idx < 0 or idx >= len(self._results):
            return
        r = self._results[idx]
        year, month = self._current_year_month()
        if year is None or month is None:
            return
        key = cache_key(r.row.staff, year, month)
        cache = self._config.checklist.xlsx_path_cache
        if key not in cache:
            return
        # 削除確認（誤クリック保護）
        confirm = messagebox.askyesno(
            "キャッシュ削除確認",
            f"{r.row.staff} の {year}年{month}月 キャッシュを削除しますか？\n"
            f"パス: {cache[key]}\n\n"
            f"削除後、対象行は ▶ 要レビュー に戻り再選択が必要になります。",
            parent=self._top,
        )
        if not confirm:
            return
        del cache[key]
        # 永続化
        save_ok = False
        if self._config_path is not None:
            try:
                save_config(self._config, self._config_path)
                save_ok = True
            except OSError as exc:
                logger.warning("save_config failed after cache clear: %s", type(exc).__name__)
                messagebox.showwarning(
                    "キャッシュ削除済（永続化失敗）",
                    f"メモリ上の cache は削除しましたが TOML 保存に失敗: {type(exc).__name__}",
                    parent=self._top,
                )
        # ADR-016 PR-2: GCS に tombstone を mirror（warn-only、UI に messagebox 出さない）
        # save_config 成功時のみ mirror（TOML と GCS のズレを最小化）
        # C-1 (codex review threadId 019dfceb): daemon thread で非同期化、UI を blocking しない
        if save_ok and self._config_path is not None:
            try:
                _mirror_delete_entry_async(
                    key,
                    self._config.gcp,
                    config_path=self._config_path,
                )
            except Exception:  # noqa: BLE001  (warn-only, never block UI)
                logger.warning(
                    "xlsx_path_cache mirror delete async spawn failed (non-fatal)"
                )
        # 当該行を再 plan して NEEDS_REVIEW に戻す
        new_results = plan_c_placement(
            [r.row], self._config.checklist, year, month
        )
        if new_results:
            self._results[idx] = new_results[0]
        self._refresh_tree()
        self._update_status_summary()
        self._status_var.set(
            f"{r.row.staff} {year}年{month}月: キャッシュ削除 → 要レビュー"
        )

    def _update_status_summary(self) -> None:
        """ステータスバーをサマリー集計で更新（_on_load_rows と同じ表示）。"""
        counts = count_by_status(
            self._results,
            lambda r: _STATUS_SHORT_LABEL.get(r.status, r.status.value),
        )
        self._status_var.set(
            counts.to_summary_text(ordered_labels=_STATUS_SUMMARY_ORDER)
        )
        ready = sum(1 for r in self._results if r.status == CPlacementStatus.PENDING)
        self._exec_btn.configure(state="normal" if ready > 0 else "disabled")

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
        year, month = self._current_year_month()
        picker = XlsxPickerDialog(
            parent=self._top,
            candidates=r.xlsx_candidates,
            folder_tree=r.folder_tree,
            title_context=title_context,
            target_year=year,
            target_month=month,
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
                save_ok = False
                try:
                    save_config(self._config, self._config_path)
                    save_ok = True
                except OSError as exc:
                    logger.warning("save_config failed: %s", type(exc).__name__)
                    messagebox.showwarning(
                        "キャッシュ保存失敗",
                        f"選択は反映しますが永続化に失敗: {type(exc).__name__}",
                        parent=self._top,
                    )
                # ADR-016 PR-2: GCS への mirror（warn-only、UI に messagebox 出さない）
                # save_config 成功時のみ mirror（TOML 永続化失敗時は GCS とのズレを
                # 残さないため skip）
                # C-1 (codex review threadId 019dfceb): daemon thread で非同期化、UI freeze 回避
                if save_ok:
                    try:
                        _mirror_upload_entry_async(
                            key,
                            str(selected),
                            self._config.gcp,
                            config_path=self._config_path,
                        )
                    except Exception:  # noqa: BLE001  (warn-only, never block UI)
                        logger.warning(
                            "xlsx_path_cache mirror upload async spawn failed (non-fatal)"
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
        # PR-ζ v1: 行選択 + dry-run / 実配置 2 ボタン化
        confirm = PlacementConfirmDialog(parent=self._top, pending_results=pending)
        confirm.get_toplevel().wait_window()
        if not confirm.get_proceed():
            self._status_var.set("配置キャンセル")
            return
        dry_run = confirm.get_dry_run()
        # selected_indices は PENDING 抽出後の pending list 内 index
        selected_pending = [
            pending[i] for i in confirm.get_selected_indices() if 0 <= i < len(pending)
        ]
        if not selected_pending:
            self._status_var.set("選択行なし、配置中止")
            return
        self._exec_btn.configure(state="disabled")
        if dry_run:
            self._status_var.set(
                f"ドライラン中... ({len(selected_pending)} 件、実書込なし)"
            )
        else:
            self._status_var.set(
                f"Excel 経由で PDF 化中... ({len(selected_pending)} 件)"
            )
        self._top.update_idletasks()

        def _bg() -> None:
            error_message: str | None = None
            try:
                # dry_run 時は exporter を生成しない（COM 起動コストも 0）
                exporter = None if dry_run else create_exporter()
                # 選択行のみを execute_c_placement に渡す。
                # `results` パラメータが list を受けるので、渡す行だけ実行される
                # （PENDING 以外の行はスキップされる既存仕様）。
                execute_c_placement(
                    selected_pending,
                    exporter,
                    log_dir=self._config.log_dir,
                    dry_run=dry_run,
                )
            except Exception as exc:  # noqa: BLE001  (broad ok: UI top-level guard)
                logger.exception("execute_c_placement failed")
                # Evaluator 指摘 (LOW): 例外時に「N 件 OK」と誤表示しないよう
                # error_message を保存して UI 側で表示分岐
                error_message = f"{type(exc).__name__}: {exc}"
            self._top.after(
                0,
                lambda: self._on_execute_done(
                    dry_run, len(selected_pending), error_message
                ),
            )

        threading.Thread(target=_bg, daemon=True).start()

    def _on_execute_done(
        self, dry_run: bool, target_count: int, error_message: str | None = None
    ) -> None:
        self._refresh_tree()
        if error_message is not None:
            # _bg() で execute_c_placement が例外を投げた場合の分岐
            self._status_var.set(
                f"{'ドライラン' if dry_run else '配置'}失敗: {error_message}"
            )
            messagebox.showerror(
                f"{'ドライラン' if dry_run else '配置'}失敗",
                f"{error_message}\n\n詳細はログを確認してください。",
                parent=self._top,
            )
            # 失敗時も exec_btn を回復させ再試行可能に（PENDING 行が残っているため）
            ready = sum(
                1 for r in self._results if r.status == CPlacementStatus.PENDING
            )
            self._exec_btn.configure(state="normal" if ready > 0 else "disabled")
            return
        if dry_run:
            self._status_var.set(
                f"ドライラン完了: {target_count} 件のパス検証 OK（PDF 未書込、再実行可）"
            )
            # ドライラン後は実配置に進めるよう exec ボタンを再有効化
            ready = sum(
                1 for r in self._results if r.status == CPlacementStatus.PENDING
            )
            self._exec_btn.configure(state="normal" if ready > 0 else "disabled")
        else:
            success = sum(
                1 for r in self._results if r.status == CPlacementStatus.SUCCESS
            )
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
