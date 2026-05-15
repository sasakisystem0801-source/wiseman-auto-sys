"""`install_tk_exception_guard` のテスト (Issue #67)。

launcher / settings / SessionPicker (13C) で共通利用する Tk callback 例外ガード。
PII 防御: logger には型名のみ、messagebox は sanitized メッセージ、二次 showerror
失敗は warning ログで握り潰し。
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest


class _FakeRoot:
    """report_callback_exception を書き込める最小 stub。"""

    def __init__(self) -> None:
        self.report_callback_exception: Any = None


class TestInstallTkExceptionGuard:
    def test_registers_handler_on_root(self) -> None:
        from wiseman_hub.ui.common import install_tk_exception_guard

        root = _FakeRoot()
        messagebox = MagicMock()
        install_tk_exception_guard(
            root, component="launcher", messagebox=messagebox
        )

        assert callable(root.report_callback_exception)

    def test_handler_logs_type_name_only(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """ログには exc_type.__name__ のみ。exc_value の文字列（PII 含みうる）は出さない。"""
        from wiseman_hub.ui.common import install_tk_exception_guard

        root = _FakeRoot()
        messagebox = MagicMock()
        install_tk_exception_guard(
            root, component="launcher", messagebox=messagebox
        )

        with caplog.at_level(logging.ERROR):
            err = ValueError("/Users/secret/patient-山田太郎.pdf")
            root.report_callback_exception(ValueError, err, None)

        assert "ValueError" in caplog.text
        assert "山田太郎" not in caplog.text
        assert "/Users/secret" not in caplog.text

    def test_handler_includes_component_in_log(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from wiseman_hub.ui.common import install_tk_exception_guard

        root = _FakeRoot()
        messagebox = MagicMock()
        install_tk_exception_guard(
            root, component="settings", messagebox=messagebox
        )

        with caplog.at_level(logging.ERROR):
            root.report_callback_exception(RuntimeError, RuntimeError("x"), None)

        assert "settings" in caplog.text
        assert "RuntimeError" in caplog.text

    def test_handler_calls_showerror_with_sanitized_message(self) -> None:
        from wiseman_hub.ui.common import install_tk_exception_guard

        root = _FakeRoot()
        messagebox = MagicMock()
        install_tk_exception_guard(
            root, component="launcher", messagebox=messagebox
        )

        err = OSError("/secret/path.pdf")
        root.report_callback_exception(OSError, err, None)

        messagebox.showerror.assert_called_once()
        args, _ = messagebox.showerror.call_args
        body = args[1]
        assert "OSError" in body
        assert "/secret/path.pdf" not in body

    def test_handler_swallows_secondary_showerror_failure(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """messagebox.showerror が失敗しても二次例外を raise しない（warning ログのみ）。"""
        from wiseman_hub.ui.common import install_tk_exception_guard

        root = _FakeRoot()
        messagebox = MagicMock()
        messagebox.showerror.side_effect = RuntimeError("tk destroyed")
        install_tk_exception_guard(
            root, component="launcher", messagebox=messagebox
        )

        with caplog.at_level(logging.WARNING):
            root.report_callback_exception(ValueError, ValueError("x"), None)

        assert "RuntimeError" in caplog.text

    @pytest.mark.parametrize(
        "bad_component",
        ["", "launcher main", "session picker", "\t", "a\nb"],
    )
    def test_rejects_invalid_component_label(self, bad_component: str) -> None:
        """空文字・空白・制御文字入り component は ValueError（grep 可読性保護）。"""
        from wiseman_hub.ui.common import install_tk_exception_guard

        root = _FakeRoot()
        with pytest.raises(ValueError, match="component must be non-empty"):
            install_tk_exception_guard(
                root, component=bad_component, messagebox=MagicMock()
            )

    @pytest.mark.parametrize(
        "ok_component",
        ["launcher", "settings", "session_picker", "session_abc-123"],
    )
    def test_accepts_snake_case_component(self, ok_component: str) -> None:
        from wiseman_hub.ui.common import install_tk_exception_guard

        root = _FakeRoot()
        install_tk_exception_guard(
            root, component=ok_component, messagebox=MagicMock()
        )
        assert callable(root.report_callback_exception)

    def test_handler_raises_attribute_error_on_exc_type_none(self) -> None:
        """Issue #71 #1: exc_type=None は現行実装で AttributeError を raise する。

        Tk の `report_callback_exception` は通常 (exc_class, exc_value, tb) を渡すが、
        仕様外の呼び出しで exc_type=None になる可能性を踏まえ、現行挙動を契約として
        固定する。AttributeError は Tk の main loop に伝播して Tk 側でログされ、
        アプリ全体を停止させない（defense-in-depth）。

        Note: 現行挙動は `exc_type.__name__` の副作用的な崩壊。理想的には
        `getattr(exc_type, "__name__", "Unknown")` で defensive にする余地があるが、
        Tk 仕様外の入力に対する改善は本テストの scope 外（要 follow-up）。
        本テストは defensive 化された際に更新が必要となる契約テストとして機能する。
        """
        from wiseman_hub.ui.common import install_tk_exception_guard

        root = _FakeRoot()
        messagebox = MagicMock()
        install_tk_exception_guard(
            root, component="launcher", messagebox=messagebox
        )

        with pytest.raises(AttributeError):
            root.report_callback_exception(None, ValueError("x"), None)

        # showerror は AttributeError 発生前に呼ばれていない（型名解決で先に落ちる）
        messagebox.showerror.assert_not_called()

    def test_handler_does_not_swallow_system_exit(self) -> None:
        """Issue #71 #2: showerror が BaseException 派生を投げた場合は伝播させる。

        実装の二次失敗ハンドラは `except Exception` で KeyboardInterrupt / SystemExit
        を意図的に通す設計（プロセス終了を阻害しない）。regression 検知のため契約固定。
        """
        from wiseman_hub.ui.common import install_tk_exception_guard

        root = _FakeRoot()
        messagebox = MagicMock()
        messagebox.showerror.side_effect = SystemExit(1)
        install_tk_exception_guard(
            root, component="launcher", messagebox=messagebox
        )

        with pytest.raises(SystemExit):
            root.report_callback_exception(ValueError, ValueError("x"), None)

    def test_handler_does_not_swallow_keyboard_interrupt(self) -> None:
        """Issue #71 #2: showerror が KeyboardInterrupt を投げた場合も伝播。

        SystemExit と同じく、プロセス中断シグナルは握り潰さない契約。
        """
        from wiseman_hub.ui.common import install_tk_exception_guard

        root = _FakeRoot()
        messagebox = MagicMock()
        messagebox.showerror.side_effect = KeyboardInterrupt()
        install_tk_exception_guard(
            root, component="launcher", messagebox=messagebox
        )

        with pytest.raises(KeyboardInterrupt):
            root.report_callback_exception(ValueError, ValueError("x"), None)


# ---------------------------------------------------------------------------
# count_by_status / StatusCounts (pure function, Tk 不要)
# ---------------------------------------------------------------------------


class TestCountByStatus:
    def test_empty_iterable_returns_zero_total(self) -> None:
        from wiseman_hub.ui.common import count_by_status

        result = count_by_status([], lambda x: "x")
        assert result.total == 0
        assert dict(result.by_status) == {}

    def test_groups_by_label_and_counts(self) -> None:
        from wiseman_hub.ui.common import count_by_status

        items = ["a", "a", "b", "c", "b"]
        result = count_by_status(items, lambda x: x)
        assert result.total == 5
        assert dict(result.by_status) == {"a": 2, "b": 2, "c": 1}

    def test_label_fn_can_classify_objects(self) -> None:
        from wiseman_hub.ui.common import count_by_status

        items = [1, 2, 3, 4, 5]
        result = count_by_status(items, lambda n: "even" if n % 2 == 0 else "odd")
        assert result.total == 5
        assert dict(result.by_status) == {"odd": 3, "even": 2}

    def test_preserves_first_occurrence_order(self) -> None:
        """dict 挿入順を保つ（Python 3.7+ 仕様、to_summary_text のデフォルト順序保証）。"""
        from wiseman_hub.ui.common import count_by_status

        result = count_by_status(["c", "a", "b", "a"], lambda x: x)
        assert list(result.by_status.keys()) == ["c", "a", "b"]


class TestStatusCountsToSummaryText:
    def test_default_omits_zero_labels(self) -> None:
        from wiseman_hub.ui.common import StatusCounts

        counts = StatusCounts(total=5, by_status={"x": 2, "y": 0, "z": 3})
        text = counts.to_summary_text()
        assert text == "対象 5 件 / x 2 / z 3"
        assert "y" not in text

    def test_includes_zero_when_omit_false(self) -> None:
        from wiseman_hub.ui.common import StatusCounts

        counts = StatusCounts(total=5, by_status={"x": 2, "y": 0, "z": 3})
        text = counts.to_summary_text(omit_zero=False)
        assert text == "対象 5 件 / x 2 / y 0 / z 3"

    def test_ordered_labels_overrides_dict_order(self) -> None:
        from wiseman_hub.ui.common import StatusCounts

        counts = StatusCounts(total=5, by_status={"a": 1, "b": 2, "c": 2})
        text = counts.to_summary_text(ordered_labels=["b", "c", "a"])
        assert text == "対象 5 件 / b 2 / c 2 / a 1"

    def test_ordered_labels_can_include_unseen_labels(self) -> None:
        """サマリー表示順を固定したい場面で、未出現ラベルは omit_zero で省略される。"""
        from wiseman_hub.ui.common import StatusCounts

        counts = StatusCounts(total=2, by_status={"a": 2})
        text = counts.to_summary_text(ordered_labels=["a", "b", "c"])
        # b, c は未出現 = 0 件 = omit_zero (default True) で省略
        assert text == "対象 2 件 / a 2"

    def test_custom_prefix(self) -> None:
        from wiseman_hub.ui.common import StatusCounts

        counts = StatusCounts(total=3, by_status={"x": 3})
        text = counts.to_summary_text(prefix="合計")
        assert text == "合計 3 件 / x 3"


# ---------------------------------------------------------------------------
# make_treeview_sortable (Tk 必要、`tk_required` mark で skip 可)
# ---------------------------------------------------------------------------


def _invoke_heading_command(tree: Any, column: str) -> None:
    # Mac/Linux Tk は callable な Python 関数を返すが、Windows Tk は Tcl コマンド名
    # (str) を返す。後者は `tree.tk.call(name)` で実行する必要がある。
    cmd = tree.heading(column)["command"]
    if callable(cmd):
        cmd()
    else:
        tree.tk.call(cmd)


@pytest.mark.tk_required
class TestMakeTreeviewSortable:
    def test_clicking_header_sorts_ascending_then_descending(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        from wiseman_hub.ui.common import make_treeview_sortable

        root = tk.Tk()
        try:
            tree = ttk.Treeview(root, columns=("name",), show="headings")
            tree.heading("name", text="氏名")
            tree.insert("", "end", iid="0", values=("c",))
            tree.insert("", "end", iid="1", values=("a",))
            tree.insert("", "end", iid="2", values=("b",))
            make_treeview_sortable(tree, ("name",))

            # 1 回目クリック → 昇順
            _invoke_heading_command(tree, "name")
            assert [tree.set(i, "name") for i in tree.get_children()] == ["a", "b", "c"]
            assert "▲" in str(tree.heading("name", "text"))

            # 2 回目クリック → 降順
            _invoke_heading_command(tree, "name")
            assert [tree.set(i, "name") for i in tree.get_children()] == ["c", "b", "a"]
            assert "▼" in str(tree.heading("name", "text"))
        finally:
            root.destroy()

    def test_status_column_uses_custom_priority_key(self) -> None:
        """業務優先度順 sort key の例 (要対応 → 完了)。"""
        import tkinter as tk
        from tkinter import ttk

        from wiseman_hub.ui.common import make_treeview_sortable

        root = tk.Tk()
        try:
            tree = ttk.Treeview(root, columns=("status",), show="headings")
            tree.heading("status", text="ステータス")
            tree.insert("", "end", iid="0", values=("成功",))
            tree.insert("", "end", iid="1", values=("要レビュー",))
            tree.insert("", "end", iid="2", values=("実行待ち",))

            priority = {"要レビュー": 0, "実行待ち": 30, "成功": 90}

            def status_key(cell: str) -> tuple[int, str]:
                return (priority.get(cell, 99), cell)

            make_treeview_sortable(
                tree, ("status",), key_funcs={"status": status_key}
            )

            # 昇順 = 業務優先度低い順 (要対応 → 完了)
            _invoke_heading_command(tree, "status")
            order = [tree.set(i, "status") for i in tree.get_children()]
            assert order == ["要レビュー", "実行待ち", "成功"]
        finally:
            root.destroy()


# ===========================================================================
# parse_sheet_name / open_folder_in_os (PR sheet-list-binding で追加された
# 共通 helper)。pr-test-analyzer CG-2 対応で直接 unit test を追加。
# ===========================================================================


from unittest.mock import patch  # noqa: E402

from wiseman_hub.ui.common import (  # noqa: E402
    open_folder_in_os,
    parse_sheet_name,
)


class TestParseSheetName:
    """Wiseman シート名 "YY年M月" のパース。"""

    # ---------- happy path ----------

    def test_one_digit_month(self) -> None:
        assert parse_sheet_name("26年4月") == (2026, 4)

    def test_two_digit_month(self) -> None:
        assert parse_sheet_name("25年12月") == (2025, 12)

    def test_year_boundary_00(self) -> None:
        assert parse_sheet_name("00年1月") == (2000, 1)

    def test_year_boundary_99(self) -> None:
        assert parse_sheet_name("99年12月") == (2099, 12)

    def test_month_boundary_1(self) -> None:
        assert parse_sheet_name("26年1月") == (2026, 1)

    def test_month_boundary_12(self) -> None:
        assert parse_sheet_name("26年12月") == (2026, 12)

    # ---------- 月バリデーション (旧 regex は受け入れていた、本 PR で厳格化) ----------

    def test_rejects_month_zero(self) -> None:
        """旧 regex は "26年0月" を (2026, 0) として返していた (downstream で壊れる)。"""
        assert parse_sheet_name("26年0月") is None

    def test_rejects_month_13(self) -> None:
        """旧 regex は "26年13月" を (2026, 13) として返していた。"""
        assert parse_sheet_name("26年13月") is None

    def test_rejects_month_99(self) -> None:
        assert parse_sheet_name("26年99月") is None

    def test_rejects_month_00(self) -> None:
        """月 "00" (2 桁ゼロパディング) も無効。"""
        assert parse_sheet_name("26年00月") is None

    # ---------- フォーマット違反 (旧 regex の動作も保持) ----------

    def test_rejects_empty_string(self) -> None:
        assert parse_sheet_name("") is None

    def test_rejects_missing_month(self) -> None:
        assert parse_sheet_name("26年") is None

    def test_rejects_missing_year(self) -> None:
        assert parse_sheet_name("年4月") is None

    def test_rejects_four_digit_year(self) -> None:
        """4 桁年は明示的に拒否 (旧 regex も同じ動作)。"""
        assert parse_sheet_name("2026年4月") is None

    def test_rejects_three_digit_month(self) -> None:
        assert parse_sheet_name("26年123月") is None

    def test_rejects_extra_whitespace(self) -> None:
        assert parse_sheet_name("26年 4月") is None
        assert parse_sheet_name(" 26年4月") is None
        assert parse_sheet_name("26年4月 ") is None


class TestOpenFolderInOs:
    """OS 別のフォルダ起動 (subprocess.run の引数を検証)。"""

    def test_uses_explorer_on_win32(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        with (
            patch("wiseman_hub.ui.common.sys.platform", "win32"),
            patch("wiseman_hub.ui.common.subprocess.run") as mock_run,
        ):
            open_folder_in_os(tmp_path)
            mock_run.assert_called_once_with(
                ["explorer", str(tmp_path)], check=False
            )

    def test_uses_open_on_darwin(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        with (
            patch("wiseman_hub.ui.common.sys.platform", "darwin"),
            patch("wiseman_hub.ui.common.subprocess.run") as mock_run,
        ):
            open_folder_in_os(tmp_path)
            mock_run.assert_called_once_with(
                ["open", str(tmp_path)], check=False
            )

    def test_uses_xdg_open_on_linux(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        with (
            patch("wiseman_hub.ui.common.sys.platform", "linux"),
            patch("wiseman_hub.ui.common.subprocess.run") as mock_run,
        ):
            open_folder_in_os(tmp_path)
            mock_run.assert_called_once_with(
                ["xdg-open", str(tmp_path)], check=False
            )

    def test_oserror_does_not_propagate(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """subprocess.run が OSError を投げても caller には伝わらない (best-effort 契約)。"""
        with (
            patch("wiseman_hub.ui.common.sys.platform", "darwin"),
            patch(
                "wiseman_hub.ui.common.subprocess.run",
                side_effect=OSError("permission denied"),
            ),
        ):
            # 例外が伝播しないことが契約 (logger.exception でログのみ)
            open_folder_in_os(tmp_path)


class TestParseSheetNameSharedAcrossDialogs:
    """B/C ダイアログが共通の parse_sheet_name を使う identity test (CG-3)。

    将来 B または C が module-local な regex を再導入して divergence する regression
    を防ぐ。
    """

    def test_b_and_c_dialogs_use_common_parse_sheet_name(self) -> None:
        from wiseman_hub.ui import checklist_b_dialog as b_mod
        from wiseman_hub.ui import checklist_c_dialog as c_mod
        from wiseman_hub.ui.common import parse_sheet_name as common_fn

        assert b_mod.parse_sheet_name is common_fn
        assert c_mod.parse_sheet_name is common_fn
