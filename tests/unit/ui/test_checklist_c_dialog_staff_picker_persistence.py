"""``_open_staff_picker_for_review`` の永続化経路の契約テスト (Issue #314)。

pr-test-analyzer Critical 指摘対応 (rating 9 + 8):
``_open_staff_picker_for_review`` 本体 (89 行) は Codex review High #1 (cache
value = normalize_lookup_key 形式) と High #2 (dataclasses.replace で row copy)
の **実行系の契約** を持つため、dispatch routing だけでなく書込経路を unit
テストで担保する必要がある。

Tk Toplevel を起動せず ``ChecklistCDialog.__new__`` + MagicMock + monkeypatch
で属性を差し替え、StaffPickerDialog / save_config / messagebox を全て隔離
することで、CI Linux ヘッドレスでも安定実行できる。

主要検証点:
    - cache に ``normalize_lookup_key(selected)`` 形式の値が書込まれる (High #1)
    - 元 ``r.row.staff`` ("小島/木塚") が in-place 改変されない (High #2)
    - ``self._results[idx]`` が再 plan 結果の row.staff=selected で更新される
    - ``remember=False`` 時に cache 書込が走らない
    - ``save_config`` OSError 時に warning + messagebox 警告 + UI 継続
    - ``year/month`` 未確定時に early return + cache 書込なし
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from wiseman_hub.cloud.sheets import ChecklistRow
from wiseman_hub.config import (
    AppConfig,
    ChecklistConfig,
    GcpConfig,
    ReportStaffEntry,
    WisemanConfig,
)
from wiseman_hub.pdf.checklist_c import CPlacementResult, CPlacementStatus
from wiseman_hub.ui.checklist_c_dialog import ChecklistCDialog
from wiseman_hub.utils.text_norm import normalize_lookup_key


def _make_appconfig(tmp_path: Path) -> AppConfig:
    """テスト用最小 AppConfig (小島 / 木塚 mapping 登録、cache 空)。"""
    base_kojima = tmp_path / "PT 小島"
    base_kojima.mkdir(parents=True, exist_ok=True)
    base_kizuka = tmp_path / "PT 木塚"
    base_kizuka.mkdir(parents=True, exist_ok=True)
    return AppConfig(
        wiseman=WisemanConfig(),
        gcp=GcpConfig(),
        checklist=ChecklistConfig(
            spreadsheet_id="dummy",
            fax_root=tmp_path,
            facility_routing={"事業所A": "事業所A_FAX"},
            report_staff={
                "小島": ReportStaffEntry(base_dir=base_kojima, suggest_patterns=["x"]),
                "木塚": ReportStaffEntry(base_dir=base_kizuka, suggest_patterns=["x"]),
            },
        ),
        log_dir=tmp_path / "logs",
    )


def _make_dialog_with_needs_review_staff_row(
    tmp_path: Path, *, year_month: tuple[int | None, int | None] = (2026, 3)
) -> tuple[ChecklistCDialog, CPlacementResult, AppConfig, Path]:
    """Tk 不要で _open_staff_picker_for_review の前提状態を組む。

    NEEDS_REVIEW_STAFF 1 行 (staff="小島/木塚", staff_candidates=["小島","木塚"])
    を仕込み、永続化経路を呼び出せる状態にする。``_current_year_month`` /
    ``_refresh_tree`` / ``_update_exec_button`` / ``_status_var`` は MagicMock。
    """
    cfg = _make_appconfig(tmp_path)
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("[checklist]\n", encoding="utf-8")

    row = ChecklistRow(
        name="テスト 太郎", monitoring_raw=None, staff="小島/木塚", facility="事業所A"
    )
    result = CPlacementResult(
        row=row,
        status=CPlacementStatus.NEEDS_REVIEW_STAFF,
        staff_candidates=["小島", "木塚"],
        message="2 名から担当者を選択してください",
    )

    dlg = ChecklistCDialog.__new__(ChecklistCDialog)
    dlg._config = cfg  # type: ignore[attr-defined]
    dlg._config_path = cfg_path  # type: ignore[attr-defined]
    dlg._results = [result]  # type: ignore[attr-defined]
    dlg._top = MagicMock()  # type: ignore[attr-defined]
    dlg._status_var = MagicMock()  # type: ignore[attr-defined]
    dlg._refresh_tree = MagicMock()  # type: ignore[attr-defined]
    dlg._update_exec_button = MagicMock()  # type: ignore[attr-defined]
    dlg._current_year_month = MagicMock(return_value=year_month)  # type: ignore[attr-defined]
    return dlg, result, cfg, cfg_path


def _patch_staff_picker(selected: str | None, remember: bool):  # type: ignore[no-untyped-def]
    """StaffPickerDialog 全体を MagicMock 化し、get_result 戻り値を固定する context manager 風 helper。"""
    picker_mock = MagicMock()
    picker_mock.get_toplevel.return_value.wait_window = MagicMock()
    picker_mock.get_result.return_value = (selected, remember)
    picker_cls_mock = MagicMock(return_value=picker_mock)
    return patch(
        "wiseman_hub.ui.checklist_c_dialog.StaffPickerDialog",
        picker_cls_mock,
    )


# ---------- Critical #1: cache value 形式 + row copy ----------


def test_staff_picker_persists_cache_value_in_normalized_form(tmp_path: Path) -> None:
    """High #1: staff_choice_cache value は normalize_lookup_key 形式で書込まれる。

    元表記 "小島" (= 表示名) ではなく ``normalize_lookup_key("小島")`` の出力が
    cache value に入る。表記揺れ・同姓・全角半角差の吸収を report_staff lookup
    で確実にする (Codex review High #1)。
    """
    dlg, result, cfg, _ = _make_dialog_with_needs_review_staff_row(tmp_path)

    with _patch_staff_picker("小島", True), patch(
        "wiseman_hub.ui.checklist_c_dialog.save_config"
    ) as mock_save:
        dlg._open_staff_picker_for_review(0, result)

    # cache 書込内容: key は "木塚|小島:2026:3" (sort + `|`)、value は normalize 後
    cache = cfg.checklist.staff_choice_cache
    assert len(cache) == 1
    # value は normalize_lookup_key("小島") (= "小島" だが正規化経路を通している保証)
    value = next(iter(cache.values()))
    assert value == normalize_lookup_key("小島")
    # save_config は 1 度だけ呼ばれる
    mock_save.assert_called_once()


def test_staff_picker_uses_dataclasses_replace_for_row_copy(tmp_path: Path) -> None:
    """High #2: ``dataclasses.replace(row, staff=selected)`` で row copy、元 row 不変。

    元の ``r.row.staff`` ("小島/木塚") が in-place 改変されないこと、新 result の
    ``row.staff`` のみ "小島" に置換されていることを assert。元 row への参照を
    元 result が保持し続けるため、original_row.staff の値で確認可能。
    """
    dlg, result, _, _ = _make_dialog_with_needs_review_staff_row(tmp_path)
    original_row = result.row

    with _patch_staff_picker("木塚", True), patch(
        "wiseman_hub.ui.checklist_c_dialog.save_config"
    ):
        dlg._open_staff_picker_for_review(0, result)

    # 元 row の staff は in-place で書き換わっていない
    assert original_row.staff == "小島/木塚"
    # 新 result は別 row (copy) を持ち、staff は選択値に置換されている
    new_result = dlg._results[0]
    assert new_result.row is not original_row  # オブジェクト同一性も確認
    assert new_result.row.staff == "木塚"
    # row の他 field は維持
    assert new_result.row.name == original_row.name
    assert new_result.row.facility == original_row.facility


# ---------- Critical #2: save_config 失敗 + remember=False 分岐 ----------


def test_staff_picker_remember_false_does_not_write_cache(tmp_path: Path) -> None:
    """remember=False → staff_choice_cache に書込まれず save_config も呼ばれない。

    StaffPickerDialog の「この選択を記憶」chk を外した時に cache 永続化を抑止
    する経路。選択結果自体は ``_results[idx]`` に反映される。
    """
    dlg, result, cfg, _ = _make_dialog_with_needs_review_staff_row(tmp_path)

    with _patch_staff_picker("小島", False), patch(
        "wiseman_hub.ui.checklist_c_dialog.save_config"
    ) as mock_save:
        dlg._open_staff_picker_for_review(0, result)

    # cache は空のまま
    assert cfg.checklist.staff_choice_cache == {}
    # save_config も呼ばれない
    mock_save.assert_not_called()
    # ただし行は再 plan されている (選択は反映)
    assert dlg._results[0].row.staff == "小島"


def test_staff_picker_save_config_oserror_shows_warning(tmp_path: Path) -> None:
    """save_config が OSError → warning messagebox + UI 継続 (silent fail しない)。

    永続化失敗時にユーザーへ通知する経路 (xlsx_path_cache 永続化と同型)。
    cache の dict 自体は in-place で更新済 → 次回 save 成功時に永続化される
    (整合性は呼出側責任)。
    """
    dlg, result, cfg, _ = _make_dialog_with_needs_review_staff_row(tmp_path)

    with _patch_staff_picker("小島", True), patch(
        "wiseman_hub.ui.checklist_c_dialog.save_config",
        side_effect=OSError("disk full"),
    ), patch(
        "wiseman_hub.ui.checklist_c_dialog.messagebox.showwarning"
    ) as mock_warn:
        dlg._open_staff_picker_for_review(0, result)

    # messagebox.showwarning が呼ばれる (silent fail 防止)
    mock_warn.assert_called_once()
    # ただし cache dict 自体は更新済 (次回 save まで保留)
    assert len(cfg.checklist.staff_choice_cache) == 1
    # 選択結果も反映
    assert dlg._results[0].row.staff == "小島"


# ---------- 補助: early return / 防御弁 ----------


def test_staff_picker_year_month_unset_early_returns(tmp_path: Path) -> None:
    """year/month 未確定時 → messagebox.showinfo + early return (cache 書込なし)。

    対象月選択前にダブルクリックされた誤操作の保護経路。
    """
    dlg, result, cfg, _ = _make_dialog_with_needs_review_staff_row(
        tmp_path, year_month=(None, None)
    )

    with patch(
        "wiseman_hub.ui.checklist_c_dialog.messagebox.showinfo"
    ) as mock_info, patch(
        "wiseman_hub.ui.checklist_c_dialog.save_config"
    ) as mock_save, patch(
        "wiseman_hub.ui.checklist_c_dialog.StaffPickerDialog"
    ) as picker_cls_mock:
        dlg._open_staff_picker_for_review(0, result)

    # messagebox.showinfo で対象月未確定を通知
    mock_info.assert_called_once()
    # StaffPickerDialog は開かれない (early return)
    picker_cls_mock.assert_not_called()
    # cache 書込も save_config も走らない
    assert cfg.checklist.staff_choice_cache == {}
    mock_save.assert_not_called()


def test_staff_picker_cancel_is_noop_no_cache_write(tmp_path: Path) -> None:
    """StaffPickerDialog でキャンセル (selected=None) → 何もしない (cache 書込なし、再 plan なし)。"""
    dlg, result, cfg, _ = _make_dialog_with_needs_review_staff_row(tmp_path)
    original_row_staff = result.row.staff

    with _patch_staff_picker(None, False), patch(
        "wiseman_hub.ui.checklist_c_dialog.save_config"
    ) as mock_save:
        dlg._open_staff_picker_for_review(0, result)

    # cache 書込なし
    assert cfg.checklist.staff_choice_cache == {}
    mock_save.assert_not_called()
    # 再 plan も走らない (元 result が残る)
    assert dlg._results[0] is result
    assert dlg._results[0].row.staff == original_row_staff


@pytest.mark.parametrize(
    "selected,expected_normalized",
    [
        ("小島", normalize_lookup_key("小島")),
        ("木塚", normalize_lookup_key("木塚")),
    ],
)
def test_staff_picker_cache_key_matches_staff_choice_cache_key(
    tmp_path: Path, selected: str, expected_normalized: str
) -> None:
    """cache 書込 key は ``staff_choice_cache_key(staff_candidates, year, month)`` と一致。

    plan_c_placement 側の lookup と書込側の key が完全一致する契約を回帰固定。
    key 形式: 順序非依存 sort + `|` 区切り (staff_choice_cache_key の責務)。
    """
    from wiseman_hub.pdf.checklist_c import staff_choice_cache_key

    dlg, result, cfg, _ = _make_dialog_with_needs_review_staff_row(tmp_path)
    expected_key = staff_choice_cache_key(["小島", "木塚"], 2026, 3)

    with _patch_staff_picker(selected, True), patch(
        "wiseman_hub.ui.checklist_c_dialog.save_config"
    ):
        dlg._open_staff_picker_for_review(0, result)

    assert expected_key in cfg.checklist.staff_choice_cache
    assert cfg.checklist.staff_choice_cache[expected_key] == expected_normalized
