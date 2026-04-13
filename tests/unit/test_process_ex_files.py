"""process_ex_files.py のユニットテスト（macOS でも実行可能）。

platform ガードは main() 内のため、モジュール自体は macOS でもインポート可能。
"""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "process_ex_files.py"


@pytest.fixture()
def mod():
    """process_ex_files モジュールをインポートする。"""
    spec = importlib.util.spec_from_file_location("process_ex_files", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestFindSubfolderMatch:
    def test_match_kinari(self, mod):
        folders = ["きなり", "太子の郷", "太子町地域包括支援センター"]
        filename = "202603_提供実績_ささき整形外科デイケアセンター(2814101271)_居宅介護支援事業所　きなり(2874101146)_20260409.ex_"
        assert mod.find_subfolder_match(filename, folders) == "きなり"

    def test_match_taishi_no_sato(self, mod):
        folders = ["きなり", "太子の郷", "太子町地域包括支援センター"]
        filename = "202603_提供実績_ささき整形外科デイケアセンター(2814101271)_太子の郷　居宅介護支援事業所(2874100080)_20260409.ex_"
        assert mod.find_subfolder_match(filename, folders) == "太子の郷"

    def test_match_taishi_houkatsu(self, mod):
        folders = ["きなり", "太子の郷", "太子町地域包括支援センター"]
        filename = "202603_提供実績_ささき整形外科デイケアセンター(2814101271)_太子町地域包括支援センター(2804100010)_20260409.ex_"
        assert mod.find_subfolder_match(filename, folders) == "太子町地域包括支援センター"

    def test_no_match(self, mod):
        folders = ["きなり", "太子の郷"]
        filename = "202603_提供実績_unknown_facility.ex_"
        assert mod.find_subfolder_match(filename, folders) is None


class TestProcessDirectory:
    def test_missing_directory(self, mod, tmp_path):
        missing = tmp_path / "nonexistent"
        assert mod.process_directory(missing) == 1

    def test_no_ex_files(self, mod, tmp_path):
        assert mod.process_directory(tmp_path) == 0

    def test_no_matching_subfolder(self, mod, tmp_path):
        ex_file = tmp_path / "test_unknown.ex_"
        ex_file.write_bytes(b"dummy")
        (tmp_path / "some_folder").mkdir()
        result = mod.process_directory(tmp_path)
        assert result == 1

    def test_temp_dir_cleaned_on_exception(self, mod, tmp_path):
        """extract_pdf で例外が発生しても _temp_extract が削除される。"""
        ex_file = tmp_path / "test_きなり.ex_"
        ex_file.write_bytes(b"dummy")
        (tmp_path / "きなり").mkdir()

        with patch.object(mod, "extract_pdf", side_effect=RuntimeError("test error")):
            with pytest.raises(RuntimeError):
                mod.process_directory(tmp_path)

        assert not (tmp_path / "_temp_extract").exists()


class TestRunExeAndWait:
    def test_timeout_kills_process(self, mod, tmp_path):
        """タイムアウト時にプロセスが確実に kill される。"""
        mock_proc = MagicMock()
        # 最初の wait(timeout=5) は TimeoutExpired、kill 後の wait() は成功
        mock_proc.wait.side_effect = [
            subprocess.TimeoutExpired(cmd="exe", timeout=5),
            None,
        ]

        with patch("subprocess.Popen", return_value=mock_proc):
            result = mod._run_exe_and_wait(tmp_path / "fake.exe", tmp_path)

        mock_proc.kill.assert_called_once()
        assert result == []

    def test_pdf_found_terminates_process(self, mod, tmp_path):
        """PDF が見つかったらプロセスが終了される。"""
        pdf_file = tmp_path / "output.pdf"

        mock_proc = MagicMock()
        call_count = 0

        def fake_sleep(sec):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                pdf_file.write_bytes(b"%PDF-1.4 dummy")

        with patch("subprocess.Popen", return_value=mock_proc), patch("time.sleep", fake_sleep):
            result = mod._run_exe_and_wait(tmp_path / "fake.exe", tmp_path)

        assert len(result) == 1
        assert result[0].name == "output.pdf"
        mock_proc.terminate.assert_called_once()

    def test_oserror_returns_empty(self, mod, tmp_path):
        """Popen が OSError を投げた場合は空リストを返す。"""
        with patch("subprocess.Popen", side_effect=OSError("access denied")):
            result = mod._run_exe_and_wait(tmp_path / "fake.exe", tmp_path)
        assert result == []


class TestMain:
    def test_non_windows_returns_1(self, mod):
        """Windows 以外では終了コード 1 を返す。"""
        with patch.object(sys, "platform", "darwin"):
            assert mod.main() == 1
