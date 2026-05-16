"""実機 Wiseman smoke E2E テスト (Issue #17)。

``WISEMAN_REAL=1`` が指定された時のみ起動。USB ドングル + 実機 Wiseman が必須。
通常の CI / 開発環境では skip される。

scripts/smoke_real.py の 3 ステップ (launch → care system → new registration)
を pytest assert で CI 化したもの。手動 ``input()`` 待機を除去し、CI workflow
(workflow_dispatch) でも実行可能。

使い方::

    $env:WISEMAN_REAL = "1"
    $env:WISEMAN_LNK_PATH = "C:\\Users\\<you>\\...\\ワイズマンASPサービス起動.lnk"
    uv run pytest tests/integration/test_smoke_real.py -m wiseman_real

事前準備:
    - USB ドングル挿入
    - ワイズマン未起動 (事前終了)
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

# 親 conftest.py で Windows 以外は module-level skip 済 (allow_module_level=True)。
# ``WISEMAN_REAL=1`` でない場合は本ファイルも全体 skip (USB ドングル + 実機が必要)。
if os.environ.get("WISEMAN_REAL") != "1":
    pytest.skip(
        "smoke_real は WISEMAN_REAL=1 環境変数で明示有効化必須 "
        "(USB ドングル + 実機 Wiseman を伴うため)",
        allow_module_level=True,
    )

from wiseman_hub.rpa.pywinauto_engine import PywinautoEngine


@pytest.fixture
def lnk_path() -> Path:
    """``WISEMAN_LNK_PATH`` 環境変数からワイズマンショートカット path を取得。

    WISEMAN_REAL=1 を立てた時点で .lnk path を意図的に渡す前提のため、未指定/
    不在は skip ではなく fail (テスト要件不整合)。
    """
    raw = os.environ.get("WISEMAN_LNK_PATH", "")
    if not raw:
        pytest.fail(
            "WISEMAN_REAL=1 を有効化した場合は WISEMAN_LNK_PATH 環境変数で "
            "ワイズマンショートカット (.lnk) のパスも指定してください。"
        )
    path = Path(raw)
    if not path.exists():
        pytest.fail(f"WISEMAN_LNK_PATH の指定先が存在しません: {path}")
    return path


@pytest.fixture
def real_engine() -> Iterator[PywinautoEngine]:
    """PywinautoEngine + テスト後 ``close_wiseman`` 強制クリーンアップ。

    親 conftest.py の ``engine`` fixture (モック起動用) とは別系統。実機起動は
    ``startup_wait_sec=10`` でドングル認証 + メインウィンドウ表示を待つ。
    """
    eng = PywinautoEngine(startup_wait_sec=10)
    yield eng
    with contextlib.suppress(Exception):
        eng.close_wiseman()


@pytest.mark.wiseman_real
def test_smoke_real_launch_to_new_registration(
    lnk_path: Path, real_engine: PywinautoEngine
) -> None:
    """実機 smoke E2E: launch → care system → new registration。

    Definition of Done (Issue #17):
        - WISEMAN_REAL=1 で実機実行、各 step を pytest assert で CI 化
        - WISEMAN_REAL 未設定 / "1" 以外で module-level skip
        - scripts/smoke_real.py の 3 ステップを再現
    """
    real_engine.launch(str(lnk_path))
    real_engine.select_care_system()
    real_engine.click_new_registration()
