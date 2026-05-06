"""C (経過報告書) 配置のドライラン CLI（実機検証用）。

GUI の「配置を実行」は PENDING 全件を一括 PDF 化するため、初回検証や
担当者ごとの段階リリースでは粒度が粗すぎる。本スクリプトは:

    1. ドライラン（既定）: 計画を表示するだけで PDF 生成しない（Excel COM 起動不要）
    2. --staff NAME: 特定担当者のみに絞って計画表示
    3. --execute-one N: フィルタ後 PENDING の N 番目を 1 件だけ実 PDF 化
       （上書き確認プロンプト + audit log 記録）

設計方針:
    既存 ``execute_c_placement`` を変更せず、別 CLI として追加する。GUI 全件一括
    の挙動は不変。``checklist_b_dryrun.py`` のパターン踏襲 + C 特有の
    Excel COM 利用と --staff フィルタを追加した派生形。

実行例（Windows 実機 PowerShell）:
    cd $HOME\\Projects\\wiseman-auto-sys

    # ドライラン全件（PDF 生成なし）
    uv run python scripts/checklist_c_dryrun.py 26年3月

    # 担当者「宮下」のみ計画表示
    uv run python scripts/checklist_c_dryrun.py 26年3月 --staff 宮下

    # 担当者「宮下」フィルタ後 PENDING の 0 番目を 1 件 PDF 化
    uv run python scripts/checklist_c_dryrun.py 26年3月 --staff 宮下 --execute-one 0
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from wiseman_hub.cloud.sheets import (
    download_xlsx,
    parse_sheet,
    select_c_rows,
)
from wiseman_hub.config import load_config
from wiseman_hub.pdf.checklist_c import (
    CPlacementResult,
    CPlacementStatus,
    execute_c_placement,
    plan_c_placement,
)
from wiseman_hub.pdf.excel_com import create_exporter
from wiseman_hub.utils.text_norm import normalize_lookup_key

_SHEET_RE = re.compile(r"^(\d{2})年(\d{1,2})月$")


def _resolve_config_path(arg: str | None) -> Path | None:
    if arg:
        return Path(arg)
    env = os.environ.get("WISEMAN_HUB_CONFIG")
    if env:
        return Path(env)
    return None  # load_config が config/default.toml を解決


def _confirm(prompt: str) -> bool:
    """yes 完全一致のみ True。EOF / Ctrl+C はキャンセル扱い（traceback を出さない）。"""
    try:
        return input(prompt).strip().lower() == "yes"
    except (EOFError, KeyboardInterrupt):
        print("\n  キャンセル (入力中断)", file=sys.stderr)
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="C 配置ドライラン + 1 件実行")
    ap.add_argument("sheet_name", help='対象シート名（例: "26年3月"）')
    ap.add_argument(
        "--staff",
        default=None,
        help=(
            "特定担当者のみフィルタ（normalize_lookup_key 適用後で一致、"
            "全角/半角空白・括弧の表記揺れ吸収。例: 宮下）"
        ),
    )
    ap.add_argument(
        "--execute-one",
        type=int,
        default=None,
        metavar="N",
        help="フィルタ後 PENDING の N 番目（0-origin）を 1 件だけ実 PDF 化",
    )
    ap.add_argument(
        "--config",
        default=None,
        help="config TOML のパス（省略時は WISEMAN_HUB_CONFIG or config/default.toml）",
    )
    args = ap.parse_args()

    # C-1: 非 Windows での --execute-one は MockExcelExporter が 41 byte の
    # 偽 PDF を NAS に書き込む silent success リスクがある（PR #193 Hotfix
    # の対象とは別経路）。Windows 実機運用前提のため早期 abort する。
    if args.execute_one is not None and sys.platform != "win32":
        print(
            f"ERROR: --execute-one は Windows 実機でのみ実行可能 "
            f"(現在 platform={sys.platform})。"
            "macOS/Linux ではドライランモード（--execute-one 省略）で実行してください。",
            file=sys.stderr,
        )
        return 2

    m = _SHEET_RE.match(args.sheet_name)
    if not m:
        print(
            f"ERROR: sheet_name format invalid: {args.sheet_name!r}",
            file=sys.stderr,
        )
        print(
            '       期待形式: "{2 桁年}年{1-2 桁月}月" (例: "26年3月", "26年12月")',
            file=sys.stderr,
        )
        return 1
    year = 2000 + int(m.group(1))
    month = int(m.group(2))
    if not (1 <= month <= 12):
        print(
            f"ERROR: month が範囲外: {month} (期待: 1-12)",
            file=sys.stderr,
        )
        return 1

    config_path = _resolve_config_path(args.config)
    try:
        config = load_config(config_path)
    except (OSError, ValueError, TypeError) as exc:
        print(
            f"ERROR: 設定ファイル読込失敗 (config={config_path}): "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 2

    if not config.checklist.spreadsheet_id:
        print(
            "ERROR: checklist.spreadsheet_id が未設定です",
            file=sys.stderr,
        )
        return 2

    print(
        f"Downloading spreadsheet "
        f"(id={config.checklist.spreadsheet_id[:8]}...)"
    )
    try:
        xlsx = download_xlsx(config.gcp, config.checklist.spreadsheet_id)
        rows = parse_sheet(xlsx, args.sheet_name)
        c_rows = select_c_rows(rows)
    except (OSError, ValueError) as exc:
        print(
            f"ERROR: スプレッドシート取得/解析失敗: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        print(
            "       SA キー / spreadsheet_id / シート名を確認してください。",
            file=sys.stderr,
        )
        return 2
    print(f"C 対象行: {len(c_rows)} 件")

    results = plan_c_placement(c_rows, config.checklist, year, month)

    status_count: dict[str, int] = {}
    for r in results:
        status_count[r.status.value] = status_count.get(r.status.value, 0) + 1
    print("\n=== status 集計（全 c_rows）===")
    for s in sorted(status_count.keys()):
        print(f"  {s}: {status_count[s]}")

    pending: list[tuple[int, CPlacementResult]] = [
        (i, r) for i, r in enumerate(results) if r.status == CPlacementStatus.PENDING
    ]
    if args.staff:
        # S-1: plan_c_placement は normalize_lookup_key で担当者マッチングするため
        # CLI フィルタも同じ正規化を使う（全角/半角空白等の表記揺れ吸収）。
        target_key = normalize_lookup_key(args.staff)
        pending = [
            (i, r) for i, r in pending
            if normalize_lookup_key(r.row.staff) == target_key
        ]
        print(f"\n担当者「{args.staff}」フィルタ後 PENDING: {len(pending)} 件")
    else:
        print(f"\nPENDING（実配置可能）: {len(pending)} 件")

    if not pending:
        print("\n配置可能な行がありません")
        return 0

    print("\n=== PENDING 行（実配置前の計画）===")
    for n, (orig_idx, r) in enumerate(pending):
        print(f"\n[{n}] (results idx {orig_idx})")
        print(f"  氏名:       {r.row.name}")
        print(f"  居宅:       {r.row.facility}")
        print(f"  担当:       {r.row.staff}")
        print(f"  xlsx パス:  {r.xlsx_path}")
        print(f"  シート名:   {r.sheet_name}")
        print(f"  target PDF: {r.target_pdf}")

    if args.execute_one is None:
        print(
            "\n(ドライランモード: --execute-one N で N 番目を 1 件だけ実 PDF 化可能)"
        )
        return 0

    n = args.execute_one
    if n < 0 or n >= len(pending):
        print(
            f"\nERROR: --execute-one {n} は範囲外 (0-{len(pending) - 1})"
        )
        return 1

    _, target_result = pending[n]
    if target_result.target_pdf is None or target_result.xlsx_path is None:
        print(
            "\nERROR: target_pdf / xlsx_path が None (PENDING で本来発生しない)"
        )
        return 1

    print(f"\n=== 実配置候補 [{n}] ===")
    print(f"  氏名:       {target_result.row.name}")
    print(f"  居宅:       {target_result.row.facility}")
    print(f"  担当:       {target_result.row.staff}")
    print(f"  xlsx パス:  {target_result.xlsx_path}")
    print(f"  シート名:   {target_result.sheet_name}")
    print(f"  target PDF: {target_result.target_pdf}")
    if not _confirm("  実 PDF 化 + NAS 配置しますか？ ('yes' のみ実行): "):
        print("  キャンセルしました")
        return 0

    try:
        target_exists = target_result.target_pdf.exists()
    except OSError as exc:
        print(
            f"ERROR: NAS 到達不能 ({type(exc).__name__}): {exc}",
            file=sys.stderr,
        )
        return 2
    if target_exists and not _confirm(
        f"  target が既に存在します ({target_result.target_pdf.name})。"
        "上書きしますか？ ('yes' のみ): "
    ):
        print("  上書きキャンセル")
        return 0

    print("\n=== Excel COM exporter 起動中... ===")
    try:
        exporter = create_exporter()
    except (OSError, RuntimeError, ImportError) as exc:
        print(
            f"ERROR: Excel COM exporter 起動失敗: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        print(
            "       Excel が実機にインストールされ、pywin32 が利用可能か確認してください",
            file=sys.stderr,
        )
        return 2

    try:
        execute_c_placement(
            [target_result],
            exporter,
            log_dir=config.log_dir,
            dry_run=False,
        )
    except Exception as exc:  # noqa: BLE001  (CLI top-level guard, PII 配慮で type 名のみ表示)
        print(
            f"\n  ❌ 配置処理が異常終了: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 3

    if target_result.status == CPlacementStatus.SUCCESS:
        print(f"\n  ✅ 配置完了: {target_result.target_pdf}")
        return 0
    print(
        f"\n  ❌ 配置失敗: status={target_result.status.value}, "
        f"message={target_result.message}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
