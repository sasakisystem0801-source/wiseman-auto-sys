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
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("TK_SILENCE_DEPRECATION", "1")

from wiseman_hub.config import AppConfig  # noqa: E402
from wiseman_hub.ui.launcher import (  # noqa: E402
    Launcher,
    LauncherAction,
    ReviewCallbackResult,
    validate_config_ready,
)

# ---------------------------------------------------------------------------
# Pure logic tests (Tk 非依存)
# ---------------------------------------------------------------------------


class TestReviewCallbackResult:
    """``ReviewCallbackResult`` dataclass の不変条件。

    cancel / 通常完了 / 第三状態（Phase B 明示スキップ）の 3 状態を
    should_phase_b プロパティ 1 つで判定可能にする。
    """

    def test_default_is_cancel_equivalent(self) -> None:
        """既定値（``ReviewCallbackResult()``）は cancel 相当 = should_phase_b False。"""
        result = ReviewCallbackResult()
        assert result.session_id is None
        assert result.should_run_phase_b is True  # 既定 True だが session_id None なので結果 False
        assert result.should_phase_b is False

    def test_session_id_with_default_phase_b_runs(self) -> None:
        """session_id 指定 + 既定値 should_run_phase_b=True → 通常 Phase B 起動。"""
        result = ReviewCallbackResult(session_id="20260101T120000Z-abcd1234")
        assert result.should_phase_b is True

    def test_session_id_with_phase_b_skipped_does_not_run(self) -> None:
        """session_id があっても should_run_phase_b=False なら Phase B スキップ（第三状態）。"""
        result = ReviewCallbackResult(
            session_id="20260101T120000Z-abcd1234",
            should_run_phase_b=False,
        )
        assert result.session_id == "20260101T120000Z-abcd1234"
        assert result.should_phase_b is False

    def test_frozen_prevents_mutation(self) -> None:
        """``frozen=True`` のため属性変更は禁止。"""
        result = ReviewCallbackResult(session_id="s1")
        with pytest.raises(FrozenInstanceError):
            result.session_id = "s2"  # type: ignore[misc]


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

    def test_whitespace_only_values_return_false(self) -> None:
        """空白のみの文字列は未設定として扱う（TOML 編集ミス検出）。"""
        cfg = AppConfig()
        cfg.pdf_merge.input_dir = "   "
        cfg.pdf_merge.output_dir = "/out"
        cfg.pdf_merge.source_a_filename = "A.pdf"
        cfg.ocr_backend.endpoint_url = "https://example.com"
        cfg.ocr_backend.api_key = "key"

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


# Tk 利用可否判定は ``conftest.py`` の ``@pytest.mark.tk_required`` に集約（プロセス内
# での Tk 生成試行を 1 回に抑え、macOS uv python で累積する Tcl global state による
# hang を防ぐ）。
tk_required = pytest.mark.tk_required


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
        """AC-L-2 基盤: 設定完了で「PDF マージ処理」押下 → on_run_pdf_merge 呼ばれる。

        13B 以降は worker thread で実行されるため ``wait_until_idle`` で待機する。
        """
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
            launcher.wait_until_idle(timeout=5.0)
        finally:
            root.destroy()

        assert called == ["run"]

    def test_open_review_calls_on_open_review(self, tmp_path: Path) -> None:
        """AC-L-3 基盤: 「確認待ち」押下 → on_open_review が呼ばれる。"""
        import tkinter as tk

        config_path = tmp_path / "config.toml"
        config_path.write_text("", encoding="utf-8")

        called: list[str] = []

        def open_review() -> ReviewCallbackResult:
            called.append("review")
            return ReviewCallbackResult()

        root = tk.Tk()
        try:
            launcher = Launcher(
                config=AppConfig(),
                config_path=config_path,
                root=root,
                on_open_review=open_review,
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

    def test_default_on_config_missing_shows_error_and_opens_settings(
        self, tmp_path: Path
    ) -> None:
        """AC-L-4: 設定未完了時 showerror → 設定 GUI 誘導（OPEN_SETTINGS 起動）。"""
        import tkinter as tk

        config_path = tmp_path / "config.toml"
        config_path.write_text("", encoding="utf-8")

        shown: list[tuple[str, str, str]] = []  # (type, title, message)

        class FakeMessageBox:
            def askyesno(self, title: str, message: str) -> bool:
                return True

            def showinfo(self, title: str, message: str) -> None:
                shown.append(("info", title, message))

            def showerror(self, title: str, message: str) -> None:
                shown.append(("error", title, message))

        settings_opened: list[str] = []

        root = tk.Tk()
        try:
            launcher = Launcher(
                config=AppConfig(),
                config_path=config_path,
                root=root,
                messagebox_fn=FakeMessageBox(),
                on_open_settings=lambda: settings_opened.append("open"),
            )
            launcher.invoke_action(LauncherAction.RUN_PDF_MERGE)
        finally:
            root.destroy()

        assert shown[0][0] == "error"
        assert "設定" in shown[0][2]
        assert settings_opened == ["open"]

    def test_invoke_action_unhandled_value_raises(self, tmp_path: Path) -> None:
        """将来 LauncherAction に値追加 → match default で silent バグ防止。"""
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
            sentinel = object()
            with pytest.raises(ValueError, match="Unhandled LauncherAction"):
                launcher.invoke_action(sentinel)  # type: ignore[arg-type]
        finally:
            root.destroy()

    def test_callback_exception_is_sanitized_in_log(
        self, tmp_path: Path, caplog: Any
    ) -> None:
        """Tk callback 例外のログには例外型名のみ、message（PII を含みうる）は出ない。"""
        import logging
        import tkinter as tk

        config_path = tmp_path / "config.toml"
        config_path.write_text("", encoding="utf-8")

        shown: list[tuple[str, str]] = []

        class FakeMessageBox:
            def askyesno(self, title: str, message: str) -> bool:
                return True

            def showinfo(self, title: str, message: str) -> None:
                pass

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
            with caplog.at_level(logging.ERROR, logger="wiseman_hub.ui.launcher"):
                launcher._on_callback_exception(  # type: ignore[arg-type]
                    ValueError,
                    ValueError("/sensitive/path/to/山田太郎.pdf"),
                    None,
                )
        finally:
            root.destroy()

        logged = " ".join(r.getMessage() for r in caplog.records)
        assert "ValueError" in logged
        assert "山田太郎" not in logged
        assert "/sensitive/path" not in logged
