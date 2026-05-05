"""C ダイアログの右クリック「キャッシュをクリア」機能のユニットテスト。

PR-ε v2 で導入した「誤投入 cache の 1 クリック undo」の検証。
業務責任者が PowerShell + notepad で直接 TOML 編集していた負担を解消する。

主な検証点:
    - 削除対象 cache key の解決ロジック (staff, year, month の組合せ)
    - 削除実行で cache から消える + save_config が呼ばれる
    - 削除後に対象行が NEEDS_REVIEW に戻る
    - 削除確認 messagebox で No 選択時は何もしない
    - cache 未登録の行で右クリックしてもメニューが disabled
    - 年月未選択 (sheet 未読込) の場合もメニュー無効
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from unittest.mock import patch

import pytest

from wiseman_hub.config import (
    AppConfig,
    ChecklistConfig,
    GcpConfig,
    ReportStaffEntry,
    WisemanConfig,
)
from wiseman_hub.pdf.checklist_c import (
    ChecklistRow,
    CPlacementResult,
    CPlacementStatus,
    cache_key,
)
from wiseman_hub.ui.checklist_c_dialog import ChecklistCDialog


def _make_config(tmp_path: Path) -> AppConfig:
    """テスト用最小 AppConfig (in-memory cache 1 件入り)。"""
    cfg = AppConfig(
        wiseman=WisemanConfig(),
        gcp=GcpConfig(),
        checklist=ChecklistConfig(
            spreadsheet_id="dummy",
            fax_root=str(tmp_path),
            facility_routing={"テスト居宅": "テスト居宅(FAX)"},
            report_staff={
                "宮下": ReportStaffEntry(
                    base_dir=str(tmp_path / "PT 宮下"),
                    suggest_patterns=["dummy"],
                ),
            },
            xlsx_path_cache={"宮下:2026:3": r"\\nas\share\PT 宮下\3月.xlsx"},
        ),
        log_dir=str(tmp_path / "logs"),
    )
    return cfg


@pytest.mark.tk_required
class TestCacheClearMenu:
    """右クリックメニューの構造的動作確認。"""

    def _make_dialog(
        self, root: tk.Tk, tmp_path: Path
    ) -> tuple[ChecklistCDialog, AppConfig]:
        cfg = _make_config(tmp_path)
        cfg_path = tmp_path / "default.toml"
        cfg_path.write_text(
            '[checklist]\nfax_root = ""\n', encoding="utf-8"
        )
        dlg = ChecklistCDialog(parent=root, config=cfg, config_path=cfg_path)
        # 月選択を埋めておく (cache_key 解決に必要)
        dlg._month_var.set("26年3月")
        # 1 行 PENDING 状態を仕込む (cache hit 済みの想定)
        row = ChecklistRow(name="テスト太郎", facility="テスト居宅", staff="宮下")
        result = CPlacementResult(row=row)
        result.status = CPlacementStatus.PENDING
        result.xlsx_path = Path(r"\\nas\share\PT 宮下\3月.xlsx")
        result.target_pdf = tmp_path / "テスト居宅(FAX)" / "テスト太郎.pdf"
        dlg._results = [result]
        dlg._refresh_tree()
        return dlg, cfg

    def test_clear_cache_removes_entry_and_saves(self, tmp_path: Path) -> None:
        root = tk.Tk()
        try:
            dlg, cfg = self._make_dialog(root, tmp_path)
            assert "宮下:2026:3" in cfg.checklist.xlsx_path_cache
            with patch(
                "wiseman_hub.ui.checklist_c_dialog.messagebox.askyesno",
                return_value=True,
            ), patch(
                "wiseman_hub.ui.checklist_c_dialog.save_config"
            ) as mock_save:
                dlg._clear_cache_for_row(0)
            assert "宮下:2026:3" not in cfg.checklist.xlsx_path_cache
            mock_save.assert_called_once()
            # 行が NEEDS_REVIEW （またはそれに近い未確定状態）に戻ること
            new_status = dlg._results[0].status
            assert new_status != CPlacementStatus.PENDING
        finally:
            root.destroy()

    def test_clear_cache_user_cancels_keeps_entry(self, tmp_path: Path) -> None:
        """確認 messagebox で No → cache 削除しない。"""
        root = tk.Tk()
        try:
            dlg, cfg = self._make_dialog(root, tmp_path)
            with patch(
                "wiseman_hub.ui.checklist_c_dialog.messagebox.askyesno",
                return_value=False,
            ), patch(
                "wiseman_hub.ui.checklist_c_dialog.save_config"
            ) as mock_save:
                dlg._clear_cache_for_row(0)
            # cache はそのまま残る、save_config も呼ばれない
            assert "宮下:2026:3" in cfg.checklist.xlsx_path_cache
            mock_save.assert_not_called()
        finally:
            root.destroy()

    def test_clear_cache_no_entry_is_noop(self, tmp_path: Path) -> None:
        """cache に該当 key がなければ何もしない (askyesno も呼ばれない)。"""
        root = tk.Tk()
        try:
            dlg, cfg = self._make_dialog(root, tmp_path)
            cfg.checklist.xlsx_path_cache.clear()
            with patch(
                "wiseman_hub.ui.checklist_c_dialog.messagebox.askyesno"
            ) as mock_msg, patch(
                "wiseman_hub.ui.checklist_c_dialog.save_config"
            ) as mock_save:
                dlg._clear_cache_for_row(0)
            mock_msg.assert_not_called()
            mock_save.assert_not_called()
        finally:
            root.destroy()

    def test_clear_cache_no_year_month_is_noop(self, tmp_path: Path) -> None:
        """月未選択時 (year, month が None) は何もしない。"""
        root = tk.Tk()
        try:
            dlg, cfg = self._make_dialog(root, tmp_path)
            dlg._month_var.set("")
            with patch(
                "wiseman_hub.ui.checklist_c_dialog.messagebox.askyesno"
            ) as mock_msg:
                dlg._clear_cache_for_row(0)
            mock_msg.assert_not_called()
            # cache は変更されていない
            assert "宮下:2026:3" in cfg.checklist.xlsx_path_cache
        finally:
            root.destroy()

    def test_clear_cache_persist_failure_warns(self, tmp_path: Path) -> None:
        """save_config が OSError を投げても in-memory cache は削除済み + warning 表示。"""
        root = tk.Tk()
        try:
            dlg, cfg = self._make_dialog(root, tmp_path)
            with patch(
                "wiseman_hub.ui.checklist_c_dialog.messagebox.askyesno",
                return_value=True,
            ), patch(
                "wiseman_hub.ui.checklist_c_dialog.save_config",
                side_effect=OSError("disk full"),
            ), patch(
                "wiseman_hub.ui.checklist_c_dialog.messagebox.showwarning"
            ) as mock_warn:
                dlg._clear_cache_for_row(0)
            # in-memory は消えている
            assert "宮下:2026:3" not in cfg.checklist.xlsx_path_cache
            # warning が出ている
            mock_warn.assert_called_once()
        finally:
            root.destroy()


def test_cache_key_format() -> None:
    """cache_key の形式が想定通り (staff:year:month)。"""
    assert cache_key("宮下", 2026, 3) == "宮下:2026:3"
    assert cache_key("小林", 2026, 12) == "小林:2026:12"
