"""担当者複数 (`/` `／` 区切り) 入力から 1 名を選ぶレビュー UI モーダル (Issue #314)。

C ダイアログで NEEDS_REVIEW_STAFF 行をダブルクリックすると開く。

機能:
    1. 担当者候補 (元表記) を radiobutton で提示
    2. report_staff に mapping 未登録の担当者は disable + 「(mapping 未登録)」表示
       (Codex review High #4: 登録済 1 名のみでも自動確定せず必ず人間判断を求める)
    3. 「この選択を記憶」チェックで staff_choice_cache 永続化を要求
    4. OK / キャンセル

戻り値:
    ``get_result() -> (selected_staff: str | None, remember: bool)``
    selected は元表記 (parsed_staffs の要素のいずれか)。キャンセル時は ``(None, False)``。

設計判断:
    - 自動確定はしない: 登録済 1 名のみでも radiobutton 表示 + 人間 OK を必須にする
      (誤入力時の沈黙誤配置リスク防止、Codex review High #4)
    - **初期選択は持たせない**: XlsxPickerDialog と同じ方針。「(未選択)」状態
      で OK disabled、必ず明示クリックを要求する
    - **disable 状態の radiobutton にカーソル誘導しない**: 未登録担当者は
      Treeview ナビゲーションでスキップされるよう state="disabled" のみ付与
"""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import ttk

from wiseman_hub.utils.text_norm import normalize_lookup_key

logger = logging.getLogger(__name__)


def split_registered_unregistered(
    parsed_staffs: list[str],
    report_staff_keys: set[str],
) -> tuple[list[str], list[str]]:
    """元表記 staff list を「登録済」「未登録」に分ける純粋関数。

    ``report_staff_keys`` は normalize_lookup_key 済のキー集合。元表記の
    各 staff を ``normalize_lookup_key`` 通してから照合する (表記揺れ吸収)。
    順序は ``parsed_staffs`` の元順を維持 (UI 表示の予測可能性)。

    Returns:
        (registered, unregistered) いずれも元表記の list。
    """
    registered: list[str] = []
    unregistered: list[str] = []
    for s in parsed_staffs:
        if normalize_lookup_key(s) in report_staff_keys:
            registered.append(s)
        else:
            unregistered.append(s)
    return registered, unregistered


def format_staff_label(staff: str, *, registered: bool) -> str:
    """radiobutton ラベル生成 (純粋関数)。

    Args:
        staff: 元表記の担当者名 (例: "小島"、"宮下")。
        registered: report_staff に mapping 登録済なら True。

    Returns:
        登録済: ``"<staff>"`` (例: ``"小島"``)
        未登録: ``"<staff> (mapping 未登録)"`` (例: ``"宮下 (mapping 未登録)"``)

    未登録ラベルは StaffPickerDialog 内で radiobutton state="disabled" と
    併用される。ラベル単体でも業務責任者が「なぜ選べないのか」を理解できるよう
    末尾に理由を付ける。
    """
    if registered:
        return staff
    return f"{staff} (mapping 未登録)"


