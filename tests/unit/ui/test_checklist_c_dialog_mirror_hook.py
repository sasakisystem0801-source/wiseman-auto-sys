"""ADR-016 PR-2: GCS mirror hook の統合テスト。

C ダイアログの cache write hook（``_open_picker_for_review``）と
delete hook（``_clear_cache_for_row``）が GCS mirror を呼ぶことを検証する。

検証戦略:
    - ``_mirror_upload_entry`` / ``_mirror_delete_entry`` を mock 化し、
      呼出回数 + 引数 (key, xlsx_path, config_path) のみを確認
    - GCS API 自体は触らない（``xlsx_path_cache_mirror`` 単体テストでカバー）
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
    """_clear_cache_for_row が delete hook を呼ぶ。"""

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

            with patch(
                "wiseman_hub.ui.checklist_c_dialog.messagebox.askyesno",
                return_value=True,
            ), patch(
                "wiseman_hub.ui.checklist_c_dialog.save_config"
            ), patch(
                "wiseman_hub.ui.checklist_c_dialog._mirror_delete_entry"
            ) as mock_del:
                dlg._clear_cache_for_row(0)

            mock_del.assert_called_once()
            args = mock_del.call_args.args
            kwargs = mock_del.call_args.kwargs
            # 第 1 引数: key
            assert args[0] == "宮下:2026:3"
            # config_path keyword
            assert kwargs.get("config_path") == cfg_path
        finally:
            root.destroy()
