"""ランチャー GUI のユニットテスト。

Issue #154 で旧ワークフロー UI 経路 (PDF マージ処理 / 確認待ちセッション) を除去。
現在のスコープは 3 ボタン構成 (業務フロー順):
  1. ex_ ファイル変換 + 振り分け (ADR-014, ① 起点)
  2. 事業所フォルダ一括結合 (ADR-013, ③ 一括再結合)
  3. 設定

2 層構成:
  1. Pure logic tests (Tk 非依存): LauncherAction enum / button_labels 等。
  2. UI wiring tests (Tk 必要): _build_ui / button.invoke()
     — Tk ランタイム利用可能な環境のみ (macOS uv python では skip)。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("TK_SILENCE_DEPRECATION", "1")

from wiseman_hub.config import AppConfig  # noqa: E402
from wiseman_hub.ui.launcher import Launcher, LauncherAction  # noqa: E402

# ---------------------------------------------------------------------------
# Pure logic tests (Tk 非依存)
# ---------------------------------------------------------------------------


class TestLauncherAction:
    """LauncherAction enum の値域 (Issue #154 で 3 アクションに整理)。"""

    def test_enum_has_three_primary_actions(self) -> None:
        assert LauncherAction.OPEN_SETTINGS.value == "open_settings"
        assert LauncherAction.OPEN_FACILITY_MERGER.value == "open_facility_merger"
        assert LauncherAction.OPEN_EX_EXTRACTOR.value == "open_ex_extractor"

    def test_enum_does_not_contain_legacy_actions(self) -> None:
        """Issue #154: 旧ワークフロー (PDF マージ / 確認待ちセッション) の
        LauncherAction 値が再追加されていないことを契約として固定する。"""
        legacy = {"run_pdf_merge", "open_review"}
        current_values = {action.value for action in LauncherAction}
        assert not (legacy & current_values), (
            f"legacy LauncherAction values reintroduced: {legacy & current_values}"
        )


# ---------------------------------------------------------------------------
# UI wiring tests (Tk 必要、Windows 実機 + macOS Tk 利用可能環境で実行)
# ---------------------------------------------------------------------------


# Tk 利用可否判定は ``conftest.py`` の ``@pytest.mark.tk_required`` に集約。
tk_required = pytest.mark.tk_required


@tk_required
class TestLauncherUI:
    """Launcher の Tkinter UI 構築・ボタン動作。"""

    def test_launcher_builds_three_buttons_in_workflow_order(
        self, tmp_path: Path
    ) -> None:
        """Issue #154 受け入れ基準: 業務フロー順 3 ボタンで起動する。

        順序: ex_ 変換 (①) → 事業所結合 (③) → 設定。
        """
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
            # 業務フロー順
            assert "ex_" in labels[0]
            assert "事業所" in labels[1]
            assert "設定" in labels[2]
            # 旧ワークフローの文言が UI に出ないことを契約化
            joined = " ".join(labels)
            assert "PDF マージ処理" not in joined
            assert "確認待ちセッション" not in joined
        finally:
            root.destroy()

    def test_open_ex_extractor_calls_callback(self, tmp_path: Path) -> None:
        """「ex_ ファイル変換 + 振り分け」押下 → on_open_ex_extractor 呼出。"""
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
                on_open_ex_extractor=lambda: called.append("ex"),
            )
            launcher.invoke_action(LauncherAction.OPEN_EX_EXTRACTOR)
        finally:
            root.destroy()

        assert called == ["ex"]

    def test_open_facility_merger_calls_callback(self, tmp_path: Path) -> None:
        """「事業所フォルダ一括結合」押下 → on_open_facility_merger 呼出。"""
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
                on_open_facility_merger=lambda: called.append("merger"),
            )
            launcher.invoke_action(LauncherAction.OPEN_FACILITY_MERGER)
        finally:
            root.destroy()

        assert called == ["merger"]

    def test_open_settings_calls_callback(self, tmp_path: Path) -> None:
        """「設定」押下 → on_open_settings 呼出。"""
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
        """on_open_settings 未指定時、既定のプレースホルダメッセージが出る。"""
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
