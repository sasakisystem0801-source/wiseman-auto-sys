"""事業所一括実行 runner のユニットテスト（W3）。

run_bulk_merge() が以下を満たすことを検証する:
- selected な item を順次 merge_fn で処理
- PermissionError → FAILED_LOCKED + 「PDFを閉じてから再実行」文言（AC-13）
- 他例外 → FAILED + 型名（PII 防御）（AC-6）
- cancel_event セット → 以降の item は CANCELLED_SKIPPED、現在実行中は完了まで待機
- progress_callback で各 item の状態変化通知
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from wiseman_hub.pdf.facility_bulk_runner import (
    BulkExecutionItem,
    BulkExecutionStatus,
    run_bulk_merge,
)
from wiseman_hub.pdf.facility_merger import FacilityMergeReport, UserMergeEntry
from wiseman_hub.pdf.facility_scanner import FacilityCandidate, FacilityStatus


def _make_candidate(tmp_path: Path, name: str) -> FacilityCandidate:
    """テスト用に FacilityCandidate を作る（実ファイル不要、ロジックのみ検証）。"""
    facility_dir = tmp_path / name
    return FacilityCandidate(
        facility_dir=facility_dir,
        facility_name=name,
        status=FacilityStatus.PENDING,
        a_pdf_path=facility_dir / "提供実績.pdf",
        a_pdf_candidates=(facility_dir / "提供実績.pdf",),
        output_pdf_path=facility_dir / f"{name}.pdf",
        has_existing_output=False,
    )


def _make_item(tmp_path: Path, name: str) -> BulkExecutionItem:
    cand = _make_candidate(tmp_path, name)
    return BulkExecutionItem(
        candidate=cand,
        a_pdf_path=cand.a_pdf_path or Path("/missing"),
        output_root=tmp_path,
    )


def _success_report(facility_name: str, output_dir: Path) -> FacilityMergeReport:
    return FacilityMergeReport(
        facility_name=facility_name,
        output_dir=output_dir,
        success=(
            UserMergeEntry(
                user_key="宇都宮",
                full_name="宇都宮太郎",
                sources_used=("A", "B", "C"),
                output_path=output_dir / f"{facility_name}.pdf",
            ),
        ),
    )


def _empty_report(facility_name: str, output_dir: Path) -> FacilityMergeReport:
    """report.success == 0（除外のみ、PARTIAL 判定用）。"""
    return FacilityMergeReport(
        facility_name=facility_name,
        output_dir=output_dir,
        success=(),
        a_only=("田中",),
    )


# -----------------------------------------------------------------------------
# 正常系
# -----------------------------------------------------------------------------


def test_all_success(tmp_path: Path) -> None:
    """全 item 成功 → 全 SUCCESS、merge_fn は selected_a_pdf で呼ばれる。"""
    items = [_make_item(tmp_path, "事業所A"), _make_item(tmp_path, "事業所B")]
    calls: list[tuple[Path, Path, Path]] = []

    def fake_merge(a: Path, facility: Path, out: Path) -> FacilityMergeReport:
        calls.append((a, facility, out))
        return _success_report(facility.name, out / facility.name)

    result = run_bulk_merge(items, merge_fn=fake_merge)

    assert all(it.status == BulkExecutionStatus.SUCCESS for it in result)
    assert all(it.report is not None for it in result)
    # merge_fn は item.a_pdf_path / candidate.facility_dir / output_root の順で呼ばれる
    assert calls[0] == (items[0].a_pdf_path, items[0].candidate.facility_dir, tmp_path)
    assert calls[1] == (items[1].a_pdf_path, items[1].candidate.facility_dir, tmp_path)


def test_partial_when_no_success(tmp_path: Path) -> None:
    """report.success == 0（除外のみ）→ PARTIAL ステータス。"""
    items = [_make_item(tmp_path, "全員除外")]

    def fake_merge(a: Path, facility: Path, out: Path) -> FacilityMergeReport:
        return _empty_report(facility.name, out / facility.name)

    result = run_bulk_merge(items, merge_fn=fake_merge)

    assert result[0].status == BulkExecutionStatus.PARTIAL
    assert result[0].report is not None
    assert len(result[0].report.success) == 0


def test_empty_items_returns_empty(tmp_path: Path) -> None:
    """空 list → 空 list、merge_fn 呼ばれず、callback も呼ばれない。"""
    calls: list[int] = []

    def fake_merge(a: Path, facility: Path, out: Path) -> FacilityMergeReport:
        calls.append(1)
        return _success_report(facility.name, out)

    result = run_bulk_merge([], merge_fn=fake_merge)

    assert result == []
    assert calls == []


# -----------------------------------------------------------------------------
# 例外処理（AC-6, AC-13）
# -----------------------------------------------------------------------------


def test_permission_error_yields_failed_locked(tmp_path: Path) -> None:
    """PermissionError → FAILED_LOCKED + UI 向け文言（AC-13）。

    Windows で出力 PDF が Acrobat 等で開かれている場合、現場で頻発するため
    「PDFを閉じてから再実行」文言で IT 非専門ユーザーを誘導する。
    """
    items = [_make_item(tmp_path, "ロック中")]

    def fake_merge(a: Path, facility: Path, out: Path) -> FacilityMergeReport:
        raise PermissionError("simulated Windows lock")

    result = run_bulk_merge(items, merge_fn=fake_merge)

    item = result[0]
    assert item.status == BulkExecutionStatus.FAILED_LOCKED
    assert item.error_message is not None
    assert "PDF" in item.error_message
    assert "閉じ" in item.error_message  # 「閉じてから」「閉じて」のいずれか
    # 内部例外メッセージ（パス含む）が UI 文言に漏れない PII 防御
    assert "simulated" not in item.error_message


def test_other_exception_yields_failed_with_type_name(tmp_path: Path) -> None:
    """PermissionError 以外の例外 → FAILED + 型名のみ（PII 防御、AC-6）。"""
    items = [_make_item(tmp_path, "壊れた")]

    class _CustomError(Exception):
        pass

    def fake_merge(a: Path, facility: Path, out: Path) -> FacilityMergeReport:
        raise _CustomError("internal path /private/施設X/秘密.pdf")

    result = run_bulk_merge(items, merge_fn=fake_merge)

    item = result[0]
    assert item.status == BulkExecutionStatus.FAILED
    assert item.error_message is not None
    # PII 防御: 例外メッセージ本文（パス）は UI 文言に含めない、型名のみ
    assert "_CustomError" in item.error_message or "CustomError" in item.error_message
    assert "施設X" not in item.error_message
    assert "/private" not in item.error_message


def test_failure_does_not_stop_subsequent_items(tmp_path: Path) -> None:
    """1 件目失敗でも 2 件目以降は処理継続（AC-6）。最終サマリで failed/success が判別可能。"""
    items = [
        _make_item(tmp_path, "失敗"),
        _make_item(tmp_path, "成功1"),
        _make_item(tmp_path, "成功2"),
    ]

    def fake_merge(a: Path, facility: Path, out: Path) -> FacilityMergeReport:
        if "失敗" in facility.name:
            raise OSError("disk full")
        return _success_report(facility.name, out / facility.name)

    result = run_bulk_merge(items, merge_fn=fake_merge)

    statuses = [it.status for it in result]
    assert statuses[0] == BulkExecutionStatus.FAILED
    assert statuses[1] == BulkExecutionStatus.SUCCESS
    assert statuses[2] == BulkExecutionStatus.SUCCESS


# -----------------------------------------------------------------------------
# キャンセル（cancel_event、AC: 「次の事業所から停止」）
# -----------------------------------------------------------------------------


def test_cancel_before_run_skips_all(tmp_path: Path) -> None:
    """事前にセットされた cancel_event → 全 item が CANCELLED_SKIPPED、merge_fn 呼ばれず。"""
    items = [_make_item(tmp_path, "事業所A"), _make_item(tmp_path, "事業所B")]
    cancel = threading.Event()
    cancel.set()
    calls: list[Path] = []

    def fake_merge(a: Path, facility: Path, out: Path) -> FacilityMergeReport:
        calls.append(facility)
        return _success_report(facility.name, out)

    result = run_bulk_merge(items, cancel_event=cancel, merge_fn=fake_merge)

    assert all(it.status == BulkExecutionStatus.CANCELLED_SKIPPED for it in result)
    assert calls == []


def test_cancel_mid_run_completes_current_skips_rest(tmp_path: Path) -> None:
    """実行中に cancel_event セット → 現在処理中は完了、以降は CANCELLED_SKIPPED。

    `merge_fn` の中断は行わない（merge_facility は atomic 書込で短時間完了する想定）。
    """
    items = [
        _make_item(tmp_path, "1"),
        _make_item(tmp_path, "2"),
        _make_item(tmp_path, "3"),
    ]
    cancel = threading.Event()
    call_count = [0]

    def fake_merge(a: Path, facility: Path, out: Path) -> FacilityMergeReport:
        call_count[0] += 1
        # 1 件目が処理中に cancel をセットする想定
        if call_count[0] == 1:
            cancel.set()
        return _success_report(facility.name, out / facility.name)

    result = run_bulk_merge(items, cancel_event=cancel, merge_fn=fake_merge)

    # 1 件目: 完了（SUCCESS）
    assert result[0].status == BulkExecutionStatus.SUCCESS
    # 2, 3 件目: CANCELLED_SKIPPED
    assert result[1].status == BulkExecutionStatus.CANCELLED_SKIPPED
    assert result[2].status == BulkExecutionStatus.CANCELLED_SKIPPED
    # merge_fn は 1 件目のみ呼ばれる
    assert call_count[0] == 1


def test_no_cancel_event_runs_all(tmp_path: Path) -> None:
    """cancel_event=None でも全件処理される（オプショナル引数）。"""
    items = [_make_item(tmp_path, "1"), _make_item(tmp_path, "2")]

    def fake_merge(a: Path, facility: Path, out: Path) -> FacilityMergeReport:
        return _success_report(facility.name, out)

    result = run_bulk_merge(items, merge_fn=fake_merge)

    assert all(it.status == BulkExecutionStatus.SUCCESS for it in result)


# -----------------------------------------------------------------------------
# progress_callback
# -----------------------------------------------------------------------------


@dataclass
class _CallbackLog:
    events: list[tuple[int, BulkExecutionStatus]] = field(default_factory=list)

    def __call__(self, index: int, item: BulkExecutionItem) -> None:
        self.events.append((index, item.status))


def test_progress_callback_called_for_each_state_change(tmp_path: Path) -> None:
    """各 item で RUNNING → 終端状態の 2 回 callback が呼ばれる。"""
    items = [_make_item(tmp_path, "1"), _make_item(tmp_path, "2")]
    log = _CallbackLog()

    def fake_merge(a: Path, facility: Path, out: Path) -> FacilityMergeReport:
        return _success_report(facility.name, out)

    run_bulk_merge(items, progress_callback=log, merge_fn=fake_merge)

    # 各 item: (index, RUNNING) → (index, SUCCESS) の順
    assert log.events == [
        (0, BulkExecutionStatus.RUNNING),
        (0, BulkExecutionStatus.SUCCESS),
        (1, BulkExecutionStatus.RUNNING),
        (1, BulkExecutionStatus.SUCCESS),
    ]


def test_progress_callback_for_cancelled(tmp_path: Path) -> None:
    """CANCELLED_SKIPPED でも callback が呼ばれる（UI 反映のため）。"""
    items = [_make_item(tmp_path, "1"), _make_item(tmp_path, "2")]
    cancel = threading.Event()
    cancel.set()
    log = _CallbackLog()

    def fake_merge(a: Path, facility: Path, out: Path) -> FacilityMergeReport:
        return _success_report(facility.name, out)

    run_bulk_merge(
        items, progress_callback=log, cancel_event=cancel, merge_fn=fake_merge
    )

    assert log.events == [
        (0, BulkExecutionStatus.CANCELLED_SKIPPED),
        (1, BulkExecutionStatus.CANCELLED_SKIPPED),
    ]


def test_progress_callback_failure_does_not_break_run(
    tmp_path: Path,
) -> None:
    """progress_callback 自体が例外を投げても run は継続する（UI コードのバグ耐性）。"""
    items = [_make_item(tmp_path, "1"), _make_item(tmp_path, "2")]
    call_count = [0]

    def crashing_callback(index: int, item: BulkExecutionItem) -> None:
        call_count[0] += 1
        raise RuntimeError("UI thread error")

    def fake_merge(a: Path, facility: Path, out: Path) -> FacilityMergeReport:
        return _success_report(facility.name, out)

    # 例外が伝播しないこと、両 item とも処理されること
    result = run_bulk_merge(
        items, progress_callback=crashing_callback, merge_fn=fake_merge
    )

    assert all(it.status == BulkExecutionStatus.SUCCESS for it in result)
    assert call_count[0] >= 2  # 各 item で少なくとも 1 回は呼ばれる


# -----------------------------------------------------------------------------
# 後方互換: 既存 merge_facility と組み合わせて使える
# -----------------------------------------------------------------------------


def test_default_merge_fn_is_merge_facility() -> None:
    """merge_fn 省略時は wiseman_hub.pdf.facility_merger.merge_facility が使われる。

    AC-8: 既存 merge_facility シグネチャを破壊しない（runner はそのまま再利用）。
    """
    from wiseman_hub.pdf.facility_bulk_runner import _DEFAULT_MERGE_FN
    from wiseman_hub.pdf.facility_merger import merge_facility

    assert _DEFAULT_MERGE_FN is merge_facility


# -----------------------------------------------------------------------------
# 監査ログ（PII 防御）
# -----------------------------------------------------------------------------


def test_logger_does_not_emit_full_path(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """ログに事業所フルパスや絶対パスが残らない（PII 防御）。

    施設名は OK、絶対パスや外部にコピーすると問題な情報は出さない。
    """
    import logging

    items = [_make_item(tmp_path, "テスト施設")]

    def fake_merge(a: Path, facility: Path, out: Path) -> FacilityMergeReport:
        raise OSError("/private/Volumes/secret/施設データ/A.pdf")

    with caplog.at_level(logging.WARNING, logger="wiseman_hub.pdf.facility_bulk_runner"):
        run_bulk_merge(items, merge_fn=fake_merge)

    logged = " ".join(r.getMessage() for r in caplog.records)
    # 例外メッセージの内部パスはログに出さない（型名 + facility_name のみ許容）
    assert "/private/Volumes/secret" not in logged
    assert "施設データ" not in logged
