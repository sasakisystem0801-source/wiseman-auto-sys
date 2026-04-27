"""ex_extractor_dialog のテスト (PR4)。

UI ロジックは ``ExExtractorViewModel`` に切り出してテストし、Tk widget 部分
(``ExExtractorDialog``) は最小限の smoke テストに留める (facility_root_dialog 踏襲)。

PII 防御方針 (テストデータ):
    すべて仮名で構成、実在介護施設名・利用者名を含めない。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from wiseman_hub.config import AppConfig
from wiseman_hub.pdf.ex_extractor import (
    ExtractionErrorCode,
    ExtractionItem,
    ExtractionResult,
    ExtractionStatus,
    FakeSfxAdapter,
)
from wiseman_hub.pdf.facility_resolver import (
    ResolveReason,
    ResolveResult,
)
from wiseman_hub.ui.ex_extractor_dialog import (
    ExExtractorDialog,
    ExExtractorViewModel,
    UiState,
)

# ---------------------------------------------------------------------------
# テスト用ヘルパー
# ---------------------------------------------------------------------------


def _confirmed_item(name: str, facility: str, dest: Path) -> ExtractionItem:
    return ExtractionItem(
        source_path=Path(name),
        resolve_result=ResolveResult.confirmed(
            facility, ResolveReason.ALIAS_MATCH
        ),
        status=ExtractionStatus.SUCCESS,
        moved_pdfs=(dest,),
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


def _failed_item(name: str) -> ExtractionItem:
    return ExtractionItem(
        source_path=Path(name),
        resolve_result=ResolveResult.confirmed(
            "サービスA", ResolveReason.ALIAS_MATCH
        ),
        status=ExtractionStatus.EXTRACT_FAILED,
        error_code=ExtractionErrorCode.NO_PDF_PRODUCED,
    )


def _manual_override_item(name: str, facility: str, dest: Path) -> ExtractionItem:
    return ExtractionItem(
        source_path=Path(name),
        resolve_result=ResolveResult.confirmed(
            facility, ResolveReason.MANUAL_OVERRIDE
        ),
        status=ExtractionStatus.SUCCESS,
        moved_pdfs=(dest,),
    )


# ---------------------------------------------------------------------------
# ExExtractorViewModel: can_run / can_open_manual / 状態遷移 (10 件)
# ---------------------------------------------------------------------------


class TestViewModelStateTransitions:
    def test_initial_state_is_idle(self, tmp_path: Path) -> None:
        vm = ExExtractorViewModel(
            source_dir=tmp_path, facility_root_dir=tmp_path
        )
        assert vm.state is UiState.IDLE
        assert vm.result is None
        assert vm.error_message is None

    def test_can_run_requires_existing_paths(self, tmp_path: Path) -> None:
        # 未存在パス
        vm = ExExtractorViewModel(
            source_dir=tmp_path / "missing",
            facility_root_dir=tmp_path,
        )
        assert vm.can_run is False

        vm2 = ExExtractorViewModel(
            source_dir=tmp_path,
            facility_root_dir=tmp_path / "missing",
        )
        assert vm2.can_run is False

    def test_can_run_on_idle_with_existing_paths(self, tmp_path: Path) -> None:
        vm = ExExtractorViewModel(
            source_dir=tmp_path, facility_root_dir=tmp_path
        )
        assert vm.can_run is True

    def test_transition_to_busy(self, tmp_path: Path) -> None:
        vm = ExExtractorViewModel(
            source_dir=tmp_path, facility_root_dir=tmp_path
        )
        vm.transition_to_busy()
        assert vm.state is UiState.BUSY
        assert vm.can_run is False

    def test_transition_to_busy_from_invalid_state_raises(
        self, tmp_path: Path
    ) -> None:
        vm = ExExtractorViewModel(
            source_dir=tmp_path, facility_root_dir=tmp_path
        )
        vm.state = UiState.MANUAL_DISTRIBUTING
        with pytest.raises(RuntimeError, match="cannot transition"):
            vm.transition_to_busy()

    def test_transition_to_showing_result(self, tmp_path: Path) -> None:
        vm = ExExtractorViewModel(
            source_dir=tmp_path, facility_root_dir=tmp_path
        )
        vm.transition_to_busy()
        result = ExtractionResult(items=())
        vm.transition_to_showing_result(result)
        assert vm.state is UiState.SHOWING_RESULT
        assert vm.result is result

    def test_transition_to_idle_with_error_pii_safe(
        self, tmp_path: Path
    ) -> None:
        vm = ExExtractorViewModel(
            source_dir=tmp_path, facility_root_dir=tmp_path
        )
        vm.transition_to_busy()
        vm.transition_to_idle_with_error("OSError")
        assert vm.state is UiState.IDLE
        assert vm.error_message == "OSError"

    def test_transition_to_idle_from_invalid_state_raises(
        self, tmp_path: Path
    ) -> None:
        """HIGH-D: SHOWING_RESULT 等の想定外 state からの IDLE 復帰を拒否。"""
        vm = ExExtractorViewModel(
            source_dir=tmp_path, facility_root_dir=tmp_path
        )
        vm.transition_to_busy()
        vm.transition_to_showing_result(ExtractionResult(items=()))
        with pytest.raises(RuntimeError, match="cannot transition to IDLE"):
            vm.transition_to_idle_with_error("OSError")

    def test_transition_to_idle_from_manual_distributing_ok(
        self, tmp_path: Path
    ) -> None:
        """HIGH-D: MANUAL_DISTRIBUTING からの IDLE 復帰は許容。"""
        vm = ExExtractorViewModel(
            source_dir=tmp_path, facility_root_dir=tmp_path
        )
        vm.transition_to_busy()
        vm.transition_to_showing_result(
            ExtractionResult(
                items=(_unmatched_item("a.ex_"),),
                pending_filenames=("a.ex_",),
            )
        )
        vm.transition_to_manual_distributing()
        vm.transition_to_idle_with_error("RuntimeError")
        assert vm.state is UiState.IDLE

    def test_can_open_manual_requires_pending(self, tmp_path: Path) -> None:
        vm = ExExtractorViewModel(
            source_dir=tmp_path, facility_root_dir=tmp_path
        )
        vm.transition_to_busy()
        # pending なし
        result = ExtractionResult(
            items=(_confirmed_item("a.ex_", "サービスA", tmp_path / "a.pdf"),)
        )
        vm.transition_to_showing_result(result)
        assert vm.can_open_manual is False

        # pending あり
        result_pending = ExtractionResult(
            items=(_unmatched_item("b.ex_"),),
            pending_filenames=("b.ex_",),
        )
        vm.state = UiState.BUSY
        vm.transition_to_showing_result(result_pending)
        assert vm.can_open_manual is True

    def test_transition_to_manual_distributing(self, tmp_path: Path) -> None:
        vm = ExExtractorViewModel(
            source_dir=tmp_path, facility_root_dir=tmp_path
        )
        vm.transition_to_busy()
        vm.transition_to_showing_result(
            ExtractionResult(
                items=(_unmatched_item("a.ex_"),),
                pending_filenames=("a.ex_",),
            )
        )
        vm.transition_to_manual_distributing()
        assert vm.state is UiState.MANUAL_DISTRIBUTING
        assert vm.is_busy is True

    def test_merge_manual_results_replaces_pending(self, tmp_path: Path) -> None:
        vm = ExExtractorViewModel(
            source_dir=tmp_path, facility_root_dir=tmp_path
        )
        vm.transition_to_busy()
        original_unmatched = _unmatched_item("a.ex_")
        confirmed_other = _confirmed_item("b.ex_", "サービスB", tmp_path / "b.pdf")
        vm.transition_to_showing_result(
            ExtractionResult(
                items=(original_unmatched, confirmed_other),
                pending_filenames=("a.ex_",),
            )
        )
        vm.transition_to_manual_distributing()

        # 手動振り分けで a.ex_ が SUCCESS になった
        manual = _manual_override_item("a.ex_", "サービスA", tmp_path / "a.pdf")
        vm.merge_manual_results((manual,))

        assert vm.state is UiState.SHOWING_RESULT
        assert vm.result is not None
        assert len(vm.result.items) == 2
        # source_path 一致で置換
        a_item = next(i for i in vm.result.items if i.source_path.name == "a.ex_")
        assert a_item.status is ExtractionStatus.SUCCESS
        assert a_item.resolve_result.reason is ResolveReason.MANUAL_OVERRIDE
        # pending_filenames は再計算されて空に
        assert vm.result.pending_filenames == ()


# ---------------------------------------------------------------------------
# get_summary_lines: PII-safe な件数表示 (5 件)
# ---------------------------------------------------------------------------


class TestSummaryLines:
    def test_empty_when_no_result(self, tmp_path: Path) -> None:
        vm = ExExtractorViewModel(
            source_dir=tmp_path, facility_root_dir=tmp_path
        )
        assert vm.get_summary_lines() == []

    def test_separates_auto_and_manual_override(self, tmp_path: Path) -> None:
        vm = ExExtractorViewModel(
            source_dir=tmp_path, facility_root_dir=tmp_path
        )
        result = ExtractionResult(
            items=(
                _confirmed_item("a.ex_", "サービスA", tmp_path / "a.pdf"),
                _manual_override_item("b.ex_", "サービスB", tmp_path / "b.pdf"),
                _manual_override_item("c.ex_", "サービスC", tmp_path / "c.pdf"),
            )
        )
        vm.state = UiState.SHOWING_RESULT
        vm.result = result

        lines = vm.get_summary_lines()
        # 自動 1, 手動 2 が分離表示される
        assert any("自動振り分け成功: 1 件" in line for line in lines)
        assert any("手動確定成功: 2 件" in line for line in lines)

    def test_summary_pii_safe_no_facility_name(self, tmp_path: Path) -> None:
        vm = ExExtractorViewModel(
            source_dir=tmp_path, facility_root_dir=tmp_path
        )
        result = ExtractionResult(
            items=(_confirmed_item("a.ex_", "PII機密事業所A", tmp_path / "a.pdf"),)
        )
        vm.state = UiState.SHOWING_RESULT
        vm.result = result

        all_text = "\n".join(vm.get_summary_lines())
        assert "PII機密事業所A" not in all_text  # 件数のみ表示

    def test_attention_count_for_partial_outputs(self, tmp_path: Path) -> None:
        partial_item = ExtractionItem(
            source_path=Path("p.ex_"),
            resolve_result=ResolveResult.confirmed(
                "サービスA", ResolveReason.ALIAS_MATCH
            ),
            status=ExtractionStatus.PARTIAL_OUTPUT,
            partial_outputs=(tmp_path / "half.pdf",),
            error_code=ExtractionErrorCode.SFX_TIMEOUT,
        )
        vm = ExExtractorViewModel(
            source_dir=tmp_path, facility_root_dir=tmp_path
        )
        vm.state = UiState.SHOWING_RESULT
        vm.result = ExtractionResult(items=(partial_item,))

        lines = vm.get_summary_lines()
        assert any("要確認" in line for line in lines)

    def test_orphan_alias_warning(self, tmp_path: Path) -> None:
        vm = ExExtractorViewModel(
            source_dir=tmp_path, facility_root_dir=tmp_path
        )
        vm.state = UiState.SHOWING_RESULT
        vm.result = ExtractionResult(
            items=(),
            orphan_alias_canonicals=("ゴースト施設X", "ゴースト施設Y"),
        )

        lines = vm.get_summary_lines()
        assert any("alias 設定不整合: 2 件" in line for line in lines)


# ---------------------------------------------------------------------------
# ExExtractorDialog smoke テスト (Tk required)
# ---------------------------------------------------------------------------


@pytest.mark.tk_required
class TestExExtractorDialogSmoke:
    def test_opens_with_unset_paths_and_run_disabled(
        self, tmp_path: Path
    ) -> None:
        import tkinter as tk

        config = AppConfig()
        # ex_source_dir / facility_root_dir 未設定
        adapter = FakeSfxAdapter()
        messagebox = MagicMock()

        root = tk.Tk()
        try:
            dialog = ExExtractorDialog(
                parent=root,
                config=config,
                adapter=adapter,
                messagebox_fn=messagebox,
            )
            # 未設定 → can_run False
            assert dialog.view_model.can_run is False
            dialog._on_close()
        finally:
            root.destroy()

    def test_opens_with_existing_paths_and_run_enabled(
        self, tmp_path: Path
    ) -> None:
        import tkinter as tk

        from wiseman_hub.config import PdfMergeConfig

        source = tmp_path / "ex_source"
        source.mkdir()
        root_dir = tmp_path / "facility_root"
        root_dir.mkdir()

        config = AppConfig(
            pdf_merge=PdfMergeConfig(
                ex_source_dir=str(source),
                facility_root_dir=str(root_dir),
            )
        )
        adapter = FakeSfxAdapter()

        root = tk.Tk()
        try:
            dialog = ExExtractorDialog(
                parent=root, config=config, adapter=adapter
            )
            assert dialog.view_model.can_run is True
            assert dialog.view_model.source_dir == source
            assert dialog.view_model.facility_root_dir == root_dir
            dialog._on_close()
        finally:
            root.destroy()

    def test_run_button_invokes_extract_fn_and_shows_result(
        self, tmp_path: Path
    ) -> None:
        import tkinter as tk

        from wiseman_hub.config import PdfMergeConfig

        source = tmp_path / "ex_source"
        source.mkdir()
        root_dir = tmp_path / "facility_root"
        root_dir.mkdir()

        config = AppConfig(
            pdf_merge=PdfMergeConfig(
                ex_source_dir=str(source),
                facility_root_dir=str(root_dir),
            )
        )

        called_args = {}

        def fake_extract(
            source_dir: Path,
            facility_root_dir: Path,
            aliases: dict[str, list[str]],
            adapter: object,
        ) -> ExtractionResult:
            called_args["source_dir"] = source_dir
            called_args["facility_root_dir"] = facility_root_dir
            return ExtractionResult(items=())

        root = tk.Tk()
        try:
            dialog = ExExtractorDialog(
                parent=root,
                config=config,
                adapter=FakeSfxAdapter(),
                extract_fn=fake_extract,
            )
            dialog._on_run_click()
            # worker thread 完了待ち
            dialog._executor.shutdown(wait=True)
            # main thread の after callback を pump
            root.update()
            root.update()

            assert called_args["source_dir"] == source
            assert dialog.view_model.state is UiState.SHOWING_RESULT
            dialog._on_close()
        finally:
            root.destroy()
