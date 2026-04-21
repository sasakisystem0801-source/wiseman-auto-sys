"""セッション永続化のユニットテスト（ADR-010）。"""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import re
import sys
import time
import types
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from wiseman_hub.pdf.matcher import CandidateFile, MatchResult, MatchStatus
from wiseman_hub.pdf.session import (
    CandidateState,
    InvalidTransitionError,
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
    transition_session,
    with_session_lock,
)

# ---------------------------------------------------------------------------
# multiprocessing target（Issue #51 #2 跨プロセスロック test 用）
# ---------------------------------------------------------------------------
#
# multiprocessing.Process の target はモジュールレベルで picklable であることが必須。
# spawn context ではサブプロセスが再 import するため、テストクラスのメソッドは不可。


def _child_try_acquire_lock(
    sessions_dir_str: str,
    session_id: str,
    result_queue: Any,
) -> None:
    """子プロセスで with_session_lock を試み、結果を queue に返す。

    親プロセスがロック保持中に呼ばれ、子は BlockingIOError / OSError を期待する。
    """
    from wiseman_hub.pdf.session import with_session_lock as _lock

    try:
        with _lock(Path(sessions_dir_str), session_id):
            result_queue.put(("ACQUIRED", None))
    except BlockingIOError as e:
        result_queue.put(("BLOCKED_BlockingIOError", e.errno))
    except OSError as e:
        result_queue.put(("BLOCKED_OSError", e.errno))
    except Exception as e:
        result_queue.put(("UNEXPECTED", f"{type(e).__name__}: {e}"))

# ---------------------------------------------------------------------------
# session_id
# ---------------------------------------------------------------------------


