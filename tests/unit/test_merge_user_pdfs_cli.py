"""scripts/merge_user_pdfs.py CLI のユニットテスト（Issue #36）。

本番の OcrClient / KanjiMatcher はそれぞれ設定必須なので、CLI の main() は
factory 関数を注入できる形にして、テストではモックを差し込む。
"""

from __future__ import annotations

# 本番では scripts.merge_user_pdfs だが、pythonpath=src なので scripts は別扱い。
# conftest.py の sys.path で scripts も拾えるようにする必要がある。
# ここでは importlib で明示的にロードする。
import importlib.util
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import fitz
import pytest

from wiseman_hub.config import AppConfig, OcrBackendConfig, PdfMergeConfig, UserNameBBox
from wiseman_hub.pdf.matcher import MatchResult, MatchStatus
from wiseman_hub.pdf.ocr_client import ExtractNameResult
from wiseman_hub.pdf.session import (
    PairStatus,
    Session,
    SessionStatus,
    generate_session_id,
    list_sessions,
    save_session,
)

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "merge_user_pdfs.py"
)


def _load_script_module() -> Any:
    """scripts/merge_user_pdfs.py を動的にロードする。"""
    spec = importlib.util.spec_from_file_location(
        "_merge_user_pdfs_cli", _SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_merge_user_pdfs_cli"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Fixtures
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


class FakeOcr:
    def __init__(self, results: list[ExtractNameResult]) -> None:
        self._results = list(results)
        self.calls = 0

    def extract_name(
        self, image_png: bytes, *, include_raw_text: bool = False
    ) -> ExtractNameResult:
        r = self._results[self.calls]
        self.calls += 1
        return r


class FakeMatcher:
    def __init__(self, mapping: dict[str, MatchResult]) -> None:
        self._mapping = mapping

    def match(self, user_name: str) -> MatchResult:
        return self._mapping[user_name]


def _make_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        pdf_merge=PdfMergeConfig(
            input_dir=tmp_path,
            output_dir=tmp_path / "out",
            source_a_filename="A.pdf",
            source_d_filename="",
            source_b_pattern="B_{name}.pdf",
            source_c_pattern="C_{name}.pdf",
            concat_order=("A", "B", "C"),
            user_name_bbox=UserNameBBox(x0=40.0, y0=40.0, x1=200.0, y1=80.0, dpi=100),
        ),
        ocr_backend=OcrBackendConfig(
            endpoint_url="https://example.invalid",
            api_key="dummy",
            timeout_sec=10,
            max_retries=1,
        ),
    )


def _write_a_pdf(tmp_path: Path, num_pages: int = 2) -> Path:
    p = tmp_path / "A.pdf"
    p.write_bytes(_make_pdf(num_pages))
    return p


def _sessions_dir(tmp_path: Path) -> Path:
    return tmp_path / "out" / ".sessions"


# ---------------------------------------------------------------------------
# AC-P8: --list-sessions
# ---------------------------------------------------------------------------


