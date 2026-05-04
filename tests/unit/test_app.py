"""WisemanHub オーケストレータのユニットテスト"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from wiseman_hub.app import WisemanHub
from wiseman_hub.rpa.base import MdiChildNotFoundError
from wiseman_hub.rpa.mock_engine import MockEngine


class TestWisemanHubWithMock:
    """MockEngineを使ったパイプライン統合テスト"""

    def _create_config_toml(self, tmp_path: Path) -> Path:
        """テスト用の設定ファイルを作成"""
        config_path = tmp_path / "test_config.toml"
        config_path.write_text(
            '[app]\n'
            'version = "0.1.0-test"\n'
            'log_level = "DEBUG"\n'
            '\n'
            '[wiseman]\n'
            'exe_path = "C:\\\\wiseman.exe"\n'
            '\n'
            '[reports]\n'
            'targets = [\n'
            '  { name = "ケア記録", menu_path = ["ケア記録", "日報"], output_format = "csv" },\n'
            ']\n'
            '\n'
            '[gcp]\n'
            'project_id = "test-project"\n'
            'bucket_name = "test-bucket"\n',
            encoding="utf-8",
        )
        return config_path

    def test_init_with_mock_engine(self, tmp_path: Path) -> None:
        config_path = self._create_config_toml(tmp_path)
        engine = MockEngine()
        hub = WisemanHub(config_path=config_path, rpa_engine=engine)
        assert hub.rpa is engine
        assert hub.config.version == "0.1.0-test"

    @patch("wiseman_hub.app.upload_files", return_value=["gs://test-bucket/mock.csv"])
    def test_pipeline_runs_with_mock(self, mock_upload: object, tmp_path: Path) -> None:
        """MockEngineでパイプライン全体が動作するか"""
        config_path = self._create_config_toml(tmp_path)
        engine = MockEngine()
        hub = WisemanHub(config_path=config_path, rpa_engine=engine)
        hub.output_dir = tmp_path / "exports"

        hub.run()

        # RPAの呼び出し履歴を確認（ADR-007: 認証はUSBドングルのみ）
        assert any(c.startswith("launch(") for c in engine.call_log)
        assert any("navigate_menu" in c for c in engine.call_log)
        assert any("export_csv" in c for c in engine.call_log)
        assert any("close_current_window" in c for c in engine.call_log)
        assert any("close_wiseman" in c for c in engine.call_log)

    @patch("wiseman_hub.app.upload_files", return_value=[])
    def test_pipeline_no_reports(self, mock_upload: object, tmp_path: Path) -> None:
        """帳票設定が空のとき、CSVなし警告で正常終了"""
        config_path = tmp_path / "no_reports.toml"
        config_path.write_text(
            '[wiseman]\n'
            'exe_path = "C:\\\\wiseman.exe"\n'
            '\n'
            '[gcp]\n'
            'project_id = "test-project"\n'
            'bucket_name = "test-bucket"\n',
            encoding="utf-8",
        )
        engine = MockEngine()
        hub = WisemanHub(config_path=config_path, rpa_engine=engine)

        hub.run()

        # upload_filesは呼ばれない（CSVがないため）
        mock_upload.assert_not_called()

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="macOS 専用テスト: Windows では PywinautoEngine が選択される正常動作",
    )
    def test_create_rpa_engine_returns_mock_on_macos(self, tmp_path: Path) -> None:
        """macOS環境ではMockEngineが自動選択される"""
        config_path = self._create_config_toml(tmp_path)
        hub = WisemanHub(config_path=config_path)
        assert type(hub.rpa).__name__ == "MockEngine"

    @patch("wiseman_hub.app.upload_files", return_value=["gs://test-bucket/r2.csv"])
    def test_pipeline_continues_on_export_csv_error(
        self, mock_upload: object, tmp_path: Path
    ) -> None:
        """1 帳票が ExportCsvError でも他の帳票処理が継続される (Issue #14)。

        ExportCsvError サブクラスの try/except 互換実装の検証:
        - 1 回目の export_csv で例外 → 該当 report をスキップして次へ
        - 2 回目の export_csv は成功 → csv_files に追加され upload される
        """
        config_path = tmp_path / "two_reports.toml"
        config_path.write_text(
            '[wiseman]\n'
            'exe_path = "C:\\\\wiseman.exe"\n'
            '\n'
            '[reports]\n'
            'targets = [\n'
            '  { name = "失敗帳票", menu_path = ["A"], output_format = "csv" },\n'
            '  { name = "成功帳票", menu_path = ["B"], output_format = "csv" },\n'
            ']\n'
            '\n'
            '[gcp]\n'
            'project_id = "test-project"\n'
            'bucket_name = "test-bucket"\n',
            encoding="utf-8",
        )
        engine = MockEngine()
        hub = WisemanHub(config_path=config_path, rpa_engine=engine)
        hub.output_dir = tmp_path / "exports"

        real_export = engine.export_csv
        call_count = [0]

        def export_csv_side_effect(output_dir: Path) -> Path:
            call_count[0] += 1
            if call_count[0] == 1:
                raise MdiChildNotFoundError("test failure")
            return real_export(output_dir)

        with patch.object(engine, "export_csv", side_effect=export_csv_side_effect):
            hub.run()

        # 両 report 分 export_csv が試行されたこと
        assert call_count[0] == 2
        # 成功した 1 ファイルだけが upload される
        mock_upload.assert_called_once()
        uploaded_files = mock_upload.call_args.args[1]
        assert len(uploaded_files) == 1
        # 失敗 report では close_current_window がスキップ、成功 report のみ呼ばれる
        # (AC-6: MDI 状態不定時の不正なウィンドウ操作を防ぐ)
        close_calls = [c for c in engine.call_log if "close_current_window" in c]
        assert len(close_calls) == 1


class TestWisemanHubLoadConfigErrors:
    """Issue #150: 不正設定で生 traceback を露出せず actionable error を出す。

    PR #149 (Issue #27 PR-A) で OcrBackendConfig / UserNameBBox / PdfMergeConfig に
    ``__post_init__`` 検証を追加したことで ValueError が伝播するようになった。
    元実装は無捕捉で、ユーザーがどのフィールドを直すべきか判別不能だった。
    """

    @pytest.mark.parametrize(
        "bad_toml,expected_in_log",
        [
            pytest.param(
                "[ocr_backend]\ntimeout_sec = -1\n",
                "OcrBackendConfig.timeout_sec must be positive",
                id="negative_timeout_sec",
            ),
            pytest.param(
                "[pdf_merge.user_name_bbox]\nx0 = 100.0\ny0 = 10.0\nx1 = 50.0\ny1 = 80.0\n",
                "x0",
                id="inverted_bbox",
            ),
            pytest.param(
                '[pdf_merge]\nconcat_order = ["X"]\n',
                "unknown source",
                id="unknown_concat_letter",
            ),
            pytest.param(
                # facility_aliases value が list でなく str → _coerce_facility_aliases TypeError
                '[pdf_merge.facility_aliases]\nfacility = "not_a_list"\n',
                "facility_aliases value must be a list",
                id="aliases_value_not_list",
            ),
            pytest.param(
                # malformed TOML 構文 → tomllib.TOMLDecodeError (ValueError サブクラス)
                "this is = = invalid\n",
                "TOMLDecodeError",
                id="malformed_toml_syntax",
            ),
            # Issue #150 (PR #157 codex 指摘 High): reports 形状エラーを exit code 2 側に寄せる
            pytest.param(
                'reports = "not_a_table"\n',
                "[reports] section must be a table",
                id="reports_section_not_table",
            ),
            pytest.param(
                '[reports]\ntargets = "bad"\n',
                "[reports].targets must be a list",
                id="reports_targets_not_list",
            ),
            pytest.param(
                '[reports]\ntargets = ["not_a_dict"]\n',
                "[reports].targets entries must be tables",
                id="reports_targets_entry_not_dict",
            ),
        ],
    )
    def test_init_raises_with_actionable_log(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        bad_toml: str,
        expected_in_log: str,
    ) -> None:
        """不正な設定で例外を raise し、logger.error に actionable 情報が残る。"""
        config_path = tmp_path / "bad.toml"
        config_path.write_text(bad_toml, encoding="utf-8")

        with (
            caplog.at_level(logging.ERROR, logger="wiseman_hub.app"),
            pytest.raises((ValueError, TypeError)),
        ):
            WisemanHub(config_path=config_path)

        assert "設定ファイル読込エラー" in caplog.text
        assert expected_in_log in caplog.text

    def test_init_re_raises_original_exception(self, tmp_path: Path) -> None:
        """例外は wrap されず元の型のまま再 raise される（caller が型で分岐できる）。"""
        config_path = tmp_path / "bad.toml"
        config_path.write_text(
            "[ocr_backend]\nmax_retries = -5\n", encoding="utf-8"
        )

        with pytest.raises(ValueError) as exc_info:
            WisemanHub(config_path=config_path)

        assert "max_retries" in str(exc_info.value)

    def test_init_raises_oserror_when_config_path_is_directory(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Issue #150 HIGH-1: ディレクトリを config_path に指定 → IsADirectoryError (OSError)
        でも actionable error が出る。`config_path` も log に含まれ setup 失敗の
        診断材料となる（ファイル存在ではなく権限/ディレクトリ等の I/O 経路問題を区別可能）。
        """
        config_dir = tmp_path / "config_dir"
        config_dir.mkdir()

        with (
            caplog.at_level(logging.ERROR, logger="wiseman_hub.app"),
            pytest.raises(OSError),
        ):
            WisemanHub(config_path=config_dir)

        assert "設定ファイル読込エラー" in caplog.text
        assert str(config_dir) in caplog.text

    @pytest.mark.parametrize(
        "alias_toml,expected_struct_msg,forbidden_pii",
        [
            # duplicate alias across facilities
            pytest.param(
                '[pdf_merge.facility_aliases]\n'
                '"本田デイケア" = ["本田"]\n'
                '"本田訪問看護" = ["本田"]\n',
                "shared by multiple facilities",
                ("本田", "デイケア", "訪問看護"),
                id="duplicate_across_facilities",
            ),
            # duplicate alias within same facility
            pytest.param(
                '[pdf_merge.facility_aliases]\n'
                '"本田デイケア" = ["本田DC", "本田DC"]\n',
                "duplicate alias within",
                ("本田", "デイケア", "本田DC"),
                id="duplicate_within_same_facility",
            ),
            # alias conflicts with another facility's canonical name
            pytest.param(
                '[pdf_merge.facility_aliases]\n'
                '"本田デイケア" = ["きなり"]\n'
                '"きなり" = ["きなり訪問"]\n',
                "conflicts with another facility",
                ("本田", "デイケア", "きなり", "訪問"),
                id="alias_conflicts_with_canonical",
            ),
        ],
    )
    def test_init_log_does_not_leak_alias_pii(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        alias_toml: str,
        expected_struct_msg: str,
        forbidden_pii: tuple[str, ...],
    ) -> None:
        """Issue #150 C1 (PII 防御): alias 検証エラーメッセージに alias / 事業所名が含まれない。

        ADR-014 に準拠して `_validate_facility_aliases` の例外メッセージは構造的な
        エラー種別のみ含み、事業所名・別名は含まない契約。logger.error は同じ exc を
        str 化するため、alias 文字列が log に漏洩しないことを回帰テストで固定する
        （将来 raise メッセージに alias を埋め戻す変更が入った場合に検出）。

        codex セカンドオピニオン Low #1 対応: duplicate-across だけでなく
        duplicate-within / canonical-conflict も明示テストし、3 経路すべてで PII
        漏洩しないことを契約として固定する。
        """
        config_path = tmp_path / "alias_invalid.toml"
        config_path.write_text(alias_toml, encoding="utf-8")

        with (
            caplog.at_level(logging.ERROR, logger="wiseman_hub.app"),
            pytest.raises(ValueError),
        ):
            WisemanHub(config_path=config_path)

        # 構造的メッセージは含まれる（actionable category）
        assert "facility_aliases" in caplog.text
        assert expected_struct_msg in caplog.text
        # PII（alias 文字列・事業所名）は含まれない
        for pii_token in forbidden_pii:
            assert pii_token not in caplog.text, (
                f"PII token {pii_token!r} leaked to log: {caplog.text!r}"
            )
