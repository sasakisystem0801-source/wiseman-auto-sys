"""B (運動機能向上計画書/モニタリング) PDF 自動配置エンジン（MVP）。

スプレッドシート選択月の対象行ごとに、カルテ階層から該当月 PDF を見つけ、
FAX 事業所フォルダ配下の運動機能向上計画書サブフォルダにコピーする。

カルテ階層:
    {karte_root}/{五十音行}/{(ふりがな)氏名}/{monitoring_subfolder}/{月}.pdf

出力先:
    {fax_root}/{FAX事業所フォルダ}/{b_output_subfolder}/{利用者名}.pdf
"""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from wiseman_hub.cloud.sheets import ChecklistRow
from wiseman_hub.config import ChecklistConfig

logger = logging.getLogger(__name__)


class PlacementStatus(StrEnum):
    """1 行ごとの配置結果。"""

    PENDING = "pending"
    SUCCESS = "success"
    SKIPPED_NO_FACILITY = "skipped_no_facility"  # 居宅マッピング未登録
    SKIPPED_NO_USER_DIR = "skipped_no_user_dir"  # 利用者フォルダ未発見
    SKIPPED_NO_PDF = "skipped_no_pdf"  # 月別 PDF 未発見
    SKIPPED_AMBIGUOUS = "skipped_ambiguous"  # 同名複数（手動選択待ち）
    ERROR = "error"


@dataclass
class PlacementResult:
    row: ChecklistRow
    status: PlacementStatus = PlacementStatus.PENDING
    source_pdf: Path | None = None
    target_pdf: Path | None = None
    candidates: list[Path] = field(default_factory=list)  # AMBIGUOUS 時の選択候補
    message: str = ""


def _strip_furigana(folder_name: str) -> str:
    """``(ふりがな)氏名`` から氏名部分を取り出す。括弧は半角・全角どちらも許容。"""
    s = folder_name
    s = re.sub(r"^\s*[（(][^）)]*[）)]\s*", "", s)
    return s.strip()


def _normalize_name(name: str) -> str:
    """氏名比較用の正規化: 全角/半角スペースを除去。"""
    return name.replace("　", "").replace(" ", "").strip()


def find_user_dir(karte_root: Path, name: str) -> tuple[Path | None, list[Path]]:
    """カルテルート配下の全五十音行から、氏名一致する利用者フォルダを探す。

    Returns:
        (matched_dir, candidates):
            matched_dir: 一意に決まれば Path、それ以外（0件 or 複数）None
            candidates: 部分一致した全フォルダ（同姓同名対応で UI 表示用）
    """
    if not karte_root.exists():
        return None, []
    target = _normalize_name(name)
    matches: list[Path] = []
    for row_dir in karte_root.iterdir():
        if not row_dir.is_dir():
            continue
        for user_dir in row_dir.iterdir():
            if not user_dir.is_dir():
                continue
            stripped = _strip_furigana(user_dir.name)
            if _normalize_name(stripped) == target:
                matches.append(user_dir)
    if len(matches) == 1:
        return matches[0], matches
    return None, matches


def find_monitoring_dir(
    user_dir: Path, canonical_name: str
) -> tuple[Path | None, list[Path]]:
    """利用者フォルダ配下から ``canonical_name`` を含むサブディレクトリを探す。

    Issue #monitoring-substring (2026-05-09): 業務上モニタリングフォルダ名が
    ``08.運動器機能向上計画書`` / ``10.運動器機能向上計画書`` / prefix なし /
    ``運動器機能向上計画書(過去分)`` 等で揺らぐため、設定値を canonical name のみ
    (= ``運動器機能向上計画書``) にし、substring match で全パターンを拾う。

    Args:
        user_dir: 利用者ルートディレクトリ
        canonical_name: 設定値 (例: ``運動器機能向上計画書``)

    Returns:
        (matched_dir, candidates):
            matched_dir: 一意に決まれば Path、それ以外 (0 件 or 複数) None
            candidates: substring match した全候補ディレクトリ (sort 順、UI 表示用)
    """
    if not user_dir.exists():
        return None, []
    matches = sorted(
        d
        for d in user_dir.iterdir()
        if d.is_dir() and canonical_name in d.name
    )
    if len(matches) == 1:
        return matches[0], matches
    return None, matches


