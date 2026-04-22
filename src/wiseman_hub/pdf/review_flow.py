"""確認 UI → READY_TO_MERGE 遷移の共通フロー（Issue #72）。

CLI (``scripts/merge_user_pdfs.py::_cmd_review``) と GUI
(``__main__._make_review_callback``) で二重実装されていた以下の処理を 1 箇所に集約する:

1. 1 回目のロック取得 → 最新セッション読込 → NEEDS_REVIEW 検証
2. ``ConfirmDialog`` を起動（dialog_factory で注入）
3. ロック解放後 aborted / 未解決残りをチェック
4. 2 回目のロック取得 → fresh reload → race 検出 → READY_TO_MERGE へ遷移

通知（print stderr / messagebox）は本モジュールでは行わず、``ReviewOutcome.reason``
で呼出側（adapter）へ結果を返す。`_cmd_review` は exit code、
`_make_review_callback` は ``ReviewCallbackResult`` に変換する。

設計メモ:
- 2 段階ロック + fresh reload は GUI 側が以前から持っていた race 対策
  （PR #74 Codex HIGH 指摘由来）。CLI も本リファクタで同じ強度になる。
- PII 防御: 例外 message はログ・返却値に含めず、型名のみ ``detail`` に残す。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

from wiseman_hub.pdf.session import (
    InvalidTransitionError,
    Session,
    SessionStatus,
    load_session,
    save_session,
    transition_session,
    with_session_lock,
)

if TYPE_CHECKING:
    from wiseman_hub.ui.confirm_dialog import ConfirmDialogResult

logger = logging.getLogger(__name__)


ReviewReason = Literal[
    "ready_to_merge",
    "resolved",
    "aborted",
    "unresolved",
    "concurrent_modification",
    "lock_error",
    "transition_lock_error",
    "invalid_transition",
    "invalid_status",
]


@dataclass(frozen=True)
class ReviewOutcome:
    """``resolve_review_session`` の結果。

    reason: 分岐を一意に識別する stable なコード（adapter のマッピングに使用）
    session_id: 対象 session（全 reason で有効）
    detail: エラー系で例外型名や不正 status 値を格納（PII を含まない）
    """

    reason: ReviewReason
    session_id: str
    detail: str | None = None


class ConfirmDialogLike(Protocol):
    """``ConfirmDialog`` のテスト差し替え用最小インターフェース。"""

    def run(self) -> ConfirmDialogResult: ...


DialogFactory = Callable[[Session, Path], ConfirmDialogLike]


def resolve_review_session(
    session_id: str,
    sessions_dir: Path,
    *,
    dialog_factory: DialogFactory,
) -> ReviewOutcome:
    """NEEDS_REVIEW セッションの確認 UI 起動 + READY_TO_MERGE 遷移を実行する。

    ロック保持期間（重要）:
    - 1 回目のロックは ``dialog_factory(...).run()`` が return するまで保持される。
      本物の ``ConfirmDialog.run()`` は Tkinter mainloop を内包しユーザー操作完了
      まで block するため、**ロック保持期間 = UI 操作時間**（数分〜数十分）となる。
    - MVP 運用（単一 PC / 1-3 名/batch、ADR-010）では他プロセスが同一 session に
      衝突する想定がないため許容。マルチ端末拡張時は 1st lock 内 UI から
      「lock 外で dialog → 再取得して変更検証」の CAS パターンへ変更する。

    呼出側契約（例外）:
    - ``session_id`` は ``validate_session_id`` 済みであること。
    - 1st lock 内の ``load_session`` が raise する
      ``SessionNotFoundError`` / ``SessionCorruptedError`` は本関数で捕捉せず伝播させる。
      picker 選択後〜1st lock 取得前の race（他プロセスが --discard した等）で発生し得る。
      呼出側 adapter は例外を catch して適切な UI / stderr メッセージへマッピングする。
    - ``dialog_factory(...).run()`` が ``BlockingIOError`` / ``OSError`` 以外の例外
      （``TclError`` 等）を raise した場合、本関数では捕捉せず伝播させる。
      ``with_session_lock`` の ``finally`` によりロックは安全に解放される。

    戻り値マッピング指針:
    - ``ready_to_merge`` / ``resolved``: Phase B 続行可
    - それ以外: Phase B 中止（adapter は CANCEL / EXIT_ERROR 等へマッピング）
    """
    # 1 回目のロック: 最新 session をロードして dialog を起動する。
    # caller の load 後に他プロセスが状態変更している可能性があるため、
    # ロック内で再ロードしてから status を判定する（TOCTOU 防止）。
    try:
        with with_session_lock(sessions_dir, session_id):
            session = load_session(session_id, sessions_dir=sessions_dir)
            if session.status == SessionStatus.READY_TO_MERGE:
                return ReviewOutcome("ready_to_merge", session_id)
            if session.status != SessionStatus.NEEDS_REVIEW:
                logger.warning(
                    "session %s invalid status for review: %s",
                    session_id,
                    session.status.value,
                )
                return ReviewOutcome(
                    "invalid_status", session_id, detail=session.status.value
                )
            dialog = dialog_factory(session, sessions_dir)
            result = dialog.run()
    except (BlockingIOError, OSError) as exc:
        logger.error(
            "session %s lock contention (1st): %s",
            session_id,
            type(exc).__name__,
        )
        return ReviewOutcome("lock_error", session_id, detail=type(exc).__name__)

    if result.aborted:
        # aborted 時はディスク状態が旧状態で一貫。再起動時に再 open_review で再開可能。
        return ReviewOutcome("aborted", session_id)
    if not result.resolved_all:
        # 未解決候補残り。adapter は「再度確認 UI を開いて続行」を誘導する。
        return ReviewOutcome("unresolved", session_id)

    # 2 回目のロック: race safe に READY_TO_MERGE へ遷移する。
    # 1 回目のロック解放後、別プロセスが session を discard / COMPLETED 遷移
    # させる可能性があるため、必ず再ロードし許可された状態のみ遷移する。
    # 許可: (a) NEEDS_REVIEW かつ all_candidates_resolved → READY_TO_MERGE へ
    #       (b) 既に READY_TO_MERGE → 冪等成功（ready_to_merge を返却）
    try:
        with with_session_lock(sessions_dir, session_id):
            fresh = load_session(session_id, sessions_dir=sessions_dir)
            if fresh.status == SessionStatus.READY_TO_MERGE:
                return ReviewOutcome("ready_to_merge", session_id)
            if (
                fresh.status != SessionStatus.NEEDS_REVIEW
                or not fresh.all_candidates_resolved
            ):
                logger.warning(
                    "session %s concurrent modification detected (status=%s): "
                    "abort transition",
                    session_id,
                    fresh.status.value,
                )
                return ReviewOutcome(
                    "concurrent_modification",
                    session_id,
                    detail=fresh.status.value,
                )
            transition_session(fresh, SessionStatus.READY_TO_MERGE)
            save_session(fresh, sessions_dir=sessions_dir)
    except (BlockingIOError, OSError) as exc:
        logger.error(
            "session %s transition save failed: %s",
            session_id,
            type(exc).__name__,
        )
        return ReviewOutcome(
            "transition_lock_error", session_id, detail=type(exc).__name__
        )
    except InvalidTransitionError as exc:
        # fresh.status チェックで弾くはずだが、状態機械の race 最終安全網。
        logger.warning(
            "session %s invalid transition: %s",
            session_id,
            type(exc).__name__,
        )
        return ReviewOutcome(
            "invalid_transition", session_id, detail=type(exc).__name__
        )

    return ReviewOutcome("resolved", session_id)
