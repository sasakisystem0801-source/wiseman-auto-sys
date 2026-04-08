"""Wiseman Hub オーケストレータ - メインアプリケーションループ"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from wiseman_hub.cloud.storage import upload_files
from wiseman_hub.config import AppConfig, load_config
from wiseman_hub.rpa.base import RPAEngine

logger = logging.getLogger(__name__)


def create_rpa_engine(config: AppConfig) -> RPAEngine:
    """プラットフォームに応じたRPAエンジンを生成する。

    Windows → PywinautoEngine（実RPA操作）
    macOS/Linux → MockEngine（テスト・デモ用）
    """
    if sys.platform == "win32":
        from wiseman_hub.rpa.pywinauto_engine import PywinautoEngine

        return PywinautoEngine(
            startup_wait_sec=config.wiseman.startup_wait_sec,
            window_title_pattern=config.wiseman.window_title_pattern,
        )
    else:
        from wiseman_hub.rpa.mock_engine import MockEngine

        logger.warning("Windows以外の環境のためMockEngineを使用します")
        return MockEngine()


class WisemanHub:
    """ワイズマン自動化ハブ。RPA操作・クラウド同期・スケジューラを統括する。"""

    def __init__(self, config_path: Path | None = None, rpa_engine: RPAEngine | None = None) -> None:
        self.config: AppConfig = load_config(config_path)
        self.output_dir = Path("data/exports")
        self.rpa = rpa_engine if rpa_engine is not None else create_rpa_engine(self.config)
        logger.info("Wiseman Hub v%s 初期化 (RPA: %s)", self.config.version, type(self.rpa).__name__)

    def run(self) -> None:
        """メインループ。PoCではワンショット実行。"""
        logger.info("=== Wiseman Hub 開始 ===")
        try:
            self._run_pipeline()
        finally:
            self.rpa.close_wiseman()
        logger.info("=== Wiseman Hub 完了 ===")

    def _run_pipeline(self) -> None:
        """起動 → CSV抽出 → GCSアップロードのパイプライン

        ワイズマンはUSBドングル認証のみで、アプリ内ログイン画面は存在しない（ADR-007）。
        """

        # Step 1: ワイズマン起動 → システム選択ランチャーからケア記録を選択
        # ADR-007: USBドングル認証後にシステム選択ランチャー(frmStartUp)が開くため
        # select_care_system() で目的のケア記録システム(frmMenu200)に遷移する
        logger.info("[Step 1/3] ワイズマン起動中...")
        self.rpa.launch(self.config.wiseman.exe_path)
        self.rpa.select_care_system()

        # Step 2: CSV抽出
        logger.info("[Step 2/3] CSV帳票を抽出中...")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        csv_files: list[Path] = []
        for report in self.config.reports:
            logger.info("  帳票: %s (メニュー: %s)", report.name, " → ".join(report.menu_path))
            self.rpa.navigate_menu(report.menu_path)
            path = self.rpa.export_csv(self.output_dir)
            if path:
                csv_files.append(path)
            self.rpa.close_current_window()

        if not csv_files:
            logger.warning("CSVファイルが抽出されませんでした")
            return
        logger.info("抽出完了: %d ファイル", len(csv_files))

        # Step 3: GCSアップロード
        logger.info("[Step 3/3] GCSにアップロード中...")
        uris = upload_files(self.config.gcp, csv_files)
        for uri in uris:
            logger.info("  → %s", uri)

        logger.info("パイプライン完了")
