"""pipeline.run_phase_a のユニットテスト（Issue #36）。

OCR クライアントと matcher は Protocol で差し替えてモック化する。
splitter は実装のまま使い、fitz で in-memory PDF を生成する。
"""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from wiseman_hub.config import (
    PdfMergeConfig,
    UserNameBBox,
)
from wiseman_hub.pdf.matcher import (
    MatchResult,
    MatchStatus,
)
from wiseman_hub.pdf.ocr_client import ExtractNameResult
from wiseman_hub.pdf.pipeline import run_phase_a, run_phase_b
from wiseman_hub.pdf.session import (
    InvalidTransitionError,
    PairStatus,
    Session,
    SessionStatus,
    UserCandidate,
    list_sessions,
    load_session,
    save_session,
)

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_pdf(num_pages: int) -> bytes:
    doc = fitz.open()
    try:
        for i in range(num_pages):
            page = doc.new_page(width=595.0, height=842.0)
            page.insert_text((50, 50), f"Page {i + 1}", fontsize=12)
        return bytes(doc.tobytes())
    finally:
        doc.close()


def _make_pdf_file(tmp_path: Path, name: str, num_pages: int) -> Path:
    path = tmp_path / name
    path.write_bytes(_make_pdf(num_pages))
    return path


def _bbox() -> UserNameBBox:
    return UserNameBBox(x0=40.0, y0=40.0, x1=200.0, y1=80.0, dpi=100)


def _config(tmp_path: Path) -> PdfMergeConfig:
    return PdfMergeConfig(
        input_dir=str(tmp_path),
        output_dir=str(tmp_path / "out"),
        source_a_filename="A.pdf",
        source_d_filename="",
        source_b_pattern="B_{name}.pdf",
        source_c_pattern="C_{name}.pdf",
        concat_order=["A", "B", "C"],
        user_name_bbox=_bbox(),
    )


class FakeOcrClient:
    """OcrClient のテスト差し替え用。extract_name の戻り値を side_effects で制御。"""

    def __init__(self, results: list[ExtractNameResult | BaseException]) -> None:
        self._results = list(results)
        self.calls = 0

    def extract_name(
        self, image_png: bytes, *, include_raw_text: bool = False
    ) -> ExtractNameResult:
        if self.calls >= len(self._results):
            raise AssertionError(
                f"FakeOcrClient: unexpected extra call #{self.calls + 1} "
                f"(only {len(self._results)} results configured)"
            )
        result = self._results[self.calls]
        self.calls += 1
        if isinstance(result, BaseException):
            raise result
        return result


class FakeMatcher:
    """NameMatcher のテスト差し替え。name → MatchResult マップで制御。"""

    def __init__(self, mapping: dict[str, MatchResult]) -> None:
        self._mapping = mapping
        self.calls: list[str] = []

    def match(self, user_name: str) -> MatchResult:
        self.calls.append(user_name)
        return self._mapping[user_name]


def _ocr_high(name: str) -> ExtractNameResult:
    return ExtractNameResult(name=name, confidence="high")


def _ocr_low(name: str) -> ExtractNameResult:
    return ExtractNameResult(name=name, confidence="low")


def _ocr_medium(name: str) -> ExtractNameResult:
    return ExtractNameResult(name=name, confidence="medium")


def _match_auto(b: Path | None = None, c: Path | None = None) -> MatchResult:
    return MatchResult(
        status=MatchStatus.AUTO_MATCHED,
        matched_b_path=b,
        matched_c_path=c,
        similar_candidates=(),
    )


def _match_no() -> MatchResult:
    return MatchResult(
        status=MatchStatus.NO_MATCH,
        matched_b_path=None,
        matched_c_path=None,
        similar_candidates=(),
    )


# ---------------------------------------------------------------------------
# AC-P1: 正常系 - 3名分の A を split→OCR→match → session JSON 生成
# ---------------------------------------------------------------------------


