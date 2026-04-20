"""PDF 分割・条件付き再結合パイプラインのオーケストレータ（Phase A）。

Phase A: split → ページ永続化 → OCR → matcher → candidate 追加 → 遷移判定

設計の根拠:
- ADR-008: OCR バックエンド
- ADR-010: 状態遷移図（本モジュールが実装する遷移の source of truth）

Phase B（merger 実行）は本モジュールの範囲外。

設計判断:
1. OCR `confidence=low` は matcher 結果に関係なく `NEEDS_CONFIRMATION` に昇格する
   （医療情報の誤字誘発事故を防ぐため）
2. OCR `name=None`（読取不能）は matcher を呼ばず `NO_MATCH` 扱い
3. 重複 `user_name` はページ順を保持したまま個別 candidate として扱う（dedupe しない）
4. Resume 時は source_a を再 split（PyMuPDF の split は高速、OCR が重い部分）
   し、処理済み `page_index` をスキップする。これにより `a_page_pdf_bytes` の
   バイナリを後から読み戻す必要がなくなる
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from wiseman_hub.config import PdfMergeConfig
from wiseman_hub.pdf.matcher import NameMatcher
from wiseman_hub.pdf.ocr_client import ExtractNameResult
from wiseman_hub.pdf.session import (
    PairStatus,
    Session,
    SessionNotFoundError,
    SessionStatus,
    UserCandidate,
    ensure_private_dir,
    generate_session_id,
    load_session,
    save_session,
    transition_session,
    with_session_lock,
)
from wiseman_hub.pdf.splitter import SplitPage, split_pdf_with_bbox

logger = logging.getLogger(__name__)


class OcrClientLike(Protocol):
    def extract_name(
        self, image_png: bytes, *, include_raw_text: bool = False
    ) -> ExtractNameResult:
        ...


_RESUMABLE_STATUSES = frozenset(
    {SessionStatus.RUNNING_PHASE_A, SessionStatus.INTERRUPTED_PHASE_A}
)


def _config_snapshot(config: PdfMergeConfig) -> dict[str, Any]:
    """dataclass を JSON 互換の dict に変換する（session JSON に埋め込む用）。"""
    return asdict(config)


# config_snapshot に追加して resume 時の source A 同一性を検証する。
# SHA-256 は改ざん検知、size/mtime は差し替え高速検知、page_count は splitter 変更検知用。
_SOURCE_A_FINGERPRINT_KEY = "source_a_fingerprint"


def _compute_source_a_fingerprint(source_a_path: Path) -> dict[str, Any]:
    """source A PDF の改ざん・差し替え検知用フィンガープリント。

    SHA-256 は content の同一性、size/mtime は高速スクリーニング用。
    """
    stat = source_a_path.stat()
    h = hashlib.sha256()
    with open(source_a_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return {
        "sha256": h.hexdigest(),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _verify_source_a_fingerprint(
    session: Session, source_a_path: Path
) -> None:
    """resume 時に source A が差し替えられていないか検証する。

    初回の Phase A では `source_a_fingerprint` を `config_snapshot` に保存する。
    resume 時に現在の source A から同じフィンガープリントを算出し、不一致なら
    利用者取り違え事故を避けるため `SourceAFingerprintMismatchError` を上げる。
    """
    recorded = session.config_snapshot.get(_SOURCE_A_FINGERPRINT_KEY)
    if recorded is None:
        # 古いセッション（フィンガープリント導入前）は検証をスキップ
        logger.warning(
            "session %s has no source_a_fingerprint (pre-feature session); "
            "skipping integrity check",
            session.session_id,
        )
        return

    current = _compute_source_a_fingerprint(source_a_path)
    mismatch_fields = [k for k in ("sha256", "size") if recorded.get(k) != current.get(k)]
    if mismatch_fields:
        raise SourceAFingerprintMismatchError(
            f"source A has changed since session {session.session_id} was created "
            f"(differs in: {mismatch_fields}). "
            f"Refusing to resume to avoid user mix-up. "
            f"Either restore the original file or discard this session "
            f"(--discard {session.session_id}) and start a new one."
        )


class SourceAFingerprintMismatchError(ValueError):
    """resume 時、source A PDF が初回実行時と異なる（改ざん・差し替え）。"""


def _prepare_page_dir(session: Session) -> Path:
    """セッションの artifact ディレクトリを作成する（POSIX では 0o700）。"""
    page_dir = Path(session.a_page_pdf_bytes_dir)
    ensure_private_dir(page_dir)
    return page_dir


def _new_session(
    *,
    source_a_path: Path,
    config: PdfMergeConfig,
    sessions_dir: Path,
) -> Session:
    sid = generate_session_id()
    now = datetime.now(UTC).isoformat()
    page_dir = sessions_dir / f"{sid}-pages"
    snapshot = _config_snapshot(config)
    snapshot[_SOURCE_A_FINGERPRINT_KEY] = _compute_source_a_fingerprint(source_a_path)
    return Session(
        session_id=sid,
        status=SessionStatus.RUNNING_PHASE_A,
        created_at=now,
        updated_at=now,
        config_snapshot=snapshot,
        source_a_path=str(source_a_path),
        candidates=[],
        a_page_pdf_bytes_dir=str(page_dir),
        output_path=None,
        total_pages_a=None,
    )


def _build_candidate(
    *,
    page_index: int,
    ocr_result: ExtractNameResult,
    matcher: NameMatcher,
) -> UserCandidate:
    """OCR 結果から UserCandidate を構築する。

    - OCR name=None → NO_MATCH（matcher を呼ばない）
    - OCR confidence=low → NEEDS_CONFIRMATION に昇格（matcher が auto_matched を返しても）
    """
    if ocr_result.name is None:
        return UserCandidate(
            page_index=page_index,
            user_name_ocr="",
            confidence=ocr_result.confidence,
            status=PairStatus.NO_MATCH,
            matched_b_path=None,
            matched_c_path=None,
            similar_candidates=[],
        )

    match_result = matcher.match(ocr_result.name)
    candidate = UserCandidate.from_match_result(
        page_index=page_index,
        user_name_ocr=ocr_result.name,
        confidence=ocr_result.confidence,
        match_result=match_result,
    )

    if ocr_result.confidence == "low" and candidate.status == PairStatus.AUTO_MATCHED:
        # medical 分野では低信頼マッチは人間確認必須。ログには PII（氏名）を残さない。
        logger.info(
            "page %d: low-confidence OCR overrides auto_matched -> needs_confirmation",
            page_index,
        )
        candidate.status = PairStatus.NEEDS_CONFIRMATION

    return candidate


def _save_page_pdf(page_dir: Path, sp: SplitPage) -> None:
    """1 ページ分の PDF バイナリを ``page_NNN.pdf`` として保存する（idempotent）。"""
    path = page_dir / f"page_{sp.page_index:03d}.pdf"
    # write_bytes は atomic ではないが、split 出力を保存する用途で中断しても
    # 次回の再 split で上書きされるため問題なし。
    path.write_bytes(sp.page_pdf_bytes)


def _finalize_status(session: Session) -> SessionStatus:
    """全ページ処理後の最終状態を決定する。"""
    return (
        SessionStatus.READY_TO_MERGE
        if session.all_candidates_resolved
        else SessionStatus.NEEDS_REVIEW
    )


def run_phase_a(
    *,
    source_a_path: Path,
    config: PdfMergeConfig,
    ocr_client: OcrClientLike,
    matcher: NameMatcher,
    sessions_dir: Path,
    session: Session | None = None,
) -> Session:
    """Phase A（split → OCR → match）を実行し、永続化済み Session を返す。

    Args:
        source_a_path: 複数利用者がまとまった A PDF
        config: PdfMergeConfig（bbox とファイル名パターンを含む）
        ocr_client: OCR クライアント（本物は OcrClient、テストは FakeOcrClient）
        matcher: 名前マッチャ（通常は KanjiMatcher）
        sessions_dir: セッションファイルと artifact ディレクトリの親
        session: 既存セッションから resume する場合のセッション。None なら新規。

    Returns:
        最終状態まで遷移した Session（READY_TO_MERGE / NEEDS_REVIEW）。
        中断時は例外が伝播し、セッションは INTERRUPTED_PHASE_A で保存済み。

    Raises:
        ValueError: resume 対象 session が不適切な状態
        KeyboardInterrupt: 中断時は再送出。session は INTERRUPTED_PHASE_A で保存済み
        その他: OcrServerError 等も session に INTERRUPTED_PHASE_A を記録して再送出
    """
    is_resume = session is not None

    if is_resume:
        assert session is not None
        if session.status not in _RESUMABLE_STATUSES:
            raise ValueError(
                f"cannot resume session {session.session_id} from status "
                f"{session.status.value!r}; expected one of "
                f"{sorted(s.value for s in _RESUMABLE_STATUSES)}"
            )
        # 利用者取り違え防止: source A が差し替えられていたら resume を拒否
        _verify_source_a_fingerprint(session, source_a_path)
    else:
        session = _new_session(
            source_a_path=source_a_path,
            config=config,
            sessions_dir=sessions_dir,
        )

    logger.info(
        "run_phase_a: session=%s source=%s resume=%s",
        session.session_id,
        source_a_path,
        is_resume,
    )

    with with_session_lock(sessions_dir, session.session_id):
        # resume の TOCTOU 対策: lock 取得前に discard されている可能性があるため
        # 再確認する。lock 取得後は他プロセスが触れないので以降はこの session を信頼できる。
        if is_resume:
            try:
                load_session(session.session_id, sessions_dir=sessions_dir)
            except SessionNotFoundError as e:
                raise SessionNotFoundError(
                    f"session {session.session_id} was removed while waiting for "
                    f"lock (likely --discard race); aborting resume."
                ) from e

        # resume の場合、interrupted → running に遷移（失敗時はそのまま残留）
        if session.status == SessionStatus.INTERRUPTED_PHASE_A:
            transition_session(session, SessionStatus.RUNNING_PHASE_A)
        save_session(session, sessions_dir=sessions_dir)

        # split は高速なため resume でも再実行（a_page_pdf_bytes_dir には残骸があり得る）
        pages = split_pdf_with_bbox(source_a_path, config.user_name_bbox)
        session.total_pages_a = len(pages)

        page_dir = _prepare_page_dir(session)

        processed_indexes = {c.page_index for c in session.candidates}

        try:
            for sp in pages:
                if sp.page_index in processed_indexes:
                    continue

                _save_page_pdf(page_dir, sp)

                ocr_result = ocr_client.extract_name(sp.bbox_image_png)
                candidate = _build_candidate(
                    page_index=sp.page_index,
                    ocr_result=ocr_result,
                    matcher=matcher,
                )
                session.candidates.append(candidate)

                # 1 ページ処理完了ごとに永続化（中断耐性）
                save_session(session, sessions_dir=sessions_dir)
        except (Exception, KeyboardInterrupt):
            # Exception 派生（OcrServerError 等）と KeyboardInterrupt を INTERRUPTED 扱い。
            # SystemExit / GeneratorExit は BaseException 直下のため捕捉せず通過させる
            # （プロセス終了を阻害しない）。
            logger.exception(
                "run_phase_a interrupted at page after processed=%d (session=%s)",
                len(session.candidates),
                session.session_id,
            )
            try:
                transition_session(session, SessionStatus.INTERRUPTED_PHASE_A)
                save_session(session, sessions_dir=sessions_dir)
            except Exception:
                logger.exception(
                    "failed to save INTERRUPTED state for session %s",
                    session.session_id,
                )
            raise

        # 全ページ処理完了
        # ページ順を保つためソート（resume で不正挿入があった場合の保険）。
        # save 前に実施してディスクと戻り値の順序を揃える。
        session.candidates.sort(key=lambda c: c.page_index)
        final = _finalize_status(session)
        transition_session(session, final)
        save_session(session, sessions_dir=sessions_dir)
        logger.info(
            "run_phase_a done: session=%s status=%s candidates=%d",
            session.session_id,
            session.status.value,
            len(session.candidates),
        )
        return session
