"""ChecklistSettingsDialog の TOML フラグメント round-trip テスト。

PR #179 (PR-α v3) で追加された ``suggest_patterns`` を設定ダイアログ経由で
読み書きできることを保証する（regression 防止）。

PR #179 までは `_staff_to_toml` / `_parse_staff_toml` が `suggest_patterns` を
扱わないため、設定ダイアログを開いて保存すると永続化済みの suggest_patterns が
消える事故が起きうる。本テストはその修正を固定する。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wiseman_hub.config import ReportStaffEntry
from wiseman_hub.ui.checklist_settings_dialog import (
    _parse_staff_toml,
    _staff_to_toml,
)


class TestStaffTomlRoundTrip:
    def test_suggest_patterns_round_trip_preserves_tuple(self) -> None:
        # Issue #27 続編 H2: suggest_patterns は tuple[str, ...]。
        original = {
            "宮下": ReportStaffEntry(
                base_dir=Path("\\\\Tera-station\\share\\PT 宮下"),
                suggest_patterns=(
                    "リハ経過報告書/令和{era}年/リハ経過報告書*{month}月*.xlsx",
                ),
            ),
        }
        text = _staff_to_toml(original)
        roundtrip = _parse_staff_toml(text)
        assert roundtrip["宮下"].base_dir == original["宮下"].base_dir
        assert roundtrip["宮下"].suggest_patterns == original["宮下"].suggest_patterns

    def test_multi_staff_with_multiple_patterns(self) -> None:
        original = {
            "小島": ReportStaffEntry(
                base_dir=Path("\\\\Tera-station\\share\\PT 小島"),
                suggest_patterns=(
                    "リハ経過報告書(新)/経過報告書*令和{era}年{month}月*.xlsx",
                    "リハ経過報告書(旧)/令和{era}年度/経過報告書*{month}月*.xlsx",
                ),
            ),
            "OT 小林": ReportStaffEntry(
                base_dir=Path("\\\\Tera-station\\share\\OT小林"),
                suggest_patterns=("経過報告書/R{era}/*{month}月*.xlsx",),
            ),
        }
        text = _staff_to_toml(original)
        roundtrip = _parse_staff_toml(text)
        # PR-γ v2 (silent-failure-hunter I1): UI 経路でも normalize_lookup_key で
        # key 正規化、空白除去後の key で格納される (デモ事案再発防止)。
        assert set(roundtrip.keys()) == {"小島", "OT小林"}
        assert roundtrip["小島"].suggest_patterns == original["小島"].suggest_patterns
        assert roundtrip["OT小林"].suggest_patterns == original["OT 小林"].suggest_patterns

    def test_empty_suggest_patterns_emits_empty_list(self) -> None:
        original = {
            "test": ReportStaffEntry(base_dir=Path("C:/x"), suggest_patterns=()),
        }
        text = _staff_to_toml(original)
        # TOML 出力は array リテラル `[]` (TOML 構文として list/tuple は array)。
        assert "suggest_patterns = []" in text
        roundtrip = _parse_staff_toml(text)
        # Python 側受け取りは tuple (空 tuple `()`)。
        assert roundtrip["test"].suggest_patterns == ()

    def test_deprecated_fields_preserved_when_non_empty(self) -> None:
        """旧 MVP 互換: year_subfolder_template / file_template が非空なら保持。"""
        original = {
            "legacy": ReportStaffEntry(
                base_dir=Path("C:/legacy"),
                suggest_patterns=(),
                year_subfolder_template="令和{era}年",
                file_template="経過報告書*{month}月*.xlsx",
            ),
        }
        text = _staff_to_toml(original)
        roundtrip = _parse_staff_toml(text)
        assert roundtrip["legacy"].year_subfolder_template == "令和{era}年"
        assert roundtrip["legacy"].file_template == "経過報告書*{month}月*.xlsx"

    def test_deprecated_fields_omitted_when_empty(self) -> None:
        """新規入力では deprecated フィールドが空なら出力しない（dump 結果が読みやすい）。"""
        original = {
            "new": ReportStaffEntry(
                base_dir=Path("C:/x"),
                suggest_patterns=("a/*.xlsx",),
            ),
        }
        text = _staff_to_toml(original)
        assert "year_subfolder_template" not in text
        assert "file_template" not in text

    def test_quoted_key_with_space_round_trip(self) -> None:
        """key にスペース・特殊文字を含むケース（"PT 宮下" など）の round-trip。

        PR-γ v2 (silent-failure-hunter I1): UI 経路でも `normalize_lookup_key`
        で正規化されるため、roundtrip 後の key は空白除去後 (`"PT宮下"`) になる。
        TOML 上は元の `"PT 宮下"` が記録されるが、メモリ上 dict key は正規化済。
        """
        original = {
            "PT 宮下": ReportStaffEntry(
                base_dir=Path("C:/x"),
                suggest_patterns=("a/*.xlsx",),
            ),
        }
        text = _staff_to_toml(original)
        roundtrip = _parse_staff_toml(text)
        assert "PT宮下" in roundtrip
        assert roundtrip["PT宮下"].suggest_patterns == ("a/*.xlsx",)


class TestStaffTomlValidation:
    def test_suggest_patterns_must_be_list(self) -> None:
        bad = '["x"]\nbase_dir = "C:/x"\nsuggest_patterns = "not a list"\n'
        with pytest.raises(TypeError, match="suggest_patterns must be a list"):
            _parse_staff_toml(bad)

    def test_suggest_patterns_elements_must_be_strings(self) -> None:
        bad = '["x"]\nbase_dir = "C:/x"\nsuggest_patterns = [1, 2]\n'
        with pytest.raises(TypeError, match="elements must be strings"):
            _parse_staff_toml(bad)

    def test_empty_text_returns_empty_dict(self) -> None:
        assert _parse_staff_toml("") == {}
        assert _parse_staff_toml("   \n  ") == {}


class TestStaffTomlPropagatesDataclassTypeGuard:
    """Issue #27 続編 C: ``str(entry.get(...))`` 削除により、TOML 値の非文字列が
    ``ReportStaffEntry.__post_init__`` の ``_check_str`` で TypeError として
    起動時に拒否されることを固定する (旧版は ``"123"`` 等に silent 強制変換)。"""

    def test_base_dir_must_be_str_or_path_not_int(self) -> None:
        bad = '["宮下"]\nbase_dir = 123\nsuggest_patterns = []\n'
        # Issue #27 続編 G Phase 3b: coerce_path で TypeError raise (str/Path 以外)。
        with pytest.raises(TypeError, match=r"base_dir must be str \(TOML\) or Path"):
            _parse_staff_toml(bad)

    def test_base_dir_must_be_str_or_path_not_bool(self) -> None:
        bad = '["宮下"]\nbase_dir = true\nsuggest_patterns = []\n'
        with pytest.raises(TypeError, match=r"base_dir must be str \(TOML\) or Path"):
            _parse_staff_toml(bad)

    def test_base_dir_must_be_str_or_path_not_float(self) -> None:
        bad = '["宮下"]\nbase_dir = 1.5\nsuggest_patterns = []\n'
        with pytest.raises(TypeError, match=r"base_dir must be str \(TOML\) or Path"):
            _parse_staff_toml(bad)

    def test_year_subfolder_template_must_be_str(self) -> None:
        bad = (
            '["宮下"]\nbase_dir = "C:/x"\n'
            "suggest_patterns = []\nyear_subfolder_template = 2026\n"
        )
        with pytest.raises(
            TypeError, match=r"ReportStaffEntry\.year_subfolder_template must be str"
        ):
            _parse_staff_toml(bad)

    def test_file_template_must_be_str(self) -> None:
        bad = (
            '["宮下"]\nbase_dir = "C:/x"\n'
            "suggest_patterns = []\nfile_template = 99\n"
        )
        with pytest.raises(
            TypeError, match=r"ReportStaffEntry\.file_template must be str"
        ):
            _parse_staff_toml(bad)

    def test_valid_string_values_still_pass(self) -> None:
        """正常系: 全フィールドが str なら成功し、値が保持されることを確認 (回帰防止)。"""
        good = (
            '["宮下"]\n'
            'base_dir = "C:/PT宮下"\n'
            'suggest_patterns = ["a/*.xlsx"]\n'
            'year_subfolder_template = "令和{era}年"\n'
            'file_template = "経過報告書*{month}月*.xlsx"\n'
        )
        result = _parse_staff_toml(good)
        # Issue #27 続編 G Phase 3b: base_dir は Path 型に移行済 (coerce_path 経由)。
        assert result["宮下"].base_dir == Path("C:/PT宮下")
        # Issue #27 続編 H2: suggest_patterns は tuple[str, ...]。
        assert result["宮下"].suggest_patterns == ("a/*.xlsx",)
        assert result["宮下"].year_subfolder_template == "令和{era}年"
        assert result["宮下"].file_template == "経過報告書*{month}月*.xlsx"

    def test_missing_fields_default_to_empty_str(self) -> None:
        """default ``""`` が dataclass の str ガードを通過することを確認 (回帰防止)。"""
        good = '["宮下"]\nbase_dir = "C:/x"\nsuggest_patterns = []\n'
        result = _parse_staff_toml(good)
        # base_dir 以外が無くても default "" で構築でき、TypeError にならない
        assert result["宮下"].year_subfolder_template == ""
        assert result["宮下"].file_template == ""


# ---------------------------------------------------------------------------
# Phase 2-α (Issue #238) review 反映 (pr-test 3.1 rating 7):
# _record_sync_timestamp 呼び出し位置を直接検証する pure-logic test。
# Tk 不要 (関数を直接 import + 副作用ファイルの存在確認だけ)。
# ---------------------------------------------------------------------------


class TestRecordSyncTimestamp:
    """Phase 2-α (Issue #238): sync timestamp 記録の呼び出し位置検証。

    PR レビューで指摘された通り、push_routing / pull_routing / pull_report_staff の
    成功時に **だけ** ``_record_sync_timestamp`` が呼ばれることを保証する。
    将来の refactor で呼び出し位置が誤って verification 前に移動した場合、Launcher の
    sync_summary が「失敗した同期」を「成功」と誤認する regression を防ぐ。

    完全な GCS push/pull のモックは別 PR (Phase 2-β / 3) で対応予定。本 test は
    helper 関数 ``_record_sync_timestamp`` の単体動作を pure-logic で fix する。
    """

    def _make_config_path(self, tmp_path):  # type: ignore[no-untyped-def]
        cfg = tmp_path / "wiseman-hub" / "config" / "default.toml"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text("", encoding="utf-8")
        return cfg

    def test_record_sync_timestamp_writes_under_sync_cache_dir(
        self, tmp_path,
    ) -> None:  # type: ignore[no-untyped-def]
        """`_record_sync_timestamp(config_path, name)` 呼出で
        ``<config_parent_parent>/cache/sync/<name>.json`` が作成される。"""
        from wiseman_hub.cloud.sync_label import (
            read_sync_timestamp,
            sync_cache_dir_for,
        )
        from wiseman_hub.ui.checklist_settings_dialog import (
            _record_sync_timestamp,
        )

        cfg = self._make_config_path(tmp_path)
        _record_sync_timestamp(cfg, "mapping_routing")

        sync_dir = sync_cache_dir_for(cfg)
        json_path = sync_dir / "mapping_routing.json"
        assert json_path.exists()
        # 書き込まれた timestamp が tz-aware で読み出せる
        ts = read_sync_timestamp(sync_dir, "mapping_routing")
        assert ts is not None and ts.tzinfo is not None

    @pytest.mark.parametrize("name", ["mapping_routing", "report_staff"])
    def test_record_sync_timestamp_per_name_isolated(
        self, tmp_path, name: str,
    ) -> None:  # type: ignore[no-untyped-def]
        """name ごとに別ファイルに書かれる (mapping_routing と report_staff の混線無し)。"""
        from wiseman_hub.cloud.sync_label import sync_cache_dir_for
        from wiseman_hub.ui.checklist_settings_dialog import (
            _record_sync_timestamp,
        )

        cfg = self._make_config_path(tmp_path)
        _record_sync_timestamp(cfg, name)

        sync_dir = sync_cache_dir_for(cfg)
        assert (sync_dir / f"{name}.json").exists()
        # 他の name のファイルは作成されない
        other = "report_staff" if name == "mapping_routing" else "mapping_routing"
        assert not (sync_dir / f"{other}.json").exists()

    def test_record_sync_timestamp_invalid_name_raises(
        self, tmp_path,
    ) -> None:  # type: ignore[no-untyped-def]
        """write_sync_timestamp の name validation が _record_sync_timestamp 経由でも有効。

        将来 caller が誤って path traversal を含む name を渡しても構造的に弾かれる。
        """
        from wiseman_hub.ui.checklist_settings_dialog import (
            _record_sync_timestamp,
        )

        cfg = self._make_config_path(tmp_path)
        with pytest.raises(ValueError):
            _record_sync_timestamp(cfg, "../traversal")

    def test_handler_calls_record_at_correct_position_in_source(self) -> None:
        """source code static check: Phase 2-β 後の callsite 配置を固定する。

        Phase 2-α の配置 (push + 2 pull) は **F4 のため変更**:
            - push_routing 成功 → ``_record_sync_timestamp("mapping_routing")``
            - on_save 成功 + ``self._pulled_routing`` flag → ``_record_sync_timestamp("mapping_routing")``
            - on_save 成功 + ``self._pulled_staff`` flag → ``_record_sync_timestamp("report_staff")``

        合計 callsite 3 は維持されるが pull 系の直接呼出は **0** に減少
        (closed-loop verify: TOML 永続化なき pull で「同期済」表示にしないため)。
        """
        from pathlib import Path

        src = (
            Path(__file__).parent.parent.parent.parent
            / "src"
            / "wiseman_hub"
            / "ui"
            / "checklist_settings_dialog.py"
        ).read_text(encoding="utf-8")
        # 3 箇所で _record_sync_timestamp が呼ばれている (push + on_save 内 if 2 件)
        assert src.count('_record_sync_timestamp(self._config_path, ') == 3
        # mapping_routing は 2 callsite (push_routing 直後 + on_save 内 if)
        assert (
            src.count('_record_sync_timestamp(self._config_path, "mapping_routing")')
            == 2
        )
        # report_staff は 1 callsite (on_save 内 if のみ、pull 直後ではない)
        assert (
            src.count('_record_sync_timestamp(self._config_path, "report_staff")')
            == 1
        )


# ---------------------------------------------------------------------------
# Phase 2-β (Issue #238): F4 (UX 重要) — pull 系 closed-loop verify
# ---------------------------------------------------------------------------


class TestPulledDirtyFlag:
    """Phase 2-β (F4): pull 直後ではなく save 成功後に sync_timestamp を打つ。

    現状 (Phase 2-α) は ``_on_pull_routing`` / ``_on_pull_staff`` が pull 直後に
    timestamp を記録するが、ユーザーが「保存」を押さずキャンセルすると、
    TOML config が古いまま sync_summary だけ「同期済」表示で**矛盾**。

    Phase 2-β では dirty flag (``self._pulled_routing`` / ``self._pulled_staff``) を
    pull 成功時に立て、``_on_save`` 成功時に flag が True の側だけ記録する。
    """

    def _src(self) -> str:
        from pathlib import Path
        return (
            Path(__file__).parent.parent.parent.parent
            / "src"
            / "wiseman_hub"
            / "ui"
            / "checklist_settings_dialog.py"
        ).read_text(encoding="utf-8")

    def test_dirty_flags_initialized_to_false_in_init(self) -> None:
        """``__init__`` で ``self._pulled_routing`` / ``self._pulled_staff`` が
        False で初期化されることを source-level で保証。"""
        src = self._src()
        assert "self._pulled_routing = False" in src
        assert "self._pulled_staff = False" in src

    def test_pull_routing_sets_dirty_flag(self) -> None:
        """``_on_pull_routing`` 成功時に ``self._pulled_routing = True`` が set される。"""
        src = self._src()
        # _on_pull_routing 関数本体に flag set がある
        # (search: def _on_pull_routing から def _on_pull_staff の手前まで)
        marker_start = "def _on_pull_routing("
        marker_end = "def _on_pull_staff("
        start = src.index(marker_start)
        end = src.index(marker_end)
        body = src[start:end]
        assert "self._pulled_routing = True" in body

    def test_pull_staff_sets_dirty_flag(self) -> None:
        """``_on_pull_staff`` 成功時に ``self._pulled_staff = True`` が set される。"""
        src = self._src()
        marker_start = "def _on_pull_staff("
        marker_end = "def _on_save("
        start = src.index(marker_start)
        end = src.index(marker_end)
        body = src[start:end]
        assert "self._pulled_staff = True" in body

    def test_on_save_records_only_when_dirty(self) -> None:
        """``_on_save`` 成功 path 内に dirty flag の if guard で
        ``_record_sync_timestamp`` 呼出が条件付きで存在する。"""
        src = self._src()
        marker_start = "def _on_save("
        # _on_save の終わり (module-level helper の前) を探す
        marker_end = "def _record_sync_timestamp("
        start = src.index(marker_start)
        end = src.index(marker_end)
        body = src[start:end]
        # 両方の dirty flag を if guard で参照
        assert "if self._pulled_routing" in body
        assert "if self._pulled_staff" in body
        # 両方の name 文字列で record 呼出
        assert (
            '_record_sync_timestamp(self._config_path, "mapping_routing")' in body
        )
        assert (
            '_record_sync_timestamp(self._config_path, "report_staff")' in body
        )
        # save 成功時の reset (flag を False に戻す)
        assert "self._pulled_routing = False" in body
        assert "self._pulled_staff = False" in body

    def test_pull_handlers_do_not_call_record_directly(self) -> None:
        """``_on_pull_routing`` / ``_on_pull_staff`` は **直接** record しない。

        これが Phase 2-β F4 の本質: pull 直後ではなく save 成功後にだけ記録する。
        """
        src = self._src()
        # _on_pull_routing
        start = src.index("def _on_pull_routing(")
        end = src.index("def _on_pull_staff(")
        assert (
            "_record_sync_timestamp("
            not in src[start:end]
        )
        # _on_pull_staff
        start = src.index("def _on_pull_staff(")
        end = src.index("def _on_save(")
        assert (
            "_record_sync_timestamp("
            not in src[start:end]
        )


class TestRecordWarnsOnWriteFailure:
    """Phase 2-β (F1): _record_sync_timestamp は write_sync_timestamp の戻り値を
    確認し、False ならば warn ログを出す。"""

    def test_record_logs_warning_when_write_returns_false(
        self, tmp_path, monkeypatch, caplog,
    ) -> None:  # type: ignore[no-untyped-def]
        """write_sync_timestamp が False を返す経路で _record_sync_timestamp が
        warning ログを emit する。"""
        import logging

        from wiseman_hub.ui.checklist_settings_dialog import (
            _record_sync_timestamp,
        )

        cfg = tmp_path / "wiseman-hub" / "config" / "default.toml"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text("", encoding="utf-8")

        # write_sync_timestamp が常に False を返すよう mock
        def _always_false(*args: object, **kwargs: object) -> bool:
            return False

        monkeypatch.setattr(
            "wiseman_hub.cloud.sync_label.write_sync_timestamp", _always_false,
        )
        with caplog.at_level(logging.WARNING):
            _record_sync_timestamp(cfg, "mapping_routing")
        # caller (UI dialog 側) で warn が emit されている
        assert any(
            "sync timestamp" in rec.message.lower()
            and "mapping_routing" in rec.message
            for rec in caplog.records
        )

    def test_record_silent_when_write_returns_true(
        self, tmp_path, monkeypatch, caplog,
    ) -> None:  # type: ignore[no-untyped-def]
        """write_sync_timestamp が True (success) を返す経路では caller は warn しない。"""
        import logging

        from wiseman_hub.ui.checklist_settings_dialog import (
            _record_sync_timestamp,
        )

        cfg = tmp_path / "wiseman-hub" / "config" / "default.toml"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text("", encoding="utf-8")

        with caplog.at_level(logging.WARNING):
            _record_sync_timestamp(cfg, "mapping_routing")
        # 通常成功時は WARNING 以上のログが出ない
        warns = [
            rec for rec in caplog.records if rec.levelno >= logging.WARNING
        ]
        assert warns == []


# ---------------------------------------------------------------------------
# Phase 2-β review 反映 (pr-test P0 rating 9 + codex rating 7-8 推奨):
# F4 dirty flag の behavioral test (実 Tk + monkeypatch)。source-level static
# check は維持しつつ、構造変更に強い動作テストを薄く追加。
# ---------------------------------------------------------------------------


tk_required = pytest.mark.tk_required


@tk_required
class TestPulledDirtyFlagBehavioral:
    """Phase 2-β (F4) review 反映: dirty flag の挙動を Tk 上で実証する。

    review (pr-test P0 rating 9): source-level static check はリファクタで
    リテラルが移動すると空振りするため、最小 1 件は behavioral に固定する。
    review (codex rating 8 conf 90): save 失敗時に flag を維持して retry で
    正しく記録される invariant も合わせて固定。

    Tk 環境がない CI runner では ``@tk_required`` で skip される (Mac dev も同様)。
    Linux CI で実行され、構造変更で dirty flag 機構が壊れたら検出する役割。
    """

    def _make_config_path(self, tmp_path):  # type: ignore[no-untyped-def]
        from pathlib import Path  # noqa: F401 (Path 自体は型注釈で使用)
        cfg = tmp_path / "wiseman-hub" / "config" / "default.toml"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text("", encoding="utf-8")
        return cfg

    def test_save_failure_keeps_dirty_flags_for_retry(
        self, tmp_path, monkeypatch,
    ) -> None:  # type: ignore[no-untyped-def]
        """save 失敗 (TOML parse error) で flag が True のまま残り、retry save で
        正しく記録される (closed-loop verify の本質的 invariant)。"""
        import tkinter as tk

        from wiseman_hub.config import AppConfig
        from wiseman_hub.ui import checklist_settings_dialog as csd

        # _record_sync_timestamp の呼出回数を観測
        recorded: list[tuple[str, str]] = []

        def _spy_record(config_path, name):  # type: ignore[no-untyped-def]
            recorded.append((str(config_path), name))

        monkeypatch.setattr(
            csd, "_record_sync_timestamp", _spy_record,
        )
        # messagebox を全部 fake (yes/no は True、info/error は no-op)
        monkeypatch.setattr(
            csd.messagebox, "askyesno", lambda *a, **kw: True,
        )
        monkeypatch.setattr(
            csd.messagebox, "showinfo", lambda *a, **kw: None,
        )
        monkeypatch.setattr(
            csd.messagebox, "showerror", lambda *a, **kw: None,
        )

        cfg = self._make_config_path(tmp_path)
        root = tk.Tk()
        try:
            dialog = csd.ChecklistSettingsDialog(
                parent=root, config=AppConfig(), config_path=cfg,
            )
            # pull 完了相当に dirty flag を立てる (実 GCP 呼出は重いため flag を
            # 直接 set。_on_pull_routing 内部の flag 立て位置は別 test で固定済)
            dialog._pulled_routing = True
            # 不正 TOML を Text widget に流し込み save で parse error 経路に
            dialog._routing_text.delete("1.0", "end")
            dialog._routing_text.insert("1.0", "this is not valid TOML = =")

            dialog._on_save()

            # AC: parse error で early return、_record_sync_timestamp 未呼出
            assert recorded == []
            # AC: flag は True のまま (retry save で打てる)
            assert dialog._pulled_routing is True

            # 修正して再 save: 今度は record が打たれて flag リセット
            dialog._routing_text.delete("1.0", "end")
            dialog._routing_text.insert("1.0", '"居宅A" = "FAX/事業所1"')
            dialog._staff_text.delete("1.0", "end")
            # save_config を mock で成功させる (実 fs 書込を回避)
            monkeypatch.setattr(
                csd, "save_config", lambda *a, **kw: None,
            )
            dialog._on_save()

            # AC: routing 側だけ record (staff は flag False のまま)
            names = [n for _, n in recorded]
            assert names == ["mapping_routing"]
            # AC: 成功 path で flag リセット
            assert dialog._pulled_routing is False
            assert dialog._pulled_staff is False
        finally:
            root.destroy()

    def test_save_success_records_only_dirty_side(
        self, tmp_path, monkeypatch,
    ) -> None:  # type: ignore[no-untyped-def]
        """片側 (staff のみ) pull → save 成功時に staff だけ record される。"""
        import tkinter as tk

        from wiseman_hub.config import AppConfig
        from wiseman_hub.ui import checklist_settings_dialog as csd

        recorded: list[str] = []

        def _spy_record(config_path, name):  # type: ignore[no-untyped-def]
            recorded.append(name)

        monkeypatch.setattr(csd, "_record_sync_timestamp", _spy_record)
        monkeypatch.setattr(
            csd.messagebox, "showinfo", lambda *a, **kw: None,
        )
        monkeypatch.setattr(
            csd.messagebox, "showerror", lambda *a, **kw: None,
        )
        monkeypatch.setattr(csd, "save_config", lambda *a, **kw: None)

        cfg = self._make_config_path(tmp_path)
        root = tk.Tk()
        try:
            dialog = csd.ChecklistSettingsDialog(
                parent=root, config=AppConfig(), config_path=cfg,
            )
            # staff のみ pull した状態をシミュレート
            dialog._pulled_routing = False
            dialog._pulled_staff = True
            # routing は空 (元の値のまま、Text widget はそのまま)
            # save 実行
            dialog._on_save()

            # AC: report_staff だけ record、mapping_routing は record されない
            assert recorded == ["report_staff"]
            # AC: 両 flag が False に reset (record されたのは staff だけだが
            # routing も False のままで一貫)
            assert dialog._pulled_routing is False
            assert dialog._pulled_staff is False
        finally:
            root.destroy()


class TestParseTomlNormalization:
    """PR-γ v2 (silent-failure-hunter I1): 設定ダイアログ保存経路の key 正規化。

    `_parse_routing_toml` / `_parse_staff_toml` が dict key を `normalize_lookup_key`
    で正規化することで、設定ダイアログから保存した直後の同一プロセス内 lookup が
    表記揺れで silent failure する経路を防ぐ。Session 78 実機デモで判明した
    `姫路医療生活協同組合 あぼし` 事案の再発防止。
    """

    def test_routing_full_width_space_key_normalized(self) -> None:
        """全角空白 key が空白除去後の key で格納される。"""
        from wiseman_hub.ui.checklist_settings_dialog import _parse_routing_toml
        text = '"姫路医療生活協同組合　あぼし" = "FAX_NAME"'
        result = _parse_routing_toml(text)
        # key は normalize_lookup_key で空白除去
        assert "姫路医療生活協同組合あぼし" in result
        # 生の全角空白 key では引けない (= 正規化後 lookup でなければ hit しない)
        assert "姫路医療生活協同組合　あぼし" not in result

    def test_routing_half_width_and_full_width_collide_to_same_key(self) -> None:
        """全角/半角 別 entry で書いても同一 key で衝突 (最後の値が勝つ)。"""
        from wiseman_hub.ui.checklist_settings_dialog import _parse_routing_toml
        text = (
            '"姫路医療生活協同組合 あぼし" = "FAX1"\n'
            '"姫路医療生活協同組合　あぼし" = "FAX2"'
        )
        result = _parse_routing_toml(text)
        # 正規化後同一 key、最後の値が勝つ
        assert len(result) == 1
        assert result["姫路医療生活協同組合あぼし"] == "FAX2"

    def test_staff_key_normalized(self) -> None:
        """staff name key も normalize_lookup_key で正規化される。"""
        from wiseman_hub.ui.checklist_settings_dialog import _parse_staff_toml
        text = '[" PT 宮下 "]\nbase_dir = "C:\\\\test"\nsuggest_patterns = ["x.xlsx"]'
        result = _parse_staff_toml(text)
        # key は trim + 空白除去
        assert "PT宮下" in result
        assert " PT 宮下 " not in result
