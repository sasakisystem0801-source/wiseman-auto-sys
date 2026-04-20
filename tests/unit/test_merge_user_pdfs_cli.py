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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import fitz
import pytest

from wiseman_hub.config import AppConfig, OcrBackendConfig, PdfMergeConfig, UserNameBBox
from wiseman_hub.pdf.matcher import MatchResult, MatchStatus
from wiseman_hub.pdf.ocr_client import ExtractNameResult
from wiseman_hub.pdf.session import (
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
    cfg = AppConfig()
    cfg.pdf_merge = PdfMergeConfig(
        input_dir=str(tmp_path),
        output_dir=str(tmp_path / "out"),
        source_a_filename="A.pdf",
        source_d_filename="",
        source_b_pattern="B_{name}.pdf",
        source_c_pattern="C_{name}.pdf",
        concat_order=["A", "B", "C"],
        user_name_bbox=UserNameBBox(x0=40.0, y0=40.0, x1=200.0, y1=80.0, dpi=100),
    )
    cfg.ocr_backend = OcrBackendConfig(
        endpoint_url="https://example.invalid",
        api_key="dummy",
        timeout_sec=10,
        max_retries=1,
    )
    return cfg


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
                candidates=[],
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
            candidates=[],
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
            candidates=[],
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
            candidates=[
                UserCandidate(
                    page_index=0,
                    user_name_ocr="既処理",
                    confidence="high",
                    status=PairStatus.AUTO_MATCHED,
                    matched_b_path=None,
                    matched_c_path=None,
                    similar_candidates=[],
                )
            ],
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
