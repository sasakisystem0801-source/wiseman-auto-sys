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
from typing import Final

from wiseman_hub.cloud.sheets import ChecklistRow
from wiseman_hub.config import ChecklistConfig
from wiseman_hub.pdf.year_folder import parse_year_folder_name
from wiseman_hub.utils.text_norm import normalize_lookup_key

logger = logging.getLogger(__name__)


class PlacementStatus(StrEnum):
    """1 行ごとの配置結果。"""

    PENDING = "pending"
    SUCCESS = "success"
    SKIPPED_NO_FACILITY = "skipped_no_facility"  # 居宅マッピング未登録
    SKIPPED_NO_USER_DIR = "skipped_no_user_dir"  # 利用者フォルダ未発見
    SKIPPED_NO_MONITORING_DIR = "skipped_no_monitoring_dir"  # モニタリングフォルダ未発見 (Issue #monitoring-substring)
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
    """氏名比較用の正規化 (PR-γ v2: text_norm に統合)。

    PR-γ v2 まで: ``name.replace("　", "").replace(" ", "").strip()`` で **NFKC 欠落**。
    全角→半角統一が効かず、``姫路医療生活協同組合 あぼし`` (半角) と
    ``姫路医療生活協同組合　あぼし`` (全角) が個別正規化後も別文字列として残るバグ。
    PR-γ v2 で ``normalize_lookup_key`` に統合 (NFKC + 全空白除去)。
    """
    return normalize_lookup_key(name)


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


# canonical_name の最低長 (Review SF6): 短すぎる設定値は全 dir に誤一致するため
# 防御。3 文字以上を要求 (例: 「運動器」= 3 文字、「計画」= 2 文字 → reject)。
_MIN_CANONICAL_LEN: Final[int] = 3


def find_monitoring_dir(
    user_dir: Path, canonical_name: str
) -> tuple[Path | None, list[Path]]:
    """利用者フォルダ配下から ``canonical_name`` を含むサブディレクトリを探す。

    Issue #monitoring-substring (2026-05-09): 業務上モニタリングフォルダ名が
    ``08.運動器機能向上計画書`` / ``10.運動器機能向上計画書`` / prefix なし /
    ``運動器機能向上計画書(過去分)`` 等で揺らぐため、設定値を canonical name のみ
    (= ``運動器機能向上計画書``) にし、substring match で全パターンを拾う。

    比較は ``_normalize_name`` (全角/半角スペース除去) 経由で揺れ吸収を一貫化
    (find_user_dir パターンと対称、Review CR2)。

    Args:
        user_dir: 利用者ルートディレクトリ
        canonical_name: 設定値 (例: ``運動器機能向上計画書``)。``_MIN_CANONICAL_LEN``
            未満の場合は誤一致防御のため ``(None, [])`` を返す + ``logger.error``。

    Returns:
        (matched_dir, candidates):
            matched_dir: 一意に決まれば Path、それ以外 (0 件 or 複数) None
            candidates: substring match した全候補ディレクトリ (sort 順、UI 表示用)

    Notes:
        ``user_dir.iterdir()`` の OSError (NAS 切断 / 権限 / TOCTOU 等) は捕捉して
        ``(None, [])`` を返す (Review C1)。バッチ全体クラッシュを防ぎ、当該行のみ
        ``SKIPPED_NO_MONITORING_DIR`` で人間判断に倒す。PII 防御のため log には
        path 値を出さず例外型のみ記録する (Review C2)。
    """
    # Review SF6: 短すぎる canonical name は全 dir 誤一致リスク → 防御
    normalized_canonical = _normalize_name(canonical_name)
    if len(normalized_canonical) < _MIN_CANONICAL_LEN:
        logger.error(
            "find_monitoring_dir: canonical_name too short "
            "(len=%d, required>=%d), refusing to match all dirs",
            len(normalized_canonical),
            _MIN_CANONICAL_LEN,
        )
        return None, []

    if not user_dir.exists():
        return None, []

    # Review C1: NAS 切断 / 権限エラー時のバッチ全体クラッシュを防ぐ
    try:
        children = list(user_dir.iterdir())
    except OSError as e:
        # Review C2: PII 防御で path を log に出さない (型名のみ)
        logger.warning(
            "find_monitoring_dir: iterdir failed (%s, possible NAS disconnect)",
            type(e).__name__,
        )
        return None, []

    # Review CR2: _normalize_name 適用で全角スペース等の揺れも吸収
    matches = sorted(
        d
        for d in children
        if d.is_dir() and normalized_canonical in _normalize_name(d.name)
    )
    if len(matches) == 1:
        return matches[0], matches
    return None, matches


