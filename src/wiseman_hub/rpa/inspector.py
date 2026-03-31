"""UIインスペクタ — ワイズマンのコントロールツリーをダンプ・カタログ化する"""

from __future__ import annotations

import json
import logging
import sys
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# pywinautoはWindows専用
if sys.platform == "win32":
    from pywinauto.base_wrapper import BaseWrapper
else:
    BaseWrapper = None


def dump_control_tree(
    wrapper: Any,
    max_depth: int = 10,
    _current_depth: int = 0,
) -> dict[str, Any]:
    """ウィンドウのコントロールツリーを辞書形式で再帰収集する。

    Args:
        wrapper: pywinautoのウィンドウ/コントロールラッパー
        max_depth: 再帰の最大深さ。0の場合はルートノードのみ収集する。
        _current_depth: 内部用。現在の深さ。

    Returns:
        コントロール情報の辞書（children に子要素を含む）
    """
    if sys.platform != "win32":
        raise RuntimeError("dump_control_tree はWindows環境でのみ実行できます")

    rect = wrapper.rectangle()
    info: dict[str, Any] = {
        "control_type": wrapper.element_info.control_type,
        "name": wrapper.element_info.name,
        "automation_id": getattr(wrapper.element_info, "automation_id", ""),
        "class_name": getattr(wrapper.element_info, "class_name", ""),
        "rectangle": {
            "left": rect.left,
            "top": rect.top,
            "right": rect.right,
            "bottom": rect.bottom,
        },
        "is_enabled": wrapper.is_enabled(),
        "is_visible": wrapper.is_visible(),
        "depth": _current_depth,
        "children": [],
    }

    if _current_depth < max_depth:
        try:
            for child in wrapper.children():
                info["children"].append(
                    dump_control_tree(child, max_depth, _current_depth + 1)
                )
        except Exception as exc:
            logger.warning(
                "子要素の取得中にエラー (depth=%d, name=%s, error=%s: %s)",
                _current_depth, info["name"], type(exc).__name__, exc,
            )

    return info


def save_catalog(tree: dict[str, Any], output_path: Path) -> None:
    """カタログをJSON形式でアトミックに保存する。

    一時ファイルに書き込み後リネームすることで、書き込み途中の破損を防ぐ。
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=output_path.parent, suffix=".tmp", delete=False
    ) as tmp:
        json.dump(tree, tmp, ensure_ascii=False, indent=2)
        tmp_path = Path(tmp.name)
    tmp_path.replace(output_path)
    logger.info("カタログ保存: %s", output_path)


def load_catalog(path: Path) -> dict[str, Any]:
    """JSONカタログを読み込む。

    Raises:
        FileNotFoundError: ファイルが存在しない場合
        ValueError: JSONが不正な場合
    """
    try:
        with open(path, encoding="utf-8") as f:
            data: dict[str, Any] = json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"カタログファイルが見つかりません: {path}") from None
    except json.JSONDecodeError as e:
        raise ValueError(f"カタログJSONが不正です ({path}): {e}") from e
    return data


def find_controls(
    node: dict[str, Any],
    *,
    control_type: str | None = None,
    name_contains: str | None = None,
    automation_id: str | None = None,
) -> list[dict[str, Any]]:
    """カタログツリーからコントロールを検索する（反復実装）。

    すべての条件はAND結合。条件を何も指定しない場合は空リストを返す。

    Args:
        node: カタログのルートノード
        control_type: 完全一致するコントロールタイプ (例: "Button")
        name_contains: 名前に含まれる部分文字列
        automation_id: 完全一致するAutomationId
    """
    has_filter = control_type is not None or name_contains is not None or automation_id is not None
    if not has_filter:
        return []

    results: list[dict[str, Any]] = []
    stack = [node]

    while stack:
        current = stack.pop()
        match = True

        if control_type is not None and current.get("control_type") != control_type:
            match = False
        if name_contains is not None and name_contains not in (current.get("name") or ""):
            match = False
        if automation_id is not None and current.get("automation_id") != automation_id:
            match = False

        if match:
            results.append(current)

        stack.extend(current.get("children", []))

    return results


def print_summary(tree: dict[str, Any]) -> None:
    """コントロール種別ごとの数をサマリー出力する。"""
    counts: dict[str, int] = {}
    _count_types(tree, counts)

    print("=== UIカタログサマリー ===")
    print(f"ルート: {tree.get('name', '(unknown)')} [{tree.get('control_type', '')}]")
    print(f"コントロール総数: {sum(counts.values())}")
    print()
    for ctype, count in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {ctype:30s} {count:>4d}")


def _count_types(tree: dict[str, Any], counts: dict[str, int]) -> None:
    """反復的にコントロールタイプをカウントする。"""
    stack = [tree]
    while stack:
        node = stack.pop()
        ctype = node.get("control_type", "Unknown")
        counts[ctype] = counts.get(ctype, 0) + 1
        stack.extend(node.get("children", []))
