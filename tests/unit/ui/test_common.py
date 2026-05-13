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


@pytest.mark.tk_required
class TestMakeTreeviewSortable:
    # Issue #276 follow-up: `tree.heading("name")["command"]` は Mac/Linux Tk では
    # 直接 callable な Python 関数を返すが、Windows Tk では Tcl コマンド名 (str) を
    # 返すため `()` 呼出で TypeError。test 書き換え (root.tk.call で Tcl 名解決 or
    # event_generate でクリック発火) は別 PR で対応。
    @pytest.mark.xfail(
        reason="Windows Tk: heading()[command] が Tcl コマンド名 str を返す (Issue #276 follow-up)",
        strict=False,
    )
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
            tree.heading("name")["command"]()
            assert [tree.set(i, "name") for i in tree.get_children()] == ["a", "b", "c"]
            assert "▲" in str(tree.heading("name", "text"))

            # 2 回目クリック → 降順
            tree.heading("name")["command"]()
            assert [tree.set(i, "name") for i in tree.get_children()] == ["c", "b", "a"]
            assert "▼" in str(tree.heading("name", "text"))
        finally:
            root.destroy()

    @pytest.mark.xfail(
        reason="Windows Tk: heading()[command] が Tcl コマンド名 str を返す (Issue #276 follow-up)",
        strict=False,
    )
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

            tree.heading("status")["command"]()  # 昇順 = 業務優先度低い順 (要対応 → 完了)
            order = [tree.set(i, "status") for i in tree.get_children()]
            assert order == ["要レビュー", "実行待ち", "成功"]
        finally:
            root.destroy()
