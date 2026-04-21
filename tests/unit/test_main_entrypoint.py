"""`python -m wiseman_hub` エントリポイントのテスト。

--rpa 指定: WisemanHub が呼ばれる
--rpa 省略: Launcher が呼ばれる
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest


def test_default_starts_launcher(tmp_path: Path, monkeypatch: Any) -> None:
    """既定（引数なし）で Launcher が起動される。"""
    config_file = tmp_path / "config.toml"
    config_file.write_text("", encoding="utf-8")

    launcher_instance = MagicMock()
    launcher_class = MagicMock(return_value=launcher_instance)
    monkeypatch.setattr("wiseman_hub.ui.launcher.Launcher", launcher_class)

    monkeypatch.setattr(sys, "argv", ["wiseman-hub", "--config", str(config_file)])

    from wiseman_hub.__main__ import main

    main()

    launcher_class.assert_called_once()
    launcher_instance.run.assert_called_once()


def test_default_injects_phase_a_callback(tmp_path: Path, monkeypatch: Any) -> None:
    """既定起動時に Launcher へ ``on_run_pdf_merge`` コールバックが注入される（AC-L-2）。"""
    config_file = tmp_path / "config.toml"
    config_file.write_text("", encoding="utf-8")

    launcher_class = MagicMock()
    monkeypatch.setattr("wiseman_hub.ui.launcher.Launcher", launcher_class)
    monkeypatch.setattr(sys, "argv", ["wiseman-hub", "--config", str(config_file)])

    from wiseman_hub.__main__ import main

    main()

    _, kwargs = launcher_class.call_args
    assert kwargs.get("on_run_pdf_merge") is not None, (
        "Phase A コールバックが Launcher に注入されていない"
    )
    assert callable(kwargs["on_run_pdf_merge"])


def test_rpa_flag_starts_wiseman_hub(tmp_path: Path, monkeypatch: Any) -> None:
    """--rpa 指定で WisemanHub が起動される。"""
    config_file = tmp_path / "config.toml"
    config_file.write_text("", encoding="utf-8")

    hub_instance = MagicMock()
    hub_class = MagicMock(return_value=hub_instance)
    monkeypatch.setattr("wiseman_hub.app.WisemanHub", hub_class)

    monkeypatch.setattr(
        sys, "argv", ["wiseman-hub", "--rpa", "--config", str(config_file)]
    )

    from wiseman_hub.__main__ import main

    main()

    hub_class.assert_called_once()
    hub_instance.run.assert_called_once()


def test_keyboard_interrupt_exits_zero(monkeypatch: Any) -> None:
    """Ctrl+C で exit code 0 終了する。"""
    launcher_class = MagicMock()
    launcher_class.return_value.run.side_effect = KeyboardInterrupt
    monkeypatch.setattr("wiseman_hub.ui.launcher.Launcher", launcher_class)
    monkeypatch.setattr(sys, "argv", ["wiseman-hub"])

    from wiseman_hub.__main__ import main

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0


def test_unexpected_exception_exits_one(monkeypatch: Any) -> None:
    """予期しない例外で exit code 1 終了する。"""
    launcher_class = MagicMock()
    launcher_class.return_value.run.side_effect = RuntimeError("boom")
    monkeypatch.setattr("wiseman_hub.ui.launcher.Launcher", launcher_class)
    monkeypatch.setattr(sys, "argv", ["wiseman-hub"])

    from wiseman_hub.__main__ import main

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1


def test_settings_callback_reloads_launcher_on_save(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """設定ダイアログで保存した直後、Launcher.reload_config に新 config が渡される。"""
    config_file = tmp_path / "config.toml"
    config_file.write_text("", encoding="utf-8")

    from wiseman_hub.config import AppConfig

    saved_config = AppConfig()
    saved_config.pdf_merge.input_dir = "/reloaded"

    class FakeDialog:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def run(self) -> Any:
            from wiseman_hub.ui.settings import SettingsDialogResult

            return SettingsDialogResult(config=saved_config)

    monkeypatch.setattr("wiseman_hub.ui.settings.SettingsDialog", FakeDialog)
    monkeypatch.setattr(
        "wiseman_hub.config.load_config", lambda _p: AppConfig()
    )

    reload_calls: list[AppConfig] = []

    class FakeLauncher:
        def reload_config(self, config: AppConfig) -> None:
            reload_calls.append(config)

    launcher = FakeLauncher()

    from wiseman_hub.__main__ import _make_settings_callback

    callback = _make_settings_callback(config_file, lambda: launcher)
    callback()

    assert len(reload_calls) == 1
    assert reload_calls[0].pdf_merge.input_dir == "/reloaded"


def test_settings_callback_does_not_reload_on_cancel(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """キャンセル（saved=False）時は reload_config が呼ばれない。"""
    config_file = tmp_path / "config.toml"
    config_file.write_text("", encoding="utf-8")

    from wiseman_hub.config import AppConfig

    class FakeDialog:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def run(self) -> Any:
            from wiseman_hub.ui.settings import SettingsDialogResult

            return SettingsDialogResult()

    monkeypatch.setattr("wiseman_hub.ui.settings.SettingsDialog", FakeDialog)
    monkeypatch.setattr(
        "wiseman_hub.config.load_config", lambda _p: AppConfig()
    )

    reload_calls: list[AppConfig] = []

    class FakeLauncher:
        def reload_config(self, config: AppConfig) -> None:
            reload_calls.append(config)

    launcher = FakeLauncher()

    from wiseman_hub.__main__ import _make_settings_callback

    callback = _make_settings_callback(config_file, lambda: launcher)
    callback()

    assert reload_calls == []


def test_phase_a_callback_reloads_config_and_runs_phase_a(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """``_make_phase_a_callback`` の返すコールバックは TOML を再ロードし run_phase_a を呼ぶ。

    設定 GUI（12B）で TOML を書き換えた直後、GUI 再起動なしに新設定で実行できることを保証する。
    """
    config_file = tmp_path / "config.toml"
    config_file.write_text("", encoding="utf-8")

    from wiseman_hub.config import AppConfig

    def fake_load_config(path: Path) -> AppConfig:
        assert path == config_file
        cfg = AppConfig()
        cfg.pdf_merge.input_dir = str(tmp_path / "in")
        cfg.pdf_merge.output_dir = str(tmp_path / "out")
        cfg.pdf_merge.source_a_filename = "A.pdf"
        cfg.ocr_backend.endpoint_url = "https://example.com"
        cfg.ocr_backend.api_key = "k"
        return cfg

    monkeypatch.setattr("wiseman_hub.config.load_config", fake_load_config)

    run_phase_a_mock = MagicMock(return_value=MagicMock())
    monkeypatch.setattr("wiseman_hub.pdf.pipeline.run_phase_a", run_phase_a_mock)
    monkeypatch.setattr("wiseman_hub.pdf.matcher.KanjiMatcher", MagicMock())
    # OcrClient は context manager 呼出を回避するため、__exit__ 非搭載の MagicMock で代替
    ocr_client_stub = MagicMock(spec=[])
    monkeypatch.setattr(
        "wiseman_hub.pdf.ocr_client.OcrClient", MagicMock(return_value=ocr_client_stub)
    )

    from wiseman_hub.__main__ import _make_phase_a_callback

    callback = _make_phase_a_callback(config_file)
    callback()

    run_phase_a_mock.assert_called_once()
    _, kwargs = run_phase_a_mock.call_args
    assert kwargs["source_a_path"] == tmp_path / "in" / "A.pdf"
    assert kwargs["sessions_dir"] == tmp_path / "out" / ".sessions"
