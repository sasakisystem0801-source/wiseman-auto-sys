"""``resolve_review_session`` の 9 reason 全 path を直接検証する（Issue #97）。

``scripts/merge_user_pdfs.py::_cmd_review`` / ``__main__._make_review_callback`` の
共通ロジックを抽出した ``pdf/review_flow.resolve_review_session`` について、
fake dialog を注入して全 reason（ready_to_merge / resolved / aborted / unresolved /
concurrent_modification / lock_error / transition_lock_error / invalid_transition /
invalid_status）を網羅的にテストする。

Issue #72 の共通化により CLI/GUI 双方の分岐を 1 テストファイルで検証可能になった。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from wiseman_hub.pdf.review_flow import (
    ReviewOutcome,
    resolve_review_session,
)
from wiseman_hub.pdf.session import (
    InvalidTransitionError,
    PairStatus,
    Session,
    SessionStatus,
    UserCandidate,
    generate_session_id,
    load_session,
    save_session,
)
from wiseman_hub.ui.confirm_dialog import ConfirmDialogResult

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _promote_needs_confirmation(
    candidates: list[UserCandidate],
) -> list[UserCandidate]:
    """NEEDS_CONFIRMATION の候補のみ CONFIRMED に昇格した新 list を返す。

    race 系テストと _FakeDialog.resolve_in_run で共通する「全未解決候補の承認」
    パターンを DRY 化するための小 helper。
    """
    return [
        replace(c, status=PairStatus.CONFIRMED)
        if c.status == PairStatus.NEEDS_CONFIRMATION
        else c
        for c in candidates
    ]


def _resolved_candidate(page_index: int = 0) -> UserCandidate:
    return UserCandidate(
        page_index=page_index,
        user_name_ocr="塩津 美喜子",
        confidence="high",
        status=PairStatus.AUTO_MATCHED,
        matched_b_path=None,
        matched_c_path=None,
        similar_candidates=(),
    )


def _unresolved_candidate(page_index: int = 0) -> UserCandidate:
    return UserCandidate(
        page_index=page_index,
        user_name_ocr="塩津 美貴子",
        confidence="medium",
        status=PairStatus.NEEDS_CONFIRMATION,
        matched_b_path=None,
        matched_c_path=None,
        similar_candidates=(),
    )


def _make_needs_review_session(
    tmp_path: Path,
    *,
    status: SessionStatus = SessionStatus.NEEDS_REVIEW,
    resolved_all: bool = False,
) -> Session:
    """NEEDS_REVIEW の Session を生成し ``.sessions/`` へ保存する。"""
    candidate = _resolved_candidate() if resolved_all else _unresolved_candidate()
    session = Session(
        session_id=generate_session_id(),
        status=status,
        created_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
        config_snapshot={"input_dir": str(tmp_path), "concat_order": ["A", "B", "C"]},
        source_a_path=str(tmp_path / "A.pdf"),
        candidates=(candidate,),
        a_page_pdf_bytes_dir=str(tmp_path / ".pages"),
        output_path=None,
    )
    save_session(session, sessions_dir=tmp_path / ".sessions")
    return session


class _FakeDialog:
    """``ConfirmDialog`` 差し替え用。``run()`` の戻り値と副作用を注入する。"""

    def __init__(
        self,
        session: Session,
        sessions_dir: Path,
        *,
        result_aborted: bool = False,
        resolve_in_run: bool = True,
        on_run: Any = None,
    ) -> None:
        self._session = session
        self._sessions_dir = sessions_dir
        self._result_aborted = result_aborted
        self._resolve_in_run = resolve_in_run
        self._on_run = on_run
        self.call_count = 0

    def run(self) -> ConfirmDialogResult:
        self.call_count += 1
        if self._on_run is not None:
            # Issue #44: race 系テストは on_run 戻り値で FakeDialog._session を差し替える
            # ことで、他プロセス先回りや巻戻し模倣後の dialog 内 session 状態を表現する。
            # 戻り値が None（既存コールバック）なら session は維持する。
            updated = self._on_run(self._session, self._sessions_dir)
            if updated is not None:
                self._session = updated
        if self._resolve_in_run and not self._result_aborted:
            self._session = replace(
                self._session,
                candidates=_promote_needs_confirmation(self._session.candidates),
            )
            self._session = save_session(
                self._session, sessions_dir=self._sessions_dir
            )
        return ConfirmDialogResult(
            session=self._session, aborted=self._result_aborted
        )


class _RecordingFactory:
    """``_FakeDialog`` を生成する callable。作成した dialog 一覧を ``calls`` に保持。

    evaluator / code-simplifier 指摘: 関数に属性を後付け (``factory.calls = ...``) する
    hack を避け、型付き class として明示する（``# type: ignore[attr-defined]`` 削除）。
    """

    def __init__(self, **dialog_kwargs: Any) -> None:
        self.calls: list[_FakeDialog] = []
        self._kwargs = dialog_kwargs

    def __call__(self, session: Session, sessions_dir: Path) -> _FakeDialog:
        d = _FakeDialog(session, sessions_dir, **self._kwargs)
        self.calls.append(d)
        return d


def _make_factory(**dialog_kwargs: Any) -> _RecordingFactory:
    return _RecordingFactory(**dialog_kwargs)


# ---------------------------------------------------------------------------
# Success paths
# ---------------------------------------------------------------------------


class TestResolvedSuccess:
    """NEEDS_REVIEW → dialog で全解決 → READY_TO_MERGE 遷移の正常系。"""

    def test_resolved_transitions_to_ready_to_merge(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / ".sessions"
        session = _make_needs_review_session(tmp_path)
        factory = _make_factory()

        outcome = resolve_review_session(
            session.session_id, sessions_dir, dialog_factory=factory
        )

        assert outcome.reason == "resolved"
        assert outcome.session_id == session.session_id
        assert outcome.detail is None

        # ディスク上は READY_TO_MERGE に遷移している
        reloaded = load_session(session.session_id, sessions_dir=sessions_dir)
        assert reloaded.status == SessionStatus.READY_TO_MERGE

        # dialog は 1 回だけ呼ばれている
        assert len(factory.calls) == 1
        assert factory.calls[0].call_count == 1

    def test_resolved_acquires_lock_exactly_twice(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC-4 直接検証: 正常系では with_session_lock が 2 回呼ばれる（TOCTOU 対策）。

        evaluator 指摘に対応し、lock 呼出回数を monkeypatch で直接カウントする。
        """
        sessions_dir = tmp_path / ".sessions"
        session = _make_needs_review_session(tmp_path)
        factory = _make_factory()

        from wiseman_hub.pdf import review_flow as flow_mod

        real_lock = flow_mod.with_session_lock
        call_count = {"n": 0}

        @contextmanager
        def counting_lock(
            sessions_dir_arg: Path, session_id_arg: str
        ) -> Iterator[None]:
            call_count["n"] += 1
            with real_lock(sessions_dir_arg, session_id_arg):
                yield

        monkeypatch.setattr(flow_mod, "with_session_lock", counting_lock)

        outcome = resolve_review_session(
            session.session_id, sessions_dir, dialog_factory=factory
        )

        assert outcome.reason == "resolved"
        assert call_count["n"] == 2  # 1st: load+dialog, 2nd: re-verify+transition


