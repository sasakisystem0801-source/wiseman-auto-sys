"""事業所ルートフォルダ管理ダイアログ（W4）のテスト。

UI ロジックは ``FacilityRootViewModel`` に切り出してテストし、
Tk widget 部分（``FacilityRootManagerDialog``）は最小限の smoke テストに留める。

ViewModel テスト（pure Python）:
    - スキャン → 行リスト構築 + 既存ルート保存
    - 全選択 / 全解除（A_MISSING / A_MULTIPLE 未解決は selectable=False）
    - UI 文言マッピング（介護現場向け平易な日本語）
    - サマリ集計（選択中 / 実行不可 / 上書き）
    - A_MULTIPLE 解決
    - 実行可能 item の抽出（resolved_a_pdf 必須）
    - 実行後の状態反映

Dialog smoke テスト（@pytest.mark.tk_required）:
    - ルート未設定での起動 + メッセージ表示
    - ルート選択 → スキャン → 行表示
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from wiseman_hub.config import AppConfig
from wiseman_hub.pdf.facility_bulk_runner import (
    BulkExecutionItem,
    BulkExecutionStatus,
)
from wiseman_hub.pdf.facility_merger import FacilityMergeReport, UserMergeEntry
from wiseman_hub.pdf.facility_scanner import FacilityCandidate, FacilityStatus
from wiseman_hub.ui.facility_root_dialog import (
    FacilityRootViewModel,
    FacilityRow,
)

# -----------------------------------------------------------------------------
# テスト用ヘルパー
# -----------------------------------------------------------------------------


def _make_candidate(
    root: Path,
    name: str,
    *,
    status: FacilityStatus = FacilityStatus.PENDING,
    a_pdfs: tuple[str, ...] = ("提供実績.pdf",),
    has_existing_output: bool = False,
) -> FacilityCandidate:
    facility_dir = root / name
    a_pdf_path: Path | None = None
    a_pdf_candidates: tuple[Path, ...]
    if status == FacilityStatus.PENDING and a_pdfs:
        a_pdf_path = facility_dir / a_pdfs[0]
        a_pdf_candidates = (a_pdf_path,)
    elif status == FacilityStatus.A_MULTIPLE:
        a_pdf_candidates = tuple(facility_dir / n for n in a_pdfs)
    else:
        a_pdf_candidates = ()
    return FacilityCandidate(
        facility_dir=facility_dir,
        facility_name=name,
        status=status,
        a_pdf_path=a_pdf_path,
        a_pdf_candidates=a_pdf_candidates,
        output_pdf_path=facility_dir / f"{name}.pdf",
        has_existing_output=has_existing_output,
    )


# -----------------------------------------------------------------------------
# ViewModel: スキャンと行構築
# -----------------------------------------------------------------------------


class TestScan:
    def test_scan_populates_rows_with_pending_default_selected(
        self, tmp_path: Path
    ) -> None:
        """PENDING 行は selected=True がデフォルト（よくある一括処理ケース）。"""
        cands = [
            _make_candidate(tmp_path, "A施設"),
            _make_candidate(tmp_path, "B施設"),
        ]
        vm = FacilityRootViewModel()
        vm.set_root_and_rows(tmp_path, cands)

        assert len(vm.rows) == 2
        assert all(r.selected for r in vm.rows)

    def test_scan_marks_a_missing_and_a_multiple_as_not_selected(
        self, tmp_path: Path
    ) -> None:
        """A_MISSING / A_MULTIPLE は実行不可なのでデフォルト selected=False。"""
        cands = [
            _make_candidate(tmp_path, "PDFなし", status=FacilityStatus.A_MISSING),
            _make_candidate(
                tmp_path,
                "複数PDF",
                status=FacilityStatus.A_MULTIPLE,
                a_pdfs=("a.pdf", "b.pdf"),
            ),
        ]
        vm = FacilityRootViewModel()
        vm.set_root_and_rows(tmp_path, cands)

        assert vm.rows[0].selected is False
        assert vm.rows[1].selected is False

    def test_scan_clears_previous_rows(self, tmp_path: Path) -> None:
        """再スキャン時、古い行が残らない。"""
        vm = FacilityRootViewModel()
        vm.set_root_and_rows(tmp_path, [_make_candidate(tmp_path, "古い")])
        vm.set_root_and_rows(tmp_path, [_make_candidate(tmp_path, "新しい")])

        assert len(vm.rows) == 1
        assert vm.rows[0].candidate.facility_name == "新しい"


# -----------------------------------------------------------------------------
# 全選択 / 全解除
# -----------------------------------------------------------------------------


class TestSelectAll:
    def test_select_all_only_targets_pending(self, tmp_path: Path) -> None:
        """全選択 → PENDING のみ ON、A_MISSING/A_MULTIPLE は OFF のまま。"""
        cands = [
            _make_candidate(tmp_path, "A", status=FacilityStatus.A_MISSING),
            _make_candidate(tmp_path, "B"),
            _make_candidate(
                tmp_path,
                "C",
                status=FacilityStatus.A_MULTIPLE,
                a_pdfs=("x.pdf", "y.pdf"),
            ),
            _make_candidate(tmp_path, "D"),
        ]
        vm = FacilityRootViewModel()
        vm.set_root_and_rows(tmp_path, cands)
        for row in vm.rows:
            row.selected = False  # 一旦 OFF

        vm.select_all()

        assert vm.rows[0].selected is False  # A_MISSING
        assert vm.rows[1].selected is True  # PENDING
        assert vm.rows[2].selected is False  # A_MULTIPLE 未解決
        assert vm.rows[3].selected is True  # PENDING

    def test_select_all_includes_resolved_a_multiple(self, tmp_path: Path) -> None:
        """A_MULTIPLE をユーザーが解決済（selected_a_pdf あり）→ 全選択対象になる。"""
        cands = [
            _make_candidate(
                tmp_path,
                "解決済",
                status=FacilityStatus.A_MULTIPLE,
                a_pdfs=("x.pdf", "y.pdf"),
            ),
        ]
        vm = FacilityRootViewModel()
        vm.set_root_and_rows(tmp_path, cands)
        vm.rows[0].selected_a_pdf = cands[0].a_pdf_candidates[0]

        vm.select_all()

        assert vm.rows[0].selected is True

    def test_deselect_all(self, tmp_path: Path) -> None:
        cands = [
            _make_candidate(tmp_path, "A"),
            _make_candidate(tmp_path, "B"),
        ]
        vm = FacilityRootViewModel()
        vm.set_root_and_rows(tmp_path, cands)

        vm.deselect_all()

        assert all(r.selected is False for r in vm.rows)


# -----------------------------------------------------------------------------
# UI 文言マッピング（介護現場向け平易な日本語）
# -----------------------------------------------------------------------------


class TestDisplayStatus:
    def test_pending_label(self, tmp_path: Path) -> None:
        row = FacilityRow(candidate=_make_candidate(tmp_path, "A"))
        assert row.display_status == "実行待ち"

    def test_a_missing_label(self, tmp_path: Path) -> None:
        row = FacilityRow(
            candidate=_make_candidate(tmp_path, "A", status=FacilityStatus.A_MISSING)
        )
        assert "PDFがありません" in row.display_status

    def test_a_multiple_label(self, tmp_path: Path) -> None:
        row = FacilityRow(
            candidate=_make_candidate(
                tmp_path,
                "A",
                status=FacilityStatus.A_MULTIPLE,
                a_pdfs=("x.pdf", "y.pdf"),
            )
        )
        assert "複数" in row.display_status

    def test_running_label(self, tmp_path: Path) -> None:
        row = FacilityRow(candidate=_make_candidate(tmp_path, "A"))
        row.execution_status = BulkExecutionStatus.RUNNING
        assert row.display_status == "処理中…"

    def test_success_label(self, tmp_path: Path) -> None:
        row = FacilityRow(candidate=_make_candidate(tmp_path, "A"))
        row.execution_status = BulkExecutionStatus.SUCCESS
        row.success_count = 6
        assert "完了" in row.display_status
        assert "6" in row.display_status

    def test_partial_label(self, tmp_path: Path) -> None:
        row = FacilityRow(candidate=_make_candidate(tmp_path, "A"))
        row.execution_status = BulkExecutionStatus.PARTIAL
        assert "結合対象なし" in row.display_status

    def test_failed_locked_label(self, tmp_path: Path) -> None:
        row = FacilityRow(candidate=_make_candidate(tmp_path, "A"))
        row.execution_status = BulkExecutionStatus.FAILED_LOCKED
        row.error_message = "結合 PDF を閉じてから再実行してください"
        assert "閉じ" in row.display_status

    def test_failed_label_uses_error_message(self, tmp_path: Path) -> None:
        row = FacilityRow(candidate=_make_candidate(tmp_path, "A"))
        row.execution_status = BulkExecutionStatus.FAILED
        row.error_message = "OSError"
        assert "エラー" in row.display_status

    def test_cancelled_label(self, tmp_path: Path) -> None:
        row = FacilityRow(candidate=_make_candidate(tmp_path, "A"))
        row.execution_status = BulkExecutionStatus.CANCELLED_SKIPPED
        assert "停止" in row.display_status or "未処理" in row.display_status


# -----------------------------------------------------------------------------
# サマリ
# -----------------------------------------------------------------------------


class TestSummary:
    def test_summary_counts(self, tmp_path: Path) -> None:
        """選択中 / 実行不可 / 上書き予定 の集計。"""
        cands = [
            _make_candidate(tmp_path, "A"),  # PENDING, selected
            _make_candidate(tmp_path, "B"),  # PENDING, selected
            _make_candidate(tmp_path, "C", status=FacilityStatus.A_MISSING),
            _make_candidate(
                tmp_path,
                "D",
                status=FacilityStatus.A_MULTIPLE,
                a_pdfs=("x.pdf", "y.pdf"),
            ),
            _make_candidate(tmp_path, "E", has_existing_output=True),  # 上書き
        ]
        vm = FacilityRootViewModel()
        vm.set_root_and_rows(tmp_path, cands)

        summary = vm.summary()

        # PENDING で selected=True なもの: A, B, E = 3
        assert summary.selected_count == 3
        # 実行不可: A_MISSING (1) + 未解決 A_MULTIPLE (1) = 2
        assert summary.unrunnable_count == 2
        # 上書き予定（has_existing_output=True かつ selected）: E = 1
        assert summary.overwrite_count == 1

    def test_summary_overwrite_only_counts_selected(self, tmp_path: Path) -> None:
        """上書き予定は selected=True のもののみカウント。"""
        cands = [
            _make_candidate(tmp_path, "A", has_existing_output=True),
        ]
        vm = FacilityRootViewModel()
        vm.set_root_and_rows(tmp_path, cands)
        vm.rows[0].selected = False

        summary = vm.summary()

        assert summary.overwrite_count == 0


# -----------------------------------------------------------------------------
# A_MULTIPLE 解決
# -----------------------------------------------------------------------------


class TestResolveAMultiple:
    def test_resolve_with_valid_candidate(self, tmp_path: Path) -> None:
        """候補内のパスを選択 → selected_a_pdf がセット、selected=True に。"""
        cand = _make_candidate(
            tmp_path,
            "複数",
            status=FacilityStatus.A_MULTIPLE,
            a_pdfs=("x.pdf", "y.pdf"),
        )
        vm = FacilityRootViewModel()
        vm.set_root_and_rows(tmp_path, [cand])

        vm.resolve_a_multiple(0, cand.a_pdf_candidates[1])

        assert vm.rows[0].selected_a_pdf == cand.a_pdf_candidates[1]
        assert vm.rows[0].selected is True

    def test_resolve_with_invalid_candidate_raises(self, tmp_path: Path) -> None:
        """候補外のパスを指定 → ValueError（UI 側でユーザーに警告するため）。"""
        cand = _make_candidate(
            tmp_path,
            "複数",
            status=FacilityStatus.A_MULTIPLE,
            a_pdfs=("x.pdf", "y.pdf"),
        )
        vm = FacilityRootViewModel()
        vm.set_root_and_rows(tmp_path, [cand])

        with pytest.raises(ValueError, match="not in candidates"):
            vm.resolve_a_multiple(0, tmp_path / "全く別.pdf")


# -----------------------------------------------------------------------------
# 実行可能 item の抽出（runner への入力）
# -----------------------------------------------------------------------------


class TestExecutableItems:
    def test_only_selected_pending_yields_items(self, tmp_path: Path) -> None:
        """selected=True かつ resolved_a_pdf あり、のみが BulkExecutionItem になる。"""
        cands = [
            _make_candidate(tmp_path, "A"),  # PENDING, selected
            _make_candidate(tmp_path, "B", status=FacilityStatus.A_MISSING),
            _make_candidate(
                tmp_path,
                "C",
                status=FacilityStatus.A_MULTIPLE,
                a_pdfs=("x.pdf", "y.pdf"),
            ),
            _make_candidate(tmp_path, "D"),  # PENDING, will deselect
        ]
        vm = FacilityRootViewModel()
        vm.set_root_and_rows(tmp_path, cands)
        vm.rows[3].selected = False

        items = vm.build_executable_items()

        # A のみが対象
        assert len(items) == 1
        assert items[0].candidate.facility_name == "A"
        assert items[0].a_pdf_path == cands[0].a_pdf_path
        assert items[0].output_root == tmp_path

    def test_resolved_a_multiple_yields_item_with_selected_path(
        self, tmp_path: Path
    ) -> None:
        """A_MULTIPLE 解決済の selected_a_pdf が item.a_pdf_path として渡る。"""
        cand = _make_candidate(
            tmp_path,
            "複数",
            status=FacilityStatus.A_MULTIPLE,
            a_pdfs=("x.pdf", "y.pdf"),
        )
        vm = FacilityRootViewModel()
        vm.set_root_and_rows(tmp_path, [cand])
        vm.resolve_a_multiple(0, cand.a_pdf_candidates[1])

        items = vm.build_executable_items()

        assert len(items) == 1
        assert items[0].a_pdf_path == cand.a_pdf_candidates[1]


# -----------------------------------------------------------------------------
# 実行後の状態反映
# -----------------------------------------------------------------------------


class TestApplyItemUpdateMismatch:
    """`apply_item_update` で facility_dir が一致しない場合の挙動。

    review 指摘 (silent-failure-hunter HIGH-1): 不一致時に silent return すると、
    実行中再スキャン等の race で UI が「処理中…」のまま固まるリスク。
    warning ログを出して fail-loud にする。
    """

    def test_unmatched_item_does_not_raise_and_logs_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        vm = FacilityRootViewModel()
        vm.set_root_and_rows(tmp_path, [_make_candidate(tmp_path, "実在")])

        # 別ルートの candidate（rows に存在しない）
        stranger_root = tmp_path / "別ルート"
        stranger_root.mkdir()
        stranger = _make_candidate(stranger_root, "幽霊事業所")
        stray_item = BulkExecutionItem(
            candidate=stranger,
            a_pdf_path=stranger_root / "a.pdf",
            output_root=stranger_root,
            status=BulkExecutionStatus.SUCCESS,
        )

        with caplog.at_level(
            logging.WARNING, logger="wiseman_hub.ui.facility_root_dialog"
        ):
            vm.apply_item_update(stray_item)  # 例外なくサイレント return せず警告

        # 元の row には影響がない
        assert vm.rows[0].execution_status is None
        # warning ログに facility_name が記録される（PII 防御で type 名のみ）
        logged = " ".join(r.getMessage() for r in caplog.records)
        assert "no row matches" in logged or "rows replaced" in logged


class TestUpdateAfterExecution:
    def test_apply_runner_result_updates_row_status(self, tmp_path: Path) -> None:
        """runner の戻り値を ViewModel に反映 → 該当行の execution_status が更新される。"""
        cand = _make_candidate(tmp_path, "A")
        vm = FacilityRootViewModel()
        vm.set_root_and_rows(tmp_path, [cand])

        item = BulkExecutionItem(
            candidate=cand,
            a_pdf_path=cand.a_pdf_path or Path("/dummy"),
            output_root=tmp_path,
            status=BulkExecutionStatus.SUCCESS,
            report=FacilityMergeReport(
                facility_name="A",
                output_dir=tmp_path / "A",
                success=(
                    UserMergeEntry(
                        user_key="x",
                        full_name="xy",
                        sources_used=("A", "B", "C"),
                        output_path=tmp_path / "A" / "A.pdf",
                    ),
                ),
            ),
        )
        vm.apply_item_update(item)

        assert vm.rows[0].execution_status == BulkExecutionStatus.SUCCESS
        assert vm.rows[0].success_count == 1

    def test_apply_failed_locked_propagates_message(self, tmp_path: Path) -> None:
        cand = _make_candidate(tmp_path, "A")
        vm = FacilityRootViewModel()
        vm.set_root_and_rows(tmp_path, [cand])

        item = BulkExecutionItem(
            candidate=cand,
            a_pdf_path=cand.a_pdf_path or Path("/dummy"),
            output_root=tmp_path,
            status=BulkExecutionStatus.FAILED_LOCKED,
            error_message="結合 PDF を閉じてから再実行してください",
        )
        vm.apply_item_update(item)

        assert vm.rows[0].execution_status == BulkExecutionStatus.FAILED_LOCKED
        assert vm.rows[0].error_message is not None
        assert "閉じ" in vm.rows[0].error_message


# -----------------------------------------------------------------------------
# 既存出力の存在判定（PDF を開くボタン活性化）
# -----------------------------------------------------------------------------


class TestOpenOutputAvailable:
    def test_output_pdf_button_enabled_when_existing_output(
        self, tmp_path: Path
    ) -> None:
        """初期スキャン時点で既存出力あり → 「PDFを開く」ボタン活性化。"""
        cand = _make_candidate(tmp_path, "A", has_existing_output=True)
        row = FacilityRow(candidate=cand)
        assert row.can_open_output_pdf is True

    def test_output_pdf_button_disabled_when_no_output(self, tmp_path: Path) -> None:
        cand = _make_candidate(tmp_path, "A", has_existing_output=False)
        row = FacilityRow(candidate=cand)
        assert row.can_open_output_pdf is False

    def test_output_pdf_button_enabled_after_success(self, tmp_path: Path) -> None:
        """実行 SUCCESS 後 → 出力 PDF ができたので開けるようになる。"""
        cand = _make_candidate(tmp_path, "A", has_existing_output=False)
        row = FacilityRow(candidate=cand)
        row.execution_status = BulkExecutionStatus.SUCCESS

        assert row.can_open_output_pdf is True


# -----------------------------------------------------------------------------
# 設定の永続化との結合（save_config を介して root_dir が保存される）
# -----------------------------------------------------------------------------


class TestPersistRoot:
    def test_set_root_writes_to_config(self, tmp_path: Path) -> None:
        """ViewModel 経由で root を設定すると AppConfig.pdf_merge.facility_root_dir が更新される。"""
        cfg = AppConfig()
        vm = FacilityRootViewModel(config=cfg)

        vm.set_root_and_rows(tmp_path, [])

        assert cfg.pdf_merge.facility_root_dir == str(tmp_path)

    def test_set_root_does_not_modify_other_fields(self, tmp_path: Path) -> None:
        """root 更新で既存フィールドが変わらない（Partial Update）。"""
        cfg = AppConfig()
        cfg.pdf_merge.input_dir = "/keep_in"
        cfg.pdf_merge.output_dir = "/keep_out"
        cfg.pdf_merge.source_a_filename = "keep.pdf"
        cfg = replace(cfg)
        vm = FacilityRootViewModel(config=cfg)

        vm.set_root_and_rows(tmp_path, [])

        assert vm.config.pdf_merge.input_dir == "/keep_in"
        assert vm.config.pdf_merge.output_dir == "/keep_out"
        assert vm.config.pdf_merge.source_a_filename == "keep.pdf"
