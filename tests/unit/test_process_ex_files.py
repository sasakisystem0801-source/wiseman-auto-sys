"""process_ex_files.py のユニットテスト（macOS でも実行可能）。"""

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


class TestSnapshotPdfs:
    def test_finds_pdf_files(self, mod, tmp_path):
        (tmp_path / "test.pdf").write_bytes(b"pdf")
        (tmp_path / "another.pdf").write_bytes(b"pdf")
        (tmp_path / "other.txt").write_bytes(b"txt")
        result = mod._snapshot_pdfs(tmp_path)
        assert len(result) == 2

    def test_multiple_dirs(self, mod, tmp_path):
        d1 = tmp_path / "a"
        d2 = tmp_path / "b"
        d1.mkdir()
        d2.mkdir()
        (d1 / "one.pdf").write_bytes(b"pdf")
        (d2 / "two.pdf").write_bytes(b"pdf")
        result = mod._snapshot_pdfs(d1, d2)
        assert len(result) == 2

    def test_nonexistent_dir_skipped(self, mod, tmp_path):
        result = mod._snapshot_pdfs(tmp_path / "nonexistent")
        assert result == set()


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
        assert mod.process_directory(tmp_path) == 1


class TestExtractWithExe:
    def test_pdf_found_after_process_exit(self, mod, tmp_path):
        """プロセス終了後に PDF が検出される。"""
        pdf_file = tmp_path / "output.pdf"

        mock_proc = MagicMock()
        # poll() が None を2回返した後、0 を返す（プロセス終了）
        mock_proc.poll.side_effect = [None, None, 0]

        call_count = 0

        def fake_sleep(sec):
            nonlocal call_count
            call_count += 1
            if call_count == 3:
                pdf_file.write_bytes(b"%PDF-1.4 dummy")

        with (
            patch("subprocess.Popen", return_value=mock_proc),
            patch("time.sleep", fake_sleep),
        ):
            result = mod._extract_with_exe(tmp_path / "fake.exe", [tmp_path])

        assert len(result) == 1
        assert result[0].name == "output.pdf"

    def test_oserror_returns_empty(self, mod, tmp_path):
        """Popen が OSError を投げた場合は空リストを返す。"""
        with patch("subprocess.Popen", side_effect=OSError("access denied")):
            result = mod._extract_with_exe(tmp_path / "fake.exe", [tmp_path])
        assert result == []

    def test_timeout_kills_process(self, mod, tmp_path):
        """タイムアウト時にプロセスが確実に終了される。"""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # プロセスは常に実行中
        mock_proc.wait.side_effect = [
            subprocess.TimeoutExpired(cmd="exe", timeout=5),
            None,
        ]

        with patch("subprocess.Popen", return_value=mock_proc):
            result = mod._extract_with_exe(tmp_path / "fake.exe", [tmp_path])

        mock_proc.kill.assert_called_once()
        assert result == []


class TestMain:
    def test_non_windows_returns_1(self, mod):
        with patch.object(sys, "platform", "darwin"):
            assert mod.main() == 1
