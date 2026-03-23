#!/usr/bin/env python3
"""ワイズマンのUI要素を一括ダンプするCLIスクリプト（Windows実機用）

使い方:
    python scripts/dump_ui.py                    # メインウィンドウをダンプ
    python scripts/dump_ui.py --text             # テキスト形式も同時出力
    python scripts/dump_ui.py --title "ケア記録"  # 特定ウィンドウを指定
    python scripts/dump_ui.py --output out.json  # 出力先を指定
    python scripts/dump_ui.py --depth 5          # 探索の最大深さ
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

# プロジェクトルートをPYTHONPATHに追加
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from wiseman_hub.rpa.inspector import dump_control_tree, print_summary, save_catalog  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_TITLE_PATTERN = ".*管理システム SP.*"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "ui_catalogs"


def main() -> None:
    if sys.platform != "win32":
        print("ERROR: このスクリプトはWindows環境でのみ実行できます", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(description="ワイズマンUI要素ダンプツール")
    parser.add_argument("--title", default=DEFAULT_TITLE_PATTERN, help="ウィンドウタイトルの正規表現パターン")
    parser.add_argument("--output", "-o", type=Path, default=None, help="出力JSONファイルパス")
    parser.add_argument("--text", action="store_true", help="テキスト形式(print_control_identifiers)も同時出力")

    def depth_range(val: str) -> int:
        n = int(val)
        if n < 1 or n > 50:
            raise argparse.ArgumentTypeError("depthは1〜50の範囲で指定してください")
        return n

    parser.add_argument("--depth", type=depth_range, default=10, help="探索の最大深さ 1-50 (default: 10)")
    args = parser.parse_args()

    from pywinauto import Application

    # ワイズマンに接続
    logger.info("ワイズマンウィンドウを検索中: %s", args.title)
    try:
        app = Application(backend="uia").connect(title_re=args.title)
        window = app.window(title_re=args.title)
        window.wait("visible", timeout=10)
    except Exception as e:
        print(f"ERROR: ワイズマンウィンドウに接続できません: {e}", file=sys.stderr)
        print("ワイズマンが起動済みであることを確認してください。", file=sys.stderr)
        sys.exit(1)

    window_title = window.window_text()
    logger.info("接続成功: %s", window_title)

    # 出力パス決定
    if args.output:
        output_path = args.output
    else:
        safe_title = re.sub(r'[\\/:*?"<>|\s]+', "_", window_title)[:50]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = DEFAULT_OUTPUT_DIR / f"{timestamp}_{safe_title}.json"

    # コントロールツリーをダンプ
    logger.info("コントロールツリーをダンプ中 (max_depth=%d)...", args.depth)
    tree = dump_control_tree(window, max_depth=args.depth)

    # JSON保存
    save_catalog(tree, output_path)
    print(f"\nJSON カタログ保存: {output_path}")

    # テキスト形式も出力
    if args.text:
        text_path = output_path.with_suffix(".txt")
        window.print_control_identifiers(filename=str(text_path))
        print(f"テキスト形式保存: {text_path}")

    # サマリー表示
    print()
    print_summary(tree)


if __name__ == "__main__":
    main()
