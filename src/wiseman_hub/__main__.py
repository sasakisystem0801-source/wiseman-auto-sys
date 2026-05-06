"""エントリポイント: python -m wiseman_hub で実行。

既定ではランチャー GUI を起動する。`--rpa` 指定時は従来の RPA パイプライン
（WisemanHub）を実行する（Wiseman 起動 → CSV 抽出 → GCS アップロード）。
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import tkinter as tk

    from wiseman_hub.config import AppConfig

logger = logging.getLogger(__name__)


def _default_config_path() -> Path:
    """既定の config/default.toml の絶対パスを返す。

    exe 配布（PyInstaller onefile）のショートカット起動等で CWD が
    別ディレクトリになるケースを考慮し、優先順位は以下:
    1. ``WISEMAN_HUB_CONFIG`` 環境変数（運用側で明示指定）
    2. frozen 実行時: ``sys.executable`` と同階層の ``config/default.toml``
    3. 通常実行: ソースツリー相対 ``config/default.toml`` （CWD = プロジェクトルート前提）

    frozen 時に CWD 相対で解決すると、ショートカットの "Start in" 未設定や
    別ディレクトリからの起動で空設定が読み込まれる致命バグになる（Codex HIGH 指摘）。
    """
    override = os.environ.get("WISEMAN_HUB_CONFIG")
    if override:
        return Path(override)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "config" / "default.toml"
    return Path("config/default.toml")


class _LauncherLike(Protocol):
    """``_make_settings_callback`` が必要とする Launcher の最小インターフェース。

    import 循環と Tk 依存を避けるため Protocol で表現し、Launcher 実体を直接
    参照しない（テストで FakeLauncher を差し替えやすくする副次効果もある）。
    """

    def reload_config(self, config: AppConfig) -> None: ...

    def get_root(self) -> tk.Misc: ...


def _make_facility_merger_callback(
    config_path: Path,
    get_launcher: Callable[[], _LauncherLike],
) -> Callable[[], None]:
    """Launcher に注入する「事業所フォルダ一括結合」コールバックを組み立てる（W5）。

    新ダイアログ ``FacilityRootManagerDialog`` を起動する。ルートフォルダを
    選択するだけで配下の事業所を自動検出し、チェックボックス UI で
    一括 / 選択処理ができる。ルート設定は TOML に永続化される。

    旧 ``FacilityMergerDialog``（単一事業所モーダル）は ``ui.facility_merger_dialog``
    にコード資産として残置するが、ランチャーからの UI 経路はこちらに統一する。
    新ダイアログは事業所が 1 つしかないルートでも動作するため機能上の劣化はない。
    """

    def open_facility_root_manager() -> None:
        from wiseman_hub.config import load_config
        from wiseman_hub.ui.facility_root_dialog import FacilityRootManagerDialog

        launcher = get_launcher()
        # 設定 GUI で root 変更後にも追随する（13B/13C と同じパターン）
        config = load_config(config_path)
        dialog = FacilityRootManagerDialog(
            parent=launcher.get_root(),
            config=config,
            config_path=config_path,
        )
        # モーダル待機
        dialog.get_toplevel().wait_window()
        # ダイアログで root_dir 等が変更されている可能性 → Launcher を新設定で再ロード
        try:
            updated = load_config(config_path)
        except (OSError, ValueError, TypeError) as exc:
            logger.warning(
                "load_config after facility_root dialog failed: %s",
                type(exc).__name__,
            )
            return
        launcher.reload_config(updated)

    return open_facility_root_manager


def _make_ex_extractor_callback(
    config_path: Path,
    get_launcher: Callable[[], _LauncherLike],
) -> Callable[[], None]:
    """Launcher に注入する「ex_ ファイル変換 + 振り分け」コールバックを組み立てる（PR4）。

    ``ExExtractorDialog`` を起動。Wiseman ダウンロードの ``.ex_`` ファイルを SFX
    抽出 + 事業所サブフォルダへ振り分ける。AMBIGUOUS / UNMATCHED は手動振り分け
    UI で確定 (Codex HIGH-3 対応で確定前確認ステップあり)。

    Windows 専用機能のため、macOS では ``UnsupportedSfxPlatformError`` がモーダル
    表示される (PR3 ``WindowsSfxAdapter`` constructor で fail-fast)。
    """

    def open_ex_extractor() -> None:
        from tkinter import messagebox

        from wiseman_hub.config import load_config
        from wiseman_hub.pdf.ex_extractor import (
            UnsupportedSfxPlatformError,
            WindowsSfxAdapter,
        )
        from wiseman_hub.ui.ex_extractor_dialog import ExExtractorDialog

        launcher = get_launcher()
        config = load_config(config_path)

        # adapter は dialog 起動前に構築 (macOS なら即座にエラーを出す)
        # MEDIUM-1 (code-reviewer C-2): parent= 指定で Launcher への transient 化
        try:
            adapter = WindowsSfxAdapter()
        except UnsupportedSfxPlatformError:
            messagebox.showerror(
                "Windows 専用機能",
                "ex_ ファイル変換は Windows 専用です (SFX 自己解凍 EXE 実行のため)。",
                parent=launcher.get_root(),
            )
            return

        dialog = ExExtractorDialog(
            parent=launcher.get_root(),
            config=config,
            config_path=config_path,
            adapter=adapter,
            # 取込元選択を TOML 永続化したら、Launcher の他 dialog
            # (settings / facility_root) が新値で動くように reload。
            # save 成功時のみ呼ばれる契約 (ExExtractorDialog._on_browse_source 側で保証)。
            on_source_persisted=launcher.reload_config,
        )
        dialog.get_toplevel().wait_window()

    return open_ex_extractor


def _make_checklist_b_callback(
    config_path: Path,
    get_launcher: Callable[[], _LauncherLike],
) -> Callable[[], None]:
    """Launcher に注入する「B: 運動機能向上計画書 自動配置」コールバック。"""

    def open_checklist_b() -> None:
        from wiseman_hub.config import load_config
        from wiseman_hub.ui.checklist_b_dialog import ChecklistBDialog

        launcher = get_launcher()
        config = load_config(config_path)
        dialog = ChecklistBDialog(
            parent=launcher.get_root(), config=config, config_path=config_path
        )
        dialog.get_toplevel().wait_window()
        # 設定が変更された可能性 → Launcher 側を再ロード
        try:
            updated = load_config(config_path)
            launcher.reload_config(updated)
        except (OSError, ValueError, TypeError):
            pass

    return open_checklist_b


def _make_checklist_c_callback(
    config_path: Path,
    get_launcher: Callable[[], _LauncherLike],
) -> Callable[[], None]:
    """Launcher に注入する「C: 経過報告書 自動配置」コールバック。"""

    def open_checklist_c() -> None:
        from wiseman_hub.config import load_config
        from wiseman_hub.ui.checklist_c_dialog import ChecklistCDialog

        launcher = get_launcher()
        config = load_config(config_path)
        dialog = ChecklistCDialog(
            parent=launcher.get_root(), config=config, config_path=config_path
        )
        dialog.get_toplevel().wait_window()
        try:
            updated = load_config(config_path)
            launcher.reload_config(updated)
        except (OSError, ValueError, TypeError):
            pass

    return open_checklist_c


def _make_settings_callback(
    config_path: Path,
    get_launcher: Callable[[], _LauncherLike],
) -> Callable[[], None]:
    """Launcher に注入する「設定」コールバックを組み立てる。

    設定保存成功時は ``Launcher.reload_config`` を呼び、以降の dialog (settings /
    facility_root / ex_extractor) が新値で動作するようにする（再起動不要）。
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


