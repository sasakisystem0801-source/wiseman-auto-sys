"""UI モジュール共通ヘルパ（最下層、他の ui モジュールから参照される土台）。"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox as _tk_messagebox
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

if TYPE_CHECKING:
    import tkinter as tk
    from tkinter import ttk

logger = logging.getLogger(__name__)

T = TypeVar("T")


_TITLE_INTERNAL_ERROR = "内部エラー"
_MSG_INTERNAL_ERROR_FMT = (
    "処理中にエラーが発生しました。詳細はログを確認してください。\n\n{type}"
)

# ログ grep 可読性維持のため component ラベルは空白・制御文字・空文字を禁止。
# snake_case / session_<id> 等を想定。
_COMPONENT_INVALID = re.compile(r"\s")


def assert_main_thread(component_name: str) -> None:
    """Tk は main thread でしか安全に使えないため、worker thread からの生成を fail-fast で拒否する。

    Tkinter（filedialog / messagebox / mainloop）は非 main thread から呼び出すと
    Windows 本番でハング / TclError を起こしうる。
    """
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError(
            f"{component_name} must be instantiated on the main thread "
            "(tkinter is not thread-safe)"
        )


class MessageBoxLike(Protocol):
    """``tkinter.messagebox`` の最小インターフェース（DI 用）。

    ui 配下の Launcher / ConfirmDialog / SettingsDialog / SessionPicker (13C) が共通で依存する
    Protocol。structural subtyping により任意の fake / mock を注入可能。
    """

    def askyesno(self, title: str, message: str) -> bool: ...

    def showinfo(self, title: str, message: str) -> None: ...

    def showerror(self, title: str, message: str) -> None: ...


class _DefaultMessageBox:
    """``tkinter.messagebox`` をそのまま使う実装。"""

    def askyesno(self, title: str, message: str) -> bool:
        return bool(_tk_messagebox.askyesno(title, message))

    def showinfo(self, title: str, message: str) -> None:
        _tk_messagebox.showinfo(title, message)

    def showerror(self, title: str, message: str) -> None:
        _tk_messagebox.showerror(title, message)


def default_messagebox() -> MessageBoxLike:
    """``tkinter.messagebox`` を使う既定実装を返す（ui モジュール共通）。"""
    return _DefaultMessageBox()


def install_tk_exception_guard(
    root: tk.Misc,
    *,
    component: str,
    messagebox: MessageBoxLike,
) -> None:
    """Tk callback 内の未捕捉例外を PII 防御付きで捕捉する guard を ``root`` にインストールする。

    Tk は `command=` や `bind` で登録した callback 内で raise された例外を握り潰さず
    stderr にダンプするが、例外文字列には PDF パス・利用者氏名などの PII が混入しうる。
    本 guard は ``report_callback_exception`` に差し替え、以下を保証する:

    - ログ: ``exc_type.__name__`` のみ（``exc_value`` の str は出さない）
    - 画面: ``messagebox.showerror`` で sanitized メッセージ（型名のみ）
    - 二次失敗: ``showerror`` 自体が失敗（root destroy 後等）しても warning で握り潰し

    :param component: ログ集計用のラベル。snake_case、空白・空文字禁止
        （grep 可読性維持のため実行時 validation あり）。例: ``"launcher"``,
        ``"settings"``, ``"session_picker"``, ``"session_<id>"``。
    :param messagebox: ``showerror`` のみが呼ばれる。DI により
        ``tkinter.messagebox`` を差替え可能（テスト容易性）。

    launcher / settings / SessionPicker (13C) で共通利用する。confirm_dialog は
    session_id 付加・aborted フラグ・quit 副作用があるため本 guard の対象外。
    """
    if not component or _COMPONENT_INVALID.search(component):
        raise ValueError(
            f"component must be non-empty and contain no whitespace "
            f"(got {component!r})"
        )

    def _handler(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_tb: object,
    ) -> None:
        logger.error("%s callback exception: %s", component, exc_type.__name__)
        try:
            messagebox.showerror(
                _TITLE_INTERNAL_ERROR,
                _MSG_INTERNAL_ERROR_FMT.format(type=exc_type.__name__),
            )
        except Exception as e:  # noqa: BLE001 — 二次 showerror 失敗は握り潰し可
            logger.warning(
                "%s showerror failed during callback exception: %s",
                component,
                type(e).__name__,
            )

    # tkinter の stub は report_callback_exception を公開していないが、
    # 実体は Tk / Toplevel で動的に読まれる公式 API（Python docs: Tk.report_callback_exception）。
    root.report_callback_exception = _handler  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Treeview sort + ステータス集計 共通ヘルパ
# ---------------------------------------------------------------------------
# 業務責任者が毎月 80 件超を扱う C / B ダイアログ等で、ステータス別集約・並び替え
# が UX 必須。複数 Treeview ダイアログ間で DRY 共通化する（C, B, ex_extractor 等）。


def make_treeview_sortable(
    tree: ttk.Treeview,
    columns: Sequence[str],
    *,
    key_funcs: Mapping[str, Callable[[str], object]] | None = None,
) -> None:
    """``ttk.Treeview`` のヘッダークリックで sort できるようにする。

    各カラムについて 1 回目クリックで昇順、2 回目で降順の toggle。
    ヘッダーのテキスト末尾に ``▲`` (asc) / ``▼`` (desc) を付加して状態可視化する。

    :param tree: 対象 Treeview。
    :param columns: ``tree.heading(col, ...)`` の col 識別子リスト。
    :param key_funcs: 特定カラムのカスタム sort key 関数。例えばステータス列を
        業務優先度順に並べたい場合に使用。``key_funcs[col](cell_value: str) -> sortable``。
        指定がないカラムは文字列辞書順 sort。

    使用例::

        tree = ttk.Treeview(parent, columns=cols, show="headings")
        for c in cols:
            tree.heading(c, text=...)  # heading text 設定は呼出側
        make_treeview_sortable(
            tree, cols, key_funcs={"status": status_sort_key_fn}
        )
    """
    state: dict[str, str] = {}  # col -> "asc" / "desc"
    base_text: dict[str, str] = {}

    def _identity(v: str) -> Any:
        # Any で受けることで sort key として比較可能（key_funcs 側も
        # tuple/int 等の sortable を返す前提、互換性は呼出側責務）
        return v

    def _sort_by(col: str) -> None:
        # 現状の Treeview の項目を (sort_key, iid) のリストにして sort
        items = list(tree.get_children(""))
        key_fn: Callable[[str], Any] = (key_funcs or {}).get(col, _identity)
        rows = [(key_fn(tree.set(iid, col)), iid) for iid in items]
        new_order = state.get(col) != "asc"  # toggle
        rows.sort(key=lambda r: r[0], reverse=not new_order)
        for index, (_key, iid) in enumerate(rows):
            tree.move(iid, "", index)
        state[col] = "asc" if new_order else "desc"
        # 全カラムの heading から ▲▼ を一旦消し、本カラムだけ更新
        for c in columns:
            tree.heading(c, text=base_text.get(c, ""))
        marker = " ▲" if new_order else " ▼"
        tree.heading(col, text=base_text.get(col, "") + marker)

    def _make_handler(c: str) -> Callable[[], None]:
        # closure で col を bind（lambda c=col: の default-arg トリック回避、mypy 友好的）
        return lambda: _sort_by(c)

    for col in columns:
        # 既存 heading text を保存（後で sort 矢印付加時に基底として使う）
        base_text[col] = str(tree.heading(col, "text"))
        tree.heading(col, command=_make_handler(col))


@dataclass(frozen=True)
class StatusCounts:
    """ステータス別件数集計（``count_by_status`` の戻り値）。"""

    total: int
    by_status: Mapping[str, int]

    def to_summary_text(
        self,
        *,
        prefix: str = "対象",
        ordered_labels: Sequence[str] | None = None,
        omit_zero: bool = True,
    ) -> str:
        """``対象 N 件 / ラベル1 X / ラベル2 Y`` 形式の集計テキストを返す。

        :param ordered_labels: 表示順を固定したい場合のラベル順序。
            ``None`` の場合は ``by_status`` の元順序（dict 挿入順）。
        :param omit_zero: 0 件のラベルは表示から省く（既定 True、視認性優先）。
        """
        labels = ordered_labels if ordered_labels is not None else list(self.by_status)
        parts = [f"{prefix} {self.total} 件"]
        for label in labels:
            count = self.by_status.get(label, 0)
            if omit_zero and count == 0:
                continue
            parts.append(f"{label} {count}")
        return " / ".join(parts)


def count_by_status(
    items: Iterable[T],
    status_label_fn: Callable[[T], str],
) -> StatusCounts:
    """``items`` を ``status_label_fn`` で分類して件数集計する純粋関数。

    Tk 不要。テスト容易性のため UI から分離した汎用集計。
    集計順序は最初に出現したラベル順（dict 挿入順）。
    """
    counts: dict[str, int] = {}
    total = 0
    for item in items:
        label = status_label_fn(item)
        counts[label] = counts.get(label, 0) + 1
        total += 1
    return StatusCounts(total=total, by_status=counts)


# ---------------------------------------------------------------------------
# シート名 (タブ名) パース + OS ファイルマネージャ起動
#   PR (xlsx-visibility): B/C ダイアログで完全重複していた `_SHEET_NAME_RE` /
#   `_sheet_name_to_year_month` / `_open_folder` を共通化 (code-reviewer
#   MEDIUM #1 対応)。
# ---------------------------------------------------------------------------

_SHEET_NAME_RE = re.compile(r"^(\d{2})年(\d{1,2})月$")


def parse_sheet_name(name: str) -> tuple[int, int] | None:
    """Wiseman シート名 ``"YY年M月"`` を ``(year, month)`` にパースする。

    例: ``"26年4月"`` → ``(2026, 4)``。``"25年12月"`` → ``(2025, 12)``。
    マッチしなければ ``None``。

    Wiseman スプレッドシートでは月別シートが「YY年M月」表記で命名される (年は
    2 桁西暦、月は 1〜2 桁)。本関数は B/C/将来の dialog で共通利用される (旧版は
    各 dialog 内に同一実装が並んでいた)。
    """
    m = _SHEET_NAME_RE.match(name)
    if not m:
        return None
    yy = int(m.group(1))
    month = int(m.group(2))
    return (2000 + yy, month)


def open_folder_in_os(folder: Path) -> None:
    """OS のファイルマネージャでフォルダを開く (best-effort、失敗時はログ警告のみ)。

    Windows: ``explorer`` / macOS: ``open`` / Linux: ``xdg-open``。
    B/C ダイアログの「行ダブルクリックで親フォルダを開く」共通処理。
    """
    try:
        if sys.platform == "win32":
            subprocess.run(["explorer", str(folder)], check=False)
        elif sys.platform == "darwin":
            subprocess.run(["open", str(folder)], check=False)
        else:
            subprocess.run(["xdg-open", str(folder)], check=False)
    except OSError:
        logger.exception("Failed to open folder")
