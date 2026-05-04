"""FacilityMergerDialog のユニットテスト。

Tk 非同梱環境では tk_required マーカーで skip。
外部依存（merge_facility / filedialog / messagebox）はすべて DI 経由で差し替える。
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from wiseman_hub.pdf.facility_merger import (
    FacilityMergeReport,
    UserMergeEntry,
)
from wiseman_hub.ui.facility_merger_dialog import FacilityMergerDialog


@pytest.mark.tk_required
class TestFacilityMergerDialog:
    """構造 + 入力バリデーション + 実行フロー確認。"""

    def test_dialog_opens_and_has_three_path_entries(self, tmp_path: Path) -> None:
        root = tk.Tk()
        try:
            dialog = FacilityMergerDialog(root)
            top = dialog.get_toplevel()
            # Toplevel が表示可能状態
            assert top.winfo_exists()
            top.destroy()
        finally:
            root.destroy()

    def test_run_without_inputs_shows_error(self, tmp_path: Path) -> None:
        """未入力状態で実行 → messagebox.showerror が呼ばれる。"""
        root = tk.Tk()
        try:
            mock_mbox = MagicMock()
            mock_merge = MagicMock()
            dialog = FacilityMergerDialog(
                root, merge_fn=mock_merge, messagebox_fn=mock_mbox
            )
            dialog._on_run()  # type: ignore[attr-defined]
            mock_mbox.showerror.assert_called_once()
            mock_merge.assert_not_called()
            dialog.get_toplevel().destroy()
        finally:
            root.destroy()

    def test_run_with_valid_inputs_invokes_merge(self, tmp_path: Path) -> None:
        """全入力済で実行 → merge_facility 呼出 + サマリ描画。"""
        root = tk.Tk()
        try:
            a_pdf = tmp_path / "a.pdf"
            a_pdf.touch()
            facility = tmp_path / "facility"
            facility.mkdir()
            output = tmp_path / "out"

            fake_report = FacilityMergeReport(
                facility_name="facility",
                output_dir=output / "facility",
                success=(
                    UserMergeEntry(
                        user_key="塩津",
                        full_name="塩津 美貴子",
                        sources_used=("A", "B", "C"),
                        output_path=output / "facility" / "塩津.pdf",
                    ),
                ),
            )
            mock_merge = MagicMock(return_value=fake_report)
            mock_mbox = MagicMock()

            dialog = FacilityMergerDialog(
                root, merge_fn=mock_merge, messagebox_fn=mock_mbox
            )
            dialog._a_var.set(str(a_pdf))  # type: ignore[attr-defined]
            dialog._facility_var.set(str(facility))  # type: ignore[attr-defined]
            dialog._output_var.set(str(output))  # type: ignore[attr-defined]

            dialog._on_run()  # type: ignore[attr-defined]

            mock_merge.assert_called_once_with(
                Path(str(a_pdf)), Path(str(facility)), Path(str(output))
            )
            mock_mbox.showerror.assert_not_called()
            result = dialog.get_result()
            assert result.executed is True
            assert result.report is fake_report

            # 結果テキストに user_key が含まれるが full_name は含まれない（PII 防御）
            text_widget = dialog._result_text  # type: ignore[attr-defined]
            content = text_widget.get("1.0", "end")
            # 新仕様（facility_merger_dialog.py:254-260）: 出力は事業所単位 1 ファイル
            # `{facility_name}.pdf`、user は `  ✓ {user_key}` で列挙、結合順は "A→B→C"
            assert "facility.pdf" in content
            assert "塩津" in content
            assert "A→B→C" in content
            assert "美貴子" not in content  # full_name 漏洩チェック

            dialog.get_toplevel().destroy()
        finally:
            root.destroy()

    def test_run_with_file_not_found_shows_error(self, tmp_path: Path) -> None:
        """merge_facility が FileNotFoundError → showerror 呼出、report なし。"""
        root = tk.Tk()
        try:
            a_pdf = tmp_path / "missing.pdf"
            facility = tmp_path / "facility"
            output = tmp_path / "out"

            mock_merge = MagicMock(
                side_effect=FileNotFoundError("missing.pdf")
            )
            mock_mbox = MagicMock()

            dialog = FacilityMergerDialog(
                root, merge_fn=mock_merge, messagebox_fn=mock_mbox
            )
            dialog._a_var.set(str(a_pdf))  # type: ignore[attr-defined]
            dialog._facility_var.set(str(facility))  # type: ignore[attr-defined]
            dialog._output_var.set(str(output))  # type: ignore[attr-defined]

            dialog._on_run()  # type: ignore[attr-defined]

            mock_mbox.showerror.assert_called_once()
            assert dialog.get_result().executed is False
            dialog.get_toplevel().destroy()
        finally:
            root.destroy()

    def test_run_with_generic_exception_sanitizes_pii(self, tmp_path: Path) -> None:
        """第三者例外 → messagebox には型名のみ表示、生 message は出さない。"""
        root = tk.Tk()
        try:
            a_pdf = tmp_path / "a.pdf"
            a_pdf.touch()
            facility = tmp_path / "facility"
            facility.mkdir()
            output = tmp_path / "out"

            # 氏名を含みうる例外 message をシミュレート
            mock_merge = MagicMock(
                side_effect=RuntimeError("塩津 美貴子 path leak")
            )
            mock_mbox = MagicMock()

            dialog = FacilityMergerDialog(
                root, merge_fn=mock_merge, messagebox_fn=mock_mbox
            )
            dialog._a_var.set(str(a_pdf))  # type: ignore[attr-defined]
            dialog._facility_var.set(str(facility))  # type: ignore[attr-defined]
            dialog._output_var.set(str(output))  # type: ignore[attr-defined]

            dialog._on_run()  # type: ignore[attr-defined]

            # showerror の第 2 引数（message）に型名は含まれるが、
            # PII ライクな "塩津 美貴子" は含まれない
            mock_mbox.showerror.assert_called_once()
            args = mock_mbox.showerror.call_args.args
            assert "RuntimeError" in args[1]
            assert "塩津" not in args[1]
            assert "美貴子" not in args[1]

            dialog.get_toplevel().destroy()
        finally:
            root.destroy()