class TestListSessionsCommand:
    def test_list_empty_prints_no_sessions(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        script = _load_script_module()
        cfg = _make_config(tmp_path)

        exit_code = script.main(
            ["--list-sessions"],
            config_loader=lambda _: cfg,
            ocr_factory=lambda _: FakeOcr([]),
            matcher_factory=lambda _: FakeMatcher({}),
        )
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "(no sessions)" in captured.out

    def test_list_shows_existing_session_ids(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        script = _load_script_module()
        cfg = _make_config(tmp_path)
        sdir = _sessions_dir(tmp_path)

        # session を 2 つ作成
        for _ in range(2):
            s = Session(
                session_id=generate_session_id(),
                status=SessionStatus.COMPLETED,
                created_at=datetime.now(UTC).isoformat(),
                updated_at=datetime.now(UTC).isoformat(),
                config_snapshot={},
                source_a_path="",
                candidates=(),
                a_page_pdf_bytes_dir=str(sdir / "pages"),
                output_path=None,
            )
            save_session(s, sessions_dir=sdir)

        exit_code = script.main(
            ["--list-sessions"],
            config_loader=lambda _: cfg,
            ocr_factory=lambda _: FakeOcr([]),
            matcher_factory=lambda _: FakeMatcher({}),
        )
        assert exit_code == 0
        out = capsys.readouterr().out
        for sid in list_sessions(sessions_dir=sdir):
            assert sid in out
        # Issue #50: 集計行の表示
        assert "2 sessions total: 2 healthy, 0 corrupted" in out

    def test_list_shows_summary_with_corrupted_sessions(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Issue #50: 破損セッション混在時、集計行で healthy/corrupted 内訳を明示。

        運用者が「何件壊れているか」「PII 残留リスクがある session_id はどれか」を
        1 目で把握できる。
        """
        import json

        script = _load_script_module()
        cfg = _make_config(tmp_path)
        sdir = _sessions_dir(tmp_path)
        sdir.mkdir(parents=True, exist_ok=True)

        # healthy session 1 件
        healthy = Session(
            session_id=generate_session_id(),
            status=SessionStatus.COMPLETED,
            created_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
            config_snapshot={},
            source_a_path="",
            candidates=(),
            a_page_pdf_bytes_dir=str(sdir / "pages"),
            output_path=None,
        )
        save_session(healthy, sessions_dir=sdir)

        # corrupted session 2 件（JSON 直書きで不正な payload を仕込む）
        corrupted_sid_1 = "20260101T000000Z-dead0001"
        corrupted_sid_2 = "20260101T000000Z-dead0002"
        (sdir / f"{corrupted_sid_1}.json").write_text("not a valid json {{{")
        (sdir / f"{corrupted_sid_2}.json").write_text(
            json.dumps({"schema_version": 9999})  # wrong schema
        )

        exit_code = script.main(
            ["--list-sessions"],
            config_loader=lambda _: cfg,
            ocr_factory=lambda _: FakeOcr([]),
            matcher_factory=lambda _: FakeMatcher({}),
        )
        assert exit_code == 0
        out = capsys.readouterr().out

        # 各 session_id が表示される
        assert healthy.session_id in out
        assert corrupted_sid_1 in out
        assert corrupted_sid_2 in out
        # corrupted マーカ（例外型名含む形式）
        assert "<corrupted: SessionCorruptedError>" in out
        # 集計行が末尾に出力される（将来の print 追加で順序が崩れても検知）
        last_line = out.rstrip().splitlines()[-1]
        assert last_line == "3 sessions total: 1 healthy, 2 corrupted"

    def test_list_shows_summary_when_all_corrupted(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Issue #50: healthy=0 境界値。全 corrupted でも集計行が 0 healthy で出る。"""
        script = _load_script_module()
        cfg = _make_config(tmp_path)
        sdir = _sessions_dir(tmp_path)
        sdir.mkdir(parents=True, exist_ok=True)

        (sdir / "20260101T000000Z-dead0001.json").write_text("not a valid json {{{")
        (sdir / "20260101T000000Z-dead0002.json").write_text("also broken")

        exit_code = script.main(
            ["--list-sessions"],
            config_loader=lambda _: cfg,
            ocr_factory=lambda _: FakeOcr([]),
            matcher_factory=lambda _: FakeMatcher({}),
        )
        assert exit_code == 0
        out = capsys.readouterr().out
        last_line = out.rstrip().splitlines()[-1]
        assert last_line == "2 sessions total: 0 healthy, 2 corrupted"


# ---------------------------------------------------------------------------
# AC-P8b: --discard <id>
# ---------------------------------------------------------------------------


class TestDiscardCommand:
    def test_discard_removes_session_and_artifacts(self, tmp_path: Path) -> None:
        script = _load_script_module()
        cfg = _make_config(tmp_path)
        sdir = _sessions_dir(tmp_path)

        sid = generate_session_id()
        artifact_dir = sdir / f"{sid}-pages"
        artifact_dir.mkdir(parents=True)
        (artifact_dir / "page_000.pdf").write_bytes(b"x")

        s = Session(
            session_id=sid,
            status=SessionStatus.INTERRUPTED_PHASE_A,
            created_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
            config_snapshot={},
            source_a_path="",
            candidates=(),
            a_page_pdf_bytes_dir=str(artifact_dir),
            output_path=None,
        )
        save_session(s, sessions_dir=sdir)

        assert (sdir / f"{sid}.json").exists()

        exit_code = script.main(
            ["--discard", sid],
            config_loader=lambda _: cfg,
            ocr_factory=lambda _: FakeOcr([]),
            matcher_factory=lambda _: FakeMatcher({}),
        )
        assert exit_code == 0
        assert not (sdir / f"{sid}.json").exists()
        assert not artifact_dir.exists()

    def test_discard_nonexistent_session_exits_nonzero(
        self, tmp_path: Path
    ) -> None:
        script = _load_script_module()
        cfg = _make_config(tmp_path)
        exit_code = script.main(
            ["--discard", "20260101T000000Z-abcd"],
            config_loader=lambda _: cfg,
            ocr_factory=lambda _: FakeOcr([]),
            matcher_factory=lambda _: FakeMatcher({}),
        )
        assert exit_code != 0

    def test_discard_validates_session_id_format(self, tmp_path: Path) -> None:
        script = _load_script_module()
        cfg = _make_config(tmp_path)
        exit_code = script.main(
            ["--discard", "../evil"],
            config_loader=lambda _: cfg,
            ocr_factory=lambda _: FakeOcr([]),
            matcher_factory=lambda _: FakeMatcher({}),
        )
        assert exit_code != 0

    def test_discard_refuses_while_session_locked(self, tmp_path: Path) -> None:
        """ADR-010: resume / Phase A 実行中の session は discard できない
        （evaluator 指摘 MEDIUM）。"""
        from wiseman_hub.pdf.session import with_session_lock

        script = _load_script_module()
        cfg = _make_config(tmp_path)
        sdir = _sessions_dir(tmp_path)

        sid = generate_session_id()
        artifact_dir = sdir / f"{sid}-pages"
        artifact_dir.mkdir(parents=True)
        s = Session(
            session_id=sid,
            status=SessionStatus.INTERRUPTED_PHASE_A,
            created_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
            config_snapshot={},
            source_a_path="",
            candidates=(),
            a_page_pdf_bytes_dir=str(artifact_dir),
            output_path=None,
        )
        save_session(s, sessions_dir=sdir)

        # 別プロセス相当: ロックを保持しながら discard を呼ぶ
        with with_session_lock(sdir, sid):
            exit_code = script.main(
                ["--discard", sid],
                config_loader=lambda _: cfg,
                ocr_factory=lambda _: FakeOcr([]),
                matcher_factory=lambda _: FakeMatcher({}),
            )

        assert exit_code != 0
        # session は削除されず残っている
        assert (sdir / f"{sid}.json").exists()
        assert artifact_dir.exists()


# ---------------------------------------------------------------------------
# AC-P8c: 新規セッション実行
# ---------------------------------------------------------------------------


class TestNewRunCommand:
    def test_new_run_creates_session(self, tmp_path: Path) -> None:
        script = _load_script_module()
        cfg = _make_config(tmp_path)
        _write_a_pdf(tmp_path, num_pages=1)

        def _match_auto() -> MatchResult:
            return MatchResult(
                status=MatchStatus.AUTO_MATCHED,
                matched_b_path=None,
                matched_c_path=None,
                similar_candidates=(),
            )

        exit_code = script.main(
            [],
            config_loader=lambda _: cfg,
            ocr_factory=lambda _: FakeOcr(
                [ExtractNameResult(name="田中太郎", confidence="high")]
            ),
            matcher_factory=lambda _: FakeMatcher({"田中太郎": _match_auto()}),
        )
        assert exit_code == 0
        sdir = _sessions_dir(tmp_path)
        sids = list_sessions(sessions_dir=sdir)
        assert len(sids) == 1

    def test_missing_source_a_exits_nonzero(self, tmp_path: Path) -> None:
        script = _load_script_module()
        cfg = _make_config(tmp_path)
        # A.pdf を作らない
        exit_code = script.main(
            [],
            config_loader=lambda _: cfg,
            ocr_factory=lambda _: FakeOcr([]),
            matcher_factory=lambda _: FakeMatcher({}),
        )
        assert exit_code != 0


# ---------------------------------------------------------------------------
# AC-P8: --resume <id>
# ---------------------------------------------------------------------------


class TestResumeCommand:
    def test_resume_continues_from_interrupted(self, tmp_path: Path) -> None:
        script = _load_script_module()
        cfg = _make_config(tmp_path)
        _write_a_pdf(tmp_path, num_pages=2)

        # INTERRUPTED セッションを事前作成（1 ページ目処理済み）
        from wiseman_hub.pdf.session import PairStatus, UserCandidate

        sid = generate_session_id()
        sdir = _sessions_dir(tmp_path)
        artifact_dir = sdir / f"{sid}-pages"
        artifact_dir.mkdir(parents=True)

        pre = Session(
            session_id=sid,
            status=SessionStatus.INTERRUPTED_PHASE_A,
            created_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
            config_snapshot={},
            source_a_path=str(tmp_path / "A.pdf"),
            candidates=(
                UserCandidate(
                    page_index=0,
                    user_name_ocr="既処理",
                    confidence="high",
                    status=PairStatus.AUTO_MATCHED,
                    matched_b_path=None,
                    matched_c_path=None,
                    similar_candidates=(),
                ),
            ),
            a_page_pdf_bytes_dir=str(artifact_dir),
            output_path=None,
        )
        save_session(pre, sessions_dir=sdir)

        def _match_auto() -> MatchResult:
            return MatchResult(
                status=MatchStatus.AUTO_MATCHED,
                matched_b_path=None,
                matched_c_path=None,
                similar_candidates=(),
            )

        exit_code = script.main(
            ["--resume", sid],
            config_loader=lambda _: cfg,
            ocr_factory=lambda _: FakeOcr(
                [ExtractNameResult(name="次ユーザ", confidence="high")]
            ),
            matcher_factory=lambda _: FakeMatcher({"次ユーザ": _match_auto()}),
        )
        assert exit_code == 0

        from wiseman_hub.pdf.session import load_session

        final = load_session(sid, sessions_dir=sdir)
        assert final.status == SessionStatus.READY_TO_MERGE
        assert len(final.candidates) == 2


# ---------------------------------------------------------------------------
# タスク 8C PR #B: --review / --merge
# ---------------------------------------------------------------------------


def _single_page_pdf_bytes(label: str) -> bytes:
    doc = fitz.open()
    try:
        page = doc.new_page(width=595.0, height=842.0)
        page.insert_text((50, 50), label, fontsize=12)
        return bytes(doc.tobytes())
    finally:
        doc.close()


def _make_session_with_candidates(
    *,
    tmp_path: Path,
    status: SessionStatus,
    candidates: list[Any],
) -> str:
    """テスト用: 指定 status + candidates の session を作って session_id を返す。"""
    sid = generate_session_id()
    sdir = _sessions_dir(tmp_path)
    artifact_dir = sdir / f"{sid}-pages"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    # 各 candidate の page_*.pdf を用意（run_phase_b が読むため）
    for c in candidates:
        (artifact_dir / f"page_{c.page_index:03d}.pdf").write_bytes(
            _single_page_pdf_bytes(f"A:{c.user_name_ocr or c.page_index}")
        )

    s = Session(
        session_id=sid,
        status=status,
        created_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
        config_snapshot={},
        source_a_path=str(tmp_path / "A.pdf"),
        candidates=candidates,
        a_page_pdf_bytes_dir=str(artifact_dir),
        output_path=None,
        total_pages_a=len(candidates),
    )
    save_session(s, sessions_dir=sdir)
    return sid


class FakeDialog:
    """ConfirmDialog の DI 用スタブ。run() が返す結果を side_effect で制御。"""

    def __init__(
        self,
        session: Session,
        sessions_dir: Path,
        *,
        resolver: Any,
        aborted: bool = False,
    ) -> None:
        self._session = session
        self._sessions_dir = sessions_dir
        self._resolver = resolver
        self._aborted = aborted
        self.ran = False

    def run(self) -> Any:
        """resolver で新 session を得て save してから結果を返す（Issue #44 immutable）。"""
        from wiseman_hub.pdf.session import save_session as _save
        from wiseman_hub.ui.confirm_dialog import ConfirmDialogResult

        self.ran = True
        if self._resolver is not None:
            self._session = self._resolver(self._session)
            self._session = _save(self._session, sessions_dir=self._sessions_dir)
        return ConfirmDialogResult(session=self._session, aborted=self._aborted)


def _resolve_all_auto(session: Session) -> Session:
    """全候補を AUTO_MATCHED 相当に解決したリゾルバ（承認操作のスタブ）の新 Session を返す。"""
    from wiseman_hub.pdf.session import PairStatus

    return replace(
        session,
        candidates=tuple(
            replace(c, status=PairStatus.CONFIRMED, similar_candidates=())
            for c in session.candidates
        ),
    )


class TestReviewCommand:
    """AC-CLI-R1〜R3: --review サブコマンド。"""

    def test_review_resolves_and_transitions_to_ready(self, tmp_path: Path) -> None:
        from wiseman_hub.pdf.session import PairStatus, UserCandidate, load_session

        script = _load_script_module()
        cfg = _make_config(tmp_path)
        sid = _make_session_with_candidates(
            tmp_path=tmp_path,
            status=SessionStatus.NEEDS_REVIEW,
            candidates=(
                UserCandidate(
                    page_index=0,
                    user_name_ocr="u0",
                    confidence="medium",
                    status=PairStatus.NEEDS_CONFIRMATION,
                    matched_b_path=None,
                    matched_c_path=None,
                    similar_candidates=(),
                ),
            ),
        )

        dialog_factory = lambda s, d: FakeDialog(  # noqa: E731
            s, d, resolver=_resolve_all_auto
        )
        exit_code = script.main(
            ["--review", sid],
            config_loader=lambda _: cfg,
            ocr_factory=lambda _: FakeOcr([]),
            matcher_factory=lambda _: FakeMatcher({}),
            dialog_factory=dialog_factory,
        )
        assert exit_code == 0
        final = load_session(sid, sessions_dir=_sessions_dir(tmp_path))
        assert final.status == SessionStatus.READY_TO_MERGE

    def test_review_aborted_leaves_status_unchanged(self, tmp_path: Path) -> None:
        """aborted=True の場合、呼出側契約どおり session は変更しない。

        EXIT_ERROR (=1) と EXIT_NEEDS_REVIEW (=3) は意味が異なる（aborted は「UI 異常終了
        のため再実行が必要」、unresolved は「ユーザーが未解決のまま閉じた」）ので等値検証する。
        """
        from wiseman_hub.pdf.session import PairStatus, UserCandidate, load_session

        script = _load_script_module()
        cfg = _make_config(tmp_path)
        sid = _make_session_with_candidates(
            tmp_path=tmp_path,
            status=SessionStatus.NEEDS_REVIEW,
            candidates=(
                UserCandidate(
                    page_index=0,
                    user_name_ocr="u0",
                    confidence="medium",
                    status=PairStatus.NEEDS_CONFIRMATION,
                    matched_b_path=None,
                    matched_c_path=None,
                    similar_candidates=(),
                ),
            ),
        )

        dialog_factory = lambda s, d: FakeDialog(s, d, resolver=None, aborted=True)  # noqa: E731
        exit_code = script.main(
            ["--review", sid],
            config_loader=lambda _: cfg,
            ocr_factory=lambda _: FakeOcr([]),
            matcher_factory=lambda _: FakeMatcher({}),
            dialog_factory=dialog_factory,
        )
        assert exit_code == script.EXIT_ERROR
        final = load_session(sid, sessions_dir=_sessions_dir(tmp_path))
        assert final.status == SessionStatus.NEEDS_REVIEW  # 変更されていない

    def test_review_already_ready_is_idempotent(self, tmp_path: Path) -> None:
        """READY_TO_MERGE で --review を呼んでも冪等に成功（UI 起動しない）。"""
        from wiseman_hub.pdf.session import PairStatus, UserCandidate, load_session

        script = _load_script_module()
        cfg = _make_config(tmp_path)
        sid = _make_session_with_candidates(
            tmp_path=tmp_path,
            status=SessionStatus.READY_TO_MERGE,
            candidates=(
                UserCandidate(
                    page_index=0,
                    user_name_ocr="u0",
                    confidence="high",
                    status=PairStatus.AUTO_MATCHED,
                    matched_b_path=None,
                    matched_c_path=None,
                    similar_candidates=(),
                ),
            ),
        )

        called = {"dialog": 0}

        def dialog_factory(s: Any, d: Any) -> Any:
            called["dialog"] += 1
            return FakeDialog(s, d, resolver=_resolve_all_auto)

        exit_code = script.main(
            ["--review", sid],
            config_loader=lambda _: cfg,
            ocr_factory=lambda _: FakeOcr([]),
            matcher_factory=lambda _: FakeMatcher({}),
            dialog_factory=dialog_factory,
        )
        assert exit_code == 0
        assert called["dialog"] == 0  # UI は起動されていない
        final = load_session(sid, sessions_dir=_sessions_dir(tmp_path))
        assert final.status == SessionStatus.READY_TO_MERGE

    def test_review_unresolved_remainder_exits_needs_review(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """UI 終了時に未解決が残っていれば EXIT_NEEDS_REVIEW。"""
        from wiseman_hub.pdf.session import PairStatus, UserCandidate, load_session

        script = _load_script_module()
        cfg = _make_config(tmp_path)
        sid = _make_session_with_candidates(
            tmp_path=tmp_path,
            status=SessionStatus.NEEDS_REVIEW,
            candidates=(
                UserCandidate(
                    page_index=0,
                    user_name_ocr="u0",
                    confidence="medium",
                    status=PairStatus.NEEDS_CONFIRMATION,
                    matched_b_path=None,
                    matched_c_path=None,
                    similar_candidates=(),
                ),
            ),
        )

        # resolver を呼ばないので未解決のまま「閉じる」経路
        dialog_factory = lambda s, d: FakeDialog(s, d, resolver=None)  # noqa: E731
        exit_code = script.main(
            ["--review", sid],
            config_loader=lambda _: cfg,
            ocr_factory=lambda _: FakeOcr([]),
            matcher_factory=lambda _: FakeMatcher({}),
            dialog_factory=dialog_factory,
        )
        assert exit_code == script.EXIT_NEEDS_REVIEW
        final = load_session(sid, sessions_dir=_sessions_dir(tmp_path))
        assert final.status == SessionStatus.NEEDS_REVIEW
        # code-reviewer 指摘: 未解決候補数が stderr に含まれる既存メッセージ契約を検証
        captured = capsys.readouterr()
        assert "1 candidate(s) still unresolved" in captured.err

    def _make_session_for_race_test(self, tmp_path: Path) -> str:
        """race catch テストで共用するセッション fixture。"""
        from wiseman_hub.pdf.session import PairStatus, UserCandidate

        return _make_session_with_candidates(
            tmp_path=tmp_path,
            status=SessionStatus.NEEDS_REVIEW,
            candidates=(
                UserCandidate(
                    page_index=0,
                    user_name_ocr="u0",
                    confidence="medium",
                    status=PairStatus.NEEDS_CONFIRMATION,
                    matched_b_path=None,
                    matched_c_path=None,
                    similar_candidates=(),
                ),
            ),
        )

    def _run_review_with_resolve_raising(
        self,
        tmp_path: Path,
        sid: str,
        exc: Exception,
    ) -> tuple[int, Any]:
        """resolve_review_session が ``exc`` を raise する状況で --review を実行する。

        patch 対象は ``wiseman_hub.pdf.review_flow.resolve_review_session``（文字列パス）。
        `_cmd_review` が関数内で lazy import するため、モジュール属性側を差し替える
        必要がある。patch 有効性を保証するため ``mock_resolve.assert_called_once()``
        を呼出側テストで行う。
        """
        from unittest import mock as _mock

        script = _load_script_module()
        cfg = _make_config(tmp_path)

        mock_resolve = _mock.MagicMock(side_effect=exc)
        dialog_factory = lambda s, d: FakeDialog(s, d, resolver=None)  # noqa: E731
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "wiseman_hub.pdf.review_flow.resolve_review_session",
                mock_resolve,
            )
            exit_code = script.main(
                ["--review", sid],
                config_loader=lambda _: cfg,
                ocr_factory=lambda _: FakeOcr([]),
                matcher_factory=lambda _: FakeMatcher({}),
                dialog_factory=dialog_factory,
            )
        return exit_code, mock_resolve

    def test_review_race_session_not_found_exits_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """evaluator 指摘: pre-load 成功後〜1st lock 取得前に他プロセスが
        --discard した race で SessionNotFoundError が resolve 内で raise される。

        _cmd_review は catch して EXIT_ERROR + 既存メッセージ形式に揃える
        （型名だけ露出してアプリ全体終了する状態を回避する）。"""
        from wiseman_hub.pdf.session import SessionNotFoundError

        sid = self._make_session_for_race_test(tmp_path)
        exit_code, mock_resolve = self._run_review_with_resolve_raising(
            tmp_path, sid, SessionNotFoundError(f"session {sid} not found")
        )

        script = _load_script_module()
        assert exit_code == script.EXIT_ERROR
        mock_resolve.assert_called_once()  # patch 有効性を保証
        captured = capsys.readouterr()
        assert "error:" in captured.err
        assert sid in captured.err

    def test_review_race_session_corrupted_exits_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """SessionCorruptedError も同じ catch 経路で EXIT_ERROR を返すことを検証
        （evaluator 指摘: 2 例外のうち片方しかテストしていなかった）。"""
        from wiseman_hub.pdf.session import SessionCorruptedError

        sid = self._make_session_for_race_test(tmp_path)
        exit_code, mock_resolve = self._run_review_with_resolve_raising(
            tmp_path, sid, SessionCorruptedError("simulated JSON corruption")
        )

        script = _load_script_module()
        assert exit_code == script.EXIT_ERROR
        mock_resolve.assert_called_once()
        captured = capsys.readouterr()
        assert "error:" in captured.err


class TestMergeCommand:
    """AC-CLI-M1〜M2: --merge サブコマンド。"""

    def test_merge_from_ready_produces_pdf_and_completes(self, tmp_path: Path) -> None:
        from wiseman_hub.pdf.session import PairStatus, UserCandidate, load_session

        script = _load_script_module()
        cfg = _make_config(tmp_path)
        (tmp_path / "B_u0.pdf").write_bytes(_single_page_pdf_bytes("B:u0"))
        (tmp_path / "C_u0.pdf").write_bytes(_single_page_pdf_bytes("C:u0"))

        sid = _make_session_with_candidates(
            tmp_path=tmp_path,
            status=SessionStatus.READY_TO_MERGE,
            candidates=(
                UserCandidate(
                    page_index=0,
                    user_name_ocr="u0",
                    confidence="high",
                    status=PairStatus.AUTO_MATCHED,
                    matched_b_path=None,
                    matched_c_path=None,
                    similar_candidates=(),
                ),
            ),
        )

        exit_code = script.main(
            ["--merge", sid],
            config_loader=lambda _: cfg,
            ocr_factory=lambda _: FakeOcr([]),
            matcher_factory=lambda _: FakeMatcher({}),
        )
        assert exit_code == 0

        final = load_session(sid, sessions_dir=_sessions_dir(tmp_path))
        assert final.status == SessionStatus.COMPLETED
        assert final.output_path is not None
        assert Path(final.output_path).exists()

    def test_merge_error_stderr_does_not_leak_pii(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """run_phase_b 失敗時、stderr の error メッセージに氏名・path が含まれないこと。

        医療介護分野の PII 防御（confirm_dialog.py の方針に準拠）。
        merger 由来の PdfMergeError は message に user_name や path を含みうるため、
        CLI 層で型名 + session_id に抑え込む必要がある。
        """
        from wiseman_hub.pdf.session import UserCandidate

        pii_name = "山田太郎"
        pii_path = "/Users/secret_path/confidential_file.pdf"

        script = _load_script_module()
        cfg = _make_config(tmp_path)
        sid = _make_session_with_candidates(
            tmp_path=tmp_path,
            status=SessionStatus.READY_TO_MERGE,
            candidates=(
                UserCandidate(
                    page_index=0,
                    user_name_ocr=pii_name,
                    confidence="high",
                    status=PairStatus.AUTO_MATCHED,
                    matched_b_path=None,
                    matched_c_path=None,
                    similar_candidates=(),
                ),
            ),
        )

        def leaky_merge(*args: object, **kwargs: object) -> None:
            # 本番 merger は _validate_user_name や _open_pdf_file_or_raise で
            # このような PII を含む message を出しうる
            from wiseman_hub.pdf.merger import PdfMergeError

            raise PdfMergeError(
                f"Failed to open PDF for B:{pii_name}: {pii_path}: bad file"
            )

        monkeypatch.setattr("wiseman_hub.pdf.pipeline.merge_user_pdfs", leaky_merge)

        exit_code = script.main(
            ["--merge", sid],
            config_loader=lambda _: cfg,
            ocr_factory=lambda _: FakeOcr([]),
            matcher_factory=lambda _: FakeMatcher({}),
        )
        assert exit_code == script.EXIT_ERROR

        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert pii_name not in combined, "PII (氏名) leaked in CLI output"
        assert pii_path not in combined, "PII (path) leaked in CLI output"
        # 最低限 session_id と型名は出すべき
        assert sid in combined
        assert "PdfMergeError" in combined

    @pytest.mark.parametrize(
        "invalid_status,invalid_pair",
        [
            (SessionStatus.NEEDS_REVIEW, PairStatus.NEEDS_CONFIRMATION),
            (SessionStatus.RUNNING_PHASE_A, PairStatus.AUTO_MATCHED),
            (SessionStatus.COMPLETED, PairStatus.AUTO_MATCHED),
            (SessionStatus.INTERRUPTED_PHASE_A, PairStatus.AUTO_MATCHED),
        ],
    )
    def test_merge_rejects_invalid_status(
        self,
        tmp_path: Path,
        invalid_status: SessionStatus,
        invalid_pair: Any,
    ) -> None:
        """READY_TO_MERGE / INTERRUPTED_PHASE_B 以外は全て EXIT_ERROR。

        argparse で弾けない異常状態（手動で session JSON を作った等）を CLI 層で防ぐ。
        """
        from wiseman_hub.pdf.session import UserCandidate

        script = _load_script_module()
        cfg = _make_config(tmp_path)
        sid = _make_session_with_candidates(
            tmp_path=tmp_path,
            status=invalid_status,
            candidates=(
                UserCandidate(
                    page_index=0,
                    user_name_ocr="u0",
                    confidence="high",
                    status=invalid_pair,
                    matched_b_path=None,
                    matched_c_path=None,
                    similar_candidates=(),
                ),
            ),
        )

        exit_code = script.main(
            ["--merge", sid],
            config_loader=lambda _: cfg,
            ocr_factory=lambda _: FakeOcr([]),
            matcher_factory=lambda _: FakeMatcher({}),
        )
        assert exit_code == script.EXIT_ERROR
