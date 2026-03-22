"""Wiseman Hub オーケストレータ - メインアプリケーションループ"""

from __future__ import annotations

import logging
from pathlib import Path

from wiseman_hub.cloud.storage import upload_files
from wiseman_hub.config import AppConfig, load_config

logger = logging.getLogger(__name__)


class WisemanHub:
    """ワイズマン自動化ハブ。RPA操作・クラウド同期・スケジューラを統括する。"""

    def __init__(self, config_path: Path | None = None) -> None:
        self.config: AppConfig = load_config(config_path)
        self.output_dir = Path("data/exports")
        logger.info("Wiseman Hub v%s 初期化", self.config.version)

    def run(self) -> None:
        """メインループ。PoCではワンショット実行。"""
        logger.info("=== Wiseman Hub 開始 ===")
        self._run_pipeline()
        logger.info("=== Wiseman Hub 完了 ===")

    def _run_pipeline(self) -> None:
        """ログイン → CSV抽出 → GCSアップロードのパイプライン"""

        # Step 1: ワイズマンにログイン
        logger.info("[Step 1/3] ワイズマンにログイン中...")
        password = self._get_password()  # noqa: F841
        # TODO: rpa_engine.launch_and_login(
        #     self.config.wiseman.exe_path,
        #     self.config.wiseman.username,
        #     password
        # )

        # Step 2: CSV抽出
        logger.info("[Step 2/3] CSV帳票を抽出中...")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        csv_files: list[Path] = []
        for report in self.config.reports:
            logger.info("  帳票: %s (メニュー: %s)", report.name, " → ".join(report.menu_path))
            # TODO: rpa_engine.navigate_menu(report.menu_path)
            # TODO: path = rpa_engine.export_csv(self.output_dir)
            # TODO: if path: csv_files.append(path)

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

    def _get_password(self) -> str:
        """Wisemanパスワードをkeyringから取得する。"""
        try:
            import keyring

            password = keyring.get_password("wiseman-hub", self.config.wiseman.username)
            if password is None:
                msg = (
                    f"パスワードが設定されていません。以下のコマンドで設定してください:\n"
                    f"  python -c \"import keyring; keyring.set_password('wiseman-hub', "
                    f"'{self.config.wiseman.username}', 'YOUR_PASSWORD')\""
                )
                raise RuntimeError(msg)
            return password
        except ImportError:
            msg = "keyringがインストールされていません: pip install keyring"
            raise RuntimeError(msg) from None