class TestRunPhaseAHappyPath:
    def test_creates_session_with_three_candidates(self, tmp_path: Path) -> None:
        a_pdf = _make_pdf_file(tmp_path, "A.pdf", num_pages=3)
        sessions_dir = tmp_path / ".sessions"

        # 各ページ用意
        b_paths = [tmp_path / f"B_ユーザ{i}.pdf" for i in range(3)]
        c_paths = [tmp_path / f"C_ユーザ{i}.pdf" for i in range(3)]
        for p in b_paths + c_paths:
            p.write_bytes(b"dummy")

        ocr = FakeOcrClient(
            [_ocr_high("ユーザ0"), _ocr_high("ユーザ1"), _ocr_high("ユーザ2")]
        )
        matcher = FakeMatcher(
            {
                "ユーザ0": _match_auto(b_paths[0], c_paths[0]),
                "ユーザ1": _match_auto(b_paths[1], c_paths[1]),
                "ユーザ2": _match_auto(b_paths[2], c_paths[2]),
            }
        )

        session = run_phase_a(
            source_a_path=a_pdf,
            config=_config(tmp_path),
            ocr_client=ocr,
            matcher=matcher,
            sessions_dir=sessions_dir,
        )

        assert session.status == SessionStatus.READY_TO_MERGE
        assert len(session.candidates) == 3
        assert session.total_pages_a == 3
        assert ocr.calls == 3
        assert matcher.calls == ["ユーザ0", "ユーザ1", "ユーザ2"]

        # session JSON が永続化されている
        assert session.session_id in list_sessions(sessions_dir=sessions_dir)

    def test_session_transitions_to_needs_review_on_mixed_results(
        self, tmp_path: Path
    ) -> None:
        a_pdf = _make_pdf_file(tmp_path, "A.pdf", num_pages=2)
        sessions_dir = tmp_path / ".sessions"

        ocr = FakeOcrClient([_ocr_high("ユーザA"), _ocr_high("ユーザB")])
        matcher = FakeMatcher(
            {
                "ユーザA": _match_auto(),
                "ユーザB": _match_no(),  # resolved 扱い？ → NO_MATCH は unresolved
            }
        )

        session = run_phase_a(
            source_a_path=a_pdf,
            config=_config(tmp_path),
            ocr_client=ocr,
            matcher=matcher,
            sessions_dir=sessions_dir,
        )

        assert session.status == SessionStatus.NEEDS_REVIEW
        statuses = [c.status for c in session.candidates]
        assert statuses == [PairStatus.AUTO_MATCHED, PairStatus.NO_MATCH]


# ---------------------------------------------------------------------------
# AC-P1b: a_page_pdf_bytes_dir に page_NNN.pdf を永続化
# ---------------------------------------------------------------------------


class TestPagePdfPersistence:
    def test_page_pdfs_saved_to_artifact_dir(self, tmp_path: Path) -> None:
        a_pdf = _make_pdf_file(tmp_path, "A.pdf", num_pages=3)
        sessions_dir = tmp_path / ".sessions"

        ocr = FakeOcrClient(
            [_ocr_high("u0"), _ocr_high("u1"), _ocr_high("u2")]
        )
        matcher = FakeMatcher(
            {"u0": _match_auto(), "u1": _match_auto(), "u2": _match_auto()}
        )

        session = run_phase_a(
            source_a_path=a_pdf,
            config=_config(tmp_path),
            ocr_client=ocr,
            matcher=matcher,
            sessions_dir=sessions_dir,
        )

        artifact_dir = Path(session.a_page_pdf_bytes_dir)
        assert artifact_dir.exists()
        page_files = sorted(artifact_dir.glob("page_*.pdf"))
        assert len(page_files) == 3
        assert page_files[0].name == "page_000.pdf"
        assert page_files[2].name == "page_002.pdf"
        # AC-P1b: total_pages_a とディスク上の page_*.pdf 数が一致する。
        # 片方だけ regress しても検知できるよう、同一アサーションで比較する。
        assert session.total_pages_a == len(page_files)
        # 各ファイルが非空の PDF
        for pf in page_files:
            assert pf.stat().st_size > 0


# ---------------------------------------------------------------------------
# AC-P2: confidence=low は強制 NEEDS_CONFIRMATION
# ---------------------------------------------------------------------------


