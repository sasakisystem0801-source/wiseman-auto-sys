"""エントリポイント: python -m wiseman_hub で実行。

既定ではランチャー GUI を起動する。`--rpa` 指定時は従来の RPA パイプライン
（WisemanHub）を実行する（Wiseman 起動 → CSV 抽出 → GCS アップロード）。
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import tkinter as tk

    from wiseman_hub.config import AppConfig
    from wiseman_hub.pdf.review_flow import ReviewOutcome
    from wiseman_hub.ui.launcher import ReviewCallbackResult

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


def _make_review_callback(
    config_path: Path,
    get_launcher: Callable[[], _LauncherLike],
) -> Callable[[], ReviewCallbackResult]:
    """Launcher に注入する「確認待ちセッション」コールバックを組み立てる。

    main thread で以下を実行して ``ReviewCallbackResult`` を返す:
      1. ``SessionPicker`` で NEEDS_REVIEW / READY_TO_MERGE セッションを選択
      2. NEEDS_REVIEW なら ``resolve_review_session`` に dialog + transition を委譲
      3. READY_TO_MERGE ならそのまま session_id を返す
      4. cancel / 未解決 / エラーは ``CANCEL_RESULT``（should_phase_b False）

    Phase B の実体は Launcher が worker thread で呼ぶ ``on_run_phase_b`` に委譲する。
    flow 本体は Issue #72 で CLI と共通化（``pdf/review_flow.py``）。
    """
    from wiseman_hub.ui.launcher import CANCEL_RESULT, ReviewCallbackResult

    def open_review() -> ReviewCallbackResult:
        from tkinter import messagebox

        from wiseman_hub.config import load_config
        from wiseman_hub.pdf.review_flow import resolve_review_session
        from wiseman_hub.pdf.session import SessionStatus
        from wiseman_hub.ui.confirm_dialog import ConfirmDialog
        from wiseman_hub.ui.session_picker import SessionPicker

        launcher = get_launcher()

        try:
            config = load_config(config_path)
        except (OSError, ValueError, TypeError) as exc:
            logger.error(
                "load_config failed before review: %s", type(exc).__name__
            )
            messagebox.showerror(
                "設定ファイル読込エラー",
                "設定ファイルを読み込めませんでした。詳細はログを確認してください。"
                f"\n\n{type(exc).__name__}",
            )
            return CANCEL_RESULT

        sessions_dir = Path(config.pdf_merge.output_dir) / ".sessions"
        parent = launcher.get_root()

        picker = SessionPicker(sessions_dir=sessions_dir, parent=parent)
        pick = picker.run()
        if not pick.selected:
            return CANCEL_RESULT
        assert pick.session_id is not None  # Protocol 契約
        session_id = pick.session_id

        if pick.status == SessionStatus.READY_TO_MERGE:
            return ReviewCallbackResult(session_id=session_id)

        # NEEDS_REVIEW: ConfirmDialog + 2 段階ロックによる race safe な遷移を
        # resolve_review_session に委譲する（CLI 側と共通、Issue #72）。
        # parent は closure で捕捉して ConfirmDialog に渡す（Toplevel modal 化）。
        from wiseman_hub.pdf.session import Session

        def dialog_factory(
            session: Session, _sessions_dir: Path
        ) -> ConfirmDialog:
            return ConfirmDialog(session, _sessions_dir, parent=parent)

        # picker 選択後〜1st lock 取得前の race（他プロセスが --discard した等）で
        # resolve 内の load_session が SessionNotFoundError/Corrupted を raise する
        # 可能性がある（review_flow の「呼出側契約」）。messagebox 通知 + CANCEL に
        # マッピングしてアプリ全体終了を防ぐ。
        from wiseman_hub.pdf.session import (
            SessionCorruptedError,
            SessionNotFoundError,
        )

        try:
            outcome = resolve_review_session(
                session_id,
                sessions_dir,
                dialog_factory=dialog_factory,
            )
        except (SessionNotFoundError, SessionCorruptedError) as exc:
            logger.error(
                "session %s load failed before review: %s",
                session_id,
                type(exc).__name__,
            )
            messagebox.showerror(
                "セッション読込エラー",
                "選択したセッションが読み込めませんでした。"
                "他のプロセスが削除した可能性があります。"
                f"\n\n{type(exc).__name__}",
            )
            return CANCEL_RESULT
        return _review_outcome_to_callback_result(outcome)

    return open_review


def _review_outcome_to_callback_result(
    outcome: ReviewOutcome,
) -> ReviewCallbackResult:
    """``ReviewOutcome`` を ``ReviewCallbackResult`` + messagebox 通知へマッピング。

    adapter 境界を分離することで、各 reason を直接ユニットテストできる
    （Issue #97、pr-test-analyzer rating 8 対応）。

    ``assert_never`` により ``ReviewReason`` Literal に新値が追加されて本関数で
    未処理になった場合、mypy が compile-time エラーで検出する。
    """
    from tkinter import messagebox
    from typing import assert_never

    from wiseman_hub.ui.launcher import CANCEL_RESULT, ReviewCallbackResult

    reason = outcome.reason
    detail = outcome.detail or ""

    if reason == "ready_to_merge" or reason == "resolved":
        return ReviewCallbackResult(session_id=outcome.session_id)

    # aborted / unresolved: ConfirmDialog 側で既にユーザーに通知済み、または
    # 未解決残りはユーザーが自覚している状態。追加の messagebox は不要。
    if reason == "aborted" or reason == "unresolved":
        return CANCEL_RESULT

    if reason == "lock_error":
        messagebox.showerror(
            "セッション操作エラー",
            "別の処理がセッションを使用中です。しばらく待って再試行してください。"
            f"\n\n{detail}",
        )
        return CANCEL_RESULT

    if reason == "concurrent_modification":
        messagebox.showerror(
            "セッション競合",
            "別のプロセスがセッションを変更したため遷移を中止しました。"
            "「確認待ちセッション」から再度開いてください。",
        )
        return CANCEL_RESULT

    if reason == "transition_lock_error":
        messagebox.showerror(
            "セッション遷移エラー",
            "解決は保存済みですが ready_to_merge への遷移に失敗しました。"
            "再度「確認待ちセッション」を開いて続行してください。"
            f"\n\n{detail}",
        )
        return CANCEL_RESULT

    if reason == "invalid_transition" or reason == "invalid_status":
        messagebox.showerror(
            "セッション状態エラー",
            "セッションの状態が予期しないものです。ログを確認してください。"
            f"\n\n{detail}",
        )
        return CANCEL_RESULT

    assert_never(reason)


def _make_phase_b_callback(
    config_path: Path,
) -> Callable[[str], None]:
    """Launcher に注入する Phase B コールバックを組み立てる（13C、worker thread 呼出）。

    13B の Phase A と同様に TOML を再ロードしてから ``run_phase_b`` を呼ぶ（設定 GUI で
    output_dir を変えた直後にも対応）。worker thread で呼ばれるため Tk API には触れない。
    """

    def run_phase_b_callback(session_id: str) -> None:
        from wiseman_hub.config import load_config
        from wiseman_hub.pdf.pipeline import run_phase_b
        from wiseman_hub.pdf.session import load_session

        config = load_config(config_path)
        sessions_dir = Path(config.pdf_merge.output_dir) / ".sessions"
        output_path = (
            Path(config.pdf_merge.output_dir) / f"{session_id}_merged.pdf"
        )
        session = load_session(session_id, sessions_dir=sessions_dir)
        run_phase_b(
            session=session,
            config=config.pdf_merge,
            sessions_dir=sessions_dir,
            output_path=output_path,
        )

    return run_phase_b_callback


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

            WisemanHub(config_path=args.config).run()
        else:
            from wiseman_hub.config import load_config
            from wiseman_hub.ui.launcher import Launcher

            config_path = (
                args.config if args.config is not None else _default_config_path()
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
                on_open_review=_make_review_callback(
                    config_path, _get_launcher
                ),
                on_run_phase_b=_make_phase_b_callback(config_path),
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
