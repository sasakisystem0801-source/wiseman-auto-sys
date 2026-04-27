"""ConfirmDialog のユニットテスト（AC-UI-1〜11）。

2 層構成:
  1. Pure logic tests (Tk 非依存): resolve_candidate / compute_approve_decision /
     log_operation / helpers — 常に実行される。
  2. UI wiring tests (Tk 必要): ConfirmDialog クラスの _on_* メソッド、
     button.invoke() — Tk ランタイムが利用可能な環境でのみ実行（uv python では skip）。

本番 Windows 11 PC では tkinter + Tcl が標準バンドルされるため UI tests も走る。
macOS 開発機（uv python）では purely logical tests のみで AC 全項目を検証する。
"""

from __future__ import annotations

import logging
import os
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest

os.environ.setdefault("TK_SILENCE_DEPRECATION", "1")

from wiseman_hub.pdf.session import (  # noqa: E402
    CandidateState,
    PairStatus,
    Session,
    SessionStatus,
    UserCandidate,
)
from wiseman_hub.ui import confirm_dialog as cd_mod  # noqa: E402
from wiseman_hub.ui.confirm_dialog import (  # noqa: E402
    ConfirmDialog,
    ConfirmDialogResult,
    _format_detail,
    _pick_first_by_kind,
    _short_path,
    compute_approve_decision,
    log_operation,
    resolve_candidate,
)

# ---------------------------------------------------------------------------
# Shared fixtures / factories
# ---------------------------------------------------------------------------


def _make_session(
    *,
    session_id: str = "20260420T001523Z-deadbeef",
    status: SessionStatus = SessionStatus.NEEDS_REVIEW,
    candidates: tuple[UserCandidate, ...] | None = None,
) -> Session:
    now = datetime.now(UTC).isoformat()
    return Session(
        session_id=session_id,
        status=status,
        created_at=now,
        updated_at=now,
        config_snapshot={"concat_order": ["A", "B", "C"]},
        source_a_path="/tmp/A.pdf",
        candidates=candidates if candidates is not None else (),
        a_page_pdf_bytes_dir="/tmp/.pages",
        output_path=None,
        total_pages_a=len(candidates) if candidates else 0,
    )


def _needs_confirmation_candidate(
    page_index: int = 1,
    name: str = "塩津 美貴子",
    with_similar: bool = True,
    matched_b_path: str | None = None,
    matched_c_path: str | None = None,
) -> UserCandidate:
    similar: tuple[CandidateState, ...] = (
        (
            CandidateState(
                path=f"/in/B_{page_index}.pdf",
                kind="B",
                distance=1,
                extracted_name="塩津 美喜子",
            ),
            CandidateState(
                path=f"/in/C_{page_index}.pdf",
                kind="C",
                distance=1,
                extracted_name="塩津 美喜子",
            ),
        )
        if with_similar
        else ()
    )
    return UserCandidate(
        page_index=page_index,
        user_name_ocr=name,
        confidence="medium",
        status=PairStatus.NEEDS_CONFIRMATION,
        matched_b_path=matched_b_path,
        matched_c_path=matched_c_path,
        similar_candidates=similar,
    )


def _no_match_candidate(page_index: int = 2, name: str = "佐藤 花子") -> UserCandidate:
    return UserCandidate(
        page_index=page_index,
        user_name_ocr=name,
        confidence="high",
        status=PairStatus.NO_MATCH,
        matched_b_path=None,
        matched_c_path=None,
        similar_candidates=(),
    )


def _auto_matched_candidate(page_index: int = 0, name: str = "山田 太郎") -> UserCandidate:
    return UserCandidate(
        page_index=page_index,
        user_name_ocr=name,
        confidence="high",
        status=PairStatus.AUTO_MATCHED,
        matched_b_path=f"/in/B_{page_index}.pdf",
        matched_c_path=f"/in/C_{page_index}.pdf",
        similar_candidates=(),
    )


# ===========================================================================
# Layer 1: Pure logic tests (Tk 不要、全環境で実行)
# ===========================================================================


# ---------------------------------------------------------------------------
# resolve_candidate: 全操作の中核
# ---------------------------------------------------------------------------


