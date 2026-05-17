"""B/C 自動配置ダイアログ初期レイアウトの retention テスト (Issue #274 Phase 1)。

Phase 1 PR #280 で `message` 列を 240 → 500 px に拡大 + `stretch=True` +
横スクロールバーを追加した。さらに本 PR で Toplevel 初期 geometry を
780x520 → 1100x600 に拡大して 5 列合計 1020px (氏名 140 + 居宅 160 +
担当 60 + ステータス 160 + 詳細 500) を初期表示で fit させ、Phase 1 の
Definition of Done を完成させた。

このテストは Phase 1 の 4 つの構成要素を同時に retention 検証する:
    1. Toplevel 初期幅 >= 1100px (詳細列が画面外に押し出されない)
    2. `tree.column("message", "width") == 500`
    3. `tree.column("message", "stretch") == 1` (True)
    4. 横スクロールバー (xscrollcommand) 接続あり

いずれか 1 つが silent regression を起こすと CI で fail する設計。
"""

from __future__ import annotations

import re
import sys
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

EXPECTED_MIN_WIDTH = 1100
EXPECTED_MESSAGE_COLUMN_WIDTH = 500
_GEOMETRY_PATTERN = re.compile(r"^(\d+)x(\d+)")


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
    """``"1100x600+0+0"`` 形式から width を整数で取り出す。

    Tk の初期化途中 (mapping 完了前) は ``"1x1+0+0"`` を返すため、
    呼び出し側で ``update_idletasks()`` を先に呼んでおくこと。
    予期しない format の場合は明示的に test を失敗させる
    (``int()`` の ValueError を素通りさせない)。
    """
    match = _GEOMETRY_PATTERN.match(geometry_str)
    if match is None:
        pytest.fail(f"unexpected geometry format: {geometry_str!r}")
    return int(match.group(1))


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
    sys.platform == "win32",
    reason="Windows + uv venv で Tcl init.tcl 不在 (Issue #276 follow-up)。"
    "Issue #276 close 時に本 decorator を削除すること。",
    strict=False,
)
def test_initial_layout_retains_phase1_constraints(
    tmp_path: Path, dialog_cls: _DialogCls, label: str
) -> None:
    """初期 geometry + 詳細列 width/stretch + 横スクロールバー接続の retention。"""
    root = tk.Tk()
    root.withdraw()
    try:
        cfg = _make_config(tmp_path)
        cfg_path = _make_config_path(tmp_path)
        dlg = dialog_cls(parent=root, config=cfg, config_path=cfg_path)
        try:
            top = dlg.get_toplevel()
            # Tk Toplevel は mapping 完了前は ``"1x1+0+0"`` を返す。
            # update_idletasks() で pending geometry 反映を待つ。
            top.update_idletasks()

            width = _extract_width(top.geometry())
            assert width >= EXPECTED_MIN_WIDTH, (
                f"{label} ダイアログの初期幅 {width}px は 5 列合計 1020px + 余白 "
                f"({EXPECTED_MIN_WIDTH}px) を下回り、詳細列が画面外に押し出される"
            )

            tree = dlg._tree
            msg_width = int(tree.column("message", "width"))
            assert msg_width == EXPECTED_MESSAGE_COLUMN_WIDTH, (
                f"{label} ダイアログの message 列幅 {msg_width}px は "
                f"Phase 1 想定の {EXPECTED_MESSAGE_COLUMN_WIDTH}px と異なる"
            )
            assert int(tree.column("message", "stretch")) == 1, (
                f"{label} ダイアログの message 列 stretch が無効化されている"
            )

            xscroll_cmd = tree.cget("xscrollcommand")
            assert xscroll_cmd, (
                f"{label} ダイアログに横スクロールバーが接続されていない "
                f"(Phase 1 の overflow 救済経路)"
            )
        finally:
            dlg.get_toplevel().destroy()
    finally:
        root.destroy()
