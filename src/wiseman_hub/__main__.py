"""エントリポイント: python -m wiseman_hub で実行。

既定ではランチャー GUI を起動する。`--rpa` 指定時は従来の RPA パイプライン
（WisemanHub）を実行する（Wiseman 起動 → CSV 抽出 → GCS アップロード）。
"""

import argparse
import logging
import sys
from pathlib import Path


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger(__name__)

    parser = argparse.ArgumentParser(
        prog="wiseman-hub",
        description="Wiseman PDF ツール / ランチャー GUI",
    )
    parser.add_argument(
        "--rpa",
        action="store_true",
        help="ランチャー GUI を開かず、RPA パイプラインを直接実行する",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="設定ファイルパス（既定: config/default.toml）",
    )
    args = parser.parse_args()

    try:
        if args.rpa:
            from wiseman_hub.app import WisemanHub

            WisemanHub(config_path=args.config).run()
        else:
            from wiseman_hub.config import load_config
            from wiseman_hub.ui.launcher import Launcher

            config_path = args.config if args.config is not None else Path("config/default.toml")
            config = load_config(config_path)
            Launcher(config=config, config_path=config_path).run()
    except KeyboardInterrupt:
        logger.info("シャットダウン（Ctrl+C）")
        sys.exit(0)
    except Exception:
        logger.exception("予期しないエラーで終了")
        sys.exit(1)


if __name__ == "__main__":
    main()