class TestResolveCandidate:
    def test_approve_updates_status_and_matched(self) -> None:
        """AC-UI-2: NEEDS_CONFIRMATION → CONFIRMED, matched_b/c が確定"""
        session = _make_session(
            candidates=(_needs_confirmation_candidate(page_index=1),)
        )
        session = resolve_candidate(
            session,
            1,
            status=PairStatus.CONFIRMED,
            matched_b="/in/B_1.pdf",
            matched_c="/in/C_1.pdf",
        )
        c = session.candidates[0]
        assert c.status == PairStatus.CONFIRMED
        assert c.matched_b_path == "/in/B_1.pdf"
        assert c.matched_c_path == "/in/C_1.pdf"

    def test_reject_from_needs_confirmation_clears_matched(self) -> None:
        """AC-UI-3: 却下 → REJECTED + matched 全 None + similar クリア"""
        # Issue #44: UserCandidate は frozen のため matched_b_path は構築時に渡す。
        cand = _needs_confirmation_candidate(page_index=1, matched_b_path="/in/B.pdf")
        session = _make_session(candidates=(cand,))
        session = resolve_candidate(
            session,
            1,
            status=PairStatus.REJECTED,
            matched_b=None,
            matched_c=None,
            clear_similar=True,
        )
        c = session.candidates[0]
        assert c.status == PairStatus.REJECTED
        assert c.matched_b_path is None
        assert c.matched_c_path is None
        assert c.similar_candidates == ()

    def test_reject_from_no_match(self) -> None:
        """AC-UI-3: NO_MATCH → REJECTED も許容"""
        session = _make_session(candidates=(_no_match_candidate(page_index=2),))
        session = resolve_candidate(
            session,
            2,
            status=PairStatus.REJECTED,
            matched_b=None,
            matched_c=None,
        )
        assert session.candidates[0].status == PairStatus.REJECTED

    def test_manual_select_stores_paths(self) -> None:
        """AC-UI-4: MANUALLY_SELECTED + 指定パス"""
        session = _make_session(candidates=(_no_match_candidate(page_index=2),))
        session = resolve_candidate(
            session,
            2,
            status=PairStatus.MANUALLY_SELECTED,
            matched_b="/manual/B.pdf",
            matched_c="/manual/C.pdf",
        )
        c = session.candidates[0]
        assert c.status == PairStatus.MANUALLY_SELECTED
        assert c.matched_b_path == "/manual/B.pdf"
        assert c.matched_c_path == "/manual/C.pdf"

    def test_manual_select_partial_only_b(self) -> None:
        """AC-UI-4: C だけ None も許容（片方キャンセル）"""
        session = _make_session(candidates=(_no_match_candidate(page_index=2),))
        session = resolve_candidate(
            session,
            2,
            status=PairStatus.MANUALLY_SELECTED,
            matched_b="/manual/B.pdf",
            matched_c=None,
        )
        c = session.candidates[0]
        assert c.matched_b_path == "/manual/B.pdf"
        assert c.matched_c_path is None

    def test_skip_clears_matched(self) -> None:
        """AC-UI-5: SKIPPED + matched 全 None"""
        # Issue #44: UserCandidate は frozen のため、matched_b_path は構築時に指定する。
        cand = _needs_confirmation_candidate(page_index=1, matched_b_path="/in/B.pdf")
        session = _make_session(candidates=(cand,))
        session = resolve_candidate(
            session,
            1,
            status=PairStatus.SKIPPED,
            matched_b=None,
            matched_c=None,
        )
        c = session.candidates[0]
        assert c.status == PairStatus.SKIPPED
        assert c.matched_b_path is None
        assert c.matched_c_path is None

    def test_non_matching_page_index_is_noop(self) -> None:
        """存在しない page_index を指定しても他 candidate は変化しない"""
        session = _make_session(
            candidates=(
                _needs_confirmation_candidate(page_index=1),
                _no_match_candidate(page_index=2),
            )
        )
        session = resolve_candidate(
            session,
            99,
            status=PairStatus.CONFIRMED,
            matched_b="/x",
            matched_c="/y",
        )
        assert session.candidates[0].status == PairStatus.NEEDS_CONFIRMATION
        assert session.candidates[1].status == PairStatus.NO_MATCH

    def test_does_not_affect_other_candidates(self) -> None:
        session = _make_session(
            candidates=(
                _auto_matched_candidate(page_index=0),
                _needs_confirmation_candidate(page_index=1),
                _no_match_candidate(page_index=2),
            )
        )
        session = resolve_candidate(
            session, 1, status=PairStatus.CONFIRMED, matched_b="/b", matched_c="/c"
        )
        assert session.candidates[0].status == PairStatus.AUTO_MATCHED
        assert session.candidates[2].status == PairStatus.NO_MATCH

    def test_returns_new_session_preserving_original(self) -> None:
        """Issue #44: resolve_candidate は新 Session を返し、元 session は不変。"""
        session = _make_session(candidates=(_needs_confirmation_candidate(page_index=1),))
        original_status = session.candidates[0].status
        result = resolve_candidate(
            session, 1, status=PairStatus.SKIPPED, matched_b=None, matched_c=None
        )
        # 新仕様: 戻り値は別インスタンス、元 session は mutation されていない。
        assert result is not session
        assert session.candidates[0].status == original_status
        assert result.candidates[0].status == PairStatus.SKIPPED

    def test_preserves_similar_by_default(self) -> None:
        """承認や手動選択時は similar を残す（監査用、却下時のみクリア）"""
        session = _make_session(candidates=(_needs_confirmation_candidate(page_index=1),))
        session = resolve_candidate(
            session,
            1,
            status=PairStatus.CONFIRMED,
            matched_b="/b",
            matched_c="/c",
            clear_similar=False,
        )
        assert len(session.candidates[0].similar_candidates) == 2


# ---------------------------------------------------------------------------
# compute_approve_decision: 承認ボタン挙動の中核
# ---------------------------------------------------------------------------