class TestConfidenceLow:
    def test_low_confidence_forces_needs_confirmation(
        self, tmp_path: Path
    ) -> None:
        a_pdf = _make_pdf_file(tmp_path, "A.pdf", num_pages=1)
        sessions_dir = tmp_path / ".sessions"

        # matcher は auto_matched を返すが、confidence=low なので強制昇格
        ocr = FakeOcrClient([_ocr_low("ユーザX")])
        matcher = FakeMatcher({"ユーザX": _match_auto()})

        session = run_phase_a(
            source_a_path=a_pdf,
            config=_config(tmp_path),
            ocr_client=ocr,
            matcher=matcher,
            sessions_dir=sessions_dir,
        )

        assert len(session.candidates) == 1
        assert session.candidates[0].status == PairStatus.NEEDS_CONFIRMATION
        assert session.status == SessionStatus.NEEDS_REVIEW


# ---------------------------------------------------------------------------
# AC-P3: name=None（OCR 読取不能）→ NO_MATCH（matcher 呼ばない）
# ---------------------------------------------------------------------------


class TestOcrNameNone:
    def test_none_name_bypasses_matcher_and_sets_no_match(
        self, tmp_path: Path
    ) -> None:
        a_pdf = _make_pdf_file(tmp_path, "A.pdf", num_pages=1)
        sessions_dir = tmp_path / ".sessions"

        ocr = FakeOcrClient(
            [ExtractNameResult(name=None, confidence="low")]
        )
        matcher = FakeMatcher({})  # 呼ばれないはず

        session = run_phase_a(
            source_a_path=a_pdf,
            config=_config(tmp_path),
            ocr_client=ocr,
            matcher=matcher,
            sessions_dir=sessions_dir,
        )

        assert session.status == SessionStatus.NEEDS_REVIEW
        assert len(session.candidates) == 1
        assert session.candidates[0].status == PairStatus.NO_MATCH
        assert session.candidates[0].user_name_ocr == ""
        assert matcher.calls == []


# ---------------------------------------------------------------------------
# AC-P4: KeyboardInterrupt → INTERRUPTED_PHASE_A、処理済み candidates 保存
# ---------------------------------------------------------------------------