class TestGenerateSessionId:
    def test_format_is_iso8601_with_suffix(self) -> None:
        sid = generate_session_id()
        # 例: "20260420T001523Z-a1b2c3d4"（32bit suffix）
        assert re.match(r"^\d{8}T\d{6}Z-[0-9a-f]{8}$", sid) is not None

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

    def test_session_id_mismatch_raises(self, tmp_path: Path) -> None:
        """ファイル名の session_id と JSON 内部の session_id が一致しない場合、破損扱い。"""
        sessions_dir = tmp_path / ".sessions"
        sessions_dir.mkdir()
        payload = {
            "schema_version": 1,
            "session_id": "internal-B",
            "status": "completed",
            "created_at": "2026-04-20T00:00:00+00:00",
            "updated_at": "2026-04-20T00:00:00+00:00",
            "config_snapshot": {},
            "source_a_path": str(tmp_path / "A.pdf"),
            "candidates": [],
            "a_page_pdf_bytes_dir": str(tmp_path / ".pages"),
            "output_path": None,
        }
        # ファイル名は "file-A" だが内部は "internal-B"
        (sessions_dir / "file-A.json").write_text(json.dumps(payload))

        with pytest.raises(SessionCorruptedError, match="session_id mismatch"):
            load_session("file-A", sessions_dir=sessions_dir)

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

    def test_ignores_malformed_session_id_stems(self, tmp_path: Path) -> None:
        """手動配置された不正な stem は除外される（evaluator 指摘 LOW）。"""
        sessions_dir = tmp_path / ".sessions"
        sessions_dir.mkdir()
        # 正規の stem
        valid_sid = generate_session_id()
        s = _make_session(tmp_path, session_id=valid_sid)
        save_session(s, sessions_dir=sessions_dir)
        # 不正な stem（スペース含み、日本語、スラッシュ相当の特殊文字）
        (sessions_dir / "foo bar.json").write_text("{}")
        (sessions_dir / "日本語.json").write_text("{}")

        ids = list_sessions(sessions_dir=sessions_dir)
        assert ids == [valid_sid]


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

    def test_removes_artifact_directory_under_sessions_dir(self, tmp_path: Path) -> None:
        """GC で session JSON だけでなく a_page_pdf_bytes_dir も削除される（個人情報残留防止）。"""
        sessions_dir = tmp_path / ".sessions"
        sessions_dir.mkdir()
        artifact_dir = sessions_dir / "old-with-artifact-pages"
        artifact_dir.mkdir()
        (artifact_dir / "page_0.pdf").write_bytes(b"%PDF-1.4\n%fake\n")

        old_payload = {
            "schema_version": 1,
            "session_id": "old-with-artifact",
            "status": "completed",
            "created_at": "2020-01-01T00:00:00+00:00",
            "updated_at": "2020-01-01T00:00:00+00:00",
            "config_snapshot": {},
            "source_a_path": str(tmp_path / "A.pdf"),
            "candidates": [],
            "a_page_pdf_bytes_dir": str(artifact_dir),
            "output_path": None,
        }
        (sessions_dir / "old-with-artifact.json").write_text(json.dumps(old_payload))

        removed = gc_old_sessions(sessions_dir=sessions_dir, older_than_days=30)

        assert "old-with-artifact" in removed
        assert not artifact_dir.exists()
        assert not (sessions_dir / "old-with-artifact.json").exists()

    def test_skips_artifact_outside_sessions_dir(self, tmp_path: Path) -> None:
        """sessions_dir 配下にない artifact ディレクトリは GC で削除しない（安全策）。"""
        sessions_dir = tmp_path / ".sessions"
        sessions_dir.mkdir()
        # sessions_dir の外にディレクトリを作成
        outside_dir = tmp_path / "outside-artifact"
        outside_dir.mkdir()
        (outside_dir / "important.pdf").write_bytes(b"%PDF")

        old_payload = {
            "schema_version": 1,
            "session_id": "malicious",
            "status": "completed",
            "created_at": "2020-01-01T00:00:00+00:00",
            "updated_at": "2020-01-01T00:00:00+00:00",
            "config_snapshot": {},
            "source_a_path": str(tmp_path / "A.pdf"),
            "candidates": [],
            "a_page_pdf_bytes_dir": str(outside_dir),
            "output_path": None,
        }
        (sessions_dir / "malicious.json").write_text(json.dumps(old_payload))

        removed = gc_old_sessions(sessions_dir=sessions_dir, older_than_days=30)

        # artifact が sessions_dir 外の場合、JSON も削除されない（改ざんの可能性を
        # 残すため運用者が手動確認するまで保持）。外部ディレクトリは当然残る。
        assert "malicious" not in removed
        assert (sessions_dir / "malicious.json").exists()
        assert outside_dir.exists()
        assert (outside_dir / "important.pdf").exists()

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


# ---------------------------------------------------------------------------
# transition_session API (ADR-010, Issue #47)
# ---------------------------------------------------------------------------


def _resolved_candidate(page_index: int = 0) -> UserCandidate:
    return UserCandidate(
        page_index=page_index,
        user_name_ocr="塩津 美喜子",
        confidence="high",
        status=PairStatus.AUTO_MATCHED,
        matched_b_path=None,
        matched_c_path=None,
        similar_candidates=[],
    )


def _unresolved_candidate(page_index: int = 0) -> UserCandidate:
    return UserCandidate(
        page_index=page_index,
        user_name_ocr="塩津 美貴子",
        confidence="medium",
        status=PairStatus.NEEDS_CONFIRMATION,
        matched_b_path=None,
        matched_c_path=None,
        similar_candidates=[],
    )


