"""PywinautoEngine の macOS ユニットテスト (Issue #15)

sys.modules にフェイク pywinauto を差し込み、sys.platform を偽装することで
Windows 専用の PywinautoEngine を macOS/Linux 上でもインポート・テスト可能にする。
"""

from __future__ import annotations

import ctypes as _ctypes
import importlib
import logging
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

# Issue #14: 例外階層を patch.dict(sys.modules) の with ブロック「前」に import する。
# patch.dict は with 終了時に「with 内で追加された sys.modules キー」を削除する仕様の
# ため、with 内で base が初回 load されると、with 終了後にテスト本体が base を再
# import する際に別クラスが生成され、pywinauto_engine.py が保持する例外クラスと
# 不一致 (pytest.raises がマッチしない) になる。
from wiseman_hub.rpa.base import (  # noqa: E402
    CsvFileNotFoundError,
    ExportCsvError,
    FileNameFieldNotFoundError,
    MdiChildNotFoundError,
    SaveButtonNotFoundError,
    SaveDialogNotShownError,
)

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
    engine._inject_for_test(launcher_window=MagicMock(), app=MagicMock())
    return engine


@pytest.fixture()
def engine_with_main(engine: PywinautoEngine) -> PywinautoEngine:
    """_main_window がセット済みの engine を返す。"""
    engine._inject_for_test(main_window=MagicMock(), app=MagicMock())
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

    @pytest.mark.parametrize(
        "matching_ct",
        ["Pane", "Text", "Hyperlink"],
        ids=["pane", "text", "hyperlink"],
    )
    def test_non_button_fallback_uses_post_message(
        self,
        engine_with_launcher: PywinautoEngine,
        matching_ct: str,
    ) -> None:
        """B2: Button 失敗 → Pane/Text/Hyperlink いずれかで WM_LBUTTON via PostMessage.

        実機 (本田様 PC) はケア記録要素を Pane として公開するが、OS テーマ /
        UIA バージョン / .NET ランタイム差で Text や Hyperlink としても露出
        し得る。本 parametrize で 3 系統が同一 PostMessage WM_LBUTTONDOWN/UP
        経路に流れることを保証する (Issue #16)。
        """
        mock_wrapper = MagicMock()
        mock_wrapper.handle = 0xBBBB

        def child_window_side_effect(**kwargs):
            ct = kwargs.get("control_type")
            if ct == matching_ct:
                mock_candidate = MagicMock()
                mock_candidate.wait.return_value = mock_wrapper
                return mock_candidate
            # `matching_ct` より優先度の高い control_type (Button + 前段の
            # fallback) はすべて失敗させる。fallback 順は
            # ("Button", "Pane", "Text", "Hyperlink") を前提とする
            # (pywinauto_engine.py:181)。
            raise _ElementNotFoundError(f"not found: {ct}")

        engine_with_launcher._launcher_window.child_window.side_effect = (
            child_window_side_effect
        )

        mock_main = MagicMock()
        engine_with_launcher._app.window.return_value = mock_main

        _mock_user32.PostMessageW.reset_mock()
        _mock_user32.PostMessageW.return_value = 1

        engine_with_launcher.select_care_system()

        post_calls = _mock_user32.PostMessageW.call_args_list
        wm_lbutton_calls = [c for c in post_calls if c.args[0] == 0xBBBB]
        assert len(wm_lbutton_calls) >= 2  # DOWN + UP
        assert wm_lbutton_calls[0].args[1] == 0x0201  # WM_LBUTTONDOWN
        assert wm_lbutton_calls[0].args[2] == 0x0001  # MK_LBUTTON wparam
        assert wm_lbutton_calls[1].args[1] == 0x0202  # WM_LBUTTONUP
        assert wm_lbutton_calls[1].args[2] == 0  # WM_LBUTTONUP wparam=0

    def test_all_control_types_fail_raises(self, engine_with_launcher: PywinautoEngine) -> None:
        """B3: 全 control_type 失敗 → RuntimeError (target_hwnd is None)、chain 保持."""

        def always_fail(**kwargs):
            mock_candidate = MagicMock()
            mock_candidate.wait.side_effect = _PywinautoTimeoutError("timeout")
            return mock_candidate

        engine_with_launcher._launcher_window.child_window.side_effect = always_fail
        engine_with_launcher._launcher_window.descendants.return_value = []

        with pytest.raises(RuntimeError, match="ケア記録選択要素が見つかりません") as exc_info:
            engine_with_launcher.select_care_system()

        calls = engine_with_launcher._launcher_window.child_window.call_args_list
        tried_cts = [c.kwargs["control_type"] for c in calls]
        assert tried_cts == ["Button", "Pane", "Text", "Hyperlink"]
        assert isinstance(exc_info.value.__cause__, _PywinautoTimeoutError)

    def test_target_hwnd_zero_raises(self, engine_with_launcher: PywinautoEngine) -> None:
        """B3': wrapper.handle == 0 → RuntimeError (silent PostMessage 防止) (Issue #332).

        pywinauto の UIA wrapper が一時的に無効化された瞬間 (comtypes の
        COM プロキシ非同期破棄中、別アプリへのフォーカス切替直後等) に
        ``wrapper.handle = 0`` を返すケースで、``_post_message(0, ...)`` への
        silent fall-through を防ぐ structural guard
        (``select_care_system`` 内 ``if target_hwnd is None or target_hwnd == 0:``
        分岐) の retention テスト。

        ガードが将来 regression で外れると、PostMessageW(0, ...) が
        ERROR_INVALID_WINDOW_HANDLE (1400) を返し、運用者には文脈情報を
        欠いた謎エラーとなる。
        """
        mock_wrapper = MagicMock()
        mock_wrapper.handle = 0  # ← UIA wrapper 無効化シナリオ
        mock_candidate = MagicMock()
        mock_candidate.wait.return_value = mock_wrapper

        # Button 分岐 (fallback の先頭) で最初にマッチさせる: handle=0 が
        # 検出された時点でガードが弾けば、後続の Pane/Text/Hyperlink
        # fallback には流れず、SendMessage/PostMessage も呼ばれないはず。
        engine_with_launcher._launcher_window.child_window.return_value = mock_candidate
        engine_with_launcher._launcher_window.descendants.return_value = []

        # ガード退化時の検出のため、SendMessage/PostMessage の呼出履歴を
        # 直前で reset し、テスト後の hwnd=0 呼出有無で判定する。
        _mock_user32.SendMessageW.reset_mock()
        _mock_user32.PostMessageW.reset_mock()

        with pytest.raises(RuntimeError, match="ケア記録選択要素が見つかりません"):
            engine_with_launcher.select_care_system()

        send_zero_calls = [
            c for c in _mock_user32.SendMessageW.call_args_list if c.args[0] == 0
        ]
        post_zero_calls = [
            c for c in _mock_user32.PostMessageW.call_args_list if c.args[0] == 0
        ]
        assert send_zero_calls == [], (
            f"ガード退化: SendMessageW(0, ...) が呼ばれた: {send_zero_calls}"
        )
        assert post_zero_calls == [], (
            f"ガード退化: PostMessageW(0, ...) が呼ばれた: {post_zero_calls}"
        )


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


