"""事業所フォルダ PDF 結合 CLI（MVP 暫定版）。

Usage:
    uv run python scripts/merge_facility.py \\
        --a "C:/path/to/提供実績.pdf" \\
        --facility "//Tera-station/share/03.FAX(事業所)/きなり(メール)※持参" \\
        --output "C:/Users/sasak/OneDrive/デスクトップ/本田様/きなり"

処理内容:
    A.pdf の各ページから氏名抽出 → facility_dir 配下の
    運動機能向上計画書/ と 経過報告書/ から姓マッチでファイル検索
    → 利用者単位で A ページ + B + C を結合して {output}/{事業所名}/{姓}.pdf に出力
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from wiseman_hub.pdf.facility_merger import FacilityMergeReport, merge_facility


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="事業所フォルダ PDF 結合（A 提供実績 + B 計画書 + C 経過報告書）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-a",
        "--a",
        dest="source_a",
        required=True,
        help="A: 提供実績 PDF ファイルパス",
    )
    parser.add_argument(
        "-f",
        "--facility",
        dest="facility_dir",
        required=True,
        help="事業所フォルダ（配下に 運動機能向上計画書/ と 経過報告書/）",
    )
    parser.add_argument(
        "-o",
        "--output",
        dest="output_root",
        required=True,
        help="出力ルート（{output}/{事業所名}/ にファイル生成）",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="デバッグログを出力"
    )
    return parser


def _print_report(report: FacilityMergeReport) -> None:
    print("=" * 60)
    print(f"事業所: {report.facility_name}")
    print(f"出力先: {report.output_dir}")
    print("=" * 60)
    print(f"成功: {len(report.success)} 件")
    for entry in report.success:
        mark = "+".join(entry.sources_used)
        # PII 防御: full_name を stdout に出さず、出力ファイル名の姓のみ表示
        print(f"  OK    {entry.user_key}.pdf  ({mark})")
    if report.extraction_failed_pages:
        pages = ", ".join(str(p + 1) for p in report.extraction_failed_pages)
        print(f"\n氏名抽出失敗（A.pdf ページ番号）: {pages}")
    if report.a_only:
        print(f"A のみ（B/C 両方なし）: {', '.join(report.a_only)}")
    if report.a_missing:
        print(f"A にマッチなし（B+C のみ結合）: {', '.join(report.a_missing)}")
    if report.b_missing:
        print(f"B（計画書）なし: {', '.join(report.b_missing)}")
    if report.c_missing:
        print(f"C（経過報告書）なし: {', '.join(report.c_missing)}")
    if report.name_conflicts:
        print(
            f"同姓コンフリクト（連番付与）: {', '.join(report.name_conflicts)}"
        )


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        report = merge_facility(
            Path(args.source_a),
            Path(args.facility_dir),
            Path(args.output_root),
        )
    except FileNotFoundError as e:
        # FileNotFoundError は filename 属性のみ、PII を含まない前提で許容
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        # PII 防御: 第三者例外（OSError.filename に絶対パス等）は型名のみ表示。
        # 詳細は logger 経路で取得する。
        logging.getLogger(__name__).exception(
            "merge_facility failed with %s", type(e).__name__
        )
        print(f"ERROR ({type(e).__name__})", file=sys.stderr)
        return 1

    _print_report(report)
    # 成功 0 件 or 抽出失敗のみ → 1
    if not report.success:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
