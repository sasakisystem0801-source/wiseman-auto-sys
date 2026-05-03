"""env_scanner.scan_fax_folders の単体テスト (GCS 部分は実機依存のため除外)。"""

from __future__ import annotations

from pathlib import Path

import pytest

from wiseman_hub.cloud.env_scanner import scan_fax_folders


class TestScanFaxFolders:
    def test_returns_sorted_folder_names(self, tmp_path: Path) -> None:
        (tmp_path / "あおぞら(FAX)").mkdir()
        (tmp_path / "ケアプラン太子（メール）※持参").mkdir()
        (tmp_path / "LEBEN(メール)").mkdir()
        result = scan_fax_folders(tmp_path)
        assert result == sorted(result)
        assert "あおぞら(FAX)" in result
        assert len(result) == 3

    def test_excludes_files(self, tmp_path: Path) -> None:
        (tmp_path / "folder").mkdir()
        (tmp_path / "stray.pdf").touch()
        (tmp_path / "config.toml").touch()
        result = scan_fax_folders(tmp_path)
        assert result == ["folder"]

    def test_excludes_hidden_dirs(self, tmp_path: Path) -> None:
        (tmp_path / "visible").mkdir()
        (tmp_path / ".hidden").mkdir()
        result = scan_fax_folders(tmp_path)
        assert result == ["visible"]

    def test_raises_when_root_missing(self, tmp_path: Path) -> None:
        ghost = tmp_path / "ghost"
        with pytest.raises(FileNotFoundError):
            scan_fax_folders(ghost)

    def test_raises_when_root_is_file(self, tmp_path: Path) -> None:
        f = tmp_path / "not_a_dir"
        f.touch()
        with pytest.raises(NotADirectoryError):
            scan_fax_folders(f)
