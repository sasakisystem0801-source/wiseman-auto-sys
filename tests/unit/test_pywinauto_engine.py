"""PywinautoEngine の macOS ユニットテスト (Issue #15)

sys.modules にフェイク pywinauto を差し込み、sys.platform を偽装することで
Windows 専用の PywinautoEngine を macOS/Linux 上でもインポート・テスト可能にする。
"""

from __future__ import annotations

import ctypes as _ctypes
import importlib
import os
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

# ── フェイク pywinauto モジュール構築 ────────────────────────────

# except 句で使うため実クラスが必要（MagicMock は不可）
_ElementNotFoundError = type("ElementNotFoundError", (Exception,), {})
_PywinautoTimeoutError = type("TimeoutError", (Exception,), {})


def _build_fake_pywinauto() -> dict[str, ModuleType]:
    """sys.modules に差し込むフェイク pywinauto パッケージ群を返す。"""
    pkg = ModuleType("pywinauto")
    pkg.Application = MagicMock

    app_mod = ModuleType("pywinauto.application")
    app_mod.WindowSpecification = MagicMock
    pkg.application = app_mod

    fw_mod = ModuleType("pywinauto.findwindows")
    fw_mod.ElementNotFoundError = _ElementNotFoundError
    pkg.findwindows = fw_mod

    tm_mod = ModuleType("pywinauto.timings")
    tm_mod.TimeoutError = _PywinautoTimeoutError
    pkg.timings = tm_mod

    return {
        "pywinauto": pkg,
        "pywinauto.application": app_mod,
        "pywinauto.findwindows": fw_mod,
        "pywinauto.timings": tm_mod,
    }


# ── モジュールインポート (module scope — 1回だけ実行) ────────────

_MOD_KEY = "wiseman_hub.rpa.pywinauto_engine"
_saved_modules: dict[str, object] = {}
_mock_user32 = MagicMock()

for _k in list(sys.modules):
    if _k.startswith(_MOD_KEY):
        _saved_modules[_k] = sys.modules.pop(_k)

_fake_mods = _build_fake_pywinauto()

# macOS には ctypes.WinDLL が存在しないため、patch 前にダミー属性を作る
_had_windll = hasattr(_ctypes, "WinDLL")
if not _had_windll:
    _ctypes.WinDLL = type("WinDLL", (), {})  # type: ignore[attr-defined]

with (
    patch.dict(sys.modules, _fake_mods),
    patch.object(sys, "platform", "win32"),
    patch.object(_ctypes, "WinDLL", return_value=_mock_user32),
):
    _pe = importlib.import_module(_MOD_KEY)

if not _had_windll:
    del _ctypes.WinDLL  # type: ignore[attr-defined]

PywinautoEngine = _pe.PywinautoEngine


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture()
def engine() -> PywinautoEngine:
    """フレッシュな PywinautoEngine インスタンスを返す。"""
    return PywinautoEngine()


@pytest.fixture()
def engine_with_launcher(engine: PywinautoEngine) -> PywinautoEngine:
    """_launcher_window がセット済みの engine を返す。"""
    engine._launcher_window = MagicMock()
    engine._app = MagicMock()
    return engine


@pytest.fixture()
def engine_with_main(engine: PywinautoEngine) -> PywinautoEngine:
    """_main_window がセット済みの engine を返す。"""
    engine._main_window = MagicMock()
    engine._app = MagicMock()
    return engine


# ── C6: __init__ defaults ────────────────────────────────────────


class TestInit:
    def test_defaults(self, engine: PywinautoEngine) -> None:
        assert engine._startup_wait_sec == 15
        assert engine._window_title_pattern == ".*管理システム SP.*"
        assert engine._app is None
        assert engine._launcher_window is None
        assert engine._main_window is None


# ── C1/C2: _post_message / _send_message ─────────────────────────


