"""統合テスト用フィクスチャ。

WinFormsモックアプリ (WisemanMock.exe) を起動し、
PywinautoEngine でGUI操作をテストする。Windows環境でのみ実行可能。
"""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# Windows以外では統合テスト全体をスキップ
if sys.platform != "win32":
    pytest.skip("Windows環境でのみ実行可能", allow_module_level=True)

from wiseman_hub.rpa.pywinauto_engine import PywinautoEngine

# モックアプリのパス
MOCK_APP_DIR = Path(__file__).parent.parent.parent / "mock_wiseman_app"
MOCK_APP_SLN = MOCK_APP_DIR / "WisemanMock.sln"
MOCK_APP_EXE = MOCK_APP_DIR / "WisemanMock" / "bin" / "Release" / "WisemanMock.exe"


def _find_msbuild() -> str | None:
    """MSBuild.exe のパスを探す。"""
    # PATH上にあればそのまま
    if shutil.which("msbuild"):
        return "msbuild"
    # VS Build Tools の既定パス
    vs_msbuild = Path(
        r"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools"
        r"\MSBuild\Current\Bin\MSBuild.exe"
    )
    if vs_msbuild.exists():
        return str(vs_msbuild)
    return None


@pytest.fixture(scope="session", autouse=True)
def build_mock_app():
    """テストセッション開始時にモックアプリをビルドする。"""
    # 既にビルド済みならスキップ
    if MOCK_APP_EXE.exists():
        return

    if not MOCK_APP_SLN.exists():
        pytest.skip(f"モックアプリのソリューションが見つかりません: {MOCK_APP_SLN}")

    msbuild = _find_msbuild()
    if msbuild is None:
        pytest.fail("MSBuild が見つかりません。VS Build Tools をインストールしてください")

    result = subprocess.run(
        [msbuild, str(MOCK_APP_SLN), "/p:Configuration=Release", "/v:minimal"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        pytest.fail(f"モックアプリのビルドに失敗:\n{result.stderr}")

    if not MOCK_APP_EXE.exists():
        pytest.fail(f"ビルド後にexeが見つかりません: {MOCK_APP_EXE}")


@pytest.fixture
def engine() -> PywinautoEngine:
    """PywinautoEngineインスタンスを生成し、テスト後にクリーンアップする。

    launch_and_login() がアプリ起動を担当するため、fixture ではプロセスを起動しない。
    テスト終了後に残存プロセスを確実に停止する。
    """
    eng = PywinautoEngine(
        startup_wait_sec=0,
        window_title_pattern=".*管理システム SP.*",
    )
    yield eng
    # クリーンアップ: engine が起動したプロセスを停止
    if eng._app is not None:
        with contextlib.suppress(Exception):
            eng._app.kill()
        eng._app = None
        eng._main_window = None
