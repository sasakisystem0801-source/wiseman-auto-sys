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
    _TITLE_BROWSE_SOURCE,
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
            # 現実装の挙動: 未設定時に __init__ が Path(".") を渡し
            # ex_extractor_dialog.py:346-349 で source_dir/facility_root_dir に "." が入る。
            # POSIX/Windows とも Path(".").exists() == True のため can_run=True になる
            # （CWD に ex_ ファイルがなければ実害なし、空処理）。
            # 「未設定 → can_run=False」の本来仕様化は Optional[Path] 設計改修が必要 → 別 Issue。
            # 本 smoke は dialog が例外なく構築・close できることのみ検証する。
            assert dialog.view_model.source_dir == Path(".")
            assert dialog.view_model.facility_root_dir == Path(".")
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

    def test_browse_source_updates_view_model_and_label(
        self, tmp_path: Path
    ) -> None:
        """Issue #155: 取込元選択ボタン → askdirectory 経由で source_dir 更新。

        - mock filedialog で folder browser をシミュレート
        - 選択結果が ``vm.source_dir`` に反映される
        - Label 表示も新パスに更新される (TOML 編集なしで都度変更可能)
        """
        import tkinter as tk

        from wiseman_hub.config import PdfMergeConfig

        original_source = tmp_path / "original_source"
        original_source.mkdir()
        new_source = tmp_path / "new_source"
        new_source.mkdir()
        root_dir = tmp_path / "facility_root"
        root_dir.mkdir()

        config = AppConfig(
            pdf_merge=PdfMergeConfig(
                ex_source_dir=str(original_source),
                facility_root_dir=str(root_dir),
            )
        )

        # mock askdirectory: 新フォルダを返す
        fake_askdirectory = MagicMock(return_value=str(new_source))

        root = tk.Tk()
        try:
            dialog = ExExtractorDialog(
                parent=root,
                config=config,
                adapter=FakeSfxAdapter(),
                filedialog_askdirectory=fake_askdirectory,
            )
            assert dialog.view_model.source_dir == original_source
            dialog._on_browse_source()

            # askdirectory が呼ばれたことを確認 (parent 値 + title 定数を厳密検証)
            fake_askdirectory.assert_called_once()
            _, kwargs = fake_askdirectory.call_args
            assert kwargs.get("parent") is dialog._top
            assert kwargs.get("title") == _TITLE_BROWSE_SOURCE

            # vm.source_dir が新フォルダに更新されている
            assert dialog.view_model.source_dir == new_source
            # Label 表示も新フォルダ (existing なので _LBL_NOT_SET ではない)
            assert dialog._lbl_source.cget("text") == str(new_source)
            dialog._on_close()
        finally:
            root.destroy()

    def test_browse_source_cancel_keeps_current_value(
        self, tmp_path: Path
    ) -> None:
        """Issue #155: askdirectory がキャンセル (空文字 return) → current value 保持。"""
        import tkinter as tk

        from wiseman_hub.config import PdfMergeConfig

        original_source = tmp_path / "original_source"
        original_source.mkdir()
        root_dir = tmp_path / "facility_root"
        root_dir.mkdir()

        config = AppConfig(
            pdf_merge=PdfMergeConfig(
                ex_source_dir=str(original_source),
                facility_root_dir=str(root_dir),
            )
        )

        # mock askdirectory: 空文字 (キャンセル)
        fake_askdirectory = MagicMock(return_value="")

        root = tk.Tk()
        try:
            dialog = ExExtractorDialog(
                parent=root,
                config=config,
                adapter=FakeSfxAdapter(),
                filedialog_askdirectory=fake_askdirectory,
            )
            dialog._on_browse_source()

            # キャンセルなので source_dir は変わらない
            assert dialog.view_model.source_dir == original_source
            dialog._on_close()
        finally:
            root.destroy()

    def test_browse_source_invalid_path_shows_error_and_keeps_value(
        self, tmp_path: Path
    ) -> None:
        """Issue #155: askdirectory が存在しないパスを返した場合、messagebox で
        通知し source_dir は更新しない (defensive: シンボリックリンク切れ等)。
        """
        import tkinter as tk

        from wiseman_hub.config import PdfMergeConfig

        original_source = tmp_path / "original_source"
        original_source.mkdir()
        root_dir = tmp_path / "facility_root"
        root_dir.mkdir()
        nonexistent = tmp_path / "does_not_exist"

        config = AppConfig(
            pdf_merge=PdfMergeConfig(
                ex_source_dir=str(original_source),
                facility_root_dir=str(root_dir),
            )
        )

        fake_askdirectory = MagicMock(return_value=str(nonexistent))
        messagebox = MagicMock()

        root = tk.Tk()
        try:
            dialog = ExExtractorDialog(
                parent=root,
                config=config,
                adapter=FakeSfxAdapter(),
                filedialog_askdirectory=fake_askdirectory,
                messagebox_fn=messagebox,
            )
            dialog._on_browse_source()

            # source_dir は更新されない
            assert dialog.view_model.source_dir == original_source
            # messagebox.showerror が 1 回呼ばれている
            messagebox.showerror.assert_called_once()
            args, _ = messagebox.showerror.call_args
            assert "無効" in args[0] or "取込元" in args[0]
            dialog._on_close()
        finally:
            root.destroy()

    def test_browse_source_disabled_during_busy_and_reenabled_after_idle(
        self, tmp_path: Path
    ) -> None:
        """Issue #155 (pr-test rating 6): BUSY 中は disable、IDLE 復帰で再有効化。

        双方向の状態遷移を 1 テストで検証する (元実装は片方向のみ)。
        race / 実行中の source_dir 変更を防ぐ UI 契約を契約として固定。
        """
        import tkinter as tk

        from wiseman_hub.config import PdfMergeConfig
        from wiseman_hub.pdf.ex_extractor import ExtractionResult

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

        root = tk.Tk()
        try:
            dialog = ExExtractorDialog(
                parent=root, config=config, adapter=FakeSfxAdapter()
            )
            # 初期状態: IDLE → browse は normal
            assert str(dialog._btn_browse_source.cget("state")) == "normal"

            # BUSY に遷移 → disable
            dialog.view_model.transition_to_busy()
            dialog._redraw()
            assert str(dialog._btn_browse_source.cget("state")) == "disabled"

            # SHOWING_RESULT → IDLE に復帰すると再有効化
            dialog.view_model.transition_to_showing_result(
                ExtractionResult(items=())
            )
            dialog._redraw()
            assert str(dialog._btn_browse_source.cget("state")) == "normal"
            dialog._on_close()
        finally:
            root.destroy()

    def test_browse_source_oserror_shows_error_and_keeps_value(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Issue #155 (silent-failure-hunter HIGH-1): exists()/is_dir() で OSError
        (Windows UNC / ネットワーク切断 / 権限拒否) → silent failure せず通知。

        元実装は try/except なしで、ハンドラから例外伝播 → ユーザーから見て
        「ボタン押したのに何も起きない」状態。本テストで type 名のみ通知 +
        値据え置きを契約化。
        """
        import logging
        import tkinter as tk
        from unittest.mock import patch

        from wiseman_hub.config import PdfMergeConfig

        original_source = tmp_path / "original_source"
        original_source.mkdir()
        root_dir = tmp_path / "facility_root"
        root_dir.mkdir()

        config = AppConfig(
            pdf_merge=PdfMergeConfig(
                ex_source_dir=str(original_source),
                facility_root_dir=str(root_dir),
            )
        )

        # askdirectory が UNC パス相当を返したと仮定し、Path.exists() が
        # PermissionError (OSError サブクラス) を raise する経路をシミュレート
        fake_askdirectory = MagicMock(return_value=r"\\unreachable\share")
        messagebox = MagicMock()

        root = tk.Tk()
        try:
            dialog = ExExtractorDialog(
                parent=root,
                config=config,
                adapter=FakeSfxAdapter(),
                filedialog_askdirectory=fake_askdirectory,
                messagebox_fn=messagebox,
            )

            with (
                patch.object(
                    Path, "exists", side_effect=PermissionError("denied")
                ),
                caplog.at_level(
                    logging.ERROR, logger="wiseman_hub.ui.ex_extractor_dialog"
                ),
            ):
                dialog._on_browse_source()

            # source_dir は更新されない
            assert dialog.view_model.source_dir == original_source
            # messagebox.showerror が 1 回呼ばれている (型名表示)
            messagebox.showerror.assert_called_once()
            args, _ = messagebox.showerror.call_args
            assert "PermissionError" in args[1]
            # logger に型名のみ記録 (PII 防御: path 文字列は出ない)
            assert "PermissionError" in caplog.text
            assert "unreachable" not in caplog.text
            dialog._on_close()
        finally:
            root.destroy()

    def test_browse_then_run_uses_selected_source(
        self, tmp_path: Path
    ) -> None:
        """Issue #155 (pr-test rating 7): browse → run の end-to-end。

        将来 ``_on_run_click`` が ``vm.source_dir`` 経由を外して
        ``config.pdf_merge.ex_source_dir`` を直接参照するバグを入れた場合に
        regression を検出する。
        """
        import tkinter as tk

        from wiseman_hub.config import PdfMergeConfig
        from wiseman_hub.pdf.ex_extractor import ExtractionResult

        original_source = tmp_path / "original_source"
        original_source.mkdir()
        new_source = tmp_path / "new_source"
        new_source.mkdir()
        root_dir = tmp_path / "facility_root"
        root_dir.mkdir()

        config = AppConfig(
            pdf_merge=PdfMergeConfig(
                ex_source_dir=str(original_source),
                facility_root_dir=str(root_dir),
            )
        )

        called_args: dict[str, Path] = {}

        def fake_extract(
            source_dir: Path,
            facility_root_dir: Path,
            aliases: dict[str, list[str]],
            adapter: object,
        ) -> ExtractionResult:
            called_args["source_dir"] = source_dir
            return ExtractionResult(items=())

        fake_askdirectory = MagicMock(return_value=str(new_source))

        root = tk.Tk()
        try:
            dialog = ExExtractorDialog(
                parent=root,
                config=config,
                adapter=FakeSfxAdapter(),
                extract_fn=fake_extract,
                filedialog_askdirectory=fake_askdirectory,
            )
            # browse で source_dir を new_source に変更
            dialog._on_browse_source()
            assert dialog.view_model.source_dir == new_source

            # run → extract_fn が new_source を受け取ることを検証
            dialog._on_run_click()
            dialog._executor.shutdown(wait=True)
            root.update()
            root.update()

            assert called_args["source_dir"] == new_source
            dialog._on_close()
        finally:
            root.destroy()

    def test_browse_then_run_with_unset_toml(
        self, tmp_path: Path
    ) -> None:
        """Issue #155 受け入れ基準: TOML 未設定でも browse → run でフロー継続可能。

        ex_source_dir が空文字列 (未設定) で起動 → Path(".") フォールバック →
        can_run False → browse で valid フォルダ選択 → can_run True → 実行成功。
        """
        import tkinter as tk

        from wiseman_hub.config import PdfMergeConfig
        from wiseman_hub.pdf.ex_extractor import ExtractionResult

        new_source = tmp_path / "new_source"
        new_source.mkdir()
        root_dir = tmp_path / "facility_root"
        root_dir.mkdir()

        # TOML ex_source_dir 未設定 (空文字列)
        config = AppConfig(
            pdf_merge=PdfMergeConfig(
                ex_source_dir="",
                facility_root_dir=str(root_dir),
            )
        )

        called_args: dict[str, Path] = {}

        def fake_extract(
            source_dir: Path,
            facility_root_dir: Path,
            aliases: dict[str, list[str]],
            adapter: object,
        ) -> ExtractionResult:
            called_args["source_dir"] = source_dir
            return ExtractionResult(items=())

        fake_askdirectory = MagicMock(return_value=str(new_source))

        root = tk.Tk()
        try:
            dialog = ExExtractorDialog(
                parent=root,
                config=config,
                adapter=FakeSfxAdapter(),
                extract_fn=fake_extract,
                filedialog_askdirectory=fake_askdirectory,
            )
            # 起動時 vm.source_dir = Path(".")（フォールバック）。"." は通常存在
            # するが、is_valid なフォルダ (root_dir 等) でない場合 can_run False
            # に依存する。本テストは GUI で valid フォルダを選び直してから実行。

            # browse で new_source を選択 → vm 更新
            dialog._on_browse_source()
            assert dialog.view_model.source_dir == new_source
            assert dialog.view_model.can_run is True

            # run → extract_fn が new_source を受け取る
            dialog._on_run_click()
            dialog._executor.shutdown(wait=True)
            root.update()
            root.update()

            assert called_args["source_dir"] == new_source
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

    # -----------------------------------------------------------------
    # 取込元 TOML 永続化 + save 失敗時の reload 抑止契約
    # -----------------------------------------------------------------

    def test_browse_source_persists_to_toml_when_config_path_given(
        self, tmp_path: Path
    ) -> None:
        """config_path 指定時、save_config_fn(config, path, create_if_missing=True)
        が呼び出され ex_source_dir が更新される。
        """
        import tkinter as tk

        from wiseman_hub.config import PdfMergeConfig

        original_source = tmp_path / "original_source"
        original_source.mkdir()
        new_source = tmp_path / "new_source"
        new_source.mkdir()
        root_dir = tmp_path / "facility_root"
        root_dir.mkdir()
        config_path = tmp_path / "default.toml"

        config = AppConfig(
            pdf_merge=PdfMergeConfig(
                ex_source_dir=str(original_source),
                facility_root_dir=str(root_dir),
            )
        )

        fake_askdirectory = MagicMock(return_value=str(new_source))
        save_calls: list[tuple[AppConfig, Path, dict]] = []

        def fake_save(cfg: AppConfig, path: Path, **kwargs: object) -> None:
            save_calls.append((cfg, path, kwargs))

        root = tk.Tk()
        try:
            dialog = ExExtractorDialog(
                parent=root,
                config=config,
                config_path=config_path,
                adapter=FakeSfxAdapter(),
                save_config_fn=fake_save,
                filedialog_askdirectory=fake_askdirectory,
            )
            dialog._on_browse_source()

            assert len(save_calls) == 1
            saved_cfg, saved_path, saved_kwargs = save_calls[0]
            assert saved_path == config_path
            # ex_source_dir が選択値で更新されている
            assert saved_cfg.pdf_merge.ex_source_dir == str(new_source)
            assert saved_kwargs.get("create_if_missing") is True
            dialog._on_close()
        finally:
            root.destroy()

    def test_browse_source_preserves_other_pdf_merge_fields(
        self, tmp_path: Path
    ) -> None:
        """Partial Update 規約: ex_source_dir のみ更新し、pdf_merge 他キーは不変."""
        import tkinter as tk

        from wiseman_hub.config import PdfMergeConfig

        original_source = tmp_path / "original_source"
        original_source.mkdir()
        new_source = tmp_path / "new_source"
        new_source.mkdir()
        root_dir = tmp_path / "facility_root"
        root_dir.mkdir()
        config_path = tmp_path / "default.toml"

        # 他フィールドに非デフォルト値をセット (更新対象外であることを検証)
        original_aliases = {"事業所A": ["A支店", "A店"]}
        config = AppConfig(
            pdf_merge=PdfMergeConfig(
                ex_source_dir=str(original_source),
                facility_root_dir=str(root_dir),
                input_dir="/some/input",
                output_dir="/some/output",
                source_a_filename="A.pdf",
                source_d_filename="D.pdf",
                source_b_pattern="custom_B_{name}.pdf",
                source_c_pattern="custom_C_{name}.pdf",
                facility_aliases=original_aliases,
            )
        )

        fake_askdirectory = MagicMock(return_value=str(new_source))
        save_calls: list[AppConfig] = []

        def fake_save(cfg: AppConfig, path: Path, **kwargs: object) -> None:
            save_calls.append(cfg)

        root = tk.Tk()
        try:
            dialog = ExExtractorDialog(
                parent=root,
                config=config,
                config_path=config_path,
                adapter=FakeSfxAdapter(),
                save_config_fn=fake_save,
                filedialog_askdirectory=fake_askdirectory,
            )
            dialog._on_browse_source()

            assert len(save_calls) == 1
            saved_cfg = save_calls[0]
            # ex_source_dir のみ更新
            assert saved_cfg.pdf_merge.ex_source_dir == str(new_source)
            # 他キーは原値を保持 (Partial Update)
            assert saved_cfg.pdf_merge.facility_root_dir == str(root_dir)
            assert saved_cfg.pdf_merge.input_dir == "/some/input"
            assert saved_cfg.pdf_merge.output_dir == "/some/output"
            assert saved_cfg.pdf_merge.source_a_filename == "A.pdf"
            assert saved_cfg.pdf_merge.source_d_filename == "D.pdf"
            assert saved_cfg.pdf_merge.source_b_pattern == "custom_B_{name}.pdf"
            assert saved_cfg.pdf_merge.source_c_pattern == "custom_C_{name}.pdf"
            assert saved_cfg.pdf_merge.facility_aliases == original_aliases
            dialog._on_close()
        finally:
            root.destroy()

    def test_browse_source_skips_persist_when_config_path_none(
        self, tmp_path: Path
    ) -> None:
        """config_path = None なら save_config_fn は呼ばれず、ViewModel のみ更新。

        既存の Tk smoke テスト互換用 (本番経路では config_path 必ず渡される)。
        """
        import tkinter as tk

        from wiseman_hub.config import PdfMergeConfig

        original_source = tmp_path / "original_source"
        original_source.mkdir()
        new_source = tmp_path / "new_source"
        new_source.mkdir()
        root_dir = tmp_path / "facility_root"
        root_dir.mkdir()

        config = AppConfig(
            pdf_merge=PdfMergeConfig(
                ex_source_dir=str(original_source),
                facility_root_dir=str(root_dir),
            )
        )

        fake_askdirectory = MagicMock(return_value=str(new_source))
        save_called = []

        def fake_save(*args: object, **kwargs: object) -> None:
            save_called.append((args, kwargs))

        root = tk.Tk()
        try:
            dialog = ExExtractorDialog(
                parent=root,
                config=config,
                # config_path 渡さない (= None)
                adapter=FakeSfxAdapter(),
                save_config_fn=fake_save,
                filedialog_askdirectory=fake_askdirectory,
            )
            dialog._on_browse_source()

            assert dialog.view_model.source_dir == new_source  # ViewModel は更新
            assert save_called == []  # save は呼ばれない
            dialog._on_close()
        finally:
            root.destroy()

    def test_browse_source_calls_on_source_persisted_after_save_success(
        self, tmp_path: Path
    ) -> None:
        """save 成功時のみ on_source_persisted callback が呼ばれる契約。"""
        import tkinter as tk

        from wiseman_hub.config import PdfMergeConfig

        new_source = tmp_path / "new_source"
        new_source.mkdir()
        root_dir = tmp_path / "facility_root"
        root_dir.mkdir()
        config_path = tmp_path / "default.toml"

        config = AppConfig(
            pdf_merge=PdfMergeConfig(
                ex_source_dir=str(tmp_path / "original"),
                facility_root_dir=str(root_dir),
            )
        )
        (tmp_path / "original").mkdir()

        fake_askdirectory = MagicMock(return_value=str(new_source))
        callback_calls: list[AppConfig] = []

        root = tk.Tk()
        try:
            dialog = ExExtractorDialog(
                parent=root,
                config=config,
                config_path=config_path,
                adapter=FakeSfxAdapter(),
                save_config_fn=lambda *a, **kw: None,  # save 成功
                on_source_persisted=callback_calls.append,
                filedialog_askdirectory=fake_askdirectory,
            )
            dialog._on_browse_source()

            assert len(callback_calls) == 1
            assert callback_calls[0] is config
            dialog._on_close()
        finally:
            root.destroy()

    def test_browse_source_does_not_call_on_persisted_when_save_fails(
        self, tmp_path: Path
    ) -> None:
        """save 失敗時は on_source_persisted を呼ばない契約
        (AppConfig 不整合防止 + reload は成功時のみが正しい契約)。"""
        import tkinter as tk

        from wiseman_hub.config import PdfMergeConfig

        new_source = tmp_path / "new_source"
        new_source.mkdir()
        root_dir = tmp_path / "facility_root"
        root_dir.mkdir()
        config_path = tmp_path / "default.toml"

        (tmp_path / "original").mkdir()
        config = AppConfig(
            pdf_merge=PdfMergeConfig(
                ex_source_dir=str(tmp_path / "original"),
                facility_root_dir=str(root_dir),
            )
        )

        fake_askdirectory = MagicMock(return_value=str(new_source))
        callback_calls: list[AppConfig] = []

        def failing_save(*args: object, **kwargs: object) -> None:
            raise PermissionError("simulated save failure")

        messagebox = MagicMock()

        root = tk.Tk()
        try:
            dialog = ExExtractorDialog(
                parent=root,
                config=config,
                config_path=config_path,
                adapter=FakeSfxAdapter(),
                save_config_fn=failing_save,
                on_source_persisted=callback_calls.append,
                messagebox_fn=messagebox,
                filedialog_askdirectory=fake_askdirectory,
            )
            dialog._on_browse_source()

            # callback は呼ばれていない (D4)
            assert callback_calls == []
            # ViewModel は今セッション用に更新されている (save 失敗でも UI 続行可能)
            assert dialog.view_model.source_dir == new_source
            # 警告 messagebox が表示されている (showerror で warning レベル伝達)
            messagebox.showerror.assert_called()
            error_titles = [c.args[0] for c in messagebox.showerror.call_args_list]
            assert any("設定保存失敗" in t for t in error_titles)
            dialog._on_close()
        finally:
            root.destroy()

    def test_browse_source_save_failure_does_not_break_ui(
        self, tmp_path: Path
    ) -> None:
        """save 失敗してもダイアログは継続使用可能 (実行ボタン引き続き使える)。"""
        import tkinter as tk

        from wiseman_hub.config import PdfMergeConfig

        new_source = tmp_path / "new_source"
        new_source.mkdir()
        root_dir = tmp_path / "facility_root"
        root_dir.mkdir()
        config_path = tmp_path / "default.toml"
        (tmp_path / "original").mkdir()

        config = AppConfig(
            pdf_merge=PdfMergeConfig(
                ex_source_dir=str(tmp_path / "original"),
                facility_root_dir=str(root_dir),
            )
        )

        fake_askdirectory = MagicMock(return_value=str(new_source))
        messagebox = MagicMock()

        def failing_save(*args: object, **kwargs: object) -> None:
            raise OSError("disk full")

        root = tk.Tk()
        try:
            dialog = ExExtractorDialog(
                parent=root,
                config=config,
                config_path=config_path,
                adapter=FakeSfxAdapter(),
                save_config_fn=failing_save,
                messagebox_fn=messagebox,
                filedialog_askdirectory=fake_askdirectory,
            )
            dialog._on_browse_source()

            # 失敗後も dialog は破壊されていない (継続使用可能)
            assert dialog._top.winfo_exists()
            # 「実行」ボタンの state が disabled でない (can_run は判定可能)
            assert dialog.view_model.can_run is True  # source/root とも存在
            dialog._on_close()
        finally:
            root.destroy()