def _parse_year_folder_name(name: str) -> int | None:
    """[deprecated] フォルダ名から R<年> の年数値を抽出。

    PR-R<年>-C: ``pdf/year_folder.parse_year_folder_name`` に統合。
    後方互換のため本関数名は維持し、内部実装を共通モジュールに委譲する。
    """
    return parse_year_folder_name(name)


def _match_month_pdf_in_dir(
    directory: Path, month: int
) -> tuple[Path | None, list[Path], bool]:
    """指定ディレクトリ直下の ``{month}.pdf`` を 1 件返す (再帰なし)。

    戻り値 3-tuple ``(found, pdfs, ambiguous)``:
        - ``(Path, [...], False)``: 月マッチ単独で確定
        - ``(None, [...], True)``: 月マッチ複数 → AMBIGUOUS (呼出側で早期 return 必須)
        - ``(None, [...], False)``: PDF はあるが月マッチなし
        - ``(None, [], False)``: PDF ゼロ or ``iterdir`` 失敗 (OSError は warn ログのみ、
          PII 防御で path は出さない)

    Issue #282 codex review High-3 反映: ``iterdir`` の OSError (NAS 切断 / SMB
    permission denied / TOCTOU) を捕捉して空結果に倒す。``find_monitoring_dir`` の
    エラー方針と整合。
    """
    try:
        pdfs = sorted(
            p for p in directory.iterdir() if p.suffix.lower() == ".pdf"
        )
    except OSError as exc:
        # PII 防御: directory 絶対パスはログに出さず、型名のみ。
        logger.warning(
            "_match_month_pdf_in_dir: iterdir failed (%s)",
            type(exc).__name__,
        )
        return None, [], False
    if not pdfs:
        return None, [], False
    candidates: list[Path] = []
    for p in pdfs:
        stem = p.stem.strip()
        try:
            if int(stem) == month:
                candidates.append(p)
        except ValueError:
            continue
    if len(candidates) == 1:
        return candidates[0], pdfs, False
    if len(candidates) >= 2:
        # Issue #282 codex review High-1 反映: AMBIGUOUS を識別フラグで返し、
        # find_month_pdf 側で年フォルダ走査をスキップさせる (誤確定防止)。
        return None, pdfs, True
    return None, pdfs, False


def find_month_pdf(monitoring_dir: Path, month: int) -> tuple[Path | None, list[Path]]:
    """``{month}.pdf`` を ``monitoring_dir`` 直下 + ``R<年>`` サブフォルダから探索。

    Issue #282: 本田様 PC の運用で ``{monitoring_subfolder}/R7/<月>.pdf`` 構造
    (令和 7 年サブフォルダ) が混在することが判明。直下のみ走査だと配置漏れになる
    ため、以下の優先順で探索する:

        1. ``monitoring_dir/<月>.pdf`` (旧構造、直配置) — 既存挙動を優先
        2. ``monitoring_dir/R<年>/<月>.pdf`` (新構造) — R 数字降順で最新年から走査
        3. それでもなければ ``None``

    R<年> フォルダ名の表記揺れ (R7 / R７ / Ｒ7 / R 7 / R.7 / r7 等) は
    ``_parse_year_folder_name`` で NFKC 正規化 + 正規表現マッチで吸収。

    codex review (#282) 反映:
        - High-1: 直下 AMBIGUOUS で年フォルダ走査に進むと誤確定 → 直下 AMBIGUOUS は
          早期 return で「人間判断に倒す」(既存契約 ``SKIPPED_AMBIGUOUS`` 維持)
        - High-2: 年フォルダ内 AMBIGUOUS で古い年にフォールバックすると誤確定 →
          年フォルダ内 AMBIGUOUS でも早期 return
        - Medium-1: 同一論理年で複数フォルダ (例: ``R7`` と ``Ｒ７`` が混在) は ``iterdir``
          順に依存して非決定的 → 同一論理年で複数物理フォルダを発見した時点で AMBIGUOUS

    Returns:
        ``(月 PDF 1 件 or None, 走査した全 .pdf リスト)``。``None`` の場合は呼出側
        が ``SKIPPED_NO_PDF`` (候補ゼロ) と ``SKIPPED_AMBIGUOUS`` (候補複数) を
        list 長で判別する既存契約を維持。
    """
    if not monitoring_dir.exists():
        return None, []

    # step 1: 直配置 (旧構造、既存挙動維持)
    found, direct_pdfs, direct_ambiguous = _match_month_pdf_in_dir(
        monitoring_dir, month
    )
    if found is not None:
        return found, direct_pdfs
    if direct_ambiguous:
        # codex review High-1: 直下 AMBIGUOUS は年フォルダ探索で誤確定させない。
        return None, direct_pdfs

    # step 2: R<年> サブフォルダ最新優先 (新構造、表記揺れ吸収)
    # 同一論理年で複数物理フォルダがある場合は AMBIGUOUS 扱い (codex Medium-1)。
    year_groups: dict[int, list[Path]] = {}
    try:
        children = list(monitoring_dir.iterdir())
    except OSError as exc:
        # codex High-3: monitoring_dir 自体の iterdir 失敗 (NAS 切断等) も graceful に。
        logger.warning(
            "find_month_pdf: iterdir failed on monitoring_dir (%s)",
            type(exc).__name__,
        )
        return None, list(direct_pdfs)
    for d in children:
        if not d.is_dir():
            continue
        year = parse_year_folder_name(d.name)
        if year is not None:
            year_groups.setdefault(year, []).append(d)

    aggregated_pdfs: list[Path] = list(direct_pdfs)
    # 最新年から降順走査。
    for year in sorted(year_groups.keys(), reverse=True):
        dirs_for_year = year_groups[year]
        if len(dirs_for_year) >= 2:
            # codex Medium-1: 同一論理年で表記揺れフォルダが複数 → 非決定的、AMBIGUOUS。
            # 全フォルダ内の pdf を候補として集約してから人間判断に倒す。
            for d in dirs_for_year:
                _, pdfs_in_dir, _ = _match_month_pdf_in_dir(d, month)
                aggregated_pdfs.extend(pdfs_in_dir)
            return None, aggregated_pdfs
        year_dir = dirs_for_year[0]
        found, year_pdfs, year_ambiguous = _match_month_pdf_in_dir(year_dir, month)
        aggregated_pdfs.extend(year_pdfs)
        if found is not None:
            return found, aggregated_pdfs
        if year_ambiguous:
            # codex review High-2: 当該年で AMBIGUOUS なら古い年で誤確定しない。
            return None, aggregated_pdfs

    # step 3: 該当なし
    return None, aggregated_pdfs