class TestInterruption:
    def test_keyboard_interrupt_saves_interrupted_state(
        self, tmp_path: Path
    ) -> None:
        a_pdf = _make_pdf_file(tmp_path, "A.pdf", num_pages=3)
        sessions_dir = tmp_path / ".sessions"

        ocr = FakeOcrClient(
            [_ocr_high("u0"), KeyboardInterrupt(), _ocr_high("u2")]
        )
        matcher = FakeMatcher(
            {"u0": _match_auto(), "u2": _match_auto()}
        )

        with pytest.raises(KeyboardInterrupt):
            run_phase_a(
                source_a_path=a_pdf,
                config=_config(tmp_path),
                ocr_client=ocr,
                matcher=matcher,
                sessions_dir=sessions_dir,
            )

        # session が保存されており INTERRUPTED_PHASE_A
        sids = list_sessions(sessions_dir=sessions_dir)
        assert len(sids) == 1
        session = load_session(sids[0], sessions_dir=sessions_dir)
        assert session.status == SessionStatus.INTERRUPTED_PHASE_A
        assert len(session.candidates) == 1
        assert session.candidates[0].page_index == 0
        # page_000.pdf は保存されている（次の OCR 失敗ページ分は無い可能性あり）
        artifact_dir = Path(session.a_page_pdf_bytes_dir)
        assert (artifact_dir / "page_000.pdf").exists()

    def test_resume_after_interruption_completes(self, tmp_path: Path) -> None:
        a_pdf = _make_pdf_file(tmp_path, "A.pdf", num_pages=3)
        sessions_dir = tmp_path / ".sessions"

        # 1 回目: 2 ページ目で中断
        ocr1 = FakeOcrClient(
            [_ocr_high("u0"), KeyboardInterrupt(), _ocr_high("u2")]
        )
        matcher1 = FakeMatcher({"u0": _match_auto(), "u2": _match_auto()})
        with pytest.raises(KeyboardInterrupt):
            run_phase_a(
                source_a_path=a_pdf,
                config=_config(tmp_path),
                ocr_client=ocr1,
                matcher=matcher1,
                sessions_dir=sessions_dir,
            )
        sid = list_sessions(sessions_dir=sessions_dir)[0]
        interrupted = load_session(sid, sessions_dir=sessions_dir)
        assert interrupted.status == SessionStatus.INTERRUPTED_PHASE_A

        # 2 回目: 残り 2 ページを処理（page 1, page 2）
        ocr2 = FakeOcrClient([_ocr_high("u1"), _ocr_high("u2")])
        matcher2 = FakeMatcher(
            {"u1": _match_auto(), "u2": _match_auto()}
        )
        resumed = run_phase_a(
            source_a_path=a_pdf,
            config=_config(tmp_path),
            ocr_client=ocr2,
            matcher=matcher2,
            sessions_dir=sessions_dir,
            session=interrupted,
        )
        assert resumed.status == SessionStatus.READY_TO_MERGE
        assert len(resumed.candidates) == 3
        # ページ順は保証される
        assert [c.page_index for c in resumed.candidates] == [0, 1, 2]

    def test_resume_rejects_modified_source_a(self, tmp_path: Path) -> None:
        """Codex HIGH-3: source A が差し替えられたら resume 拒否。"""
        from wiseman_hub.pdf.pipeline import SourceAFingerprintMismatchError

        # 1 回目: 2 ページ中 1 ページ目で中断
        a_pdf = _make_pdf_file(tmp_path, "A.pdf", num_pages=2)
        sessions_dir = tmp_path / ".sessions"

        ocr1 = FakeOcrClient([_ocr_high("u0"), KeyboardInterrupt()])
        matcher1 = FakeMatcher({"u0": _match_auto()})
        with pytest.raises(KeyboardInterrupt):
            run_phase_a(
                source_a_path=a_pdf,
                config=_config(tmp_path),
                ocr_client=ocr1,
                matcher=matcher1,
                sessions_dir=sessions_dir,
            )
        sid = list_sessions(sessions_dir=sessions_dir)[0]
        interrupted = load_session(sid, sessions_dir=sessions_dir)

        # A.pdf を別内容で上書き
        a_pdf.write_bytes(_make_pdf(num_pages=2))  # 同ページ数でも content 違うので SHA 変化

        with pytest.raises(SourceAFingerprintMismatchError, match="source A has changed"):
            run_phase_a(
                source_a_path=a_pdf,
                config=_config(tmp_path),
                ocr_client=FakeOcrClient([]),
                matcher=FakeMatcher({}),
                sessions_dir=sessions_dir,
                session=interrupted,
            )

    def test_resume_accepts_unchanged_source_a(self, tmp_path: Path) -> None:
        """同一の A.pdf であれば resume 成功（fingerprint 一致）。"""
        a_pdf = _make_pdf_file(tmp_path, "A.pdf", num_pages=2)
        sessions_dir = tmp_path / ".sessions"

        ocr1 = FakeOcrClient([KeyboardInterrupt()])
        matcher1 = FakeMatcher({})
        with pytest.raises(KeyboardInterrupt):
            run_phase_a(
                source_a_path=a_pdf,
                config=_config(tmp_path),
                ocr_client=ocr1,
                matcher=matcher1,
                sessions_dir=sessions_dir,
            )
        sid = list_sessions(sessions_dir=sessions_dir)[0]
        interrupted = load_session(sid, sessions_dir=sessions_dir)

        # A.pdf を一切変更せず resume
        ocr2 = FakeOcrClient([_ocr_high("u0"), _ocr_high("u1")])
        matcher2 = FakeMatcher(
            {"u0": _match_auto(), "u1": _match_auto()}
        )
        resumed = run_phase_a(
            source_a_path=a_pdf,
            config=_config(tmp_path),
            ocr_client=ocr2,
            matcher=matcher2,
            sessions_dir=sessions_dir,
            session=interrupted,
        )
        assert resumed.status == SessionStatus.READY_TO_MERGE

    def test_resume_detects_discard_race(self, tmp_path: Path) -> None:
        """Codex MEDIUM-2: lock 取得前に別プロセスが discard → SessionNotFoundError。"""
        a_pdf = _make_pdf_file(tmp_path, "A.pdf", num_pages=1)
        sessions_dir = tmp_path / ".sessions"

        # Phase A を 1 回中断させてから INTERRUPTED セッションを作る
        ocr1 = FakeOcrClient([KeyboardInterrupt()])
        matcher1 = FakeMatcher({})
        with pytest.raises(KeyboardInterrupt):
            run_phase_a(
                source_a_path=a_pdf,
                config=_config(tmp_path),
                ocr_client=ocr1,
                matcher=matcher1,
                sessions_dir=sessions_dir,
            )
        sid = list_sessions(sessions_dir=sessions_dir)[0]
        interrupted = load_session(sid, sessions_dir=sessions_dir)

        # load_session 後 run_phase_a 前に discard された状況を再現
        (sessions_dir / f"{sid}.json").unlink()

        from wiseman_hub.pdf.session import SessionNotFoundError

        with pytest.raises(SessionNotFoundError, match="removed while waiting for lock"):
            run_phase_a(
                source_a_path=a_pdf,
                config=_config(tmp_path),
                ocr_client=FakeOcrClient([_ocr_high("u0")]),
                matcher=FakeMatcher({"u0": _match_auto()}),
                sessions_dir=sessions_dir,
                session=interrupted,
            )

    def test_resume_rejects_invalid_status(self, tmp_path: Path) -> None:
        """COMPLETED 等のセッションは resume 不可。"""
        a_pdf = _make_pdf_file(tmp_path, "A.pdf", num_pages=1)
        sessions_dir = tmp_path / ".sessions"
        sessions_dir.mkdir()

        # 完了済みセッションを手動構築
        from datetime import UTC, datetime

        from wiseman_hub.pdf.session import (
            generate_session_id,
            save_session,
        )

        completed = Session(
            session_id=generate_session_id(),
            status=SessionStatus.COMPLETED,
            created_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
            config_snapshot={},
            source_a_path=str(a_pdf),
            candidates=[],
            a_page_pdf_bytes_dir=str(tmp_path / "pages"),
            output_path=None,
        )
        save_session(completed, sessions_dir=sessions_dir)

        ocr = FakeOcrClient([])
        matcher = FakeMatcher({})
        with pytest.raises(ValueError, match="cannot resume"):
            run_phase_a(
                source_a_path=a_pdf,
                config=_config(tmp_path),
                ocr_client=ocr,
                matcher=matcher,
                sessions_dir=sessions_dir,
                session=completed,
            )