class TestComputeApproveDecision:
    def test_needs_confirmation_with_similar_returns_first_bc(self) -> None:
        cand = _needs_confirmation_candidate(page_index=1)
        result = compute_approve_decision(cand)
        assert result == ("/in/B_1.pdf", "/in/C_1.pdf")

    def test_no_similar_returns_none(self) -> None:
        """AC-UI-2: similar が空なら承認不可"""
        cand = _needs_confirmation_candidate(page_index=1, with_similar=False)
        assert compute_approve_decision(cand) is None

    def test_not_needs_confirmation_returns_none(self) -> None:
        cand = _no_match_candidate(page_index=2)
        assert compute_approve_decision(cand) is None

    def test_only_b_similar(self) -> None:
        cand = UserCandidate(
            page_index=1,
            user_name_ocr="X",
            confidence="medium",
            status=PairStatus.NEEDS_CONFIRMATION,
            matched_b_path=None,
            matched_c_path=None,
            similar_candidates=(
                CandidateState(path="/b.pdf", kind="B", distance=1, extracted_name="X"),
            ),
        )
        assert compute_approve_decision(cand) == ("/b.pdf", None)

    def test_only_c_similar(self) -> None:
        cand = UserCandidate(
            page_index=1,
            user_name_ocr="X",
            confidence="medium",
            status=PairStatus.NEEDS_CONFIRMATION,
            matched_b_path=None,
            matched_c_path=None,
            similar_candidates=(
                CandidateState(path="/c.pdf", kind="C", distance=1, extracted_name="X"),
            ),
        )
        assert compute_approve_decision(cand) == (None, "/c.pdf")

    def test_auto_matched_returns_none(self) -> None:
        assert compute_approve_decision(_auto_matched_candidate()) is None


# ---------------------------------------------------------------------------
# log_operation: PII 保護
# ---------------------------------------------------------------------------


class TestLogOperation:
    def test_no_pii_in_log(self, caplog: pytest.LogCaptureFixture) -> None:
        """AC-UI-9: user_name_ocr / matched_*_path がログに出ない"""
        cand = UserCandidate(
            page_index=7,
            user_name_ocr="塩津 美貴子",
            confidence="medium",
            status=PairStatus.NEEDS_CONFIRMATION,
            matched_b_path="/secret/Bファイル.pdf",
            matched_c_path="/secret/Cファイル.pdf",
            similar_candidates=(),
        )
        with caplog.at_level(logging.INFO, logger="wiseman_hub.ui.confirm_dialog"):
            log_operation("20260420T001523Z-abcd1234", cand, "approved")

        text = caplog.text
        assert "塩津" not in text
        assert "美貴子" not in text
        assert "Bファイル" not in text
        assert "Cファイル" not in text
        # 許可されたフィールドは含まれる
        assert "20260420T001523Z-abcd1234" in text
        assert "page_index=7" in text
        assert "op=approved" in text
        assert "confidence=" in text

    def test_all_operation_names_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """attempt / outcome 両方のログ名を検証（監査証跡完全性）"""
        cand = _needs_confirmation_candidate(page_index=1)
        ops = (
            "approved_attempt", "approved",
            "rejected_attempt", "rejected",
            "manually_selected_attempt", "manually_selected",
            "skipped_attempt", "skipped",
        )
        for op in ops:
            caplog.clear()
            with caplog.at_level(logging.INFO, logger="wiseman_hub.ui.confirm_dialog"):
                log_operation("sess-1", cand, op)
            assert f"op={op}" in caplog.text


# ---------------------------------------------------------------------------
# Open candidates filter (AC-UI-1)
# ---------------------------------------------------------------------------


class TestOpenStatuses:
    def test_filter_logic_matches_spec(self) -> None:
        """AC-UI-1 の定数: OPEN_PAIR_STATUSES = {NEEDS_CONFIRMATION, NO_MATCH}"""
        from wiseman_hub.pdf.session import OPEN_PAIR_STATUSES

        assert frozenset(
            {PairStatus.NEEDS_CONFIRMATION, PairStatus.NO_MATCH}
        ) == OPEN_PAIR_STATUSES
        # 解決済み状態は含まれない
        for resolved in (
            PairStatus.AUTO_MATCHED,
            PairStatus.CONFIRMED,
            PairStatus.REJECTED,
            PairStatus.MANUALLY_SELECTED,
            PairStatus.SKIPPED,
        ):
            assert resolved not in OPEN_PAIR_STATUSES


# ---------------------------------------------------------------------------
# all_candidates_resolved 経由でセッション終了判定を確認
# ---------------------------------------------------------------------------


class TestAllResolvedDetection:
    def test_all_resolved_after_sequential_operations(self) -> None:
        """AC-UI-8: 4 操作で全件解決 → all_candidates_resolved == True"""
        session = _make_session(
            candidates=(
                _needs_confirmation_candidate(page_index=1),
                _no_match_candidate(page_index=2),
                _needs_confirmation_candidate(page_index=3),
                _no_match_candidate(page_index=4),
            )
        )
        assert not session.all_candidates_resolved

        session = resolve_candidate(
            session, 1, status=PairStatus.CONFIRMED, matched_b="/b1", matched_c="/c1"
        )
        session = resolve_candidate(
            session, 2, status=PairStatus.REJECTED, matched_b=None, matched_c=None
        )
        session = resolve_candidate(
            session,
            3,
            status=PairStatus.MANUALLY_SELECTED,
            matched_b="/mb",
            matched_c="/mc",
        )
        session = resolve_candidate(
            session, 4, status=PairStatus.SKIPPED, matched_b=None, matched_c=None
        )

        assert session.all_candidates_resolved

    def test_partial_resolution_not_all_resolved(self) -> None:
        """AC-UI-7: 一部のみ解決 → all_candidates_resolved == False"""
        session = _make_session(
            candidates=(
                _needs_confirmation_candidate(page_index=1),
                _no_match_candidate(page_index=2),
            )
        )
        session = resolve_candidate(
            session, 1, status=PairStatus.CONFIRMED, matched_b="/b", matched_c="/c"
        )
        assert not session.all_candidates_resolved


