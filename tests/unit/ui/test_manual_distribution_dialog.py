"""manual_distribution_dialog のテスト (PR4)。

ViewModel 中心に検証 (Tk widget は最小限の smoke のみ)。
PII 防御: テストデータは仮名のみ。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wiseman_hub.pdf.ex_extractor import (
    ExtractionItem,
    ExtractionStatus,
    FakeSfxAdapter,
)
from wiseman_hub.pdf.facility_resolver import (
    ResolveReason,
    ResolveResult,
)
from wiseman_hub.ui.manual_distribution_dialog import (
    ManualDistributionViewModel,
    ManualUiState,
)


def _ambiguous_item(name: str, candidates: tuple[str, ...]) -> ExtractionItem:
    return ExtractionItem(
        source_path=Path(name),
        resolve_result=ResolveResult.ambiguous(
            candidates, ResolveReason.AMBIGUOUS_PARTIAL
        ),
        status=ExtractionStatus.SKIPPED_AMBIGUOUS,
    )


def _unmatched_item(name: str) -> ExtractionItem:
    return ExtractionItem(
        source_path=Path(name),
        resolve_result=ResolveResult.unmatched(ResolveReason.NO_CANDIDATE),
        status=ExtractionStatus.SKIPPED_UNMATCHED,
    )


def _confirmed_manual(name: str, facility: str, dest: Path) -> ExtractionItem:
    return ExtractionItem(
        source_path=Path(name),
        resolve_result=ResolveResult.confirmed(
            facility, ResolveReason.MANUAL_OVERRIDE
        ),
        status=ExtractionStatus.SUCCESS,
        moved_pdfs=(dest,),
    )


# ---------------------------------------------------------------------------
# ViewModel: 候補列挙 (4 件)
# ---------------------------------------------------------------------------


class TestCandidateOptions:
    def test_ambiguous_returns_resolve_candidates(self, tmp_path: Path) -> None:
        item = _ambiguous_item("a.ex_", ("サービスX", "サービスY"))
        vm = ManualDistributionViewModel(
            pending_items=(item,),
            facility_names=["サービスX", "サービスY", "サービスZ"],
            facility_root_dir=tmp_path,
        )
        assert vm.candidate_options == ["サービスX", "サービスY"]
        assert vm.is_unmatched is False

    def test_unmatched_returns_all_facility_names(self, tmp_path: Path) -> None:
        item = _unmatched_item("a.ex_")
        vm = ManualDistributionViewModel(
            pending_items=(item,),
            facility_names=["サービスX", "サービスY", "サービスZ"],
            facility_root_dir=tmp_path,
        )
        assert vm.candidate_options == ["サービスX", "サービスY", "サービスZ"]
        assert vm.is_unmatched is True

    def test_can_skip_only_for_unmatched(self, tmp_path: Path) -> None:
        amb_vm = ManualDistributionViewModel(
            pending_items=(_ambiguous_item("a.ex_", ("X", "Y")),),
            facility_names=["X", "Y"],
            facility_root_dir=tmp_path,
        )
        unm_vm = ManualDistributionViewModel(
            pending_items=(_unmatched_item("b.ex_"),),
            facility_names=["X"],
            facility_root_dir=tmp_path,
        )
        assert amb_vm.can_skip is False
        assert unm_vm.can_skip is True

    def test_empty_pending_items_done(self, tmp_path: Path) -> None:
        vm = ManualDistributionViewModel(
            pending_items=(),
            facility_names=[],
            facility_root_dir=tmp_path,
        )
        assert vm.current_item is None
        assert vm.candidate_options == []


# ---------------------------------------------------------------------------
# ViewModel: 状態遷移 (8 件)
# ---------------------------------------------------------------------------


class TestStateTransitions:
    def _make_vm(self, tmp_path: Path) -> ManualDistributionViewModel:
        return ManualDistributionViewModel(
            pending_items=(_unmatched_item("a.ex_"), _unmatched_item("b.ex_")),
            facility_names=["サービスA", "サービスB"],
            facility_root_dir=tmp_path,
        )

    def test_select_facility_in_options(self, tmp_path: Path) -> None:
        vm = self._make_vm(tmp_path)
        vm.select_facility("サービスA")
        assert vm.selected_facility == "サービスA"
        assert vm.can_confirm is True

    def test_select_facility_not_in_options_rejected(
        self, tmp_path: Path
    ) -> None:
        vm = self._make_vm(tmp_path)
        vm.select_facility("不正な値")
        assert vm.selected_facility is None  # 受け付けない

    def test_select_none_or_empty_clears(self, tmp_path: Path) -> None:
        vm = self._make_vm(tmp_path)
        vm.select_facility("サービスA")
        vm.select_facility(None)
        assert vm.selected_facility is None

        vm.select_facility("サービスA")
        vm.select_facility("   ")  # 空白のみ
        assert vm.selected_facility is None

    def test_can_confirm_false_without_selection(self, tmp_path: Path) -> None:
        vm = self._make_vm(tmp_path)
        assert vm.can_confirm is False

    def test_transition_to_confirming_then_back(self, tmp_path: Path) -> None:
        vm = self._make_vm(tmp_path)
        vm.select_facility("サービスA")
        vm.transition_to_confirming()
        assert vm.state is ManualUiState.CONFIRMING
        vm.back_to_selecting()
        assert vm.state is ManualUiState.SELECTING

    def test_transition_to_extracting_requires_confirming(
        self, tmp_path: Path
    ) -> None:
        vm = self._make_vm(tmp_path)
        with pytest.raises(RuntimeError, match="cannot extract"):
            vm.transition_to_extracting()

    def test_add_completed_advances_to_next_item(self, tmp_path: Path) -> None:
        vm = self._make_vm(tmp_path)
        vm.select_facility("サービスA")
        vm.transition_to_confirming()
        vm.transition_to_extracting()

        item = _confirmed_manual("a.ex_", "サービスA", tmp_path / "a.pdf")
        vm.add_completed_and_advance(item)

        assert vm.current_index == 1
        assert vm.state is ManualUiState.SELECTING
        assert vm.selected_facility is None
        assert len(vm.completed_results) == 1

    def test_skip_current_advances(self, tmp_path: Path) -> None:
        vm = self._make_vm(tmp_path)
        vm.skip_current()
        assert vm.current_index == 1
        # 元 item が completed_results に保持される (SKIPPED_UNMATCHED のまま)
        assert len(vm.completed_results) == 1
        assert (
            vm.completed_results[0].status
            is ExtractionStatus.SKIPPED_UNMATCHED
        )

    def test_done_when_all_processed(self, tmp_path: Path) -> None:
        vm = self._make_vm(tmp_path)
        # 1 件目を skip
        vm.skip_current()
        # 2 件目を skip
        vm.skip_current()

        assert vm.state is ManualUiState.DONE
        assert vm.is_done is True

    def test_abort_remaining_pads_unprocessed_items(self, tmp_path: Path) -> None:
        """HIGH-G: close 中断時に未処理 item が DONE 状態で穴埋めされる。"""
        vm = self._make_vm(tmp_path)
        # 1 件目を skip
        vm.skip_current()
        # 2 件目は処理せず abort
        vm.abort_remaining()

        assert vm.state is ManualUiState.DONE
        assert len(vm.completed_results) == 2
        # 2 件目は元の SKIPPED_UNMATCHED status のまま保持される
        assert (
            vm.completed_results[1].status
            is ExtractionStatus.SKIPPED_UNMATCHED
        )

    def test_abort_remaining_when_already_done(self, tmp_path: Path) -> None:
        """abort_remaining は DONE 状態でも安全に呼べる (idempotent)。"""
        vm = ManualDistributionViewModel(
            pending_items=(),
            facility_names=[],
            facility_root_dir=tmp_path,
        )
        vm.state = ManualUiState.DONE
        vm.abort_remaining()  # 何も追加しない
        assert vm.state is ManualUiState.DONE
        assert vm.completed_results == []

    def test_fail_current_advances_with_error_message(
        self, tmp_path: Path
    ) -> None:
        vm = self._make_vm(tmp_path)
        vm.select_facility("サービスA")
        vm.transition_to_confirming()
        vm.transition_to_extracting()

        original_item = vm.pending_items[0]
        vm.fail_current_and_advance(original_item, "OSError")

        assert vm.error_message == "OSError"
        assert vm.current_index == 1
        assert len(vm.completed_results) == 1


# ---------------------------------------------------------------------------
# Dialog smoke テスト (Tk required) — 最小限
# ---------------------------------------------------------------------------


@pytest.mark.tk_required
class TestManualDistributionDialogSmoke:
    def test_empty_pending_starts_in_done(self, tmp_path: Path) -> None:
        import tkinter as tk

        from wiseman_hub.ui.manual_distribution_dialog import (
            ManualDistributionDialog,
        )

        root = tk.Tk()
        try:
            dialog = ManualDistributionDialog(
                parent=root,
                pending_items=(),
                facility_names=[],
                facility_root_dir=tmp_path,
                adapter=FakeSfxAdapter(),
            )
            assert dialog.view_model.state is ManualUiState.DONE
            dialog._on_close()
        finally:
            root.destroy()

    def test_skip_advances_to_next_item(self, tmp_path: Path) -> None:
        import tkinter as tk

        from wiseman_hub.ui.manual_distribution_dialog import (
            ManualDistributionDialog,
        )

        items = (
            _unmatched_item("a.ex_"),
            _unmatched_item("b.ex_"),
        )
        root = tk.Tk()
        try:
            dialog = ManualDistributionDialog(
                parent=root,
                pending_items=items,
                facility_names=["サービスA"],
                facility_root_dir=tmp_path,
                adapter=FakeSfxAdapter(),
            )
            assert dialog.view_model.current_index == 0
            dialog._on_skip_click()
            assert dialog.view_model.current_index == 1
            dialog._on_skip_click()
            assert dialog.view_model.is_done is True
            # close は追加処理なし (DONE 状態)
            dialog._on_close()
        finally:
            root.destroy()
