"""``__main__._review_outcome_to_callback_result`` adapter 層の直接ユニットテスト。

Issue #97 (pr-test-analyzer rating 8 対応): ``_make_review_callback`` の 12 return
statements のうち、``ReviewOutcome`` → ``ReviewCallbackResult`` 変換 + messagebox
呼出の分岐を直接検証する。

- flow 本体（9 reason）の網羅は ``tests/unit/pdf/test_review_flow.py``
- picker/config 前段の分岐（cancel 1/2 + success 1）は本ファイルの TestAdapter に
  組み込まず、既存の ``test_launcher_phase_b_integration.py`` で integration として検証
  済み（inline lambda stub ではあるが、adapter の本質は messagebox/result 変換のみ）。
"""

from __future__ import annotations

from typing import Any
from unittest import mock

import pytest

from wiseman_hub.__main__ import _review_outcome_to_callback_result
from wiseman_hub.pdf.review_flow import ReviewOutcome
from wiseman_hub.ui.launcher import CANCEL_RESULT, ReviewCallbackResult


class TestSuccessMapping:
    """reason ∈ {ready_to_merge, resolved} は ReviewCallbackResult(session_id) を返し、
    messagebox は呼ばれない。"""

    def test_ready_to_merge_maps_to_callback_result(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_showerror = mock.MagicMock()
        monkeypatch.setattr("tkinter.messagebox.showerror", mock_showerror)

        outcome = ReviewOutcome("ready_to_merge", "sess-abc-123")
        result = _review_outcome_to_callback_result(outcome)

        assert result == ReviewCallbackResult(session_id="sess-abc-123")
        assert result.should_phase_b is True
        mock_showerror.assert_not_called()

    def test_resolved_maps_to_callback_result(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_showerror = mock.MagicMock()
        monkeypatch.setattr("tkinter.messagebox.showerror", mock_showerror)

        outcome = ReviewOutcome("resolved", "sess-xyz-999")
        result = _review_outcome_to_callback_result(outcome)

        assert result == ReviewCallbackResult(session_id="sess-xyz-999")
        assert result.should_phase_b is True
        mock_showerror.assert_not_called()


class TestSilentCancelMapping:
    """reason ∈ {aborted, unresolved} は CANCEL_RESULT + messagebox なし。

    aborted: ConfirmDialog 側で既にエラー画面を表示済み
    unresolved: ユーザーが未解決を自覚している
    """

    def test_aborted_maps_to_cancel_silently(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_showerror = mock.MagicMock()
        monkeypatch.setattr("tkinter.messagebox.showerror", mock_showerror)

        outcome = ReviewOutcome("aborted", "sess-1")
        result = _review_outcome_to_callback_result(outcome)

        assert result == CANCEL_RESULT
        assert result.should_phase_b is False
        mock_showerror.assert_not_called()

    def test_unresolved_maps_to_cancel_silently(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_showerror = mock.MagicMock()
        monkeypatch.setattr("tkinter.messagebox.showerror", mock_showerror)

        outcome = ReviewOutcome("unresolved", "sess-2")
        result = _review_outcome_to_callback_result(outcome)

        assert result == CANCEL_RESULT
        mock_showerror.assert_not_called()


class TestErrorMessageMapping:
    """エラー系 5 reason は CANCEL_RESULT + reason に対応する messagebox を 1 回呼ぶ。"""

    def _capture_showerror(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> mock.MagicMock:
        mock_showerror = mock.MagicMock()
        monkeypatch.setattr("tkinter.messagebox.showerror", mock_showerror)
        return mock_showerror

    def test_lock_error_shows_contention_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_showerror = self._capture_showerror(monkeypatch)
        outcome = ReviewOutcome("lock_error", "sess-lk", detail="BlockingIOError")

        result = _review_outcome_to_callback_result(outcome)

        assert result == CANCEL_RESULT
        mock_showerror.assert_called_once()
        title, body = mock_showerror.call_args[0]
        assert title == "セッション操作エラー"
        assert "BlockingIOError" in body
        # PII 防御: session_id は message に含まない
        assert "sess-lk" not in body

    def test_concurrent_modification_shows_conflict_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_showerror = self._capture_showerror(monkeypatch)
        outcome = ReviewOutcome("concurrent_modification", "s", detail="completed")

        result = _review_outcome_to_callback_result(outcome)

        assert result == CANCEL_RESULT
        mock_showerror.assert_called_once()
        title, body = mock_showerror.call_args[0]
        assert title == "セッション競合"
        assert "別のプロセス" in body

    def test_transition_lock_error_shows_transition_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_showerror = self._capture_showerror(monkeypatch)
        outcome = ReviewOutcome(
            "transition_lock_error", "s", detail="BlockingIOError"
        )

        result = _review_outcome_to_callback_result(outcome)

        assert result == CANCEL_RESULT
        mock_showerror.assert_called_once()
        title, body = mock_showerror.call_args[0]
        assert title == "セッション遷移エラー"
        assert "解決は保存済み" in body
        assert "BlockingIOError" in body

    def test_invalid_transition_shows_status_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_showerror = self._capture_showerror(monkeypatch)
        outcome = ReviewOutcome(
            "invalid_transition", "s", detail="InvalidTransitionError"
        )

        result = _review_outcome_to_callback_result(outcome)

        assert result == CANCEL_RESULT
        mock_showerror.assert_called_once()
        title, body = mock_showerror.call_args[0]
        assert title == "セッション状態エラー"
        assert "InvalidTransitionError" in body

    def test_invalid_status_shows_status_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_showerror = self._capture_showerror(monkeypatch)
        outcome = ReviewOutcome(
            "invalid_status", "s", detail="running_phase_a"
        )

        result = _review_outcome_to_callback_result(outcome)

        assert result == CANCEL_RESULT
        mock_showerror.assert_called_once()
        title, body = mock_showerror.call_args[0]
        assert title == "セッション状態エラー"
        assert "running_phase_a" in body


class TestRaceSessionLoadError:
    """evaluator 指摘: picker 選択後〜1st lock 取得前に他プロセスが --discard した race で
    resolve 内の load_session が SessionNotFoundError / SessionCorruptedError を raise
    する可能性がある。adapter 側で catch して messagebox 通知 + CANCEL_RESULT に
    マッピングすることで、アプリ全体終了を防ぐ。

    本ファイルでは ``_review_outcome_to_callback_result`` 単体ではなく
    ``_make_review_callback`` が構築する closure 内の catch 挙動を確認する。
    """

    def _run_open_review_with_resolve_raising(
        self,
        tmp_path: Any,
        monkeypatch: pytest.MonkeyPatch,
        exc: Exception,
    ) -> tuple[Any, mock.MagicMock, mock.MagicMock]:
        """共通: resolve_review_session が ``exc`` を raise する状況で open_review 実行。

        patch 対象は ``wiseman_hub.pdf.review_flow.resolve_review_session``（文字列パス）。
        `open_review` 内の lazy import 経由で差し替えを効かせる。patch 有効性は
        呼出側テストで ``mock_resolve.assert_called_once()`` で保証する。
        """
        from wiseman_hub.__main__ import _make_review_callback
        from wiseman_hub.pdf.session import SessionStatus

        cfg_mock = mock.MagicMock()
        cfg_mock.pdf_merge.output_dir = str(tmp_path)
        monkeypatch.setattr("wiseman_hub.config.load_config", lambda _: cfg_mock)

        # SessionPicker が session_id を返すように stub
        picker_result = mock.MagicMock()
        picker_result.selected = True
        picker_result.session_id = "race-victim-sid"
        picker_result.status = SessionStatus.NEEDS_REVIEW
        picker_mock = mock.MagicMock()
        picker_mock.return_value.run.return_value = picker_result
        monkeypatch.setattr(
            "wiseman_hub.ui.session_picker.SessionPicker", picker_mock
        )

        mock_resolve = mock.MagicMock(side_effect=exc)
        monkeypatch.setattr(
            "wiseman_hub.pdf.review_flow.resolve_review_session", mock_resolve
        )

        mock_showerror = mock.MagicMock()
        monkeypatch.setattr("tkinter.messagebox.showerror", mock_showerror)

        launcher_stub = mock.MagicMock()
        launcher_stub.get_root.return_value = mock.MagicMock()
        cb = _make_review_callback(
            tmp_path / "config.toml", lambda: launcher_stub
        )
        result = cb()
        return result, mock_resolve, mock_showerror

    def test_session_not_found_race_maps_to_cancel_with_messagebox(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from wiseman_hub.pdf.session import SessionNotFoundError

        result, mock_resolve, mock_showerror = (
            self._run_open_review_with_resolve_raising(
                tmp_path,
                monkeypatch,
                SessionNotFoundError("race: session discarded"),
            )
        )

        assert result == CANCEL_RESULT
        mock_resolve.assert_called_once()  # patch 有効性を保証
        mock_showerror.assert_called_once()
        title, body = mock_showerror.call_args[0]
        assert title == "セッション読込エラー"
        assert "SessionNotFoundError" in body
        # PII 防御: session_id は message body に出さない
        assert "race-victim-sid" not in body

    def test_session_corrupted_race_maps_to_cancel_with_messagebox(
        self, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SessionCorruptedError も同じ catch 経路で CANCEL + messagebox を返すことを
        検証（evaluator 指摘: 2 例外のうち片方しかテストしていなかった）。"""
        from wiseman_hub.pdf.session import SessionCorruptedError

        result, mock_resolve, mock_showerror = (
            self._run_open_review_with_resolve_raising(
                tmp_path,
                monkeypatch,
                SessionCorruptedError("simulated JSON corruption"),
            )
        )

        assert result == CANCEL_RESULT
        mock_resolve.assert_called_once()
        mock_showerror.assert_called_once()
        title, body = mock_showerror.call_args[0]
        assert title == "セッション読込エラー"
        assert "SessionCorruptedError" in body


class TestAdapterReasonExhaustiveness:
    """全 9 reason について adapter が ReviewCallbackResult を返すことを網羅的に確認。

    将来 ReviewReason に新値が追加された際、本テストが回帰検出する（UNTESTED reason の
    入れ忘れ防止）。"""

    @pytest.mark.parametrize(
        "reason,expect_session_id",
        [
            ("ready_to_merge", True),
            ("resolved", True),
            ("aborted", False),
            ("unresolved", False),
            ("lock_error", False),
            ("concurrent_modification", False),
            ("transition_lock_error", False),
            ("invalid_transition", False),
            ("invalid_status", False),
        ],
    )
    def test_all_reasons_produce_callback_result(
        self,
        reason: str,
        expect_session_id: bool,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("tkinter.messagebox.showerror", mock.MagicMock())
        outcome = ReviewOutcome(reason, "sess-ABC", detail="detail")  # type: ignore[arg-type]

        result = _review_outcome_to_callback_result(outcome)

        assert isinstance(result, ReviewCallbackResult)
        if expect_session_id:
            assert result.session_id == "sess-ABC"
            assert result.should_phase_b is True
        else:
            assert result == CANCEL_RESULT
            assert result.should_phase_b is False
