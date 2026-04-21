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
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import tkinter as tk

    from wiseman_hub.config import AppConfig

logger = logging.getLogger(__name__)


class _LauncherLike(Protocol):
    """``_make_settings_callback`` が必要とする Launcher の最小インターフェース。

    import 循環と Tk 依存を避けるため Protocol で表現し、Launcher 実体を直接
    参照しない（テストで FakeLauncher を差し替えやすくする副次効果もある）。
    """

    def reload_config(self, config: AppConfig) -> None: ...

    def get_root(self) -> tk.Misc: ...


def _make_settings_callback(
    config_path: Path,
    get_launcher: Callable[[], _LauncherLike],
) -> Callable[[], None]:
    """Launcher に注入する「設定」コールバックを組み立てる。

    設定保存成功時は ``Launcher.reload_config`` を呼び、以降の
    ``validate_config_ready`` 判定が新値で行われるようにする（再起動不要）。
    """

    def open_settings() -> None:
        from tkinter import messagebox

        from wiseman_hub.config import load_config
        from wiseman_hub.ui.settings import SettingsDialog

        launcher = get_launcher()
        try:
            config = load_config(config_path)
        except (OSError, ValueError, TypeError) as exc:
            # TOML 構文エラー / ファイル I/O 失敗時は dialog を開かず Launcher 継続。
            # PII 防御で型名のみログに残す。
            logger.error(
                "load_config failed before settings dialog: %s", type(exc).__name__
            )
            messagebox.showerror(
                "設定ファイル読込エラー",
                "設定ファイルを読み込めませんでした。詳細はログを確認してください。"
                f"\n\n{type(exc).__name__}",
            )
            return

        dialog = SettingsDialog(
            config=config,
            config_path=config_path,
            # Launcher の root を親にすることで Toplevel + grab_set でモーダル化される。
            # 設定編集中に Launcher の PDF マージ処理ボタンが押せない（race 防止）。
            parent=launcher.get_root(),
        )
        result = dialog.run()
        if result.config is not None:
            launcher.reload_config(result.config)

    return open_settings


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
            # 設定コールバックで後から Launcher を参照する必要があるため、
            # クロージャで双方向バインディングする（Launcher インスタンス生成前に
            # コールバックを作る必要がある一方、コールバックは Launcher のメソッドを呼ぶ）。
            # ``list[Launcher | None] = [None]`` で初期化し、参照時 assert で
            # 未初期化（将来スレッド化した場合の race）を fail-fast に検出する。
            launcher_ref: list[Launcher | None] = [None]

            def _get_launcher() -> Launcher:
                # python -O で assert が strip されるケースに備え明示 raise。
                instance = launcher_ref[0]
                if instance is None:
                    raise RuntimeError("launcher accessed before initialization")
                return instance

            launcher = Launcher(
                config=config,
                config_path=config_path,
                on_run_pdf_merge=_make_phase_a_callback(config_path),
                on_open_settings=_make_settings_callback(
                    config_path, _get_launcher
                ),
            )
            launcher_ref[0] = launcher
            launcher.run()
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
