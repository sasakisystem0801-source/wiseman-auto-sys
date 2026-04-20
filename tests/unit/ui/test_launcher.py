"""ランチャー GUI のユニットテスト（AC-L-1 / AC-L-4）。

2 層構成（ConfirmDialog と同じパターン）:
  1. Pure logic tests (Tk 非依存): ボタン押下ハンドラのロジック、設定検証、
     遷移判定 — 常に実行。
  2. UI wiring tests (Tk 必要): Launcher クラスの _build_ui / button.invoke()
     — Tk ランタイム利用可能な環境のみ（macOS uv python では skip）。

13A のスコープ:
- 3 ボタンの骨格（「PDF 処理」「確認待ちセッション」「設定」）
- 「設定」は 12B でスタブ、ここでは click で未実装メッセージ
- AC-L-2 / AC-L-3 の Phase A / Phase B 統合は 13B / 13C で追加実装
"""

from __future__ import annotations

import os
from functools import cache
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("TK_SILENCE_DEPRECATION", "1")

from wiseman_hub.config import AppConfig  # noqa: E402
from wiseman_hub.ui.launcher import Launcher, LauncherAction, validate_config_ready  # noqa: E402

# ---------------------------------------------------------------------------
# Pure logic tests (Tk 非依存)
# ---------------------------------------------------------------------------


class TestValidateConfigReady:
    """validate_config_ready(): AC-L-4 の事前条件チェック。

    必須設定（pdf_merge.input_dir/output_dir/source_a_filename、ocr_backend.endpoint_url/api_key）
    がすべて空でない場合に True、一つでも欠けていれば False を返す。
    """

    def test_fully_configured_returns_true(self) -> None:
        cfg = AppConfig()
        cfg.pdf_merge.input_dir = "/in"
        cfg.pdf_merge.output_dir = "/out"
        cfg.pdf_merge.source_a_filename = "A.pdf"
        cfg.ocr_backend.endpoint_url = "https://example.com"
        cfg.ocr_backend.api_key = "key"

        assert validate_config_ready(cfg) is True

    def test_empty_input_dir_returns_false(self) -> None:
        cfg = AppConfig()
        cfg.pdf_merge.output_dir = "/out"
        cfg.pdf_merge.source_a_filename = "A.pdf"
        cfg.ocr_backend.endpoint_url = "https://example.com"
        cfg.ocr_backend.api_key = "key"

        assert validate_config_ready(cfg) is False

    def test_empty_output_dir_returns_false(self) -> None:
        cfg = AppConfig()
        cfg.pdf_merge.input_dir = "/in"
        cfg.pdf_merge.source_a_filename = "A.pdf"
        cfg.ocr_backend.endpoint_url = "https://example.com"
        cfg.ocr_backend.api_key = "key"

        assert validate_config_ready(cfg) is False

    def test_empty_source_a_filename_returns_false(self) -> None:
        cfg = AppConfig()
        cfg.pdf_merge.input_dir = "/in"
        cfg.pdf_merge.output_dir = "/out"
        cfg.ocr_backend.endpoint_url = "https://example.com"
        cfg.ocr_backend.api_key = "key"

        assert validate_config_ready(cfg) is False

    def test_empty_ocr_endpoint_returns_false(self) -> None:
        cfg = AppConfig()
        cfg.pdf_merge.input_dir = "/in"
        cfg.pdf_merge.output_dir = "/out"
        cfg.pdf_merge.source_a_filename = "A.pdf"
        cfg.ocr_backend.api_key = "key"

        assert validate_config_ready(cfg) is False

    def test_empty_ocr_api_key_returns_false(self) -> None:
        cfg = AppConfig()
        cfg.pdf_merge.input_dir = "/in"
        cfg.pdf_merge.output_dir = "/out"
        cfg.pdf_merge.source_a_filename = "A.pdf"
        cfg.ocr_backend.endpoint_url = "https://example.com"

        assert validate_config_ready(cfg) is False

    def test_default_config_returns_false(self) -> None:
        """フィールドが全デフォルト（空）の AppConfig → False（AC-L-4）。"""
        cfg = AppConfig()
        assert validate_config_ready(cfg) is False


class TestLauncherAction:
    """LauncherAction enum / 操作名を扱うロジック。"""

    def test_enum_has_three_primary_actions(self) -> None:
        assert LauncherAction.RUN_PDF_MERGE.value == "run_pdf_merge"
        assert LauncherAction.OPEN_REVIEW.value == "open_review"
        assert LauncherAction.OPEN_SETTINGS.value == "open_settings"


# ---------------------------------------------------------------------------
# UI wiring tests (Tk 必要、Windows 実機 + macOS Tk 利用可能環境で実行)
# ---------------------------------------------------------------------------


@cache
def _tk_available() -> bool:
    """Tk が import + root 生成できる環境か判定（プロセス内で 1 回のみ実行）。"""
    try:
        import tkinter as _tk

        root = _tk.Tk()
        root.withdraw()
        root.destroy()
        return True
    except Exception:
        return False


tk_required = pytest.mark.skipif(
    not _tk_available(), reason="Tk runtime not available (skip UI wiring tests)"
)