# ── navigate_menu ────────────────────────────────────────────────


class TestNavigateMenu:
    """MDI メニュー遷移の failure path カバレッジ (bare-str / 未接続 / primary / fallback / both-fail+chain)."""

    def test_bare_str_raises_type_error(self, engine: PywinautoEngine) -> None:
        """bare str ("業務->日報" 等) は silent corruption (str→list[char]) を防ぐため拒否。"""
        with pytest.raises(TypeError, match="must be a sequence of str segments"):
            engine.navigate_menu("業務->日報")  # type: ignore[arg-type]

    def test_requires_main_window(self, engine: PywinautoEngine) -> None:
        """_main_window is None → RuntimeError"""
        with pytest.raises(RuntimeError, match="メインウィンドウが未接続"):
            engine.navigate_menu(["業務", "日報"])

    def test_primary_path_uses_menu_select(self, engine_with_main: PywinautoEngine) -> None:
        """menu_select 成功で fallback に降りないこと。"""
        with patch("time.sleep"):
            engine_with_main.navigate_menu(["業務", "日報"])

        engine_with_main._main_window.menu_select.assert_called_once_with("業務->日報")
        # primary 成功時は fallback の MenuItem click_input が呼ばれないことを確認
        click_calls = [
            c for c in engine_with_main._main_window.child_window.call_args_list
            if c.kwargs.get("control_type") == "MenuItem"
        ]
        assert click_calls == []

    def test_fallback_to_individual_click_on_menu_select_failure(
        self, engine_with_main: PywinautoEngine, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """menu_select 失敗 → 個別 MenuItem.click_input で fallback 完走、warning log 出力."""
        engine_with_main._main_window.menu_select.side_effect = _ElementNotFoundError(
            "menu_select not supported in UIA",
        )
        # child_window(title=..., control_type="MenuItem") は default MagicMock で
        # click_input 成功扱い (side_effect なし)。

        # silent fallback 検出のため、運用者の唯一の可観測 signal である warning log を assert
        caplog.set_level(logging.WARNING, logger="wiseman_hub.rpa.pywinauto_engine")

        with patch("time.sleep"):
            engine_with_main.navigate_menu(["業務", "日報"])

        # fallback が走り、menu_path の各 item で child_window(title=item, ...) が呼ばれる
        menuitem_calls = [
            c for c in engine_with_main._main_window.child_window.call_args_list
            if c.kwargs.get("control_type") == "MenuItem"
        ]
        titles = [c.kwargs["title"] for c in menuitem_calls]
        assert titles == ["業務", "日報"]
        assert "menu_select失敗" in caplog.text

    def test_both_paths_fail_raises_runtime_error_with_chain(
        self, engine_with_main: PywinautoEngine,
    ) -> None:
        """menu_select 失敗 + 個別クリック失敗 → RuntimeError、__cause__ は fallback 側例外."""
        engine_with_main._main_window.menu_select.side_effect = _PywinautoTimeoutError(
            "menu_select timeout",
        )
        engine_with_main._main_window.child_window.return_value.click_input.side_effect = (
            _ElementNotFoundError("MenuItem not found in fallback")
        )

        with patch("time.sleep"), pytest.raises(RuntimeError, match="メニュー遷移失敗") as exc_info:
            engine_with_main.navigate_menu(["業務", "日報"])

        # chain は fallback_err (ElementNotFoundError) を指す
        assert isinstance(exc_info.value.__cause__, _ElementNotFoundError)
        # message には primary (menu_select) と fallback (individual click) の両方の文脈
        assert "menu_select" in str(exc_info.value)
        assert "individual click" in str(exc_info.value)


# ── export_csv ───────────────────────────────────────────────────


class TestExportCsv:
    def test_requires_main_window(self, engine: PywinautoEngine) -> None:
        with pytest.raises(RuntimeError, match="メインウィンドウが未接続"):
            engine.export_csv(Path("/tmp"))

    def test_btnprint_uses_bm_click_postmessage(self, engine_with_main: PywinautoEngine) -> None:
        """btnPrint は BM_CLICK (PostMessage) でクリックされる (Issue #14 後も維持)"""
        mock_child = MagicMock()
        mock_child.exists.return_value = True
        engine_with_main._main_window.child_window.return_value = mock_child

        mock_btn_wrapper = MagicMock()
        mock_btn_wrapper.handle = 0xBBBB
        mock_child.child_window.return_value.wrapper_object.return_value = mock_btn_wrapper

        # auto_export.csv が見つからず、ダイアログも見つからない → SaveDialogNotShownError
        engine_with_main._find_auto_export_csv = MagicMock(return_value=None)
        engine_with_main._app.window.side_effect = _ElementNotFoundError("no dialog")

        with patch("time.sleep"), pytest.raises(SaveDialogNotShownError):
            engine_with_main.export_csv(Path("/tmp/test_out"))

        _mock_user32.PostMessageW.assert_called_with(0xBBBB, 0x00F5, 0, 0)


# ── Issue #14: export_csv 失敗モード区別化 ─────────────────────────


class TestExportCsvFailureModes:
    """5 つの失敗モードがそれぞれ対応する ExportCsvError サブクラスを raise すること。"""

    def test_exception_hierarchy(self) -> None:
        """すべての失敗モード例外が ExportCsvError を継承する。"""
        for cls in (
            MdiChildNotFoundError,
            SaveDialogNotShownError,
            FileNameFieldNotFoundError,
            SaveButtonNotFoundError,
            CsvFileNotFoundError,
        ):
            assert issubclass(cls, ExportCsvError)
            assert issubclass(cls, RuntimeError)

    def test_raises_mdi_child_not_found(
        self, engine_with_main: PywinautoEngine, tmp_path: Path
    ) -> None:
        """active MDI 子ウィンドウが取れない場合は MdiChildNotFoundError"""
        engine_with_main._get_active_mdi_child = MagicMock(return_value=None)

        with pytest.raises(MdiChildNotFoundError, match="MDI 子ウィンドウ"):
            engine_with_main.export_csv(tmp_path)

    def test_raises_save_dialog_not_shown(
        self, engine_with_main: PywinautoEngine, tmp_path: Path
    ) -> None:
        """auto_export.csv なし + ダイアログ未出現 → SaveDialogNotShownError、context に title_re + chain."""
        mock_child = MagicMock()
        mock_child.exists.return_value = True
        engine_with_main._main_window.child_window.return_value = mock_child
        engine_with_main._find_auto_export_csv = MagicMock(return_value=None)
        engine_with_main._app.window.side_effect = _PywinautoTimeoutError("timeout")

        with patch("time.sleep"), pytest.raises(SaveDialogNotShownError) as exc_info:
            engine_with_main.export_csv(tmp_path)

        assert "title_re" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, _PywinautoTimeoutError)

    def test_raises_filename_field_not_found(
        self, engine_with_main: PywinautoEngine, tmp_path: Path
    ) -> None:
        """ダイアログ表示済だが全 selector で入力欄不在 → FileNameFieldNotFoundError、selector list 含む"""
        mock_child = MagicMock()
        mock_child.exists.return_value = True
        engine_with_main._main_window.child_window.return_value = mock_child
        engine_with_main._find_auto_export_csv = MagicMock(return_value=None)

        mock_dialog = MagicMock()
        # ダイアログ表示は成功 (wait OK)
        engine_with_main._app.window.return_value = mock_dialog
        # 全 selector で ElementNotFoundError
        mock_dialog.child_window.return_value.set_edit_text.side_effect = (
            _ElementNotFoundError("no field")
        )

        with patch("time.sleep"), pytest.raises(
            FileNameFieldNotFoundError, match="FileNameControlHost"
        ) as exc_info:
            engine_with_main.export_csv(tmp_path)

        assert isinstance(exc_info.value.__cause__, _ElementNotFoundError)

    def test_raises_save_button_not_found(
        self, engine_with_main: PywinautoEngine, tmp_path: Path
    ) -> None:
        """ファイル名入力成功後、保存ボタン全 selector 失敗 → SaveButtonNotFoundError"""
        mock_child = MagicMock()
        mock_child.exists.return_value = True
        engine_with_main._main_window.child_window.return_value = mock_child
        engine_with_main._find_auto_export_csv = MagicMock(return_value=None)

        mock_dialog = MagicMock()
        engine_with_main._app.window.return_value = mock_dialog

        # ファイル名 selector の最初 (FileNameControlHost) は成功、保存ボタンは全失敗。
        # set_edit_text は成功する (default MagicMock の挙動) ため side_effect 設定なし。
        # click_input を ElementNotFoundError にして保存ボタン全 selector を失敗させる。
        mock_dialog.child_window.return_value.click_input.side_effect = (
            _ElementNotFoundError("no save button")
        )

        with patch("time.sleep"), pytest.raises(
            SaveButtonNotFoundError, match="btnSave"
        ) as exc_info:
            engine_with_main.export_csv(tmp_path)

        assert isinstance(exc_info.value.__cause__, _ElementNotFoundError)

    def test_raises_csv_file_not_found(
        self, engine_with_main: PywinautoEngine, tmp_path: Path
    ) -> None:
        """全操作成功だが csv_path に出力されない → CsvFileNotFoundError、期待パス含む"""
        mock_child = MagicMock()
        mock_child.exists.return_value = True
        engine_with_main._main_window.child_window.return_value = mock_child
        engine_with_main._find_auto_export_csv = MagicMock(return_value=None)

        mock_dialog = MagicMock()
        engine_with_main._app.window.return_value = mock_dialog
        # set_edit_text / click_input は default MagicMock で成功扱い (side_effect なし)。
        # csv_path.exists() は False のまま (ファイル未作成)。

        with patch("time.sleep"), pytest.raises(CsvFileNotFoundError) as exc_info:
            engine_with_main.export_csv(tmp_path)

        assert str(tmp_path) in str(exc_info.value)


