"""実機ワイズマン最小E2E検証スクリプト (#3)。

使い方:
    uv run python scripts/smoke_real.py

事前準備:
    - USBドングルが挿入されていること
    - ワイズマンが起動していないこと (事前終了)
    - 設定: LNK_PATH を環境に合わせて調整
"""

from __future__ import annotations

import logging
import sys

from wiseman_hub.rpa.pywinauto_engine import PywinautoEngine

LNK_PATH = r"C:\Users\sasak\OneDrive\デスクトップ\ワイズマンASPサービス起動_O.lnk"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s:%(lineno)d %(message)s",
)


def main() -> int:
    engine = PywinautoEngine(startup_wait_sec=10)
    try:
        engine.launch(LNK_PATH)
        print("[1/3] launcher OK")
        engine.select_care_system()
        print("[2/3] care system OK")
        engine.click_new_registration()
        print("[3/3] new registration OK")
        print("=== ALL GREEN ===")
    except Exception:
        logging.exception("smoke test failed")
        return 1
    finally:
        try:
            input("Press Enter to close Wiseman and exit...")
        except EOFError:
            pass
        try:
            engine.close_wiseman()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
