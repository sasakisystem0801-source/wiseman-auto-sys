"""B/C 自動配置ダイアログの初期 geometry 検証 (Issue #274 Phase 1 追加修正)。

Phase 1 PR #280 で `message` 列を 240 → 500 px に拡大して `stretch=True`
+ 横スクロールバーを追加したが、Toplevel の初期 geometry が `780x520` の
ままで 5 列合計 1020px (氏名 140 + 居宅 160 + 担当 60 + ステータス 160
+ 詳細 500) を fit させられず、本田様 PC 実機検証で詳細列が画面外に
押し出されていた。1100x600 に拡大することで初期表示で詳細列が見える
状態にし、Phase 1 の Definition of Done を完成させる。

retention テストの意義:
    将来 `geometry()` を別値に上書きしてしまった場合に CI で検知できる。
    Phase 1 改善 (column message=500, stretch=True, hscroll) の前提が崩れる
    silent regression を防止する。
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path

import pytest

from wiseman_hub.config import (
    AppConfig,
    ChecklistConfig,
    GcpConfig,
    WisemanConfig,
)
from wiseman_hub.ui.checklist_b_dialog import ChecklistBDialog
from wiseman_hub.ui.checklist_c_dialog import ChecklistCDialog

# Phase 1 詳細列の前提となる 5 列合計幅 + 余白。
# 内訳: name 140 + facility 160 + staff 60 + status 160 + message 500 = 1020
# 余白: vscrollbar 16-20 + 左右 padding 16 + ウィンドウ枠 → ~80px
EXPECTED_MIN_WIDTH = 1100


def _make_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        version="test",
        wiseman=WisemanConfig(
            exe_path="/dummy", karte_root=tmp_path / "karte", fax_root=tmp_path / "fax"
        ),
        gcp=GcpConfig(project_id="proj", bucket_name="bucket"),
        checklist=ChecklistConfig(spreadsheet_id="spread123"),
    )


def _make_config_path(tmp_path: Path) -> Path:
    cfg_dir = tmp_path / "wiseman-hub" / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    return cfg_dir / "default.toml"


def _extract_width(geometry_str: str) -> int:
    """``"1100x600+0+0"`` 形式から width を整数で取り出す。"""
    width_str, _, _ = geometry_str.partition("x")
    return int(width_str)


# B/C 両ダイアログで構造が完全一致のため parametrize で集約。
# xfail reason の重複も同時解消 (Issue #276 解決時の更新箇所が 1 箇所で済む)。
_DialogCls = type[ChecklistBDialog] | type[ChecklistCDialog]


@pytest.mark.tk_required
@pytest.mark.parametrize(
    "dialog_cls,label",
    [
        pytest.param(ChecklistBDialog, "B", id="b_dialog"),
        pytest.param(ChecklistCDialog, "C", id="c_dialog"),
    ],
)
@pytest.mark.xfail(
    reason="Windows + uv venv で Tcl init.tcl 不在 (Issue #276 follow-up)",
    strict=False,
)
def test_initial_width_fits_all_columns(
    tmp_path: Path, dialog_cls: _DialogCls, label: str
) -> None:
    """ダイアログの初期幅 >= 1100px (詳細列 500px が画面外に出ない)。"""
    root = tk.Tk()
    root.withdraw()
    try:
        cfg = _make_config(tmp_path)
        cfg_path = _make_config_path(tmp_path)
        dlg = dialog_cls(parent=root, config=cfg, config_path=cfg_path)
        try:
            width = _extract_width(dlg.get_toplevel().geometry())
            assert width >= EXPECTED_MIN_WIDTH, (
                f"{label} ダイアログの初期幅 {width}px は 5 列合計 1020px + 余白 "
                f"({EXPECTED_MIN_WIDTH}px) を下回り、詳細列が画面外に押し出される"
            )
        finally:
            dlg.get_toplevel().destroy()
    finally:
        root.destroy()
