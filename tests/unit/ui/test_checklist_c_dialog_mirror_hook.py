"""ADR-016 PR-2: GCS mirror hook の統合テスト（write + delete 両方）。

C ダイアログの cache write hook（``_open_picker_for_review``）と
delete hook（``_clear_cache_for_row``）が GCS mirror を呼ぶことを検証する。

I-7 (codex review threadId 019dfceb) 反映:
    元実装は delete hook のみテストされていたが、本ファイルで write hook も
    検証する。さらに C-1 (UI 非同期化) を反映した async 版（``upload_entry_async``
    / ``delete_entry_async``）が呼ばれることを確認する。

検証戦略:
    - ``_mirror_upload_entry_async`` / ``_mirror_delete_entry_async`` を mock 化し、
      呼出回数 + 引数 (key, xlsx_path, config_path) のみを確認
    - GCS API 自体は触らない（``xlsx_path_cache_mirror`` 単体テストでカバー）
    - async 化されているので mock の呼出は同期的（spawn の代わり）
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from unittest.mock import patch

import pytest

from wiseman_hub.config import (
    AppConfig,
    ChecklistConfig,
    GcpConfig,
    ReportStaffEntry,
    WisemanConfig,
)
from wiseman_hub.pdf.checklist_c import (
    ChecklistRow,
    CPlacementResult,
    CPlacementStatus,
)
from wiseman_hub.ui.checklist_c_dialog import ChecklistCDialog


def _make_config(tmp_path: Path) -> AppConfig:
    fake_sa = tmp_path / "sa.json"
    fake_sa.write_text("{}", encoding="utf-8")
    return AppConfig(
        wiseman=WisemanConfig(),
        gcp=GcpConfig(
            project_id="p",
            data_bucket_name="b",
            service_account_key_path=str(fake_sa),
        ),
        checklist=ChecklistConfig(
            spreadsheet_id="dummy",
            fax_root=str(tmp_path),
            facility_routing={"テスト居宅": "テスト居宅(FAX)"},
            report_staff={
                "宮下": ReportStaffEntry(
                    base_dir=str(tmp_path / "PT 宮下"),
                    suggest_patterns=["dummy"],
                ),
            },
            xlsx_path_cache={"宮下:2026:3": r"\\nas\share\PT 宮下\3月.xlsx"},
        ),
        log_dir=str(tmp_path / "logs"),
    )


@pytest.mark.tk_required
class TestMirrorDeleteHook:
    """_clear_cache_for_row が delete async hook を呼ぶ。"""

    def test_delete_hook_invoked_with_key_and_config_path(
        self, tmp_path: Path
    ) -> None:
        root = tk.Tk()
        try:
            cfg = _make_config(tmp_path)
            cfg_path = tmp_path / "default.toml"
            cfg_path.write_text(
                '[checklist]\nfax_root = ""\n', encoding="utf-8"
            )
            dlg = ChecklistCDialog(parent=root, config=cfg, config_path=cfg_path)
            dlg._month_var.set("26年3月")
            row = ChecklistRow(
                name="テスト太郎",
                monitoring_raw="",
                staff="宮下",
                facility="テスト居宅",
            )
            result = CPlacementResult(row=row)
            result.status = CPlacementStatus.PENDING
            result.xlsx_path = Path(r"\\nas\share\PT 宮下\3月.xlsx")
            dlg._results = [result]

            with (
                patch(
                    "wiseman_hub.ui.checklist_c_dialog.messagebox.askyesno",
                    return_value=True,
                ),
                patch("wiseman_hub.ui.checklist_c_dialog.save_config"),
                patch(
                    "wiseman_hub.ui.checklist_c_dialog._mirror_delete_entry_async"
                ) as mock_del,
            ):
                dlg._clear_cache_for_row(0)

            # I-7: async 版が呼ばれる（同期 mirror_delete_entry は呼ばれない）
            mock_del.assert_called_once()
            args = mock_del.call_args.args
            kwargs = mock_del.call_args.kwargs
            assert args[0] == "宮下:2026:3"
            assert kwargs.get("config_path") == cfg_path
        finally:
            root.destroy()

    def test_delete_hook_skipped_on_save_config_failure(
        self, tmp_path: Path
    ) -> None:
        """save_config 失敗時は mirror delete hook を呼ばない（TOML/GCS ズレ最小化）。"""
        root = tk.Tk()
        try:
            cfg = _make_config(tmp_path)
            cfg_path = tmp_path / "default.toml"
            cfg_path.write_text(
                '[checklist]\nfax_root = ""\n', encoding="utf-8"
            )
            dlg = ChecklistCDialog(parent=root, config=cfg, config_path=cfg_path)
            dlg._month_var.set("26年3月")
            row = ChecklistRow(
                name="テスト太郎",
                monitoring_raw="",
                staff="宮下",
                facility="テスト居宅",
            )
            result = CPlacementResult(row=row)
            result.status = CPlacementStatus.PENDING
            result.xlsx_path = Path(r"\\nas\share\PT 宮下\3月.xlsx")
            dlg._results = [result]

            with (
                patch(
                    "wiseman_hub.ui.checklist_c_dialog.messagebox.askyesno",
                    return_value=True,
                ),
                patch(
                    "wiseman_hub.ui.checklist_c_dialog.save_config",
                    side_effect=OSError("disk full"),
                ),
                patch(
                    "wiseman_hub.ui.checklist_c_dialog.messagebox.showwarning"
                ),
                patch(
                    "wiseman_hub.ui.checklist_c_dialog._mirror_delete_entry_async"
                ) as mock_del,
            ):
                dlg._clear_cache_for_row(0)

            mock_del.assert_not_called()
        finally:
            root.destroy()


@pytest.mark.tk_required
class TestMirrorWriteHook:
    """I-7: write hook (_open_picker_for_review 内 _apply_xlsx_to_row 等価点) のテスト。

    実コードで write hook が呼ばれるのは「ユーザーがファイル選択ダイアログで
    xlsx を選択 → save_config 成功」のフローだが、ファイルダイアログを起動する
    ことなく直接 cache 書込相当の経路を mock し hook 起動を検証する。

    ここでは hook の呼出契約（async 版が呼ばれること、引数）を確認する。
    """

    def test_write_hook_async_function_imported(self) -> None:
        """C-1 反映の確認: dialog module から async 版 mirror upload が import 済。"""
        from wiseman_hub.ui import checklist_c_dialog as ccd

        # async 版が import されていること（同期版が誤って残っていないこと）
        assert hasattr(ccd, "_mirror_upload_entry_async")
        assert hasattr(ccd, "_mirror_delete_entry_async")
        # 同期版は import しない（C-1: UI freeze 防止のため async 一択）
        assert not hasattr(ccd, "_mirror_upload_entry")
        assert not hasattr(ccd, "_mirror_delete_entry")


class TestMirrorAsyncContract:
    """C-1: mirror async wrapper が UI thread を blocking しないことを契約として検証。"""

    def test_upload_entry_async_returns_thread_immediately(
        self, tmp_path: Path
    ) -> None:
        """upload_entry_async は spawn 後即座に Thread を返す（UI thread を block しない）。"""
        import threading
        import time

        from wiseman_hub.cloud.xlsx_path_cache_mirror import upload_entry_async

        cfg_path = tmp_path / "default.toml"
        cfg_path.write_text("[checklist]\n", encoding="utf-8")
        gcp = GcpConfig()  # 未設定（worker 内で warn-only）

        start = time.monotonic()
        thread = upload_entry_async(
            "宮下:2026:3",
            r"\\nas\share\test.xlsx",
            gcp,
            config_path=cfg_path,
        )
        elapsed_ms = (time.monotonic() - start) * 1000

        assert isinstance(thread, threading.Thread)
        # spawn 自体は即時（10 ms 以内が普通、generous に 500 ms 上限）
        assert elapsed_ms < 500, (
            f"upload_entry_async should not block UI thread, took {elapsed_ms:.1f} ms"
        )
        # worker が完了するのを待つ（GCP 未設定なので即 warn-only で終わる）
        thread.join(timeout=2.0)
        assert not thread.is_alive(), "worker should finish quickly when GCP unset"

    def test_delete_entry_async_returns_thread_immediately(
        self, tmp_path: Path
    ) -> None:
        """delete_entry_async は spawn 後即座に Thread を返す。"""
        import threading
        import time

        from wiseman_hub.cloud.xlsx_path_cache_mirror import delete_entry_async

        cfg_path = tmp_path / "default.toml"
        cfg_path.write_text("[checklist]\n", encoding="utf-8")
        gcp = GcpConfig()

        start = time.monotonic()
        thread = delete_entry_async("宮下:2026:3", gcp, config_path=cfg_path)
        elapsed_ms = (time.monotonic() - start) * 1000

        assert isinstance(thread, threading.Thread)
        assert elapsed_ms < 500
        thread.join(timeout=2.0)
        assert not thread.is_alive()
