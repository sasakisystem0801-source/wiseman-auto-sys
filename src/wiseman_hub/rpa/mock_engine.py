"""モックRPAエンジン — macOSテスト用・デモ用"""

from __future__ import annotations

import logging
from pathlib import Path

from wiseman_hub.rpa.base import RPAEngine

logger = logging.getLogger(__name__)


class MockEngine(RPAEngine):
    """テスト・開発用のモックRPAエンジン。

    実際のGUI操作は行わず、ログ出力とダミーデータを返す。
    macOS上でのユニットテストやパイプライン統合テストに使用する。
    """

    def __init__(self) -> None:
        self._logged_in = False
        self._current_screen: str = ""
        self._call_log: list[str] = []

    @property
    def call_log(self) -> list[str]:
        """呼び出し履歴（テスト検証用）"""
        return self._call_log

    def launch_and_login(self, exe_path: str, username: str, password: str) -> None:
        self._call_log.append(f"launch_and_login({exe_path}, {username})")
        logger.info("[MOCK] ワイズマン起動・ログイン: %s / %s", exe_path, username)
        self._logged_in = True

    def navigate_menu(self, menu_path: list[str]) -> None:
        path_str = " → ".join(menu_path)
        self._call_log.append(f"navigate_menu({path_str})")
        logger.info("[MOCK] メニュー遷移: %s", path_str)
        self._current_screen = menu_path[-1] if menu_path else ""

    def export_csv(self, output_dir: Path) -> Path | None:
        self._call_log.append(f"export_csv({output_dir})")
        logger.info("[MOCK] CSVエクスポート: %s", output_dir)

        # ダミーCSVを生成
        output_dir.mkdir(parents=True, exist_ok=True)
        csv_path = output_dir / f"mock_{self._current_screen or 'export'}.csv"
        csv_path.write_text(
            "利用者名,日付,サービス内容\n"
            "山田太郎,2026-03-24,通所リハビリ\n"
            "佐藤花子,2026-03-24,訪問リハビリ\n",
            encoding="utf-8",
        )
        logger.info("[MOCK] ダミーCSV生成: %s", csv_path)
        return csv_path

    def read_grid_data(self) -> list[list[str]]:
        self._call_log.append("read_grid_data()")
        logger.info("[MOCK] グリッドデータ読み取り")
        return [
            ["利用者名", "日付", "サービス内容"],
            ["山田太郎", "2026-03-24", "通所リハビリ"],
            ["佐藤花子", "2026-03-24", "訪問リハビリ"],
        ]

    def close_current_window(self) -> None:
        self._call_log.append("close_current_window()")
        logger.info("[MOCK] 子ウィンドウを閉じる")
        self._current_screen = ""

    def close_wiseman(self) -> None:
        self._call_log.append("close_wiseman()")
        logger.info("[MOCK] ワイズマン終了")
        self._logged_in = False

    def is_dongle_present(self) -> bool:
        self._call_log.append("is_dongle_present()")
        logger.info("[MOCK] ドングル確認 → True")
        return True

    def take_screenshot(self, name: str) -> Path:
        self._call_log.append(f"take_screenshot({name})")
        output_dir = Path("data/screenshots")
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{name}.png"
        path.write_bytes(b"MOCK_PNG")
        logger.info("[MOCK] スクリーンショット: %s", path)
        return path
