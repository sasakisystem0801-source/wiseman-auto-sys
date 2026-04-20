"""セッション永続化のユニットテスト（ADR-010）。"""

from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from wiseman_hub.pdf.matcher import CandidateFile, MatchResult, MatchStatus
from wiseman_hub.pdf.session import (
    CandidateState,
    PairStatus,
    Session,
    SessionCorruptedError,
    SessionNotFoundError,
    SessionStatus,
    UserCandidate,
    gc_old_sessions,
    generate_session_id,
    list_sessions,
    load_session,
    save_session,
)

# ---------------------------------------------------------------------------
# session_id
# ---------------------------------------------------------------------------


class TestGenerateSessionId:
    def test_format_is_iso8601_with_suffix(self) -> None:
        sid = generate_session_id()
        # 例: "20260420T001523Z-a1b2"
        assert re.match(r"^\d{8}T\d{6}Z-[0-9a-f]{4}$", sid) is not None

    def test_two_consecutive_calls_unique(self) -> None:
        # 同一秒内でも一意
        sid1 = generate_session_id()
        sid2 = generate_session_id()
        assert sid1 != sid2


# ---------------------------------------------------------------------------
# save / load
# ---------------------------------------------------------------------------


def _make_session(tmp_path: Path, **overrides) -> Session:
    defaults = dict(
        session_id=generate_session_id(),
        status=SessionStatus.RUNNING_PHASE_A,
        created_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
        config_snapshot={"input_dir": str(tmp_path), "concat_order": ["A", "B", "C"]},
        source_a_path=str(tmp_path / "A.pdf"),
        candidates=[],
        a_page_pdf_bytes_dir=str(tmp_path / ".pages"),
        output_path=None,
    )
    defaults.update(overrides)
    return Session(**defaults)