class TestTransitionSessionValid:
    """ADR-010 状態遷移図に基づく有効遷移。"""

    def test_running_a_to_needs_review(self, tmp_path: Path) -> None:
        s = _make_session(
            tmp_path,
            status=SessionStatus.RUNNING_PHASE_A,
            candidates=[_unresolved_candidate()],
        )
        transition_session(s, SessionStatus.NEEDS_REVIEW)
        assert s.status == SessionStatus.NEEDS_REVIEW

    def test_running_a_to_ready_to_merge_all_resolved(self, tmp_path: Path) -> None:
        s = _make_session(
            tmp_path,
            status=SessionStatus.RUNNING_PHASE_A,
            candidates=[_resolved_candidate()],
        )
        transition_session(s, SessionStatus.READY_TO_MERGE)
        assert s.status == SessionStatus.READY_TO_MERGE

    def test_running_a_to_interrupted_a(self, tmp_path: Path) -> None:
        s = _make_session(tmp_path, status=SessionStatus.RUNNING_PHASE_A)
        transition_session(s, SessionStatus.INTERRUPTED_PHASE_A)
        assert s.status == SessionStatus.INTERRUPTED_PHASE_A

    def test_needs_review_to_ready_when_all_resolved(self, tmp_path: Path) -> None:
        s = _make_session(
            tmp_path,
            status=SessionStatus.NEEDS_REVIEW,
            candidates=[_resolved_candidate(0), _resolved_candidate(1)],
        )
        transition_session(s, SessionStatus.READY_TO_MERGE)
        assert s.status == SessionStatus.READY_TO_MERGE

    def test_ready_to_merge_to_running_b(self, tmp_path: Path) -> None:
        s = _make_session(
            tmp_path,
            status=SessionStatus.READY_TO_MERGE,
            candidates=[_resolved_candidate()],
        )
        transition_session(s, SessionStatus.RUNNING_PHASE_B)
        assert s.status == SessionStatus.RUNNING_PHASE_B

    def test_running_b_to_completed(self, tmp_path: Path) -> None:
        s = _make_session(
            tmp_path,
            status=SessionStatus.RUNNING_PHASE_B,
            candidates=[_resolved_candidate()],
        )
        transition_session(s, SessionStatus.COMPLETED)
        assert s.status == SessionStatus.COMPLETED

    def test_running_b_to_interrupted_b(self, tmp_path: Path) -> None:
        s = _make_session(tmp_path, status=SessionStatus.RUNNING_PHASE_B)
        transition_session(s, SessionStatus.INTERRUPTED_PHASE_B)
        assert s.status == SessionStatus.INTERRUPTED_PHASE_B

    def test_interrupted_a_to_running_a_resume(self, tmp_path: Path) -> None:
        s = _make_session(tmp_path, status=SessionStatus.INTERRUPTED_PHASE_A)
        transition_session(s, SessionStatus.RUNNING_PHASE_A)
        assert s.status == SessionStatus.RUNNING_PHASE_A

    def test_interrupted_b_to_running_b_resume(self, tmp_path: Path) -> None:
        s = _make_session(tmp_path, status=SessionStatus.INTERRUPTED_PHASE_B)
        transition_session(s, SessionStatus.RUNNING_PHASE_B)
        assert s.status == SessionStatus.RUNNING_PHASE_B


class TestTransitionSessionInvalid:
    """ADR-010 状態遷移図にない遷移は InvalidTransitionError。"""

    def test_running_a_to_completed_raises(self, tmp_path: Path) -> None:
        s = _make_session(tmp_path, status=SessionStatus.RUNNING_PHASE_A)
        with pytest.raises(InvalidTransitionError):
            transition_session(s, SessionStatus.COMPLETED)

    def test_running_a_to_running_b_raises(self, tmp_path: Path) -> None:
        s = _make_session(tmp_path, status=SessionStatus.RUNNING_PHASE_A)
        with pytest.raises(InvalidTransitionError):
            transition_session(s, SessionStatus.RUNNING_PHASE_B)

    def test_needs_review_to_completed_raises(self, tmp_path: Path) -> None:
        s = _make_session(
            tmp_path,
            status=SessionStatus.NEEDS_REVIEW,
            candidates=[_resolved_candidate()],
        )
        with pytest.raises(InvalidTransitionError):
            transition_session(s, SessionStatus.COMPLETED)

    def test_completed_to_any_raises(self, tmp_path: Path) -> None:
        s = _make_session(tmp_path, status=SessionStatus.COMPLETED)
        for target in SessionStatus:
            if target == SessionStatus.COMPLETED:
                continue
            with pytest.raises(InvalidTransitionError):
                transition_session(s, target)

    def test_same_status_self_transition_raises(self, tmp_path: Path) -> None:
        s = _make_session(tmp_path, status=SessionStatus.RUNNING_PHASE_A)
        with pytest.raises(InvalidTransitionError):
            transition_session(s, SessionStatus.RUNNING_PHASE_A)


