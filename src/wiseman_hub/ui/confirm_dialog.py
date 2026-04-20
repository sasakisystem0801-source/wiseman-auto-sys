"""利用者ペアの人間確認 UI（ADR-009 / ADR-010）。

``needs_confirmation`` / ``no_match`` な候補を Tkinter Treeview に一覧し、
承認・却下・手動選択・スキップの 4 操作で全件解決させる。

- 本モジュールは `candidate.status` と `matched_b/c_path` のみ更新する
- ``session.status`` の ``needs_review`` → ``ready_to_merge`` 遷移は **呼出側の責務**
  （呼出側は ``all_candidates_resolved`` を確認後 ``transition_session`` を使う）
- 各操作後に ``save_session`` を呼び fail-fast で永続化する（PII 孤児化を避ける）
- PII（氏名・ファイルパス）は ``logger`` に出さない

テストは ``tests/unit/ui/test_confirm_dialog.py``（AC-UI-1〜11）。
"""

from __future__ import annotations

import contextlib
import logging
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Protocol

from wiseman_hub.pdf.matcher import SourceKind
from wiseman_hub.pdf.session import (
    OPEN_PAIR_STATUSES,
    CandidateState,
    PairStatus,
    Session,
    SessionStatus,
    UserCandidate,
    save_session,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfirmDialogResult:
    """UI クローズ時の返却値。

    Attributes:
        resolved_all: 全候補が解決状態（呼出側は True のときのみ
            ``transition_session(READY_TO_MERGE)`` を実行する）。
        session: UI 操作後の最新 session。
    """

    resolved_all: bool
    session: Session


class MessageBoxLike(Protocol):
    """`tkinter.messagebox` の最小インターフェース（DI 用）。"""

    def askyesno(self, title: str, message: str) -> bool: ...

    def showinfo(self, title: str, message: str) -> None: ...


class _DefaultMessageBox:
    """`tkinter.messagebox` をそのまま使う実装。"""

    def askyesno(self, title: str, message: str) -> bool:
        return bool(messagebox.askyesno(title, message))

    def showinfo(self, title: str, message: str) -> None:
        messagebox.showinfo(title, message)


# ---------------------------------------------------------------------------
# UI text（ロケール分離を意識して module 定数に集約、翻訳時の単一変更点）
# ---------------------------------------------------------------------------


_COLUMNS: tuple[tuple[str, str, int], ...] = (
    ("page", "ページ", 60),
    ("ocr_name", "抽出氏名", 180),
    ("confidence", "信頼度", 80),
    ("pair_status", "状態", 130),
    ("b_path", "候補 B", 160),
    ("c_path", "候補 C", 160),
)

_BTN_APPROVE = "承認"
_BTN_REJECT = "却下"
_BTN_MANUAL = "手動選択..."
_BTN_SKIP = "スキップ"

_TITLE_ALL_RESOLVED = "全件解決"
_MSG_ALL_RESOLVED = "すべて解決しました。閉じて結合へ進みます。"
_TITLE_CLOSE_UNRESOLVED = "未解決のまま閉じる"
_MSG_CLOSE_UNRESOLVED = "未解決の候補が残っています。後で再開できます。\n本当に閉じますか？"

_SOURCE_KIND_B: SourceKind = "B"
_SOURCE_KIND_C: SourceKind = "C"


# ---------------------------------------------------------------------------
# ConfirmDialog 本体
# ---------------------------------------------------------------------------


class ConfirmDialog:
    """`needs_review` セッションの候補を人間が解決する Tkinter ダイアログ。

    呼出側は事前に ``with_session_lock`` を取得し、``session.status == NEEDS_REVIEW``
    を保証すること。

    依存性注入:
        - ``root``: テスト時に ``tk.Tk()`` を外から渡す（通常は ``None`` で内部生成）
        - ``save_session_fn``: 永続化関数（テストでスタブ差替え可能）
        - ``askopenfilename_fn``: 手動選択ダイアログ（テストでスタブ差替え可能）
        - ``messagebox_fn``: 確認ダイアログ（テストでスタブ差替え可能）
    """

    def __init__(
        self,
        session: Session,
        sessions_dir: Path,
        *,
        root: tk.Tk | None = None,
        save_session_fn: Callable[..., Path] = save_session,
        askopenfilename_fn: Callable[..., str] = filedialog.askopenfilename,
        messagebox_fn: MessageBoxLike | None = None,
    ) -> None:
        if session.status != SessionStatus.NEEDS_REVIEW:
            raise ValueError(
                f"ConfirmDialog requires session.status == NEEDS_REVIEW "
                f"(got {session.status.value})"
            )
        if not any(c.status in OPEN_PAIR_STATUSES for c in session.candidates):
            raise ValueError(
                "ConfirmDialog requires at least one unresolved candidate"
            )

        self._session = session
        self._sessions_dir = sessions_dir
        self._save_session_fn = save_session_fn
        self._askopenfilename_fn = askopenfilename_fn
        self._messagebox = messagebox_fn or _DefaultMessageBox()

        self._owns_root = root is None
        self._root = root if root is not None else tk.Tk()

        self._build_ui()

    # -- UI construction ----------------------------------------------------

    def _build_ui(self) -> None:
        root = self._root
        root.title(f"利用者ペア確認 - Session {self._session.session_id}")
        root.geometry("900x520")
        root.protocol("WM_DELETE_WINDOW", self._on_close_button)

        self._progress_var = tk.StringVar(value=self._progress_text())
        ttk.Label(root, textvariable=self._progress_var, anchor="w", padding=8).pack(
            fill="x"
        )

        tree_frame = ttk.Frame(root, padding=(8, 0))
        tree_frame.pack(fill="both", expand=True)

        columns = tuple(col[0] for col in _COLUMNS)
        self._tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", selectmode="browse"
        )
        for key, heading, width in _COLUMNS:
            self._tree.heading(key, text=heading)
            self._tree.column(key, width=width, anchor="w")
        self._tree.pack(side="left", fill="both", expand=True)

        scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        scroll.pack(side="right", fill="y")
        self._tree.configure(yscrollcommand=scroll.set)
        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        # 詳細表示（選択中）
        self._detail_var = tk.StringVar(value="候補を選択してください。")
        ttk.Label(
            root,
            textvariable=self._detail_var,
            padding=8,
            anchor="w",
            justify="left",
        ).pack(fill="x")

        # 操作ボタン群
        btn_frame = ttk.Frame(root, padding=8)
        btn_frame.pack(fill="x")
        self._btn_approve = ttk.Button(
            btn_frame, text=_BTN_APPROVE, command=self._on_approve
        )
        self._btn_reject = ttk.Button(
            btn_frame, text=_BTN_REJECT, command=self._on_reject
        )
        self._btn_manual = ttk.Button(
            btn_frame, text=_BTN_MANUAL, command=self._on_manual_select
        )
        self._btn_skip = ttk.Button(btn_frame, text=_BTN_SKIP, command=self._on_skip)
        for btn in (self._btn_approve, self._btn_reject, self._btn_manual, self._btn_skip):
            btn.pack(side="left", padx=4)
            btn.state(["disabled"])  # type: ignore[no-untyped-call]

        self._refresh_tree()

    # -- Public entry -------------------------------------------------------

    def run(self) -> ConfirmDialogResult:
        """mainloop を起動し、UI 終了後に結果を返す。"""
        try:
            self._root.mainloop()
        finally:
            if self._owns_root:
                with contextlib.suppress(tk.TclError):
                    self._root.destroy()
        return ConfirmDialogResult(
            resolved_all=self._session.all_candidates_resolved,
            session=self._session,
        )

    # -- Treeview management ------------------------------------------------

    def _refresh_tree(self) -> None:
        """Treeview を未解決候補だけで再構築し、ボタン状態を更新する。"""
        selected_idx = self._selected_page_index()
        for item_id in self._tree.get_children():
            self._tree.delete(item_id)

        for cand in self._session.candidates:
            if cand.status not in OPEN_PAIR_STATUSES:
                continue
            self._tree.insert(
                "",
                "end",
                iid=str(cand.page_index),
                values=(
                    cand.page_index,
                    cand.user_name_ocr,
                    cand.confidence,
                    cand.status.value,
                    _short_path(cand.matched_b_path),
                    _short_path(cand.matched_c_path),
                ),
            )

        self._progress_var.set(self._progress_text())

        # 選択中の行が resolved で消えた場合はクリア
        if selected_idx is not None and str(selected_idx) not in self._tree.get_children():
            self._detail_var.set("候補を選択してください。")
            self._set_buttons_for(None)

    def _selected_page_index(self) -> int | None:
        sel = self._tree.selection()
        if not sel:
            return None
        return int(sel[0])

    def _selected_candidate(self) -> UserCandidate | None:
        idx = self._selected_page_index()
        if idx is None:
            return None
        for c in self._session.candidates:
            if c.page_index == idx:
                return c
        return None

    def _on_select(self, _event: object) -> None:
        cand = self._selected_candidate()
        if cand is None:
            self._detail_var.set("候補を選択してください。")
            self._set_buttons_for(None)
            return
        self._detail_var.set(_format_detail(cand))
        self._set_buttons_for(cand)

    def _set_buttons_for(self, cand: UserCandidate | None) -> None:
        if cand is None:
            for btn in (
                self._btn_approve,
                self._btn_reject,
                self._btn_manual,
                self._btn_skip,
            ):
                btn.state(["disabled"])  # type: ignore[no-untyped-call]  # noqa: E501
            return

        # 承認は NEEDS_CONFIRMATION かつ similar_candidates に B or C があるときのみ
        has_similar_bc = (
            _pick_first_by_kind(cand.similar_candidates, _SOURCE_KIND_B) is not None
            or _pick_first_by_kind(cand.similar_candidates, _SOURCE_KIND_C) is not None
        )
        can_approve = cand.status == PairStatus.NEEDS_CONFIRMATION and has_similar_bc
        self._btn_approve.state(  # type: ignore[no-untyped-call]
            ["!disabled"] if can_approve else ["disabled"]
        )

        # 却下 / 手動 / スキップは NEEDS_CONFIRMATION / NO_MATCH 両方で有効
        for btn in (self._btn_reject, self._btn_manual, self._btn_skip):
            btn.state(["!disabled"])  # type: ignore[no-untyped-call]

    # -- Operations ---------------------------------------------------------

    def _on_approve(self) -> None:
        cand = self._selected_candidate()
        if cand is None:
            return
        decision = compute_approve_decision(cand)
        if decision is None:
            return
        first_b, first_c = decision
        self._apply_update(
            cand.page_index,
            status=PairStatus.CONFIRMED,
            matched_b=first_b,
            matched_c=first_c,
        )
        self._log_operation("approved", cand)

    def _on_reject(self) -> None:
        cand = self._selected_candidate()
        if cand is None or cand.status not in OPEN_PAIR_STATUSES:
            return
        self._apply_update(
            cand.page_index,
            status=PairStatus.REJECTED,
            matched_b=None,
            matched_c=None,
            clear_similar=True,
        )
        self._log_operation("rejected", cand)

    def _on_manual_select(self) -> None:
        cand = self._selected_candidate()
        if cand is None or cand.status not in OPEN_PAIR_STATUSES:
            return

        b_path = self._askopenfilename_fn(
            title="B 側 PDF を選択（キャンセル可）",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        c_path = self._askopenfilename_fn(
            title="C 側 PDF を選択（キャンセル可）",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )

        chosen_b = b_path if b_path else None
        chosen_c = c_path if c_path else None
        if chosen_b is None and chosen_c is None:
            # どちらも選ばれなかった場合は何もしない
            return

        self._apply_update(
            cand.page_index,
            status=PairStatus.MANUALLY_SELECTED,
            matched_b=chosen_b,
            matched_c=chosen_c,
        )
        self._log_operation("manually_selected", cand)

    def _on_skip(self) -> None:
        cand = self._selected_candidate()
        if cand is None or cand.status not in OPEN_PAIR_STATUSES:
            return
        self._apply_update(
            cand.page_index,
            status=PairStatus.SKIPPED,
            matched_b=None,
            matched_c=None,
        )
        self._log_operation("skipped", cand)

    # -- Core update --------------------------------------------------------

    def _apply_update(
        self,
        page_index: int,
        *,
        status: PairStatus,
        matched_b: str | None,
        matched_c: str | None,
        clear_similar: bool = False,
    ) -> None:
        """candidate 更新 → fail-fast 永続化 → Tree リフレッシュ → 全件解決検知。

        純粋なロジック部分は :func:`resolve_candidate` に切り出してあるため
        Tk ランタイム非依存でユニットテスト可能。本メソッドは UI wiring のみ。

        save_session 失敗時は例外を伝播（UI 握り潰し禁止、PII 孤児化回避）。
        """
        resolve_candidate(
            self._session,
            page_index,
            status=status,
            matched_b=matched_b,
            matched_c=matched_c,
            clear_similar=clear_similar,
        )
        # fail-fast: 例外は呼出元に伝播させる（捕捉しない）
        self._save_session_fn(self._session, sessions_dir=self._sessions_dir)

        self._refresh_tree()
        self._check_all_resolved()

    def _check_all_resolved(self) -> None:
        """全件解決を検知したら確認ダイアログを出してクローズする。"""
        if not self._session.all_candidates_resolved:
            return
        self._messagebox.showinfo(_TITLE_ALL_RESOLVED, _MSG_ALL_RESOLVED)
        self._root.quit()

    # -- Close handling -----------------------------------------------------

    def _on_close_button(self) -> None:
        # resolved_all の判定は run() 内で session.all_candidates_resolved から
        # 都度計算するため、ここでは quit() のみ（フラグ保持不要）。
        if self._session.all_candidates_resolved:
            self._root.quit()
            return

        if self._messagebox.askyesno(_TITLE_CLOSE_UNRESOLVED, _MSG_CLOSE_UNRESOLVED):
            self._root.quit()
        # いいえ → dialog 継続

    # -- Helpers ------------------------------------------------------------

    def _progress_text(self) -> str:
        resolved = needs_conf = no_match = 0
        for c in self._session.candidates:
            if c.is_resolved:
                resolved += 1
            elif c.status == PairStatus.NEEDS_CONFIRMATION:
                needs_conf += 1
            elif c.status == PairStatus.NO_MATCH:
                no_match += 1
        total = len(self._session.candidates)
        open_count = total - resolved
        return (
            f"進捗: {resolved}/{total} 解決済  |  "
            f"未解決 {open_count} 件（確認 {needs_conf} / 不一致 {no_match}）"
        )

    def _log_operation(self, op: str, cand: UserCandidate) -> None:
        log_operation(self._session.session_id, cand, op)


# ---------------------------------------------------------------------------
# Pure logic（Tk ランタイム非依存、ユニットテスト完全カバレッジ対象）
# ---------------------------------------------------------------------------


def resolve_candidate(
    session: Session,
    page_index: int,
    *,
    status: PairStatus,
    matched_b: str | None,
    matched_c: str | None,
    clear_similar: bool = False,
) -> Session:
    """指定 page_index の candidate を新 status と matched パスで更新する。

    副作用: ``session.candidates`` list を差し替える（in-place）。戻り値は同じ
    ``session`` 参照（chain 用）。該当 page_index が存在しない場合は何もしない。
    ``similar_candidates`` は ``clear_similar=True`` で空にする（却下時に使用）。
    """
    new_candidates: list[UserCandidate] = []
    for c in session.candidates:
        if c.page_index != page_index:
            new_candidates.append(c)
            continue
        similar = [] if clear_similar else c.similar_candidates
        new_candidates.append(
            UserCandidate(
                page_index=c.page_index,
                user_name_ocr=c.user_name_ocr,
                confidence=c.confidence,
                status=status,
                matched_b_path=matched_b,
                matched_c_path=matched_c,
                similar_candidates=list(similar),
            )
        )
    session.candidates = new_candidates
    return session


def log_operation(session_id: str, cand: UserCandidate, op: str) -> None:
    """PII を出さずに候補操作をログ出力する。

    許可: session_id / page_index / confidence / op（操作名）。
    禁止: user_name_ocr / matched_*_path（氏名・ファイルパス）。
    """
    logger.info(
        "session %s page_index=%d confidence=%s op=%s",
        session_id,
        cand.page_index,
        cand.confidence,
        op,
    )


def compute_approve_decision(
    cand: UserCandidate,
) -> tuple[str | None, str | None] | None:
    """「承認」操作で採用すべき matched_b / matched_c を計算する。

    - cand.status が NEEDS_CONFIRMATION でない場合は None（操作不可）
    - similar_candidates に B / C がどちらも無い場合も None
    - それ以外は (first_b, first_c) のタプル（片方 None 可）
    """
    if cand.status != PairStatus.NEEDS_CONFIRMATION:
        return None
    first_b = _pick_first_by_kind(cand.similar_candidates, _SOURCE_KIND_B)
    first_c = _pick_first_by_kind(cand.similar_candidates, _SOURCE_KIND_C)
    if first_b is None and first_c is None:
        return None
    return (first_b, first_c)


def _pick_first_by_kind(
    similar: list[CandidateState], kind: SourceKind
) -> str | None:
    """similar_candidates の先頭から、指定 kind (B/C) の path を返す（無ければ None）。"""
    return next((c.path for c in similar if c.kind == kind), None)


def _short_path(path: str | None, max_len: int = 30) -> str:
    if not path:
        return ""
    name = Path(path).name
    if len(name) <= max_len:
        return name
    return "..." + name[-(max_len - 3) :]


def _format_detail(cand: UserCandidate) -> str:
    head = (
        f"選択中: page_index={cand.page_index}, "
        f"ocr=\"{cand.user_name_ocr}\", confidence={cand.confidence}"
    )
    if not cand.similar_candidates:
        return head + "\nsimilar: (なし)"
    parts = [
        f"[{c.kind}:{Path(c.path).name} d={c.distance}]" for c in cand.similar_candidates
    ]
    return head + "\nsimilar: " + " ".join(parts)
