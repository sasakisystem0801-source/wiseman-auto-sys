"""提供実績 .ex_ ファイル → PDF 変換 & 事業所サブフォルダ振り分け CLI (薄ラッパー)。

PR3 で本体実装は ``src/wiseman_hub/pdf/ex_extractor.py`` に移動し、本スクリプトは
**CLI インターフェース互換** (argv パターン / デフォルトパス / stderr フォーマット)
を維持しつつ extract_directory を呼び出すだけの薄ラッパーとなった。

## 旧版との挙動差分 (重要)

旧版は ``find_subfolder_match`` (filename 単純包含のみ) で振り分けていたが、本版は
**PR2 ``resolve_facility``** (alias 優先 + 語境界要求 + AMBIGUOUS 細分) に統一。
これにより誤配布リスクは構造的に低減するが、旧版で当たっていた一部のファイルが
AMBIGUOUS / UNMATCHED に落ち、自動振り分けされず stderr に列挙される可能性がある。

## CLI 終了コード

| code | 意味 | 旧版 |
|------|------|------|
| 0 | 全件 SUCCESS | 同 (失敗 0 件) |
| 2 | 一部 pending (AMBIGUOUS / UNMATCHED が存在) | **新規** |
| 1 | 失敗あり (EXTRACT_FAILED / MOVE_FAILED / PARTIAL_OUTPUT) または致命的エラー | 同 |

旧版は 0/1 のみだったが、PR3 で「pending あり」は失敗とは別の状態として
exit code 2 で明示する (現場運用で「振り分け止まり」を検知しやすくするため)。

## 使い方

```sh
# デフォルトパス (C:\\Users\\sasak\\OneDrive\\デスクトップ\\本田様)
uv run python scripts/process_ex_files.py

# パス指定
uv run python scripts/process_ex_files.py "D:\\path\\to\\folder"
```

ADR-014 参照。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from wiseman_hub.pdf.ex_extractor import (
    ExtractionResult,
    UnsupportedSfxPlatformError,
    WindowsSfxAdapter,
    extract_directory,
)

# logging.basicConfig は main() 内で呼ぶ (import 時 root logger 上書きを防ぐ、
# pytest 並列実行 / PR4 UI からの import で他の log capture を破壊しないため)
logger = logging.getLogger(__name__)

DEFAULT_DIR = Path(r"C:\Users\sasak\OneDrive\デスクトップ\本田様")


EXIT_OK = 0
EXIT_FAILED = 1
EXIT_PENDING = 2


def _print_summary(result: ExtractionResult) -> None:
    """集計サマリを logger 経由 (stderr) で出力 (現場運用の視認性維持)。

    PII 防御: filename のみ出力、事業所名 / 移動先パス / candidates は出さない
    (PR4 UI で表示)。orphan_alias_canonicals は alias 設定不整合の通知用に
    canonical 名を出力する必要があるため例外的に出すが、運用ドキュメントで
    ログ取り扱いを明記すること (Codex / evaluator 指摘 MEDIUM)。
    """
    total = len(result.items)
    success = result.success_count
    pending = len(result.pending_manual)
    failed = len(result.failed)

    logger.info("=" * 50)
    logger.info(
        "成功: %d / 手動振り分け待ち: %d / 失敗: %d / 合計: %d",
        success,
        pending,
        failed,
        total,
    )

    # AC-3 / Codex HIGH-F: pending 件数を専用行で明示し
    # 現場運用で「振り分け止まり」を即座に検知可能にする
    if pending > 0:
        logger.warning("⚠️  手動振り分け待ち: %d 件 (自動振り分けされていません)", pending)

    if result.pending_filenames:
        logger.warning("--- 手動振り分け待ち ---")
        for name in result.pending_filenames:
            logger.warning("  ? %s", name)
        logger.warning(
            "上記ファイルは PR4 UI 完成までの暫定として、"
            "手動で各事業所サブフォルダへ移動してください。"
        )

    if result.failed:
        logger.error("--- 失敗 ---")
        for item in result.failed:
            code_str = item.error_code.value if item.error_code else "unknown"
            logger.error("  x %s [%s]", item.source_path.name, code_str)
            # HIGH-A: 部分移動済 PDF を運用者へ可視化 (件数のみ、移動先は出さない)
            if item.partially_moved:
                logger.error(
                    "    (一部 PDF は移動済み: %d 件、移動先フォルダを確認してください)",
                    len(item.partially_moved),
                )

    # HIGH-G / M-1: cleanup_warning は failed と独立に表示 (primary が SUCCESS でも残る)
    cleanup_warned = [
        item for item in result.items if item.cleanup_warning is not None
    ]
    if cleanup_warned:
        logger.warning("--- .exe ファイル削除失敗 (次回実行で衝突する可能性) ---")
        for item in cleanup_warned:
            logger.warning("  ! %s", item.source_path.name)

    if result.orphan_alias_canonicals:
        logger.warning("--- 設定不整合 (alias 設定だけ残り実フォルダ未存在) ---")
        for canonical in result.orphan_alias_canonicals:
            logger.warning("  ! %s", canonical)


def _exit_code(result: ExtractionResult) -> int:
    """結果から終了コードを決定 (1 > 2 > 0 の優先順)。"""
    if result.failed:
        return EXIT_FAILED
    if result.pending_manual:
        return EXIT_PENDING
    return EXIT_OK


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stderr,
    )

    if sys.platform != "win32":
        print("このスクリプトは Windows 専用です。", file=sys.stderr)
        return EXIT_FAILED

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DIR
    logger.info("対象ディレクトリ: %s", target)

    try:
        adapter = WindowsSfxAdapter()
    except UnsupportedSfxPlatformError as e:
        print(str(e), file=sys.stderr)
        return EXIT_FAILED

    try:
        # 旧版互換: source_dir == facility_root_dir (同一ディレクトリ運用)
        # PR4/5 で TOML 経由で別パス指定をサポート予定
        result = extract_directory(
            source_dir=target,
            facility_root_dir=target,
            aliases={},  # CLI では alias 未対応 (PR4 UI で TOML から渡す)
            adapter=adapter,
        )
    except FileNotFoundError as e:
        logger.error("%s", e)
        return EXIT_FAILED

    _print_summary(result)
    return _exit_code(result)


if __name__ == "__main__":
    sys.exit(main())
