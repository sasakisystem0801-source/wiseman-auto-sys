"""B (運動機能向上計画書/モニタリング) PDF 自動配置ダイアログ（MVP）。

スプレッドシートから月選択 → モニタリング日付ありの行抽出 → 居宅 → FAX 事業所
解決 → カルテから月別 PDF コピー → 配置。
"""

from __future__ import annotations

import datetime as _dt
import logging
import threading
import tkinter as tk
from collections.abc import Callable
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
from wiseman_hub.ui.common import open_folder_in_os, parse_sheet_name
from wiseman_hub.ui.sheet_list_binding import SheetListBinding

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

class ChecklistBDialog:
    """B 自動配置ダイアログ（Toplevel）。"""

    def __init__(
        self,
        parent: tk.Tk | tk.Toplevel | tk.Misc,
        config: AppConfig,
        config_path: Path | None = None,
        *,
        now_fn: Callable[[], _dt.datetime] | None = None,
    ) -> None:
        self._config = config
        self._config_path = config_path
        self._top = tk.Toplevel(parent)
        self._top.title("B: 運動機能向上計画書 自動配置")
        self._top.geometry("780x520")
        self._top.transient(parent)  # type: ignore[arg-type]
        self._top.grab_set()

        self._results: list[PlacementResult] = []
        # PR (sheet-list-binding): cache hit 経路で xlsx_bytes が「シート一覧更新」を
        # 介さず空のまま _on_load_rows に到達するため、空 bytes で明示初期化する
        # (C ダイアログと同じ pattern、cache populate 後の透過 download で埋まる)。
        self._xlsx_bytes: bytes = b""
        # PR (sheet-list-binding): C ダイアログと同じ helper を共有してシート一覧 cache
        # の populate/save/sync_label 表示を統一する。spreadsheet_id は config 再読込で
        # 変わり得るため毎呼出で問合せ。
        # Evaluator MEDIUM 指摘対応: now_fn を DI 可能にして launcher と対称化
        # (テスト時の時刻 freeze で sync label の文言検証を deterministic 化)。
        self._sheet_binding = SheetListBinding(
            self._config_path,
            lambda: self._config.checklist.spreadsheet_id,
            now_fn=now_fn,
        )
        self._build_ui()
        # 起動時に cache から sheet 一覧を populate (C ダイアログと feature parity)。
        self._try_load_sheet_cache()

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
        # PR (sheet-list-binding): C ダイアログに合わせて文言を「シート一覧更新」に。
        # cache 起動 populate があるため「取得」から「更新」へ意味も変わる。
        ttk.Button(head, text="シート一覧更新", command=self._on_load_sheets).pack(
            side="left", padx=4
        )
        ttk.Button(head, text="対象行を読込", command=self._on_load_rows).pack(
            side="left", padx=4
        )
        ttk.Button(head, text="設定...", command=self._on_open_settings).pack(
            side="right", padx=4
        )

        # PR (sheet-list-binding): C ダイアログ Issue #238 Phase 1 と同じ位置・同じ文言で
        # 「シート一覧 最終更新: ...」を表示し、業務責任者が両ダイアログ間で同じ動線で
        # 鮮度を確認できるようにする。
        sync_info = ttk.Frame(top, padding=(8, 0, 8, 4))
        sync_info.pack(fill="x")
        self._sync_info_var = tk.StringVar(value="シート一覧 最終更新: 不明")
        ttk.Label(
            sync_info, textvariable=self._sync_info_var, foreground="#555"
        ).pack(side="left")

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

        # 設定変更前の spreadsheet_id を記憶しておく (Codex HIGH 指摘対応:
        # spreadsheet_id 変更時のみ状態リセットが必要、無変更なら _xlsx_bytes など
        # を捨てる必要なし)。
        prev_spreadsheet_id = self._config.checklist.spreadsheet_id
        dlg = ChecklistSettingsDialog(
            parent=self._top, config=self._config, config_path=self._config_path
        )
        dlg.get_toplevel().wait_window()
        if dlg.saved():
            try:
                self._config = load_config(self._config_path)
            except (OSError, ValueError, TypeError) as exc:
                messagebox.showerror(
                    "設定再読込失敗",
                    f"{type(exc).__name__}",
                    parent=self._top,
                )
                return
            # Codex HIGH 指摘: spreadsheet_id が変わった場合、cache hit で残っている
            # 旧 spreadsheet の sheet 名 / xlsx_bytes / results を新設定で使うと
            # 業務影響 (旧 spreadsheet の xlsx を新月で処理) が発生する。明示的に
            # リセット + 新 spreadsheet の cache から再 populate する。
            if self._config.checklist.spreadsheet_id != prev_spreadsheet_id:
                self._reset_after_spreadsheet_change()
                self._status_var.set(
                    "設定を再読込しました (スプレッドシート変更を検知 → 再 populate)"
                )
            else:
                self._status_var.set("設定を再読込しました")

    def _reset_after_spreadsheet_change(self) -> None:
        """spreadsheet_id 変更後に旧 spreadsheet の在状態を一掃して再 populate する。

        Codex HIGH 指摘対応: cache hit 経路で旧 spreadsheet の月名が month_combo に
        残っていると、ユーザーが「対象行を読込」を押すたびに `_xlsx_bytes`
        (旧 spreadsheet のもの) + 新 spreadsheet の cache 月名で誤処理する。
        """
        self._xlsx_bytes = b""
        self._month_combo["values"] = ()
        self._month_var.set("")
        self._results = []
        for item in self._tree.get_children():
            self._tree.delete(item)
        self._exec_btn.configure(state="disabled")
        # 新 spreadsheet の cache から再 populate (cache miss なら combo は空のまま)
        self._try_load_sheet_cache()
        # sync info を新 spreadsheet 基準で再描画 (cache hit なら fetched_at、
        # cache miss なら「不明」表示に切り替わる)
        self._refresh_sync_info()

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
                self._safe_after(lambda: self._on_sheets_loaded(xlsx, names))
            except Exception as exc:  # noqa: BLE001 (UI top-level: 詳細は logger 経由)
                logger.exception("Drive API xlsx download failed")
                err_type = type(exc).__name__
                self._safe_after(lambda: self._on_load_error(err_type))

        threading.Thread(target=_bg, daemon=True).start()

    def _on_sheets_loaded(self, xlsx_bytes: bytes, sheet_names: list[str]) -> None:
        self._xlsx_bytes = xlsx_bytes
        self._month_combo["values"] = sheet_names
        if sheet_names:
            self._month_combo.current(len(sheet_names) - 1)
        self._status_var.set(f"シート一覧取得完了 ({len(sheet_names)} シート)")
        # PR (sheet-list-binding): 次回起動時に即時 populate できるよう永続化 + sync
        # label を「たった今」相当で再描画 (C ダイアログ PR-δ v1 と同じ動作)。
        self._sheet_binding.save_after_fetch(sheet_names)
        self._refresh_sync_info()

    def _on_load_error(self, err_type: str) -> None:
        self._status_var.set(f"取得失敗: {err_type}")
        # PR (sheet-list-binding): 既存 cache の fetched_at は残しつつ「※更新失敗」を
        # 併記 (C ダイアログ Issue #238 review HIGH-1 と同じ挙動)。
        self._refresh_sync_info_with_error(err_type)
        messagebox.showerror("読込エラー", f"スプレッドシート読込に失敗: {err_type}")

    def _try_load_sheet_cache(self) -> None:
        """起動時に cache から sheet_names を populate (C ダイアログと同じ挙動)。

        cache miss / config_path 未指定 / spreadsheet_id 未設定 時は no-op。
        xlsx_bytes は cache していないため空のまま。「対象行を読込」時に必要なら
        ``_on_load_rows`` の既存フローで透過 download される (本ダイアログでも
        将来追加可能、現状は「シート一覧更新」を押すまで xlsx_bytes 空のまま)。
        """
        hit_count = self._sheet_binding.populate_combo_on_open(self._month_combo)
        if hit_count > 0:
            self._status_var.set(
                f"シート一覧 (キャッシュ {hit_count} 件) - 最新化は「シート一覧更新」"
            )
            self._refresh_sync_info()

    def _refresh_sync_info(self) -> None:
        """sync info label を最新の cache.fetched_at で再描画。"""
        self._sync_info_var.set(self._sheet_binding.format_sync_label())

    def _refresh_sync_info_with_error(self, err_type: str) -> None:
        """背景更新失敗時に「※更新失敗」を併記。"""
        self._sync_info_var.set(
            self._sheet_binding.format_sync_label_with_error(err_type)
        )

    def _on_load_rows(self) -> None:
        sheet = self._month_var.get()
        if not sheet:
            messagebox.showinfo("月未選択", "対象月を選択してください")
            return
        ym = parse_sheet_name(sheet)
        if ym is None:
            messagebox.showerror("シート名形式不正", f"対応外: {sheet}")
            return
        _, month = ym
        # cache hit で combo は埋まっているが xlsx_bytes が未取得な場合、ここで
        # 透過 download する。Codex Medium 指摘対応: UI thread の同期 I/O は Tk を
        # フリーズさせるため、background thread + after(0,...) で UI thread に
        # 戻すパターン (_on_load_sheets と同じ) に統一。
        if not self._xlsx_bytes:
            cfg = self._config.checklist
            if not cfg.spreadsheet_id:
                messagebox.showerror(
                    "設定不足", "設定でスプレッドシートIDを登録してください"
                )
                return
            self._fetch_xlsx_then_process(sheet, month)
            return
        self._process_rows(sheet, month)

    def _fetch_xlsx_then_process(self, sheet: str, month: int) -> None:
        """透過 download を background thread で実行、完了後に _process_rows に継続。

        - silent-failure C-2 対応: download 失敗時に sync_info に「※更新失敗」を
          併記し、業務責任者が「キャッシュは最新」と誤認するのを防ぐ。
        - Codex Medium 対応: download 中もユーザーがダイアログを閉じられるように
          background 化。
        """
        self._status_var.set("xlsx をダウンロード中（初回 / キャッシュ後）...")
        self._top.update_idletasks()
        spreadsheet_id = self._config.checklist.spreadsheet_id

        def _bg() -> None:
            try:
                xlsx = download_xlsx(self._config.gcp, spreadsheet_id)
                self._safe_after(
                    lambda: self._on_transparent_download_done(xlsx, sheet, month)
                )
            except Exception as exc:  # noqa: BLE001 (UI top-level: 各エラー型は logger に残す)
                err_type = type(exc).__name__
                logger.exception("transparent xlsx download failed")
                self._safe_after(
                    lambda: self._on_transparent_download_failed(err_type)
                )

        threading.Thread(target=_bg, daemon=True).start()

    def _safe_after(self, fn: Callable[[], None]) -> None:
        """winfo_exists ガード付きの after(0, fn).

        Codex Medium 指摘対応: ダイアログ destroy 後に worker thread から after()
        を呼ぶと TclError、または callback 内で破棄済 widget アクセスで例外。
        launcher の after_idle race-guard と対称化。
        """
        def _safe_call() -> None:
            try:
                if not self._top.winfo_exists():
                    return
            except tk.TclError:
                return
            fn()

        try:
            if not self._top.winfo_exists():
                return
        except tk.TclError:
            return
        self._top.after(0, _safe_call)

    def _on_transparent_download_done(
        self, xlsx: bytes, sheet: str, month: int
    ) -> None:
        self._xlsx_bytes = xlsx
        self._process_rows(sheet, month)

    def _on_transparent_download_failed(self, err_type: str) -> None:
        self._status_var.set(f"ダウンロード失敗: {err_type}")
        # silent-failure C-2: sync_info に「※更新失敗」を併記して、業務責任者が
        # 「キャッシュは最新」と誤認するのを防ぐ (_on_load_sheets 失敗時と同等扱い)。
        self._refresh_sync_info_with_error(err_type)
        messagebox.showerror(
            "ダウンロード失敗",
            f"スプレッドシート読込に失敗: {err_type}",
        )

    def _process_rows(self, sheet: str, month: int) -> None:
        """xlsx_bytes 取得済の状態で parse → plan → Treeview 反映。"""
        try:
            rows = parse_sheet(self._xlsx_bytes, sheet)
        except Exception as exc:  # noqa: BLE001 (UI top-level: 詳細は logger 経由)
            logger.exception("parse_sheet failed")
            messagebox.showerror("解析失敗", type(exc).__name__)
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
        open_folder_in_os(folder)

    def _on_execute(self) -> None:
        if not messagebox.askyesno("実行確認", "PENDING 状態の行を配置します。続行しますか？"):
            return
        self._exec_btn.configure(state="disabled")
        self._status_var.set("配置中...")
        self._top.update_idletasks()

        def _bg() -> None:
            execute_placement(self._results)
            self._safe_after(self._on_execute_done)

        threading.Thread(target=_bg, daemon=True).start()

    def _on_execute_done(self) -> None:
        self._refresh_tree()
        success = sum(1 for r in self._results if r.status == PlacementStatus.SUCCESS)
        self._status_var.set(f"配置完了: 成功 {success} 件")
        self._exec_btn.configure(state="disabled")