class TestReadyToMergeEarlyReturn:
    """1st lock 内で READY_TO_MERGE を検知した場合、dialog 起動せず冪等成功。"""

    def test_ready_to_merge_first_lock(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / ".sessions"
        session = _make_needs_review_session(
            tmp_path,
            status=SessionStatus.READY_TO_MERGE,
            resolved_all=True,
        )
        factory = _make_factory()

        outcome = resolve_review_session(
            session.session_id, sessions_dir, dialog_factory=factory
        )

        assert outcome.reason == "ready_to_merge"
        assert outcome.session_id == session.session_id
        # dialog は 1 度も呼ばれない（READY_TO_MERGE で早期 return）
        assert factory.calls == []

    def test_ready_to_merge_second_lock_idempotent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """dialog 後、2nd lock 再取得時に他プロセスが既に READY_TO_MERGE へ遷移
        させていた場合、冪等成功として ready_to_merge を返す。"""
        sessions_dir = tmp_path / ".sessions"
        session = _make_needs_review_session(tmp_path)

        # dialog 中に候補を解決 + 他プロセスが先回りして READY_TO_MERGE 遷移させた状況。
        # Issue #44: on_run 戻り値で FakeDialog._session を差し替えることで in-memory
        # も resolved 状態にする（FakeDialog._session.candidates が resolved_all=True
        # を満たさないと review_flow が unresolved で早期 return してしまうため）。
        def race_to_ready(s: Session, d: Path) -> Session:
            racer = load_session(s.session_id, sessions_dir=d)
            racer = replace(
                racer,
                candidates=_promote_needs_confirmation(racer.candidates),
                status=SessionStatus.READY_TO_MERGE,
            )
            save_session(racer, sessions_dir=d)
            return racer

        factory = _make_factory(on_run=race_to_ready, resolve_in_run=False)

        outcome = resolve_review_session(
            session.session_id, sessions_dir, dialog_factory=factory
        )

        assert outcome.reason == "ready_to_merge"
        assert outcome.session_id == session.session_id

        reloaded = load_session(session.session_id, sessions_dir=sessions_dir)
        assert reloaded.status == SessionStatus.READY_TO_MERGE


# ---------------------------------------------------------------------------
# Cancel paths
# ---------------------------------------------------------------------------


class TestAbortedDialog:
    """``ConfirmDialog.run()`` が aborted=True を返した場合、transition はしない。"""

    def test_aborted_preserves_state(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / ".sessions"
        session = _make_needs_review_session(tmp_path)
        factory = _make_factory(result_aborted=True, resolve_in_run=False)

        outcome = resolve_review_session(
            session.session_id, sessions_dir, dialog_factory=factory
        )

        assert outcome.reason == "aborted"
        assert outcome.session_id == session.session_id

        reloaded = load_session(session.session_id, sessions_dir=sessions_dir)
        assert reloaded.status == SessionStatus.NEEDS_REVIEW  # 旧状態保持


class TestUnresolved:
    """dialog を閉じたが未解決候補が残っている場合、transition せず unresolved を返す。"""

    def test_unresolved_no_transition(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / ".sessions"
        session = _make_needs_review_session(tmp_path)

        # dialog 終了時に候補が未解決のまま save する fake
        factory = _make_factory(resolve_in_run=False)

        outcome = resolve_review_session(
            session.session_id, sessions_dir, dialog_factory=factory
        )

        assert outcome.reason == "unresolved"
        # code-reviewer 指摘: unresolved の detail に未解決候補数が入ることを検証
        # （CLI 側の既存メッセージ "N candidate(s) still unresolved" を復元する契約）
        assert outcome.detail == "1"  # _make_needs_review_session は 1 候補
        reloaded = load_session(session.session_id, sessions_dir=sessions_dir)
        assert reloaded.status == SessionStatus.NEEDS_REVIEW


class TestInvalidStatus:
    """1st lock 内で NEEDS_REVIEW / READY_TO_MERGE 以外の status を検知したら dialog 起動しない。"""

    def test_running_phase_a_invalid(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / ".sessions"
        session = _make_needs_review_session(
            tmp_path, status=SessionStatus.RUNNING_PHASE_A
        )
        factory = _make_factory()

        outcome = resolve_review_session(
            session.session_id, sessions_dir, dialog_factory=factory
        )

        assert outcome.reason == "invalid_status"
        assert outcome.detail == SessionStatus.RUNNING_PHASE_A.value
        assert factory.calls == []

    def test_completed_invalid(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / ".sessions"
        session = _make_needs_review_session(
            tmp_path, status=SessionStatus.COMPLETED, resolved_all=True
        )
        factory = _make_factory()

        outcome = resolve_review_session(
            session.session_id, sessions_dir, dialog_factory=factory
        )

        assert outcome.reason == "invalid_status"
        assert outcome.detail == SessionStatus.COMPLETED.value


class TestLockError:
    """1st lock が BlockingIOError / OSError を raise したら dialog 起動せず lock_error。"""

    def test_blocking_io_error_first_lock(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sessions_dir = tmp_path / ".sessions"
        session = _make_needs_review_session(tmp_path)
        factory = _make_factory()

        # with_session_lock 自体を monkeypatch して 1 回目の呼出で BlockingIOError
        call_count = {"n": 0}

        @contextmanager
        def failing_lock(
            _sessions_dir: Path, _session_id: str
        ) -> Iterator[None]:
            call_count["n"] += 1
            raise BlockingIOError("simulated first-lock contention")
            yield  # pragma: no cover

        monkeypatch.setattr(
            "wiseman_hub.pdf.review_flow.with_session_lock", failing_lock
        )

        outcome = resolve_review_session(
            session.session_id, sessions_dir, dialog_factory=factory
        )

        assert outcome.reason == "lock_error"
        assert outcome.detail == "BlockingIOError"
        assert factory.calls == []
        assert call_count["n"] == 1

    def test_os_error_first_lock(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sessions_dir = tmp_path / ".sessions"
        session = _make_needs_review_session(tmp_path)
        factory = _make_factory()

        @contextmanager
        def failing_lock(
            _sessions_dir: Path, _session_id: str
        ) -> Iterator[None]:
            raise OSError("permission denied")
            yield  # pragma: no cover

        monkeypatch.setattr(
            "wiseman_hub.pdf.review_flow.with_session_lock", failing_lock
        )

        outcome = resolve_review_session(
            session.session_id, sessions_dir, dialog_factory=factory
        )

        assert outcome.reason == "lock_error"
        assert outcome.detail == "OSError"


class TestTransitionLockError:
    """2nd lock 再取得で BlockingIOError になった場合、dialog の save は残るが transition_lock_error。"""

    def test_second_lock_blocks_after_dialog(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sessions_dir = tmp_path / ".sessions"
        session = _make_needs_review_session(tmp_path)
        factory = _make_factory()

        from wiseman_hub.pdf import review_flow as flow_mod

        real_lock = flow_mod.with_session_lock
        call_n = {"n": 0}

        @contextmanager
        def flaky_lock(
            sessions_dir_arg: Path, session_id_arg: str
        ) -> Iterator[None]:
            call_n["n"] += 1
            if call_n["n"] == 2:
                raise BlockingIOError("simulated 2nd-lock contention")
            with real_lock(sessions_dir_arg, session_id_arg):
                yield

        monkeypatch.setattr(flow_mod, "with_session_lock", flaky_lock)

        outcome = resolve_review_session(
            session.session_id, sessions_dir, dialog_factory=factory
        )

        assert outcome.reason == "transition_lock_error"
        assert outcome.detail == "BlockingIOError"
        # dialog は 1 回呼ばれて candidate の解決は save されているが、遷移は未完了
        reloaded = load_session(session.session_id, sessions_dir=sessions_dir)
        assert reloaded.status == SessionStatus.NEEDS_REVIEW
        assert reloaded.all_candidates_resolved  # 解決状態は永続化済み


class TestConcurrentModification:
    """dialog 後、2nd lock 取得時に他プロセスが status を不正遷移させた場合、
    transition を中止し concurrent_modification を返す。"""

    def test_status_changed_to_completed_between_locks(
        self, tmp_path: Path
    ) -> None:
        sessions_dir = tmp_path / ".sessions"
        session = _make_needs_review_session(tmp_path)

        # dialog の on_run で候補を解決 + ディスク上 status を COMPLETED に書換。
        # Issue #44: on_run 戻り値で dialog 内 session も resolved 化し in-memory
        # を resolved_all=True に保つ（review_flow が unresolved で早期 return しないように）。
        def race_to_completed(s: Session, d: Path) -> Session:
            # dialog 内 in-memory 用: candidates を CONFIRMED にした session
            in_memory = replace(
                s,
                candidates=_promote_needs_confirmation(s.candidates),
            )
            # Disk は他プロセスが COMPLETED 遷移させた状態を模倣（candidates も解決済）
            racer = load_session(s.session_id, sessions_dir=d)
            racer = replace(
                racer,
                candidates=in_memory.candidates,
                status=SessionStatus.COMPLETED,
            )
            save_session(racer, sessions_dir=d)
            return in_memory

        factory = _make_factory(on_run=race_to_completed, resolve_in_run=False)

        outcome = resolve_review_session(
            session.session_id, sessions_dir, dialog_factory=factory
        )

        assert outcome.reason == "concurrent_modification"
        assert outcome.detail == SessionStatus.COMPLETED.value

        # ディスク状態は他プロセスが設定した値のまま（本関数は変更しない）
        reloaded = load_session(session.session_id, sessions_dir=sessions_dir)
        assert reloaded.status == SessionStatus.COMPLETED

    def test_all_resolved_reverted_between_locks(self, tmp_path: Path) -> None:
        """2nd lock で NEEDS_REVIEW のままでも解決が巻き戻されていれば concurrent_modification。"""
        sessions_dir = tmp_path / ".sessions"
        session = _make_needs_review_session(tmp_path)

        # Issue #44: on_run 戻り値で dialog 内 session を resolved 化し、
        # disk は別プロセスにより NEEDS_CONFIRMATION に巻き戻された状態を模倣する。
        def race_unresolve(s: Session, d: Path) -> Session:
            # dialog 内: 全 candidates を CONFIRMED に
            in_memory = replace(
                s,
                candidates=_promote_needs_confirmation(s.candidates),
            )
            # disk: 他プロセスが candidates を NEEDS_CONFIRMATION に巻き戻した
            racer = load_session(s.session_id, sessions_dir=d)
            reverted = [
                replace(c, status=PairStatus.NEEDS_CONFIRMATION)
                for c in racer.candidates
            ]
            racer = replace(racer, candidates=reverted)
            save_session(racer, sessions_dir=d)
            return in_memory

        factory = _make_factory(on_run=race_unresolve, resolve_in_run=False)

        outcome = resolve_review_session(
            session.session_id, sessions_dir, dialog_factory=factory
        )

        assert outcome.reason == "concurrent_modification"
        assert outcome.detail == SessionStatus.NEEDS_REVIEW.value

        # evaluator 指摘: status==NEEDS_REVIEW かつ all_candidates_resolved==False
        # の両条件で concurrent_modification を判定していることを明示検証
        reloaded = load_session(session.session_id, sessions_dir=sessions_dir)
        assert reloaded.status == SessionStatus.NEEDS_REVIEW
        assert reloaded.all_candidates_resolved is False


class TestSessionLoadErrorPropagation:
    """1st lock 内の load_session が SessionNotFoundError / SessionCorruptedError を
    raise した場合、本関数では捕捉せず伝播させる（docstring「呼出側契約」）。

    evaluator 指摘: picker 選択後〜1st lock 取得前に他プロセスが --discard した
    race で発生し得るため、契約を明示的にテスト化する。"""

    def test_session_not_found_propagates(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / ".sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        factory = _make_factory()

        # 存在しない session_id を渡す → 1st lock 取得は成功するが load_session で
        # SessionNotFoundError が raise される
        from wiseman_hub.pdf.session import SessionNotFoundError

        with pytest.raises(SessionNotFoundError):
            resolve_review_session(
                "nonexistent-id", sessions_dir, dialog_factory=factory
            )
        # dialog は起動しない（load_session 失敗で exception が伝播）
        assert factory.calls == []

    def test_session_corrupted_propagates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sessions_dir = tmp_path / ".sessions"
        session = _make_needs_review_session(tmp_path)
        factory = _make_factory()

        # load_session を monkeypatch して SessionCorruptedError を raise
        from wiseman_hub.pdf import review_flow as flow_mod
        from wiseman_hub.pdf.session import SessionCorruptedError

        def raise_corrupted(_sid: str, *, sessions_dir: Path) -> Session:
            raise SessionCorruptedError("simulated JSON corruption")

        monkeypatch.setattr(flow_mod, "load_session", raise_corrupted)

        with pytest.raises(SessionCorruptedError):
            resolve_review_session(
                session.session_id, sessions_dir, dialog_factory=factory
            )
        assert factory.calls == []


class TestInvalidTransitionFallback:
    """最終安全網: transition_session が InvalidTransitionError を raise した場合。

    通常は fresh.status チェックで弾くが、状態機械の race 最終安全網として残す。"""

    def test_invalid_transition_error_mapped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sessions_dir = tmp_path / ".sessions"
        session = _make_needs_review_session(tmp_path)
        factory = _make_factory()

        # transition_session を monkeypatch して InvalidTransitionError を raise
        def raise_invalid(_session: Session, _to: SessionStatus) -> None:
            raise InvalidTransitionError("simulated state machine race")

        monkeypatch.setattr(
            "wiseman_hub.pdf.review_flow.transition_session", raise_invalid
        )

        outcome = resolve_review_session(
            session.session_id, sessions_dir, dialog_factory=factory
        )

        assert outcome.reason == "invalid_transition"
        assert outcome.detail == "InvalidTransitionError"


# ---------------------------------------------------------------------------
# ReviewOutcome 値オブジェクト
# ---------------------------------------------------------------------------


class TestReviewOutcome:
    """``ReviewOutcome`` の invariant 検証。"""

    def test_frozen_dataclass(self) -> None:
        """frozen=True のため属性変更は FrozenInstanceError。"""
        from dataclasses import FrozenInstanceError

        outcome = ReviewOutcome("resolved", "abc123")
        with pytest.raises(FrozenInstanceError):
            outcome.reason = "aborted"  # type: ignore[misc]

    def test_default_detail_is_none(self) -> None:
        outcome = ReviewOutcome("resolved", "abc123")
        assert outcome.detail is None

    def test_all_reasons_constructable(self) -> None:
        """全 9 reason が construct 可能（Literal 型 + Issue #97 網羅確認）。"""
        all_reasons = [
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
        for r in all_reasons:
            outcome = ReviewOutcome(r, "abc123")  # type: ignore[arg-type]
            assert outcome.reason == r
