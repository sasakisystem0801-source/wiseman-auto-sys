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
        r = _make_pending_result(tmp_path)
        exporter = MagicMock()
        execute_c_placement([r], exporter=None, log_dir="", dry_run=True)
        # exporter は不要 → 引数 None で動く
        exporter.export_first_page.assert_not_called()
        exporter.close.assert_not_called()

    def test_dry_run_keeps_status_pending(self, tmp_path: Path) -> None:
        """dry_run 後も status=PENDING を保ち再実行可能（実配置に進める）。"""
        r = _make_pending_result(tmp_path)
        execute_c_placement([r], exporter=None, log_dir="", dry_run=True)
        assert r.status == CPlacementStatus.PENDING
        assert "dry-run" in r.message

    def test_dry_run_audit_log_has_flag(self, tmp_path: Path) -> None:
        r = _make_pending_result(tmp_path)
        execute_c_placement(
            [r], exporter=None, log_dir=str(tmp_path), dry_run=True
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
        execute_c_placement([skipped], exporter=None, log_dir="", dry_run=True)
        assert skipped.status == CPlacementStatus.SKIPPED_NO_SHEET
        assert skipped.message == original_message

    def test_dry_run_marks_missing_fields_as_error(self, tmp_path: Path) -> None:
        """xlsx_path/sheet_name/target_pdf 欠落は dry_run でも ERROR。"""
        r = _make_pending_result(tmp_path)
        r.target_pdf = None
        execute_c_placement([r], exporter=None, log_dir="", dry_run=True)
        assert r.status == CPlacementStatus.ERROR


class TestRealRun:
    def test_real_run_requires_exporter(self, tmp_path: Path) -> None:
        r = _make_pending_result(tmp_path)
        with pytest.raises(ValueError, match="exporter must be provided"):
            execute_c_placement([r], exporter=None, log_dir="", dry_run=False)

    def test_real_run_calls_export_and_marks_success(self, tmp_path: Path) -> None:
        r = _make_pending_result(tmp_path)
        exporter = MagicMock()
        execute_c_placement([r], exporter=exporter, log_dir="", dry_run=False)
        exporter.export_first_page.assert_called_once_with(
            r.xlsx_path, r.sheet_name, r.target_pdf
        )
        exporter.close.assert_called_once()
        assert r.status == CPlacementStatus.SUCCESS

    def test_real_run_audit_log_has_dry_run_false(self, tmp_path: Path) -> None:
        r = _make_pending_result(tmp_path)
        exporter = MagicMock()
        execute_c_placement(
            [r], exporter=exporter, log_dir=str(tmp_path), dry_run=False
        )
        lines = _read_audit_lines(tmp_path)
        assert len(lines) == 1
        assert lines[0]["dry_run"] is False
        assert lines[0]["status"] == CPlacementStatus.SUCCESS.value

    def test_real_run_export_exception_marks_error(self, tmp_path: Path) -> None:
        r = _make_pending_result(tmp_path)
        exporter = MagicMock()
        exporter.export_first_page.side_effect = RuntimeError("COM crashed")
        execute_c_placement([r], exporter=exporter, log_dir="", dry_run=False)
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
        execute_c_placement([r2], exporter=None, log_dir="", dry_run=True)
        assert r1.status == CPlacementStatus.PENDING
        assert r1.message == ""  # default
        assert r2.status == CPlacementStatus.PENDING
        assert "dry-run" in r2.message