class StaffPickerDialog:
    def __init__(
        self,
        parent: tk.Misc,
        parsed_staffs: list[str],
        report_staff_keys: set[str],
        title_context: str = "",
    ) -> None:
        """担当者選択ダイアログ。

        Args:
            parent: 親 widget (Toplevel / Tk)。
            parsed_staffs: parse_multi_staff で分解した元表記担当者 list。
            report_staff_keys: ChecklistConfig.report_staff のキー集合
                (normalize_lookup_key 適用済)。disable 制御に使用。
            title_context: タイトルバーに付ける補助情報 (利用者名 / 居宅 / 元 row.staff)。
        """
        self._parent = parent
        self._parsed_staffs = list(parsed_staffs)
        self._registered, self._unregistered = split_registered_unregistered(
            self._parsed_staffs, report_staff_keys
        )
        self._selected: str | None = None
        self._remember: bool = True

        self._top = tk.Toplevel(parent)
        self._top.title(
            f"担当者を選択: {title_context}" if title_context else "担当者を選択"
        )
        self._top.geometry("520x360")
        if hasattr(parent, "winfo_toplevel"):
            self._top.transient(parent.winfo_toplevel())
        self._top.grab_set()

        self._build_ui()

    def get_toplevel(self) -> tk.Toplevel:
        return self._top

    def get_result(self) -> tuple[str | None, bool]:
        return self._selected, self._remember

    # ---- UI 構築 ----

    def _build_ui(self) -> None:
        top = self._top

        head = ttk.Frame(top, padding=8)
        head.pack(fill="x")
        n_all = len(self._parsed_staffs)
        n_reg = len(self._registered)
        if self._unregistered:
            head_text = (
                f"担当者 {n_all} 名中、登録済 {n_reg} 名 "
                f"(未登録: {', '.join(self._unregistered)})"
            )
        else:
            head_text = f"担当者 {n_all} 名から選択してください"
        ttk.Label(head, text=head_text, wraplength=480).pack(side="left")

        body = ttk.LabelFrame(top, text="候補担当者", padding=8)
        body.pack(fill="both", expand=True, padx=8, pady=4)

        # 初期選択は持たせない (XlsxPickerDialog と同じ方針)。
        # tk.StringVar の初期値は parsed_staffs の値と一致しない sentinel を使う。
        self._choice_var = tk.StringVar(value="__UNSELECTED__")
        registered_keys_set = {normalize_lookup_key(s) for s in self._registered}
        for staff in self._parsed_staffs:
            is_registered = normalize_lookup_key(staff) in registered_keys_set
            label = format_staff_label(staff, registered=is_registered)
            rb = ttk.Radiobutton(
                body,
                text=label,
                value=staff,
                variable=self._choice_var,
                command=self._on_choice_change,
            )
            if not is_registered:
                rb.configure(state="disabled")
            rb.pack(anchor="w", pady=2)

        # 「現在の選択値」表示
        sel_frame = ttk.Frame(top, padding=(8, 0))
        sel_frame.pack(fill="x")
        self._current_var = tk.StringVar(
            value="現在の選択: (未選択 — 上の候補から 1 名を選んでください)"
        )
        ttk.Label(
            sel_frame, textvariable=self._current_var, foreground="#0a5",
            wraplength=480,
        ).pack(side="left", fill="x", expand=True)

        # 記憶チェック + ボタン
        bottom = ttk.Frame(top, padding=8)
        bottom.pack(fill="x")
        self._remember_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            bottom,
            text="この選択を記憶（次回以降同じ組合せで自動使用）",
            variable=self._remember_var,
        ).pack(side="left")
        ttk.Button(bottom, text="キャンセル", command=self._on_cancel).pack(
            side="right", padx=4
        )
        self._ok_btn = ttk.Button(bottom, text="OK", command=self._on_ok)
        self._ok_btn.pack(side="right", padx=4)
        # 初期状態は未選択 → OK 不可
        self._ok_btn.configure(state="disabled")

    # ---- ハンドラ ----

    def _on_choice_change(self) -> None:
        """radiobutton 選択変更で現在の選択ラベル + OK 状態を更新。"""
        val = self._choice_var.get()
        if val and val != "__UNSELECTED__":
            self._current_var.set(f"現在の選択: {val}")
            self._ok_btn.configure(state="normal")
        else:
            self._current_var.set(
                "現在の選択: (未選択 — 上の候補から 1 名を選んでください)"
            )
            self._ok_btn.configure(state="disabled")

    def _on_ok(self) -> None:
        val = self._choice_var.get()
        if not val or val == "__UNSELECTED__":
            return
        # 念のため: 未登録担当者の radiobutton は disable しているが、
        # キーボード等で値設定された場合の二重ガード
        if normalize_lookup_key(val) not in {
            normalize_lookup_key(s) for s in self._registered
        }:
            logger.warning(
                "StaffPickerDialog: unregistered staff selected (defensive reject): %s",
                val,
            )
            return
        self._selected = val
        self._remember = bool(self._remember_var.get())
        self._top.destroy()

    def _on_cancel(self) -> None:
        self._selected = None
        self._remember = False
        self._top.destroy()
