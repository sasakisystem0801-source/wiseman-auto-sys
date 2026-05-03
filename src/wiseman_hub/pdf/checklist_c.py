"""C (経過報告書) PDF 自動配置エンジン（MVP）。

各行ごとに:
    1. 担当者から xlsx パスを解決（ReportStaffEntry の template 展開）
    2. xlsx 内の利用者シートを特定（氏名一致）
    3. Excel COM で 1 ページ目を PDF 化
    4. FAX 事業所フォルダ配下の経過報告書サブフォルダに配置

xlsx パステンプレート（{era}=令和年, {month}=月数値）:
    base_dir = ``\\\\Tera-station\\share\\PT 宮下``
    year_subfolder_template = ``リハ経過報告書\\令和{era}年``
    file_template = ``リハ経過報告書 (宮下) {month}月 .xlsx``
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from wiseman_hub.cloud.sheets import ChecklistRow
from wiseman_hub.config import ChecklistConfig, ReportStaffEntry
from wiseman_hub.pdf.excel_com import ExcelExporter
from wiseman_hub.pdf.staff_path_scanner import (
    build_folder_tree,
    scan_candidates,
    scan_fallback,
)

logger = logging.getLogger(__name__)


class CPlacementStatus(StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    NEEDS_REVIEW = "needs_review"  # cache miss + 候補あり/なし、人間レビュー UI で選択待ち
    SKIPPED_NO_FACILITY = "skipped_no_facility"
    SKIPPED_NO_STAFF = "skipped_no_staff"  # 担当者マッピング未登録
    SKIPPED_NO_XLSX = "skipped_no_xlsx"
    SKIPPED_NO_SHEET = "skipped_no_sheet"  # xlsx 内に対象利用者シートなし
    SKIPPED_AMBIGUOUS_SHEET = "skipped_ambiguous_sheet"
    ERROR = "error"


@dataclass
class CPlacementResult:
    """C 配置プランの 1 行分の結果。

    NEEDS_REVIEW 時のフィールド:
        xlsx_candidates: scanner が glob 抽出した候補 xlsx の絶対パス list
        rejected_candidates: 候補から除外したパス → 除外理由（例: "staff_token_mismatch"）
        folder_tree: 候補ゼロ時に UI で表示する base_dir 配下のフォルダツリー。
            形式は ``{"name": str, "path": str, "is_dir": bool, "children": [...]}``。
    """

    row: ChecklistRow
    status: CPlacementStatus = CPlacementStatus.PENDING
    xlsx_path: Path | None = None
    sheet_name: str | None = None
    target_pdf: Path | None = None
    sheet_candidates: list[str] = field(default_factory=list)
    xlsx_candidates: list[Path] = field(default_factory=list)
    rejected_candidates: dict[Path, str] = field(default_factory=dict)
    folder_tree: dict[str, Any] | None = None
    message: str = ""


def western_to_reiwa(year: int) -> int:
    """西暦 → 令和年（2019 = R1）。"""
    return year - 2018


def cache_key(staff: str, year: int, month: int) -> str:
    """xlsx_path_cache の dict キー形式（"{staff}:{year}:{month}"）を組み立てる。"""
    return f"{staff}:{year}:{month}"


def resolve_xlsx_path(entry: ReportStaffEntry, year: int, month: int) -> Path:
    """[deprecated] 旧 MVP の単純 template 展開（後方互換専用）。

    新規コードからは ``resolve_xlsx`` 経由で cache + scanner を使うこと。
    suggest_patterns 空 + 旧 *_template フィールドが両方埋まっているときの
    フォールバック用に残置している。

    template が空のときは ``base_dir`` を返すだけになるが、呼び出し側で
    ``exists()`` 失敗扱いになるので機能はしない。
    """
    era = western_to_reiwa(year)
    base = Path(entry.base_dir)
    year_sub = entry.year_subfolder_template.format(era=era, month=month)
    fname = entry.file_template.format(era=era, month=month)
    return base / year_sub / fname


@dataclass
class ResolveResult:
    """resolve_xlsx の戻り値。

    呼び出し側 ``plan_c_placement`` が CPlacementResult に統合する。
    status は CPlacementStatus の以下のサブセットのみを返す:
        - PENDING: cache hit でパス確定（後段でシート検査）
        - NEEDS_REVIEW: 候補抽出に成功（複数 or 単独）、人間レビュー UI で選択待ち
        - SKIPPED_NO_XLSX: 候補ゼロ + folder_tree も組めない（base_dir 不在等）
    """

    status: CPlacementStatus
    xlsx_path: Path | None = None
    candidates: list[Path] = field(default_factory=list)
    folder_tree: dict[str, Any] | None = None
    message: str = ""


def resolve_xlsx(
    staff: str,
    entry: ReportStaffEntry,
    year: int,
    month: int,
    cache: dict[str, str],
) -> ResolveResult:
    """担当者ごとの xlsx パス解決。cache hit → PENDING / miss → NEEDS_REVIEW。

    解決順序:
        1. cache hit でファイル存在 → PENDING（自動確定）
        2. cache stale（path 不在） → fall through、再 scan
        3. suggest_patterns で候補抽出 → 単独/複数とも NEEDS_REVIEW（自動確定しない）
        4. 候補ゼロ + 旧 *_template があれば legacy fallback で path 試行
        5. 候補ゼロ → フォルダツリー + scan_fallback で NEEDS_REVIEW
        6. base_dir 不在 → SKIPPED_NO_XLSX

    自動確定するのは「cache hit」のみ。これは過去に人間が UI で選択 +
    「記憶する」を確定した path であり、deterministic な根拠を持つ。
    """
    key = cache_key(staff, year, month)
    cached_str = cache.get(key)
    if cached_str:
        cached_path = Path(cached_str)
        if cached_path.exists():
            return ResolveResult(
                status=CPlacementStatus.PENDING,
                xlsx_path=cached_path,
            )
        # cache stale
        logger.info("cache stale for %s, re-scanning", key)

    # suggest_patterns で候補絞り込み
    candidates = scan_candidates(entry, year, month)
    if candidates:
        return ResolveResult(
            status=CPlacementStatus.NEEDS_REVIEW,
            candidates=candidates,
            message=f"{len(candidates)} 件候補あり、確認後に選択してください",
        )

    # 後方互換: suggest_patterns 空かつ legacy template が埋まっている場合
    if not entry.suggest_patterns and entry.year_subfolder_template and entry.file_template:
        legacy = resolve_xlsx_path(entry, year, month)
        if legacy.exists():
            return ResolveResult(
                status=CPlacementStatus.PENDING,
                xlsx_path=legacy,
                message="legacy template 経路で解決",
            )

    # フォールバック: base_dir 配下を浅く scan + folder_tree 提示
    base = Path(entry.base_dir) if entry.base_dir else None
    if base is None or not base.exists():
        return ResolveResult(
            status=CPlacementStatus.SKIPPED_NO_XLSX,
            message=f"base_dir 不在または未設定: {entry.base_dir or '(empty)'}",
        )
    fallback = scan_fallback(base, max_depth=3)
    tree = build_folder_tree(base, max_depth=3)
    return ResolveResult(
        status=CPlacementStatus.NEEDS_REVIEW,
        candidates=fallback,
        folder_tree=tree,
        message="候補なし、フォルダから選択してください",
    )


def _normalize_name(name: str) -> str:
    return name.replace("　", "").replace(" ", "").strip()


def find_sheet_for_user(xlsx_path: Path, user_name: str) -> tuple[str | None, list[str]]:
    """xlsx 内のシート名から利用者氏名にマッチするものを探す。"""
    if not xlsx_path.exists():
        return None, []
    target = _normalize_name(user_name)
    with open(xlsx_path, "rb") as f:
        wb = load_workbook(io.BytesIO(f.read()), read_only=True)
    try:
        names = list(wb.sheetnames)
    finally:
        wb.close()
    matches = [n for n in names if _normalize_name(n) == target]
    if len(matches) == 1:
        return matches[0], names
    return None, names


def resolve_facility(facility_name: str, routing: dict[str, str]) -> str | None:
    if facility_name in routing:
        return routing[facility_name]
    return None


def plan_c_placement(
    rows: list[ChecklistRow],
    cfg: ChecklistConfig,
    year: int,
    month: int,
) -> list[CPlacementResult]:
    """C 配置の計画を立てる（実 PDF 化はしない）。

    各行ごとに:
        1. 居宅 → FAX フォルダ resolve
        2. 担当者 → ReportStaffEntry resolve
        3. resolve_xlsx で cache hit / 候補抽出 / フォールバック
        4. PENDING のみシート検査して target_pdf 確定
        5. NEEDS_REVIEW は xlsx_candidates / folder_tree を保持して UI に渡す
    """
    fax_root = Path(cfg.fax_root)
    results: list[CPlacementResult] = []
    for row in rows:
        result = CPlacementResult(row=row)
        fax_folder = resolve_facility(row.facility, cfg.facility_routing)
        if not fax_folder:
            result.status = CPlacementStatus.SKIPPED_NO_FACILITY
            result.message = f"居宅マッピング未登録: {row.facility}"
            results.append(result)
            continue
        staff_entry = cfg.report_staff.get(row.staff)
        if staff_entry is None:
            result.status = CPlacementStatus.SKIPPED_NO_STAFF
            result.message = f"担当者マッピング未登録: {row.staff}"
            results.append(result)
            continue

        resolved = resolve_xlsx(
            staff=row.staff,
            entry=staff_entry,
            year=year,
            month=month,
            cache=cfg.xlsx_path_cache,
        )

        if resolved.status == CPlacementStatus.NEEDS_REVIEW:
            result.status = CPlacementStatus.NEEDS_REVIEW
            result.xlsx_candidates = resolved.candidates
            result.folder_tree = resolved.folder_tree
            result.message = resolved.message
            # NEEDS_REVIEW では target_pdf 確定不能、ユーザー選択後に再 plan
            results.append(result)
            continue

        if resolved.status == CPlacementStatus.SKIPPED_NO_XLSX:
            result.status = CPlacementStatus.SKIPPED_NO_XLSX
            result.message = resolved.message
            results.append(result)
            continue

        # PENDING（cache hit または legacy fallback）
        xlsx_path = resolved.xlsx_path
        assert xlsx_path is not None
        sheet_name, all_sheets = find_sheet_for_user(xlsx_path, row.name)
        if sheet_name is None:
            if all_sheets:
                result.sheet_candidates = all_sheets
            result.status = CPlacementStatus.SKIPPED_NO_SHEET
            result.message = f"利用者シート未発見: {row.name}"
            results.append(result)
            continue
        target = fax_root / fax_folder / cfg.c_output_subfolder / f"{row.name}.pdf"
        result.xlsx_path = xlsx_path
        result.sheet_name = sheet_name
        result.target_pdf = target
        result.status = CPlacementStatus.PENDING
        results.append(result)
    return results


def apply_xlsx_selection(
    result: CPlacementResult,
    xlsx_path: Path,
    cfg: ChecklistConfig,
) -> None:
    """ユーザーがレビュー UI で選択した xlsx_path を result に in-place 反映する。

    シート検査 → 利用者シート存在 + 単独 → PENDING + target_pdf 確定。
    シート未検出または曖昧 → SKIPPED_NO_SHEET / SKIPPED_AMBIGUOUS_SHEET。

    呼び出し側 (UI) は本関数の後に必要に応じて cfg.xlsx_path_cache を更新する。
    本関数は cache 操作を行わない（責務分離）。
    """
    fax_root = Path(cfg.fax_root)
    fax_folder = resolve_facility(result.row.facility, cfg.facility_routing)
    if not fax_folder:
        result.status = CPlacementStatus.SKIPPED_NO_FACILITY
        result.message = f"居宅マッピング未登録: {result.row.facility}"
        return
    sheet_name, all_sheets = find_sheet_for_user(xlsx_path, result.row.name)
    if sheet_name is None:
        if all_sheets:
            result.sheet_candidates = all_sheets
        result.status = CPlacementStatus.SKIPPED_NO_SHEET
        result.message = f"利用者シート未発見: {result.row.name}"
        return
    target = fax_root / fax_folder / cfg.c_output_subfolder / f"{result.row.name}.pdf"
    result.xlsx_path = xlsx_path
    result.sheet_name = sheet_name
    result.target_pdf = target
    result.status = CPlacementStatus.PENDING
    # NEEDS_REVIEW 時のフィールドはクリア（UI に古い候補を表示させない）
    result.xlsx_candidates = []
    result.folder_tree = None
    result.message = ""


def execute_c_placement(
    results: list[CPlacementResult], exporter: ExcelExporter
) -> list[CPlacementResult]:
    """PENDING の plan を Excel COM で PDF 化して配置する。"""
    try:
        for r in results:
            if r.status != CPlacementStatus.PENDING:
                continue
            if r.xlsx_path is None or r.sheet_name is None or r.target_pdf is None:
                r.status = CPlacementStatus.ERROR
                r.message = "internal: missing xlsx/sheet/target"
                continue
            try:
                exporter.export_first_page(r.xlsx_path, r.sheet_name, r.target_pdf)
                r.status = CPlacementStatus.SUCCESS
            except Exception as exc:  # MVP: 詳細分類は後段
                r.status = CPlacementStatus.ERROR
                r.message = f"export failed: {exc.__class__.__name__}: {exc}"
                logger.exception("Excel export failed for %s", r.row.name)
    finally:
        exporter.close()
    return results
