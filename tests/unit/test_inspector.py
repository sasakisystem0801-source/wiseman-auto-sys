"""UIインスペクタのユニットテスト（macOS実行可能）"""

from __future__ import annotations

from pathlib import Path

import pytest

from wiseman_hub.rpa.inspector import find_controls, load_catalog, print_summary, save_catalog

# テスト用モックカタログ
MOCK_CATALOG: dict = {
    "control_type": "Window",
    "name": "通所・訪問リハビリ管理システム SP(ケア記録)",
    "automation_id": "MainForm",
    "class_name": "WindowsForms10.Window",
    "rectangle": {"left": 0, "top": 0, "right": 1920, "bottom": 1080},
    "is_enabled": True,
    "is_visible": True,
    "depth": 0,
    "children": [
        {
            "control_type": "MenuBar",
            "name": "メニューバー",
            "automation_id": "menuStrip1",
            "class_name": "MenuStrip",
            "rectangle": {"left": 0, "top": 0, "right": 1920, "bottom": 30},
            "is_enabled": True,
            "is_visible": True,
            "depth": 1,
            "children": [],
        },
        {
            "control_type": "Button",
            "name": "印刷",
            "automation_id": "btnPrint",
            "class_name": "WindowsForms10.BUTTON",
            "rectangle": {"left": 100, "top": 50, "right": 180, "bottom": 80},
            "is_enabled": True,
            "is_visible": True,
            "depth": 1,
            "children": [],
        },
        {
            "control_type": "Button",
            "name": "閉じる",
            "automation_id": "btnClose",
            "class_name": "WindowsForms10.BUTTON",
            "rectangle": {"left": 200, "top": 50, "right": 280, "bottom": 80},
            "is_enabled": True,
            "is_visible": True,
            "depth": 1,
            "children": [],
        },
        {
            "control_type": "DataGrid",
            "name": "ケア記録一覧",
            "automation_id": "dgvRecords",
            "class_name": "DataGridView",
            "rectangle": {"left": 0, "top": 100, "right": 1920, "bottom": 900},
            "is_enabled": True,
            "is_visible": True,
            "depth": 1,
            "children": [
                {
                    "control_type": "DataItem",
                    "name": "行1",
                    "automation_id": "",
                    "class_name": "",
                    "rectangle": {"left": 0, "top": 100, "right": 1920, "bottom": 130},
                    "is_enabled": True,
                    "is_visible": True,
                    "depth": 2,
                    "children": [],
                },
            ],
        },
        {
            "control_type": "ComboBox",
            "name": "印刷形式",
            "automation_id": "cmbFormat",
            "class_name": "WindowsForms10.COMBOBOX",
            "rectangle": {"left": 300, "top": 50, "right": 450, "bottom": 80},
            "is_enabled": False,
            "is_visible": True,
            "depth": 1,
            "children": [],
        },
    ],
}


class TestSaveAndLoadCatalog:
    def test_round_trip(self, tmp_path: Path) -> None:
        output = tmp_path / "catalog.json"
        save_catalog(MOCK_CATALOG, output)
        loaded = load_catalog(output)
        assert loaded["name"] == MOCK_CATALOG["name"]
        assert len(loaded["children"]) == len(MOCK_CATALOG["children"])

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        output = tmp_path / "sub" / "dir" / "catalog.json"
        save_catalog(MOCK_CATALOG, output)
        assert output.exists()

    def test_load_nonexistent_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_catalog(tmp_path / "no_such_file.json")

    def test_load_invalid_json_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("{broken json", encoding="utf-8")
        with pytest.raises(ValueError):
            load_catalog(bad)

    def test_load_empty_file_raises(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.json"
        empty.write_text("", encoding="utf-8")
        with pytest.raises(ValueError):
            load_catalog(empty)

    def test_load_preserves_structure(self, tmp_path: Path) -> None:
        output = tmp_path / "catalog.json"
        save_catalog(MOCK_CATALOG, output)
        loaded = load_catalog(output)
        # DataGridの子要素が保持されているか
        datagrid = [c for c in loaded["children"] if c["control_type"] == "DataGrid"][0]
        assert len(datagrid["children"]) == 1
        assert datagrid["children"][0]["name"] == "行1"


class TestFindControls:
    def test_find_by_control_type(self) -> None:
        buttons = find_controls(MOCK_CATALOG, control_type="Button")
        assert len(buttons) == 2
        names = {b["name"] for b in buttons}
        assert names == {"印刷", "閉じる"}

    def test_find_by_name_contains(self) -> None:
        results = find_controls(MOCK_CATALOG, name_contains="印刷")
        # "印刷" ボタンと "印刷形式" コンボボックス
        assert len(results) == 2

    def test_find_by_automation_id(self) -> None:
        results = find_controls(MOCK_CATALOG, automation_id="btnPrint")
        assert len(results) == 1
        assert results[0]["name"] == "印刷"

    def test_find_with_combined_filters(self) -> None:
        # Button AND name_contains="印刷" → "印刷" のみ（"印刷形式" はComboBox）
        results = find_controls(MOCK_CATALOG, control_type="Button", name_contains="印刷")
        assert len(results) == 1
        assert results[0]["automation_id"] == "btnPrint"

    def test_find_no_filter_returns_empty(self) -> None:
        results = find_controls(MOCK_CATALOG)
        assert results == []

    def test_find_no_match_returns_empty(self) -> None:
        results = find_controls(MOCK_CATALOG, control_type="Slider")
        assert results == []

    def test_find_nested_control(self) -> None:
        results = find_controls(MOCK_CATALOG, control_type="DataItem")
        assert len(results) == 1
        assert results[0]["name"] == "行1"

    def test_find_when_name_is_null(self) -> None:
        node: dict = {"control_type": "Button", "name": None, "automation_id": "", "children": []}
        results = find_controls(node, name_contains="印刷")
        assert results == []


class TestPrintSummary:
    def test_outputs_without_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        print_summary(MOCK_CATALOG)
        captured = capsys.readouterr()
        assert "UIカタログサマリー" in captured.out
        assert "Button" in captured.out
        assert "DataGrid" in captured.out
        # 総数: Window(1) + MenuBar(1) + Button(2) + DataGrid(1) + DataItem(1) + ComboBox(1) = 7
        assert "7" in captured.out

    def test_print_summary_single_node(self, capsys: pytest.CaptureFixture[str]) -> None:
        node: dict = {"control_type": "Window", "name": "空", "children": []}
        print_summary(node)
        captured = capsys.readouterr()
        assert "1" in captured.out
        assert "空" in captured.out