class TestPostMessage:
    def test_success(self) -> None:
        _mock_user32.PostMessageW.return_value = 1
        PywinautoEngine._post_message(0x1234, 0x0201, 0, 0)
        _mock_user32.PostMessageW.assert_called_with(0x1234, 0x0201, 0, 0)

    def test_failure_raises_runtime_error(self) -> None:
        _mock_user32.PostMessageW.return_value = 0
        with (
            patch.object(_ctypes, "get_last_error", create=True, return_value=1400),
            pytest.raises(RuntimeError, match="PostMessageW failed"),
        ):
            PywinautoEngine._post_message(0xDEAD, 0x0201, 0, 0)


class TestSendMessage:
    def test_success(self) -> None:
        _mock_user32.IsWindow.return_value = 1
        _mock_user32.SendMessageW.return_value = 42
        result = PywinautoEngine._send_message(0x1234, 0x00F5, 0, 0)
        assert result == 42

    def test_invalid_hwnd_raises(self) -> None:
        _mock_user32.IsWindow.return_value = 0
        with pytest.raises(RuntimeError, match="invalid hwnd"):
            PywinautoEngine._send_message(0xBAD, 0x00F5, 0, 0)


# ── C4: _get_active_mdi_child ────────────────────────────────────


class TestGetActiveMdiChild:
    def test_returns_none_when_main_window_is_none(self, engine: PywinautoEngine) -> None:
        assert engine._get_active_mdi_child() is None

    def test_returns_child_when_exists(self, engine_with_main: PywinautoEngine) -> None:
        mock_child = MagicMock()
        mock_child.exists.return_value = True
        engine_with_main._main_window.child_window.return_value = mock_child
        result = engine_with_main._get_active_mdi_child()
        assert result is mock_child

    def test_returns_none_on_element_not_found(self, engine_with_main: PywinautoEngine) -> None:
        engine_with_main._main_window.child_window.side_effect = _ElementNotFoundError
        assert engine_with_main._get_active_mdi_child() is None


# ── C3/B3: select_care_system ────────────────────────────────────


class TestSelectCareSystem:
    def test_requires_launcher(self, engine: PywinautoEngine) -> None:
        """C3: _launcher_window is None → RuntimeError"""
        with pytest.raises(RuntimeError, match="ランチャーが未接続"):
            engine.select_care_system()

    def test_button_path_uses_send_message(self, engine_with_launcher: PywinautoEngine) -> None:
        """B1: Button が見つかれば BM_CLICK via SendMessage"""
        mock_wrapper = MagicMock()
        mock_wrapper.handle = 0xAAAA
        mock_candidate = MagicMock()
        mock_candidate.wait.return_value = mock_wrapper

        engine_with_launcher._launcher_window.child_window.return_value = mock_candidate

        mock_main = MagicMock()
        engine_with_launcher._app.window.return_value = mock_main

        _mock_user32.IsWindow.return_value = 1
        _mock_user32.SendMessageW.return_value = 0

        engine_with_launcher.select_care_system()

        first_call = engine_with_launcher._launcher_window.child_window.call_args_list[0]
        assert first_call.kwargs["control_type"] == "Button"

        _mock_user32.SendMessageW.assert_called_with(0xAAAA, 0x00F5, 0, 0)

    def test_pane_fallback_uses_post_message(self, engine_with_launcher: PywinautoEngine) -> None:
        """B2: Button 失敗 → Pane で WM_LBUTTON via PostMessage"""
        mock_wrapper = MagicMock()
        mock_wrapper.handle = 0xBBBB

        def child_window_side_effect(**kwargs):
            ct = kwargs.get("control_type")
            if ct == "Button":
                raise _ElementNotFoundError("not found")
            mock_candidate = MagicMock()
            mock_candidate.wait.return_value = mock_wrapper
            return mock_candidate

        engine_with_launcher._launcher_window.child_window.side_effect = child_window_side_effect

        mock_main = MagicMock()
        engine_with_launcher._app.window.return_value = mock_main

        _mock_user32.PostMessageW.return_value = 1

        engine_with_launcher.select_care_system()

        post_calls = _mock_user32.PostMessageW.call_args_list
        wm_lbutton_calls = [c for c in post_calls if c.args[0] == 0xBBBB]
        assert len(wm_lbutton_calls) >= 2  # DOWN + UP
        assert wm_lbutton_calls[0].args[1] == 0x0201  # WM_LBUTTONDOWN
        assert wm_lbutton_calls[1].args[1] == 0x0202  # WM_LBUTTONUP

    def test_all_control_types_fail_raises(self, engine_with_launcher: PywinautoEngine) -> None:
        """B3: 全 control_type 失敗 → RuntimeError (target_hwnd is None)"""

        def always_fail(**kwargs):
            mock_candidate = MagicMock()
            mock_candidate.wait.side_effect = _PywinautoTimeoutError("timeout")
            return mock_candidate

        engine_with_launcher._launcher_window.child_window.side_effect = always_fail
        engine_with_launcher._launcher_window.descendants.return_value = []

        with pytest.raises(RuntimeError, match="ケア記録選択要素が見つかりません"):
            engine_with_launcher.select_care_system()

        calls = engine_with_launcher._launcher_window.child_window.call_args_list
        tried_cts = [c.kwargs["control_type"] for c in calls]
        assert tried_cts == ["Button", "Pane", "Text", "Hyperlink"]


