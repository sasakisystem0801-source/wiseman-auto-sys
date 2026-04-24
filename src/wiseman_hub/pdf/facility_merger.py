"""事業所フォルダ PDF 結合（MVP 暫定実装）。

要件:
  入力 A = 提供実績チェックリスト PDF（複数利用者 1 ページずつ、テキスト層あり）
  入力 B = `{事業所}/運動機能向上計画書/{姓 or ゆらぎ名}.pdf` フォルダ
  入力 C = `{事業所}/経過報告書/{姓 or ゆらぎ名}.pdf` フォルダ
  出力   = `{output_root}/{事業所名}/{姓}.pdf` （A ページ + B + C を結合）

今回スコープ:
  - A の各ページからテキスト層で氏名抽出（OCR 不要）
  - B/C はファイル名（stem）の**姓部分一致**でマッチ（【藤野様】↔ 藤野 等のゆらぎ吸収）
  - 欠損は警告として report に記録し処理継続（片側のみでも出力）
  - A にマッチせず B/C のみある利用者も B+C で出力

スコープ外（将来拡張）:
  - B/C の PDF テキスト層から氏名抽出による内容ベースマッチ
  - OCR フォールバック（B/C がスキャン画像の場合）
  - フリガナ正規化（asao ↔ 浅尾 等）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import fitz

from wiseman_hub.pdf.merger import (
    _append_pdf_bytes,
    _append_pdf_file,
    _save_atomically,
)
from wiseman_hub.pdf.splitter import _extract_single_page_pdf, _open_pdf_or_raise
from wiseman_hub.pdf.text_name_extractor import extract_name_from_page

logger = logging.getLogger(__name__)

PLAN_DIR_NAME: Final[str] = "運動機能向上計画書"
REPORT_DIR_NAME: Final[str] = "経過報告書"


@dataclass(frozen=True)
class UserMergeEntry:
    """1 利用者分のマージ情報。"""

    user_key: str  # 出力ファイル名の stem（抽出された姓 または B/C の stem）
    full_name: str  # 抽出されたフルネーム（A にマッチした場合）または user_key
    sources_used: tuple[str, ...]  # ("A", "B", "C") などの使用ラベル
    output_path: Path


@dataclass(frozen=True)
class FacilityMergeReport:
    """事業所フォルダ処理結果。

    欠損/コンフリクトは互いに重ならない独立集合で記録する:
      - a_only: A のみ存在（B/C 両方なし）
      - b_missing: A + C はあるが B なし（a_only と排他）
      - c_missing: A + B はあるが C なし（a_only と排他）
    """

    facility_name: str
    output_dir: Path
    success: tuple[UserMergeEntry, ...] = ()
    extraction_failed_pages: tuple[int, ...] = ()  # A.pdf で氏名抽出失敗したページ（0-based）
    a_only: tuple[str, ...] = ()  # A のみ存在（B/C 両方なし）
    a_missing: tuple[str, ...] = ()  # B/C はあるが A マッチなし
    b_missing: tuple[str, ...] = ()  # A + C はあるが B なし
    c_missing: tuple[str, ...] = ()  # A + B はあるが C なし
    name_conflicts: tuple[str, ...] = ()  # 同姓で出力キーが衝突したため連番付与した user_key


def _collect_pdfs_by_stem(directory: Path) -> dict[str, Path]:
    """ディレクトリ内の *.pdf をファイル名 stem → Path でマップ化する。"""
    if not directory.exists():
        return {}
    return {p.stem: p for p in sorted(directory.glob("*.pdf"))}


_MIN_STEM_LEN_FOR_SUBSTRING_MATCH: Final[int] = 2


def _match_by_partial(
    last_name: str, candidates: dict[str, Path]
) -> tuple[str, Path] | None:
    """姓の部分文字列一致で最適なファイルを見つける。

    マッチ規則（優先順）:
      1. stem 完全一致
      2. stem が姓を**含む**（【藤野様】は '藤野' を含む）
      3. 姓が stem を含む（stem が 2 文字以上の省略記法のみ）
         → 1 文字 stem ("田") による "田中" / "田村" 等の誤マッチ回避
    """
    if last_name in candidates:
        return last_name, candidates[last_name]
    for stem, path in candidates.items():
        if last_name in stem:
            return stem, path
    for stem, path in candidates.items():
        if len(stem) >= _MIN_STEM_LEN_FOR_SUBSTRING_MATCH and stem in last_name:
            return stem, path
    return None


def merge_facility(
    source_a_pdf: Path,
    facility_dir: Path,
    output_root: Path,
) -> FacilityMergeReport:
    """1 事業所分の A + B + C PDF を利用者単位で結合する。

    Args:
        source_a_pdf: 提供実績 PDF（複数利用者、1 利用者 1 ページ、テキスト層あり）
        facility_dir: 事業所フォルダ（配下に `運動機能向上計画書/` と `経過報告書/`）
        output_root: 出力ルート（`{output_root}/{事業所名}/` が作成される）

    Raises:
        FileNotFoundError: source_a_pdf または facility_dir が存在しない
        PdfMergeError: PDF 読込/書込失敗
    """
    if not source_a_pdf.exists():
        raise FileNotFoundError(f"Source A PDF not found: {source_a_pdf}")
    if not facility_dir.exists():
        raise FileNotFoundError(f"Facility dir not found: {facility_dir}")

    plan_dir = facility_dir / PLAN_DIR_NAME
    report_dir = facility_dir / REPORT_DIR_NAME
    plans = _collect_pdfs_by_stem(plan_dir)
    reports = _collect_pdfs_by_stem(report_dir)

    facility_name = facility_dir.name
    output_dir = output_root / facility_name
    output_dir.mkdir(parents=True, exist_ok=True)

    success: list[UserMergeEntry] = []
    extraction_failed: list[int] = []
    a_only: list[str] = []
    b_missing: list[str] = []
    c_missing: list[str] = []
    matched_bc_stems: set[str] = set()
    used_user_keys: set[str] = set()  # 出力ファイル名衝突検知用
    name_conflicts: list[str] = []

    def _unique_key(base: str) -> tuple[str, bool]:
        """base が使用済なら連番を付与してユニーク化する。
        戻り値: (key, 衝突したか)
        """
        if base not in used_user_keys:
            return base, False
        idx = 2
        while f"{base}_{idx}" in used_user_keys:
            idx += 1
        return f"{base}_{idx}", True

    logger.info(
        "merge_facility start: A=%s facility=%s output=%s",
        source_a_pdf.name,
        facility_name,
        output_dir,
    )

    # Phase 1: A.pdf の各ページを処理
    a_doc = _open_pdf_or_raise(source_a_pdf)
    try:
        for page_index in range(a_doc.page_count):
            page = a_doc[page_index]
            extracted = extract_name_from_page(page)
            if extracted is None:
                extraction_failed.append(page_index)
                logger.warning(
                    "Name extraction failed at page %d/%d",
                    page_index + 1,
                    a_doc.page_count,
                )
                continue

            user_key, conflicted = _unique_key(extracted.last_name)
            used_user_keys.add(user_key)
            if conflicted:
                name_conflicts.append(user_key)
                logger.warning(
                    "Name conflict detected, suffixed: page=%d key=%s",
                    page_index + 1,
                    user_key,
                )
            output_path = output_dir / f"{user_key}.pdf"

            # B/C マッチは元の姓（extracted.last_name）で行う（連番 suffix は出力名のみ）
            b_match = _match_by_partial(extracted.last_name, plans)
            c_match = _match_by_partial(extracted.last_name, reports)

            # 先に排他的分岐で欠損カテゴリを確定（pop 依存を排除）
            if b_match is None and c_match is None:
                a_only.append(user_key)
            else:
                if b_match is None:
                    b_missing.append(user_key)
                if c_match is None:
                    c_missing.append(user_key)

            sources: list[str] = ["A"]
            dst = fitz.open()
            try:
                page_bytes = _extract_single_page_pdf(a_doc, page_index)
                _append_pdf_bytes(dst, page_bytes, "A")

                if b_match is not None:
                    _append_pdf_file(dst, b_match[1], "B")
                    sources.append("B")
                    matched_bc_stems.add(f"B:{b_match[0]}")

                if c_match is not None:
                    _append_pdf_file(dst, c_match[1], "C")
                    sources.append("C")
                    matched_bc_stems.add(f"C:{c_match[0]}")

                _save_atomically(dst, output_path)
                success.append(
                    UserMergeEntry(
                        user_key=user_key,
                        full_name=extracted.full_name,
                        sources_used=tuple(sources),
                        output_path=output_path,
                    )
                )
            finally:
                dst.close()
    finally:
        a_doc.close()

    # Phase 2: A にマッチしなかった B/C の残り（B+C のみで結合）
    # Phase 1 と同じ `_match_by_partial` を使い、B/C 間でもゆらぎ吸収する
    remaining_b = {s: p for s, p in plans.items() if f"B:{s}" not in matched_bc_stems}
    remaining_c = {s: p for s, p in reports.items() if f"C:{s}" not in matched_bc_stems}
    a_missing: list[str] = []
    # B stems を起点にして C と partial マッチ、マッチした C stem は消費
    consumed_c_stems: set[str] = set()
    entries_to_process: list[tuple[str, Path | None, Path | None]] = []

    for b_stem, b_path in sorted(remaining_b.items()):
        # B 主導で C とマッチ
        c_match = _match_by_partial(b_stem, remaining_c)
        if c_match is not None and c_match[0] not in consumed_c_stems:
            consumed_c_stems.add(c_match[0])
            entries_to_process.append((b_stem, b_path, c_match[1]))
        else:
            entries_to_process.append((b_stem, b_path, None))

    # 残った C（B と対応しないもの）を単独で追加
    for c_stem, c_path in sorted(remaining_c.items()):
        if c_stem not in consumed_c_stems:
            entries_to_process.append((c_stem, None, c_path))

    for stem, entry_b, entry_c in entries_to_process:
        user_key, conflicted = _unique_key(stem)
        used_user_keys.add(user_key)
        if conflicted:
            name_conflicts.append(user_key)
        output_path = output_dir / f"{user_key}.pdf"
        sources = []
        dst = fitz.open()
        try:
            if entry_b is not None:
                _append_pdf_file(dst, entry_b, "B")
                sources.append("B")
            if entry_c is not None:
                _append_pdf_file(dst, entry_c, "C")
                sources.append("C")
            if not sources:
                continue
            _save_atomically(dst, output_path)
            a_missing.append(user_key)
            success.append(
                UserMergeEntry(
                    user_key=user_key,
                    full_name=stem,
                    sources_used=tuple(sources),
                    output_path=output_path,
                )
            )
        finally:
            dst.close()

    report = FacilityMergeReport(
        facility_name=facility_name,
        output_dir=output_dir,
        success=tuple(success),
        extraction_failed_pages=tuple(extraction_failed),
        a_only=tuple(a_only),
        a_missing=tuple(a_missing),
        b_missing=tuple(b_missing),
        c_missing=tuple(c_missing),
        name_conflicts=tuple(name_conflicts),
    )
    logger.info(
        "merge_facility done: facility=%s success=%d extract_failed=%d "
        "a_only=%d a_missing=%d b_missing=%d c_missing=%d conflicts=%d",
        facility_name,
        len(report.success),
        len(report.extraction_failed_pages),
        len(report.a_only),
        len(report.a_missing),
        len(report.b_missing),
        len(report.c_missing),
        len(report.name_conflicts),
    )
    return report
