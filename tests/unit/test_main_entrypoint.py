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
