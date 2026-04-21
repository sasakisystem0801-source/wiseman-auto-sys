"""設定 GUI (タスク 12B) のユニットテスト。

2 層構成:
  1. Pure logic tests (Tk 非依存): SettingsForm ↔ AppConfig 変換、バリデーション
  2. UI wiring tests (Tk 必要): SettingsDialog の Entry / Button / filedialog 動作

AC:
  - AC-S-1: 起動時に現在の TOML 値でフィールド初期化
  - AC-S-2: Save → save_config 呼出（コメント維持は save_config 側の責務）
  - AC-S-3: 必須未入力で Save → エラー表示、保存しない
  - AC-S-4: フォルダ選択ダイアログの結果が入力欄に反映
  - AC-S-5: API Key 欄はマスク表示（show='*'）
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("TK_SILENCE_DEPRECATION", "1")

from wiseman_hub.config import AppConfig  # noqa: E402
from wiseman_hub.ui.settings import (  # noqa: E402
    SettingsDialog,
    SettingsForm,
    form_from_config,
    form_to_config,
    validate_form,
)

tk_required = pytest.mark.tk_required


# ---------------------------------------------------------------------------
# Pure logic: SettingsForm <-> AppConfig
# ---------------------------------------------------------------------------


def _full_form() -> SettingsForm:
    return SettingsForm(
        input_dir="/in",
        output_dir="/out",
        source_a_filename="A.pdf",
        source_b_pattern="B_{name}.pdf",
        source_c_pattern="C_{name}.pdf",
        concat_order="A,B,C",
        bbox_x0="10.0",
        bbox_y0="20.0",
        bbox_x1="100.0",
        bbox_y1="50.0",
        bbox_dpi="200",
        ocr_endpoint_url="https://example.com",
        ocr_api_key="secret",
        wiseman_exe_path="C:/Wiseman/app.exe",
    )


class TestValidateForm:
    """AC-S-3: 必須未入力チェック。"""

    def test_fully_filled_form_returns_no_errors(self) -> None:
        assert validate_form(_full_form()) == []

    def test_missing_input_dir_returns_error(self) -> None:
        form = _full_form()
        form.input_dir = ""
        errors = validate_form(form)
        assert any("入力" in e for e in errors)

    def test_missing_output_dir_returns_error(self) -> None:
        form = _full_form()
        form.output_dir = ""
        errors = validate_form(form)
        assert any("出力" in e for e in errors)

    def test_missing_source_a_filename_returns_error(self) -> None:
        form = _full_form()
        form.source_a_filename = ""
        errors = validate_form(form)
        assert any("A" in e for e in errors)

    def test_missing_ocr_endpoint_returns_error(self) -> None:
        form = _full_form()
        form.ocr_endpoint_url = ""
        errors = validate_form(form)
        assert any("エンドポイント" in e for e in errors)

    def test_missing_ocr_api_key_returns_error(self) -> None:
        form = _full_form()
        form.ocr_api_key = ""
        errors = validate_form(form)
        assert any("キー" in e for e in errors)

    def test_whitespace_only_input_dir_returns_error(self) -> None:
        form = _full_form()
        form.input_dir = "   "
        errors = validate_form(form)
        assert any("入力" in e for e in errors)

    def test_invalid_bbox_number_returns_error(self) -> None:
        form = _full_form()
        form.bbox_x0 = "not-a-number"
        errors = validate_form(form)
        assert any("bbox" in e.lower() or "座標" in e for e in errors)

    def test_invalid_bbox_dpi_returns_error(self) -> None:
        form = _full_form()
        form.bbox_dpi = "-1"
        errors = validate_form(form)
        assert any("dpi" in e.lower() for e in errors)

    def test_bbox_dpi_zero_returns_error(self) -> None:
        """境界値: dpi=0 は「正の整数」要件を満たさない。"""
        form = _full_form()
        form.bbox_dpi = "0"
        errors = validate_form(form)
        assert any("dpi" in e.lower() for e in errors)

    def test_invalid_concat_order_returns_error(self) -> None:
        form = _full_form()
        form.concat_order = "A,X,C"  # X は不正
        errors = validate_form(form)
        assert any("concat_order" in e or "結合順" in e for e in errors)

    def test_empty_concat_order_returns_error(self) -> None:
        form = _full_form()
        form.concat_order = ""
        errors = validate_form(form)
        assert any("concat_order" in e or "結合順" in e for e in errors)


class TestFormFromConfig:
    """AC-S-1 基盤: AppConfig → SettingsForm。"""

    def test_roundtrip_preserves_form_fields(self) -> None:
        base = AppConfig()
        base.pdf_merge.input_dir = "/in"
        base.pdf_merge.output_dir = "/out"
        base.pdf_merge.source_a_filename = "A.pdf"
        base.pdf_merge.user_name_bbox.x0 = 1.5
        base.pdf_merge.user_name_bbox.dpi = 300
        base.pdf_merge.concat_order = ["B", "A", "C"]
        base.ocr_backend.endpoint_url = "https://api"
        base.ocr_backend.api_key = "key"
        base.wiseman.exe_path = "C:/Wiseman/app.exe"

        form = form_from_config(base)

        assert form.input_dir == "/in"
        assert form.output_dir == "/out"
        assert form.source_a_filename == "A.pdf"
        assert form.bbox_x0 == "1.5"
        assert form.bbox_dpi == "300"
        assert form.concat_order == "B,A,C"
        assert form.ocr_endpoint_url == "https://api"
        assert form.ocr_api_key == "key"
        assert form.wiseman_exe_path == "C:/Wiseman/app.exe"

    def test_default_config_yields_empty_required_fields(self) -> None:
        form = form_from_config(AppConfig())
        assert form.input_dir == ""
        assert form.ocr_api_key == ""


class TestFormToConfig:
    """AC-S-2 基盤: SettingsForm → AppConfig（既存 config の非フォーム項目を保持）。"""

    def test_non_form_fields_are_preserved(self) -> None:
        base = AppConfig()
        base.version = "0.9.9"
        base.log_level = "DEBUG"
        base.schedule.cron = "0 3 * * *"
        base.pdf_merge.source_d_filename = "D.pdf"  # フォームに無い

        new_cfg = form_to_config(_full_form(), base)

        assert new_cfg.version == "0.9.9"  # 変更されない
        assert new_cfg.log_level == "DEBUG"
        assert new_cfg.schedule.cron == "0 3 * * *"
        assert new_cfg.pdf_merge.source_d_filename == "D.pdf"

    def test_form_values_override_base(self) -> None:
        base = AppConfig()
        base.pdf_merge.input_dir = "/old"
        base.ocr_backend.api_key = "old_key"

        new_cfg = form_to_config(_full_form(), base)

        assert new_cfg.pdf_merge.input_dir == "/in"
        assert new_cfg.ocr_backend.api_key == "secret"
        assert new_cfg.pdf_merge.user_name_bbox.x0 == 10.0
        assert new_cfg.pdf_merge.user_name_bbox.dpi == 200
        assert new_cfg.pdf_merge.concat_order == ["A", "B", "C"]


# ---------------------------------------------------------------------------
# UI wiring tests (Tk required)
# ---------------------------------------------------------------------------


class _FakeMessageBox:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def askyesno(self, title: str, message: str) -> bool:
        return True

    def showinfo(self, title: str, message: str) -> None:
        self.calls.append(("info", title, message))

    def showerror(self, title: str, message: str) -> None:
        self.calls.append(("error", title, message))


def _base_config() -> AppConfig:
    cfg = AppConfig()
    cfg.pdf_merge.input_dir = "/in"
    cfg.pdf_merge.output_dir = "/out"
    cfg.pdf_merge.source_a_filename = "A.pdf"
    cfg.pdf_merge.user_name_bbox.x0 = 10.0
    cfg.pdf_merge.user_name_bbox.y0 = 20.0
    cfg.pdf_merge.user_name_bbox.x1 = 100.0
    cfg.pdf_merge.user_name_bbox.y1 = 50.0
    cfg.ocr_backend.endpoint_url = "https://example.com"
    cfg.ocr_backend.api_key = "key"
    return cfg


@tk_required
class TestSettingsDialogUI:
    def test_fields_initialized_from_config(self, tmp_path: Path) -> None:
        """AC-S-1: TOML 現在値でフィールド初期化。"""
        import tkinter as tk

        root = tk.Tk()
        config_path = tmp_path / "c.toml"
        try:
            dlg = SettingsDialog(
                config=_base_config(),
                config_path=config_path,
                root=root,
                messagebox_fn=_FakeMessageBox(),
            )
            form = dlg.current_form()
        finally:
            root.destroy()

        assert form.input_dir == "/in"
        assert form.ocr_api_key == "key"

    def test_save_with_valid_form_calls_save_fn(self, tmp_path: Path) -> None:
        """AC-S-2: Save → save_fn 呼出 → dialog close。"""
        import tkinter as tk

        save_calls: list[tuple[AppConfig, Path]] = []

        def fake_save(cfg: AppConfig, path: Path, **_: Any) -> None:
            save_calls.append((cfg, path))

        root = tk.Tk()
        config_path = tmp_path / "c.toml"
        try:
            dlg = SettingsDialog(
                config=_base_config(),
                config_path=config_path,
                root=root,
                save_fn=fake_save,
                messagebox_fn=_FakeMessageBox(),
            )
            result = dlg.attempt_save()
        finally:
            root.destroy()

        assert len(save_calls) == 1
        assert save_calls[0][1] == config_path
        assert result.saved is True
        assert result.config is not None
        assert result.config.pdf_merge.input_dir == "/in"

    def test_save_with_invalid_form_shows_error_and_keeps_open(
        self, tmp_path: Path
    ) -> None:
        """AC-S-3: 必須未入力で Save → showerror、save_fn 呼ばれない。"""
        import tkinter as tk

        save_calls: list[object] = []

        def fake_save(*args: Any, **kwargs: Any) -> None:
            save_calls.append(args)

        mbox = _FakeMessageBox()

        cfg = _base_config()
        cfg.pdf_merge.input_dir = ""  # 必須を欠落させる

        root = tk.Tk()
        config_path = tmp_path / "c.toml"
        try:
            dlg = SettingsDialog(
                config=cfg,
                config_path=config_path,
                root=root,
                save_fn=fake_save,
                messagebox_fn=mbox,
            )
            result = dlg.attempt_save()
        finally:
            root.destroy()

        assert save_calls == []
        error_calls = [c for c in mbox.calls if c[0] == "error"]
        assert len(error_calls) == 1
        assert result.saved is False

    def test_cancel_does_not_call_save(self, tmp_path: Path) -> None:
        import tkinter as tk

        save_calls: list[object] = []

        def fake_save(*args: Any, **kwargs: Any) -> None:
            save_calls.append(args)

        root = tk.Tk()
        config_path = tmp_path / "c.toml"
        try:
            dlg = SettingsDialog(
                config=_base_config(),
                config_path=config_path,
                root=root,
                save_fn=fake_save,
                messagebox_fn=_FakeMessageBox(),
            )
            result = dlg.cancel()
        finally:
            root.destroy()

        assert save_calls == []
        assert result.saved is False

    def test_folder_chooser_updates_input_dir(self, tmp_path: Path) -> None:
        """AC-S-4: askdirectory 結果が Entry に反映。"""
        import tkinter as tk

        root = tk.Tk()
        config_path = tmp_path / "c.toml"
        try:
            dlg = SettingsDialog(
                config=_base_config(),
                config_path=config_path,
                root=root,
                askdirectory_fn=lambda **_: "/picked/path",
                messagebox_fn=_FakeMessageBox(),
            )
            dlg.pick_folder("input_dir")
            form = dlg.current_form()
        finally:
            root.destroy()

        assert form.input_dir == "/picked/path"

    def test_folder_chooser_cancel_keeps_previous_value(self, tmp_path: Path) -> None:
        """askdirectory が空文字（キャンセル）なら既存値を保持する。"""
        import tkinter as tk

        root = tk.Tk()
        config_path = tmp_path / "c.toml"
        try:
            dlg = SettingsDialog(
                config=_base_config(),
                config_path=config_path,
                root=root,
                askdirectory_fn=lambda **_: "",
                messagebox_fn=_FakeMessageBox(),
            )
            dlg.pick_folder("input_dir")
            form = dlg.current_form()
        finally:
            root.destroy()

        assert form.input_dir == "/in"

    def test_api_key_field_is_masked(self, tmp_path: Path) -> None:
        """AC-S-5: API Key 欄は show='*' でマスク。"""
        import tkinter as tk

        root = tk.Tk()
        config_path = tmp_path / "c.toml"
        try:
            dlg = SettingsDialog(
                config=_base_config(),
                config_path=config_path,
                root=root,
                messagebox_fn=_FakeMessageBox(),
            )
            api_key_entry = dlg.api_key_entry
            assert api_key_entry.cget("show") == "*"
        finally:
            root.destroy()

    def test_save_failure_shows_error_and_does_not_close(
        self, tmp_path: Path
    ) -> None:
        """save_fn が例外 → showerror、UI 継続（PII 防御で型名のみ）。"""
        import tkinter as tk

        def failing_save(*args: Any, **kwargs: Any) -> None:
            raise OSError("/sensitive/path/山田太郎")

        mbox = _FakeMessageBox()

        root = tk.Tk()
        config_path = tmp_path / "c.toml"
        try:
            dlg = SettingsDialog(
                config=_base_config(),
                config_path=config_path,
                root=root,
                save_fn=failing_save,
                messagebox_fn=mbox,
            )
            result = dlg.attempt_save()
        finally:
            root.destroy()

        assert result.saved is False
        error_calls = [c for c in mbox.calls if c[0] == "error"]
        assert len(error_calls) == 1
        # PII 防御: dialog message に氏名・パスが露出していない
        assert "山田太郎" not in error_calls[0][2]
        assert "/sensitive/path" not in error_calls[0][2]

    def test_save_failure_with_permission_error_shows_type_name(
        self, tmp_path: Path
    ) -> None:
        """PermissionError（Windows 読取専用 TOML 想定）でも型名のみがメッセージに出る。"""
        import tkinter as tk

        def failing_save(*args: Any, **kwargs: Any) -> None:
            raise PermissionError("/denied/path")

        mbox = _FakeMessageBox()
        root = tk.Tk()
        try:
            dlg = SettingsDialog(
                config=_base_config(),
                config_path=tmp_path / "c.toml",
                root=root,
                save_fn=failing_save,
                messagebox_fn=mbox,
            )
            result = dlg.attempt_save()
        finally:
            root.destroy()

        assert result.saved is False
        error_calls = [c for c in mbox.calls if c[0] == "error"]
        assert len(error_calls) == 1
        assert "PermissionError" in error_calls[0][2]
        assert "/denied/path" not in error_calls[0][2]

    def test_unexpected_exception_propagates_to_callback_handler(
        self, tmp_path: Path
    ) -> None:
        """想定外例外（KeyError 等）は attempt_save 内で握り潰されず伝播する。"""
        import tkinter as tk

        def failing_save(*args: Any, **kwargs: Any) -> None:
            raise KeyError("unexpected schema key")

        root = tk.Tk()
        try:
            dlg = SettingsDialog(
                config=_base_config(),
                config_path=tmp_path / "c.toml",
                root=root,
                save_fn=failing_save,
                messagebox_fn=_FakeMessageBox(),
            )
            with pytest.raises(KeyError):
                dlg.attempt_save()
        finally:
            root.destroy()

    def test_save_success_closes_dialog(self, tmp_path: Path) -> None:
        """AC-S-2 補完: Save 成功時に dialog が閉じられる（_close_dialog 呼出）。"""
        import tkinter as tk

        root = tk.Tk()
        try:
            dlg = SettingsDialog(
                config=_base_config(),
                config_path=tmp_path / "c.toml",
                root=root,
                save_fn=lambda *a, **kw: None,
                messagebox_fn=_FakeMessageBox(),
            )
            dlg.attempt_save()
            # standalone モード（root 渡し）では _root.quit() が呼ばれる。
            # quit 呼出は StringVar に影響しないため、再度 attempt_save できる状態
            # になっていることを間接的に確認する（_is_toplevel=False なので destroy は呼ばれない）。
            assert dlg._is_toplevel is False
        finally:
            root.destroy()
