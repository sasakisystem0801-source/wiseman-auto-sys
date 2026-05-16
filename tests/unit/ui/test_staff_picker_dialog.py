"""StaffPickerDialog の pure helper の契約テスト (Issue #314)。

UI dialog instance ごと立ち上げず、純粋関数として ``split_registered_unregistered``
+ ``format_staff_label`` を検証することで、分岐網羅 + ヘッドレス CI 実行 +
回帰検出強度を両立する。Tkinter は import しない (Linux xvfb 不要)。
"""

from __future__ import annotations

from wiseman_hub.ui.staff_picker_dialog import (
    format_staff_label,
    split_registered_unregistered,
)
from wiseman_hub.utils.text_norm import normalize_lookup_key

# ---------- split_registered_unregistered ----------


def test_split_all_registered_returns_empty_unregistered() -> None:
    """全員登録済 → unregistered は空 list、order 維持。"""
    parsed = ["小島", "木塚"]
    keys = {normalize_lookup_key("小島"), normalize_lookup_key("木塚")}
    reg, unreg = split_registered_unregistered(parsed, keys)
    assert reg == ["小島", "木塚"]
    assert unreg == []


def test_split_all_unregistered_returns_empty_registered() -> None:
    """全員未登録 → registered は空 list。"""
    parsed = ["未知A", "未知B"]
    keys: set[str] = set()
    reg, unreg = split_registered_unregistered(parsed, keys)
    assert reg == []
    assert unreg == ["未知A", "未知B"]


def test_split_partial_hit_preserves_order() -> None:
    """部分 hit → 元順を保ったまま 2 list に分かれる (UI 表示順予測可能性)。"""
    parsed = ["小島", "宮下", "木塚"]
    keys = {normalize_lookup_key("小島"), normalize_lookup_key("木塚")}
    reg, unreg = split_registered_unregistered(parsed, keys)
    # 元順維持: 「小島→木塚」 / 「宮下」
    assert reg == ["小島", "木塚"]
    assert unreg == ["宮下"]


def test_split_normalizes_lookup_for_matching() -> None:
    """報告者キーが normalize_lookup_key 済なら元表記の表記揺れも吸収して照合する。

    全角空白付きの元表記が半角空白で normalize されてキー集合の値と一致する。
    """
    parsed = ["小島  太郎"]  # 全角空白 (絵文字や全角スペースを想定)
    # キー側は半角空白 1 個に正規化された形 (normalize_lookup_key の挙動依存)
    keys = {normalize_lookup_key("小島  太郎")}
    reg, unreg = split_registered_unregistered(parsed, keys)
    assert reg == ["小島  太郎"]
    assert unreg == []


def test_split_empty_input_returns_two_empty_lists() -> None:
    """空入力 → 両方とも空。境界値保護。"""
    reg, unreg = split_registered_unregistered([], {normalize_lookup_key("X")})
    assert reg == []
    assert unreg == []


# ---------- format_staff_label ----------


def test_format_staff_label_registered_returns_bare_name() -> None:
    """登録済 → 元表記そのまま (装飾なし、業務責任者がわかる表示)。"""
    assert format_staff_label("小島", registered=True) == "小島"


def test_format_staff_label_unregistered_appends_reason() -> None:
    """未登録 → 末尾に「(mapping 未登録)」明示 (なぜ選べないかを伝える)。"""
    assert format_staff_label("宮下", registered=False) == "宮下 (mapping 未登録)"


def test_format_staff_label_preserves_special_chars() -> None:
    """元表記の空白・記号は装飾せずそのまま保つ (業務責任者の意識から外さない)。"""
    assert format_staff_label("小島 太郎", registered=True) == "小島 太郎"
    assert (
        format_staff_label("小島 太郎", registered=False)
        == "小島 太郎 (mapping 未登録)"
    )