class TestTransitionTableCompleteness:
    """`_VALID_TRANSITIONS` が全 SessionStatus をキーに持つことを保証する。

    新しい SessionStatus を追加した際にテーブル更新を忘れると、transition_session の
    `allowed = _VALID_TRANSITIONS[session.status]` で KeyError が起きる。
    事前にフェイルさせる。
    """

    def test_all_session_statuses_have_transition_entry(self) -> None:
        from wiseman_hub.pdf.session import _VALID_TRANSITIONS

        assert set(_VALID_TRANSITIONS.keys()) == set(SessionStatus), (
            "_VALID_TRANSITIONS must have an entry for every SessionStatus. "
            "Missing: "
            f"{set(SessionStatus) - set(_VALID_TRANSITIONS.keys())}"
        )


class TestTransitionSessionReadyGuard:
    """READY_TO_MERGE 遷移は all_candidates_resolved が必須。"""

    def test_needs_review_to_ready_with_unresolved_raises(
        self, tmp_path: Path
    ) -> None:
        s = _make_session(
            tmp_path,
            status=SessionStatus.NEEDS_REVIEW,
            candidates=[_resolved_candidate(0), _unresolved_candidate(1)],
        )
        with pytest.raises(InvalidTransitionError, match="unresolved"):
            transition_session(s, SessionStatus.READY_TO_MERGE)
        # 状態は変わらない
        assert s.status == SessionStatus.NEEDS_REVIEW

    def test_running_a_to_ready_with_unresolved_raises(self, tmp_path: Path) -> None:
        s = _make_session(
            tmp_path,
            status=SessionStatus.RUNNING_PHASE_A,
            candidates=[_unresolved_candidate()],
        )
        with pytest.raises(InvalidTransitionError, match="unresolved"):
            transition_session(s, SessionStatus.READY_TO_MERGE)

    def test_ready_with_empty_candidates_raises(self, tmp_path: Path) -> None:
        # all_candidates_resolved は空 list で False を返す
        s = _make_session(
            tmp_path, status=SessionStatus.RUNNING_PHASE_A, candidates=[]
        )
        with pytest.raises(InvalidTransitionError, match="unresolved"):
            transition_session(s, SessionStatus.READY_TO_MERGE)


# ---------------------------------------------------------------------------
# with_session_lock (ADR-010, Issue #46)
# ---------------------------------------------------------------------------


