"""B 配置のドライラン CLI（実機検証用）。

GUI の「実行」ボタンは PENDING 全件を一括コピーするため、初回検証では
リスクが高い。本スクリプトは:

    1. ドライラン（既定）: 計画を表示するだけで実コピーしない
    2. --execute-one N: PENDING 行の N 番目を **1 件のみ** 実コピー（確認プロンプト付き）

実行例（Windows 実機 PowerShell）:
    $env:WISEMAN_HUB_CONFIG = "$HOME\\wiseman-hub\\config\\default.toml"
    cd $HOME\\Projects\\wiseman-auto-sys

    # ドライラン（実コピーなし、計画のみ表示）
    uv run python scripts/checklist_b_dryrun.py 26年3月

    # 0 番目を 1 件だけ実コピー（confirm 後）
    uv run python scripts/checklist_b_dryrun.py 26年3月 --execute-one 0

過去失敗対策:
    既存 ``execute_placement`` を変更せず、別 CLI として追加。GUI 全件一括の
    挙動は不変。
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

from wiseman_hub.cloud.sheets import (
    download_xlsx,
    parse_sheet,
    select_b_rows,
)
from wiseman_hub.config import load_config
from wiseman_hub.pdf.checklist_b import (
    PlacementStatus,
    plan_b_placement,
)

_SHEET_RE = re.compile(r"^(\d{2})年(\d{1,2})月$")


def _resolve_config_path(arg: str | None) -> Path | None:
    if arg:
        return Path(arg)
    env = os.environ.get("WISEMAN_HUB_CONFIG")
    if env:
        return Path(env)
    return None  # load_config が config/default.toml を解決


def main() -> int:
    ap = argparse.ArgumentParser(description="B 配置ドライラン + 1 件実行")
    ap.add_argument("sheet_name", help='対象シート名（例: "26年3月"）')
    ap.add_argument(
        "--execute-one",
        type=int,
        default=None,
        metavar="N",
        help="PENDING 行の N 番目（0-origin）を 1 件だけ実コピー",
    )
    ap.add_argument(
        "--config",
        default=None,
        help="config TOML のパス（省略時は WISEMAN_HUB_CONFIG or config/default.toml）",
    )
    args = ap.parse_args()

    m = _SHEET_RE.match(args.sheet_name)
    if not m:
        print(f"ERROR: sheet_name format invalid: {args.sheet_name}")
        return 1
    month = int(m.group(2))

    config_path = _resolve_config_path(args.config)
    config = load_config(config_path)

    if not config.checklist.spreadsheet_id:
        print("ERROR: checklist.spreadsheet_id が未設定です")
        return 1

    print(
        f"Downloading spreadsheet "
        f"(id={config.checklist.spreadsheet_id[:8]}...)"
    )
    xlsx = download_xlsx(config.gcp, config.checklist.spreadsheet_id)
    rows = parse_sheet(xlsx, args.sheet_name)
    b_rows = select_b_rows(rows)
    print(f"B 対象行: {len(b_rows)} 件")

    results = plan_b_placement(b_rows, config.checklist, month)
    pending: list[tuple[int, object]] = [
        (i, r) for i, r in enumerate(results) if r.status == PlacementStatus.PENDING
    ]
    print(f"PENDING (実コピー可能): {len(pending)} 件")

    if not pending:
        print("\n配置可能な行がありません")
        return 0

    print("\n=== PENDING 行（実コピー前の計画）===")
    for n, (orig_idx, r) in enumerate(pending):
        print(f"\n[{n}] (results idx {orig_idx})")
        print(f"  氏名:       {r.row.name}")
        print(f"  居宅:       {r.row.facility}")
        print(f"  担当:       {r.row.staff}")
        print(f"  source PDF: {r.source_pdf}")
        print(f"  target PDF: {r.target_pdf}")

    if args.execute_one is None:
        print(
            "\n(ドライランモード: --execute-one N で N 番目を 1 件だけ実コピー可能)"
        )
        return 0

    n = args.execute_one
    if n < 0 or n >= len(pending):
        print(
            f"\nERROR: --execute-one {n} は範囲外 (0-{len(pending) - 1})"
        )
        return 1

    _, r = pending[n]
    if r.source_pdf is None or r.target_pdf is None:
        print("\nERROR: source/target が None (PENDING で本来発生しない)")
        return 1

    print(f"\n=== 実コピー候補 [{n}] ===")
    print(f"  source: {r.source_pdf}")
    print(f"  target: {r.target_pdf}")
    confirm = input("  実コピーしますか？ ('yes' のみ実行): ")
    if confirm.strip().lower() != "yes":
        print("  キャンセルしました")
        return 0

    if r.target_pdf.exists():
        overwrite = input(
            f"  target が既に存在します ({r.target_pdf.name})。上書きしますか？ ('yes' のみ): "
        )
        if overwrite.strip().lower() != "yes":
            print("  上書きキャンセル")
            return 0

    r.target_pdf.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(r.source_pdf, r.target_pdf)
    print(f"  ✅ コピー完了: {r.target_pdf}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
