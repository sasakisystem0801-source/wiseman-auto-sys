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
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from tkinter import filedialog, ttk

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
from wiseman_hub.ui.common import MessageBoxLike, assert_main_thread, default_messagebox

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfirmDialogResult:
    """UI クローズ時の返却値。

    ``resolved_all`` は ``session.all_candidates_resolved`` の派生値で二重真実を避けるため
    property 化している。呼出側が UI 終了後に session を変更しても一貫性が保たれる。

    ``aborted`` が True の場合 ``resolved_all`` は常に False を返す（`_on_callback_exception`
    経由で mainloop が異常終了した場合、メモリ上は全件解決済みでも save に失敗しており
    ディスクは旧状態。呼出側が READY_TO_MERGE に進むのを防ぐ安全網）。

    Attributes:
        session: UI 操作後の最新 session。
        aborted: Tk callback 例外で mainloop が異常終了した場合 True。
            呼出側は `aborted=True` 時はメモリ上の session を破棄し on-disk から再ロードする。
    """

    session: Session
    aborted: bool = False

    @property
    def resolved_all(self) -> bool:
        if self.aborted:
            return False
        return self.session.all_candidates_resolved


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
_TITLE_INTERNAL_ERROR = "内部エラー"
_MSG_INTERNAL_ERROR_FMT = (
    "処理中に回復不能なエラーが発生しました。\n"
    "セッションは保存前の状態で保持されています。再開してやり直してください。\n"
    "詳細はログを確認してください。\n\n{type}"
)
_TITLE_PARTIAL_MANUAL = "手動選択"
_MSG_PARTIAL_MANUAL = (
    "B 側と C 側のいずれか片方のみが選択されました。\n"
    "このまま確定しますか？（キャンセルすると両方未選択に戻ります）"
)
_TITLE_FILEDIALOG_ERROR = "ファイル選択エラー"
_MSG_FILEDIALOG_ERROR_FMT = (
    "ファイル選択ダイアログが失敗しました。\n"
    "手動選択をキャンセル扱いとします。\n\n{type}"
)

