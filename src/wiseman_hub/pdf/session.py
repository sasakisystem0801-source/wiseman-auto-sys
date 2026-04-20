"""PDF 分割・再結合パイプラインのセッション永続化（ADR-010）。

- 1 回の実行 = 1 セッション
- `<sessions_dir>/<session_id>.json` に保存
- アトミック書込: tempfile + os.replace（Windows セーフ）
- GC: 30 日経過の completed セッションは自動削除
- schema_version 付与で将来の後方互換性確保

本モジュールは状態遷移の判定は行わない（値オブジェクト + IO のみ）。
遷移判定は pipeline.py 側で実装する。
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from wiseman_hub.pdf.matcher import MatchResult, MatchStatus, SourceKind
from wiseman_hub.pdf.ocr_client import Confidence

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# session_id は内部生成（generate_session_id）の値のみ受け入れる。
# merger 側の _FORBIDDEN_NAME_CHARS とは対象が異なるため別ルール（分離は意図的）。
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class SessionError(Exception):
    """セッション関連の失敗を表す基底例外。"""


class SessionNotFoundError(SessionError):
    """指定 session_id が存在しない。"""


class SessionCorruptedError(SessionError):
    """JSON 破損・schema version 不一致・必須フィールド欠落。"""


class SessionStatus(StrEnum):
    RUNNING_PHASE_A = "running_phase_a"
    NEEDS_REVIEW = "needs_review"
    READY_TO_MERGE = "ready_to_merge"
    RUNNING_PHASE_B = "running_phase_b"
    COMPLETED = "completed"
    INTERRUPTED_PHASE_A = "interrupted_phase_a"
    INTERRUPTED_PHASE_B = "interrupted_phase_b"


class PairStatus(StrEnum):
    AUTO_MATCHED = "auto_matched"
    NEEDS_CONFIRMATION = "needs_confirmation"
    NO_MATCH = "no_match"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    MANUALLY_SELECTED = "manually_selected"
    SKIPPED = "skipped"


# ペアが「解決済み」と判定される状態集合（すべて解決 → SessionStatus.READY_TO_MERGE へ遷移可）
_RESOLVED_PAIR_STATUSES = frozenset(
    {
        PairStatus.AUTO_MATCHED,
        PairStatus.CONFIRMED,
        PairStatus.REJECTED,
        PairStatus.MANUALLY_SELECTED,
        PairStatus.SKIPPED,
    }
)


@dataclass(frozen=True)
class CandidateState:
    """JSON 永続化用の類似候補（matcher.CandidateFile をシリアライズ可能形に変換）。"""

    path: str
    kind: SourceKind
    distance: int
    extracted_name: str


# MatchStatus と PairStatus は最初の3値が同一文字列で揃っている（意図的）。
# 昇格状態（confirmed / rejected / manually_selected / skipped）だけ PairStatus 固有。
_MATCH_TO_PAIR: dict[MatchStatus, PairStatus] = {
    MatchStatus.AUTO_MATCHED: PairStatus.AUTO_MATCHED,
    MatchStatus.NEEDS_CONFIRMATION: PairStatus.NEEDS_CONFIRMATION,
    MatchStatus.NO_MATCH: PairStatus.NO_MATCH,
}


@dataclass
class UserCandidate:
    """1 利用者ページに紐づく状態。"""

    page_index: int
    user_name_ocr: str
    confidence: Confidence
    status: PairStatus
    matched_b_path: str | None
    matched_c_path: str | None
    similar_candidates: list[CandidateState] = field(default_factory=list)

    @property
    def is_resolved(self) -> bool:
        return self.status in _RESOLVED_PAIR_STATUSES

    @classmethod
    def from_match_result(
        cls,
        *,
        page_index: int,
        user_name_ocr: str,
        confidence: Confidence,
        match_result: MatchResult,
    ) -> UserCandidate:
        pair_status = _MATCH_TO_PAIR[match_result.status]

        return cls(
            page_index=page_index,
            user_name_ocr=user_name_ocr,
            confidence=confidence,
            status=pair_status,
            matched_b_path=str(match_result.matched_b_path)
            if match_result.matched_b_path
            else None,
            matched_c_path=str(match_result.matched_c_path)
            if match_result.matched_c_path
            else None,
            similar_candidates=[
                CandidateState(
                    path=str(c.path),
                    kind=c.kind,
                    distance=c.distance,
                    extracted_name=c.extracted_name,
                )
                for c in match_result.similar_candidates
            ],
        )


@dataclass
class Session:
    session_id: str
    status: SessionStatus
    created_at: str
    updated_at: str
    config_snapshot: dict[str, Any]
    source_a_path: str
    candidates: list[UserCandidate]
    a_page_pdf_bytes_dir: str
    output_path: str | None

    @property
    def all_candidates_resolved(self) -> bool:
        # 空 candidates は `all([]) == True` になるが、実運用では Phase A で利用者 0名
        # だった場合にいきなり ready_to_merge 扱いになるのを防ぐため False を返す。
        if not self.candidates:
            return False
        return all(c.is_resolved for c in self.candidates)


# ---------------------------------------------------------------------------
# session_id
# ---------------------------------------------------------------------------


def generate_session_id() -> str:
    """`20260420T001523Z-a1b2` 形式の session_id を生成する。"""
    now = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    suffix = secrets.token_hex(2)
    return f"{now}-{suffix}"


def _validate_session_id(session_id: str) -> None:
    """パストラバーサル防止。英数字・ハイフン・アンダースコアのみ許可。"""
    if not _SESSION_ID_RE.match(session_id):
        raise ValueError(f"invalid session_id: {session_id!r}")


# ---------------------------------------------------------------------------
# save / load
# ---------------------------------------------------------------------------


def _session_path(session_id: str, sessions_dir: Path) -> Path:
    _validate_session_id(session_id)
    return sessions_dir / f"{session_id}.json"


def _to_dict(session: Session) -> dict[str, Any]:
    # StrEnum は dataclasses.asdict 後も Enum インスタンスのまま残るため、明示的に str へ。
    d = asdict(session)
    d["schema_version"] = SCHEMA_VERSION
    d["status"] = str(session.status)
    for cand, original in zip(d["candidates"], session.candidates, strict=True):
        cand["status"] = str(original.status)
    return d


def save_session(session: Session, *, sessions_dir: Path) -> Path:
    """セッションを JSON としてアトミックに保存する。

    副作用: ``session.updated_at`` を現在時刻で上書きする（監査ログと整合させるため）。
    """
    sessions_dir.mkdir(parents=True, exist_ok=True)
    _validate_session_id(session.session_id)

    session.updated_at = datetime.now(UTC).isoformat()

    data = _to_dict(session)
    payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")

    target = _session_path(session.session_id, sessions_dir)
    fd, tmp_name = tempfile.mkstemp(
        dir=sessions_dir, prefix=f".{session.session_id}.", suffix=".tmp"
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, target)
    except (OSError, ValueError):
        # BaseException 派生（KeyboardInterrupt / MemoryError / SystemExit）は伝播させ、
        # 本モジュールが扱う IO/値エラーのみ tmp クリーンアップして再送出する。
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError as e:
            logger.warning("failed to clean up tmp session file %s: %s", tmp_path, e)
        raise
    return target


def load_session(session_id: str, *, sessions_dir: Path) -> Session:
    """JSON からセッションを復元する。"""
    _validate_session_id(session_id)
    path = _session_path(session_id, sessions_dir)
    if not path.exists():
        raise SessionNotFoundError(f"session not found: {session_id}")

    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as e:
        raise SessionCorruptedError(f"failed to read/parse session {session_id}: {e}") from e

    return _from_dict(data, session_id)


def _from_dict(data: dict[str, Any], session_id: str) -> Session:
    schema_version = data.get("schema_version")
    if schema_version != SCHEMA_VERSION:
        raise SessionCorruptedError(
            f"unsupported schema_version for {session_id}: "
            f"got {schema_version!r}, expected {SCHEMA_VERSION}"
        )

    required = [
        "session_id",
        "status",
        "created_at",
        "updated_at",
        "config_snapshot",
        "source_a_path",
        "candidates",
        "a_page_pdf_bytes_dir",
    ]
    missing = [k for k in required if k not in data]
    if missing:
        raise SessionCorruptedError(
            f"session {session_id} missing required fields: {missing}"
        )

    try:
        status = SessionStatus(data["status"])
    except ValueError as e:
        raise SessionCorruptedError(f"invalid status for {session_id}: {e}") from e

    candidates = [_candidate_from_dict(c, session_id) for c in data["candidates"]]

    return Session(
        session_id=data["session_id"],
        status=status,
        created_at=data["created_at"],
        updated_at=data["updated_at"],
        config_snapshot=data["config_snapshot"],
        source_a_path=data["source_a_path"],
        candidates=candidates,
        a_page_pdf_bytes_dir=data["a_page_pdf_bytes_dir"],
        output_path=data.get("output_path"),
    )


_CANDIDATE_REQUIRED = ("page_index", "user_name_ocr", "confidence", "status")
_SIMILAR_REQUIRED = ("path", "kind", "distance", "extracted_name")
_VALID_CONFIDENCE = ("high", "medium", "low")


def _candidate_from_dict(data: dict[str, Any], session_id: str) -> UserCandidate:
    missing = [k for k in _CANDIDATE_REQUIRED if k not in data]
    if missing:
        raise SessionCorruptedError(
            f"candidate in {session_id} missing required fields: {missing}"
        )

    try:
        status = PairStatus(data["status"])
    except ValueError as e:
        raise SessionCorruptedError(
            f"invalid candidate status in {session_id}: {e}"
        ) from e

    if data["confidence"] not in _VALID_CONFIDENCE:
        raise SessionCorruptedError(
            f"invalid confidence in {session_id}: {data['confidence']!r}"
        )

    similar = []
    for c in data.get("similar_candidates", []):
        sim_missing = [k for k in _SIMILAR_REQUIRED if k not in c]
        if sim_missing:
            raise SessionCorruptedError(
                f"similar_candidate in {session_id} missing required fields: {sim_missing}"
            )
        if c["kind"] not in ("B", "C"):
            raise SessionCorruptedError(
                f"invalid similar_candidate kind in {session_id}: {c['kind']!r}"
            )
        similar.append(
            CandidateState(
                path=c["path"],
                kind=c["kind"],
                distance=c["distance"],
                extracted_name=c["extracted_name"],
            )
        )

    return UserCandidate(
        page_index=data["page_index"],
        user_name_ocr=data["user_name_ocr"],
        confidence=data["confidence"],
        status=status,
        matched_b_path=data.get("matched_b_path"),
        matched_c_path=data.get("matched_c_path"),
        similar_candidates=similar,
    )


# ---------------------------------------------------------------------------
# list / gc
# ---------------------------------------------------------------------------


def list_sessions(*, sessions_dir: Path) -> list[str]:
    """sessions_dir 内の全 session_id を返す（ソートなし）。"""
    if not sessions_dir.exists():
        return []
    result: list[str] = []
    for path in sessions_dir.iterdir():
        if not path.is_file():
            continue
        if path.suffix != ".json":
            continue
        if path.name.startswith("."):
            continue
        result.append(path.stem)
    return sorted(result)


def gc_old_sessions(*, sessions_dir: Path, older_than_days: int = 30) -> list[str]:
    """`completed` 状態かつ `updated_at` が指定日数経過しているセッションを削除する。

    未完了セッション（interrupted / needs_review 等）は対象外。
    破損セッションも触らない（手動対処を促すため）。
    """
    if not sessions_dir.exists():
        return []

    threshold = datetime.now(UTC) - timedelta(days=older_than_days)
    removed: list[str] = []

    for session_id in list_sessions(sessions_dir=sessions_dir):
        try:
            s = load_session(session_id, sessions_dir=sessions_dir)
        except SessionCorruptedError:
            logger.warning("skip corrupted session during GC: %s", session_id)
            continue

        if s.status != SessionStatus.COMPLETED:
            continue

        try:
            updated = datetime.fromisoformat(s.updated_at)
        except ValueError:
            logger.warning("skip session with invalid updated_at: %s", session_id)
            continue

        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=UTC)

        if updated < threshold:
            path = _session_path(session_id, sessions_dir)
            try:
                path.unlink()
                removed.append(session_id)
                logger.info("GC removed completed session: %s", session_id)
            except OSError as e:
                logger.warning("failed to GC session %s: %s", session_id, e)

    return removed