# ---------------------------------------------------------------------------
# 追加: session のロック取得失敗は例外伝播（run_phase_a は内部でロック取得）
# ---------------------------------------------------------------------------


class TestLockIntegration:
    def test_run_phase_a_acquires_session_lock(self, tmp_path: Path) -> None:
        """外部で同セッションロックを保持中に run_phase_a を呼ぶと失敗する。"""
        a_pdf = _make_pdf_file(tmp_path, "A.pdf", num_pages=1)
        sessions_dir = tmp_path / ".sessions"
        sessions_dir.mkdir()

        from datetime import UTC, datetime

        from wiseman_hub.pdf.session import (
            generate_session_id,
            save_session,
            with_session_lock,
        )

        # INTERRUPTED 状態の session を作り、ロック保持のまま resume を試みる
        sid = generate_session_id()
        pre_session = Session(
            session_id=sid,
            status=SessionStatus.INTERRUPTED_PHASE_A,
            created_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
            config_snapshot={},
            source_a_path=str(a_pdf),
            candidates=[],
            a_page_pdf_bytes_dir=str(sessions_dir / f"{sid}-pages"),
            output_path=None,
        )
        save_session(pre_session, sessions_dir=sessions_dir)

        ocr = FakeOcrClient([_ocr_high("u0")])
        matcher = FakeMatcher({"u0": _match_auto()})

        with with_session_lock(sessions_dir, sid), pytest.raises((BlockingIOError, OSError)):
            run_phase_a(
                source_a_path=a_pdf,
                config=_config(tmp_path),
                ocr_client=ocr,
                matcher=matcher,
                sessions_dir=sessions_dir,
                session=pre_session,
            )


