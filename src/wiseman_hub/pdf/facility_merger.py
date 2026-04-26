"""事業所フォルダ PDF 結合。

新仕様（事業所単位 1 ファイル ABCABC 連結）:
  入力 A = 提供実績チェックリスト PDF（複数利用者 1 ページずつ、テキスト層あり）
  入力 B = `{事業所}/運動機能向上計画書/{姓 or ゆらぎ名}.pdf` フォルダ
  入力 C = `{事業所}/経過報告書/{姓 or ゆらぎ名}.pdf` フォルダ
  出力   = `{output_root}/{事業所名}/{事業所名}.pdf` の **単一ファイル**

連結ルール:
  - A + B + C 全て揃う利用者**のみ** A→B→C 順に連結し、A.pdf 出現順で並べる
    → `A1+B1+C1+A2+B2+C2+...` の 1 ファイル
  - 不揃い (A単独/A+B/A+C/B+C) は出力に含めず、カテゴリ別に report 記録
  - 同姓重複 fail-safe: 同姓 2 名以上は ABC 全揃いに見えても除外
    → `ambiguous_bc_skipped` に記録、誤添付より添付不足を優先

今回スコープ:
  - A の各ページからテキスト層で氏名抽出（OCR 不要）
  - B/C はファイル名（stem）の**姓部分一致**でマッチ（【藤野様】↔ 藤野 等のゆらぎ吸収）

スコープ外（将来拡張）:
  - B/C の PDF テキスト層から氏名抽出による内容ベースマッチ
  - OCR フォールバック（B/C がスキャン画像の場合）
  - フリガナ正規化による厳密五十音順ソート（現状は A.pdf 出現順を継承）
"""

from __future__ import annotations

import logging
from collections import Counter
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
    """1 利用者分のマージ情報（新仕様: 連結された 1 利用者の論理識別子）。

    新仕様では `success` 配下の全 entry は同一の `output_path`（事業所単位ファイル）
    を共有する。各 entry は「事業所単位 PDF 内のどの利用者が連結されたか」を示す
    論理レコードであり、利用者ごとに別ファイルを作るものではない。
    """

    user_key: str  # 事業所単位 PDF 内の論理識別子（抽出された姓ベース）
    full_name: str  # **PII**: ログ・UI 出力禁止、user_key を使うこと
    sources_used: tuple[str, ...]  # 新仕様では常に ("A", "B", "C")
    output_path: Path  # **新仕様**: 全 success entry で同一の事業所単位ファイル


@dataclass(frozen=True)
class FacilityMergeReport:
    """事業所フォルダ処理結果。

    **新仕様 (重要)**: `success` には ABC 全揃いの利用者のみが含まれる。
    下記の除外カテゴリ（a_only / b_missing / c_missing / a_missing /
    ambiguous_bc_skipped）に分類された利用者は **出力 PDF に含まれない**。

    各カテゴリは互いに排他（同じ user_key が複数カテゴリに入ることはない）:
      - a_only: A はあるが B/C 両方なし → 除外
      - b_missing: A はあるが B 欠損（C 判定前に確定 → 除外）
      - c_missing: A + B はあるが C 欠損 → 除外
      - a_missing: B/C のみ存在し A にマッチなし → 除外
      - ambiguous_bc_skipped: 同姓重複で fail-safe 適用 → 除外
      - bc_dirs_missing: 事業所フォルダ配下に B/C サブフォルダ自体が無い場合の
        ディレクトリ名（運用上の重大警告: NW 一時断・タイポ等で全利用者除外
        になるため UI で明示的に警告する必要あり）
    """

    facility_name: str
    output_dir: Path
    success: tuple[UserMergeEntry, ...] = ()
    extraction_failed_pages: tuple[int, ...] = ()  # A.pdf で氏名抽出失敗したページ（0-based）
    a_only: tuple[str, ...] = ()  # A のみ存在（B/C 両方なし）→ 除外
    a_missing: tuple[str, ...] = ()  # B/C のみ存在し A マッチなし → 除外
    b_missing: tuple[str, ...] = ()  # A はあるが B 欠損 → 除外
    c_missing: tuple[str, ...] = ()  # A + B はあるが C 欠損 → 除外
    name_conflicts: tuple[str, ...] = ()  # 同姓で user_key 衝突した連番付与（旧仕様残骸）
    ambiguous_bc_skipped: tuple[str, ...] = ()  # 同姓重複 fail-safe → 除外
    bc_dirs_missing: tuple[str, ...] = ()  # B/C サブフォルダ自体が不在（重大警告）