# ---------------------------------------------------------------------------
# Helpers: _pick_first_b / _pick_first_c / _short_path / _format_detail
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_pick_first_by_kind_b(self) -> None:
        similar = [
            CandidateState(path="/c.pdf", kind="C", distance=0, extracted_name="x"),
            CandidateState(path="/b1.pdf", kind="B", distance=1, extracted_name="x"),
            CandidateState(path="/b2.pdf", kind="B", distance=2, extracted_name="x"),
        ]
        assert _pick_first_by_kind(similar, "B") == "/b1.pdf"
        assert _pick_first_by_kind(similar, "C") == "/c.pdf"

    def test_pick_first_by_kind_missing(self) -> None:
        assert _pick_first_by_kind([], "B") is None
        assert _pick_first_by_kind([], "C") is None
        only_b = [CandidateState(path="/b.pdf", kind="B", distance=0, extracted_name="x")]
        assert _pick_first_by_kind(only_b, "C") is None

    def test_short_path_variations(self) -> None:
        assert _short_path(None) == ""
        assert _short_path("") == ""
        assert _short_path("/path/to/short.pdf") == "short.pdf"
        long = "/path/to/" + "x" * 40 + ".pdf"
        assert _short_path(long).startswith("...")
        assert len(_short_path(long)) <= 30

    def test_format_detail_contains_ocr_and_similar(self) -> None:
        cand = _needs_confirmation_candidate(page_index=5)
        text = _format_detail(cand)
        assert "page_index=5" in text
        assert cand.user_name_ocr in text  # UI 内は PII OK（表示目的）
        assert "[B:" in text and "[C:" in text
        assert "d=1" in text

    def test_format_detail_no_similar(self) -> None:
        cand = _needs_confirmation_candidate(page_index=5, with_similar=False)
        text = _format_detail(cand)
        assert "similar: (なし)" in text


# ---------------------------------------------------------------------------
# ConfirmDialogResult: 返却値の immutability
# ---------------------------------------------------------------------------


class TestResult:
    def test_result_is_frozen(self) -> None:
        """session フィールドは dataclass(frozen=True) で再代入不可"""
        session = _make_session(candidates=(_needs_confirmation_candidate(),))
        r = ConfirmDialogResult(session=session)
        with pytest.raises((AttributeError, TypeError)):  # FrozenInstanceError
            r.session = _make_session()  # type: ignore[misc]

    def test_resolved_all_is_property_not_stored(self) -> None:
        """resolved_all は派生値（property）。session の状態を直接反映する（二重真実なし）。

        Issue #44: Session immutable 化により resolve_candidate は新 Session を返すため、
        旧テストの「同一 session 参照が mutation で追従」モデルは成立しない。本テストでは
        「property として session 状態を計算し、保存値ではない」ことを 2 つの
        ConfirmDialogResult で検証する。
        """
        session = _make_session(
            candidates=(_needs_confirmation_candidate(page_index=1),)
        )
        r_before = ConfirmDialogResult(session=session)
        assert r_before.resolved_all is False

        updated_session = resolve_candidate(
            session, 1, status=PairStatus.CONFIRMED, matched_b="/b", matched_c="/c"
        )
        r_after = ConfirmDialogResult(session=updated_session)
        assert r_after.resolved_all is True

        # property のため setter は存在しない
        with pytest.raises(AttributeError):
            r_before.resolved_all = False  # type: ignore[misc]

    def test_aborted_forces_resolved_all_false(self) -> None:
        """aborted=True なら候補が全解決済みでも resolved_all は False（業務事故防止）

        save 失敗で callback 例外 → mainloop 異常終了 → メモリ上は全件解決でも
        ディスクは旧状態。呼出側が READY_TO_MERGE に遷移するのを防ぐ safety net。
        """
        session = _make_session(
            candidates=(
                UserCandidate(
                    page_index=1,
                    user_name_ocr="X",
                    confidence="high",
                    status=PairStatus.CONFIRMED,  # メモリ上は解決済み
                    matched_b_path="/b",
                    matched_c_path="/c",
                    similar_candidates=(),
                ),
            )
        )
        assert session.all_candidates_resolved is True

        # 通常終了なら resolved_all=True
        ok = ConfirmDialogResult(session=session, aborted=False)
        assert ok.resolved_all is True

        # aborted=True なら resolved_all=False（安全網）
        aborted = ConfirmDialogResult(session=session, aborted=True)
        assert aborted.resolved_all is False


# ---------------------------------------------------------------------------
# Stdlib-only import check (AC-UI-11)
# ---------------------------------------------------------------------------