# ---------------------------------------------------------------------------
# run_phase_b テスト（タスク 8C PR #B）
# ---------------------------------------------------------------------------


def _single_page_pdf_bytes(label: str) -> bytes:
    doc = fitz.open()
    try:
        page = doc.new_page(width=595.0, height=842.0)
        page.insert_text((50, 50), label, fontsize=12)
        return bytes(doc.tobytes())
    finally:
        doc.close()


def _make_phase_b_session(
    *,
    tmp_path: Path,
    sessions_dir: Path,
    status: SessionStatus,
    candidates: list[UserCandidate],
    output_path_field: str | None = None,
) -> Session:
    """Phase B のテスト用セッションをディスクに用意する。

    各 candidate の page_{index:03d}.pdf を a_page_pdf_bytes_dir に書き出す（run_phase_b は
    file から読む契約）。
    """
    from datetime import UTC, datetime

    from wiseman_hub.pdf.session import generate_session_id

    sid = generate_session_id()
    now = datetime.now(UTC).isoformat()
    pages_dir = sessions_dir / f"{sid}-pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    for c in candidates:
        page_path = pages_dir / f"page_{c.page_index:03d}.pdf"
        page_path.write_bytes(_single_page_pdf_bytes(f"A:{c.user_name_ocr or c.page_index}"))

    session = Session(
        session_id=sid,
        status=status,
        created_at=now,
        updated_at=now,
        config_snapshot={},
        source_a_path=str(tmp_path / "A.pdf"),
        candidates=candidates,
        a_page_pdf_bytes_dir=str(pages_dir),
        output_path=output_path_field,
        total_pages_a=len(candidates),
    )
    save_session(session, sessions_dir=sessions_dir)
    return session


def _cand(
    *,
    page_index: int,
    name: str,
    status: PairStatus,
    matched_b: str | None = None,
    matched_c: str | None = None,
) -> UserCandidate:
    return UserCandidate(
        page_index=page_index,
        user_name_ocr=name,
        confidence="high",
        status=status,
        matched_b_path=matched_b,
        matched_c_path=matched_c,
        similar_candidates=[],
    )


def _page_texts(path: Path) -> list[str]:
    doc = fitz.open(path)
    try:
        return [doc[i].get_text().strip() for i in range(doc.page_count)]
    finally:
        doc.close()


class TestRunPhaseBStateGuard:
    """AC-P6: run_phase_b は READY_TO_MERGE / INTERRUPTED_PHASE_B のみ実行可。"""

    @pytest.mark.parametrize(
        "status",
        [
            SessionStatus.RUNNING_PHASE_A,
            SessionStatus.NEEDS_REVIEW,
            SessionStatus.RUNNING_PHASE_B,
            SessionStatus.COMPLETED,
            SessionStatus.INTERRUPTED_PHASE_A,
        ],
    )
    def test_rejects_non_mergeable_status(
        self, tmp_path: Path, status: SessionStatus
    ) -> None:
        sessions_dir = tmp_path / ".sessions"
        session = _make_phase_b_session(
            tmp_path=tmp_path,
            sessions_dir=sessions_dir,
            status=status,
            candidates=[_cand(page_index=0, name="u0", status=PairStatus.AUTO_MATCHED)],
        )

        with pytest.raises((InvalidTransitionError, ValueError)):
            run_phase_b(
                session=session,
                config=_config(tmp_path),
                sessions_dir=sessions_dir,
                output_path=tmp_path / "merged.pdf",
            )


