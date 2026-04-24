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
import shutil
import time
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from glob import glob
from pathlib import Path
from typing import IO, Any

from wiseman_hub.pdf.matcher import MatchResult, MatchStatus, SourceKind
from wiseman_hub.pdf.ocr_client import Confidence
from wiseman_hub.utils.atomic_io import DEFAULT_TMP_GLOB, write_bytes_atomically

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


class InvalidTransitionError(SessionError):
    """ADR-010 の状態遷移図に存在しない遷移、または READY_TO_MERGE 遷移時に未解決
    候補が残っているなど invariant を破る操作。"""


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

# 解決済み集合の補集合（= 人間確認が必要な状態）。UI モジュール等から参照される。
OPEN_PAIR_STATUSES = frozenset(PairStatus) - _RESOLVED_PAIR_STATUSES

# 網羅性 invariant: PairStatus に新値を追加した際、どちらの集合にも入れ忘れたら
# import 時点で落ちる（静かな分類漏れを防ぐ）。
assert _RESOLVED_PAIR_STATUSES.isdisjoint(OPEN_PAIR_STATUSES), (
    "RESOLVED と OPEN 集合が重複している"
)
assert frozenset(PairStatus) == _RESOLVED_PAIR_STATUSES | OPEN_PAIR_STATUSES, (
    "PairStatus を RESOLVED / OPEN のいずれにも分類し忘れている"
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


@dataclass(frozen=True)
class UserCandidate:
    """1 利用者ページに紐づく状態（Issue #44: frozen immutable）。

    属性を更新する場合は ``dataclasses.replace`` で新インスタンスを構築する。

    注意: ``similar_candidates`` は ``list[CandidateState]`` のため、frozen=True で
    あっても要素の append/remove など in-place 変更は型レベルでは防げない。変更時は
    ``replace(candidate, similar_candidates=[...])`` で新 list を渡すこと。
    型レベルでの deep immutability は Issue #117 で ``tuple`` へ移行予定。
    """

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


@dataclass(frozen=True)
class Session:
    """Phase A/B のセッション状態（Issue #44: frozen immutable）。

    属性を更新する場合は ``dataclasses.replace`` で新インスタンスを構築する。
    ``save_session`` / ``transition_session`` は元 session を mutation せず新 Session を返す。

    注意: ``candidates`` は ``list[UserCandidate]`` のため、frozen=True であっても
    ``session.candidates.append(...)`` のような list 要素の in-place 変更は型レベル
    では防げない。新しい候補集合を構成する場合は必ず ``replace(session, candidates=[...])``
    で新 list を渡すこと。型レベルでの deep immutability は Issue #117 で ``tuple`` へ移行予定。
    """

    session_id: str
    status: SessionStatus
    created_at: str
    updated_at: str
    config_snapshot: dict[str, Any]
    source_a_path: str
    candidates: list[UserCandidate]
    a_page_pdf_bytes_dir: str
    output_path: str | None
    # Phase A 完了時の総ページ数。resume 時に「未処理ページ」判定と進捗表示に使う。
    # optional なので本フィールド導入前の v1 JSON とも互換。
    total_pages_a: int | None = None

    @property
    def all_candidates_resolved(self) -> bool:
        # 空 candidates は `all([]) == True` になるが、実運用では Phase A で利用者 0名
        # だった場合にいきなり ready_to_merge 扱いになるのを防ぐため False を返す。
        if not self.candidates:
            return False
        return all(c.is_resolved for c in self.candidates)


# ---------------------------------------------------------------------------
# セッションロック（ADR-010, Issue #46）
# ---------------------------------------------------------------------------


def _lock_path(session_id: str, sessions_dir: Path) -> Path:
    validate_session_id(session_id)
    return sessions_dir / f"{session_id}.lock"


def _acquire_exclusive_lock(fh: IO[bytes]) -> None:
    """plat 依存の non-blocking 排他ロック。既に保持されていれば例外。

    Windows: ``msvcrt.locking`` の LK_NBLCK（non-blocking exclusive lock）
    POSIX: ``fcntl.flock`` の LOCK_EX | LOCK_NB
    """
    if os.name == "nt":
        import msvcrt

        # 1 バイトロックで十分（実体はプロセス間排他のシグナル）
        # POSIX で mypy を走らせると msvcrt の stub が Windows 限定 attribute を
        # 認識できないため attr-defined を明示的に抑制する。
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
    else:
        import fcntl

        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _release_lock(fh: IO[bytes]) -> None:
    """plat 依存のロック解放。失敗しても例外は伝播させず警告のみ。

    close 時には OS が自動解放するが、明示解放で直後の再取得を安定させる。
    """
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
        else:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except OSError as e:
        logger.warning("failed to release session lock: %s", e)


@contextmanager
def with_session_lock(sessions_dir: Path, session_id: str) -> Iterator[None]:
    """セッション単位の排他ロックを取得する。

    Windows exe 二重起動、UI 操作中の自動 GC、resume と discard の競合から
    セッション JSON の lost update を防ぐ。

    実装: ``{sessions_dir}/{session_id}.lock`` を作成し non-blocking で排他ロック。
    既にロック保持中のプロセスが存在すれば BlockingIOError / OSError。

    Args:
        sessions_dir: セッションファイル保存ディレクトリ（存在しなければ作成）
        session_id: ロック対象のセッション ID

    Raises:
        ValueError: session_id がパストラバーサル等で不正
        BlockingIOError / OSError: 既に別プロセスがロック保持中
    """
    _ensure_sessions_dir(sessions_dir)
    path = _lock_path(session_id, sessions_dir)

    # "a+b" は「存在しなければ作成、既存はそのまま」の書込可能モード。
    # 本ロックはファイル内容を使わないため truncate しない。
    # SIM115: 本関数自体が @contextmanager でラップされており、finally で必ず close する。
    fh = open(path, "a+b")  # noqa: SIM115
    try:
        _acquire_exclusive_lock(fh)
    except BaseException:
        fh.close()
        raise

    try:
        yield
    finally:
        _release_lock(fh)
        fh.close()


# ---------------------------------------------------------------------------
# 状態遷移（ADR-010, Issue #47）
# ---------------------------------------------------------------------------


# ADR-010 の state diagram を表にしたもの。ここにない遷移は全て InvalidTransitionError。
# COMPLETED は終状態（GC 対象）のため出口なし。
_VALID_TRANSITIONS: dict[SessionStatus, frozenset[SessionStatus]] = {
    SessionStatus.RUNNING_PHASE_A: frozenset(
        {
            SessionStatus.NEEDS_REVIEW,
            SessionStatus.READY_TO_MERGE,
            SessionStatus.INTERRUPTED_PHASE_A,
        }
    ),
    SessionStatus.NEEDS_REVIEW: frozenset({SessionStatus.READY_TO_MERGE}),
    SessionStatus.READY_TO_MERGE: frozenset({SessionStatus.RUNNING_PHASE_B}),
    SessionStatus.RUNNING_PHASE_B: frozenset(
        {
            SessionStatus.COMPLETED,
            SessionStatus.INTERRUPTED_PHASE_B,
        }
    ),
    SessionStatus.COMPLETED: frozenset(),
    SessionStatus.INTERRUPTED_PHASE_A: frozenset({SessionStatus.RUNNING_PHASE_A}),
    SessionStatus.INTERRUPTED_PHASE_B: frozenset({SessionStatus.RUNNING_PHASE_B}),
}


def transition_session(session: Session, next_status: SessionStatus) -> Session:
    """`session.status` を `next_status` に遷移させた新 ``Session`` を返す。

    Issue #44 immutable 化: 元の ``session`` は mutation されず、status と updated_at を
    差し替えた新インスタンスを返す。呼出側は ``session = transition_session(session, ...)``
    のように戻り値で置き換えること。

    ADR-010 の状態遷移図と整合しない遷移は `InvalidTransitionError` を送出する。
    `READY_TO_MERGE` への遷移は `session.all_candidates_resolved` を追加検証する
    （未解決候補があるまま merger に進むことを防ぐ）。

    本関数は `save_session` を呼ばない。呼び出し側が必要に応じて保存すること。
    これは「ロック内で複数状態を組み立ててから一括保存」のような pipeline パターンを
    許容するため。
    """
    allowed = _VALID_TRANSITIONS[session.status]
    if next_status not in allowed:
        raise InvalidTransitionError(
            f"invalid transition: {session.status.value} -> {next_status.value} "
            f"(allowed: {sorted(s.value for s in allowed)})"
        )

    if next_status == SessionStatus.READY_TO_MERGE and not session.all_candidates_resolved:
        unresolved_indexes: list[int] = [
            c.page_index for c in session.candidates if not c.is_resolved
        ]
        detail: str = (
            f"page_index={unresolved_indexes}"
            if unresolved_indexes
            else "no candidates in session"
        )
        raise InvalidTransitionError(
            f"cannot transition to ready_to_merge: unresolved candidates ({detail})"
        )

    logger.info(
        "session %s transition: %s -> %s",
        session.session_id,
        session.status.value,
        next_status.value,
    )
    return replace(
        session,
        status=next_status,
        updated_at=datetime.now(UTC).isoformat(),
    )


# ---------------------------------------------------------------------------
# session_id
# ---------------------------------------------------------------------------


def generate_session_id() -> str:
    """`20260420T001523Z-a1b2c3d4` 形式の session_id を生成する。

    ランダム部は 32bit（token_hex(4)）。同一秒内に大量生成しても衝突確率を十分低く
    保つため token_hex(2)=16bit から拡張した（Birthday bound: 2^16 の sqrt で
    ~256 IDs で 50% 衝突、2^32 では ~65k IDs）。
    """
    now = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    suffix = secrets.token_hex(4)
    return f"{now}-{suffix}"


def validate_session_id(session_id: str) -> None:
    """session_id 形式のパストラバーサル防止検証。英数字・ハイフン・アンダースコアのみ許可。

    CLI・UI など外部入力から session_id を受け取る箇所で呼び出す公開 API。
    """
    if not _SESSION_ID_RE.match(session_id):
        raise ValueError(f"invalid session_id: {session_id!r}")


# ---------------------------------------------------------------------------
# save / load
# ---------------------------------------------------------------------------


def session_path(session_id: str, sessions_dir: Path) -> Path:
    """``session_id`` に対応する JSON 保存先パスを返す（session 存在の保証はしない）。

    Issue #44 以前は private ``_session_path`` だったが、``save_session`` の戻り値を
    ``Session`` に変更したため、ファイルパスが必要な呼出側向けに public 化した。
    """
    validate_session_id(session_id)
    return sessions_dir / f"{session_id}.json"


def _to_dict(session: Session) -> dict[str, Any]:
    # StrEnum は dataclasses.asdict 後も Enum インスタンスのまま残るため、明示的に str へ。
    d = asdict(session)
    d["schema_version"] = SCHEMA_VERSION
    d["status"] = str(session.status)
    for cand, original in zip(d["candidates"], session.candidates, strict=True):
        cand["status"] = str(original.status)
    return d


def ensure_private_dir(path: Path) -> None:
    """``path`` を作成し、POSIX では所有者のみ読み書き可能（0o700）にする。

    氏名・B/C パス等の個人情報を含むため、共有 PC 上で他ユーザーから読めない権限を設定する。
    Windows は ACL 継承（ユーザープロファイル配下配置を config で推奨）に委ねる。

    新規作成時だけでなく、既存ディレクトリも mode を検査する（resume で古い運用から
    引き継いだディレクトリが 0o755 のまま残っているケースを補正するため）。POSIX で
    chmod 失敗または chmod 後に mode が 0o700 と一致しない場合、APPI 準拠上の問題
    となるため logger.error で強調ログし stderr 警告を出す（SMB/NFS マウント等で
    発生しうる）。
    """
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        try:
            current_mode = path.stat().st_mode & 0o777
            if current_mode != 0o700:
                os.chmod(path, 0o700)
                actual_mode = path.stat().st_mode & 0o777
                if actual_mode != 0o700:
                    _report_insecure_dir(path, actual_mode)
        except OSError as e:
            logger.error(
                "failed to enforce 0o700 on %s: %s. "
                "PII files inside may be readable by other local users.",
                path,
                e,
            )


def _report_insecure_dir(path: Path, actual_mode: int) -> None:
    import sys as _sys

    msg = (
        f"WARNING: {path} ended up with mode {oct(actual_mode)} instead of 0o700. "
        "PII may be readable by other local users (SMB/NFS/ACL-managed FS)."
    )
    logger.error(msg)
    print(msg, file=_sys.stderr)


def _ensure_sessions_dir(sessions_dir: Path) -> None:
    """セッションディレクトリ専用の薄いエイリアス（後方互換）。"""
    ensure_private_dir(sessions_dir)


# Issue #105: プロセスクラッシュで残留した atomic_io の ``.*.tmp`` を掃除する閾値。
# 採用根拠: session JSON 書込は現状 <50 KB で数百 ms 以内に完了するため、60 秒は
# 2 桁以上の安全マージン。将来 payload が秒オーダーまで膨らむ場合は再評価する。
_STALE_TMP_THRESHOLD_SECONDS = 60.0


def _sweep_stale_session_tmp(
    sessions_dir: Path,
    *,
    threshold_seconds: float = _STALE_TMP_THRESHOLD_SECONDS,
) -> None:
    """``sessions_dir`` 直下の stale tmp を best-effort で削除する。

    ``atomic_io.DEFAULT_TMP_GLOB`` にマッチする tempfile のうち、mtime が閾値
    以上経過したもののみ削除する。実用上の atomic_io 書込時間（通常数百 ms）に
    対して閾値 60 秒は十分な安全マージンであり、並行書込中の tmp を誤削除する
    race は実用上発生しない。

    ``sessions_dir`` が存在しない場合は ``glob`` が空リストを返すため no-op。

    例外契約: 本関数は例外を伝播しない（best-effort）。sweep 失敗は ``save_session``
    の可否に影響しない。``FileNotFoundError``（race で他プロセスが先に消した場合）
    は silent に skip する。他の ``OSError`` は型名別に集計し warning ログに出力する
    （path / 例外 message / PII は出さない）。

    Args:
        sessions_dir: sweep 対象のセッションディレクトリ
        threshold_seconds: stale と見なす経過時間の閾値。既定は 60 秒。テスト注入用。
    """
    threshold = time.time() - threshold_seconds
    pattern = str(sessions_dir / DEFAULT_TMP_GLOB)
    failures: Counter[str] = Counter()
    for p in glob(pattern):
        try:
            mtime = os.path.getmtime(p)
        except FileNotFoundError:
            continue  # race で他プロセスが先に消した → 成功扱い
        except OSError as e:
            failures[type(e).__name__] += 1
            continue
        if mtime > threshold:
            continue
        try:
            os.unlink(p)
        except FileNotFoundError:
            continue  # race で他プロセスが先に消した → 成功扱い
        except OSError as e:
            failures[type(e).__name__] += 1
    if failures:
        logger.warning("session tmp sweep failures: %s", dict(failures))


def save_session(session: Session, *, sessions_dir: Path) -> Session:
    """セッションを JSON としてアトミックに保存し、``updated_at`` を更新した新 Session を返す。

    Issue #44 immutable 化: 元の ``session`` は mutation されず、``updated_at`` のみを
    現在時刻に差し替えた新インスタンスを構築し、それをシリアライズして保存する。
    呼出側は ``session = save_session(session, ...)`` のように戻り値で置き換えること。
    保存先パスが必要な場合は ``session_path(session_id, sessions_dir)`` を使う。
    """
    _ensure_sessions_dir(sessions_dir)
    validate_session_id(session.session_id)
    # Issue #105: プロセスクラッシュで残留した PII 含む tmp を都度掃除する。
    # 頻繁な glob だが sessions_dir のファイル数は通常小さく、mtime で並行保護。
    _sweep_stale_session_tmp(sessions_dir)

    refreshed = replace(session, updated_at=datetime.now(UTC).isoformat())

    data = _to_dict(refreshed)
    payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")

    target = session_path(refreshed.session_id, sessions_dir)
    # tmp cleanup は atomic_io 側の finally で BaseException 含む全例外時に実施される。
    # write_bytes_atomically は fsync 標準なのでセッション保存の耐障害性要件を満たす。
    # prefix は atomic_io のデフォルト "." を採用（session ディレクトリに sweep 機構は
    # 存在しないため、旧実装の ``.{session_id}.`` prefix を維持する必要はない）。
    write_bytes_atomically(target, payload)
    return refreshed


def load_session(session_id: str, *, sessions_dir: Path) -> Session:
    """JSON からセッションを復元する。"""
    validate_session_id(session_id)
    path = session_path(session_id, sessions_dir)
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

    # ファイル名の session_id と JSON 内部の session_id が一致することを検証
    # （ファイルコピー・手動復旧・破損時の取り違いを防ぐ）
    if data.get("session_id") != session_id:
        raise SessionCorruptedError(
            f"session_id mismatch: file={session_id!r}, content={data.get('session_id')!r}"
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

    total_pages_a = data.get("total_pages_a")
    if total_pages_a is not None and not isinstance(total_pages_a, int):
        raise SessionCorruptedError(
            f"total_pages_a must be int or absent in {session_id}: "
            f"{type(total_pages_a).__name__}"
        )

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
        total_pages_a=total_pages_a,
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
    """sessions_dir 内の session_id を返す（昇順）。

    不正な stem（スペースや特殊文字を含む手動配置ファイル）は除外する。
    ``generate_session_id`` が生成する形式に合致するものだけを返すため、
    呼び出し側で改めて validate する必要はない。
    """
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
        if not _SESSION_ID_RE.match(path.stem):
            # 不正な stem は個人情報を含む .json の可能性があるため、運用者が手動
            # 確認できるよう info ログに出す（警告ではなく、ノイズ低減のため info）。
            logger.info(
                "list_sessions skipped non-conforming file: %s (not a valid session_id)",
                path.name,
            )
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
            # PII を含む artifact が GC 対象外のまま滞留する。運用者が手動対処できるよう
            # artifact パスも出力する（詳細ログで追跡可能にする）。
            logger.warning(
                "GC skipped session with invalid updated_at: session=%s "
                "updated_at_raw=%r artifact_dir=%s (manual cleanup required)",
                session_id,
                s.updated_at,
                s.a_page_pdf_bytes_dir,
            )
            continue

        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=UTC)

        if updated < threshold:
            path = session_path(session_id, sessions_dir)
            try:
                remove_session_artifacts(s, sessions_dir)
                path.unlink()
                removed.append(session_id)
                logger.info("GC removed completed session: %s", session_id)
            except (OSError, SessionError) as e:
                # 他セッションの GC を阻害しないよう継続する。ただし JSON は残すため
                # 次回 GC サイクルで再試行される（transient 失敗なら自動回復）。
                logger.warning("failed to GC session %s: %s", session_id, e)

    return removed


def remove_session_artifacts(session: Session, sessions_dir: Path) -> None:
    """セッションに紐づく per-page PDF ディレクトリを削除する。

    氏名を含む PDF 断片が残ると個人情報が長期残留するため、
    セッション JSON 削除と同時に artifact も除去する。
    安全策として sessions_dir 配下であることを検証してから削除する。

    Raises:
        OSError: `shutil.rmtree` が失敗した場合。呼び出し側はこれを捕捉して
            JSON を先消ししないこと（PII 孤児化を防ぐため）。
        SessionError: artifact パスが sessions_dir 外（改ざん等）。
    """
    artifact_dir = Path(session.a_page_pdf_bytes_dir)
    if not artifact_dir.exists():
        return
    try:
        sessions_dir_resolved = sessions_dir.resolve()
        artifact_resolved = artifact_dir.resolve()
        artifact_resolved.relative_to(sessions_dir_resolved)
    except (OSError, ValueError) as e:
        # sessions_dir 配下でない artifact は触らない（誤操作防止）。
        # 呼び出し側は JSON を消さずに停止する判断ができるよう例外で通知する。
        raise SessionError(
            f"artifact path is outside sessions_dir: {artifact_dir} "
            f"(session={session.session_id})"
        ) from e
    shutil.rmtree(artifact_dir)
    logger.info("removed session artifacts: %s", artifact_dir)