class TestMainThreadEnforcement:
    """Tkinter は thread-safe でないため worker thread から ConfirmDialog を構築できない。

    Tk 不要のテスト（`__init__` が thread 検証で例外を投げる地点までしか到達しない）。
    """

    def test_worker_thread_construction_raises(self) -> None:
        import threading as _threading

        session = _make_session(
            candidates=(_needs_confirmation_candidate(page_index=1),)
        )
        error: list[BaseException] = []

        def _try_construct() -> None:
            try:
                ConfirmDialog(session, Path("/tmp/.sessions"))
            except BaseException as e:
                error.append(e)

        t = _threading.Thread(target=_try_construct)
        t.start()
        t.join()

        assert len(error) == 1
        assert isinstance(error[0], RuntimeError)
        assert "main thread" in str(error[0])


class TestStdlibOnly:
    def test_no_third_party_imports_across_ui_package(self) -> None:
        """ADR-009: PyInstaller hook 不要化のため third-party UI ライブラリ禁止（ui/ 全体）"""
        ui_dir = Path(cd_mod.__file__).parent
        py_files = list(ui_dir.rglob("*.py"))
        assert py_files, "ui package has no .py files (fixture broken)"
        forbidden = ("PySide6", "PyQt5", "PyQt6", "flet", "DearPyGui", "wxPython", "kivy")
        for f in py_files:
            text = f.read_text(encoding="utf-8")
            for lib in forbidden:
                assert lib not in text, f"forbidden third-party import {lib!r} in {f}"


# ===========================================================================
# Layer 2: UI wiring tests (Tk 必要、skip ガード)
# ===========================================================================


# Tk 利用可否判定は ``conftest.py`` の ``@pytest.mark.tk_required`` に集約（プロセス内
# での Tk 生成試行を 1 回に抑え、macOS uv python で累積する Tcl global state による
# hang を防ぐ）。
_skip_if_no_tk = pytest.mark.tk_required


# ---------------------------------------------------------------------------
# Stubs for Tk-dependent tests
# ---------------------------------------------------------------------------


@dataclass
class _FakeMessageBox:
    yesno_return: bool = True
    showinfo_calls: list[tuple[str, str]] = field(default_factory=list)
    askyesno_calls: list[tuple[str, str]] = field(default_factory=list)
    showerror_calls: list[tuple[str, str]] = field(default_factory=list)

    def askyesno(self, title: str, message: str) -> bool:
        self.askyesno_calls.append((title, message))
        return self.yesno_return

    def showinfo(self, title: str, message: str) -> None:
        self.showinfo_calls.append((title, message))

    def showerror(self, title: str, message: str) -> None:
        self.showerror_calls.append((title, message))


class _SaveSessionSpy:
    def __init__(self) -> None:
        self.calls: list[Session] = []

    def __call__(self, session: Session, *, sessions_dir: Path) -> Path:
        self.calls.append(session)
        return sessions_dir / f"{session.session_id}.json"


class _FailingSaveSession:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.calls = 0

    def __call__(self, session: Session, *, sessions_dir: Path) -> Path:
        self.calls += 1
        raise self.exc


@pytest.fixture
def tk_root() -> object:
    import contextlib

    root = tk.Tk()
    root.withdraw()
    yield root
    with contextlib.suppress(tk.TclError):
        root.destroy()


def _build_dialog(
    session: Session,
    tk_root: tk.Tk,
    *,
    save_spy: _SaveSessionSpy | _FailingSaveSession | None = None,
    askopenfilename_fn: Callable[..., str] | None = None,
    messagebox: _FakeMessageBox | None = None,
    sessions_dir: Path = Path("/tmp/.sessions"),
) -> tuple[ConfirmDialog, _SaveSessionSpy | _FailingSaveSession, _FakeMessageBox]:
    spy: _SaveSessionSpy | _FailingSaveSession = save_spy or _SaveSessionSpy()
    mb = messagebox or _FakeMessageBox()
    dialog = ConfirmDialog(
        session,
        sessions_dir,
        root=tk_root,
        save_session_fn=spy,
        askopenfilename_fn=askopenfilename_fn or (lambda **_: ""),
        messagebox_fn=mb,
    )
    return dialog, spy, mb


@_skip_if_no_tk
class TestConfirmDialogConstruction:
    def test_raises_if_session_not_needs_review(self, tk_root: tk.Tk) -> None:
        session = _make_session(
            status=SessionStatus.RUNNING_PHASE_A,
            candidates=(_needs_confirmation_candidate(),),
        )
        with pytest.raises(ValueError, match="NEEDS_REVIEW"):
            ConfirmDialog(session, Path("/tmp/.sessions"), root=tk_root)

    def test_raises_if_no_open_candidates(self, tk_root: tk.Tk) -> None:
        session = _make_session(candidates=(_auto_matched_candidate(),))
        with pytest.raises(ValueError, match="at least one unresolved"):
            ConfirmDialog(session, Path("/tmp/.sessions"), root=tk_root)

    def test_treeview_shows_only_open_candidates(self, tk_root: tk.Tk) -> None:
        """AC-UI-1 (UI level)"""
        session = _make_session(
            candidates=(
                _auto_matched_candidate(page_index=0),
                _needs_confirmation_candidate(page_index=1),
                _no_match_candidate(page_index=2),
            )
        )
        dialog, _, _ = _build_dialog(session, tk_root)
        items = dialog._tree.get_children()
        assert set(items) == {"1", "2"}


