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


def test_nonexistent_config_path_emits_warning(
    tmp_path: Path,
    monkeypatch: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Issue #64: --config で存在しないパスを指定すると警告ログが出る。

    ランチャーは起動するが load_config は空の AppConfig を返すため、
    ユーザーは「なぜ設定が消えた」と困惑する。事前に警告ログで通知する。
    """
    import logging

    launcher_class = MagicMock()
    monkeypatch.setattr("wiseman_hub.ui.launcher.Launcher", launcher_class)

    nonexistent = tmp_path / "does_not_exist.toml"
    monkeypatch.setattr(sys, "argv", ["wiseman-hub", "--config", str(nonexistent)])

    from wiseman_hub.__main__ import main

    with caplog.at_level(logging.WARNING, logger="wiseman_hub.__main__"):
        main()

    assert "--config path does not exist" in caplog.text
    assert str(nonexistent) in caplog.text


def test_existing_config_path_emits_no_warning(
    tmp_path: Path,
    monkeypatch: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Issue #64: 正常に存在する --config パスでは警告ログを出さない。"""
    import logging

    config_file = tmp_path / "valid.toml"
    config_file.write_text("", encoding="utf-8")

    launcher_class = MagicMock()
    monkeypatch.setattr("wiseman_hub.ui.launcher.Launcher", launcher_class)
    monkeypatch.setattr(sys, "argv", ["wiseman-hub", "--config", str(config_file)])

    from wiseman_hub.__main__ import main

    with caplog.at_level(logging.WARNING, logger="wiseman_hub.__main__"):
        main()

    assert "--config path does not exist" not in caplog.text


def test_default_config_path_absence_emits_no_warning(
    monkeypatch: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Issue #64: --config を指定しない場合は警告を出さない。

    既定パス（config/default.toml）が存在しなくても警告対象は明示指定のみ。
    """
    import logging

    launcher_class = MagicMock()
    monkeypatch.setattr("wiseman_hub.ui.launcher.Launcher", launcher_class)
    monkeypatch.setattr(sys, "argv", ["wiseman-hub"])

    from wiseman_hub.__main__ import main

    with caplog.at_level(logging.WARNING, logger="wiseman_hub.__main__"):
        main()

    assert "--config path does not exist" not in caplog.text


def test_nonexistent_config_path_emits_warning_on_rpa_path(
    tmp_path: Path,
    monkeypatch: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Issue #64: --rpa 経路でも --config 警告が発火する契約を固定。

    警告ロジックは parse_args 直後（--rpa 分岐の前）に配置されているため、
    UI / RPA 両経路で発火する。将来誰かが警告を `else` ブロック内へ
    移動した場合に regression を検知する。
    """
    import logging

    hub_class = MagicMock()
    monkeypatch.setattr("wiseman_hub.app.WisemanHub", hub_class)

    nonexistent = tmp_path / "does_not_exist.toml"
    monkeypatch.setattr(
        sys, "argv", ["wiseman-hub", "--rpa", "--config", str(nonexistent)]
    )

    from wiseman_hub.__main__ import main

    with caplog.at_level(logging.WARNING, logger="wiseman_hub.__main__"):
        main()

    assert "--config path does not exist" in caplog.text
    assert str(nonexistent) in caplog.text


def test_rpa_with_invalid_config_exits_two(
    tmp_path: Path,
    monkeypatch: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Issue #150: --rpa + 不正 TOML で exit code 2 (config error) 終了する。

    WisemanHub.__init__ 内で actionable な logger.error を出した後、
    CLI が runtime error (1) と区別可能な setup-time error (2) で exit する。
    """
    import logging

    config_file = tmp_path / "bad.toml"
    config_file.write_text("[ocr_backend]\ntimeout_sec = -1\n", encoding="utf-8")

    monkeypatch.setattr(
        sys, "argv", ["wiseman-hub", "--rpa", "--config", str(config_file)]
    )

    from wiseman_hub.__main__ import main

    with (
        caplog.at_level(logging.ERROR, logger="wiseman_hub.app"),
        pytest.raises(SystemExit) as exc_info,
    ):
        main()

    assert exc_info.value.code == 2
    assert "設定ファイル読込エラー" in caplog.text
    assert "OcrBackendConfig.timeout_sec must be positive" in caplog.text


def test_default_with_invalid_config_exits_two(
    tmp_path: Path,
    monkeypatch: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Issue #150: launcher 経路 + 不正 TOML で exit code 2 (config error) 終了する。

    Launcher は構築されず、actionable な logger.error が __main__ から発火する。
    """
    import logging

    config_file = tmp_path / "bad.toml"
    config_file.write_text(
        '[pdf_merge]\nconcat_order = ["X"]\n', encoding="utf-8"
    )

    launcher_class = MagicMock()
    monkeypatch.setattr("wiseman_hub.ui.launcher.Launcher", launcher_class)
    monkeypatch.setattr(
        sys, "argv", ["wiseman-hub", "--config", str(config_file)]
    )

    from wiseman_hub.__main__ import main

    with (
        caplog.at_level(logging.ERROR, logger="wiseman_hub.__main__"),
        pytest.raises(SystemExit) as exc_info,
    ):
        main()

    assert exc_info.value.code == 2
    assert "設定ファイル読込エラー" in caplog.text
    assert "unknown source" in caplog.text
    launcher_class.assert_not_called()


def test_default_with_aliases_typeerror_exits_two(
    tmp_path: Path,
    monkeypatch: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Issue #150: launcher 経路でも TypeError (facility_aliases value not list) で
    exit code 2。except 句の TypeError 部分が launcher 経路でも実機検証される。
    """
    import logging

    config_file = tmp_path / "alias_typeerror.toml"
    config_file.write_text(
        "[pdf_merge.facility_aliases]\n"
        'facility = "not_a_list"\n',
        encoding="utf-8",
    )

    launcher_class = MagicMock()
    monkeypatch.setattr("wiseman_hub.ui.launcher.Launcher", launcher_class)
    monkeypatch.setattr(
        sys, "argv", ["wiseman-hub", "--config", str(config_file)]
    )

    from wiseman_hub.__main__ import main

    with (
        caplog.at_level(logging.ERROR, logger="wiseman_hub.__main__"),
        pytest.raises(SystemExit) as exc_info,
    ):
        main()

    assert exc_info.value.code == 2
    assert "TypeError" in caplog.text
    assert "facility_aliases value must be a list" in caplog.text
    launcher_class.assert_not_called()


def test_default_with_alias_conflict_does_not_leak_pii(
    tmp_path: Path,
    monkeypatch: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Issue #150 C1 (PII 防御): launcher 経路でも alias 文字列が log に漏れない。

    rpa 経路の test_init_log_does_not_leak_alias_pii と対をなすテスト。
    `__main__` logger 経由でも構造的メッセージのみ表出することを契約として固定する。
    """
    import logging

    config_file = tmp_path / "alias_conflict.toml"
    config_file.write_text(
        "[pdf_merge.facility_aliases]\n"
        '"本田デイケア" = ["本田"]\n'
        '"本田訪問看護" = ["本田"]\n',
        encoding="utf-8",
    )

    launcher_class = MagicMock()
    monkeypatch.setattr("wiseman_hub.ui.launcher.Launcher", launcher_class)
    monkeypatch.setattr(
        sys, "argv", ["wiseman-hub", "--config", str(config_file)]
    )

    from wiseman_hub.__main__ import main

    with (
        caplog.at_level(logging.ERROR, logger="wiseman_hub.__main__"),
        pytest.raises(SystemExit) as exc_info,
    ):
        main()

    assert exc_info.value.code == 2
    assert "facility_aliases" in caplog.text
    assert "shared by multiple facilities" in caplog.text
    # PII (alias 文字列・事業所名) が log に漏洩しないこと
    assert "本田" not in caplog.text
    assert "デイケア" not in caplog.text


def test_rpa_failure_emits_main_logger_for_cli_context(
    tmp_path: Path,
    monkeypatch: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Issue #150 HIGH-2: --rpa 経路の setup 失敗時に __main__ logger でも
    CLI context (`RPA 起動失敗`) が記録される。

    WisemanHub.__init__ の `wiseman_hub.app` logger と二重で `__main__` 側にも
    残ることで、launcher 経路と非対称にならず、どちらの経路で setup が落ちたかを
    grep で識別可能にする。
    """
    import logging

    config_file = tmp_path / "bad.toml"
    config_file.write_text(
        "[ocr_backend]\ntimeout_sec = -1\n", encoding="utf-8"
    )

    monkeypatch.setattr(
        sys, "argv", ["wiseman-hub", "--rpa", "--config", str(config_file)]
    )

    from wiseman_hub.__main__ import main

    with (
        caplog.at_level(logging.ERROR),
        pytest.raises(SystemExit) as exc_info,
    ):
        main()

    assert exc_info.value.code == 2
    logger_names = {r.name for r in caplog.records}
    assert "wiseman_hub.app" in logger_names
    assert "wiseman_hub.__main__" in logger_names
    assert "RPA 起動失敗" in caplog.text
    assert str(config_file) in caplog.text


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

        def get_root(self) -> None:
            # テスト用: SettingsDialog を monkeypatch で FakeDialog に差し替えて
            # いるため、戻り値が実際に使われることはない。
            return None

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

        def get_root(self) -> None:
            # テスト用: SettingsDialog を monkeypatch で FakeDialog に差し替えて
            # いるため、戻り値が実際に使われることはない。
            return None

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


# ===========================================================================
# _default_config_path: Codex HIGH 指摘対応（exe ショートカット起動での CWD 相対バグ）
# ===========================================================================


class TestDefaultConfigPath:
    """exe 配布時の config 解決が CWD 依存で破綻しないことを回帰固定。"""

    def test_uses_env_var_when_set(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """WISEMAN_HUB_CONFIG 環境変数があれば最優先（運用でのオーバーライド）。"""
        from wiseman_hub.__main__ import _default_config_path

        override = tmp_path / "custom" / "my.toml"
        monkeypatch.setenv("WISEMAN_HUB_CONFIG", str(override))
        assert _default_config_path() == override

    def test_uses_executable_parent_when_frozen(self, monkeypatch: Any) -> None:
        """PyInstaller onefile 起動時は sys.executable 隣の config/default.toml を使う。

        Codex HIGH 再現: frozen + CWD=別ディレクトリでも同階層の config を解決できる。
        """
        from wiseman_hub.__main__ import _default_config_path

        monkeypatch.delenv("WISEMAN_HUB_CONFIG", raising=False)
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(
            sys, "executable", "/opt/wiseman/wiseman_hub.exe", raising=False
        )
        result = _default_config_path()
        assert result == Path("/opt/wiseman/config/default.toml")

    def test_uses_cwd_relative_when_not_frozen(self, monkeypatch: Any) -> None:
        """通常実行（ソース起動）は従来互換の相対パス（プロジェクトルート前提）。"""
        from wiseman_hub.__main__ import _default_config_path

        monkeypatch.delenv("WISEMAN_HUB_CONFIG", raising=False)
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        assert _default_config_path() == Path("config/default.toml")

    def test_env_var_wins_over_frozen(self, monkeypatch: Any) -> None:
        """frozen + 環境変数 の場合は環境変数が優先（明示的オーバーライド）。"""
        from wiseman_hub.__main__ import _default_config_path

        monkeypatch.setenv("WISEMAN_HUB_CONFIG", "/explicit/path.toml")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", "/opt/wiseman/wiseman_hub.exe", raising=False)
        assert _default_config_path() == Path("/explicit/path.toml")