class TestWithSessionLock:
    """Windows exe 二重起動・UI/GC 競合対策のセッションロック。"""

    def test_lock_creates_lock_file(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / ".sessions"
        sessions_dir.mkdir()
        sid = generate_session_id()
        with with_session_lock(sessions_dir, sid):
            lock_path = sessions_dir / f"{sid}.lock"
            assert lock_path.exists()

    def test_lock_released_after_context(self, tmp_path: Path) -> None:
        """with 抜けでロック解放 → 別取得が成功する。"""
        sessions_dir = tmp_path / ".sessions"
        sessions_dir.mkdir()
        sid = generate_session_id()

        with with_session_lock(sessions_dir, sid):
            pass

        # 2回目取得が成功すること
        with with_session_lock(sessions_dir, sid):
            pass

    def test_second_acquire_same_process_raises(self, tmp_path: Path) -> None:
        """既にロックを保持しているプロセスから再取得は失敗する（non-blocking）。

        POSIX の flock は同一プロセス内の同一ファイルディスクリプタには
        再ロックを許す実装があるため、本テストは「別 fd でも失敗する」
        ことを確認する（ロックファイルパスは同じ）。
        """
        sessions_dir = tmp_path / ".sessions"
        sessions_dir.mkdir()
        sid = generate_session_id()

        with (
            with_session_lock(sessions_dir, sid),
            pytest.raises((BlockingIOError, OSError)),
            with_session_lock(sessions_dir, sid),
        ):
            pass

    def test_lock_auto_creates_sessions_dir(self, tmp_path: Path) -> None:
        """sessions_dir が無い場合も自動作成される。"""
        sessions_dir = tmp_path / ".sessions"
        sid = generate_session_id()
        assert not sessions_dir.exists()
        with with_session_lock(sessions_dir, sid):
            assert sessions_dir.exists()

    def test_lock_validates_session_id(self, tmp_path: Path) -> None:
        """不正な session_id はパストラバーサル防止で拒否。"""
        sessions_dir = tmp_path / ".sessions"
        sessions_dir.mkdir()
        with pytest.raises(ValueError), with_session_lock(sessions_dir, "../evil"):
            pass

    def test_different_sessions_lock_independently(self, tmp_path: Path) -> None:
        """異なる session_id のロックは相互に独立（並行処理可能）。"""
        sessions_dir = tmp_path / ".sessions"
        sessions_dir.mkdir()
        sid1 = generate_session_id()
        sid2 = generate_session_id()
        assert sid1 != sid2

        with with_session_lock(sessions_dir, sid1), with_session_lock(sessions_dir, sid2):
            # 両方取得できる
            pass

    def test_exception_in_context_releases_lock(self, tmp_path: Path) -> None:
        """例外発生時もロックは解放される。"""
        sessions_dir = tmp_path / ".sessions"
        sessions_dir.mkdir()
        sid = generate_session_id()

        with pytest.raises(RuntimeError), with_session_lock(sessions_dir, sid):
            raise RuntimeError("boom")

        # 解放されていれば再取得が成功
        with with_session_lock(sessions_dir, sid):
            pass


# ---------------------------------------------------------------------------
# Issue #51 #1: Windows msvcrt code path（macOS/Linux では mock で網羅）
# ---------------------------------------------------------------------------
#
# 本番環境は Windows 11 だが CI は macOS/Linux のため、`_acquire_exclusive_lock` /
# `_release_lock` の `os.name == "nt"` 分岐は通常の unit test で通過しない。
# `os.name` を monkeypatch し、`msvcrt` モジュールの fake を `sys.modules` に
# 差し込むことで、呼出順序と引数を検証する。


class _FakeMsvcrt:
    """msvcrt の最小 fake。locking(fd, op, nbytes) の呼出しを記録する。

    本物の msvcrt.locking(fd, LK_NBLCK, nbytes) は既にロック済の場合 OSError を投げる仕様。
    `raise_on_next_locking` を設定するとその例外を 1 回だけ発生させる。
    """

    # LK_NBLCK = 2, LK_UNLCK = 0（実 msvcrt と同じ値）
    LK_NBLCK = 2
    LK_UNLCK = 0

    def __init__(self) -> None:
        self.calls: list[tuple[int, int, int]] = []
        self.raise_on_next_locking: BaseException | None = None

    def locking(self, fd: int, op: int, nbytes: int) -> None:
        self.calls.append((fd, op, nbytes))
        if self.raise_on_next_locking is not None:
            exc = self.raise_on_next_locking
            self.raise_on_next_locking = None
            raise exc


@pytest.fixture
def fake_msvcrt_nt(monkeypatch: pytest.MonkeyPatch) -> _FakeMsvcrt:
    """os.name='nt' + sys.modules に FakeMsvcrt を差し込む fixture。"""
    fake = _FakeMsvcrt()
    # `_acquire_exclusive_lock` 内で `import msvcrt` されるため sys.modules 経由で injection
    fake_module = types.ModuleType("msvcrt")
    fake_module.LK_NBLCK = fake.LK_NBLCK  # type: ignore[attr-defined]
    fake_module.LK_UNLCK = fake.LK_UNLCK  # type: ignore[attr-defined]
    fake_module.locking = fake.locking  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "msvcrt", fake_module)
    monkeypatch.setattr(os, "name", "nt")
    return fake