@_skip_if_no_tk
class TestPersistenceFailFast:
    def test_save_called_each_operation(self, tk_root: tk.Tk) -> None:
        """AC-UI-6 (UI level): 承認・却下・スキップの 3 操作 → save_session 3 回呼ばれる

        手動選択（``_on_manual_select``）の save 呼出は :class:`TestManualSelectWiring` で
        spy を使って別途検証する（filedialog の DI が必要なためテストを分離）。
        """
        session = _make_session(
            candidates=(
                _needs_confirmation_candidate(page_index=1),
                _no_match_candidate(page_index=2),
                _needs_confirmation_candidate(page_index=3),
            )
        )
        dialog, spy, _ = _build_dialog(session, tk_root)
        assert isinstance(spy, _SaveSessionSpy)

        dialog._tree.selection_set("1")
        dialog._on_select(None)
        dialog._on_approve()

        dialog._tree.selection_set("2")
        dialog._on_select(None)
        dialog._on_reject()

        dialog._tree.selection_set("3")
        dialog._on_select(None)
        dialog._on_skip()

        assert len(spy.calls) == 3

    def test_save_error_propagates(self, tk_root: tk.Tk) -> None:
        """AC-UI-10 (UI level): save_session 失敗で例外が呼出元に伝播"""
        session = _make_session(candidates=(_needs_confirmation_candidate(page_index=1),))
        failing = _FailingSaveSession(OSError("disk full"))
        dialog, _, _ = _build_dialog(session, tk_root, save_spy=failing)
        dialog._tree.selection_set("1")
        dialog._on_select(None)

        with pytest.raises(OSError, match="disk full"):
            dialog._on_approve()

        assert failing.calls == 1

    def test_save_error_leaves_memory_ahead_of_disk(self, tk_root: tk.Tk) -> None:
        """AC-UI-10 補足: save 失敗時のメモリ/ディスク不整合を契約として明示する。

        resolve_candidate が save 前に in-place 更新するため、save 失敗後のメモリは
        新 status になる（ディスクは旧 status）。呼出側はメモリ上の session を破棄し
        再ロードする責務がある（confirm_dialog.py の _apply_update docstring で規定）。
        """
        session = _make_session(candidates=(_needs_confirmation_candidate(page_index=1),))
        failing = _FailingSaveSession(OSError("disk full"))
        dialog, _, _ = _build_dialog(session, tk_root, save_spy=failing)
        dialog._tree.selection_set("1")
        dialog._on_select(None)

        with pytest.raises(OSError):
            dialog._on_approve()

        # メモリ上は更新済み（契約上の期待値）
        assert session.candidates[0].status == PairStatus.CONFIRMED


@_skip_if_no_tk
class TestCloseBehavior:
    def test_close_with_unresolved_asks_confirmation(self, tk_root: tk.Tk) -> None:
        """AC-UI-7 (UI level)"""
        session = _make_session(
            candidates=(
                _needs_confirmation_candidate(page_index=1),
                _no_match_candidate(page_index=2),
            )
        )
        mb = _FakeMessageBox(yesno_return=True)
        dialog, _, _ = _build_dialog(session, tk_root, messagebox=mb)

        dialog._on_close_button()

        assert dialog._session.all_candidates_resolved is False
        assert len(mb.askyesno_calls) == 1

    def test_close_all_resolved_shows_info(self, tk_root: tk.Tk) -> None:
        """AC-UI-8 (UI level): 全件解決 → showinfo → quit"""
        session = _make_session(
            candidates=(_needs_confirmation_candidate(page_index=1),)
        )
        mb = _FakeMessageBox()
        dialog, _, _ = _build_dialog(session, tk_root, messagebox=mb)

        dialog._tree.selection_set("1")
        dialog._on_select(None)
        dialog._on_approve()

        assert len(mb.showinfo_calls) == 1
        assert dialog._session.all_candidates_resolved is True

    def test_close_declined_keeps_dialog_open(self, tk_root: tk.Tk) -> None:
        """AC-UI-7 (UI level): 「いいえ」選択でダイアログ継続"""
        session = _make_session(
            candidates=(_needs_confirmation_candidate(page_index=1),)
        )
        mb = _FakeMessageBox(yesno_return=False)
        dialog, _, _ = _build_dialog(session, tk_root, messagebox=mb)

        dialog._on_close_button()

        assert dialog._session.all_candidates_resolved is False


