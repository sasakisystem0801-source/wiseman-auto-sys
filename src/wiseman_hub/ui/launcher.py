"""ランチャー GUI（3 ボタン構成、業務フロー順）。

アプリ起動時にユーザーが最初に見る画面。業務フロー順に 3 ボタンを提供する:
1. ex_ ファイル変換 + 振り分け（① 業務フロー起点、ADR-014）
2. 事業所フォルダ一括結合（③ 一括再結合、ADR-013）
3. 設定

設計方針:
- 全コールバックを DI で差替え可能（テスト容易性）
- PII（氏名・パス）は logger に出さない
- 旧ワークフロー UI 経路（PDF マージ処理 / 確認待ちセッション）は Issue #154 で
  除去。コード本体は ``pdf/pipeline.py`` / ``ui/session_picker.py`` 等に資産として
  残置（ADR-013 §既存単一事業所ダイアログの扱い 方針）。
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import enum
import logging
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import ttk

from wiseman_hub.config import AppConfig
from wiseman_hub.ui.common import (
    MessageBoxLike,
    assert_main_thread,
    default_messagebox,
    install_tk_exception_guard,
)

logger = logging.getLogger(__name__)


# Phase 2-α (Issue #238): GCP 同期サマリー表示の対象。
# 表示順は業務頻度 (mapping_routing > report_staff > sheets) に対応。
_SYNC_SUMMARY_ITEMS: tuple[tuple[str, str], ...] = (
    ("居宅対照表", "mapping_routing"),
    ("担当者マッピング", "report_staff"),
    ("シート一覧", "sheets"),
)


class LauncherAction(enum.Enum):
    """ランチャーの主要操作。"""

    OPEN_SETTINGS = "open_settings"
    OPEN_FACILITY_MERGER = "open_facility_merger"
    OPEN_EX_EXTRACTOR = "open_ex_extractor"
    OPEN_CHECKLIST_B = "open_checklist_b"
    OPEN_CHECKLIST_C = "open_checklist_c"


_BTN_OPEN_SETTINGS = "設定"
_BTN_OPEN_FACILITY_MERGER = "事業所フォルダ一括結合"
_BTN_OPEN_EX_EXTRACTOR = "ex_ ファイル変換 + 振り分け"
_BTN_OPEN_CHECKLIST_B = "B: 運動機能向上計画書 自動配置"
_BTN_OPEN_CHECKLIST_C = "C: 経過報告書 自動配置"

_TITLE_UNIMPL = "未実装"

_TITLE_SETTINGS_PLACEHOLDER = "設定画面（未実装）"
_MSG_SETTINGS_PLACEHOLDER = (
    "設定画面は後続タスクで実装予定です。\n"
    "現状は config/default.toml を直接編集してください。"
)

_TITLE_EX_EXTRACTOR_PLACEHOLDER = "ex_ ファイル変換（未統合）"
_MSG_EX_EXTRACTOR_PLACEHOLDER = (
    "ex_ ファイル変換 + 振り分けは PR4 で統合予定です。"
)

_MSG_FACILITY_MERGER_UNIMPL = "事業所フォルダ結合ダイアログ（未統合）"

_TITLE_CHECKLIST_B_PLACEHOLDER = "B 自動配置（未統合）"
_MSG_CHECKLIST_B_PLACEHOLDER = (
    "B 運動機能向上計画書の自動配置は次セッションで統合予定です。"
)
_TITLE_CHECKLIST_C_PLACEHOLDER = "C 自動配置（未統合）"
_MSG_CHECKLIST_C_PLACEHOLDER = (
    "C 経過報告書の自動配置は次セッションで統合予定です。"
)


class Launcher:
    """3 ボタン構成のメインランチャー GUI。

    コールバック省略時は既定のプレースホルダメッセージを表示する。
    Issue #154 で旧ワークフロー (Phase A / Phase B / 確認待ちセッション) の UI
    経路を除去。同期 callback のみで構成され、busy 状態管理 / executor は不要。
    """

    def __init__(
        self,
        config: AppConfig,
        config_path: Path,
        *,
        root: tk.Tk | None = None,
        on_open_settings: Callable[[], None] | None = None,
        on_open_facility_merger: Callable[[], None] | None = None,
        on_open_ex_extractor: Callable[[], None] | None = None,
        on_open_checklist_b: Callable[[], None] | None = None,
        on_open_checklist_c: Callable[[], None] | None = None,
        messagebox_fn: MessageBoxLike | None = None,
        now_fn: Callable[[], _dt.datetime] | None = None,
        defer_initial_refresh: bool = True,
    ) -> None:
        assert_main_thread("Launcher")

        self._config = config
        self._config_path = config_path
        self._messagebox = messagebox_fn or default_messagebox()
        # Phase 2-α (Issue #238): now の DI で sync_summary 表示をテスト容易化。
        self._now_fn: Callable[[], _dt.datetime] = now_fn or (
            lambda: _dt.datetime.now(tz=_dt.UTC)
        )
        # Phase 2-β (Issue #238 I-2): 起動時 cache I/O を Tk window 描画後に遅延
        # するためのフラグ。production default = True (after_idle で初回 refresh
        # を予約)、テストでは False を渡して deterministic な同期実行に切替。
        self._defer_initial_refresh = defer_initial_refresh
        # _build_sync_summary で初期化される (StringVar は Tk root 取得後でないと作れない)
        self._sync_vars: dict[str, tk.StringVar] = {}

        self._on_open_settings = on_open_settings
        self._on_open_facility_merger = on_open_facility_merger
        self._on_open_ex_extractor = on_open_ex_extractor
        self._on_open_checklist_b = on_open_checklist_b
        self._on_open_checklist_c = on_open_checklist_c

        self._owns_root = root is None
        self._root = root if root is not None else tk.Tk()
        install_tk_exception_guard(
            self._root, component="launcher", messagebox=self._messagebox
        )

        self._build_ui()

    def _build_ui(self) -> None:
        root = self._root
        root.title("Wiseman PDF ツール")
        # Phase 2-α (Issue #238): sync_summary フレーム分だけ縦幅を拡張。
        root.geometry("420x460")

        ttk.Label(
            root,
            text="Wiseman PDF ツール",
            font=("TkDefaultFont", 14, "bold"),
            padding=12,
        ).pack()

        # Phase 2-α (Issue #238): GCP 同期サマリー (3 行: 居宅対照表 / 担当者マッピング / シート一覧)
        self._build_sync_summary(root)

        btn_frame = ttk.Frame(root, padding=12)
        btn_frame.pack(fill="both", expand=True)

        # 業務フロー順: ex_ 変換 (①) → B/C 自動配置 → 事業所結合 (③) → 設定
        self._btn_ex_extractor = ttk.Button(
            btn_frame,
            text=_BTN_OPEN_EX_EXTRACTOR,
            command=lambda: self.invoke_action(LauncherAction.OPEN_EX_EXTRACTOR),
        )
        self._btn_checklist_b = ttk.Button(
            btn_frame,
            text=_BTN_OPEN_CHECKLIST_B,
            command=lambda: self.invoke_action(LauncherAction.OPEN_CHECKLIST_B),
        )
        self._btn_checklist_c = ttk.Button(
            btn_frame,
            text=_BTN_OPEN_CHECKLIST_C,
            command=lambda: self.invoke_action(LauncherAction.OPEN_CHECKLIST_C),
        )
        self._btn_facility_merger = ttk.Button(
            btn_frame,
            text=_BTN_OPEN_FACILITY_MERGER,
            command=lambda: self.invoke_action(
                LauncherAction.OPEN_FACILITY_MERGER
            ),
        )
        self._btn_settings = ttk.Button(
            btn_frame,
            text=_BTN_OPEN_SETTINGS,
            command=lambda: self.invoke_action(LauncherAction.OPEN_SETTINGS),
        )

        for btn in (
            self._btn_ex_extractor,
            self._btn_checklist_b,
            self._btn_checklist_c,
            self._btn_facility_merger,
            self._btn_settings,
        ):
            btn.pack(fill="x", pady=6, ipady=6)

    def button_labels(self) -> tuple[str, str, str, str, str]:
        """各ボタンのラベル（テスト用）。

        順序: ex_ 変換 / B 自動配置 / C 自動配置 / 事業所結合 / 設定。
        """
        return (
            _BTN_OPEN_EX_EXTRACTOR,
            _BTN_OPEN_CHECKLIST_B,
            _BTN_OPEN_CHECKLIST_C,
            _BTN_OPEN_FACILITY_MERGER,
            _BTN_OPEN_SETTINGS,
        )

    def reload_config(self, config: AppConfig) -> None:
        """設定 GUI で保存された直後に呼ぶ。Settings dialog 等が新値を反映するため。

        Phase 2-α (Issue #238): 設定保存と同時に GCP 同期 (push/pull) が走り得るので、
        sync_summary も再描画する。
        """
        self._config = config
        self._refresh_sync_summary()

    def _build_sync_summary(self, root: tk.Misc) -> None:
        """GCP 同期サマリー frame を構築する (Phase 2-α / Issue #238)。

        3 行の固定 layout (居宅対照表 / 担当者マッピング / シート一覧)、各行は
        ``StringVar`` で更新可能。初期値は「不明」 (Phase 1 ChecklistCDialog と
        統一、cache 不在 / parse 失敗 / tz naive すべて ``format_synced_at_label``
        の None 経路で「不明」に集約)。

        Phase 2-β (I-2): 起動時 cache I/O は ``self._defer_initial_refresh`` が
        True (production default) なら ``after_idle`` で window 描画完了後に
        遅延実行する。テストでは ``False`` で同期実行に切替。
        """
        frame = ttk.LabelFrame(
            root, text="GCP 同期サマリー", padding=8
        )
        frame.pack(fill="x", padx=12, pady=(0, 4))
        for label, key in _SYNC_SUMMARY_ITEMS:
            var = tk.StringVar(value=f"{label}: 不明")
            ttk.Label(frame, textvariable=var, anchor="w").pack(fill="x")
            self._sync_vars[key] = var
        if self._defer_initial_refresh:
            # Tk idle queue にキューイング (mainloop が初回 idle に入った時点で実行)
            self._root.after_idle(self._refresh_sync_summary)
        else:
            self._refresh_sync_summary()

    def _refresh_sync_summary(self) -> None:
        """sync_summary の各行を最新の cache 状態で再描画する (Phase 2-α / Issue #238)。

        本処理は Tk main thread 上の同期 I/O (3 ファイル分の JSON read) を伴うが、
        各 read は ``read_sync_timestamp`` / ``sheet_list_cache.load`` 内部で warn-only
        フォールバックされる。Launcher 起動時の体感遅延が問題になる場合は将来 daemon
        thread 化する余地あり (review_team I-2 rating 7、Phase 2-β 繰越判定)。

        review 反映 (evaluator AC-2): cache 不在 / parse 失敗 / tz naive のすべてを
        ``format_synced_at_label(None, now)`` 経由で「不明」表示に集約。Phase 1 の
        ChecklistCDialog (sheet_list_cache 直接呼出) との文言整合を取る。
        """
        if not self._sync_vars:
            return  # _build_sync_summary 完了前 (_build_ui 直前) に呼ばれた場合
        from wiseman_hub.cloud.sync_label import (
            format_synced_at_label,
            read_sync_timestamp,
            sync_cache_dir_for,
        )

        now = self._now_fn()
        sync_dir = sync_cache_dir_for(self._config_path)
        for prefix, key in _SYNC_SUMMARY_ITEMS:
            ts = (
                self._read_sheet_fetched_at()
                if key == "sheets"
                else read_sync_timestamp(sync_dir, key)
            )
            self._sync_vars[key].set(
                f"{prefix}: {format_synced_at_label(ts, now)}"
            )

    def _read_sheet_fetched_at(self) -> _dt.datetime | None:
        """sheet_list_cache から fetched_at を取得 (spreadsheet_id 未設定時は None)。"""
        from wiseman_hub.cloud.sheet_list_cache import (
            cache_dir_for as _sheet_cache_dir_for,
        )
        from wiseman_hub.cloud.sheet_list_cache import (
            load as _sheet_load,
        )

        spreadsheet_id = self._config.checklist.spreadsheet_id
        if not spreadsheet_id:
            return None
        cached = _sheet_load(_sheet_cache_dir_for(self._config_path), spreadsheet_id)
        return cached.fetched_at if cached is not None else None

    def get_root(self) -> tk.Tk:
        """子ダイアログ（SettingsDialog など）が ``tk.Toplevel(parent)`` で
        モーダル化するための親 widget を返す。"""
        return self._root

    def invoke_action(self, action: LauncherAction) -> None:
        """指定アクションのハンドラを実行する（ボタン押下と同等）。"""
        match action:
            case LauncherAction.OPEN_SETTINGS:
                self._invoke_or_show(
                    self._on_open_settings,
                    _TITLE_SETTINGS_PLACEHOLDER,
                    _MSG_SETTINGS_PLACEHOLDER,
                )
            case LauncherAction.OPEN_FACILITY_MERGER:
                self._invoke_or_show(
                    self._on_open_facility_merger,
                    _TITLE_UNIMPL,
                    _MSG_FACILITY_MERGER_UNIMPL,
                )
            case LauncherAction.OPEN_EX_EXTRACTOR:
                self._invoke_or_show(
                    self._on_open_ex_extractor,
                    _TITLE_EX_EXTRACTOR_PLACEHOLDER,
                    _MSG_EX_EXTRACTOR_PLACEHOLDER,
                )
            case LauncherAction.OPEN_CHECKLIST_B:
                self._invoke_or_show(
                    self._on_open_checklist_b,
                    _TITLE_CHECKLIST_B_PLACEHOLDER,
                    _MSG_CHECKLIST_B_PLACEHOLDER,
                )
            case LauncherAction.OPEN_CHECKLIST_C:
                self._invoke_or_show(
                    self._on_open_checklist_c,
                    _TITLE_CHECKLIST_C_PLACEHOLDER,
                    _MSG_CHECKLIST_C_PLACEHOLDER,
                )
            case _:
                raise ValueError(f"Unhandled LauncherAction: {action}")

    def run(self) -> None:
        """mainloop を起動する。"""
        try:
            self._root.mainloop()
        finally:
            if self._owns_root:
                with contextlib.suppress(tk.TclError):
                    self._root.destroy()

    def _invoke_or_show(
        self, callback: Callable[[], None] | None, title: str, message: str
    ) -> None:
        """コールバックが注入されていれば呼ぶ、なければ showinfo でプレースホルダ表示。"""
        if callback is not None:
            callback()
        else:
            self._messagebox.showinfo(title, message)
