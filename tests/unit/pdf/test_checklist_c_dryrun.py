"""execute_c_placement の dry_run モード（PR-ζ v1）。

検証点:
    - dry_run=True で exporter.export_first_page が呼ばれない
    - dry_run=True で status が PENDING のまま、message に "dry-run" 記載
    - 監査ログに dry_run=true フラグが入る
    - dry_run=False は既存動作（exporter 必須、status=SUCCESS、close 呼出）
    - dry_run=False で exporter=None は ValueError
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from wiseman_hub.cloud.sheets import ChecklistRow
from wiseman_hub.pdf.checklist_c import (
    CPlacementResult,
    CPlacementStatus,
    execute_c_placement,
)


def _fake_write_pdf(xlsx_path: Path, sheet_name: str, output_pdf: Path) -> None:
    """exporter mock の write 動作を模す（実 PDF 風バイトを書く）。"""
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    output_pdf.write_bytes(b"%PDF-1.4\n%FAKE\n%%EOF\n")


def _make_pending_result(tmp_path: Path) -> CPlacementResult:
    """PENDING で全フィールド埋まった結果を返す。"""
    row = ChecklistRow(
        name="テスト太郎",
        monitoring_raw="",
        staff="宮下",
        facility="テスト居宅",
    )
    r = CPlacementResult(row=row)
    r.status = CPlacementStatus.PENDING
    r.xlsx_path = tmp_path / "stub.xlsx"
    r.sheet_name = "テスト太郎"
    r.target_pdf = tmp_path / "out" / "テスト太郎.pdf"
    return r


def _read_audit_lines(log_dir: Path) -> list[dict]:
    """log_dir/audit/c_placement_*.jsonl の全行を読む。"""
    audit_dir = log_dir / "audit"
    if not audit_dir.exists():
        return []
    lines: list[dict] = []
    for f in audit_dir.glob("c_placement_*.jsonl"):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                lines.append(json.loads(line))
    return lines


class TestDryRun:
    def test_dry_run_does_not_call_exporter(self, tmp_path: Path) -> None:
        """dry_run=True で exporter が渡されても export_first_page / close を呼ばない。

        Evaluator 指摘 (HIGH): 旧版は exporter=None を渡しながらローカル MagicMock に
        assert_not_called していたため、実装が誤って exporter を触っても通過してしまう
        欠陥があった。本テストでは実際に渡された MagicMock に対してアサートすることで、
        AC1-a「dry_run=True 時 export_first_page が一度も呼ばれない」を保証する。
        """
        r = _make_pending_result(tmp_path)
        mock_exporter = MagicMock()
        execute_c_placement([r], exporter=mock_exporter, log_dir=Path(""), dry_run=True)
        mock_exporter.export_first_page.assert_not_called()
        mock_exporter.close.assert_not_called()

    def test_dry_run_accepts_exporter_none(self, tmp_path: Path) -> None:
        """dry_run=True で exporter=None も許容（呼出側が exporter を作らない用途）。"""
        r = _make_pending_result(tmp_path)
        # 例外を出さず正常完了することの確認
        execute_c_placement([r], exporter=None, log_dir=Path(""), dry_run=True)
        assert r.status == CPlacementStatus.PENDING
        assert "dry-run" in r.message

    def test_dry_run_keeps_status_pending(self, tmp_path: Path) -> None:
        """dry_run 後も status=PENDING を保ち再実行可能（実配置に進める）。"""
        r = _make_pending_result(tmp_path)
        execute_c_placement([r], exporter=None, log_dir=Path(""), dry_run=True)
        assert r.status == CPlacementStatus.PENDING
        assert "dry-run" in r.message

    def test_dry_run_audit_log_has_flag(self, tmp_path: Path) -> None:
        r = _make_pending_result(tmp_path)
        execute_c_placement(
            [r], exporter=None, log_dir=tmp_path, dry_run=True
        )
        lines = _read_audit_lines(tmp_path)
        assert len(lines) == 1
        assert lines[0]["dry_run"] is True
        assert lines[0]["status"] == CPlacementStatus.PENDING.value
        assert lines[0]["user"] == "テスト太郎"

    def test_dry_run_skips_non_pending_rows(self, tmp_path: Path) -> None:
        """SKIPPED / SUCCESS の行は dry_run でも触らない（既存挙動継承）。"""
        skipped = _make_pending_result(tmp_path)
        skipped.status = CPlacementStatus.SKIPPED_NO_SHEET
        skipped.message = "シート未発見"
        original_message = skipped.message
        execute_c_placement([skipped], exporter=None, log_dir=Path(""), dry_run=True)
        assert skipped.status == CPlacementStatus.SKIPPED_NO_SHEET
        assert skipped.message == original_message

    def test_dry_run_marks_missing_fields_as_error(self, tmp_path: Path) -> None:
        """xlsx_path/sheet_name/target_pdf 欠落は dry_run でも ERROR。"""
        r = _make_pending_result(tmp_path)
        r.target_pdf = None
        execute_c_placement([r], exporter=None, log_dir=Path(""), dry_run=True)
        assert r.status == CPlacementStatus.ERROR


class TestRealRun:
    def test_real_run_requires_exporter(self, tmp_path: Path) -> None:
        r = _make_pending_result(tmp_path)
        with pytest.raises(ValueError, match="exporter must be provided"):
            execute_c_placement([r], exporter=None, log_dir=Path(""), dry_run=False)

    def test_real_run_calls_export_and_marks_success(self, tmp_path: Path) -> None:
        r = _make_pending_result(tmp_path)
        exporter = MagicMock()
        # exporter は本来 PDF を書く責務を持つので、mock も実ファイルを書く挙動に
        # 仕込む。これにより execute_c_placement の二重ガード（書込後の存在 +
        # サイズ確認、Hotfix）を通過できる。
        exporter.export_first_page.side_effect = _fake_write_pdf
        execute_c_placement([r], exporter=exporter, log_dir=Path(""), dry_run=False)
        exporter.export_first_page.assert_called_once_with(
            r.xlsx_path, r.sheet_name, r.target_pdf
        )
        exporter.close.assert_called_once()
        assert r.status == CPlacementStatus.SUCCESS

    def test_real_run_audit_log_has_dry_run_false(self, tmp_path: Path) -> None:
        r = _make_pending_result(tmp_path)
        exporter = MagicMock()
        exporter.export_first_page.side_effect = _fake_write_pdf
        execute_c_placement(
            [r], exporter=exporter, log_dir=tmp_path, dry_run=False
        )
        lines = _read_audit_lines(tmp_path)
        assert len(lines) == 1
        assert lines[0]["dry_run"] is False
        assert lines[0]["status"] == CPlacementStatus.SUCCESS.value

    def test_real_run_silent_failure_marks_error(self, tmp_path: Path) -> None:
        """exporter が例外を出さずに PDF を書かなかった場合、SUCCESS にせず ERROR。

        Hotfix: Excel COM の ExportAsFixedFormat が DisplayAlerts=False で
        サイレント失敗する既知事案 (UNC + 特殊文字 + 親フォルダ未存在) の
        再発防止。`output_pdf.exists()` が False なら必ず ERROR に転帰する。
        """
        r = _make_pending_result(tmp_path)
        exporter = MagicMock()
        # PDF を書かない mock (旧仕様の Excel COM のサイレント失敗を再現)
        exporter.export_first_page.return_value = None
        execute_c_placement([r], exporter=exporter, log_dir=Path(""), dry_run=False)
        assert r.status == CPlacementStatus.ERROR
        assert "PDF was not written" in r.message

    def test_real_run_empty_pdf_marks_error(self, tmp_path: Path) -> None:
        """exporter が 0 バイトの PDF を書いた場合も ERROR (壊れた PDF を SUCCESS にしない)。"""
        r = _make_pending_result(tmp_path)
        exporter = MagicMock()
        def _empty_write(xlsx_path: Path, sheet_name: str, output_pdf: Path) -> None:
            output_pdf.parent.mkdir(parents=True, exist_ok=True)
            output_pdf.write_bytes(b"")  # 0 bytes
        exporter.export_first_page.side_effect = _empty_write
        execute_c_placement([r], exporter=exporter, log_dir=Path(""), dry_run=False)
        assert r.status == CPlacementStatus.ERROR
        assert "empty" in r.message.lower() or "0 bytes" in r.message

    def test_real_run_export_exception_marks_error(self, tmp_path: Path) -> None:
        r = _make_pending_result(tmp_path)
        exporter = MagicMock()
        exporter.export_first_page.side_effect = RuntimeError("COM crashed")
        execute_c_placement([r], exporter=exporter, log_dir=Path(""), dry_run=False)
        assert r.status == CPlacementStatus.ERROR
        assert "COM crashed" in r.message
        # close は finally で必ず呼ばれる
        exporter.close.assert_called_once()


class TestSelectedSubset:
    """呼出側が選択行のみ渡せば、その分だけ処理される（既存 list 仕様の確認）。"""

    def test_only_passed_rows_are_processed(self, tmp_path: Path) -> None:
        r1 = _make_pending_result(tmp_path)
        r1.row = ChecklistRow(name="一郎", monitoring_raw="", staff="宮下", facility="A")
        r2 = _make_pending_result(tmp_path)
        r2.row = ChecklistRow(name="二郎", monitoring_raw="", staff="宮下", facility="A")
        # r2 のみ渡す → r1 は触られない
        execute_c_placement([r2], exporter=None, log_dir=Path(""), dry_run=True)
        assert r1.status == CPlacementStatus.PENDING
        assert r1.message == ""  # default
        assert r2.status == CPlacementStatus.PENDING
        assert "dry-run" in r2.message