@_skip_if_no_tk
class TestManualSelectWiring:
    def test_both_b_and_c_selected(self, tk_root: tk.Tk) -> None:
        """AC-UI-4 + AC-UI-6 (UI level): 両方選択 → MANUALLY_SELECTED + save_session 呼出"""
        session = _make_session(candidates=(_no_match_candidate(page_index=2),))
        picks = iter(["/manual/B.pdf", "/manual/C.pdf"])
        dialog, spy, _ = _build_dialog(
            session, tk_root, askopenfilename_fn=lambda **_: next(picks)
        )
        assert isinstance(spy, _SaveSessionSpy)
        dialog._tree.selection_set("2")
        dialog._on_select(None)

        dialog._on_manual_select()

        cand = session.candidates[0]
        assert cand.status == PairStatus.MANUALLY_SELECTED
        assert cand.matched_b_path == "/manual/B.pdf"
        assert cand.matched_c_path == "/manual/C.pdf"
        # 手動選択も他操作と同様に save_session が 1 回呼ばれること（AC-UI-6 補完）
        assert len(spy.calls) == 1

    def test_both_cancelled_is_noop(self, tk_root: tk.Tk) -> None:
        session = _make_session(candidates=(_no_match_candidate(page_index=2),))
        dialog, spy, _ = _build_dialog(
            session, tk_root, askopenfilename_fn=lambda **_: ""
        )
        assert isinstance(spy, _SaveSessionSpy)
        dialog._tree.selection_set("2")
        dialog._on_select(None)

        dialog._on_manual_select()

        assert session.candidates[0].status == PairStatus.NO_MATCH
        assert len(spy.calls) == 0

    def test_partial_selection_asks_confirm_yes(self, tk_root: tk.Tk) -> None:
        """片側のみ選択 → askyesno → yes → MANUALLY_SELECTED で確定"""
        session = _make_session(candidates=(_no_match_candidate(page_index=2),))
        picks = iter(["/manual/B.pdf", ""])  # C はキャンセル
        mb = _FakeMessageBox(yesno_return=True)
        dialog, spy, _ = _build_dialog(
            session,
            tk_root,
            askopenfilename_fn=lambda **_: next(picks),
            messagebox=mb,
        )
        assert isinstance(spy, _SaveSessionSpy)
        dialog._tree.selection_set("2")
        dialog._on_select(None)

        dialog._on_manual_select()

        assert len(mb.askyesno_calls) == 1
        assert session.candidates[0].status == PairStatus.MANUALLY_SELECTED
        assert session.candidates[0].matched_b_path == "/manual/B.pdf"
        assert session.candidates[0].matched_c_path is None

    def test_partial_selection_asks_confirm_no(self, tk_root: tk.Tk) -> None:
        """片側のみ選択 → askyesno → no → no-op（save 呼出なし）"""
        session = _make_session(candidates=(_no_match_candidate(page_index=2),))
        picks = iter(["", "/manual/C.pdf"])  # B はキャンセル
        mb = _FakeMessageBox(yesno_return=False)
        dialog, spy, _ = _build_dialog(
            session,
            tk_root,
            askopenfilename_fn=lambda **_: next(picks),
            messagebox=mb,
        )
        assert isinstance(spy, _SaveSessionSpy)
        dialog._tree.selection_set("2")
        dialog._on_select(None)

        dialog._on_manual_select()

        assert len(mb.askyesno_calls) == 1
        assert session.candidates[0].status == PairStatus.NO_MATCH
        assert len(spy.calls) == 0

    def test_filedialog_tclerror_shows_error_and_skips(self, tk_root: tk.Tk) -> None:
        """askopenfilename が TclError 送出 → showerror 表示 + その kind は未選択扱い"""
        session = _make_session(candidates=(_no_match_candidate(page_index=2),))

        def _raise(**_: object) -> str:
            raise tk.TclError("display connection lost")

        mb = _FakeMessageBox()
        dialog, spy, _ = _build_dialog(
            session, tk_root, askopenfilename_fn=_raise, messagebox=mb
        )
        assert isinstance(spy, _SaveSessionSpy)
        dialog._tree.selection_set("2")
        dialog._on_select(None)

        dialog._on_manual_select()

        # 両方 TclError → 両方未選択 → no-op（save 呼出ゼロ）
        assert len(mb.showerror_calls) == 2
        assert session.candidates[0].status == PairStatus.NO_MATCH
        assert len(spy.calls) == 0


@_skip_if_no_tk
class TestCallbackException:
    """Tk `report_callback_exception` 経路のテスト（CRITICAL: fail-fast の core）"""

    def test_callback_exception_shows_error_and_sets_aborted(
        self, tk_root: tk.Tk
    ) -> None:
        """save_session 失敗が Tk callback 経由 → showerror + aborted=True + quit"""
        session = _make_session(candidates=(_needs_confirmation_candidate(page_index=1),))
        failing = _FailingSaveSession(OSError("disk full"))
        mb = _FakeMessageBox()
        dialog, _, _ = _build_dialog(
            session, tk_root, save_spy=failing, messagebox=mb
        )

        # Tk callback が設定されていることの確認
        assert dialog._root.report_callback_exception == dialog._on_callback_exception

        # callback exception ハンドラを直接発火し副作用を検証
        try:
            raise OSError("disk full")
        except OSError as e:
            dialog._on_callback_exception(OSError, e, None)

        assert len(mb.showerror_calls) == 1
        title, msg = mb.showerror_calls[0]
        assert "内部エラー" in title
        assert "OSError" in msg
        assert "disk full" in msg  # 画面は PII 露出可

        # aborted が伝搬すれば最終結果 resolved_all は False 固定
        assert dialog._aborted is True

    def test_callback_exception_does_not_leak_path_to_log(
        self, tk_root: tk.Tk, caplog: pytest.LogCaptureFixture
    ) -> None:
        """PII 防御: 例外 message 内のファイルパスがログに流出しないこと

        OSError 等の例外文字列にファイルパスが含まれても、logger には型名のみ出力する。
        本テストは「`logger.exception` で traceback が出るとファイルパスが漏れる」
        という既知リスク（Codex review で検出）を回帰防止する。
        """
        session = _make_session(candidates=(_needs_confirmation_candidate(page_index=1),))
        dialog, _, _ = _build_dialog(session, tk_root)

        pii_path = "/secret/利用者_塩津美貴子.pdf"
        with caplog.at_level(logging.DEBUG, logger="wiseman_hub.ui.confirm_dialog"):
            try:
                raise PermissionError(f"[Errno 13] denied: '{pii_path}'")
            except PermissionError as e:
                dialog._on_callback_exception(PermissionError, e, None)

        # ログに session_id と型名は含むが、PII パスは含まない
        joined = caplog.text
        assert session.session_id in joined
        assert "PermissionError" in joined
        assert "塩津" not in joined, f"PII leaked to log: {joined}"
        assert "利用者" not in joined
        assert pii_path not in joined


