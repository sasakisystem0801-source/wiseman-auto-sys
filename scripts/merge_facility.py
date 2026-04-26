"""事業所フォルダ PDF 結合 CLI（新仕様: 事業所単位 1 ファイル ABCABC 連結）。

Usage:
    # 本実行
    uv run python scripts/merge_facility.py \\
        --a "C:/path/to/提供実績.pdf" \\
        --facility "//Tera-station/share/03.FAX(事業所)/きなり(メール)※持参" \\
        --output "C:/Users/sasak/OneDrive/デスクトップ/本田様/きなり"

    # 事前診断（書込せず抽出・マッチプランだけ表示。実機で最初に実行推奨）
    uv run python scripts/merge_facility.py --a ... --facility ... --output ... --diag

処理内容:
    A.pdf の各ページから氏名抽出 → facility_dir 配下の
    運動機能向上計画書/ と 経過報告書/ から姓マッチでファイル検索
    → ABC 全揃いの利用者のみ A→B→C 順に連結し、A.pdf 出現順で並べて
    {output}/{事業所名}/{事業所名}.pdf の **単一ファイル** に出力
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from pathlib import Path

from wiseman_hub.pdf.facility_merger import (
    PLAN_DIR_NAME,
    REPORT_DIR_NAME,
    FacilityMergeReport,
    _collect_pdfs_by_stem,
    _match_by_partial,
    merge_facility,
)
from wiseman_hub.pdf.splitter import _open_pdf_or_raise
from wiseman_hub.pdf.text_name_extractor import extract_name_from_page


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
    parser.add_argument(
        "--diag",
        action="store_true",
        help="事前診断モード: 実ファイル書込せず、氏名抽出結果と B/C マッチプランだけ表示。"
        "実機で最初に実行して、実データと実装の整合を確認するのに使う。",
    )
    return parser


def run_diagnostic(
    source_a: Path, facility_dir: Path, output_root: Path
) -> int:
    """事前診断: ファイル書込せず、A 抽出 + B/C マッチプランだけ表示する。

    実機で最初にこれを実行することで、実データと実装の整合を書込前に確認できる:
      - A.pdf のテキスト層有無（氏名抽出できるか）
      - ファイル名ゆらぎのマッチ挙動
      - 同姓重複 fail-safe が発動するか
      - B/C の残余（Phase 2 対象）

    Returns: 0 (診断完了)
    """
    print("=" * 60)
    print("DIAGNOSTIC MODE (書込は行いません)")
    print("=" * 60)
    print(f"A         : {source_a}")
    print(f"facility  : {facility_dir}")
    print(f"output    : {output_root}")
    print(f"facility 名: {facility_dir.name}")

    if not source_a.exists():
        print(f"\nERROR: A.pdf が存在しません: {source_a}", file=sys.stderr)
        return 2
    if not facility_dir.exists():
        print(
            f"\nERROR: facility フォルダが存在しません: {facility_dir}",
            file=sys.stderr,
        )
        return 2

    plan_dir = facility_dir / PLAN_DIR_NAME
    report_dir = facility_dir / REPORT_DIR_NAME
    plans = _collect_pdfs_by_stem(plan_dir)
    reports = _collect_pdfs_by_stem(report_dir)

    print(f"\n[B] 運動機能向上計画書: {len(plans)} files")
    for stem in sorted(plans):
        print(f"  - {stem}.pdf")
    print(f"\n[C] 経過報告書: {len(reports)} files")
    for stem in sorted(reports):
        print(f"  - {stem}.pdf")

    # A.pdf の各ページから氏名抽出
    print("\n" + "=" * 60)
    print("A.pdf ページ別氏名抽出 + マッチ予測")
    print("=" * 60)
    doc = _open_pdf_or_raise(source_a)
    try:
        surname_counts: Counter[str] = Counter()
        page_results: list[tuple[int, str | None, str | None]] = []
        for i in range(doc.page_count):
            e = extract_name_from_page(doc[i])
            if e is None:
                page_results.append((i, None, None))
            else:
                page_results.append((i, e.last_name, e.first_name))
                surname_counts[e.last_name] += 1

        ambiguous = {s for s, c in surname_counts.items() if c >= 2}
        matched_b: set[str] = set()
        matched_c: set[str] = set()

        full_set_count = 0
        excluded_a_only = 0
        excluded_b_missing = 0
        excluded_c_missing = 0
        excluded_ambiguous = 0
        for i, last, first in page_results:
            if last is None:
                print(f"  p{i + 1:2d}: [EXTRACTION FAILED]")
                continue
            if last in ambiguous:
                print(
                    f"  p{i + 1:2d}: {last} {first}  "
                    f"[AMBIGUOUS → 除外（同姓重複 fail-safe）]"
                )
                excluded_ambiguous += 1
                continue
            b_match = _match_by_partial(last, plans)
            c_match = _match_by_partial(last, reports)
            b_label = b_match[0] + ".pdf" if b_match else "-"
            c_label = c_match[0] + ".pdf" if c_match else "-"
            if b_match and c_match:
                verdict = "→ 連結対象 (A+B+C)"
                full_set_count += 1
                matched_b.add(b_match[0])
                matched_c.add(c_match[0])
            elif not b_match and not c_match:
                verdict = "→ 除外 (a_only)"
                excluded_a_only += 1
            elif not b_match:
                verdict = "→ 除外 (b_missing)"
                excluded_b_missing += 1
            else:
                verdict = "→ 除外 (c_missing)"
                excluded_c_missing += 1
            print(
                f"  p{i + 1:2d}: {last} {first:<8s}  "
                f"B={b_label:<15s}  C={c_label:<15s}  {verdict}"
            )

        # 残余 B/C（A にマッチせず → 新仕様では除外）
        remaining_b = sorted(set(plans) - matched_b)
        remaining_c = sorted(set(reports) - matched_c)
        a_missing_total = len(remaining_b) + len(remaining_c)
        if a_missing_total > 0:
            print(
                f"\nA にマッチしない B/C（除外、a_missing カテゴリ）: "
                f"{a_missing_total} ファイル"
            )
            for stem in remaining_b:
                print(f"  ・B: {stem}.pdf")
            for stem in remaining_c:
                print(f"  ・C: {stem}.pdf")

        print("\n" + "-" * 60)
        print(f"連結対象 (ABC 全揃い): {full_set_count} 名")
        excluded_total = (
            excluded_a_only
            + excluded_b_missing
            + excluded_c_missing
            + excluded_ambiguous
            + a_missing_total
        )
        print(f"除外合計: {excluded_total} 名/ファイル")
        if excluded_a_only:
            print(f"  ・A のみ: {excluded_a_only}")
        if excluded_b_missing:
            print(f"  ・B 欠損: {excluded_b_missing}")
        if excluded_c_missing:
            print(f"  ・C 欠損: {excluded_c_missing}")
        if excluded_ambiguous:
            print(f"  ・同姓重複: {excluded_ambiguous}")
        if a_missing_total:
            print(f"  ・A 欠損 (B/C のみ): {a_missing_total}")

        if ambiguous:
            print(f"\n同姓重複姓: {sorted(ambiguous)}")
        if surname_counts:
            print(f"\n抽出成功: {sum(surname_counts.values())} 名分")
        failed = sum(1 for _, last, _ in page_results if last is None)
        if failed:
            print(f"氏名抽出失敗ページ数: {failed}")
        if full_set_count > 0:
            print(
                f"\n出力予測: {facility_dir.name}/{facility_dir.name}.pdf "
                f"({full_set_count * 3} ページ想定)"
            )
        else:
            print("\n出力予測: 結合対象なし → 出力ファイル作成されません")
    finally:
        doc.close()

    print("\n" + "=" * 60)
    print("DIAGNOSTIC ONLY: ファイル書込はされていません")
    print("問題なければ --diag フラグを外して再実行してください")
    return 0


def _print_report(report: FacilityMergeReport) -> None:
    print("=" * 60)
    print(f"事業所: {report.facility_name}")
    print(f"出力先: {report.output_dir}")
    print("=" * 60)

    # 重大警告: B/C サブフォルダ自体が不在
    if report.bc_dirs_missing:
        print(
            "\n⚠ 重大警告: 以下のサブフォルダが見つかりません",
            file=sys.stderr,
        )
        for d in report.bc_dirs_missing:
            print(f"   ・{d}/", file=sys.stderr)
        print(
            "   → 全利用者が連結対象外になります。"
            "事業所フォルダのパス・ネットワーク接続を確認してください。\n",
            file=sys.stderr,
        )

    # 重大警告: 氏名抽出失敗
    if report.extraction_failed_pages:
        pages = ", ".join(str(p + 1) for p in report.extraction_failed_pages)
        print(
            f"\n⚠ 注意: A.pdf の {len(report.extraction_failed_pages)} ページで"
            f"氏名抽出に失敗しました（ページ: {pages}）",
            file=sys.stderr,
        )
        print(
            "   → 該当利用者は出力 PDF に含まれません\n",
            file=sys.stderr,
        )

    if report.success:
        output_file = f"{report.facility_name}.pdf"
        print(
            f"結合 {len(report.success)} 名 → {output_file} (A→B→C 順で連結)"
        )
        for entry in report.success:
            # PII 防御: full_name を stdout に出さず、user_key（姓）のみ表示
            print(f"  ✓ {entry.user_key}")
    else:
        print("結合対象なし（ABC 全揃いの利用者がいません）")

    # 氏名抽出失敗の詳細表示は冒頭の重大警告で済ませているのでここでは省略

    excluded_total = (
        len(report.a_only)
        + len(report.b_missing)
        + len(report.c_missing)
        + len(report.a_missing)
        + len(report.ambiguous_bc_skipped)
    )
    if excluded_total > 0:
        print(f"\n除外: {excluded_total} 名（出力 PDF に含まれません）")
    if report.a_only:
        print(f"  ・A のみ（B/C 両方なし）: {', '.join(report.a_only)}")
    if report.b_missing:
        print(f"  ・B（計画書）なし: {', '.join(report.b_missing)}")
    if report.c_missing:
        print(f"  ・C（経過報告書）なし: {', '.join(report.c_missing)}")
    if report.a_missing:
        print(
            f"  ・A にマッチなし（B/C のみ存在）: {', '.join(report.a_missing)}"
        )
    if report.ambiguous_bc_skipped:
        print(
            "  ・同姓重複 fail-safe（誤添付防止）: "
            f"{', '.join(report.ambiguous_bc_skipped)}"
        )
    if report.name_conflicts:
        print(
            f"\n同姓コンフリクト（連番付与）: {', '.join(report.name_conflicts)}"
        )


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.diag:
        return run_diagnostic(
            Path(args.source_a),
            Path(args.facility_dir),
            Path(args.output_root),
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
