"""UIカタログのJSON構造を解析するスクリプト"""
import json
import sys
from pathlib import Path


def show_tree(node, depth=0, max_depth=4):
    ct = node.get("control_type", "")
    aid = node.get("automation_id", "")
    name = node.get("name", "")[:50]
    print(f"{'  ' * depth}{ct} | aid={aid} | name={name}")
    if depth < max_depth:
        for c in node.get("children", []):
            show_tree(c, depth + 1, max_depth)


catalogs = sorted(Path("data/ui_catalogs").glob("*.json"))
if not catalogs:
    print("ERROR: data/ui_catalogs/*.json が見つかりません")
    sys.exit(1)

data = json.loads(catalogs[-1].read_text(encoding="utf-8"))
print(f"=== カタログ: {catalogs[-1].name} ===\n")

# MDI Client Pane > Window の中身を depth=4 で表示
for child in data.get("children", []):
    if child.get("control_type") == "Pane":
        for win in child.get("children", []):
            if win.get("control_type") == "Window":
                print(f"--- MDI Child: {win.get('name', '')} ---")
                show_tree(win, depth=0, max_depth=4)