@tk_required
class TestLauncherUI:
    """Launcher の Tkinter UI 構築・ボタン動作。"""

    def test_launcher_builds_three_buttons(self, tmp_path: Path) -> None:
        """AC-L-1: ランチャー起動時に 3 ボタンが存在する。"""
        import tkinter as tk

        config_path = tmp_path / "config.toml"
        config_path.write_text("", encoding="utf-8")

        root = tk.Tk()
        try:
            launcher = Launcher(
                config=AppConfig(),
                config_path=config_path,
                root=root,
            )
            labels = launcher.button_labels()
            assert len(labels) == 3
            assert any("PDF" in lb for lb in labels)
            assert any("確認" in lb for lb in labels)
            assert any("設定" in lb for lb in labels)
        finally:
            root.destroy()

    def test_run_pdf_merge_with_unconfigured_calls_on_config_missing(
        self, tmp_path: Path
    ) -> None:
        """AC-L-4: 設定未完了で「PDF マージ処理」押下 → on_config_missing が呼ばれる。"""
        import tkinter as tk

        config_path = tmp_path / "config.toml"
        config_path.write_text("", encoding="utf-8")

        called: list[str] = []

        root = tk.Tk()
        try:
            launcher = Launcher(
                config=AppConfig(),
                config_path=config_path,
                root=root,
                on_config_missing=lambda: called.append("missing"),
            )
            launcher.invoke_action(LauncherAction.RUN_PDF_MERGE)
        finally:
            root.destroy()

        assert called == ["missing"]

    def test_run_pdf_merge_with_configured_calls_on_run_pdf_merge(
        self, tmp_path: Path
    ) -> None:
        """AC-L-2 基盤: 設定完了で「PDF マージ処理」押下 → on_run_pdf_merge 呼ばれる。"""
        import tkinter as tk

        config_path = tmp_path / "config.toml"
        config_path.write_text("", encoding="utf-8")

        cfg = AppConfig()
        cfg.pdf_merge.input_dir = "/in"
        cfg.pdf_merge.output_dir = "/out"
        cfg.pdf_merge.source_a_filename = "A.pdf"
        cfg.ocr_backend.endpoint_url = "https://example.com"
        cfg.ocr_backend.api_key = "key"

        called: list[str] = []

        root = tk.Tk()
        try:
            launcher = Launcher(
                config=cfg,
                config_path=config_path,
                root=root,
                on_run_pdf_merge=lambda: called.append("run"),
            )
            launcher.invoke_action(LauncherAction.RUN_PDF_MERGE)
        finally:
            root.destroy()

        assert called == ["run"]

    def test_open_review_calls_on_open_review(self, tmp_path: Path) -> None:
        """AC-L-3 基盤: 「確認待ち」押下 → on_open_review が呼ばれる。"""
        import tkinter as tk

        config_path = tmp_path / "config.toml"
        config_path.write_text("", encoding="utf-8")

        called: list[str] = []

        root = tk.Tk()
        try:
            launcher = Launcher(
                config=AppConfig(),
                config_path=config_path,
                root=root,
                on_open_review=lambda: called.append("review"),
            )
            launcher.invoke_action(LauncherAction.OPEN_REVIEW)
        finally:
            root.destroy()

        assert called == ["review"]

    def test_open_settings_calls_on_open_settings(self, tmp_path: Path) -> None:
        """「設定」押下 → on_open_settings が呼ばれる（12B スタブ先での呼出）。"""
        import tkinter as tk

        config_path = tmp_path / "config.toml"
        config_path.write_text("", encoding="utf-8")

        called: list[str] = []

        root = tk.Tk()
        try:
            launcher = Launcher(
                config=AppConfig(),
                config_path=config_path,
                root=root,
                on_open_settings=lambda: called.append("settings"),
            )
            launcher.invoke_action(LauncherAction.OPEN_SETTINGS)
        finally:
            root.destroy()

        assert called == ["settings"]

    def test_default_on_open_settings_shows_placeholder_message(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """on_open_settings 未指定時、既定のプレースホルダメッセージが出る（12B 未完の間）。"""
        import tkinter as tk

        config_path = tmp_path / "config.toml"
        config_path.write_text("", encoding="utf-8")

        shown: list[tuple[str, str]] = []

        class FakeMessageBox:
            def askyesno(self, title: str, message: str) -> bool:
                return True

            def showinfo(self, title: str, message: str) -> None:
                shown.append((title, message))

            def showerror(self, title: str, message: str) -> None:
                shown.append((title, message))

        root = tk.Tk()
        try:
            launcher = Launcher(
                config=AppConfig(),
                config_path=config_path,
                root=root,
                messagebox_fn=FakeMessageBox(),
            )
            launcher.invoke_action(LauncherAction.OPEN_SETTINGS)
        finally:
            root.destroy()

        assert len(shown) == 1
        assert "設定" in shown[0][0]

    def test_default_on_config_missing_shows_error_dialog(
        self, tmp_path: Path
    ) -> None:
        """on_config_missing 未指定時、既定のエラーダイアログが showerror で表示される。"""
        import tkinter as tk

        config_path = tmp_path / "config.toml"
        config_path.write_text("", encoding="utf-8")

        shown_errors: list[tuple[str, str]] = []

        class FakeMessageBox:
            def askyesno(self, title: str, message: str) -> bool:
                return True

            def showinfo(self, title: str, message: str) -> None:
                pass

            def showerror(self, title: str, message: str) -> None:
                shown_errors.append((title, message))

        root = tk.Tk()
        try:
            launcher = Launcher(
                config=AppConfig(),
                config_path=config_path,
                root=root,
                messagebox_fn=FakeMessageBox(),
            )
            launcher.invoke_action(LauncherAction.RUN_PDF_MERGE)
        finally:
            root.destroy()

        assert len(shown_errors) == 1
        assert "設定" in shown_errors[0][1]
