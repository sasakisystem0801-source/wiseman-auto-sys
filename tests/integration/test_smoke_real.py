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

import logging
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

logger = logging.getLogger(__name__)

# 親 conftest.py で Windows 以外は module-level skip 済 (allow_module_level=True)。
# ``WISEMAN_REAL=1`` でない場合は本ファイルも全体 skip (USB ドングル + 実機が必要)。
if os.environ.get("WISEMAN_REAL") != "1":
    pytest.skip(
        "smoke_real は WISEMAN_REAL=1 環境変数で明示有効化必須 "
        "(USB ドングル + 実機 Wiseman を伴うため)",
        allow_module_level=True,
    )

# module-level skip より後に置く意図 (Windows 以外で pywinauto 不在の ImportError 回避)。
from wiseman_hub.rpa.pywinauto_engine import PywinautoEngine  # noqa: E402,I001


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

    cleanup で ``close_wiseman`` が unexpected exception を raise した場合は
    実機 Wiseman プロセスが残存し、次回テスト「ワイズマン未起動」前提が崩れる。
    例外は test 結果を汚さないよう吸収するが、``logger.exception`` で記録し
    TeamViewer 経由のポストモーテム調査で気付けるようにする (silent leak 防止)。
    """
    eng = PywinautoEngine(startup_wait_sec=10)
    yield eng
    try:
        eng.close_wiseman()
    except Exception:
        logger.exception(
            "real_engine cleanup: close_wiseman が失敗。実機 Wiseman プロセス "
            "が残存している可能性あり、次回テスト前に手動終了を確認すること。"
        )


@pytest.mark.wiseman_real
def test_smoke_real_launch_to_new_registration(
    lnk_path: Path, real_engine: PywinautoEngine
) -> None:
    """実機 smoke E2E: launch → care system → new registration の 3 step が完走することを確認。

    各 step 後に engine 内部 state (``_launcher_window`` / ``_main_window``) +
    新規登録フォーム frmKihon を最小限 assert する。step メソッドが将来 silent
    fallback (例外を握り潰して return) に refactor された場合のテストすり抜け
    防止 (PR #323 silent-failure-hunter 指摘 C2 反映)。
    """
    real_engine.launch(str(lnk_path))
    assert real_engine._launcher_window is not None, (
        "launch 後に _launcher_window が attach されていない "
        "(engine 内部のランチャー検出が silent 失敗した可能性)"
    )

    real_engine.select_care_system()
    assert real_engine._main_window is not None, (
        "select_care_system 後に _main_window が attach されていない "
        "(engine 内部のメインウィンドウ検出が silent 失敗した可能性)"
    )

    real_engine.click_new_registration()
    # click_new_registration 内の `reg_window.wait("visible")` が例外 raise の
    # はずだが、二重防御として新規登録フォーム frmKihon の存在を post-condition
    # で明示的に assert する。
    reg_window = real_engine._main_window.child_window(auto_id="frmKihon")
    assert reg_window.exists(), (
        "click_new_registration 後に frmKihon (新規登録フォーム) が "
        "main_window 配下に見つからない"
    )
