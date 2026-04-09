"""実機ワイズマン最小E2E検証スクリプト (#3)。

使い方:
    # 環境変数で指定
    $env:WISEMAN_LNK_PATH = "C:\\Users\\<you>\\...\\ワイズマンASPサービス起動.lnk"
    uv run python scripts/smoke_real.py

    # または引数で指定
    uv run python scripts/smoke_real.py "C:\\path\\to\\shortcut.lnk"

事前準備:
    - USBドングルが挿入されていること
    - ワイズマンが起動していないこと (事前終了)
"""

from __future__ import annotations

import contextlib
import logging
import os
import sys
from pathlib import Path

from wiseman_hub.rpa.pywinauto_engine import PywinautoEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s:%(lineno)d %(message)s",
)
logger = logging.getLogger(__name__)


def _resolve_lnk_path() -> Path:
    """ワイズマン起動ショートカットのパスを argv / 環境変数から解決する。"""
    raw = sys.argv[1] if len(sys.argv) >= 2 else os.environ.get("WISEMAN_LNK_PATH", "")
    if not raw:
        raise SystemExit(
            "WISEMAN_LNK_PATH 環境変数またはコマンドライン引数でワイズマン "
            "ショートカット (.lnk) のパスを指定してください。"
        )
    path = Path(raw)
    if not path.exists():
        raise SystemExit(f"指定されたパスが存在しません: {path}")
    return path


def main() -> int:
    lnk_path = _resolve_lnk_path()
    engine = PywinautoEngine(startup_wait_sec=10)
    try:
        engine.launch(str(lnk_path))
        print("[1/3] launcher OK")
        engine.select_care_system()
        print("[2/3] care system OK")
        engine.click_new_registration()
        print("[3/3] new registration OK")
        print("=== ALL GREEN ===")
    except Exception:
        logger.exception("smoke test failed")
        return 1
    finally:
        with contextlib.suppress(EOFError):
            input("Press Enter to close Wiseman and exit...")
        try:
            engine.close_wiseman()
        except Exception:
            logger.exception("close_wiseman failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