def find_month_pdf(monitoring_dir: Path, month: int) -> tuple[Path | None, list[Path]]:
    """``{month}.pdf`` または ``{month}.PDF`` をマッチさせる。複数 PDF は候補返却。"""
    if not monitoring_dir.exists():
        return None, []
    pdfs = sorted(p for p in monitoring_dir.iterdir() if p.suffix.lower() == ".pdf")
    if not pdfs:
        return None, []
    # 「月」マッチ: stem == str(month) or stem == f"{month:02d}"
    candidates: list[Path] = []
    for p in pdfs:
        stem = p.stem.strip()
        try:
            if int(stem) == month:
                candidates.append(p)
        except ValueError:
            continue
    if len(candidates) == 1:
        return candidates[0], pdfs
    return None, pdfs


def resolve_facility(
    facility_name: str, routing: dict[str, str]
) -> str | None:
    """居宅名 → FAX 事業所フォルダ名 を引く。MVP では完全一致のみ。"""
    if facility_name in routing:
        return routing[facility_name]
    return None


def plan_b_placement(
    rows: list[ChecklistRow],
    cfg: ChecklistConfig,
    month: int,
) -> list[PlacementResult]:
    """各行ごとに「どの PDF をどこに置くか」を計画する（実コピーはしない）。

    実行可能 (SUCCESS pending) / 各種スキップ理由 / 手動選択待ち を区別して返す。
    """
    karte_root = Path(cfg.karte_root)
    fax_root = Path(cfg.fax_root)
    results: list[PlacementResult] = []
    for row in rows:
        result = PlacementResult(row=row)
        fax_folder = resolve_facility(row.facility, cfg.facility_routing)
        if not fax_folder:
            result.status = PlacementStatus.SKIPPED_NO_FACILITY
            result.message = f"居宅マッピング未登録: {row.facility}"
            results.append(result)
            continue

        user_dir, user_candidates = find_user_dir(karte_root, row.name)
        if user_dir is None:
            if len(user_candidates) >= 2:
                result.status = PlacementStatus.SKIPPED_AMBIGUOUS
                result.candidates = user_candidates
                result.message = f"同姓同名候補 {len(user_candidates)} 件"
            else:
                result.status = PlacementStatus.SKIPPED_NO_USER_DIR
                result.message = f"利用者フォルダ未発見: {row.name}"
            results.append(result)
            continue

        monitoring_dir, monitoring_candidates = find_monitoring_dir(
            user_dir, cfg.monitoring_subfolder
        )
        if monitoring_dir is None:
            if len(monitoring_candidates) >= 2:
                # 派生フォルダ同居等で複数 HIT → 誤配置 0 のため人間判断 (a 案)
                result.status = PlacementStatus.SKIPPED_AMBIGUOUS
                result.candidates = monitoring_candidates
                result.message = (
                    f"モニタリングフォルダ候補 {len(monitoring_candidates)} 件 "
                    f"(設定: {cfg.monitoring_subfolder})"
                )
            else:
                result.status = PlacementStatus.SKIPPED_NO_PDF
                result.message = (
                    f"モニタリングフォルダ未発見 (設定: {cfg.monitoring_subfolder})"
                )
            results.append(result)
            continue

        month_pdf, all_pdfs = find_month_pdf(monitoring_dir, month)
        if month_pdf is None:
            if all_pdfs:
                result.status = PlacementStatus.SKIPPED_AMBIGUOUS
                result.candidates = all_pdfs
                result.message = f"{month}.pdf 不在、候補 {len(all_pdfs)} 件"
            else:
                result.status = PlacementStatus.SKIPPED_NO_PDF
                result.message = f"PDF 不在: {monitoring_dir}"
            results.append(result)
            continue

        target = fax_root / fax_folder / cfg.b_output_subfolder / f"{row.name}.pdf"
        result.source_pdf = month_pdf
        result.target_pdf = target
        result.status = PlacementStatus.PENDING
        results.append(result)
    return results


def execute_placement(results: list[PlacementResult]) -> list[PlacementResult]:
    """PENDING 状態の plan を実コピーする。既存ファイルは上書き。"""
    for r in results:
        if r.status != PlacementStatus.PENDING:
            continue
        if r.source_pdf is None or r.target_pdf is None:
            r.status = PlacementStatus.ERROR
            r.message = "internal: missing source/target"
            continue
        try:
            r.target_pdf.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(r.source_pdf, r.target_pdf)
            r.status = PlacementStatus.SUCCESS
        except OSError as exc:
            r.status = PlacementStatus.ERROR
            r.message = f"copy failed: {exc.__class__.__name__}"
            logger.exception("Copy failed for %s", r.row.name)
    return results