class TestRunPhaseBHappyPath:
    """AC-PB-1: READY_TO_MERGE → COMPLETED, output PDF 生成。"""

    def test_merges_auto_matched_users_and_sets_completed(
        self, tmp_path: Path
    ) -> None:
        sessions_dir = tmp_path / ".sessions"
        (tmp_path / "B_u0.pdf").write_bytes(_single_page_pdf_bytes("B:u0"))
        (tmp_path / "C_u0.pdf").write_bytes(_single_page_pdf_bytes("C:u0"))
        (tmp_path / "B_u1.pdf").write_bytes(_single_page_pdf_bytes("B:u1"))
        (tmp_path / "C_u1.pdf").write_bytes(_single_page_pdf_bytes("C:u1"))
        session = _make_phase_b_session(
            tmp_path=tmp_path,
            sessions_dir=sessions_dir,
            status=SessionStatus.READY_TO_MERGE,
            candidates=[
                _cand(page_index=0, name="u0", status=PairStatus.AUTO_MATCHED),
                _cand(page_index=1, name="u1", status=PairStatus.AUTO_MATCHED),
            ],
        )

        output = tmp_path / "out" / "merged.pdf"
        result = run_phase_b(
            session=session,
            config=_config(tmp_path),
            sessions_dir=sessions_dir,
            output_path=output,
        )

        assert result.status == SessionStatus.COMPLETED
        assert result.output_path == str(output)
        assert output.exists()
        texts = _page_texts(output)
        # concat_order = [A, B, C]、D 無し
        assert texts == ["A:u0", "B:u0", "C:u0", "A:u1", "B:u1", "C:u1"]
        # ディスクの session も COMPLETED で永続化されている
        reloaded = load_session(session.session_id, sessions_dir=sessions_dir)
        assert reloaded.status == SessionStatus.COMPLETED
        assert reloaded.output_path == str(output)


