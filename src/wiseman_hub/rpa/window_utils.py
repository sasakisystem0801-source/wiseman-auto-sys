"""ウィンドウ検索・待機ヘルパー"""

from __future__ import annotations

import logging
import sys
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# pywinautoはWindows専用。macOSではインポートをスキップ
if sys.platform == "win32":
    from pywinauto import Application, Desktop
    from pywinauto.findwindows import ElementNotFoundError
else:
    Application = None
    Desktop = None
    ElementNotFoundError = Exception


def find_wiseman_window(title_pattern: str = ".*管理システム SP.*") -> object | None:
    """ワイズマンのメインウィンドウを検索する。

    Args:
        title_pattern: タイトルバーの正規表現パターン

    Returns:
        見つかったウィンドウオブジェクト。見つからない場合はNone。
    """
    if sys.platform != "win32":
        logger.warning("Windows以外の環境ではウィンドウ検索は使用できません")
        return None

    try:
        app = Application(backend="uia").connect(title_re=title_pattern)
        window = app.window(title_re=title_pattern)
        window.wait("visible", timeout=5)
        logger.info("ワイズマンウィンドウ発見: %s", window.window_text())
        return window
    except ElementNotFoundError:
        logger.warning("ワイズマンウィンドウが見つかりません: %s", title_pattern)
        return None


def wait_for_window(title_pattern: str, timeout: int = 30) -> object | None:
    """指定タイトルのウィンドウが出現するまで待機する。"""
    if sys.platform != "win32":
        return None

    start = time.time()
    while time.time() - start < timeout:
        result = find_wiseman_window(title_pattern)
        if result is not None:
            return result
        time.sleep(1)
    logger.error("ウィンドウ待機タイムアウト (%ds): %s", timeout, title_pattern)
    return None
