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
    ) -> None:
        assert_main_thread("Launcher")

        self._config = config
        self._config_path = config_path
        self._messagebox = messagebox_fn or default_messagebox()

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
        root.geometry("420x380")

        ttk.Label(
            root,
            text="Wiseman PDF ツール",
            font=("TkDefaultFont", 14, "bold"),
            padding=12,
        ).pack()

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
        """設定 GUI で保存された直後に呼ぶ。Settings dialog 等が新値を反映するため。"""
        self._config = config

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
