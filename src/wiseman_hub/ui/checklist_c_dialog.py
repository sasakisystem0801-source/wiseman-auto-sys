"""C (経過報告書) PDF 自動配置ダイアログ（MVP）。

スプレッドシートから月選択 → 担当者ありの行抽出 → 担当者→ xlsx パス解決 →
xlsx の利用者シートを 1 ページ目だけ PDF 化 → FAX 事業所配下に配置。
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
from wiseman_hub.ui.common import (
    count_by_status,
    make_treeview_sortable,
    open_folder_in_os,
    parse_sheet_name,
)
from wiseman_hub.ui.placement_confirm_dialog import PlacementConfirmDialog
from wiseman_hub.ui.sheet_list_binding import SheetListBinding
from wiseman_hub.ui.xlsx_picker_dialog import XlsxPickerDialog

logger = logging.getLogger(__name__)


_STATUS_LABEL: dict[CPlacementStatus, str] = {
    CPlacementStatus.PENDING: "実行待ち",
    CPlacementStatus.SUCCESS: "成功",
    CPlacementStatus.NEEDS_REVIEW: "▶ 要レビュー（ダブルクリックで選択）",
    CPlacementStatus.NEEDS_REVIEW_STAFF: "▶ 担当者を選択（ダブルクリック）",
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
    CPlacementStatus.NEEDS_REVIEW_STAFF: "担当者選択",
    CPlacementStatus.SKIPPED_NO_FACILITY: "⚠居宅未登録",
    CPlacementStatus.SKIPPED_NO_STAFF: "⚠担当者未登録",
    CPlacementStatus.SKIPPED_NO_XLSX: "⚠xlsx不在",
    CPlacementStatus.SKIPPED_NO_SHEET: "⚠シート未発見",
    CPlacementStatus.SKIPPED_AMBIGUOUS_SHEET: "⚠シート候補複数",
    CPlacementStatus.ERROR: "✗エラー",
}

# サマリー表示順（業務優先度: 残作業 → エラー系 → 完了）
# NEEDS_REVIEW_STAFF は xlsx レビューより前段の人間判断のため「要レビュー」より上。
_STATUS_SUMMARY_ORDER: list[str] = [
    "実行待ち",
    "担当者選択",
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
    "▶ 担当者を選択（ダブルクリック）": 0,
    "▶ 要レビュー（ダブルクリックで選択）": 1,
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


def _format_xlsx_cell(r: CPlacementResult) -> str:
    """Treeview の xlsx 列表示を行ステータスと候補件数から組み立てる。

    Issue #315: NEEDS_REVIEW 行で xlsx_path=None のため列が常に空欄になり、
    業務責任者が「読込直後にどの行がほぼ確定／要確認／候補ゼロか」を
    判別できなかった。配置確認モーダルを開かずに状態を一望できるよう、
    候補件数を列に出す。

    - xlsx_path 確定済（PENDING / SUCCESS 等）: basename
    - NEEDS_REVIEW で候補 1 件: basename（人間が中身確認するだけで済む状態）
    - NEEDS_REVIEW で候補 N 件 (N>=2): "(N 件候補)"
    - NEEDS_REVIEW で候補なし: "(候補なし)"
    - NEEDS_REVIEW_STAFF (Issue #314): "(担当者 N 名)" / 部分 hit は
      "(担当者 N 名 / 未登録あり)" — staff 確定後に xlsx 解決が走るため
      xlsx 列では人数情報のみを表示し、未登録の有無で警戒を可視化する
    - SKIPPED 系: 空
    """
    if r.xlsx_path is not None:
        return r.xlsx_path.name
    if r.status == CPlacementStatus.NEEDS_REVIEW:
        n = len(r.xlsx_candidates)
        if n == 1:
            return r.xlsx_candidates[0].name
        if n >= 2:
            return f"({n} 件候補)"
        return "(候補なし)"
    if r.status == CPlacementStatus.NEEDS_REVIEW_STAFF:
        n = len(r.staff_candidates)
        # 部分 hit (一部の担当者がマッピング未登録) は message にマーカーを残して
        # _format_xlsx_cell 側で検出する。message 文言は plan_c_placement が
        # "(未登録あり)" を必ず含める契約。
        if "未登録あり" in r.message:
            return f"(担当者 {n} 名 / 未登録あり)"
        return f"(担当者 {n} 名)"
    return ""


class ChecklistCDialog:
    """C 自動配置ダイアログ（Toplevel）。"""

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
        self._top.title("C: 経過報告書 自動配置")
        self._top.geometry("780x520")
        self._top.transient(parent)  # type: ignore[arg-type]
        self._top.grab_set()

        self._results: list[CPlacementResult] = []
        self._xlsx_bytes: bytes = b""
        # PR (sheet-list-binding): sheet_list_cache の load/save/sync-label を helper に集約。
        # spreadsheet_id は config 再読込で変わり得るので毎呼出で問合せ。
        # Evaluator MEDIUM 指摘対応: now_fn を DI 可能にして B/launcher と対称化。
        self._sheet_binding = SheetListBinding(
            self._config_path,
            lambda: self._config.checklist.spreadsheet_id,
            now_fn=now_fn,
        )
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

        # Issue #238 Phase 1: シート一覧キャッシュの最終同期日時を表示。
        # head 直下に専用 frame を置くことで「対象月選択 → 鮮度確認」の動線を可視化。
        sync_info = ttk.Frame(top, padding=(8, 0, 8, 4))
        sync_info.pack(fill="x")
        self._sync_info_var = tk.StringVar(value="シート一覧 最終更新: 不明")
        ttk.Label(
            sync_info, textvariable=self._sync_info_var, foreground="#555"
        ).pack(side="left")

        mid = ttk.Frame(top, padding=8)
        mid.pack(fill="both", expand=True)
        # PR (xlsx-column): 「xlsx」列を staff の隣に追加。cache hit / 手動選択完了の
        # どちらの経路でも PENDING 行で「どのファイルを使うのか」を一目で確認可能にする。
        # フルパスは UNC を含む長文 + PII 漏洩懸念があるため basename のみ表示
        # (フルパスは Treeview 行ダブルクリック → 親フォルダを explorer で開く既存挙動)。
        cols = ("name", "facility", "staff", "xlsx", "status", "message")
        self._tree = ttk.Treeview(mid, columns=cols, show="headings", height=14)
        self._tree.heading("name", text="氏名")
        self._tree.heading("facility", text="居宅")
        self._tree.heading("staff", text="担当")
        self._tree.heading("xlsx", text="xlsx")
        self._tree.heading("status", text="ステータス")
        self._tree.heading("message", text="詳細")
        self._tree.column("name", width=140)
        self._tree.column("facility", width=160)
        self._tree.column("staff", width=60)
        # xlsx 列は basename 表示なので 220 で大半の業務ファイル名が収まる。
        self._tree.column("xlsx", width=220, stretch=False)
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

        # 設定変更前の spreadsheet_id を記憶 (Codex HIGH 指摘対応: spreadsheet_id
        # 変更時のみ状態リセットが必要、無変更なら _xlsx_bytes / results を捨てない)。
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
            # spreadsheet_id 変更時のみ旧状態を一掃 (Codex HIGH 指摘対応)。
            # 旧 spreadsheet の xlsx_bytes / sheet 名で新 spreadsheet の月別行を
            # 処理する誤動作を防ぐ。
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
        残っていると、ユーザーが「対象行を読込」を押すたびに ``_xlsx_bytes``
        (旧 spreadsheet のもの) + 新 spreadsheet の cache 月名で誤処理する。
        """
        self._xlsx_bytes = b""
        self._month_combo["values"] = ()
        self._month_var.set("")
        self._results = []
        for item in self._tree.get_children():
            self._tree.delete(item)
        self._exec_btn.configure(state="disabled")
        self._try_load_sheet_cache()
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
        # PR-δ v1: 次回起動時に即時 populate できるよう cache に永続化
        # PR (sheet-list-binding): helper 経由に統一 (config_path/spreadsheet_id
        # の None ガードは helper 側に集約)。
        self._sheet_binding.save_after_fetch(sheet_names)
        # Issue #238 Phase 1: 取得直後の sync info を「たった今」相当で表示。
        # cache から再 load して fetched_at を反映 (save 内の now と同じ値が読める)。
        self._refresh_sync_info()

    def _try_load_sheet_cache(self) -> None:
        """起動時に cache から sheet_names を populate（cache hit 時のみ）。

        cache miss / config_path 未指定 / spreadsheet_id 未設定 時は no-op。
        xlsx_bytes は cache していないため空のまま。「対象行を読込」時に
        必要なら自動 download される（_on_load_rows のフロー）。

        Issue #238 Phase 1: cache hit 時に ``fetched_at`` を sync info label に反映。
        PR (sheet-list-binding): cache_dir 算出 / load 呼出を helper に委譲。
        """
        hit_count = self._sheet_binding.populate_combo_on_open(self._month_combo)
        if hit_count > 0:
            self._status_var.set(
                f"シート一覧 (キャッシュ {hit_count} 件) - 最新化は「シート一覧更新」"
            )
            self._refresh_sync_info()

    def _refresh_sync_info(self) -> None:
        """sync info label を最新の cache.fetched_at で再描画 (Issue #238 Phase 1)。

        config_path / spreadsheet_id 未設定や cache miss 時は「不明」表示。
        UI thread から呼ぶこと (Tk variable 更新は main thread 限定)。
        PR (sheet-list-binding): 文字列組立は helper の format_sync_label に委譲。
        """
        self._sync_info_var.set(self._sheet_binding.format_sync_label())

    def _refresh_sync_info_with_error(self, err_type: str) -> None:
        """背景更新失敗時に sync_info に「※更新失敗」を併記 (review HIGH-1)。

        既存 cache の fetched_at は捨てずに表示、末尾に失敗マーカーを足すことで
        「いつの cache か」「最新化に失敗している」の両方をユーザーに伝える。
        PR (sheet-list-binding): helper の format_sync_label_with_error に委譲。
        """
        self._sync_info_var.set(
            self._sheet_binding.format_sync_label_with_error(err_type)
        )

    def _on_load_error(self, err_type: str) -> None:
        self._status_var.set(f"取得失敗: {err_type}")
        # Issue #238 Phase 1 review HIGH-1: background 更新失敗時に sync_info が
        # 古いまま据え置かれると、ユーザーは「最新化されている」と誤認する。
        # 既存の cache fetched_at は維持しつつ、失敗マーカーを併記して可視化。
        self._refresh_sync_info_with_error(err_type)
        messagebox.showerror("読込エラー", f"スプレッドシート読込に失敗: {err_type}")

    def _on_load_rows(self) -> None:
        sheet = self._month_var.get()
        if not sheet:
            messagebox.showinfo("月未選択", "対象月を選択してください")
            return
        ym = parse_sheet_name(sheet)
        if ym is None:
            messagebox.showerror("シート名形式不正", f"対応外: {sheet}")
            return
        year, month = ym
        # cache hit で combo は埋まっているが xlsx_bytes が未取得な場合、ここで
        # 透過 download する。Codex Medium 指摘対応: UI thread の同期 I/O は Tk を
        # フリーズさせるため、background + after(0,...) で UI thread に戻す。
        if not self._xlsx_bytes:
            if not self._config.checklist.spreadsheet_id:
                messagebox.showerror(
                    "設定不足", "設定でスプレッドシートIDを登録してください"
                )
                return
            self._fetch_xlsx_then_process(sheet, year, month)
            return
        self._process_rows(sheet, year, month)

    def _fetch_xlsx_then_process(self, sheet: str, year: int, month: int) -> None:
        """透過 download を background thread で実行、完了後に _process_rows に継続。

        silent-failure C-2 対応: download 失敗時に sync_info に「※更新失敗」を併記し、
        業務責任者が「キャッシュは最新」と誤認するのを防ぐ。
        """
        self._status_var.set("xlsx をダウンロード中（初回 / キャッシュ後）...")
        self._top.update_idletasks()
        spreadsheet_id = self._config.checklist.spreadsheet_id

        def _bg() -> None:
            try:
                xlsx = download_xlsx(self._config.gcp, spreadsheet_id)
                self._safe_after(
                    lambda: self._on_transparent_download_done(
                        xlsx, sheet, year, month
                    )
                )
            except Exception as exc:  # noqa: BLE001 (UI top-level: 詳細は logger 経由)
                err_type = type(exc).__name__
                logger.exception("transparent xlsx download failed")
                self._safe_after(
                    lambda: self._on_transparent_download_failed(err_type)
                )

        threading.Thread(target=_bg, daemon=True).start()

    def _safe_after(self, fn: Callable[[], None]) -> None:
        """worker thread から UI thread に callback を安全に投げる helper。

        Tk 仕様で worker thread から widget メソッド (``winfo_exists`` 等) を呼ぶと
        ``RuntimeError: main thread is not in main loop`` になるため、scheduling 側
        では try/except (``tk.TclError`` / ``RuntimeError``) のみ。実際の
        ``winfo_exists`` 検査は callback 内 (main thread) で行う。
        launcher の after_idle race-guard と対称化 (Codex Medium 指摘対応)。
        """
        def _safe_call() -> None:
            try:
                if not self._top.winfo_exists():
                    return
            except tk.TclError:
                return
            fn()

        try:
            self._top.after(0, _safe_call)
        except (tk.TclError, RuntimeError):
            # ダイアログ既に destroy / Tk main loop 終了済 → 諦める
            return

    def _on_transparent_download_done(
        self, xlsx: bytes, sheet: str, year: int, month: int
    ) -> None:
        self._xlsx_bytes = xlsx
        self._process_rows(sheet, year, month)

    def _on_transparent_download_failed(self, err_type: str) -> None:
        self._status_var.set(f"ダウンロード失敗: {err_type}")
        # silent-failure C-2: sync_info に「※更新失敗」を併記して、業務責任者が
        # 「キャッシュは最新」と誤認するのを防ぐ。
        self._refresh_sync_info_with_error(err_type)
        messagebox.showerror(
            "ダウンロード失敗",
            f"スプレッドシート読込に失敗: {err_type}",
        )

    def _process_rows(self, sheet: str, year: int, month: int) -> None:
        """xlsx_bytes 取得済の状態で parse → plan → Treeview 反映。"""
        try:
            rows = parse_sheet(self._xlsx_bytes, sheet)
        except Exception as exc:  # noqa: BLE001 (UI top-level: 詳細は logger 経由)
            logger.exception("parse_sheet failed")
            messagebox.showerror("解析失敗", type(exc).__name__)
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
            xlsx_label = _format_xlsx_cell(r)
            self._tree.insert(
                "",
                "end",
                iid=str(idx),
                values=(
                    r.row.name,
                    r.row.facility,
                    r.row.staff,
                    xlsx_label,
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
        open_folder_in_os(folder)

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
        ym = parse_sheet_name(sheet)
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
            self._safe_after(
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