class TestSaveLoad:
    def test_round_trip_empty_candidates(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / ".sessions"
        s = _make_session(tmp_path)

        path = save_session(s, sessions_dir=sessions_dir)

        assert path.exists()
        assert path.parent == sessions_dir

        loaded = load_session(s.session_id, sessions_dir=sessions_dir)
        assert loaded.session_id == s.session_id
        assert loaded.status == s.status
        assert loaded.candidates == []

    def test_round_trip_with_candidates(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / ".sessions"
        cand = UserCandidate(
            page_index=0,
            user_name_ocr="塩津 美喜子",
            confidence="high",
            status=PairStatus.AUTO_MATCHED,
            matched_b_path=str(tmp_path / "B_塩津美喜子.pdf"),
            matched_c_path=str(tmp_path / "C_塩津美喜子.pdf"),
            similar_candidates=[
                CandidateState(
                    path=str(tmp_path / "B_other.pdf"),
                    kind="B",
                    distance=1,
                    extracted_name="塩津美貴子",
                )
            ],
        )
        s = _make_session(tmp_path, candidates=[cand])

        save_session(s, sessions_dir=sessions_dir)
        loaded = load_session(s.session_id, sessions_dir=sessions_dir)

        assert len(loaded.candidates) == 1
        assert loaded.candidates[0].user_name_ocr == "塩津 美喜子"
        assert loaded.candidates[0].similar_candidates[0].extracted_name == "塩津美貴子"

    def test_save_is_atomic_no_temp_file_left(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / ".sessions"
        s = _make_session(tmp_path)
        save_session(s, sessions_dir=sessions_dir)

        # temp ファイルが残っていないこと
        tmp_files = list(sessions_dir.glob("*.tmp*"))
        assert tmp_files == []

    def test_save_twice_updates_updated_at(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / ".sessions"
        s = _make_session(tmp_path)
        save_session(s, sessions_dir=sessions_dir)
        loaded1 = load_session(s.session_id, sessions_dir=sessions_dir)

        time.sleep(0.01)

        s2 = _make_session(
            tmp_path,
            session_id=s.session_id,
            status=SessionStatus.NEEDS_REVIEW,
        )
        save_session(s2, sessions_dir=sessions_dir)
        loaded2 = load_session(s.session_id, sessions_dir=sessions_dir)

        assert loaded2.status == SessionStatus.NEEDS_REVIEW
        assert loaded2.updated_at >= loaded1.updated_at

    def test_save_failure_cleans_tmp_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """os.replace が失敗しても .tmp ファイルが残らないこと。"""
        import os

        from wiseman_hub.pdf import session as session_mod

        sessions_dir = tmp_path / ".sessions"
        s = _make_session(tmp_path)

        real_replace = os.replace

        def failing_replace(src: str, dst: str) -> None:
            raise OSError("simulated disk full")

        monkeypatch.setattr(session_mod.os, "replace", failing_replace)

        with pytest.raises(OSError, match="simulated disk full"):
            save_session(s, sessions_dir=sessions_dir)

        # tmp ファイルが残っていないこと
        monkeypatch.setattr(session_mod.os, "replace", real_replace)
        tmp_files = list(sessions_dir.glob("*.tmp*"))
        assert tmp_files == []
        # 本体ファイルも作られていない
        assert not (sessions_dir / f"{s.session_id}.json").exists()


class TestLoadErrors:
    def test_missing_session_raises(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / ".sessions"
        sessions_dir.mkdir()

        with pytest.raises(SessionNotFoundError):
            load_session("nonexistent-xxxx", sessions_dir=sessions_dir)

    def test_invalid_json_raises_corrupted(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / ".sessions"
        sessions_dir.mkdir()
        (sessions_dir / "broken.json").write_text("not a json {{{")

        with pytest.raises(SessionCorruptedError):
            load_session("broken", sessions_dir=sessions_dir)

    def test_wrong_schema_version_raises(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / ".sessions"
        sessions_dir.mkdir()
        # 未来バージョンを偽装
        (sessions_dir / "future.json").write_text(
            json.dumps({"schema_version": 99, "session_id": "future"})
        )

        with pytest.raises(SessionCorruptedError, match="schema_version"):
            load_session("future", sessions_dir=sessions_dir)

    def test_missing_required_field_raises(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / ".sessions"
        sessions_dir.mkdir()
        (sessions_dir / "partial.json").write_text(
            json.dumps({"schema_version": 1, "session_id": "partial"})
        )

        with pytest.raises(SessionCorruptedError, match="missing required fields"):
            load_session("partial", sessions_dir=sessions_dir)

    def _candidate_payload(self, tmp_path: Path, candidate: dict) -> dict:
        return {
            "schema_version": 1,
            "session_id": "corrupt",
            "status": "needs_review",
            "created_at": "2026-04-20T00:00:00+00:00",
            "updated_at": "2026-04-20T00:00:00+00:00",
            "config_snapshot": {},
            "source_a_path": str(tmp_path / "A.pdf"),
            "candidates": [candidate],
            "a_page_pdf_bytes_dir": str(tmp_path / ".pages"),
            "output_path": None,
        }

    def test_invalid_candidate_kind_raises(self, tmp_path: Path) -> None:
        """similar_candidates 内の kind が B/C 以外の場合、破損扱いで拒否する。"""
        sessions_dir = tmp_path / ".sessions"
        sessions_dir.mkdir()
        payload = self._candidate_payload(
            tmp_path,
            {
                "page_index": 0,
                "user_name_ocr": "x",
                "confidence": "high",
                "status": "needs_confirmation",
                "matched_b_path": None,
                "matched_c_path": None,
                "similar_candidates": [
                    {"path": "/tmp/a.pdf", "kind": "X", "distance": 1, "extracted_name": "a"}
                ],
            },
        )
        payload["session_id"] = "bad-kind"
        (sessions_dir / "bad-kind.json").write_text(json.dumps(payload))

        with pytest.raises(SessionCorruptedError, match="kind"):
            load_session("bad-kind", sessions_dir=sessions_dir)

    def test_invalid_confidence_raises(self, tmp_path: Path) -> None:
        """confidence が high/medium/low 以外の場合、破損扱いで拒否する。"""
        sessions_dir = tmp_path / ".sessions"
        sessions_dir.mkdir()
        payload = self._candidate_payload(
            tmp_path,
            {
                "page_index": 0,
                "user_name_ocr": "x",
                "confidence": "INVALID",
                "status": "auto_matched",
                "matched_b_path": None,
                "matched_c_path": None,
                "similar_candidates": [],
            },
        )
        payload["session_id"] = "bad-conf"
        (sessions_dir / "bad-conf.json").write_text(json.dumps(payload))

        with pytest.raises(SessionCorruptedError, match="confidence"):
            load_session("bad-conf", sessions_dir=sessions_dir)

    def test_missing_candidate_required_field_raises(self, tmp_path: Path) -> None:
        """candidate の必須フィールド欠落で KeyError ではなく SessionCorruptedError を発する。"""
        sessions_dir = tmp_path / ".sessions"
        sessions_dir.mkdir()
        # page_index 欠落
        payload = self._candidate_payload(
            tmp_path,
            {
                "user_name_ocr": "x",
                "confidence": "high",
                "status": "auto_matched",
                "matched_b_path": None,
                "matched_c_path": None,
                "similar_candidates": [],
            },
        )
        payload["session_id"] = "missing-page"
        (sessions_dir / "missing-page.json").write_text(json.dumps(payload))

        with pytest.raises(SessionCorruptedError, match="missing required fields"):
            load_session("missing-page", sessions_dir=sessions_dir)

    def test_missing_similar_candidate_field_raises(self, tmp_path: Path) -> None:
        """similar_candidate 内の必須フィールド欠落で SessionCorruptedError を発する。"""
        sessions_dir = tmp_path / ".sessions"
        sessions_dir.mkdir()
        payload = self._candidate_payload(
            tmp_path,
            {
                "page_index": 0,
                "user_name_ocr": "x",
                "confidence": "medium",
                "status": "needs_confirmation",
                "matched_b_path": None,
                "matched_c_path": None,
                # extracted_name 欠落
                "similar_candidates": [{"path": "/tmp/a.pdf", "kind": "B", "distance": 1}],
            },
        )
        payload["session_id"] = "missing-name"
        (sessions_dir / "missing-name.json").write_text(json.dumps(payload))

        with pytest.raises(SessionCorruptedError, match="similar_candidate"):
            load_session("missing-name", sessions_dir=sessions_dir)


# ---------------------------------------------------------------------------
# list / gc
# ---------------------------------------------------------------------------


class TestListSessions:
    def test_empty_dir_returns_empty_list(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / ".sessions"
        assert list_sessions(sessions_dir=sessions_dir) == []

    def test_returns_all_session_ids_sorted(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / ".sessions"
        # 逆順で保存しても昇順で返ることを確認
        s2 = _make_session(tmp_path, session_id="sess-bbbb")
        s1 = _make_session(tmp_path, session_id="sess-aaaa")
        save_session(s2, sessions_dir=sessions_dir)
        save_session(s1, sessions_dir=sessions_dir)

        ids = list_sessions(sessions_dir=sessions_dir)

        assert ids == ["sess-aaaa", "sess-bbbb"]

    def test_ignores_non_json_files(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / ".sessions"
        sessions_dir.mkdir()
        (sessions_dir / "a.json").write_text(
            json.dumps({"schema_version": 1, "session_id": "a"})
        )
        (sessions_dir / "readme.txt").write_text("noise")

        ids = list_sessions(sessions_dir=sessions_dir)

        assert ids == ["a"]


class TestGcOldSessions:
    def test_removes_completed_older_than_threshold(self, tmp_path: Path) -> None:
        # save_session は updated_at を自動更新するため、GC テストは JSON 直書きで古い日付を仕込む
        sessions_dir = tmp_path / ".sessions"
        sessions_dir.mkdir()
        old_payload = {
            "schema_version": 1,
            "session_id": "old-comp",
            "status": "completed",
            "created_at": "2020-01-01T00:00:00+00:00",
            "updated_at": "2020-01-01T00:00:00+00:00",
            "config_snapshot": {},
            "source_a_path": str(tmp_path / "A.pdf"),
            "candidates": [],
            "a_page_pdf_bytes_dir": str(tmp_path / ".pages"),
            "output_path": None,
        }
        (sessions_dir / "old-comp.json").write_text(json.dumps(old_payload))

        removed = gc_old_sessions(sessions_dir=sessions_dir, older_than_days=30)

        assert "old-comp" in removed
        assert not (sessions_dir / "old-comp.json").exists()

    def test_keeps_recent_completed(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / ".sessions"
        s = _make_session(
            tmp_path,
            session_id="recent-comp",
            status=SessionStatus.COMPLETED,
        )
        save_session(s, sessions_dir=sessions_dir)

        removed = gc_old_sessions(sessions_dir=sessions_dir, older_than_days=30)

        assert removed == []
        assert (sessions_dir / "recent-comp.json").exists()

    def test_keeps_non_completed_regardless_of_age(self, tmp_path: Path) -> None:
        """未完了セッションは古くても削除しない（再開の機会を残す）。"""
        sessions_dir = tmp_path / ".sessions"
        sessions_dir.mkdir()
        old_payload = {
            "schema_version": 1,
            "session_id": "old-interrupted",
            "status": "interrupted_phase_a",
            "created_at": "2020-01-01T00:00:00+00:00",
            "updated_at": "2020-01-01T00:00:00+00:00",
            "config_snapshot": {},
            "source_a_path": str(tmp_path / "A.pdf"),
            "candidates": [],
            "a_page_pdf_bytes_dir": str(tmp_path / ".pages"),
            "output_path": None,
        }
        (sessions_dir / "old-interrupted.json").write_text(json.dumps(old_payload))

        removed = gc_old_sessions(sessions_dir=sessions_dir, older_than_days=30)

        assert removed == []
        assert (sessions_dir / "old-interrupted.json").exists()

    def test_skips_corrupted_session_without_losing_others(self, tmp_path: Path) -> None:
        """破損セッション混在時、GC が異常終了せず他の正常セッションを処理する。"""
        sessions_dir = tmp_path / ".sessions"
        sessions_dir.mkdir()
        (sessions_dir / "broken.json").write_text("not json {{")
        old_ok_payload = {
            "schema_version": 1,
            "session_id": "old-ok",
            "status": "completed",
            "created_at": "2020-01-01T00:00:00+00:00",
            "updated_at": "2020-01-01T00:00:00+00:00",
            "config_snapshot": {},
            "source_a_path": str(tmp_path / "A.pdf"),
            "candidates": [],
            "a_page_pdf_bytes_dir": str(tmp_path / ".pages"),
            "output_path": None,
        }
        (sessions_dir / "old-ok.json").write_text(json.dumps(old_ok_payload))

        removed = gc_old_sessions(sessions_dir=sessions_dir, older_than_days=30)

        # 破損は保全、正常な古い完了セッションのみ削除される
        assert removed == ["old-ok"]
        assert (sessions_dir / "broken.json").exists()
        assert not (sessions_dir / "old-ok.json").exists()

    def test_skips_invalid_updated_at_format(self, tmp_path: Path) -> None:
        """updated_at が ISO 8601 でない completed セッションは GC 対象外（手動対処に委ねる）。"""
        sessions_dir = tmp_path / ".sessions"
        sessions_dir.mkdir()
        bad_payload = {
            "schema_version": 1,
            "session_id": "bad-date",
            "status": "completed",
            "created_at": "not-a-date",
            "updated_at": "not-a-date",
            "config_snapshot": {},
            "source_a_path": str(tmp_path / "A.pdf"),
            "candidates": [],
            "a_page_pdf_bytes_dir": str(tmp_path / ".pages"),
            "output_path": None,
        }
        (sessions_dir / "bad-date.json").write_text(json.dumps(bad_payload))

        removed = gc_old_sessions(sessions_dir=sessions_dir, older_than_days=30)

        assert removed == []
        assert (sessions_dir / "bad-date.json").exists()


class TestSessionStatusTransitions:
    """状態遷移の制約（ADR-010 準拠）。Session 自体は値オブジェクト、遷移判定は外側。
    ここでは enum 値が揃っていることのみ確認。"""

    def test_all_statuses_defined(self) -> None:
        names = {s.value for s in SessionStatus}
        assert names == {
            "running_phase_a",
            "needs_review",
            "ready_to_merge",
            "running_phase_b",
            "completed",
            "interrupted_phase_a",
            "interrupted_phase_b",
        }

    def test_pair_statuses_defined(self) -> None:
        names = {s.value for s in PairStatus}
        assert names == {
            "auto_matched",
            "needs_confirmation",
            "no_match",
            "confirmed",
            "rejected",
            "manually_selected",
            "skipped",
        }


class TestSessionHelpers:
    def test_is_resolved_pair_auto_matched(self) -> None:
        c = UserCandidate(
            page_index=0,
            user_name_ocr="x",
            confidence="high",
            status=PairStatus.AUTO_MATCHED,
            matched_b_path=None,
            matched_c_path=None,
            similar_candidates=[],
        )
        assert c.is_resolved is True

    def test_is_resolved_pair_needs_confirmation(self) -> None:
        c = UserCandidate(
            page_index=0,
            user_name_ocr="x",
            confidence="high",
            status=PairStatus.NEEDS_CONFIRMATION,
            matched_b_path=None,
            matched_c_path=None,
            similar_candidates=[],
        )
        assert c.is_resolved is False

    def test_session_is_ready_to_merge_all_resolved(self, tmp_path: Path) -> None:
        c1 = UserCandidate(
            page_index=0, user_name_ocr="x", confidence="high",
            status=PairStatus.AUTO_MATCHED,
            matched_b_path=None, matched_c_path=None, similar_candidates=[],
        )
        c2 = UserCandidate(
            page_index=1, user_name_ocr="y", confidence="high",
            status=PairStatus.CONFIRMED,
            matched_b_path=None, matched_c_path=None, similar_candidates=[],
        )
        s = _make_session(tmp_path, candidates=[c1, c2])
        assert s.all_candidates_resolved is True

    def test_session_not_ready_one_pending(self, tmp_path: Path) -> None:
        c1 = UserCandidate(
            page_index=0, user_name_ocr="x", confidence="high",
            status=PairStatus.AUTO_MATCHED,
            matched_b_path=None, matched_c_path=None, similar_candidates=[],
        )
        c2 = UserCandidate(
            page_index=1, user_name_ocr="y", confidence="medium",
            status=PairStatus.NEEDS_CONFIRMATION,
            matched_b_path=None, matched_c_path=None, similar_candidates=[],
        )
        s = _make_session(tmp_path, candidates=[c1, c2])
        assert s.all_candidates_resolved is False


class TestFromMatchResult:
    def test_build_candidate_from_match_result_auto_matched(self, tmp_path: Path) -> None:
        mr = MatchResult(
            status=MatchStatus.AUTO_MATCHED,
            matched_b_path=tmp_path / "B_x.pdf",
            matched_c_path=tmp_path / "C_x.pdf",
            similar_candidates=[],
        )
        c = UserCandidate.from_match_result(
            page_index=0,
            user_name_ocr="塩津 美喜子",
            confidence="high",
            match_result=mr,
        )
        assert c.status == PairStatus.AUTO_MATCHED
        assert c.matched_b_path == str(tmp_path / "B_x.pdf")

    def test_build_candidate_from_match_result_needs_confirmation(self, tmp_path: Path) -> None:
        mr = MatchResult(
            status=MatchStatus.NEEDS_CONFIRMATION,
            matched_b_path=None,
            matched_c_path=None,
            similar_candidates=[
                CandidateFile(
                    path=tmp_path / "B_similar.pdf",
                    kind="B",
                    distance=1,
                    extracted_name="山田太郎",
                ),
            ],
        )
        c = UserCandidate.from_match_result(
            page_index=0,
            user_name_ocr="山中太郎",
            confidence="medium",
            match_result=mr,
        )
        assert c.status == PairStatus.NEEDS_CONFIRMATION
        assert c.matched_b_path is None
        assert len(c.similar_candidates) == 1
        assert c.similar_candidates[0].extracted_name == "山田太郎"

    def test_build_candidate_from_match_result_no_match(self, tmp_path: Path) -> None:
        mr = MatchResult(
            status=MatchStatus.NO_MATCH,
            matched_b_path=None,
            matched_c_path=None,
            similar_candidates=[],
        )
        c = UserCandidate.from_match_result(
            page_index=0,
            user_name_ocr="全然違う",
            confidence="low",
            match_result=mr,
        )
        assert c.status == PairStatus.NO_MATCH
