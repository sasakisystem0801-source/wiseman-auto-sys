"""B ダイアログの SheetListBinding 統合ユニットテスト。

本 PR (sheet-list-binding) で導入した cache 起動 populate + sync info label の
B ダイアログ側の検証。C ダイアログとの feature parity を保つ。

主な検証点:
    - cache hit 時に month combo が populate される
    - cache miss 時は combo 空 + sync_info「不明」
    - シート取得後 cache 永続化 + 「たった今」相当の sync label
    - 取得失敗時に「※更新失敗 (...)」併記
    - config_path=None でも例外を出さず空状態で起動可能 (test fallback)
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path

import pytest

from wiseman_hub.cloud.sheet_list_cache import (
    cache_dir_for as _sheet_cache_dir_for,
)
from wiseman_hub.cloud.sheet_list_cache import (
    save as _save_sheet_cache,
)
from wiseman_hub.config import (
    AppConfig,
    ChecklistConfig,
    GcpConfig,
    WisemanConfig,
)
from wiseman_hub.ui.checklist_b_dialog import ChecklistBDialog


def _make_config(tmp_path: Path, spreadsheet_id: str = "spread123") -> AppConfig:
    """B ダイアログテスト用最小 AppConfig。"""
    return AppConfig(
        wiseman=WisemanConfig(),
        gcp=GcpConfig(),
        checklist=ChecklistConfig(
            spreadsheet_id=spreadsheet_id,
            fax_root=tmp_path,
        ),
        log_dir=tmp_path / "logs",
    )


def _make_config_path(tmp_path: Path) -> Path:
    """SheetListBinding が cache_dir を導出できる階層を作る。"""
    cfg_dir = tmp_path / "wiseman-hub" / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    return cfg_dir / "default.toml"


@pytest.mark.tk_required
class TestCachePopulateOnOpen:
    """AC-3: 起動時 cache hit で month combo が populate される。"""

    def test_cache_hit_populates_combo(self, tmp_path: Path) -> None:
        cfg_path = _make_config_path(tmp_path)
        cache_dir = _sheet_cache_dir_for(cfg_path)
        _save_sheet_cache(
            cache_dir, "spread123", ["25年12月", "26年1月", "26年2月"]
        )
        root = tk.Tk()
        root.withdraw()
        try:
            cfg = _make_config(tmp_path)
            dlg = ChecklistBDialog(
                parent=root, config=cfg, config_path=cfg_path
            )
            try:
                assert dlg._month_combo["values"] == (
                    "25年12月",
                    "26年1月",
                    "26年2月",
                )
                assert dlg._month_var.get() == "26年2月"  # 末尾選択
                # status label にキャッシュ件数 / 最新化案内が出ている
                assert "キャッシュ" in dlg._status_var.get()
                assert "シート一覧更新" in dlg._status_var.get()
            finally:
                dlg.get_toplevel().destroy()
        finally:
            root.destroy()

    def test_cache_miss_keeps_combo_empty(self, tmp_path: Path) -> None:
        cfg_path = _make_config_path(tmp_path)
        root = tk.Tk()
        root.withdraw()
        try:
            cfg = _make_config(tmp_path)
            dlg = ChecklistBDialog(
                parent=root, config=cfg, config_path=cfg_path
            )
            try:
                # 実 ttk.Combobox は未設定時 ``""`` を返す。Tk 内部は値を tuple で
                # 保持するが ``__getitem__("values")`` 経由では空文字列にシリアライズ
                # される (T14 Evaluator 指摘対応: _FakeCombo の () とは異なるため、
                # 実 Tk 経路ではこちらが正しい期待値)。
                assert dlg._month_combo["values"] in ("", ())
                # status は既定文言 ("シート一覧取得から開始してください")
                assert "開始してください" in dlg._status_var.get()
            finally:
                dlg.get_toplevel().destroy()
        finally:
            root.destroy()


@pytest.mark.tk_required
class TestSyncInfoLabel:
    """AC-4: B ダイアログにも「シート一覧 最終更新: ...」label が表示される。"""

    def test_initial_label_unknown_on_cache_miss(self, tmp_path: Path) -> None:
        cfg_path = _make_config_path(tmp_path)
        root = tk.Tk()
        root.withdraw()
        try:
            cfg = _make_config(tmp_path)
            dlg = ChecklistBDialog(
                parent=root, config=cfg, config_path=cfg_path
            )
            try:
                assert dlg._sync_info_var.get() == "シート一覧 最終更新: 不明"
            finally:
                dlg.get_toplevel().destroy()
        finally:
            root.destroy()

    def test_label_shows_just_now_after_cache_save(self, tmp_path: Path) -> None:
        cfg_path = _make_config_path(tmp_path)
        cache_dir = _sheet_cache_dir_for(cfg_path)
        _save_sheet_cache(cache_dir, "spread123", ["26年1月"])
        root = tk.Tk()
        root.withdraw()
        try:
            cfg = _make_config(tmp_path)
            dlg = ChecklistBDialog(
                parent=root, config=cfg, config_path=cfg_path
            )
            try:
                # cache hit 時の sync label には「たった今」相当が並ぶ
                label = dlg._sync_info_var.get()
                assert label.startswith("シート一覧 最終更新:")
                assert "たった今" in label
            finally:
                dlg.get_toplevel().destroy()
        finally:
            root.destroy()


@pytest.mark.tk_required
class TestOnSheetsLoadedSavesCache:
    """AC-2 (B 側): _on_sheets_loaded が cache を永続化する。"""

    def test_persists_after_fetch(self, tmp_path: Path) -> None:
        cfg_path = _make_config_path(tmp_path)
        root = tk.Tk()
        root.withdraw()
        try:
            cfg = _make_config(tmp_path)
            dlg = ChecklistBDialog(
                parent=root, config=cfg, config_path=cfg_path
            )
            try:
                # 起動直後は cache 不在
                cache_file = (
                    _sheet_cache_dir_for(cfg_path) / "spread123.json"
                )
                assert not cache_file.exists()
                # Drive API のレスポンス相当を直接 callback に流す
                dlg._on_sheets_loaded(b"xlsx-bytes", ["26年1月", "26年2月"])
                # cache JSON が作られる
                assert cache_file.exists()
                # 取得完了 status
                assert "シート一覧取得完了" in dlg._status_var.get()
                # sync label も「たった今」相当に更新
                assert "たった今" in dlg._sync_info_var.get()
            finally:
                dlg.get_toplevel().destroy()
        finally:
            root.destroy()


@pytest.mark.tk_required
class TestOnLoadErrorShowsFailureMarker:
    """背景更新失敗時に sync_info に ※更新失敗 を併記。"""

    def test_failure_marker_appended(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg_path = _make_config_path(tmp_path)
        cache_dir = _sheet_cache_dir_for(cfg_path)
        _save_sheet_cache(cache_dir, "spread123", ["26年1月"])
        root = tk.Tk()
        root.withdraw()
        try:
            cfg = _make_config(tmp_path)
            dlg = ChecklistBDialog(
                parent=root, config=cfg, config_path=cfg_path
            )
            # messagebox.showerror をスタブして UI dialog を出さない
            from wiseman_hub.ui import checklist_b_dialog as mod

            captured: list[tuple[str, str]] = []

            def _stub_error(title: str, message: str) -> None:
                captured.append((title, message))

            monkeypatch.setattr(mod.messagebox, "showerror", _stub_error)
            try:
                dlg._on_load_error("ConnectionError")
                # 既存 cache の表示 + 失敗マーカー併記
                label = dlg._sync_info_var.get()
                assert "シート一覧 最終更新:" in label
                assert "※更新失敗 (ConnectionError)" in label
                # messagebox も呼ばれていることを確認
                assert any(
                    "ConnectionError" in msg for _, msg in captured
                )
            finally:
                dlg.get_toplevel().destroy()
        finally:
            root.destroy()


@pytest.mark.tk_required
class TestTransparentDownload:
    """pr-test-analyzer CG-1 対応: cache hit 後 _on_load_rows の透過 download パス。

    本 PR で B ダイアログに新規導入された UX の核心経路 (業務責任者は「シート一覧
    更新」を意識せず即「対象行を読込」できる)。Codex Medium 指摘で background 化
    + 失敗時 sync_info マーカー併記の挙動を確認する。
    """

    def _make_dialog_with_cache(
        self, root: tk.Tk, tmp_path: Path, *, with_xlsx_bytes: bool = False
    ) -> tuple[ChecklistBDialog, Path]:
        cfg_path = _make_config_path(tmp_path)
        cache_dir = _sheet_cache_dir_for(cfg_path)
        _save_sheet_cache(cache_dir, "spread123", ["26年5月"])
        cfg = _make_config(tmp_path)
        dlg = ChecklistBDialog(parent=root, config=cfg, config_path=cfg_path)
        dlg._month_var.set("26年5月")
        if with_xlsx_bytes:
            dlg._xlsx_bytes = b"prefetched"
        return dlg, cfg_path

    def test_cache_hit_triggers_transparent_download(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """cache hit + _xlsx_bytes 空 → download_xlsx が 1 回呼ばれる。"""
        from wiseman_hub.ui import checklist_b_dialog as mod

        root = tk.Tk()
        root.withdraw()
        try:
            dlg, _ = self._make_dialog_with_cache(root, tmp_path)
            calls: list[str] = []

            def _stub_download(_gcp, sid: str) -> bytes:  # type: ignore[no-untyped-def]
                calls.append(sid)
                return b"fake-xlsx-bytes"

            # parse_sheet / select_b_rows / plan_b_placement も stub して
            # 透過 download の経路のみを検証
            monkeypatch.setattr(mod, "download_xlsx", _stub_download)
            monkeypatch.setattr(mod, "parse_sheet", lambda _b, _s: [])
            monkeypatch.setattr(mod, "select_b_rows", lambda _rows: [])
            monkeypatch.setattr(mod, "plan_b_placement", lambda *_a, **_k: [])

            dlg._on_load_rows()
            # background thread の完了を待つ (winfo_exists ガード経由で UI 反映)
            root.update()
            # threading 完了まで最大 1 秒待機
            import time

            for _ in range(20):
                if calls:
                    root.update()
                    break
                root.update()
                time.sleep(0.05)
            assert calls == ["spread123"]
            assert dlg._xlsx_bytes == b"fake-xlsx-bytes"
            dlg.get_toplevel().destroy()
        finally:
            root.destroy()

    def test_existing_xlsx_bytes_skips_download(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_xlsx_bytes が既にある場合は download_xlsx が呼ばれない (parse のみ実行)。"""
        from wiseman_hub.ui import checklist_b_dialog as mod

        root = tk.Tk()
        root.withdraw()
        try:
            dlg, _ = self._make_dialog_with_cache(
                root, tmp_path, with_xlsx_bytes=True
            )
            calls: list[str] = []

            def _stub_download(_gcp, sid: str) -> bytes:  # type: ignore[no-untyped-def]
                calls.append(sid)
                return b"should-not-be-called"

            monkeypatch.setattr(mod, "download_xlsx", _stub_download)
            monkeypatch.setattr(mod, "parse_sheet", lambda _b, _s: [])
            monkeypatch.setattr(mod, "select_b_rows", lambda _rows: [])
            monkeypatch.setattr(mod, "plan_b_placement", lambda *_a, **_k: [])

            dlg._on_load_rows()
            root.update()
            # _xlsx_bytes は元の値のまま、download は走らない
            assert calls == []
            assert dlg._xlsx_bytes == b"prefetched"
            dlg.get_toplevel().destroy()
        finally:
            root.destroy()

    def test_transparent_download_failure_appends_sync_marker(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """silent-failure C-2: download 失敗時に sync_info に「※更新失敗」を併記。"""
        from wiseman_hub.ui import checklist_b_dialog as mod

        root = tk.Tk()
        root.withdraw()
        try:
            dlg, _ = self._make_dialog_with_cache(root, tmp_path)

            def _failing_download(_gcp, _sid: str) -> bytes:  # type: ignore[no-untyped-def]
                raise ConnectionError("simulated network failure")

            monkeypatch.setattr(mod, "download_xlsx", _failing_download)
            shown_errors: list[tuple[str, str]] = []
            monkeypatch.setattr(
                mod.messagebox,
                "showerror",
                lambda t, m, **_k: shown_errors.append((t, m)),
            )

            dlg._on_load_rows()
            root.update()
            import time

            # background 失敗 callback が走るまで待機
            for _ in range(20):
                if shown_errors:
                    root.update()
                    break
                root.update()
                time.sleep(0.05)
            # sync_info に失敗マーカーが付く
            assert "※更新失敗" in dlg._sync_info_var.get()
            assert "ConnectionError" in dlg._sync_info_var.get()
            # messagebox showerror も呼ばれる
            assert any(
                "ConnectionError" in m for _, m in shown_errors
            )
            dlg.get_toplevel().destroy()
        finally:
            root.destroy()

    def test_transparent_download_empty_spreadsheet_id_shows_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """設定の spreadsheet_id が空の状態で透過 download に至ったら設定不足エラー表示。

        通常は cache hit があれば spreadsheet_id 設定済みのはずだが、設定再読込で
        spreadsheet_id が消えた + cache_path が残るレアケースを防御。
        """
        from wiseman_hub.ui import checklist_b_dialog as mod

        cfg_path = _make_config_path(tmp_path)
        cache_dir = _sheet_cache_dir_for(cfg_path)
        _save_sheet_cache(cache_dir, "spread123", ["26年5月"])
        cfg = _make_config(tmp_path, spreadsheet_id="spread123")
        root = tk.Tk()
        root.withdraw()
        try:
            dlg = ChecklistBDialog(parent=root, config=cfg, config_path=cfg_path)
            dlg._month_var.set("26年5月")
            # 直後に spreadsheet_id を空に
            dlg._config.checklist.spreadsheet_id = ""

            calls: list[str] = []
            monkeypatch.setattr(
                mod,
                "download_xlsx",
                lambda _g, sid: calls.append(sid) or b"",
            )
            shown_errors: list[tuple[str, str]] = []
            monkeypatch.setattr(
                mod.messagebox,
                "showerror",
                lambda t, m, **_k: shown_errors.append((t, m)),
            )

            dlg._on_load_rows()
            root.update()
            # download は呼ばれない、エラー表示のみ
            assert calls == []
            assert any("設定不足" in t for t, _ in shown_errors)
            dlg.get_toplevel().destroy()
        finally:
            root.destroy()


@pytest.mark.tk_required
class TestConfigPathNoneGuard:
    """config_path=None でも例外を出さず空状態で起動可能。"""

    def test_no_op_without_config_path(self, tmp_path: Path) -> None:
        root = tk.Tk()
        root.withdraw()
        try:
            cfg = _make_config(tmp_path)
            dlg = ChecklistBDialog(parent=root, config=cfg, config_path=None)
            try:
                # combo は空、sync label「不明」のまま、例外なし
                assert dlg._month_combo["values"] in ("", ())
                assert dlg._sync_info_var.get() == "シート一覧 最終更新: 不明"
            finally:
                dlg.get_toplevel().destroy()
        finally:
            root.destroy()
