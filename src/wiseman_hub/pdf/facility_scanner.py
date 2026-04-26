"""事業所ルートフォルダ scanner（W2）。

ルートフォルダ配下の各サブディレクトリを走査し、
「事業所フォルダ」を判定して候補リストを返す。

事業所フォルダの定義:
    直下に `運動機能向上計画書/` AND `経過報告書/` の両方が存在するサブディレクトリ。

A.pdf 特定ルール:
    事業所フォルダ直下の `*.pdf`（拡張子大文字小文字非依存）を収集し、
    **`{事業所名}.pdf`（既存出力ファイル）を A 候補から除外** する（AC-12）。
    残りの件数で status を決定:
        - 0 件 → ``A_MISSING``
        - 1 件 → ``PENDING``（実行可能）
        - 2 件以上 → ``A_MULTIPLE``（UI で 1 件選択するまで実行不可）

設計判断:
    - FacilityCandidate は frozen（イミュータブル）。UI 状態（チェック ON/OFF や
      A_MULTIPLE 解決）は別構造で持つ
    - status は StrEnum（Python 3.11+）。UI 文言マッピングは呼び出し元責務
    - I/O エラー（PermissionError 等）は呼び出し元へ伝播。scan の途中で 1 事業所が
      壊れていても他事業所の処理は続けないのは設計判断（root レベルの権限問題は
      全件影響する想定なので fail-fast にする）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from wiseman_hub.pdf.facility_merger import PLAN_DIR_NAME, REPORT_DIR_NAME

logger = logging.getLogger(__name__)

_PDF_SUFFIX_LOWER = ".pdf"


class FacilityStatus(StrEnum):
    """scan 結果の事業所単位ステータス（実行前段階）。

    実行中・実行後の status（running / success / partial / failed / cancelled_skipped）は
    bulk runner（W3）側で管理する別 enum を持つ。scan の段階では「実行可能か」だけを判定する。
    """

    PENDING = "pending"  # ABC 揃いで実行可能（A.pdf 1 件）
    A_MISSING = "a_missing"  # 事業所直下に PDF が 0 件 → 実行不可
    A_MULTIPLE = "a_multiple"  # PDF 2 件以上 → ユーザー 1 件選択するまで実行不可


@dataclass(frozen=True)
class FacilityCandidate:
    """scan で検出された 1 事業所分の候補情報。

    Attributes:
        facility_dir: 事業所フォルダのパス。
        facility_name: 事業所フォルダ名（``facility_dir.name``）。
        status: 実行前ステータス（``FacilityStatus``）。
        a_pdf_path: PENDING 時のみ非 None。A_MISSING / A_MULTIPLE では None。
        a_pdf_candidates: 検出された PDF 全候補（出力ファイル除外後）。
            UI で A_MULTIPLE 時の選択肢として使う。PENDING 時は 1 要素 tuple。
        output_pdf_path: 出力先 ``{facility_dir}/{facility_name}.pdf``（実行されなくても算出）。
        has_existing_output: 既存出力ファイルが存在するか（UI で「上書きされます」表示用）。
    """

    facility_dir: Path
    facility_name: str
    status: FacilityStatus
    a_pdf_path: Path | None
    a_pdf_candidates: tuple[Path, ...]
    output_pdf_path: Path
    has_existing_output: bool


def _collect_a_candidates(facility_dir: Path, output_pdf_path: Path) -> list[Path]:
    """事業所直下の `*.pdf` を収集し、既存出力ファイルを除外する（AC-12 の核）。

    出力ファイルを除外しないと、再実行時に `{事業所名}.pdf` が「もう 1 つの A 候補」
    として認識され A_MULTIPLE 判定 → 永続的に実行不可ループに陥る。

    拡張子は大文字小文字非依存（Windows で `.PDF` 混在の可能性に対応）。
    """
    return sorted(
        p
        for p in facility_dir.iterdir()
        if p.is_file()
        and p.suffix.lower() == _PDF_SUFFIX_LOWER
        and p != output_pdf_path
    )


def _is_facility_dir(entry: Path) -> bool:
    """B/C 両方のサブフォルダが存在 → 事業所と判定（AC-2）。"""
    return (entry / PLAN_DIR_NAME).is_dir() and (entry / REPORT_DIR_NAME).is_dir()


def scan_facility_root(root: Path) -> list[FacilityCandidate]:
    """ルートフォルダ配下を走査し、事業所候補リストを返す。

    Args:
        root: 事業所群が並ぶ親ディレクトリ。

    Returns:
        事業所名昇順でソートされた候補リスト。事業所が無ければ空リスト。

    Raises:
        FileNotFoundError: root が存在しない（AC-9 の一部）。
        NotADirectoryError: root がディレクトリでない（AC-9 の一部）。
    """
    if not root.exists():
        raise FileNotFoundError(f"facility root not found: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"facility root is not a directory: {root}")

    candidates: list[FacilityCandidate] = []
    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if not entry.is_dir():
            continue
        if not _is_facility_dir(entry):
            continue

        facility_name = entry.name
        output_pdf_path = entry / f"{facility_name}.pdf"
        has_existing_output = output_pdf_path.exists()

        a_pdfs = _collect_a_candidates(entry, output_pdf_path)

        if len(a_pdfs) == 0:
            status = FacilityStatus.A_MISSING
            a_pdf_path: Path | None = None
        elif len(a_pdfs) == 1:
            status = FacilityStatus.PENDING
            a_pdf_path = a_pdfs[0]
        else:
            status = FacilityStatus.A_MULTIPLE
            a_pdf_path = None

        candidates.append(
            FacilityCandidate(
                facility_dir=entry,
                facility_name=facility_name,
                status=status,
                a_pdf_path=a_pdf_path,
                a_pdf_candidates=tuple(a_pdfs),
                output_pdf_path=output_pdf_path,
                has_existing_output=has_existing_output,
            )
        )

    logger.info(
        "scan_facility_root done: total=%d pending=%d a_missing=%d a_multiple=%d",
        len(candidates),
        sum(1 for c in candidates if c.status == FacilityStatus.PENDING),
        sum(1 for c in candidates if c.status == FacilityStatus.A_MISSING),
        sum(1 for c in candidates if c.status == FacilityStatus.A_MULTIPLE),
    )
    return candidates
