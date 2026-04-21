"""エントリポイント: python -m wiseman_hub で実行。

既定ではランチャー GUI を起動する。`--rpa` 指定時は従来の RPA パイプライン
（WisemanHub）を実行する（Wiseman 起動 → CSV 抽出 → GCS アップロード）。
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import sys
from collections.abc import Callable
from pathlib import Path


def _make_phase_a_callback(
    config_path: Path,
) -> Callable[[], None]:
    """Launcher に注入する「PDF マージ処理」コールバックを組み立てる。

    Phase A 実行時点の TOML を再ロードすることで、設定 GUI（12B）での変更を
    再起動なしに反映する。Launcher 側で worker thread で呼ばれるため、
    ここでは Tk API には触れない（スレッド非安全）。
    """

    def run_phase_a_callback() -> None:
        from wiseman_hub.config import load_config
        from wiseman_hub.pdf.matcher import KanjiMatcher
        from wiseman_hub.pdf.ocr_client import OcrClient
        from wiseman_hub.pdf.pipeline import run_phase_a

        config = load_config(config_path)
        source_a_path = (
            Path(config.pdf_merge.input_dir) / config.pdf_merge.source_a_filename
        )
        sessions_dir = Path(config.pdf_merge.output_dir) / ".sessions"

        matcher = KanjiMatcher(
            input_dir=Path(config.pdf_merge.input_dir),
            source_b_pattern=config.pdf_merge.source_b_pattern,
            source_c_pattern=config.pdf_merge.source_c_pattern,
        )
        ocr_client = OcrClient(config.ocr_backend)

        # OcrClient は __enter__/__exit__ を実装する（HTTP セッションクリーンアップ）。
        # Protocol 上は任意のため、hasattr で確認してから stack に入れる。
        with contextlib.ExitStack() as stack:
            if hasattr(ocr_client, "__exit__"):
                stack.enter_context(ocr_client)
            run_phase_a(
                source_a_path=source_a_path,
                config=config.pdf_merge,
                ocr_client=ocr_client,
                matcher=matcher,
                sessions_dir=sessions_dir,
            )

    return run_phase_a_callback


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

            config_path = (
                args.config if args.config is not None else Path("config/default.toml")
            )
            config = load_config(config_path)
            Launcher(
                config=config,
                config_path=config_path,
                on_run_pdf_merge=_make_phase_a_callback(config_path),
            ).run()
    except KeyboardInterrupt:
        logger.info("シャットダウン（Ctrl+C）")
        sys.exit(0)
    except Exception as exc:
        # PII 防御: ``logger.exception`` は traceback 経由で PDF パス / 氏名を含む
        # 可能性のある例外 message を出力する。本番は医療介護データを扱うため、
        # ログには型名のみを残し、例外詳細は画面/検証環境に限定する。
        logger.error("予期しないエラーで終了: %s", type(exc).__name__)
        sys.exit(1)


if __name__ == "__main__":
    main()