def resolve_facility(
    facility_name: str, routing: dict[str, str]
) -> str | None:
    """居宅名 → FAX 事業所フォルダ名 を引く。

    PR-γ v2 (Session 78 実機デモ後): C 側 (``checklist_c.resolve_facility``) と
    挙動を揃えて lookup 前に ``normalize_lookup_key`` を通す。``routing`` 側は
    ``config.py:_load_checklist`` で読込時に正規化済 (line 1179) のため、
    検索側でも同じ正規化を通さないと表記揺れで lookup が失敗する。

    実機デモで判明した直接原因: スプレッドシートに ``姫路医療生活協同組合 あぼし``
    (全角空白) が入っていたが、``routing`` の key は ``姫路医療生活協同組合あぼし``
    (空白除去後) だったため、生 facility_name での lookup が miss していた。
    """
    return routing.get(normalize_lookup_key(facility_name))


def plan_b_placement(
    rows: list[ChecklistRow],
    cfg: ChecklistConfig,
    month: int,
) -> list[PlacementResult]:
    """各行ごとに「どの PDF をどこに置くか」を計画する（実コピーはしない）。

    実行可能 (SUCCESS pending) / 各種スキップ理由 / 手動選択待ち を区別して返す。
    """
    # Issue #27 続編 G Phase 3a: ChecklistConfig.karte_root / fax_root は Path 型に移行済。
    # 重複ラップ (Path(Path)) 除去、Phase 2a/2b consumer 整合パターン踏襲。
    karte_root = cfg.karte_root
    fax_root = cfg.fax_root
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
                # Review code-reviewer Imp 1: 集計時に SKIPPED_NO_PDF と区別できるよう
                # AMBIGUOUS は専用 status を使用 (= 既存規約通り)。
                result.status = PlacementStatus.SKIPPED_AMBIGUOUS
                result.candidates = monitoring_candidates
                result.message = (
                    f"モニタリングフォルダ候補 {len(monitoring_candidates)} 件 "
                    f"(設定: {cfg.monitoring_subfolder})"
                )
            else:
                # Review CR1: モニタリングフォルダ自体が無いケースに SKIPPED_NO_PDF
                # (= 月別 PDF 不在) を流用すると業務文脈で識別不能 →
                # 専用 SKIPPED_NO_MONITORING_DIR を使用 (find_user_dir 不在の
                # SKIPPED_NO_USER_DIR と対称)。
                result.status = PlacementStatus.SKIPPED_NO_MONITORING_DIR
                result.message = (
                    f"モニタリングフォルダ未発見 — 利用者フォルダ配下に "
                    f"'{cfg.monitoring_subfolder}' を含むサブフォルダがありません"
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
