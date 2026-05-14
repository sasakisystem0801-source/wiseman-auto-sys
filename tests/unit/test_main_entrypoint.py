"""`python -m wiseman_hub` エントリポイントのテスト。

--rpa 指定: WisemanHub が呼ばれる
--rpa 省略: Launcher が呼ばれる
"""

from __future__ import annotations

import sys
from dataclasses import replace
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


def test_default_does_not_inject_legacy_phase_a_callback(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Issue #154: 旧ワークフロー (PDF マージ処理) の callback 注入が除去されたことを契約化。

    元実装の test_default_injects_phase_a_callback は AC-L-2 として
    ``on_run_pdf_merge`` 注入を保証していたが、Issue #154 で UI 経路除去に伴い
    callback 自体を main() から削除。再追加 regression を catch する negative test。
    """
    config_file = tmp_path / "config.toml"
    config_file.write_text("", encoding="utf-8")

    launcher_class = MagicMock()
    monkeypatch.setattr("wiseman_hub.ui.launcher.Launcher", launcher_class)
    monkeypatch.setattr(sys, "argv", ["wiseman-hub", "--config", str(config_file)])

    from wiseman_hub.__main__ import main

    main()

    _, kwargs = launcher_class.call_args
    # 旧ワークフロー callback は注入されない
    assert "on_run_pdf_merge" not in kwargs
    assert "on_open_review" not in kwargs
    assert "on_run_phase_b" not in kwargs
    # 残存 callback は注入される (業務フロー: ex_extractor + facility_merger + settings)
    assert callable(kwargs.get("on_open_ex_extractor"))
    assert callable(kwargs.get("on_open_facility_merger"))
    assert callable(kwargs.get("on_open_settings"))


def test_rpa_flag_starts_wiseman_hub(tmp_path: Path, monkeypatch: Any) -> None:
    """--rpa 指定で WisemanHub が起動される。"""
    config_file = tmp_path / "config.toml"
    config_file.write_text("", encoding="utf-8")

    hub_instance = MagicMock()
    # Issue #27 続編 F Phase 2-b: ``_apply_log_level(hub.config.log_level)`` が main 経由で
    # 呼ばれるため、MagicMock のままだと ``getattr(logging, MagicMock, ...)`` で TypeError。
    # log_level は AppConfig デフォルト "INFO" を明示して bootstrap と同等に振る舞わせる。
    hub_instance.config.log_level = "INFO"
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
    # Issue #27 続編 F Phase 2-b: MagicMock 子オブジェクトの log_level を "INFO" に固定 (上記参照)
    hub_class.return_value.config.log_level = "INFO"
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

    # Issue #27 続編 E Phase 3b: AppConfig + PdfMergeConfig は frozen=True、
    # ``replace()`` で階層構築する (旧 attribute 代入は FrozenInstanceError)。
    base = AppConfig()
    saved_config = replace(
        base,
        pdf_merge=replace(base.pdf_merge, input_dir=Path("/reloaded")),
    )

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
    assert reload_calls[0].pdf_merge.input_dir == Path("/reloaded")


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


# Issue #154: test_phase_a_callback_reloads_config_and_runs_phase_a を削除。
# _make_phase_a_callback 関数自体が __main__.py から除去されたため。
# pdf/pipeline.run_phase_a は ADR-013 方針でコード資産として残置されており、
# 直接呼出のテスト (tests/unit/pdf/test_pipeline.py) で動作検証は継続。


# ===========================================================================
# Issue #27 続編 F Phase 2: _apply_log_level helper + config.log_level 反映
# ===========================================================================


@pytest.fixture
def restore_root_logger_level() -> Any:
    """root logger の level を test 前後で保存・復元 (テスト間副作用回避)。"""
    import logging

    original = logging.getLogger().level
    yield
    logging.getLogger().setLevel(original)


class TestApplyLogLevel:
    """``_apply_log_level`` helper の値域 + fallback 動作を契約化。

    本 helper は ``AppConfig.log_level`` (Literal 5 値) を root logger に反映する。
    続編 F Phase 1 (PR #286) で Literal 化したが、Phase 2 で実 logging に接続するまで
    orphan だった経路を消化する。
    """

    @pytest.mark.parametrize(
        "level_name,expected",
        [
            ("DEBUG", 10),
            ("INFO", 20),
            ("WARNING", 30),
            ("ERROR", 40),
            ("CRITICAL", 50),
        ],
    )
    def test_applies_valid_log_level(
        self,
        level_name: str,
        expected: int,
        restore_root_logger_level: Any,
    ) -> None:
        """Literal 5 値で root logger の level が一致する。"""
        import logging

        from wiseman_hub.__main__ import _apply_log_level

        _apply_log_level(level_name)
        assert logging.getLogger().getEffectiveLevel() == expected

    def test_fallback_to_info_for_unknown_level_name(
        self, restore_root_logger_level: Any
    ) -> None:
        """defensive guard: AppConfig.__post_init__ の値域検証を通過しない経路は
        型上は無いが、念のため getattr fallback で INFO に落ちることを保証。"""
        import logging

        from wiseman_hub.__main__ import _apply_log_level

        _apply_log_level("BOGUS_LEVEL")
        assert logging.getLogger().getEffectiveLevel() == logging.INFO


def test_main_applies_config_log_level_to_root_logger(
    tmp_path: Path, monkeypatch: Any, restore_root_logger_level: Any
) -> None:
    """Launcher 経路で ``config.log_level = "DEBUG"`` が root logger に反映される。

    本テストは Phase 2 の core 契約: load_config 後に ``_apply_log_level`` が
    呼ばれることで orphan が解消されている (旧: bootstrap INFO のままだった)。
    """
    import logging

    config_file = tmp_path / "config.toml"
    # ``log_level`` は AppConfig 直下フィールドで TOML 上は ``[app]`` section に格納される
    # (config.py: ``app_data = _require_section_table("app", data.get("app", {}))``)。
    config_file.write_text('[app]\nlog_level = "DEBUG"\n', encoding="utf-8")

    launcher_instance = MagicMock()
    launcher_class = MagicMock(return_value=launcher_instance)
    monkeypatch.setattr("wiseman_hub.ui.launcher.Launcher", launcher_class)

    monkeypatch.setattr(sys, "argv", ["wiseman-hub", "--config", str(config_file)])

    from wiseman_hub.__main__ import main

    main()

    assert logging.getLogger().getEffectiveLevel() == logging.DEBUG


def test_main_rpa_path_applies_config_log_level_to_root_logger(
    tmp_path: Path, monkeypatch: Any, restore_root_logger_level: Any
) -> None:
    """RPA 経路 (--rpa) でも ``hub.config.log_level`` が root logger に反映される。

    Issue #27 続編 F Phase 2-b: Launcher 経路と対称化。WisemanHub Mock の
    ``config.log_level`` を "DEBUG" にして main() 経由で root logger に反映される
    こと、また ``hub.run()`` 呼出より前に level が反映されることを契約化する。
    """
    import logging

    config_file = tmp_path / "config.toml"
    config_file.write_text("", encoding="utf-8")  # WisemanHub Mock 化で config 内容は問わない

    hub_instance = MagicMock()
    hub_instance.config.log_level = "DEBUG"
    hub_class = MagicMock(return_value=hub_instance)
    monkeypatch.setattr("wiseman_hub.app.WisemanHub", hub_class)

    monkeypatch.setattr(
        sys, "argv", ["wiseman-hub", "--rpa", "--config", str(config_file)]
    )

    from wiseman_hub.__main__ import main

    main()

    hub_class.assert_called_once()
    hub_instance.run.assert_called_once()
    assert logging.getLogger().getEffectiveLevel() == logging.DEBUG


def test_main_rpa_path_log_level_applied_before_hub_run(
    tmp_path: Path, monkeypatch: Any, restore_root_logger_level: Any
) -> None:
    """RPA 経路で ``_apply_log_level`` が ``hub.run()`` より前に呼ばれる順序を契約化。

    Phase 2-b コメントの「``hub.run()`` 以降は config.log_level で出力される」
    という挙動を保証する (順序逆転で run() のログだけ bootstrap INFO になる
    regression を防ぐ)。
    """
    import logging

    config_file = tmp_path / "config.toml"
    config_file.write_text("", encoding="utf-8")

    hub_instance = MagicMock()
    hub_instance.config.log_level = "WARNING"  # bootstrap INFO=20 と区別可能な値

    # hub.run() が呼ばれた時点での root logger.level を記録 (順序検証用)
    level_at_run: list[int] = []

    def _capture_level_at_run() -> None:
        level_at_run.append(logging.getLogger().getEffectiveLevel())

    hub_instance.run.side_effect = _capture_level_at_run
    hub_class = MagicMock(return_value=hub_instance)
    monkeypatch.setattr("wiseman_hub.app.WisemanHub", hub_class)

    monkeypatch.setattr(
        sys, "argv", ["wiseman-hub", "--rpa", "--config", str(config_file)]
    )

    from wiseman_hub.__main__ import main

    main()

    assert level_at_run == [logging.WARNING], (
        "hub.run() 実行時点で root logger.level が config.log_level (WARNING) に "
        "なっていない: _apply_log_level の順序逆転 regression の疑い"
    )


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


# ===========================================================================
# Issue #158: 起動後 callback の load_config 失敗 actionable error 化
# ===========================================================================
#
# PR #157 で起動経路 (WisemanHub.__init__ / __main__.main()) と settings dialog
# 経路の load_config 失敗を actionable error 化済み。本テスト群は同等の対称性を
# 残り 4 callback (facility_root / ex_extractor / checklist_b / checklist_c) に
# 確保することを契約化する。
#
# 期待挙動:
#     - load_config が OSError / ValueError / TypeError を raise した場合
#     - logger.error に PII-safe (型名のみ) のメッセージが記録される
#     - messagebox.showerror が "設定ファイル読込エラー" タイトルで呼ばれる
#     - dialog 構築 (FacilityRootManagerDialog / ExExtractorDialog 等) は実行されない
#     - early return: callback は副作用なく終了


class TestPostStartupCallbackLoadConfigError:
    """Issue #158: 起動後 callback の load_config 失敗 actionable error 化。

    PR #157 の ``_make_settings_callback`` と同形パターンを
    facility_root / ex_extractor / checklist_b / checklist_c の 4 callback
    に展開。設定ファイルが TOML 構文エラー / I/O 失敗で読めない状況でも、
    UI を破壊せず early return + messagebox + log error を発火する契約。

    PII 防御契約 (本テスト群で固定):
        - log は ``type(exc).__name__`` のみ、``exc.args`` / ``str(exc)`` は出さない
        - messagebox body も同様 (型名のみ)。``f"\\n\\n{exc}"`` への退化を test で検出。
    """

    @staticmethod
    def _setup_failing_load_config(monkeypatch: Any, exc: Exception) -> None:
        """``wiseman_hub.config.load_config`` を例外 raise 版に差し替え。"""
        def _raise(_p: Path) -> None:
            raise exc

        monkeypatch.setattr("wiseman_hub.config.load_config", _raise)

    @staticmethod
    def _capture_messagebox(monkeypatch: Any) -> list[tuple[str, str]]:
        """``tkinter.messagebox.showerror`` 呼び出しを記録するスタブを設置。"""
        captured: list[tuple[str, str]] = []

        def _stub(title: str, message: str, *args: Any, **kwargs: Any) -> None:
            captured.append((title, message))

        monkeypatch.setattr("tkinter.messagebox.showerror", _stub)
        return captured

    def test_facility_root_callback_actionable_error_on_oserror(
        self, tmp_path: Path, monkeypatch: Any, caplog: Any
    ) -> None:
        """facility_root callback: load_config が OSError raise → actionable + early return。"""
        import logging

        config_file = tmp_path / "config.toml"
        config_file.write_text("", encoding="utf-8")

        self._setup_failing_load_config(monkeypatch, OSError("permission denied"))
        captured = self._capture_messagebox(monkeypatch)

        # dialog が実行されていないことの検証スタブ
        dialog_called: list[bool] = []

        def _dialog_stub(*args: Any, **kwargs: Any) -> None:
            dialog_called.append(True)

        monkeypatch.setattr(
            "wiseman_hub.ui.facility_root_dialog.FacilityRootManagerDialog",
            _dialog_stub,
        )

        class FakeLauncher:
            def get_root(self) -> None:
                return None

            def reload_config(self, config: Any) -> None:
                pass

        from wiseman_hub.__main__ import _make_facility_merger_callback

        callback = _make_facility_merger_callback(config_file, lambda: FakeLauncher())

        with caplog.at_level(logging.ERROR):
            callback()  # 例外が外に漏れないこと

        # dialog が起動されていない (early return)
        assert dialog_called == []
        # messagebox が表示されている
        assert len(captured) == 1
        assert captured[0][0] == "設定ファイル読込エラー"
        # PII 防御: messagebox body に型名は含まれるが exc.args は出さない
        # (将来 `f"\n\n{exc}"` への退化を catch する規約 lock-in)
        assert "OSError" in captured[0][1]
        assert "permission denied" not in captured[0][1]
        # log も同様に型名のみ (PII-safe)
        assert any("OSError" in rec.message for rec in caplog.records)
        assert all(
            "permission denied" not in rec.message for rec in caplog.records
        )

    def test_ex_extractor_callback_actionable_error_on_valueerror(
        self, tmp_path: Path, monkeypatch: Any, caplog: Any
    ) -> None:
        """ex_extractor callback: load_config が ValueError raise → actionable + early return。"""
        import logging

        config_file = tmp_path / "config.toml"
        config_file.write_text("", encoding="utf-8")

        self._setup_failing_load_config(
            monkeypatch, ValueError("invalid TOML structure")
        )
        captured = self._capture_messagebox(monkeypatch)

        dialog_called: list[bool] = []

        def _dialog_stub(*args: Any, **kwargs: Any) -> None:
            dialog_called.append(True)

        monkeypatch.setattr(
            "wiseman_hub.ui.ex_extractor_dialog.ExExtractorDialog",
            _dialog_stub,
        )

        class FakeLauncher:
            def get_root(self) -> None:
                return None

            def reload_config(self, config: Any) -> None:
                pass

        from wiseman_hub.__main__ import _make_ex_extractor_callback

        callback = _make_ex_extractor_callback(config_file, lambda: FakeLauncher())

        with caplog.at_level(logging.ERROR):
            callback()

        assert dialog_called == []
        assert len(captured) == 1
        assert captured[0][0] == "設定ファイル読込エラー"
        # PII 防御: 型名のみ、exc.args (TOML 内容の漏洩) は出さない
        assert "ValueError" in captured[0][1]
        assert "invalid TOML structure" not in captured[0][1]
        assert any("ValueError" in rec.message for rec in caplog.records)
        assert all(
            "invalid TOML structure" not in rec.message
            for rec in caplog.records
        )

    def test_checklist_b_callback_actionable_error_on_typeerror(
        self, tmp_path: Path, monkeypatch: Any, caplog: Any
    ) -> None:
        """checklist_b callback: load_config が TypeError raise → actionable + early return。"""
        import logging

        config_file = tmp_path / "config.toml"
        config_file.write_text("", encoding="utf-8")

        self._setup_failing_load_config(
            monkeypatch, TypeError("expected dict, got list")
        )
        captured = self._capture_messagebox(monkeypatch)

        dialog_called: list[bool] = []

        def _dialog_stub(*args: Any, **kwargs: Any) -> None:
            dialog_called.append(True)

        monkeypatch.setattr(
            "wiseman_hub.ui.checklist_b_dialog.ChecklistBDialog",
            _dialog_stub,
        )

        class FakeLauncher:
            def get_root(self) -> None:
                return None

            def reload_config(self, config: Any) -> None:
                pass

        from wiseman_hub.__main__ import _make_checklist_b_callback

        callback = _make_checklist_b_callback(config_file, lambda: FakeLauncher())

        with caplog.at_level(logging.ERROR):
            callback()

        assert dialog_called == []
        assert len(captured) == 1
        assert captured[0][0] == "設定ファイル読込エラー"
        # PII 防御: 型名のみ、exc.args (構造化エラー詳細の漏洩) は出さない
        assert "TypeError" in captured[0][1]
        assert "expected dict" not in captured[0][1]
        assert any("TypeError" in rec.message for rec in caplog.records)
        assert all(
            "expected dict" not in rec.message for rec in caplog.records
        )

    def test_checklist_c_callback_actionable_error_on_oserror(
        self, tmp_path: Path, monkeypatch: Any, caplog: Any
    ) -> None:
        """checklist_c callback: load_config が OSError raise → actionable + early return。"""
        import logging

        config_file = tmp_path / "config.toml"
        config_file.write_text("", encoding="utf-8")

        self._setup_failing_load_config(monkeypatch, OSError("disk full"))
        captured = self._capture_messagebox(monkeypatch)

        dialog_called: list[bool] = []

        def _dialog_stub(*args: Any, **kwargs: Any) -> None:
            dialog_called.append(True)

        monkeypatch.setattr(
            "wiseman_hub.ui.checklist_c_dialog.ChecklistCDialog",
            _dialog_stub,
        )

        class FakeLauncher:
            def get_root(self) -> None:
                return None

            def reload_config(self, config: Any) -> None:
                pass

        from wiseman_hub.__main__ import _make_checklist_c_callback

        callback = _make_checklist_c_callback(config_file, lambda: FakeLauncher())

        with caplog.at_level(logging.ERROR):
            callback()

        assert dialog_called == []
        assert len(captured) == 1
        assert captured[0][0] == "設定ファイル読込エラー"
        # PII 防御: 型名のみ、exc.args (filesystem 状態の漏洩) は出さない
        assert "OSError" in captured[0][1]
        assert "disk full" not in captured[0][1]
        assert any("OSError" in rec.message for rec in caplog.records)
        assert all(
            "disk full" not in rec.message for rec in caplog.records
        )


class TestPostActionReloadWarningLog:
    """Issue #250: post-action reload (dialog 終了後の load_config) 失敗時の warning ログ化。

    系譜:
        - PR #157 (Issue #150 close): ``_make_settings_callback`` で起動経路 +
          settings dialog の load_config を actionable error 化 (起源パターン)
        - PR #249 (Issue #158 close): 起動前 4 callback (facility_root /
          ex_extractor / checklist_b / checklist_c) に展開
        - **本 PR (Issue #250 close)**: post-action reload (dialog 終了後の
          再ロード) を ``facility_root`` post-action と対称化

    本 PR 起源は PR #249 の silent-failure-hunter Important rating 7 conf 90:
    checklist_b/c の post-action は完全 silent (``except: pass``) のままで、
    設定変更後 reload 失敗時にユーザーが「dialog 閉じたら設定が反映されない
    けどエラーも出ない」状態に陥る silent failure が残っていた。

    対象 callback (post-action reload を持つ 3 callback):
        - ``_make_facility_merger_callback`` (facility_root)
        - ``_make_checklist_b_callback``
        - ``_make_checklist_c_callback``

    ``ex_extractor`` は post-action reload を持たない (dialog 内部の
    ``on_source_persisted`` 経由で reload するため、本契約の対象外)。

    期待挙動 (3 callback 共通):
        - 1 回目 load_config (起動前) は成功し dialog を構築
        - dialog 終了後の 2 回目 load_config が ``(OSError, ValueError, TypeError)``
          のいずれかを raise した場合
        - ``logger.warning`` に PII-safe (型名のみ) のメッセージが記録される
        - ``launcher.reload_config`` は呼ばれない (early return)
        - 例外は callback の外に漏れない

    カバー戦略 (対角線):
        3 callback × 3 例外型 = 9 マトリックスのうち 3 件 (各 callback で
        異なる例外型を 1 つずつ) でカバー。``except (OSError, ValueError,
        TypeError) as exc`` の handling code path は同一なので、9 件完全
        マトリックスは redundant。各 callback が tuple 全例外を catch できる
        ことが代理的に verify される (Python の例外 catch 仕様)。

    PII 防御契約 (本テスト群で固定):
        - log は ``type(exc).__name__`` のみ。``exc.args`` / ``str(exc)`` は出さない
        - ``logger.warning("... %s", exc)`` への退化を test で catch
        - WARNING record の message format ``"load_config after <ctx> dialog
          failed: <TypeName>"`` との完全一致 assertion で `%s` formatter の
          追加退化も catch (negative + positive assertion の両側 lock-in)

    実装前提:
        - callback は ``from wiseman_hub.config import load_config`` を関数内
          import で評価する (lazy import)。``monkeypatch.setattr("wiseman_hub.
          config.load_config", _stub)`` で stub が有効になるのはこの前提に依存。
        - 将来 module top-level の eager import に refactor された場合、
          ``counter[0] == 2`` assertion が ``counter[0] == 0`` で fail し、
          patch が外れたことを catch する (safety net 機能)。
    """

    @staticmethod
    def _setup_load_config_succeed_then_raise(
        monkeypatch: Any, config: Any, exc: Exception
    ) -> list[int]:
        """1 回目は ``config`` を返し、2 回目以降は ``exc`` を raise する load_config スタブ。

        Returns:
            呼び出し回数を保持する 1 要素 list (test 側で counter[0] を assert)。
        """
        counter = [0]

        def _stub(_p: Path) -> Any:
            counter[0] += 1
            if counter[0] == 1:
                return config
            raise exc

        monkeypatch.setattr("wiseman_hub.config.load_config", _stub)
        return counter

    @staticmethod
    def _install_noop_dialog(monkeypatch: Any, target: str) -> None:
        """``target`` (dotted path) を、``wait_window()`` が即 return する
        no-op に差し替える (post-action reload に到達させる fixture)。

        load-bearing semantic は **wait_window() が同期的に return すること**。
        実 dialog は modal で wait_window 内で event loop が回るが、本 stub は
        即座に制御を返し、呼出元 callback の post-action ``load_config`` を
        同期的に到達させる。
        """

        class _NoopToplevel:
            def wait_window(self) -> None:
                return None

        class _NoopDialog:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                return None

            def get_toplevel(self) -> Any:
                return _NoopToplevel()

        monkeypatch.setattr(target, _NoopDialog)

    def test_facility_root_callback_post_action_warning_on_oserror(
        self, tmp_path: Path, monkeypatch: Any, caplog: Any
    ) -> None:
        """facility_root callback: post-action reload OSError → warning ログ + reload_config 不呼。"""
        import logging

        config_file = tmp_path / "config.toml"
        config_file.write_text("", encoding="utf-8")

        fake_config = object()
        counter = self._setup_load_config_succeed_then_raise(
            monkeypatch, fake_config, OSError("permission denied")
        )
        self._install_noop_dialog(
            monkeypatch,
            "wiseman_hub.ui.facility_root_dialog.FacilityRootManagerDialog",
        )

        reload_called: list[Any] = []

        class FakeLauncher:
            def get_root(self) -> None:
                return None

            def reload_config(self, config: Any) -> None:
                reload_called.append(config)

        from wiseman_hub.__main__ import _make_facility_merger_callback

        callback = _make_facility_merger_callback(
            config_file, lambda: FakeLauncher()
        )

        with caplog.at_level(logging.WARNING):
            callback()

        # 1 回目 (起動前) + 2 回目 (post-action) の計 2 回呼ばれた
        assert counter[0] == 2
        # post-action reload が失敗 → launcher.reload_config は呼ばれない
        assert reload_called == []
        # warning ログ: PII-safe (型名のみ)
        warning_records = [
            rec for rec in caplog.records if rec.levelname == "WARNING"
        ]
        # PII 契約 lock-in: template 完全一致 (`%s` formatter の追加退化も catch)
        assert (
            "load_config after facility_root dialog failed: OSError"
            in [rec.message for rec in warning_records]
        )
        # PII 防御: exc.args (filesystem state の漏洩) は出さない
        assert all(
            "permission denied" not in rec.message for rec in caplog.records
        )

    def test_checklist_b_callback_post_action_warning_on_valueerror(
        self, tmp_path: Path, monkeypatch: Any, caplog: Any
    ) -> None:
        """checklist_b callback: post-action reload ValueError → warning + reload_config 不呼。"""
        import logging

        config_file = tmp_path / "config.toml"
        config_file.write_text("", encoding="utf-8")

        fake_config = object()
        counter = self._setup_load_config_succeed_then_raise(
            monkeypatch, fake_config, ValueError("invalid TOML structure")
        )
        self._install_noop_dialog(
            monkeypatch,
            "wiseman_hub.ui.checklist_b_dialog.ChecklistBDialog",
        )

        reload_called: list[Any] = []

        class FakeLauncher:
            def get_root(self) -> None:
                return None

            def reload_config(self, config: Any) -> None:
                reload_called.append(config)

        from wiseman_hub.__main__ import _make_checklist_b_callback

        callback = _make_checklist_b_callback(
            config_file, lambda: FakeLauncher()
        )

        with caplog.at_level(logging.WARNING):
            callback()

        assert counter[0] == 2
        assert reload_called == []
        warning_records = [
            rec for rec in caplog.records if rec.levelname == "WARNING"
        ]
        # PII 契約 lock-in: template 完全一致
        assert (
            "load_config after checklist_b dialog failed: ValueError"
            in [rec.message for rec in warning_records]
        )
        assert all(
            "invalid TOML structure" not in rec.message
            for rec in caplog.records
        )

    def test_checklist_c_callback_post_action_warning_on_typeerror(
        self, tmp_path: Path, monkeypatch: Any, caplog: Any
    ) -> None:
        """checklist_c callback: post-action reload TypeError → warning + reload_config 不呼。"""
        import logging

        config_file = tmp_path / "config.toml"
        config_file.write_text("", encoding="utf-8")

        fake_config = object()
        counter = self._setup_load_config_succeed_then_raise(
            monkeypatch, fake_config, TypeError("expected dict, got list")
        )
        self._install_noop_dialog(
            monkeypatch,
            "wiseman_hub.ui.checklist_c_dialog.ChecklistCDialog",
        )

        reload_called: list[Any] = []

        class FakeLauncher:
            def get_root(self) -> None:
                return None

            def reload_config(self, config: Any) -> None:
                reload_called.append(config)

        from wiseman_hub.__main__ import _make_checklist_c_callback

        callback = _make_checklist_c_callback(
            config_file, lambda: FakeLauncher()
        )

        with caplog.at_level(logging.WARNING):
            callback()

        assert counter[0] == 2
        assert reload_called == []
        warning_records = [
            rec for rec in caplog.records if rec.levelname == "WARNING"
        ]
        # PII 契約 lock-in: template 完全一致
        assert (
            "load_config after checklist_c dialog failed: TypeError"
            in [rec.message for rec in warning_records]
        )
        assert all(
            "expected dict, got list" not in rec.message
            for rec in caplog.records
        )
