"""ランチャー GUI のユニットテスト。

Issue #154 で旧ワークフロー UI 経路 (PDF マージ処理 / 確認待ちセッション) を除去。
現在のスコープは 3 ボタン構成 (業務フロー順):
  1. ex_ ファイル変換 + 振り分け (ADR-014, ① 起点)
  2. 事業所フォルダ一括結合 (ADR-013, ③ 一括再結合)
  3. 設定

2 層構成:
  1. Pure logic tests (Tk 非依存): LauncherAction enum / button_labels 等。
  2. UI wiring tests (Tk 必要): _build_ui / button.invoke()
     — Tk ランタイム利用可能な環境のみ (macOS uv python では skip)。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

os.environ.setdefault("TK_SILENCE_DEPRECATION", "1")

from wiseman_hub.config import AppConfig  # noqa: E402
from wiseman_hub.ui.launcher import Launcher, LauncherAction  # noqa: E402

# ---------------------------------------------------------------------------
# Pure logic tests (Tk 非依存)
# ---------------------------------------------------------------------------


class TestLauncherAction:
    """LauncherAction enum の値域 (Issue #154 で 3 アクションに整理)。"""

    def test_enum_has_three_primary_actions(self) -> None:
        assert LauncherAction.OPEN_SETTINGS.value == "open_settings"
        assert LauncherAction.OPEN_FACILITY_MERGER.value == "open_facility_merger"
        assert LauncherAction.OPEN_EX_EXTRACTOR.value == "open_ex_extractor"

    def test_enum_does_not_contain_legacy_actions(self) -> None:
        """Issue #154: 旧ワークフロー (PDF マージ / 確認待ちセッション) の
        LauncherAction 値が再追加されていないことを契約として固定する。"""
        legacy = {"run_pdf_merge", "open_review"}
        current_values = {action.value for action in LauncherAction}
        assert not (legacy & current_values), (
            f"legacy LauncherAction values reintroduced: {legacy & current_values}"
        )


# ---------------------------------------------------------------------------
# UI wiring tests (Tk 必要、Windows 実機 + macOS Tk 利用可能環境で実行)
# ---------------------------------------------------------------------------


# Tk 利用可否判定は ``conftest.py`` の ``@pytest.mark.tk_required`` に集約。
tk_required = pytest.mark.tk_required


@tk_required
class TestLauncherUI:
    """Launcher の Tkinter UI 構築・ボタン動作。"""

    def test_launcher_builds_buttons_in_workflow_order(
        self, tmp_path: Path
    ) -> None:
        """業務フロー順 5 ボタンで起動する (PR #172 で B/C を追加)。

        順序: ex_ 変換 → B 配置 → C 配置 → 事業所結合 → 設定。
        """
        import tkinter as tk

        config_path = tmp_path / "config.toml"
        config_path.write_text("", encoding="utf-8")

        root = tk.Tk()
        try:
            launcher = Launcher(
                config=AppConfig(),
                config_path=config_path,
                root=root,
            )
            labels = launcher.button_labels()
            assert len(labels) == 5
            # 業務フロー順
            assert "ex_" in labels[0]
            assert labels[1].startswith("B:")
            assert labels[2].startswith("C:")
            assert "事業所" in labels[3]
            assert "設定" in labels[4]
            # 旧ワークフローの文言が UI に出ないことを契約化
            joined = " ".join(labels)
            assert "PDF マージ処理" not in joined
            assert "確認待ちセッション" not in joined
        finally:
            root.destroy()

    def test_open_ex_extractor_calls_callback(self, tmp_path: Path) -> None:
        """「ex_ ファイル変換 + 振り分け」押下 → on_open_ex_extractor 呼出。"""
        import tkinter as tk

        config_path = tmp_path / "config.toml"
        config_path.write_text("", encoding="utf-8")

        called: list[str] = []

        root = tk.Tk()
        try:
            launcher = Launcher(
                config=AppConfig(),
                config_path=config_path,
                root=root,
                on_open_ex_extractor=lambda: called.append("ex"),
            )
            launcher.invoke_action(LauncherAction.OPEN_EX_EXTRACTOR)
        finally:
            root.destroy()

        assert called == ["ex"]

    def test_open_facility_merger_calls_callback(self, tmp_path: Path) -> None:
        """「事業所フォルダ一括結合」押下 → on_open_facility_merger 呼出。"""
        import tkinter as tk

        config_path = tmp_path / "config.toml"
        config_path.write_text("", encoding="utf-8")

        called: list[str] = []

        root = tk.Tk()
        try:
            launcher = Launcher(
                config=AppConfig(),
                config_path=config_path,
                root=root,
                on_open_facility_merger=lambda: called.append("merger"),
            )
            launcher.invoke_action(LauncherAction.OPEN_FACILITY_MERGER)
        finally:
            root.destroy()

        assert called == ["merger"]

    def test_open_settings_calls_callback(self, tmp_path: Path) -> None:
        """「設定」押下 → on_open_settings 呼出。"""
        import tkinter as tk

        config_path = tmp_path / "config.toml"
        config_path.write_text("", encoding="utf-8")

        called: list[str] = []

        root = tk.Tk()
        try:
            launcher = Launcher(
                config=AppConfig(),
                config_path=config_path,
                root=root,
                on_open_settings=lambda: called.append("settings"),
            )
            launcher.invoke_action(LauncherAction.OPEN_SETTINGS)
        finally:
            root.destroy()

        assert called == ["settings"]

    def test_default_on_open_settings_shows_placeholder_message(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """on_open_settings 未指定時、既定のプレースホルダメッセージが出る。"""
        import tkinter as tk

        config_path = tmp_path / "config.toml"
        config_path.write_text("", encoding="utf-8")

        shown: list[tuple[str, str]] = []

        class FakeMessageBox:
            def askyesno(self, title: str, message: str) -> bool:
                return True

            def showinfo(self, title: str, message: str) -> None:
                shown.append((title, message))

            def showerror(self, title: str, message: str) -> None:
                shown.append((title, message))

        root = tk.Tk()
        try:
            launcher = Launcher(
                config=AppConfig(),
                config_path=config_path,
                root=root,
                messagebox_fn=FakeMessageBox(),
            )
            launcher.invoke_action(LauncherAction.OPEN_SETTINGS)
        finally:
            root.destroy()

        assert len(shown) == 1
        assert "設定" in shown[0][0]

    def test_invoke_action_unhandled_value_raises(self, tmp_path: Path) -> None:
        """将来 LauncherAction に値追加 → match default で silent バグ防止。"""
        import tkinter as tk

        config_path = tmp_path / "config.toml"
        config_path.write_text("", encoding="utf-8")

        root = tk.Tk()
        try:
            launcher = Launcher(
                config=AppConfig(),
                config_path=config_path,
                root=root,
            )
            sentinel = object()
            with pytest.raises(ValueError, match="Unhandled LauncherAction"):
                launcher.invoke_action(sentinel)  # type: ignore[arg-type]
        finally:
            root.destroy()


# ---------------------------------------------------------------------------
# Phase 2-α (Issue #238): GCP 同期サマリー表示
# ---------------------------------------------------------------------------


@tk_required
class TestLauncherSyncSummary:
    """Launcher 起動時の sync_summary フレーム表示 (Issue #238 Phase 2-α)。

    テスト容易化のため Launcher は ``now_fn`` DI を受ける。各テストで
    fixed_now を渡し相対表示 (N分前 等) を deterministic にする。
    """

    def _make_config_path(self, tmp_path: Path) -> Path:
        """sync_cache_dir_for の前提に合わせて 2 階層下の config パスを作る。"""
        cfg = tmp_path / "wiseman-hub" / "config" / "default.toml"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text("", encoding="utf-8")
        return cfg

    def test_all_three_rows_show_unknown_when_no_cache(
        self, tmp_path: Path
    ) -> None:
        """cache 未作成なら 3 行とも「{ラベル}: 不明」を表示 (Phase 1 ChecklistCDialog と統一)。

        review 反映 (evaluator AC-2 FAIL): cache 不在 / parse 失敗 / tz naive を
        format_synced_at_label の None 経路で「不明」に集約することで、Phase 1 と
        文言が一致する。
        """
        import tkinter as tk

        cfg = self._make_config_path(tmp_path)
        root = tk.Tk()
        try:
            launcher = Launcher(
                config=AppConfig(),
                config_path=cfg,
                root=root,
                # Phase 2-β (I-2): production default = True (after_idle 遅延)、
                # test では deterministic な同期実行を要求する。
                defer_initial_refresh=False,
            )
            assert launcher._sync_vars["mapping_routing"].get() == (
                "居宅対照表: 不明"
            )
            assert launcher._sync_vars["report_staff"].get() == (
                "担当者マッピング: 不明"
            )
            assert launcher._sync_vars["sheets"].get() == (
                "シート一覧: 不明"
            )
        finally:
            root.destroy()

    def test_corrupt_cache_falls_back_to_unknown(
        self, tmp_path: Path
    ) -> None:
        """cache JSON が破損 / tz naive なら「不明」表示 (AC-2 統合検証)。"""
        import datetime as _dt
        import json
        import tkinter as tk

        from wiseman_hub.cloud.sync_label import sync_cache_dir_for

        cfg = self._make_config_path(tmp_path)
        sync_dir = sync_cache_dir_for(cfg)
        sync_dir.mkdir(parents=True, exist_ok=True)
        # tz naive の datetime を直接書き込み (read_sync_timestamp が None で返す)
        (sync_dir / "mapping_routing.json").write_text(
            json.dumps({"fetched_at": "2026-05-09T14:30:00"}),  # tz 欠落
            encoding="utf-8",
        )
        # JSON 破損
        (sync_dir / "report_staff.json").write_text("{ broken json", encoding="utf-8")

        fixed_now = _dt.datetime(2026, 5, 9, 14, 30, tzinfo=_dt.UTC)
        root = tk.Tk()
        try:
            launcher = Launcher(
                config=AppConfig(),
                config_path=cfg,
                root=root,
                now_fn=lambda: fixed_now,
                defer_initial_refresh=False,
            )
            assert launcher._sync_vars["mapping_routing"].get() == (
                "居宅対照表: 不明"
            )
            assert launcher._sync_vars["report_staff"].get() == (
                "担当者マッピング: 不明"
            )
        finally:
            root.destroy()

    def test_mapping_routing_label_reflects_cache(self, tmp_path: Path) -> None:
        """``mapping_routing`` timestamp 書込後、起動 Launcher が分前表示になる。"""
        import datetime as _dt
        import tkinter as tk

        from wiseman_hub.cloud.sync_label import (
            sync_cache_dir_for,
            write_sync_timestamp,
        )

        cfg = self._make_config_path(tmp_path)
        cache_dir = sync_cache_dir_for(cfg)
        ts = _dt.datetime(2026, 5, 9, 14, 25, tzinfo=_dt.UTC)
        write_sync_timestamp(cache_dir, "mapping_routing", ts=ts)

        fixed_now = _dt.datetime(2026, 5, 9, 14, 30, tzinfo=_dt.UTC)
        root = tk.Tk()
        try:
            launcher = Launcher(
                config=AppConfig(),
                config_path=cfg,
                root=root,
                now_fn=lambda: fixed_now,
                defer_initial_refresh=False,
            )
            text = launcher._sync_vars["mapping_routing"].get()
            assert text.startswith("居宅対照表: ")
            # 5 分前 (300 秒) → "5 分前" 表示
            assert text.endswith("(5 分前)")
        finally:
            root.destroy()

    def test_reload_config_refreshes_sync_summary(self, tmp_path: Path) -> None:
        """``reload_config`` で sync_summary が再描画される (新規 cache 反映)。"""
        import datetime as _dt
        import tkinter as tk

        from wiseman_hub.cloud.sync_label import (
            sync_cache_dir_for,
            write_sync_timestamp,
        )

        cfg = self._make_config_path(tmp_path)

        fixed_now = _dt.datetime(2026, 5, 9, 14, 30, tzinfo=_dt.UTC)
        root = tk.Tk()
        try:
            launcher = Launcher(
                config=AppConfig(),
                config_path=cfg,
                root=root,
                now_fn=lambda: fixed_now,
                defer_initial_refresh=False,
            )
            # 起動直後は cache 不在 → 不明 (Phase 1 ChecklistCDialog と統一)
            assert launcher._sync_vars["report_staff"].get() == (
                "担当者マッピング: 不明"
            )
            # cache 作成後 reload_config → 再描画
            cache_dir = sync_cache_dir_for(cfg)
            ts = _dt.datetime(2026, 5, 9, 14, 28, tzinfo=_dt.UTC)
            write_sync_timestamp(cache_dir, "report_staff", ts=ts)
            launcher.reload_config(launcher._config)
            text = launcher._sync_vars["report_staff"].get()
            assert text.startswith("担当者マッピング: ")
            assert text.endswith("(2 分前)")
        finally:
            root.destroy()

    def test_sheet_list_cache_label_reflects_fetched_at(
        self, tmp_path: Path
    ) -> None:
        """``sheet_list_cache`` の fetched_at が「シート一覧」行に反映される。

        ``save()`` は現在時刻で書き込むため fixed_now との差が unstable になる。
        本 test は cache JSON を直接 fixed_now-3 分の timestamp で書き、
        分前表示が deterministic になるよう調整する。
        """
        import datetime as _dt
        import json
        import tkinter as tk

        from wiseman_hub.cloud.sheet_list_cache import (
            cache_dir_for as sheet_cache_dir_for,
        )
        from wiseman_hub.config import AppConfig as _AppConfig
        from wiseman_hub.config import ChecklistConfig

        cfg = self._make_config_path(tmp_path)
        sheet_dir = sheet_cache_dir_for(cfg)
        sheet_dir.mkdir(parents=True, exist_ok=True)

        fixed_now = _dt.datetime(2026, 5, 9, 14, 30, tzinfo=_dt.UTC)
        ts_fetched = _dt.datetime(2026, 5, 9, 14, 27, tzinfo=_dt.UTC)
        (sheet_dir / "spread_xyz.json").write_text(
            json.dumps(
                {
                    "spreadsheet_id": "spread_xyz",
                    "sheet_names": ["25年12月", "26年1月"],
                    "fetched_at": ts_fetched.isoformat(),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        root = tk.Tk()
        try:
            launcher = Launcher(
                config=_AppConfig(
                    checklist=ChecklistConfig(spreadsheet_id="spread_xyz"),
                ),
                config_path=cfg,
                root=root,
                now_fn=lambda: fixed_now,
                defer_initial_refresh=False,
            )
            text = launcher._sync_vars["sheets"].get()
            assert text.startswith("シート一覧: ")
            # 3 分前 (180 秒) → "3 分前" 表示で deterministic
            assert text.endswith("(3 分前)")
        finally:
            root.destroy()


# ---------------------------------------------------------------------------
# Phase 2-β (Issue #238): I-2 — _refresh_sync_summary を window 描画後に遅延
# ---------------------------------------------------------------------------


@tk_required
class TestLauncherDeferredInitialRefresh:
    """Phase 2-β (I-2): 起動時 cache I/O を Tk window 描画後に遅延する。

    production default は ``defer_initial_refresh=True`` (after_idle 経由)、
    test では ``False`` を渡して deterministic な同期実行に切替。

    本テストは defer 機構そのもの (True 時の挙動) を確認する。
    """

    def _make_config_path(self, tmp_path: Path) -> Path:
        cfg = tmp_path / "wiseman-hub" / "config" / "default.toml"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text("", encoding="utf-8")
        return cfg

    def test_initial_render_shows_unknown_when_deferred(
        self, tmp_path: Path
    ) -> None:
        """``defer_initial_refresh=True`` (default) なら ``__init__`` 直後は
        StringVar が初期値「不明」のままで cache read を行わない。"""
        import datetime as _dt
        import tkinter as tk

        from wiseman_hub.cloud.sync_label import (
            sync_cache_dir_for,
            write_sync_timestamp,
        )

        cfg = self._make_config_path(tmp_path)
        cache_dir = sync_cache_dir_for(cfg)
        ts = _dt.datetime(2026, 5, 9, 14, 25, tzinfo=_dt.UTC)
        write_sync_timestamp(cache_dir, "mapping_routing", ts=ts)

        fixed_now = _dt.datetime(2026, 5, 9, 14, 30, tzinfo=_dt.UTC)
        root = tk.Tk()
        try:
            launcher = Launcher(
                config=AppConfig(),
                config_path=cfg,
                root=root,
                now_fn=lambda: fixed_now,
                # defer_initial_refresh は default で True (production)
            )
            # __init__ 直後 (mainloop 開始前) は initial 値「不明」のまま
            assert launcher._sync_vars["mapping_routing"].get() == (
                "居宅対照表: 不明"
            )
            # Tk idle queue を回すと after_idle callback が走り cache 値で update
            root.update_idletasks()
            text = launcher._sync_vars["mapping_routing"].get()
            assert text.startswith("居宅対照表: ")
            assert text.endswith("(5 分前)")
        finally:
            root.destroy()

    def test_default_defer_is_true(self, tmp_path: Path) -> None:
        """``defer_initial_refresh`` の default 値は True (production 想定)。"""
        import inspect

        from wiseman_hub.ui.launcher import Launcher as _Launcher

        sig = inspect.signature(_Launcher.__init__)
        assert sig.parameters["defer_initial_refresh"].default is True

    def test_defer_false_renders_immediately(self, tmp_path: Path) -> None:
        """``defer_initial_refresh=False`` なら ``__init__`` 内で同期 refresh。

        既存 Phase 2-α テスト 5 件 (cache 値を直接 assert) が動くための仕掛け。
        """
        import datetime as _dt
        import tkinter as tk

        from wiseman_hub.cloud.sync_label import (
            sync_cache_dir_for,
            write_sync_timestamp,
        )

        cfg = self._make_config_path(tmp_path)
        cache_dir = sync_cache_dir_for(cfg)
        ts = _dt.datetime(2026, 5, 9, 14, 25, tzinfo=_dt.UTC)
        write_sync_timestamp(cache_dir, "mapping_routing", ts=ts)

        fixed_now = _dt.datetime(2026, 5, 9, 14, 30, tzinfo=_dt.UTC)
        root = tk.Tk()
        try:
            launcher = Launcher(
                config=AppConfig(),
                config_path=cfg,
                root=root,
                now_fn=lambda: fixed_now,
                defer_initial_refresh=False,
            )
            # __init__ 直後で既に cache 値が反映されている (update_idletasks 不要)
            text = launcher._sync_vars["mapping_routing"].get()
            assert text.startswith("居宅対照表: ")
            assert text.endswith("(5 分前)")
        finally:
            root.destroy()