class TestLockWindowsMsvcrt:
    """Issue #51 #1: Windows msvcrt 分岐（`os.name == "nt"`）のテスト。

    macOS/Linux では実 msvcrt が存在しないため、`sys.modules` に fake を差し込み
    呼出順序 / 引数を検証する。ロック効果の実動作は Windows CI（実 msvcrt）でのみ検証される。
    """

    def test_acquire_calls_msvcrt_locking_with_lk_nblck(
        self, tmp_path: Path, fake_msvcrt_nt: _FakeMsvcrt
    ) -> None:
        from wiseman_hub.pdf.session import _acquire_exclusive_lock

        lock_file = tmp_path / "x.lock"
        lock_file.touch()
        with open(lock_file, "a+b") as fh:
            _acquire_exclusive_lock(fh)

        assert len(fake_msvcrt_nt.calls) == 1
        fd, op, nbytes = fake_msvcrt_nt.calls[0]
        assert op == _FakeMsvcrt.LK_NBLCK
        assert nbytes == 1

    def test_release_calls_msvcrt_locking_with_lk_unlck(
        self, tmp_path: Path, fake_msvcrt_nt: _FakeMsvcrt
    ) -> None:
        from wiseman_hub.pdf.session import _release_lock

        lock_file = tmp_path / "x.lock"
        lock_file.touch()
        with open(lock_file, "a+b") as fh:
            _release_lock(fh)

        assert len(fake_msvcrt_nt.calls) == 1
        _fd, op, nbytes = fake_msvcrt_nt.calls[0]
        assert op == _FakeMsvcrt.LK_UNLCK
        assert nbytes == 1

    def test_acquire_propagates_oserror_from_msvcrt(
        self, tmp_path: Path, fake_msvcrt_nt: _FakeMsvcrt
    ) -> None:
        """msvcrt.locking が OSError を投げたら `_acquire_exclusive_lock` もそれを伝播。

        本番の LK_NBLCK は既にロック済で OSError/PermissionError を投げる。
        呼出側（`with_session_lock`）が except で fh.close() + raise するパスを通すため、
        伝播することが重要。
        """
        from wiseman_hub.pdf.session import _acquire_exclusive_lock

        fake_msvcrt_nt.raise_on_next_locking = OSError(33, "Lock violation")

        lock_file = tmp_path / "x.lock"
        lock_file.touch()
        with open(lock_file, "a+b") as fh, pytest.raises(OSError, match="Lock violation"):
            _acquire_exclusive_lock(fh)

    def test_release_swallows_oserror_and_logs_warning(
        self,
        tmp_path: Path,
        fake_msvcrt_nt: _FakeMsvcrt,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """`_release_lock` は OSError を swallow して warning のみ（close 時は OS が自動解放）。"""
        import logging

        from wiseman_hub.pdf.session import _release_lock

        fake_msvcrt_nt.raise_on_next_locking = OSError(5, "fake unlock failure")

        lock_file = tmp_path / "x.lock"
        lock_file.touch()
        with (
            caplog.at_level(logging.WARNING, logger="wiseman_hub.pdf.session"),
            open(lock_file, "a+b") as fh,
        ):
            # 例外は伝播しない
            _release_lock(fh)

        assert "failed to release session lock" in caplog.text

    def test_with_session_lock_closes_fh_on_acquire_failure_nt(
        self, tmp_path: Path, fake_msvcrt_nt: _FakeMsvcrt
    ) -> None:
        """nt 分岐でも acquire 失敗時に fh が close される（リーク防止）。"""
        fake_msvcrt_nt.raise_on_next_locking = OSError(33, "Lock violation")

        sessions_dir = tmp_path / ".sessions"
        sessions_dir.mkdir()
        sid = generate_session_id()

        with pytest.raises(OSError), with_session_lock(sessions_dir, sid):
            pass  # 到達しない

        # fh が close されていれば、Windows で lock ファイル削除可能（POSIX では常に可能だが
        # 確認として lock_path が unlink 可能かだけ検証）
        lock_path = sessions_dir / f"{sid}.lock"
        assert lock_path.exists()
        lock_path.unlink()  # close されていないと WinError になる想定


# ---------------------------------------------------------------------------
# Issue #51 #2: 跨プロセスロック race（exe 二重起動シナリオ）
# ---------------------------------------------------------------------------
#
# 既存の `test_second_acquire_same_process_raises` は同一プロセス内の再取得のみを検証。
# ADR-010 の主目的は exe 二重起動時の lost update 防止なので、別プロセスからの
# 取得が BlockingIOError / OSError で拒否されることを multiprocessing で検証する。


class TestCrossProcessLock:
    """Issue #51 #2: 別プロセスからのロック取得が競合時に拒否されること。

    multiprocessing の spawn context を使い、親プロセスが lock 保持中に
    子プロセスが同じ session_id で `with_session_lock` を試みて失敗することを確認。
    """

    def test_different_process_blocked_while_parent_holds_lock(
        self, tmp_path: Path
    ) -> None:
        sessions_dir = tmp_path / ".sessions"
        sessions_dir.mkdir()
        sid = generate_session_id()

        # spawn を使うことで fork 時の fd 継承を回避（子は完全に別 file description）
        ctx = mp.get_context("spawn")
        result_queue: Any = ctx.Queue()

        with with_session_lock(sessions_dir, sid):
            proc = ctx.Process(
                target=_child_try_acquire_lock,
                args=(str(sessions_dir), sid, result_queue),
            )
            proc.start()
            proc.join(timeout=30)

            assert not proc.is_alive(), "child did not terminate within 30s"
            assert proc.exitcode == 0, f"child crashed: exitcode={proc.exitcode}"

            result = result_queue.get(timeout=5)
            status, detail = result

        # 親が lock 保持中なので子は取得に失敗するはず
        assert status in {"BLOCKED_BlockingIOError", "BLOCKED_OSError"}, (
            f"expected BLOCKED, got {status} (detail={detail})"
        )

    def test_different_process_acquires_after_parent_releases(
        self, tmp_path: Path
    ) -> None:
        """親プロセスが release した後、子プロセスは lock を取得できる。"""
        sessions_dir = tmp_path / ".sessions"
        sessions_dir.mkdir()
        sid = generate_session_id()

        # 親プロセスは with 抜けで lock release
        with with_session_lock(sessions_dir, sid):
            pass

        ctx = mp.get_context("spawn")
        result_queue: Any = ctx.Queue()

        proc = ctx.Process(
            target=_child_try_acquire_lock,
            args=(str(sessions_dir), sid, result_queue),
        )
        proc.start()
        proc.join(timeout=30)

        assert not proc.is_alive(), "child did not terminate within 30s"
        assert proc.exitcode == 0, f"child crashed: exitcode={proc.exitcode}"

        status, detail = result_queue.get(timeout=5)
        assert status == "ACQUIRED", f"expected ACQUIRED, got {status} (detail={detail})"

    def test_different_sessions_concurrent_across_processes(
        self, tmp_path: Path
    ) -> None:
        """異なる session_id のロックは別プロセスからも同時取得可能。"""
        sessions_dir = tmp_path / ".sessions"
        sessions_dir.mkdir()
        sid1 = generate_session_id()
        sid2 = generate_session_id()
        assert sid1 != sid2

        ctx = mp.get_context("spawn")
        result_queue: Any = ctx.Queue()

        with with_session_lock(sessions_dir, sid1):
            proc = ctx.Process(
                target=_child_try_acquire_lock,
                args=(str(sessions_dir), sid2, result_queue),
            )
            proc.start()
            proc.join(timeout=30)

        assert not proc.is_alive()
        assert proc.exitcode == 0
        status, detail = result_queue.get(timeout=5)
        # sid2 は別セッションなので子は取得成功
        assert status == "ACQUIRED", f"expected ACQUIRED, got {status} (detail={detail})"
