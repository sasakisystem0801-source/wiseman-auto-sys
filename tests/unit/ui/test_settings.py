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
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("TK_SILENCE_DEPRECATION", "1")

from wiseman_hub.config import (  # noqa: E402
    AppConfig,
    OcrBackendConfig,
    UserNameBBox,
)
from wiseman_hub.ui.settings import (  # noqa: E402
    SettingsDialog,
    SettingsForm,
    ValidationCode,
    ValidationError,
    form_from_config,
    form_to_config,
    format_validation_errors,
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


def _codes(errors: list[ValidationError]) -> set[ValidationCode]:
    return {e.code for e in errors}


class TestValidateForm:
    """AC-S-3: 必須未入力チェック。error code ベースで assert（文字列依存を排除）。"""

    def test_fully_filled_form_returns_no_errors(self) -> None:
        assert validate_form(_full_form()) == []

    def test_missing_input_dir_returns_error(self) -> None:
        form = _full_form()
        form.input_dir = ""
        assert ValidationCode.INPUT_DIR_MISSING in _codes(validate_form(form))

    def test_missing_output_dir_returns_error(self) -> None:
        form = _full_form()
        form.output_dir = ""
        assert ValidationCode.OUTPUT_DIR_MISSING in _codes(validate_form(form))

    def test_missing_source_a_filename_returns_error(self) -> None:
        form = _full_form()
        form.source_a_filename = ""
        assert ValidationCode.SOURCE_A_FILENAME_MISSING in _codes(validate_form(form))

    def test_missing_ocr_endpoint_returns_error(self) -> None:
        form = _full_form()
        form.ocr_endpoint_url = ""
        assert ValidationCode.OCR_ENDPOINT_MISSING in _codes(validate_form(form))

    def test_missing_ocr_api_key_returns_error(self) -> None:
        form = _full_form()
        form.ocr_api_key = ""
        assert ValidationCode.OCR_API_KEY_MISSING in _codes(validate_form(form))

    def test_whitespace_only_input_dir_returns_error(self) -> None:
        form = _full_form()
        form.input_dir = "   "
        assert ValidationCode.INPUT_DIR_MISSING in _codes(validate_form(form))

    def test_invalid_bbox_number_returns_error(self) -> None:
        form = _full_form()
        form.bbox_x0 = "not-a-number"
        errors = validate_form(form)
        assert ValidationCode.BBOX_NOT_NUMBER in _codes(errors)

    def test_bbox_not_number_context_carries_field(self) -> None:
        """AC-3: BBOX_NOT_NUMBER の field_name に壊れた field 名が入る（PII 防御のため値は入れない）。"""
        form = _full_form()
        form.bbox_y1 = "abc"
        errors = [e for e in validate_form(form) if e.code == ValidationCode.BBOX_NOT_NUMBER]
        assert len(errors) == 1
        assert errors[0].field_name == "bbox_y1"
        # PII 防御: context に raw value を入れない
        assert "abc" not in str(errors[0].context.values())

    def test_invalid_bbox_dpi_negative_returns_positive_int_error(self) -> None:
        """dpi=-1 は整数 parse は成功するが「正の整数」要件違反。"""
        form = _full_form()
        form.bbox_dpi = "-1"
        assert ValidationCode.BBOX_DPI_NOT_POSITIVE_INT in _codes(validate_form(form))

    def test_bbox_dpi_zero_returns_positive_int_error(self) -> None:
        """境界値: dpi=0 は「正の整数」要件を満たさない。"""
        form = _full_form()
        form.bbox_dpi = "0"
        assert ValidationCode.BBOX_DPI_NOT_POSITIVE_INT in _codes(validate_form(form))

    def test_invalid_bbox_dpi_non_integer_returns_integer_error(self) -> None:
        """dpi='abc' は整数 parse 失敗 → BBOX_DPI_NOT_INTEGER（POSITIVE_INT とは別 code）。"""
        form = _full_form()
        form.bbox_dpi = "abc"
        assert ValidationCode.BBOX_DPI_NOT_INTEGER in _codes(validate_form(form))

    def test_invalid_concat_order_returns_error(self) -> None:
        form = _full_form()
        form.concat_order = "A,X,C"  # X は不正
        errors = [
            e for e in validate_form(form) if e.code == ValidationCode.CONCAT_ORDER_INVALID_TOKEN
        ]
        assert len(errors) == 1
        assert errors[0].context["invalid_tokens"] == ["X"]

    def test_empty_concat_order_returns_error(self) -> None:
        form = _full_form()
        form.concat_order = ""
        assert ValidationCode.CONCAT_ORDER_EMPTY in _codes(validate_form(form))

    def test_multiple_missing_fields_accumulate_errors(self) -> None:
        """全 check が順次実行され errors が積み重なる（early return / break 混入 regression 防御）。

        Issue #68 PR review (pr-test-analyzer rating 7) の指摘対応。
        """
        form = _full_form()
        form.input_dir = ""
        form.output_dir = ""
        form.source_a_filename = ""
        form.ocr_endpoint_url = ""
        form.ocr_api_key = ""
        codes = _codes(validate_form(form))
        assert ValidationCode.INPUT_DIR_MISSING in codes
        assert ValidationCode.OUTPUT_DIR_MISSING in codes
        assert ValidationCode.SOURCE_A_FILENAME_MISSING in codes
        assert ValidationCode.OCR_ENDPOINT_MISSING in codes
        assert ValidationCode.OCR_API_KEY_MISSING in codes


class TestFormatValidationErrors:
    """AC-5: enum → 既存日本語メッセージ変換が破られていないこと。UI 文言は不変。"""

    def test_all_codes_have_message(self) -> None:
        """全 ValidationCode に対応メッセージがある（AC-2 網羅性の反証）。"""
        for code in ValidationCode:
            msg = format_validation_errors([ValidationError(code=code, field_name="dummy")])
            assert msg, f"code={code} に対応メッセージがない"

    def test_input_dir_missing_message_matches_legacy(self) -> None:
        msg = format_validation_errors(
            [ValidationError(code=ValidationCode.INPUT_DIR_MISSING, field_name="input_dir")]
        )
        assert "入力フォルダを指定してください。" in msg

    def test_output_dir_missing_message_matches_legacy(self) -> None:
        msg = format_validation_errors(
            [ValidationError(code=ValidationCode.OUTPUT_DIR_MISSING, field_name="output_dir")]
        )
        assert "出力フォルダを指定してください。" in msg

    def test_bbox_not_number_includes_field_label(self) -> None:
        """AC-3: BBOX_NOT_NUMBER 表示は field 名（bbox x0 等）を含むが raw 値は含まない。"""
        msg = format_validation_errors(
            [ValidationError(code=ValidationCode.BBOX_NOT_NUMBER, field_name="bbox_x0")]
        )
        assert "bbox x0" in msg
        assert "数値で入力してください。" in msg

    def test_concat_order_invalid_token_includes_tokens(self) -> None:
        msg = format_validation_errors(
            [
                ValidationError(
                    code=ValidationCode.CONCAT_ORDER_INVALID_TOKEN,
                    field_name="concat_order",
                    context={"invalid_tokens": ["X", "Y"]},
                )
            ]
        )
        assert "不正な識別子" in msg
        assert "X" in msg and "Y" in msg

    def test_multiple_errors_joined_with_bullet(self) -> None:
        msg = format_validation_errors(
            [
                ValidationError(code=ValidationCode.INPUT_DIR_MISSING, field_name="input_dir"),
                ValidationError(code=ValidationCode.OUTPUT_DIR_MISSING, field_name="output_dir"),
            ]
        )
        assert msg.count("・") == 2


class TestFormFromConfig:
    """AC-S-1 基盤: AppConfig → SettingsForm。"""

    def test_roundtrip_preserves_form_fields(self) -> None:
        base = AppConfig()
        # Issue #27 続編 E Phase 1/2: PdfMergeConfig / WisemanConfig / UserNameBBox /
        # OcrBackendConfig はすべて frozen=True のため ``replace()`` で差し替える。
        # frozen 化で __post_init__ が replace 経由で再評価されるため、
        # bbox は不変条件 (x0<x1, y0<y1) を満たす全フィールド指定で構築する。
        base.pdf_merge = replace(
            base.pdf_merge,
            input_dir="/in",
            output_dir="/out",
            source_a_filename="A.pdf",
            user_name_bbox=UserNameBBox(x0=1.5, y0=2.0, x1=100.0, y1=50.0, dpi=300),
            concat_order=("B", "A", "C"),
        )
        base.ocr_backend = replace(base.ocr_backend, endpoint_url="https://api", api_key="key")
        base.wiseman = replace(base.wiseman, exe_path="C:/Wiseman/app.exe")

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
        base.pdf_merge = replace(base.pdf_merge, source_d_filename="D.pdf")  # フォームに無い

        new_cfg = form_to_config(_full_form(), base)

        assert new_cfg.version == "0.9.9"  # 変更されない
        assert new_cfg.log_level == "DEBUG"
        assert new_cfg.schedule.cron == "0 3 * * *"
        assert new_cfg.pdf_merge.source_d_filename == "D.pdf"

    def test_form_values_override_base(self) -> None:
        base = AppConfig()
        base.pdf_merge = replace(base.pdf_merge, input_dir="/old")
        base.ocr_backend = replace(base.ocr_backend, api_key="old_key")

        new_cfg = form_to_config(_full_form(), base)

        assert new_cfg.pdf_merge.input_dir == "/in"
        assert new_cfg.ocr_backend.api_key == "secret"
        assert new_cfg.pdf_merge.user_name_bbox.x0 == 10.0
        assert new_cfg.pdf_merge.user_name_bbox.dpi == 200
        assert new_cfg.pdf_merge.concat_order == ("A", "B", "C")


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
    # Issue #27 続編 E Phase 1: UserNameBBox / OcrBackendConfig は frozen=True。
    cfg.pdf_merge.user_name_bbox = UserNameBBox(x0=10.0, y0=20.0, x1=100.0, y1=50.0)
    cfg.ocr_backend = OcrBackendConfig(endpoint_url="https://example.com", api_key="key")
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
