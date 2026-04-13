"""提供実績 .ex_ ファイル → PDF 変換 & サブフォルダ振り分けスクリプト。

Wiseman からダウンロードされた .ex_ ファイル（自己解凍EXE）を処理し、
PDF を抽出してファイル名に含まれる事業所名のサブフォルダに移動する。

使い方:
    # デフォルトパス（C:\\Users\\sasak\\OneDrive\\デスクトップ\\本田様）
    uv run python scripts/process_ex_files.py

    # パス指定
    uv run python scripts/process_ex_files.py "D:\\path\\to\\folder"

処理フロー:
    1. .ex_ ファイルを列挙
    2. ファイル名から振り分け先サブフォルダを特定
    3. .ex_ → .exe にコピー（元ファイルは保持）
    4. PDF を抽出（expand → 7-Zip → EXE実行 の順で試行）
    5. PDF をサブフォルダに移動
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path

if sys.platform != "win32":
    raise SystemExit("このスクリプトは Windows 専用です。")

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


def _snapshot_pdfs(directory: Path) -> set[Path]:
    """ディレクトリ内の PDF ファイル一覧を取得。"""
    return set(directory.glob("*.pdf")) | set(directory.glob("*.PDF"))


def _try_expand(ex_path: Path, work_dir: Path) -> list[Path]:
    """Windows 標準 expand コマンドで .ex_ を展開。"""
    before = _snapshot_pdfs(work_dir)
    exe_candidate = work_dir / ex_path.with_suffix(".exe").name
    try:
        result = subprocess.run(
            ["expand", str(ex_path), str(exe_candidate)],
            capture_output=True,
            timeout=30,
        )
        if result.returncode == 0 and exe_candidate.exists():
            # expand で .exe が得られた場合、その .exe を実行して PDF を得る
            new_pdfs = _run_exe_and_wait(exe_candidate, work_dir, before)
            exe_candidate.unlink(missing_ok=True)
            if new_pdfs:
                return new_pdfs
    except Exception as e:
        logger.debug("expand 失敗: %s", e)
    return []


def _try_7zip(exe_path: Path, work_dir: Path) -> list[Path]:
    """7-Zip で自己解凍 EXE から PDF を抽出。"""
    before = _snapshot_pdfs(work_dir)
    for sz in [
        Path(r"C:\Program Files\7-Zip\7z.exe"),
        Path(r"C:\Program Files (x86)\7-Zip\7z.exe"),
    ]:
        if not sz.exists():
            continue
        try:
            subprocess.run(
                [str(sz), "x", str(exe_path), f"-o{work_dir}", "-y", "-bso0"],
                capture_output=True,
                timeout=30,
            )
            new_pdfs = _snapshot_pdfs(work_dir) - before
            if new_pdfs:
                return list(new_pdfs)
        except Exception as e:
            logger.debug("7-Zip 失敗: %s", e)
    return []


def _run_exe_and_wait(
    exe_path: Path,
    watch_dir: Path,
    before: set[Path] | None = None,
) -> list[Path]:
    """EXE を実行し、新しい PDF ファイルの出現を待つ。"""
    if before is None:
        before = _snapshot_pdfs(watch_dir)
    try:
        proc = subprocess.Popen(
            [str(exe_path)],
            cwd=str(watch_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as e:
        logger.warning("EXE 実行失敗: %s", e)
        return []

    # PDF 出現を最大 15 秒待機
    for _ in range(30):
        time.sleep(0.5)
        new_pdfs = _snapshot_pdfs(watch_dir) - before
        if new_pdfs:
            # プロセスがまだ動いていたら終了させる
            proc.terminate()
            proc.wait(timeout=5)
            return list(new_pdfs)

    # タイムアウト — プロセスを終了
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()

    # 最後にもう一度チェック
    final = _snapshot_pdfs(watch_dir) - before
    return list(final)


def extract_pdf(ex_path: Path, work_dir: Path) -> list[Path]:
    """3段階フォールバックで .ex_ から PDF を抽出する。"""
    # 方法1: expand コマンド
    logger.info("  [1/3] expand コマンドを試行...")
    pdfs = _try_expand(ex_path, work_dir)
    if pdfs:
        logger.info("  → expand で PDF 取得成功")
        return pdfs

    # .exe コピーを作成（方法2, 3 で使用）
    exe_path = work_dir / ex_path.with_suffix(".exe").name
    if not exe_path.exists():
        shutil.copy2(ex_path, exe_path)

    # 方法2: 7-Zip 抽出
    logger.info("  [2/3] 7-Zip を試行...")
    pdfs = _try_7zip(exe_path, work_dir)
    if pdfs:
        exe_path.unlink(missing_ok=True)
        logger.info("  → 7-Zip で PDF 取得成功")
        return pdfs

    # 方法3: EXE を直接実行
    logger.info("  [3/3] EXE 直接実行を試行...")
    pdfs = _run_exe_and_wait(exe_path, work_dir)
    exe_path.unlink(missing_ok=True)
    if pdfs:
        logger.info("  → EXE 実行で PDF 取得成功")
        return pdfs

    logger.warning("  → 全方法で PDF 抽出に失敗")
    return []


def process_directory(base_dir: Path) -> int:
    """ベースディレクトリの .ex_ ファイルを処理する。"""
    if not base_dir.exists():
        logger.error("ディレクトリが見つかりません: %s", base_dir)
        return 1

    # サブフォルダ一覧
    subfolders = [d.name for d in base_dir.iterdir() if d.is_dir() and not d.name.startswith("_")]
    logger.info("サブフォルダ: %s", subfolders)

    # .ex_ ファイル一覧
    ex_files = sorted(base_dir.glob("*.ex_"))
    if not ex_files:
        logger.info("処理対象の .ex_ ファイルがありません")
        return 0

    logger.info("処理対象: %d ファイル", len(ex_files))

    # 一時作業ディレクトリ
    work_dir = base_dir / "_temp_extract"
    work_dir.mkdir(exist_ok=True)

    success: list[str] = []
    failed: list[tuple[str, str]] = []

    for ex_file in ex_files:
        logger.info("")
        logger.info("--- %s ---", ex_file.name)

        # 1. サブフォルダマッチ
        target_folder = find_subfolder_match(ex_file.name, subfolders)
        if not target_folder:
            logger.warning("  マッチするサブフォルダなし → スキップ")
            failed.append((ex_file.name, "サブフォルダ不一致"))
            continue
        logger.info("  振り分け先: %s", target_folder)

        # 2. PDF 抽出
        pdfs = extract_pdf(ex_file, work_dir)
        if not pdfs:
            failed.append((ex_file.name, "PDF 抽出失敗"))
            continue

        # 3. PDF をサブフォルダに移動
        dest_dir = base_dir / target_folder
        for pdf in pdfs:
            dest = dest_dir / pdf.name
            if dest.exists():
                logger.warning("  上書き: %s", dest.name)
            shutil.move(str(pdf), str(dest))
            logger.info("  → 移動完了: %s/%s", target_folder, pdf.name)

        success.append(ex_file.name)

    # 一時ディレクトリ削除
    shutil.rmtree(work_dir, ignore_errors=True)

    # サマリー
    logger.info("")
    logger.info("=" * 50)
    logger.info("成功: %d / 失敗: %d / 合計: %d", len(success), len(failed), len(ex_files))
    for name, reason in failed:
        logger.info("  ✗ %s: %s", name, reason)
    if not failed:
        logger.info("=== ALL GREEN ===")

    return 1 if failed else 0


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DIR
    logger.info("対象ディレクトリ: %s", target)
    return process_directory(target)


if __name__ == "__main__":
    sys.exit(main())
