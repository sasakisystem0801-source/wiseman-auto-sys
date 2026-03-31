"""統合テスト用フィクスチャ。

WinFormsモックアプリ (WisemanMock.exe) を起動し、
PywinautoEngine でGUI操作をテストする。Windows環境でのみ実行可能。
"""

from __future__ import annotations

import subprocess
import sys
import time
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


@pytest.fixture(scope="session", autouse=True)
def build_mock_app():
    """テストセッション開始時にモックアプリをビルドする。"""
    if not MOCK_APP_SLN.exists():
        pytest.skip(f"モックアプリのソリューションが見つかりません: {MOCK_APP_SLN}")

    result = subprocess.run(
        ["msbuild", str(MOCK_APP_SLN), "/p:Configuration=Release", "/v:minimal"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        pytest.fail(f"モックアプリのビルドに失敗:\n{result.stderr}")

    if not MOCK_APP_EXE.exists():
        pytest.fail(f"ビルド後にexeが見つかりません: {MOCK_APP_EXE}")


@pytest.fixture
def mock_app_process():
    """モックアプリを起動し、テスト終了後に停止する。"""
    proc = subprocess.Popen([str(MOCK_APP_EXE)])
    time.sleep(2)  # ウィンドウ表示を待機
    if proc.poll() is not None:
        pytest.fail(f"モックアプリが起動直後にクラッシュしました (exit code: {proc.returncode})")
    yield proc
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture
def engine() -> PywinautoEngine:
    """PywinautoEngineインスタンスを生成する（ドングル待機なし）。"""
    return PywinautoEngine(
        startup_wait_sec=0,
        window_title_pattern=".*管理システム SP.*",
    )
