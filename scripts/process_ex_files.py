"""提供実績 .ex_ ファイル → PDF 変換 & サブフォルダ振り分けスクリプト。

Wiseman からダウンロードされた .ex_ ファイル（WinSFX32 LZH 自己解凍EXE）を処理し、
PDF を抽出してファイル名に含まれる事業所名のサブフォルダに移動する。

使い方:
    # デフォルトパス（C:\\Users\\sasak\\OneDrive\\デスクトップ\\本田様）
    uv run python scripts/process_ex_files.py

    # パス指定
    uv run python scripts/process_ex_files.py "D:\\path\\to\\folder"

処理フロー:
    1. .ex_ ファイルを列挙
    2. ファイル名から振り分け先サブフォルダを特定
    3. .ex_ → .exe にコピー（元の .ex_ ファイルと同じディレクトリ）
    4. EXE を実行し、WinSFX32 ダイアログの OK を自動クリック
    5. 生成された PDF をサブフォルダに移動
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_DIR = Path(r"C:\Users\sasak\OneDrive\デスクトップ\本田様")


def find_subfolder_match(filename: str, subfolders: list[str]) -> str | None:
    """ファイル名に含まれる事業所名からマッチするサブフォルダを探す。"""
    for folder in subfolders:
        if folder in filename:
            return folder
    return None


def _snapshot_pdfs(*directories: Path) -> set[Path]:
    """複数ディレクトリの PDF ファイル一覧を取得。"""
    pdfs: set[Path] = set()
    for d in directories:
        if d.exists():
            pdfs |= set(d.glob("*.pdf")) | set(d.glob("*.PDF"))
    return pdfs


def _terminate_proc(proc: subprocess.Popen[bytes]) -> None:
    """プロセスを確実に終了させる。"""
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _click_sfx_dialog(proc_pid: int) -> bool:
    """WinSFX32 ダイアログの OK ボタンを自動クリックする。

    2つの方法を試す:
    1. pywinauto.Application().connect(process=pid) でプロセスに直接接続
    2. Desktop スキャンでウィンドウタイトルを検索
    """
    try:
        from pywinauto import Application  # type: ignore[import-untyped]

        # 方法1: プロセスPIDで直接接続
        try:
            app = Application(backend="uia").connect(process=proc_pid, timeout=3)
            dlg = app.top_window()
            title = dlg.window_text()
            logger.info("  → ダイアログ検出 (PID %d): %s", proc_pid, title)

            # OK ボタンを探してクリック
            for btn_title in ["OK", "OK(O)", "&OK"]:
                try:
                    btn = dlg.child_window(title=btn_title, control_type="Button")
                    if btn.exists(timeout=1):
                        btn.click_input()
                        logger.info("  → OK クリック完了")
                        return True
                except Exception:
                    continue

            # title_re でも試す
            try:
                btn = dlg.child_window(title_re=r".*OK.*", control_type="Button")
                if btn.exists(timeout=1):
                    btn.click_input()
                    logger.info("  → OK クリック完了 (regex)")
                    return True
            except Exception:
                pass

            # ボタンが見つからない場合、Enter キーを送信
            try:
                dlg.type_keys("{ENTER}")
                logger.info("  → Enter 送信で代替")
                return True
            except Exception as e:
                logger.debug("  Enter 送信失敗: %s", e)

        except Exception as e:
            logger.debug("  PID接続失敗: %s", e)

    except ImportError:
        logger.warning("pywinauto 未インストール — ダイアログ自動操作不可")
    except Exception as e:
        logger.debug("SFX ダイアログ操作失敗: %s", e)
    return False


def _extract_with_exe(
    exe_path: Path,
    watch_dirs: list[Path],
) -> list[Path]:
    """自己解凍 EXE を実行し、WinSFX32 ダイアログを自動操作して PDF を取得する。"""
    before = _snapshot_pdfs(*watch_dirs)

    try:
        proc = subprocess.Popen(
            [str(exe_path)],
            cwd=str(exe_path.parent),
        )
    except OSError as e:
        logger.warning("  EXE 実行失敗: %s", e)
        return []

    dialog_clicked = False

    try:
        for i in range(60):  # 最大 30 秒
            time.sleep(0.5)

            # 1-3秒後にダイアログを操作
            if not dialog_clicked and 2 <= i <= 20:
                dialog_clicked = _click_sfx_dialog(proc.pid)

            # PDF チェック
            new_pdfs = _snapshot_pdfs(*watch_dirs) - before
            if new_pdfs:
                logger.info("  → PDF 検出: %s", [p.name for p in new_pdfs])
                return list(new_pdfs)

            # プロセスが終了していたら少し待ってからチェック
            if proc.poll() is not None:
                time.sleep(1)
                new_pdfs = _snapshot_pdfs(*watch_dirs) - before
                if new_pdfs:
                    logger.info("  → PDF 検出 (プロセス終了後): %s", [p.name for p in new_pdfs])
                return list(new_pdfs)
    finally:
        if proc.poll() is None:
            _terminate_proc(proc)

    return list(_snapshot_pdfs(*watch_dirs) - before)


def process_single_file(
    ex_file: Path,
    base_dir: Path,
    target_folder: str,
) -> bool:
    """1つの .ex_ ファイルを処理する。"""
    # .exe コピーを元ファイルと同じ場所に作成
    exe_path = ex_file.with_suffix(".exe")
    logger.info("  → .exe 作成: %s", exe_path.name)
    shutil.copy2(ex_file, exe_path)

    try:
        # PDF を監視するディレクトリ（元ファイルの場所 + サブフォルダ + temp 等）
        watch_dirs = [
            base_dir,  # .ex_ ファイルのある場所
            exe_path.parent,  # .exe のある場所（通常同じ）
            Path.home() / "Desktop",  # デスクトップ
            Path.home() / "Downloads",  # ダウンロード
        ]

        logger.info("  → EXE 実行 + SFX ダイアログ自動操作...")
        pdfs = _extract_with_exe(exe_path, watch_dirs)

        if not pdfs:
            logger.warning("  → PDF 抽出失敗")
            return False

        # PDF をサブフォルダに移動
        dest_dir = base_dir / target_folder
        for pdf in pdfs:
            dest = dest_dir / pdf.name
            if dest.exists():
                logger.warning("  上書き: %s", dest.name)
            shutil.move(str(pdf), str(dest))
            logger.info("  → 移動完了: %s/%s", target_folder, pdf.name)

        return True
    finally:
        exe_path.unlink(missing_ok=True)


def process_directory(base_dir: Path) -> int:
    """ベースディレクトリの .ex_ ファイルを処理する。"""
    if not base_dir.exists():
        logger.error("ディレクトリが見つかりません: %s", base_dir)
        return 1

    subfolders = [d.name for d in base_dir.iterdir() if d.is_dir() and not d.name.startswith("_")]
    logger.info("サブフォルダ: %s", subfolders)

    ex_files = sorted(base_dir.glob("*.ex_"))
    if not ex_files:
        logger.info("処理対象の .ex_ ファイルがありません")
        return 0

    logger.info("処理対象: %d ファイル", len(ex_files))

    success: list[str] = []
    failed: list[str] = []

    for ex_file in ex_files:
        logger.info("")
        logger.info("--- %s ---", ex_file.name)

        target_folder = find_subfolder_match(ex_file.name, subfolders)
        if not target_folder:
            logger.warning("  マッチするサブフォルダなし → スキップ")
            failed.append(ex_file.name)
            continue
        logger.info("  振り分け先: %s", target_folder)

        if process_single_file(ex_file, base_dir, target_folder):
            success.append(ex_file.name)
        else:
            failed.append(ex_file.name)

    logger.info("")
    logger.info("=" * 50)
    logger.info("成功: %d / 失敗: %d / 合計: %d", len(success), len(failed), len(ex_files))
    for name in failed:
        logger.info("  ✗ %s", name)
    if not failed:
        logger.info("=== ALL GREEN ===")

    return 1 if failed else 0


def main() -> int:
    if sys.platform != "win32":
        print("このスクリプトは Windows 専用です。", file=sys.stderr)
        return 1
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DIR
    logger.info("対象ディレクトリ: %s", target)
    return process_directory(target)


if __name__ == "__main__":
    sys.exit(main())
