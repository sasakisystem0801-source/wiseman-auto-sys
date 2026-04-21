"""UI テスト共通 fixtures / マーカー。

``tk_available`` を session-scoped fixture で 1 回だけ評価し、全 UI テストで共有する。
個別モジュールで ``tk.Tk()`` を複数回試行すると Tcl のグローバル状態が累積し、
macOS uv python（Tk 非同梱）の 3 ファイル目で hang する事象が観測されたため。

使い方::

    import pytest

    @pytest.mark.tk_required
    class TestLauncherUI:
        def test_foo(self): ...
"""

from __future__ import annotations

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """``@pytest.mark.tk_required`` マーカーを登録（`--strict-markers` 対応）。"""
    config.addinivalue_line(
        "markers",
        "tk_required: skip if Tk runtime (tkinter.Tk()) cannot be created",
    )


@pytest.fixture(scope="session")
def _tk_available() -> bool:
    """Tk が import + root 生成できるか判定（session 単位で 1 回のみ実行）。"""
    try:
        import tkinter as _tk

        root = _tk.Tk()
        root.withdraw()
        root.destroy()
    except Exception:
        return False
    return True


@pytest.fixture(autouse=True)
def _skip_if_tk_unavailable(
    request: pytest.FixtureRequest, _tk_available: bool
) -> None:
    """``@pytest.mark.tk_required`` が付いたテストを Tk 非利用環境で skip する。"""
    if request.node.get_closest_marker("tk_required") and not _tk_available:
        pytest.skip("Tk runtime not available")
