"""PDF 分割・条件付き再結合パイプラインの CLI（Phase A、Issue #36）。

使い方:
    # 新規実行（config/default.toml を使用、A.pdf は pdf_merge.input_dir 配下）
    python scripts/merge_user_pdfs.py

    # 特定の config を使用
    python scripts/merge_user_pdfs.py --config config/prod.toml

    # 既存セッション一覧表示
    python scripts/merge_user_pdfs.py --list-sessions

    # INTERRUPTED セッションの再開
    python scripts/merge_user_pdfs.py --resume <session_id>

    # 不要セッションの破棄（JSON + artifact ディレクトリ削除）
    python scripts/merge_user_pdfs.py --discard <session_id>

本 CLI は Phase A（split → OCR → match）までを担当する。Phase B（merger 実行）と
確認 UI は別モジュール（scripts/review_ui.py など）として後続で実装される。

依存性注入: `main()` は config_loader / ocr_factory / matcher_factory を受け、
テストではモック実装を差し込む。

終了コード:
    0: 成功（READY_TO_MERGE 到達、list-sessions、discard 成功を含む）
    1: 一般的エラー（config 不備、source_a 不在、OCR 失敗、ロック競合）
    2: argparse が引数エラーと判定した場合（自動割当）
    3: Phase A 完了したが NEEDS_REVIEW（人間確認必要 → UI タスクで解消）
    130: KeyboardInterrupt（POSIX 慣例の 128 + SIGINT 2）
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import sys
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol, cast

from wiseman_hub.config import (
    AppConfig,
    OcrBackendConfig,
    PdfMergeConfig,
    load_config,
)
from wiseman_hub.pdf.matcher import KanjiMatcher, NameMatcher
from wiseman_hub.pdf.ocr_client import OcrClient
from wiseman_hub.pdf.pipeline import OcrClientLike, run_phase_a
from wiseman_hub.pdf.session import (
    Session,
    SessionCorruptedError,
    SessionError,
    SessionNotFoundError,
    SessionStatus,
    list_sessions,
    load_session,
    remove_session_artifacts,
    validate_session_id,
    with_session_lock,
)

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NEEDS_REVIEW = 3
EXIT_KEYBOARD_INTERRUPT = 130


# ---------------------------------------------------------------------------
# Factory defaults（テストで差し替え可能）
# ---------------------------------------------------------------------------


class _MatcherFactory(Protocol):
    def __call__(self, config: PdfMergeConfig) -> NameMatcher:
        ...


class _OcrFactory(Protocol):
    def __call__(self, config: OcrBackendConfig) -> OcrClientLike:
        ...


def _default_ocr_factory(config: OcrBackendConfig) -> OcrClientLike:
    return OcrClient(config)


def _default_matcher_factory(config: PdfMergeConfig) -> NameMatcher:
    return KanjiMatcher(
        input_dir=Path(config.input_dir),
        source_b_pattern=config.source_b_pattern,
        source_c_pattern=config.source_c_pattern,
    )


# ---------------------------------------------------------------------------
# セッションディレクトリ解決
# ---------------------------------------------------------------------------


def _resolve_sessions_dir(config: AppConfig) -> Path:
    """設定の pdf_merge.output_dir 配下に ``.sessions/`` を配置する。

    output_dir が空の場合はカレントディレクトリ配下にフォールバック（開発時用）。
    """
    if config.pdf_merge.output_dir:
        return Path(config.pdf_merge.output_dir) / ".sessions"
    return Path.cwd() / ".sessions"


def _resolve_source_a(config: AppConfig) -> Path:
    return Path(config.pdf_merge.input_dir) / config.pdf_merge.source_a_filename


# ---------------------------------------------------------------------------
# 各サブコマンド
# ---------------------------------------------------------------------------


def _cmd_list_sessions(sessions_dir: Path) -> int:
    sids = list_sessions(sessions_dir=sessions_dir)
    if not sids:
        print("(no sessions)")
        return EXIT_OK
    for sid in sids:
        try:
            s = load_session(sid, sessions_dir=sessions_dir)
            print(f"{sid}\t{s.status.value}\tcandidates={len(s.candidates)}")
        except Exception as e:
            # 破損セッションもスキップせず表示（手動対処を促す）
            print(f"{sid}\t<corrupted: {type(e).__name__}>")
    return EXIT_OK


def _cmd_discard(sessions_dir: Path, session_id: str) -> int:
    try:
        validate_session_id(session_id)
    except ValueError as e:
        print(f"error: invalid session_id: {e}", file=sys.stderr)
        return EXIT_ERROR

    session_path = sessions_dir / f"{session_id}.json"
    if not session_path.exists():
        print(f"error: session not found: {session_id}", file=sys.stderr)
        return EXIT_ERROR

    # ADR-010: resume / Phase A 実行中との競合を防ぐため discard もロックを取得する。
    artifact_hint: str | None = None
    try:
        with with_session_lock(sessions_dir, session_id):
            # artifact を先に削除（session JSON から artifact パスを読み取るため）
            try:
                s = load_session(session_id, sessions_dir=sessions_dir)
                remove_session_artifacts(s, sessions_dir)
            except SessionCorruptedError as e:
                # 破損 JSON でも JSON 削除は続行するが、artifact パスは読めないため
                # 運用者に手動確認を促す（PII 残留防止）。
                logger.warning(
                    "session %s is corrupted; deleting JSON only: %s", session_id, e
                )
                artifact_hint = str(sessions_dir / f"{session_id}-pages")
            except (OSError, SessionError) as e:
                # Permission denied / NFS エラー / artifact が sessions_dir 外等は
                # fail-hard（黙って JSON 削除すると artifact が孤児化する）。
                print(
                    f"error: could not cleanup artifacts for {session_id}: {e}. "
                    f"JSON left intact for safety.",
                    file=sys.stderr,
                )
                return EXIT_ERROR
            session_path.unlink()
    except (BlockingIOError, OSError) as e:
        print(
            f"error: session {session_id} is locked by another process "
            f"(phase A or UI?): {e}",
            file=sys.stderr,
        )
        return EXIT_ERROR

    print(f"discarded session: {session_id}")
    if artifact_hint is not None:
        print(
            f"note: session JSON was corrupted; check {artifact_hint} "
            f"manually for residual PII.",
            file=sys.stderr,
        )
    return EXIT_OK


def _cmd_run(
    *,
    source_a_path: Path,
    config: AppConfig,
    sessions_dir: Path,
    ocr_factory: _OcrFactory,
    matcher_factory: _MatcherFactory,
) -> int:
    if not source_a_path.exists():
        print(
            f"error: source A PDF not found: {source_a_path}",
            file=sys.stderr,
        )
        return EXIT_ERROR

    return _run_phase_a_with_factories(
        source_a_path=source_a_path,
        config=config,
        sessions_dir=sessions_dir,
        ocr_factory=ocr_factory,
        matcher_factory=matcher_factory,
        existing_session=None,
    )


def _cmd_resume(
    *,
    config: AppConfig,
    sessions_dir: Path,
    session_id: str,
    ocr_factory: _OcrFactory,
    matcher_factory: _MatcherFactory,
) -> int:
    try:
        validate_session_id(session_id)
    except ValueError as e:
        print(f"error: invalid session_id: {e}", file=sys.stderr)
        return EXIT_ERROR

    try:
        session = load_session(session_id, sessions_dir=sessions_dir)
    except SessionNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_ERROR

    # source_a_path は session から取得（config が変わっていても初回時のものを尊重）
    source_a_path = Path(session.source_a_path)
    if not source_a_path.exists():
        print(
            f"error: source A PDF recorded in session no longer exists: "
            f"{source_a_path}",
            file=sys.stderr,
        )
        return EXIT_ERROR

    return _run_phase_a_with_factories(
        source_a_path=source_a_path,
        config=config,
        sessions_dir=sessions_dir,
        ocr_factory=ocr_factory,
        matcher_factory=matcher_factory,
        existing_session=session,
    )


def _run_phase_a_with_factories(
    *,
    source_a_path: Path,
    config: AppConfig,
    sessions_dir: Path,
    ocr_factory: _OcrFactory,
    matcher_factory: _MatcherFactory,
    existing_session: Session | None = None,
) -> int:
    ocr_client = ocr_factory(config.ocr_backend)
    matcher = matcher_factory(config.pdf_merge)

    # 本番 OcrClient は __enter__/__exit__ を実装するが、OcrClientLike Protocol は
    # それを要求しない。ランタイムで有無を確認し、実装していれば cast してスタックへ。
    with contextlib.ExitStack() as stack:
        if hasattr(ocr_client, "__exit__"):
            stack.enter_context(cast(AbstractContextManager[object], ocr_client))
        try:
            session = run_phase_a(
                source_a_path=source_a_path,
                config=config.pdf_merge,
                ocr_client=ocr_client,
                matcher=matcher,
                sessions_dir=sessions_dir,
                session=existing_session,
            )
        except KeyboardInterrupt:
            print("interrupted by user (SIGINT)", file=sys.stderr)
            return EXIT_KEYBOARD_INTERRUPT
        except Exception as e:
            logger.exception("run_phase_a failed")
            print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
            return EXIT_ERROR

        print(
            f"session {session.session_id}: status={session.status.value} "
            f"candidates={len(session.candidates)}"
        )

        if session.status == SessionStatus.NEEDS_REVIEW:
            print(
                "some candidates need human confirmation. "
                "run the review UI (task 8C) to resolve them before merging.",
                file=sys.stderr,
            )
            return EXIT_NEEDS_REVIEW
        return EXIT_OK


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="merge_user_pdfs",
        description=(
            "PDF split → OCR → match pipeline (Phase A). "
            "Run Phase B via the Tkinter review UI (task 8C)."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/default.toml"),
        help="TOML config path (default: config/default.toml)",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--list-sessions",
        action="store_true",
        help="list existing sessions under pdf_merge.output_dir/.sessions",
    )
    group.add_argument(
        "--resume",
        metavar="SESSION_ID",
        help="resume an interrupted Phase A session",
    )
    group.add_argument(
        "--discard",
        metavar="SESSION_ID",
        help="delete a session JSON and its artifact directory",
    )
    return parser


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main(
    argv: list[str] | None = None,
    *,
    config_loader: Callable[[Path], AppConfig] = load_config,
    ocr_factory: _OcrFactory = _default_ocr_factory,
    matcher_factory: _MatcherFactory = _default_matcher_factory,
) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s:%(lineno)d %(message)s",
    )

    parser = _build_parser()
    args = parser.parse_args(argv)

    config = config_loader(args.config)
    sessions_dir = _resolve_sessions_dir(config)

    if args.list_sessions:
        return _cmd_list_sessions(sessions_dir)
    if args.discard is not None:
        return _cmd_discard(sessions_dir, args.discard)
    if args.resume is not None:
        return _cmd_resume(
            config=config,
            sessions_dir=sessions_dir,
            session_id=args.resume,
            ocr_factory=ocr_factory,
            matcher_factory=matcher_factory,
        )

    source_a_path = _resolve_source_a(config)
    return _cmd_run(
        source_a_path=source_a_path,
        config=config,
        sessions_dir=sessions_dir,
        ocr_factory=ocr_factory,
        matcher_factory=matcher_factory,
    )


if __name__ == "__main__":
    sys.exit(main())