# ── B4: click_new_registration ───────────────────────────────────


class TestClickNewRegistration:
    def test_requires_main_window(self, engine: PywinautoEngine) -> None:
        """B4: _main_window is None → RuntimeError"""
        with pytest.raises(RuntimeError, match="メインウィンドウが未接続"):
            engine.click_new_registration()

    def test_posts_bm_click_and_waits_for_frmkihon(self, engine_with_main: PywinautoEngine) -> None:
        mock_btn_wrapper = MagicMock()
        mock_btn_wrapper.handle = 0xCCCC
        mock_btn = MagicMock()
        mock_btn.wrapper_object.return_value = mock_btn_wrapper

        mock_frmkihon = MagicMock()

        def child_window_router(**kwargs):
            if kwargs.get("title") == "新規登録":
                return mock_btn
            if kwargs.get("auto_id") == "frmKihon":
                return mock_frmkihon
            return MagicMock()

        engine_with_main._main_window.child_window.side_effect = child_window_router
        _mock_user32.PostMessageW.return_value = 1

        engine_with_main.click_new_registration()

        post_calls = [c for c in _mock_user32.PostMessageW.call_args_list if c.args[0] == 0xCCCC]
        assert any(c.args[1] == 0x00F5 for c in post_calls)  # BM_CLICK

        mock_frmkihon.wait.assert_called_with("visible", timeout=10)


# ── export_csv ───────────────────────────────────────────────────


class TestExportCsv:
    def test_requires_main_window(self, engine: PywinautoEngine) -> None:
        with pytest.raises(RuntimeError, match="メインウィンドウが未接続"):
            engine.export_csv(Path("/tmp"))

    def test_btnprint_uses_bm_click_via_post_message(self, engine_with_main: PywinautoEngine) -> None:
        """btnPrint は BM_CLICK(PostMessage) で送信される（WM_LBUTTON ではない）"""
        mock_child = MagicMock()
        mock_child.exists.return_value = True
        engine_with_main._main_window.child_window.return_value = mock_child

        mock_btn_wrapper = MagicMock()
        mock_btn_wrapper.handle = 0xFFFF
        mock_child.child_window.return_value.wrapper_object.return_value = mock_btn_wrapper

        # SaveFileDialog が見つからないケース（ボタンクリック後のフローは別テスト）
        engine_with_main._app.window.side_effect = _ElementNotFoundError("no dialog")

        _mock_user32.PostMessageW.return_value = 1

        with patch("time.sleep"):
            result = engine_with_main.export_csv(Path("/tmp/test_out"))

        # export_csv は SaveFileDialog が見つからず None を返すが、
        # BM_CLICK(0x00F5) が PostMessageW で送信されたことを検証
        assert result is None
        post_calls = [c for c in _mock_user32.PostMessageW.call_args_list if c.args[0] == 0xFFFF]
        assert any(c.args[1] == 0x00F5 for c in post_calls)  # BM_CLICK
        # WM_LBUTTONDOWN(0x0201) が使われていないことを確認
        assert not any(c.args[1] == 0x0201 for c in post_calls)


