"""事業所ルートフォルダ一括実行 runner（W3）。

scanner（W2）が返した FacilityCandidate から組み立てた BulkExecutionItem を
順次 merge_facility で処理する。

主な責務:
    - selected な item を順次（max 1 並列）処理
    - PermissionError を `FAILED_LOCKED` + UI 文言「PDFを閉じてから再実行」に変換（AC-13）
    - 他例外は `FAILED` + 型名のみ（PII 防御、AC-6）
    - 1 件失敗でも続行（後続事業所の処理は止めない、AC-6）
    - cancel_event で「次の事業所から停止」（現在実行中は中断しない）
    - progress_callback で各 item の状態変化を通知（UI スレッドへの bridge 用）

設計判断:
    - merge_fn は DI（テストで `merge_facility` を差し替え可能）
    - BulkExecutionItem は frozen ではない（status を in-place 更新する）
    - cancel は事業所間の境界でチェックのみ（merge_facility の中断はしない）
    - progress_callback の例外は捕捉して run を継続（UI コードのバグ耐性）
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from wiseman_hub.pdf.facility_merger import FacilityMergeReport, merge_facility
from wiseman_hub.pdf.facility_scanner import FacilityCandidate

logger = logging.getLogger(__name__)


MergeFn = Callable[[Path, Path, Path], FacilityMergeReport]
ProgressCallback = Callable[[int, "BulkExecutionItem"], None]

#: 公開されるデフォルト merge 関数（テストの後方互換確認用に変数化）。
_DEFAULT_MERGE_FN: Final[MergeFn] = merge_facility


class BulkExecutionStatus(StrEnum):
    """一括実行中の事業所単位ステータス（実行中・実行後）。

    scanner（W2）の FacilityStatus は実行前段階（PENDING/A_MISSING/A_MULTIPLE）、
    本 enum は実行プロセス中・後の状態を表す。
    """

    PENDING = "pending"  # 実行待ち（runner に渡される時点の初期値）
    RUNNING = "running"  # 処理中
    SUCCESS = "success"  # report.success > 0
    PARTIAL = "partial"  # report.success == 0（除外のみ、出力ファイルなし）
    FAILED = "failed"  # 例外（PermissionError 以外）
    FAILED_LOCKED = "failed_locked"  # PermissionError（PDF lock）
    CANCELLED_SKIPPED = "cancelled_skipped"  # cancel_event 後の未処理


# UI 文言定数（PII を含まない汎用メッセージ、現場向け平易な日本語）
_MSG_LOCKED: Final[str] = "結合 PDF を閉じてから再実行してください"


@dataclass
class BulkExecutionItem:
    """1 事業所分の実行要求 + 結果。

    UI から渡される時点では status=PENDING、merge_fn 実行を経て終端状態に遷移する。

    Attributes:
        candidate: scanner が返した FacilityCandidate。
        a_pdf_path: 解決済 A.pdf パス。
            FacilityStatus.PENDING の場合は ``candidate.a_pdf_path`` をそのまま使う。
            A_MULTIPLE をユーザーが解決済の場合は選択された Path。
        output_root: 事業所サブフォルダの親ディレクトリ（要件 3 でルート自身と同一）。
        status: 実行ステータス（mutable、in-place 更新）。
        report: merge_facility の戻り値（成功時のみ非 None）。
        error_message: UI 表示用の文言（PII 防御済、エラー時のみ非 None）。
    """

    candidate: FacilityCandidate
    a_pdf_path: Path
    output_root: Path
    status: BulkExecutionStatus = BulkExecutionStatus.PENDING
    report: FacilityMergeReport | None = None
    error_message: str | None = None


def _safe_progress(
    callback: ProgressCallback | None, index: int, item: BulkExecutionItem
) -> None:
    """progress_callback 呼出を例外耐性つきで実行。

    UI 側の callback がバグで例外を投げても、bulk run 全体を巻き込まない。
    """
    if callback is None:
        return
    try:
        callback(index, item)
    except Exception as e:  # noqa: BLE001 — UI コードの不具合で run を止めない
        logger.warning(
            "progress_callback raised: %s (continuing run)", type(e).__name__
        )


def _classify_success(report: FacilityMergeReport) -> BulkExecutionStatus:
    """merge_facility 完了時のステータス分類: 結合 1 名以上 → SUCCESS、0 名 → PARTIAL。"""
    if len(report.success) > 0:
        return BulkExecutionStatus.SUCCESS
    return BulkExecutionStatus.PARTIAL


def run_bulk_merge(
    items: list[BulkExecutionItem],
    *,
    progress_callback: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
    merge_fn: MergeFn | None = None,
) -> list[BulkExecutionItem]:
    """事業所一括実行のエントリポイント。

    Args:
        items: 実行対象（事前にチェック ON 済かつ A.pdf 解決済のみが渡される想定）。
        progress_callback: 各 item のステータス変化時に ``(index, item)`` で呼ばれる。
            RUNNING / 終端ステータス遷移ごとに通知される。
        cancel_event: セットされたら以降の item を CANCELLED_SKIPPED にする。
            現在処理中の merge_fn は完了まで待つ（中断しない）。
        merge_fn: DI 用。省略時は ``merge_facility`` を使う。

    Returns:
        入力 ``items`` をそのまま返す（status / report / error_message が更新される）。
    """
    fn: MergeFn = merge_fn if merge_fn is not None else _DEFAULT_MERGE_FN

    for index, item in enumerate(items):
        # cancel_event の境界チェック（事業所単位）
        if cancel_event is not None and cancel_event.is_set():
            item.status = BulkExecutionStatus.CANCELLED_SKIPPED
            _safe_progress(progress_callback, index, item)
            continue

        item.status = BulkExecutionStatus.RUNNING
        _safe_progress(progress_callback, index, item)

        try:
            report = fn(item.a_pdf_path, item.candidate.facility_dir, item.output_root)
        except PermissionError as e:
            # AC-13: Windows で出力 PDF が Acrobat 等で開かれている典型例
            logger.error(
                "merge_facility PermissionError (likely PDF lock): facility=%s type=%s",
                item.candidate.facility_name,
                type(e).__name__,
            )
            item.status = BulkExecutionStatus.FAILED_LOCKED
            item.error_message = _MSG_LOCKED
        except Exception as e:  # noqa: BLE001 — 1 件失敗で他事業所を巻き込まない（AC-6）
            # PII 防御: 例外メッセージ本文（パス含むことがある）はログにも UI にも出さない
            logger.error(
                "merge_facility failed: facility=%s type=%s",
                item.candidate.facility_name,
                type(e).__name__,
            )
            item.status = BulkExecutionStatus.FAILED
            item.error_message = type(e).__name__
        else:
            item.report = report
            item.status = _classify_success(report)

        _safe_progress(progress_callback, index, item)

    logger.info(
        "run_bulk_merge done: total=%d success=%d partial=%d failed=%d "
        "failed_locked=%d cancelled=%d",
        len(items),
        sum(1 for it in items if it.status == BulkExecutionStatus.SUCCESS),
        sum(1 for it in items if it.status == BulkExecutionStatus.PARTIAL),
        sum(1 for it in items if it.status == BulkExecutionStatus.FAILED),
        sum(1 for it in items if it.status == BulkExecutionStatus.FAILED_LOCKED),
        sum(1 for it in items if it.status == BulkExecutionStatus.CANCELLED_SKIPPED),
    )
    return items