class TestTrySelectorsSequentialGuards:
    """Issue #11 M6 helper の防御契約検証。

    silent-failure-hunter Important I-1 (rating 6): 呼出側 typo 等で空 list が
    混入すると「全 selector で発見できません: 」という空末尾メッセージのみで
    原因 chain が消失する経路を防御。
    """

    def test_empty_selectors_raises_value_error(
        self, engine_with_main: PywinautoEngine,
    ) -> None:
        with pytest.raises(ValueError, match="selectors must be non-empty"):
            engine_with_main._try_selectors_sequential(
                parent=MagicMock(),
                selectors=[],
                action=lambda w: w.click_input(),
                error_cls=SaveButtonNotFoundError,
                field_name="ダミー要素",
            )


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

    def test_falls_back_to_direct_close_when_confirm_dialog_missing(
        self, engine_with_main: PywinautoEngine,
    ) -> None:
        """確認ダイアログ未出現時に ``_main_window.close()`` 直接終了 fallback を選ぶこと."""
        mock_btn_wrapper = MagicMock()
        mock_btn_wrapper.handle = 0xCAFE
        mock_btn = MagicMock()
        mock_btn.wrapper_object.return_value = mock_btn_wrapper
        engine_with_main._main_window.child_window.return_value = mock_btn

        _mock_user32.PostMessageW.return_value = 1

        # ``_app.window(title_re=".*確認.*")`` が ElementNotFoundError を投げる
        engine_with_main._app.window.side_effect = _ElementNotFoundError("no confirm dialog")
        engine_with_main._app.process = 7777

        # close_wiseman は cleanup 時に _main_window = None にリセットするため、
        # mock の close() 呼出を assert する前に参照を保持する。
        mock_main_ref = engine_with_main._main_window

        with (
            patch.object(os, "kill", side_effect=ProcessLookupError),
            patch("time.sleep"),
            patch("time.monotonic", side_effect=[0, 0.1]),
        ):
            engine_with_main.close_wiseman()

        # 直接 close() が呼ばれたこと、cleanup 完了
        mock_main_ref.close.assert_called_once()
        assert engine_with_main._main_window is None
        assert engine_with_main._app is None

    def test_yes_button_click_fails_falls_back_to_direct_close(
        self, engine_with_main: PywinautoEngine,
    ) -> None:
        """確認ダイアログ visible だが「はい」click 失敗 → except 句で catch → 直接 close fallback."""
        mock_btn_wrapper = MagicMock()
        mock_btn_wrapper.handle = 0xFADE
        mock_btn = MagicMock()
        mock_btn.wrapper_object.return_value = mock_btn_wrapper

        _mock_user32.PostMessageW.return_value = 1

        # 確認ダイアログ自体は取得・visible 待機まで成功するが、内部の「はい」要素 click_input が失敗
        mock_confirm = MagicMock()
        mock_yes = MagicMock()
        mock_yes.click_input.side_effect = _ElementNotFoundError("はい button not found")
        mock_confirm.child_window.return_value = mock_yes

        # _main_window.child_window(auto_id="btnExit") と _app.window(title_re=".*確認.*")
        # の双方を分岐させるため side_effect を分ける
        engine_with_main._main_window.child_window.return_value = mock_btn
        engine_with_main._app.window.return_value = mock_confirm
        engine_with_main._app.process = 5555

        mock_main_ref = engine_with_main._main_window

        with (
            patch.object(os, "kill", side_effect=ProcessLookupError),
            patch("time.sleep"),
            patch("time.monotonic", side_effect=[0, 0.1]),
        ):
            engine_with_main.close_wiseman()

        mock_main_ref.close.assert_called_once()
        assert engine_with_main._main_window is None
        assert engine_with_main._app is None

    def test_permission_error_during_pid_check_continues(
        self, engine_with_main: PywinautoEngine,
    ) -> None:
        """``os.kill(pid, 0)`` で PermissionError → 終了確認を継続し ProcessLookupError で cleanup."""
        mock_btn_wrapper = MagicMock()
        mock_btn_wrapper.handle = 0xBEEF
        mock_btn = MagicMock()
        mock_btn.wrapper_object.return_value = mock_btn_wrapper
        engine_with_main._main_window.child_window.return_value = mock_btn

        _mock_user32.PostMessageW.return_value = 1

        mock_confirm = MagicMock()
        engine_with_main._app.window.return_value = mock_confirm
        engine_with_main._app.process = 6666

        # 1 回目: PermissionError (pass で続行) → 2 回目: ProcessLookupError (break)
        kill_side_effects = [PermissionError("access denied"), ProcessLookupError]

        with (
            patch.object(os, "kill", side_effect=kill_side_effects),
            patch("time.sleep"),
            patch("time.monotonic", side_effect=[0, 0.1, 0.2]),
        ):
            engine_with_main.close_wiseman()

        # 最終的に cleanup される (timeout warning に流れていないこと = _main_window/_app が None)
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