def _collect_pdfs_by_stem(directory: Path) -> dict[str, Path]:
    """ディレクトリ内の *.pdf をファイル名 stem → Path でマップ化する。

    ディレクトリ不在時は空 dict を返すが **warning ログを出す** ことで、
    UNC 一時的アクセス失敗等によるデータ欠損の silent drop を可視化する
    （Windows SMB share でネットワーク断時の偽陰性対策）。
    """
    if not directory.exists():
        logger.warning(
            "PDF source directory not found (treating as empty): %s", directory.name
        )
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
    """事業所フォルダの A + B + C PDF を **事業所単位 1 ファイル** に連結する。

    新仕様:
      - A + B + C 全揃いの利用者のみ、A→B→C 順で連結
      - 利用者間は A.pdf 出現順で `A1+B1+C1+A2+B2+C2+...`
      - 出力: `{output_root}/{facility_name}/{facility_name}.pdf` の単一ファイル
      - 全揃い 0 名の場合は出力ファイル自体を作らない
      - 不揃い・同姓重複利用者は出力に含めずカテゴリ別 report 記録

    Args:
        source_a_pdf: 提供実績 PDF（複数利用者、1 利用者 1 ページ、テキスト層あり）
        facility_dir: 事業所フォルダ（配下に `運動機能向上計画書/` と `経過報告書/`）
        output_root: 出力ルート（`{output_root}/{事業所名}/` が作成される）

    Raises:
        FileNotFoundError: source_a_pdf または facility_dir が存在しない
        PdfCorruptedError: A.pdf が空・破損・非PDF（splitter._open_pdf_or_raise 由来）
        PdfEncryptedError: A.pdf が暗号化されている（同上）
        PdfMergeError: B/C 読込または出力書込失敗
    """
    if not source_a_pdf.exists():
        raise FileNotFoundError(f"Source A PDF not found: {source_a_pdf}")
    if not facility_dir.exists():
        raise FileNotFoundError(f"Facility dir not found: {facility_dir}")

    plan_dir = facility_dir / PLAN_DIR_NAME
    report_dir = facility_dir / REPORT_DIR_NAME

    # B/C サブフォルダ不在は **重大警告**（NW 一時断・タイポ等で
    # 全利用者が silent 除外になるため、UI で明示的に告知する）
    bc_dirs_missing: list[str] = []
    if not plan_dir.exists():
        bc_dirs_missing.append(PLAN_DIR_NAME)
        logger.error(
            "B subdirectory missing (silent exclusion risk): %s", PLAN_DIR_NAME
        )
    if not report_dir.exists():
        bc_dirs_missing.append(REPORT_DIR_NAME)
        logger.error(
            "C subdirectory missing (silent exclusion risk): %s", REPORT_DIR_NAME
        )

    plans = _collect_pdfs_by_stem(plan_dir)
    reports = _collect_pdfs_by_stem(report_dir)

    facility_name = facility_dir.name
    output_dir = output_root / facility_name
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{facility_name}.pdf"

    extraction_failed: list[int] = []
    a_only: list[str] = []
    b_missing: list[str] = []
    c_missing: list[str] = []
    a_missing_set: set[str] = set()  # B と C に同一 stem がある場合の重複防止
    ambiguous_bc_skipped: list[str] = []
    name_conflicts: list[str] = []
    used_user_keys: set[str] = set()
    matched_bc_stems: set[str] = set()  # a_missing 計算用

    def _unique_key(base: str) -> tuple[str, bool]:
        """base が使用済なら連番を付与してユニーク化（同姓重複の検知ログ用に維持）。"""
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
        output_path,
    )

    a_doc = _open_pdf_or_raise(source_a_pdf)
    # 全揃い利用者の連結データを A.pdf 出現順に蓄積
    full_set_entries: list[
        tuple[str, bytes, Path, Path, str]
    ] = []  # (user_key, a_page_bytes, b_path, c_path, full_name)
    try:
        # Phase 0: 同姓重複検出（fail-safe 用）
        surname_counts: Counter[str] = Counter()
        for page_index in range(a_doc.page_count):
            e = extract_name_from_page(a_doc[page_index])
            if e is not None:
                surname_counts[e.last_name] += 1
        ambiguous_surnames: set[str] = {
            s for s, c in surname_counts.items() if c >= 2
        }
        if ambiguous_surnames:
            logger.warning(
                "Ambiguous surnames detected (excluded for fail-safe): count=%d",
                len(ambiguous_surnames),
            )

        # Phase 1: A.pdf 各ページを処理し、ABC 全揃い利用者を抽出
        for page_index in range(a_doc.page_count):
            page = a_doc[page_index]
            extracted = extract_name_from_page(page)
            if extracted is None:
                extraction_failed.append(page_index)
                # error 級: 該当ページの利用者は出力 PDF から完全に欠落するため
                # production で見落とし防止に severity を warning から上げる
                logger.error(
                    "Name extraction failed at page %d/%d (user excluded from output)",
                    page_index + 1,
                    a_doc.page_count,
                )
                continue

            user_key, conflicted = _unique_key(extracted.last_name)
            used_user_keys.add(user_key)
            if conflicted:
                name_conflicts.append(user_key)

            # 同姓重複 fail-safe: 該当姓は ABC 全揃いに見えても除外
            if extracted.last_name in ambiguous_surnames:
                ambiguous_bc_skipped.append(user_key)
                logger.warning(
                    "Ambiguous surname fail-safe: excluded page=%d key=%s",
                    page_index + 1,
                    user_key,
                )
                continue

            b_match = _match_by_partial(extracted.last_name, plans)
            c_match = _match_by_partial(extracted.last_name, reports)

            # 排他カテゴリ分類（不揃いは出力に含めず report のみ記録）
            if b_match is None and c_match is None:
                a_only.append(user_key)
                continue
            if b_match is None:
                b_missing.append(user_key)
                continue
            if c_match is None:
                c_missing.append(user_key)
                continue

            # ABC 全揃い → 連結対象として蓄積
            page_bytes = _extract_single_page_pdf(a_doc, page_index)
            full_set_entries.append(
                (user_key, page_bytes, b_match[1], c_match[1], extracted.full_name)
            )
            matched_bc_stems.add(f"B:{b_match[0]}")
            matched_bc_stems.add(f"C:{c_match[0]}")

        # Phase 2: A にマッチしなかった B/C は a_missing にカテゴリ記録のみ
        # （旧仕様の B+C 結合出力は廃止）
        # set 使用: B と C に同一 stem がある場合の二重カウントを構造的に防ぐ
        for stem in plans:
            if f"B:{stem}" not in matched_bc_stems:
                a_missing_set.add(stem)
        for stem in reports:
            if f"C:{stem}" not in matched_bc_stems:
                a_missing_set.add(stem)
    finally:
        a_doc.close()

    a_missing = sorted(a_missing_set)

    # 出力フェーズ: 全揃いがあれば 1 ファイルに ABCABC... 連結、無ければ書き出さない
    # **重要**: success リストへの登録は `_save_atomically` の **書込成功後** に行う。
    # 旧構造（書込前 append）では _save_atomically 失敗時に「成功 N 件」報告が
    # 残ったまま例外伝播し、UI に誤情報が出る silent failure リスクがあった。
    success: list[UserMergeEntry] = []
    if full_set_entries:
        dst = fitz.open()
        try:
            pending_entries: list[UserMergeEntry] = []
            for user_key, a_bytes, b_path, c_path, full_name in full_set_entries:
                _append_pdf_bytes(dst, a_bytes, "A")
                _append_pdf_file(dst, b_path, "B")
                _append_pdf_file(dst, c_path, "C")
                pending_entries.append(
                    UserMergeEntry(
                        user_key=user_key,
                        full_name=full_name,
                        sources_used=("A", "B", "C"),
                        output_path=output_path,
                    )
                )
            _save_atomically(dst, output_path)
            # 書込成功後にのみ success に登録（失敗時は空のまま例外伝播）
            success.extend(pending_entries)
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
        ambiguous_bc_skipped=tuple(ambiguous_bc_skipped),
        bc_dirs_missing=tuple(bc_dirs_missing),
    )
    logger.info(
        "merge_facility done: facility=%s merged=%d extract_failed=%d "
        "a_only=%d a_missing=%d b_missing=%d c_missing=%d "
        "ambiguous_bc_skipped=%d",
        facility_name,
        len(report.success),
        len(report.extraction_failed_pages),
        len(report.a_only),
        len(report.a_missing),
        len(report.b_missing),
        len(report.c_missing),
        len(report.ambiguous_bc_skipped),
    )
    return report
