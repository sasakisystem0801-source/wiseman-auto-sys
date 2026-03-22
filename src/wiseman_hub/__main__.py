"""エントリポイント: python -m wiseman_hub で実行"""

import logging
import sys

from wiseman_hub.app import WisemanHub


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger(__name__)

    try:
        hub = WisemanHub()
        hub.run()
    except KeyboardInterrupt:
        logger.info("シャットダウン（Ctrl+C）")
        sys.exit(0)
    except Exception:
        logger.exception("予期しないエラーで終了")
        sys.exit(1)


if __name__ == "__main__":
    main()