# RFC 6761 .invalid TLD: 名前解決が必ず失敗することが保証されている。
# smoke モードでは OcrClient.__init__ の引数バリデーションのみを検証し、
# 万が一 HTTP リクエストが発火しても外部に到達しないようガードする二重防御。
_SMOKE_OCR_ENDPOINT = "http://smoke.invalid/"
_SMOKE_OCR_API_KEY = "smoke-dummy"  # noqa: S105 — smoke 用ダミー、本物の credential ではない


def _run_smoke_test() -> None:
    """PyInstaller ビルドの hidden imports / DLL 解決を検証する smoke モード（Issue #80）。

    GUI を起動せず、本番経路で実 import が必要な以下を CLI から最小実行する:

    - ``fitz`` (pymupdf) のダミー PDF 生成・読込（Phase A/B の split/merge 基盤）
    - ``pdf.splitter.split_pdf_with_bbox`` （Phase A の入口、ダミー PDF + bbox）
    - ``pdf.ocr_client.OcrClient.__init__`` （HTTP リクエストは投げない、init 経路のみ）
    - ``fitz.open(path)`` のファイルパス経路 round-trip （splitter は in-memory 経路、
      こちらはファイルパス経路で別の C 拡張パスを踏むため、PyInstaller の DLL 解決を
      重複検証する目的で残す）

    PII 防御: 例外発生時は ``type(e).__name__`` のみを stderr に出力する。本番経路の
    規律と一致させる（CLAUDE.md Definition of Done + ADR-014 PII 方針）。CI 側の
    デバッグ性は workflow の Process state / dist listing / PyInstaller warn-files
    出力で担保する（``build-windows-smoke.yml`` 参照）。

    GUI 副作用回避のため、``tkinter`` および UI モジュールは本関数では import しない
    （AC-2 の検証対象。関数内 import は意図的）。
    """
    import tempfile

    import fitz

    from wiseman_hub.config import OcrBackendConfig, UserNameBBox
    from wiseman_hub.pdf.ocr_client import OcrClient
    from wiseman_hub.pdf.splitter import split_pdf_with_bbox

    logger.info(
        "smoke test start: fitz / splitter / ocr_client / fitz.open round-trip 経路を検証"
    )

    try:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            dummy_pdf = tmp / "smoke.pdf"

            doc = fitz.open()
            try:
                page = doc.new_page(width=595, height=842)
                page.insert_text((50, 100), "smoke", fontsize=11)
                doc.save(str(dummy_pdf))
            finally:
                doc.close()

            bbox = UserNameBBox(x0=10.0, y0=10.0, x1=200.0, y1=80.0, dpi=72)
            pages = split_pdf_with_bbox(dummy_pdf, bbox)
            if len(pages) != 1:
                raise RuntimeError(
                    f"split_pdf_with_bbox: expected 1 page, got {len(pages)}"
                )

            # _make_phase_a_callback の ExitStack パターンと整合する形で
            # OcrClient を context manager 化し、将来の拡張時にもリークを防ぐ。
            with OcrClient(
                OcrBackendConfig(
                    endpoint_url=_SMOKE_OCR_ENDPOINT,
                    api_key=_SMOKE_OCR_API_KEY,
                )
            ):
                pass

            # fitz.open(str(path)) のファイルパス経路を独立検証
            # （splitter は内部で fitz.open(Path) を踏む in-memory 経路。
            # こちらはファイルパス経由で異なる C 拡張入口を踏み、
            # PyInstaller の DLL 解決の網羅性を上げる）。
            doc2 = fitz.open(str(dummy_pdf))
            try:
                if doc2.page_count != 1:
                    raise RuntimeError(
                        f"fitz.open round-trip: expected 1 page, got {doc2.page_count}"
                    )
            finally:
                doc2.close()
    except Exception as exc:
        sys.stderr.write(f"smoke test failed: {type(exc).__name__}\n")
        sys.exit(1)

    logger.info("smoke test passed")


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
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help=(
            "PyInstaller ビルド検証用 smoke モード。GUI を起動せず、PDF split / "
            "OCR client init / fitz.open の最小経路を実行して exit する "
            "（CI で hidden imports と DLL 解決を検証する用途、Issue #80）"
        ),
    )
    args = parser.parse_args()

    if args.smoke_test:
        _run_smoke_test()
        return

    # Issue #64: --config で明示指定されたパスが存在しない場合、
    # load_config は空の AppConfig を返すため全設定未入力扱いになる。
    # ユーザー困惑を避けるため警告ログで事前通知する。
    if args.config is not None and not args.config.exists():
        logger.warning(
            "--config path does not exist: %s (using empty config, "
            "all settings will appear unconfigured)",
            args.config,
        )

    try:
        if args.rpa:
            from wiseman_hub.app import WisemanHub

            try:
                hub = WisemanHub(config_path=args.config)
            except (OSError, ValueError, TypeError):
                # Issue #150: WisemanHub.__init__ 内で actionable な logger.error を
                # 出力済み。CLI 経路 (--rpa) で setup 失敗したことを別 logger
                # (`__main__`) でも残し、launcher 経路と非対称にならないようにする
                # (どちらの経路で失敗したかを log だけで識別可能にする)。
                # exit code 2 = config error (runtime error 1 と区別、setup-time 問題)。
                logger.error(
                    "RPA 起動失敗: 設定エラーで中止 (config=%s)", args.config
                )
                sys.exit(2)
            hub.run()
        else:
            from wiseman_hub.config import load_config
            from wiseman_hub.ui.launcher import Launcher

            config_path = (
                args.config if args.config is not None else _default_config_path()
            )
            try:
                config = load_config(config_path)
            except (OSError, ValueError, TypeError) as exc:
                # Issue #150: launcher 経路でも RPA 経路と同様に actionable な
                # exit を行う。WisemanHub.__init__ を経由しないため logger.error
                # を直接発火する（フィールド情報 + config_path を 1 行で残し、
                # `_validate_facility_aliases` の PII フリーメッセージは exc str 化
                # で安全に出せる）。
                logger.error(
                    "設定ファイル読込エラー (config=%s): %s: %s",
                    config_path,
                    type(exc).__name__,
                    exc,
                )
                sys.exit(2)

            # ADR-016 Phase 2: audit log の GCS upload を起動時 + 5 分間隔で実行。
            # 起動条件未達（GCP 未設定 / SA キー不在 / log_dir 未設定）の場合は
            # warning ログを出して thread を起動せず、ローカル append は継続する
            # （audit 機能の degradation は許容、業務継続を優先）。
            from wiseman_hub.cloud.audit_uploader import start_audit_uploader

            start_audit_uploader(config.log_dir, config.gcp)
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

            # Issue #154: 旧ワークフロー UI 経路 (PDF マージ処理 / 確認待ちセッション)
            # の callback 注入を除去。pdf/pipeline.run_phase_a / run_phase_b と
            # ui/session_picker / confirm_dialog は ADR-013 方針でコード資産として残置。
            launcher = Launcher(
                config=config,
                config_path=config_path,
                on_open_settings=_make_settings_callback(
                    config_path, _get_launcher
                ),
                on_open_facility_merger=_make_facility_merger_callback(
                    config_path, _get_launcher
                ),
                on_open_ex_extractor=_make_ex_extractor_callback(
                    config_path, _get_launcher
                ),
                on_open_checklist_b=_make_checklist_b_callback(
                    config_path, _get_launcher
                ),
                on_open_checklist_c=_make_checklist_c_callback(
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