_SOURCE_KIND_B = SourceKind.B
_SOURCE_KIND_C = SourceKind.C


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
        parent: tk.Misc | None = None,
        save_session_fn: Callable[..., Session] = save_session,
        askopenfilename_fn: Callable[..., str] = filedialog.askopenfilename,
        messagebox_fn: MessageBoxLike | None = None,
    ) -> None:
        """Args:
            root: 既存 Tk root をテストから渡すとき（parent 排他）。
            parent: Launcher など親ウィンドウが既にある場合に渡す。指定時は
                ``Toplevel`` + ``grab_set`` + ``wait_window`` で **モーダル** 化し、
                確認 UI 操作中に Launcher の他ボタンが押されて Phase A/B が並行実行
                される race を構造的に防ぐ（医療 PII の誤配置対策、12B と同パターン）。
        """
        assert_main_thread("ConfirmDialog")
        if session.status != SessionStatus.NEEDS_REVIEW:
            raise ValueError(
                f"ConfirmDialog requires session.status == NEEDS_REVIEW "
                f"(got {session.status.value}, session_id={session.session_id})"
            )
        if not any(c.status in OPEN_PAIR_STATUSES for c in session.candidates):
            raise ValueError(
                "ConfirmDialog requires at least one unresolved candidate "
                f"(session_id={session.session_id})"
            )

        self._session = session
        self._sessions_dir = sessions_dir
        self._save_session_fn = save_session_fn
        self._askopenfilename_fn = askopenfilename_fn
        self._messagebox = messagebox_fn or default_messagebox()
        # Tk callback 例外で mainloop が異常終了したかを追跡。ConfirmDialogResult に伝搬する
        # ことで、save 失敗後のメモリ全解決状態でも呼出側が READY_TO_MERGE に進むのを防ぐ。
        self._aborted = False

        if root is not None and parent is not None:
            raise ValueError("pass either root or parent, not both")
        if parent is not None:
            self._owns_root = True
            self._is_toplevel = True
            toplevel = tk.Toplevel(parent)
            toplevel.transient(parent)  # type: ignore[call-overload]
            toplevel.grab_set()
            self._root: tk.Tk | tk.Toplevel = toplevel
        elif root is not None:
            self._owns_root = False
            self._is_toplevel = False
            self._root = root
        else:
            self._owns_root = True
            self._is_toplevel = False
            self._root = tk.Tk()

        self._build_ui()

    # -- UI construction ----------------------------------------------------

    def _build_ui(self) -> None:
        root = self._root
        root.title(f"利用者ペア確認 - Session {self._session.session_id}")
        root.geometry("900x520")
        root.protocol("WM_DELETE_WINDOW", self._on_close_button)
        # Tkinter 既定は callback 例外を stderr 出力 + mainloop 継続 → fail-fast の骨抜き。
        # save_session 失敗等を「成功したように見せかけない」ため全 callback 例外をここで
        # 捕捉し、ユーザーに明示通知 + close する（医療介護事故防止）。
        # common.install_tk_exception_guard は aborted/session_id 副作用を持たないため、
        # ConfirmDialog 固有の handler を直接登録する（Protocol に副作用フックを追加するのは過剰）。
        root.report_callback_exception = self._on_callback_exception  # type: ignore[union-attr]

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

        self._detail_var = tk.StringVar(value="候補を選択してください。")
        ttk.Label(
            root,
            textvariable=self._detail_var,
            padding=8,
            anchor="w",
            justify="left",
        ).pack(fill="x")

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
        """mainloop / wait_window を起動し、UI 終了後に結果を返す。"""
        try:
            if self._is_toplevel:
                # Toplevel モードは親 mainloop が既に走っているので wait_window で
                # このダイアログが閉じるまで block（grab_set で他操作抑止済み）。
                self._root.wait_window()
            else:
                self._root.mainloop()
        finally:
            if self._owns_root:
                try:
                    self._root.destroy()
                except tk.TclError as e:
                    # destroy 失敗は benign（二重 destroy、子ウィジェット破棄順序等）。
                    # 業務データには影響しないため debug ログに留める（PII 防御で型名のみ）。
                    logger.debug("session %s destroy failed (benign): %s",
                                 self._session.session_id, type(e).__name__)
        return ConfirmDialogResult(session=self._session, aborted=self._aborted)

    def _close_dialog(self) -> None:
        """モードに応じて dialog を閉じる。

        - Toplevel モード: grab_release → ``destroy()`` で window を閉じる（親 mainloop は継続）
        - Standalone モード: ``quit()`` で mainloop を止める（``run()`` の finally で destroy）

        Windows では destroy 単独だと grab が残留するパスが観測されており、明示的に
        grab_release を呼んでから destroy する（Codex MEDIUM 指摘）。
        """
        if self._is_toplevel:
            with contextlib.suppress(tk.TclError):
                if self._root.grab_current() is self._root:  # type: ignore[no-untyped-call]
                    self._root.grab_release()
            with contextlib.suppress(tk.TclError):
                self._root.destroy()
        else:
            with contextlib.suppress(tk.TclError):
                self._root.quit()

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
        can_others = cand is not None
        # 承認は NEEDS_CONFIRMATION かつ similar に B or C がある場合のみ可能
        # （compute_approve_decision と同一ルールで真の単一情報源）
        can_approve = cand is not None and compute_approve_decision(cand) is not None
        states = (
            (self._btn_approve, can_approve),
            (self._btn_reject, can_others),
            (self._btn_manual, can_others),
            (self._btn_skip, can_others),
        )
        for btn, ok in states:
            btn.state(["!disabled"] if ok else ["disabled"])  # type: ignore[no-untyped-call]

    # -- Operations ---------------------------------------------------------

    def _on_approve(self) -> None:
        cand = self._selected_candidate()
        if cand is None:
            return
        decision = compute_approve_decision(cand)
        if decision is None:
            return
        first_b, first_c = decision
        self._log_operation("approved_attempt", cand)
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
        self._log_operation("rejected_attempt", cand)
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

        chosen_b = self._ask_manual_path("B 側 PDF を選択（キャンセル可）")
        chosen_c = self._ask_manual_path("C 側 PDF を選択（キャンセル可）")

        if chosen_b is None and chosen_c is None:
            return

        # 片側のみ選択は「片肺状態の無言確定」を避けるため明示確認を挟む。
        partial = (chosen_b is None) ^ (chosen_c is None)
        if partial and not self._messagebox.askyesno(
            _TITLE_PARTIAL_MANUAL, _MSG_PARTIAL_MANUAL
        ):
            return

        self._log_operation("manually_selected_attempt", cand)
        self._apply_update(
            cand.page_index,
            status=PairStatus.MANUALLY_SELECTED,
            matched_b=chosen_b,
            matched_c=chosen_c,
        )
        self._log_operation("manually_selected", cand)

    def _ask_manual_path(self, title: str) -> str | None:
        """filedialog を呼び、キャンセル時は ``None``、失敗時は警告表示して ``None`` を返す。

        Tk 環境障害（DISPLAY 切断・TclError 等）で askopenfilename 自体が失敗する
        可能性があるため、fail-fast ではなく「キャンセル相当扱い」にする。
        この失敗で業務データは破損しない（未選択のまま操作を継続できる）。
        """
        try:
            path = self._askopenfilename_fn(
                title=title,
                filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
            )
        except (tk.TclError, OSError) as e:
            # PII 防御: ログには型名のみ（例外 message はファイルパスを含む可能性）。
            logger.warning(
                "session %s filedialog failed: %s",
                self._session.session_id,
                type(e).__name__,
            )
            self._messagebox.showerror(
                _TITLE_FILEDIALOG_ERROR,
                _MSG_FILEDIALOG_ERROR_FMT.format(type=type(e).__name__),
            )
            return None
        return path if path else None

    def _on_skip(self) -> None:
        cand = self._selected_candidate()
        if cand is None or cand.status not in OPEN_PAIR_STATUSES:
            return
        self._log_operation("skipped_attempt", cand)
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

        純粋なロジックは :func:`resolve_candidate` に切り出してあり Tk 非依存。本メソッドは
        永続化・UI 更新・終了検知の orchestration を担当する。

        **save_session 失敗時の契約**:
        - `resolve_candidate` は save 前に新 Session を構築して ``self._session`` を
          置換するため、save が失敗した場合 **dialog 内部のメモリは新 status /
          ディスクは旧 status** の不整合になる。
        - 例外は呼出元に伝播する（UI 握り潰し禁止、PII 孤児化回避）。
        - Tk callback 経由で送出された例外は :meth:`_on_callback_exception` が捕捉し、
          ユーザー通知 + mainloop 停止する。
        - 呼出側は UI 終了後にセッションを **必ず再ロード** し、dialog 内部の session を捨てること。
          これで on-disk の旧状態から再開できる（未解決扱いで再提示される）。
        """
        self._session = resolve_candidate(
            self._session,
            page_index,
            status=status,
            matched_b=matched_b,
            matched_c=matched_c,
            clear_similar=clear_similar,
        )
        # fail-fast: 例外は呼出元に伝播させる（捕捉しない）
        self._session = self._save_session_fn(
            self._session, sessions_dir=self._sessions_dir
        )

        self._refresh_tree()
        self._check_all_resolved()

    def _check_all_resolved(self) -> None:
        """全件解決を検知したら確認ダイアログを出してクローズする。"""
        if not self._session.all_candidates_resolved:
            return
        self._messagebox.showinfo(_TITLE_ALL_RESOLVED, _MSG_ALL_RESOLVED)
        self._close_dialog()

    # -- Tk callback exception handling -------------------------------------

    def _on_callback_exception(
        self,
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_tb: object,
    ) -> None:
        """Tk callback 内で発生した未捕捉例外を fail-fast でハンドルする。

        通常は ``save_session`` の `OSError` / `PermissionError` / `json` 系例外がここに来る。
        PII（ファイルパス等）が例外文字列に含まれる可能性があるため、ログには型名と
        session_id のみ出力する。例外詳細は messagebox で画面表示のみに留める。
        mainloop 停止後 ``run()`` は ``aborted=True`` を含む ``ConfirmDialogResult`` を返す。
        """
        # PII 防御: logger には type 名と session_id のみ（str(exc_value) はパスを含み得る）。
        logger.error(
            "session %s callback exception: %s",
            self._session.session_id,
            exc_type.__name__,
        )
        self._aborted = True
        # PII 防御: 画面表示も型名のみ（`str(exc_value)` は output_dir 配下のセッション
        # ファイルパスを含みうる。output_dir が `C:\Users\担当者\介護記録\出力\` のように
        # 担当者・患者氏名をパス名に持つ運用では messagebox にそのまま PII が表示される）。
        # 12B / 13C 以降の方針で UI も型名のみに統一。
        detail = _MSG_INTERNAL_ERROR_FMT.format(type=exc_type.__name__)
        try:
            self._messagebox.showerror(_TITLE_INTERNAL_ERROR, detail)
        except Exception as e:  # noqa: BLE001 — showerror 二次失敗は握り潰し可
            # 二次例外のログも type 名のみ（message に PII 含みうるため）
            logger.warning(
                "session %s showerror failed during callback exception: %s",
                self._session.session_id,
                type(e).__name__,
            )
        # close: Toplevel なら destroy、standalone なら quit（run の finally で destroy）
        self._close_dialog()

    # -- Close handling -----------------------------------------------------

    def _on_close_button(self) -> None:
        # resolved_all の判定は run() 内で session.all_candidates_resolved から
        # 都度計算するため、ここではフラグ保持不要。
        if self._session.all_candidates_resolved:
            self._close_dialog()
            return

        if self._messagebox.askyesno(_TITLE_CLOSE_UNRESOLVED, _MSG_CLOSE_UNRESOLVED):
            self._close_dialog()
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
    """指定 page_index の candidate を新 status と matched パスで更新した新 Session を返す。

    Issue #44/#117 immutable 化: 元の ``session`` は mutation されず、``candidates`` を
    置換した新 Session を返す。該当 page_index が存在しない場合は同じ内容の新 Session
    を返す（candidates 自体は新 tuple として構築される）。
    ``similar_candidates`` は ``clear_similar=True`` で空にする（却下時に使用）。
    """
    new_candidates: list[UserCandidate] = []
    for c in session.candidates:
        if c.page_index != page_index:
            new_candidates.append(c)
            continue
        similar: tuple[CandidateState, ...] = () if clear_similar else c.similar_candidates
        new_candidates.append(
            UserCandidate(
                page_index=c.page_index,
                user_name_ocr=c.user_name_ocr,
                confidence=c.confidence,
                status=status,
                matched_b_path=matched_b,
                matched_c_path=matched_c,
                similar_candidates=similar,
            )
        )
    return replace(session, candidates=tuple(new_candidates))


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
    similar: Sequence[CandidateState], kind: SourceKind
) -> str | None:
    """similar_candidates の先頭から、指定 kind (B/C) の path を返す（無ければ None）。"""
    return next((c.path for c in similar if c.kind == kind), None)


def _short_path(path: str | None, max_len: int = 30) -> str:
    if not path:
        return ""
    name = Path(path).name
    if len(name) <= max_len:
        return name
    return "..." + name[-(max_len - 3):]


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