@_skip_if_no_tk
class TestRefreshTreeSelection:
    """_refresh_tree の selection-cleared 経路（操作連打で stale selection を防ぐ）"""

    def test_refresh_clears_selection_when_resolved_row_disappears(
        self, tk_root: tk.Tk
    ) -> None:
        """承認後に Treeview から該当行が消え、detail/buttons がクリアされる"""
        session = _make_session(
            candidates=(
                _needs_confirmation_candidate(page_index=1),
                _no_match_candidate(page_index=2),
            )
        )
        dialog, _, _ = _build_dialog(session, tk_root)
        dialog._tree.selection_set("1")
        dialog._on_select(None)
        assert dialog._btn_approve.instate(["!disabled"])  # 承認ボタン有効

        dialog._on_approve()  # 承認 → row 1 が消える

        # row 1 が消えている
        assert "1" not in dialog._tree.get_children()
        # detail がクリア・全ボタンが disabled
        assert dialog._detail_var.get() == "候補を選択してください。"
        assert dialog._btn_approve.instate(["disabled"])
        assert dialog._btn_reject.instate(["disabled"])
        assert dialog._btn_manual.instate(["disabled"])
        assert dialog._btn_skip.instate(["disabled"])


# ===========================================================================
# Toplevel モード（13C）
# ===========================================================================


@_skip_if_no_tk
class TestConfirmDialogToplevelMode:
    """parent 指定時は Tk.Tk ではなく Toplevel + grab_set でモーダル化する。

    13C で Launcher から呼び出す際、Launcher の他ボタンが押されて Phase B と
    Phase A が同時実行される race を構造的に排除するため必須。
    12B SettingsDialog と同じ dual mode パターン。
    """

    def test_both_root_and_parent_raises(self, tk_root: tk.Tk) -> None:
        session = _make_session(candidates=(_needs_confirmation_candidate(),))
        with pytest.raises(ValueError, match="either root or parent"):
            ConfirmDialog(
                session,
                Path("/tmp/.sessions"),
                root=tk_root,
                parent=tk_root,
            )

    def test_parent_mode_creates_toplevel(self, tk_root: tk.Tk) -> None:
        """parent 指定時: 内部 root は Toplevel、_is_toplevel=True。"""
        session = _make_session(candidates=(_needs_confirmation_candidate(),))
        dialog = ConfirmDialog(
            session,
            Path("/tmp/.sessions"),
            parent=tk_root,
            messagebox_fn=_FakeMessageBox(),
        )
        try:
            assert dialog._is_toplevel is True
            assert isinstance(dialog._root, tk.Toplevel)
        finally:
            import contextlib as _cl

            with _cl.suppress(tk.TclError):
                dialog._root.destroy()

    def test_root_mode_creates_no_toplevel(self, tk_root: tk.Tk) -> None:
        """従来互換: root 指定時は _is_toplevel=False。"""
        session = _make_session(candidates=(_needs_confirmation_candidate(),))
        dialog = ConfirmDialog(
            session,
            Path("/tmp/.sessions"),
            root=tk_root,
            messagebox_fn=_FakeMessageBox(),
        )
        assert dialog._is_toplevel is False
        assert dialog._root is tk_root

    def test_toplevel_close_uses_destroy_not_quit(self, tk_root: tk.Tk) -> None:
        """Toplevel モードは親 mainloop を止めないため quit() ではなく destroy()。

        `_close_dialog()` ヘルパーがモード分岐する契約を固定。
        """
        session = _make_session(candidates=(_needs_confirmation_candidate(),))
        dialog = ConfirmDialog(
            session,
            Path("/tmp/.sessions"),
            parent=tk_root,
            messagebox_fn=_FakeMessageBox(),
        )
        assert dialog._root.winfo_exists()
        dialog._close_dialog()
        # destroy 後は winfo_exists が 0 を返す（Toplevel は消えている）
        # ただし tkinter の実装上、destroy 後の winfo_exists 呼出が TclError になる
        # ケースもあるため、両方許容する契約とする
        import contextlib as _cl

        with _cl.suppress(tk.TclError):
            assert not dialog._root.winfo_exists()
        # 親 mainloop は生きている（親 root は破棄されない）
        assert tk_root.winfo_exists()