# ── B5/B6: close_wiseman ─────────────────────────────────────────


class TestCloseWiseman:
    def test_skips_when_no_main_window(self, engine: PywinautoEngine) -> None:
        engine.close_wiseman()

    def test_normal_exit(self, engine_with_main: PywinautoEngine) -> None:
        """B5: プロセスが正常終了するケース"""
        mock_btn_wrapper = MagicMock()
        mock_btn_wrapper.handle = 0xDDDD
        mock_btn = MagicMock()
        mock_btn.wrapper_object.return_value = mock_btn_wrapper
        engine_with_main._main_window.child_window.return_value = mock_btn

        _mock_user32.PostMessageW.return_value = 1

        mock_confirm = MagicMock()
        engine_with_main._app.window.return_value = mock_confirm
        engine_with_main._app.process = 9999

        with (
            patch.object(os, "kill", side_effect=ProcessLookupError),
            patch("time.sleep"),
            patch("time.monotonic", side_effect=[0, 0.1]),
        ):
            engine_with_main.close_wiseman()

        assert engine_with_main._main_window is None
        assert engine_with_main._app is None

    def test_timeout_path(self, engine_with_main: PywinautoEngine) -> None:
        """B6: プロセスが終了せずタイムアウト"""
        mock_btn_wrapper = MagicMock()
        mock_btn_wrapper.handle = 0xEEEE
        mock_btn = MagicMock()
        mock_btn.wrapper_object.return_value = mock_btn_wrapper
        engine_with_main._main_window.child_window.return_value = mock_btn

        _mock_user32.PostMessageW.return_value = 1

        mock_confirm = MagicMock()
        engine_with_main._app.window.return_value = mock_confirm
        engine_with_main._app.process = 8888

        with (
            patch.object(os, "kill"),
            patch("time.sleep"),
            patch("time.monotonic", side_effect=[0, 5, 11]),
        ):
            engine_with_main.close_wiseman()

        assert engine_with_main._main_window is None
        assert engine_with_main._app is None


# ── C5: launch ───────────────────────────────────────────────────


class TestLaunch:
    def test_exe_path_uses_application_start(self, engine: PywinautoEngine) -> None:
        """.exe → Application(backend='uia').start(exe_path)"""
        mock_app = MagicMock()
        mock_app.start.return_value = mock_app
        mock_launcher = MagicMock()
        mock_app.window.return_value = mock_launcher

        with patch.object(_pe, "Application", return_value=mock_app), patch("time.sleep"):
            engine.launch("C:\\wiseman.exe")

        mock_app.start.assert_called_once_with("C:\\wiseman.exe")
        assert engine._app is mock_app

    def test_lnk_path_uses_subprocess(self, engine: PywinautoEngine) -> None:
        """.lnk → subprocess.Popen + connect"""
        mock_app = MagicMock()
        mock_launcher = MagicMock()
        mock_app.window.return_value = mock_launcher

        with (
            patch.object(_pe, "Application", return_value=mock_app),
            patch("subprocess.Popen") as mock_popen,
            patch("time.sleep"),
        ):
            engine.launch("C:\\wiseman.lnk")

        mock_popen.assert_called_once()
        mock_app.connect.assert_called_once()
        assert engine._app is mock_app

    def test_launch_failure_kills_app(self, engine: PywinautoEngine) -> None:
        """起動失敗時に app.kill() が呼ばれ、_app が None にリセットされる"""
        mock_app = MagicMock()
        mock_app.start.return_value = mock_app
        mock_app.window.return_value.wait.side_effect = Exception("timeout")

        with (
            patch.object(_pe, "Application", return_value=mock_app),
            patch("time.sleep"),
            pytest.raises(Exception, match="timeout"),
        ):
            engine.launch("C:\\wiseman.exe")

        mock_app.kill.assert_called_once()
        assert engine._app is None
