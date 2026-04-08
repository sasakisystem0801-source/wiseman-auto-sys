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


def _sources_newer_than_exe() -> bool:
    """モックアプリのソース(.cs/.csproj)が exe より新しければ True。

    既存ビルドのスキップは開発中のソース変更を見逃す原因になる（#3 で実証済み）ため、
    mtime 比較で必要時のみ再ビルドする。
    """
    if not MOCK_APP_EXE.exists():
        return True
    exe_mtime = MOCK_APP_EXE.stat().st_mtime
    source_dir = MOCK_APP_DIR / "WisemanMock"
    for pattern in ("*.cs", "*.csproj"):
        for src in source_dir.glob(pattern):
            if src.stat().st_mtime > exe_mtime:
                return True
    return False


@pytest.fixture(scope="session", autouse=True)
def build_mock_app():
    """テストセッション開始時にモックアプリをビルドする。

    ソース(.cs/.csproj)が exe より新しい場合のみ再ビルドする。
    """
    if not _sources_newer_than_exe():
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

    launch() がアプリ起動を担当するため、fixture ではプロセスを起動しない。
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