class TestRunPhaseBExclusion:
    """AC-PB-3: REJECTED / SKIPPED 候補は merger 入力から除外される。"""

    def test_rejected_and_skipped_users_excluded(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / ".sessions"
        (tmp_path / "B_u0.pdf").write_bytes(_single_page_pdf_bytes("B:u0"))
        (tmp_path / "C_u0.pdf").write_bytes(_single_page_pdf_bytes("C:u0"))
        session = _make_phase_b_session(
            tmp_path=tmp_path,
            sessions_dir=sessions_dir,
            status=SessionStatus.READY_TO_MERGE,
            candidates=[
                _cand(page_index=0, name="u0", status=PairStatus.AUTO_MATCHED),
                _cand(page_index=1, name="u_rejected", status=PairStatus.REJECTED),
                _cand(page_index=2, name="u_skipped", status=PairStatus.SKIPPED),
            ],
        )

        output = tmp_path / "merged.pdf"
        run_phase_b(
            session=session,
            config=_config(tmp_path),
            sessions_dir=sessions_dir,
            output_path=output,
        )

        assert _page_texts(output) == ["A:u0", "B:u0", "C:u0"]


class TestRunPhaseBManualSelected:
    """AC-PB-4: MANUALLY_SELECTED の matched_b_path がカスタムパスの場合、そのパスを使う。"""

    def test_manually_selected_custom_path_wins_over_pattern(
        self, tmp_path: Path
    ) -> None:
        sessions_dir = tmp_path / ".sessions"
        custom = tmp_path / "elsewhere" / "any-name.pdf"
        custom.parent.mkdir()
        custom.write_bytes(_single_page_pdf_bytes("CUSTOM-B"))
        # pattern 解決されるはずの B_misread.pdf はわざと作らない（override が優先されることの証明）。
        # 日本語名は fitz デフォルトフォント (Helvetica) で描画できないため ASCII 名でテスト。
        (tmp_path / "C_misread.pdf").write_bytes(_single_page_pdf_bytes("C:misread"))

        session = _make_phase_b_session(
            tmp_path=tmp_path,
            sessions_dir=sessions_dir,
            status=SessionStatus.READY_TO_MERGE,
            candidates=[
                _cand(
                    page_index=0,
                    name="misread",
                    status=PairStatus.MANUALLY_SELECTED,
                    matched_b=str(custom),
                ),
            ],
        )

        output = tmp_path / "merged.pdf"
        run_phase_b(
            session=session,
            config=_config(tmp_path),
            sessions_dir=sessions_dir,
            output_path=output,
        )

        assert _page_texts(output) == ["A:misread", "CUSTOM-B", "C:misread"]


class TestRunPhaseBInterrupted:
    """AC-PB-2: merger 失敗時 INTERRUPTED_PHASE_B で保存 + 例外再送出。
    AC-PB-5: INTERRUPTED_PHASE_B からのリトライ。"""

    @pytest.mark.parametrize(
        "injected_exc,exc_match",
        [
            pytest.param(
                "PdfMergeError", "disk full", id="pdf_merge_error"
            ),
            pytest.param(
                "FileNotFoundError", "D source", id="file_not_found_from_merger"
            ),
        ],
    )
    def test_merger_failure_sets_interrupted_and_reraises(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        injected_exc: str,
        exc_match: str,
    ) -> None:
        sessions_dir = tmp_path / ".sessions"
        (tmp_path / "B_u0.pdf").write_bytes(_single_page_pdf_bytes("B"))
        (tmp_path / "C_u0.pdf").write_bytes(_single_page_pdf_bytes("C"))
        session = _make_phase_b_session(
            tmp_path=tmp_path,
            sessions_dir=sessions_dir,
            status=SessionStatus.READY_TO_MERGE,
            candidates=[_cand(page_index=0, name="u0", status=PairStatus.AUTO_MATCHED)],
        )

        from wiseman_hub.pdf.merger import PdfMergeError

        exc_class: type[Exception] = (
            PdfMergeError if injected_exc == "PdfMergeError" else FileNotFoundError
        )

        def failing_merge(*args: object, **kwargs: object) -> None:
            raise exc_class(f"{exc_match} simulation")

        monkeypatch.setattr("wiseman_hub.pdf.pipeline.merge_user_pdfs", failing_merge)

        with pytest.raises(exc_class, match=exc_match):
            run_phase_b(
                session=session,
                config=_config(tmp_path),
                sessions_dir=sessions_dir,
                output_path=tmp_path / "merged.pdf",
            )

        reloaded = load_session(session.session_id, sessions_dir=sessions_dir)
        assert reloaded.status == SessionStatus.INTERRUPTED_PHASE_B
        # 失敗時 output_path は設定されてはならない（成功時のみ set される契約）
        assert reloaded.output_path is None

    def test_missing_b_source_is_fatal_and_removes_output(
        self, tmp_path: Path
    ) -> None:
        """欠損 B/C があるとき、COMPLETED に進まず INTERRUPTED_PHASE_B で停止。
        既に書き出された不完全 output PDF は削除される（PII 配布事故防止）。"""
        from wiseman_hub.pdf.merger import PdfMergeError

        sessions_dir = tmp_path / ".sessions"
        # B_u0.pdf を作らない = 欠損
        (tmp_path / "C_u0.pdf").write_bytes(_single_page_pdf_bytes("C:u0"))
        session = _make_phase_b_session(
            tmp_path=tmp_path,
            sessions_dir=sessions_dir,
            status=SessionStatus.READY_TO_MERGE,
            candidates=[_cand(page_index=0, name="u0", status=PairStatus.AUTO_MATCHED)],
        )

        output = tmp_path / "merged.pdf"
        with pytest.raises(PdfMergeError, match="missing B/C"):
            run_phase_b(
                session=session,
                config=_config(tmp_path),
                sessions_dir=sessions_dir,
                output_path=output,
            )

        # 出力 PDF は削除される（残骸で運用者が誤使用する事故を防ぐ）
        assert not output.exists()
        reloaded = load_session(session.session_id, sessions_dir=sessions_dir)
        assert reloaded.status == SessionStatus.INTERRUPTED_PHASE_B
        assert reloaded.output_path is None

    def test_retry_from_interrupted_reaches_completed(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / ".sessions"
        (tmp_path / "B_u0.pdf").write_bytes(_single_page_pdf_bytes("B:u0"))
        (tmp_path / "C_u0.pdf").write_bytes(_single_page_pdf_bytes("C:u0"))
        session = _make_phase_b_session(
            tmp_path=tmp_path,
            sessions_dir=sessions_dir,
            status=SessionStatus.INTERRUPTED_PHASE_B,
            candidates=[_cand(page_index=0, name="u0", status=PairStatus.AUTO_MATCHED)],
        )

        output = tmp_path / "merged.pdf"
        result = run_phase_b(
            session=session,
            config=_config(tmp_path),
            sessions_dir=sessions_dir,
            output_path=output,
        )
        assert result.status == SessionStatus.COMPLETED
        assert output.exists()
