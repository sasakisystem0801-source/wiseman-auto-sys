"""利用者単位に PDF を結合し、末尾に共通PDF (D) を追加する。

入力:
- 利用者ごとの `UserPageSource`（OCR で特定した氏名 + splitter の1ページPDF）
- `PdfMergeConfig`（concat_order, B/C のファイル名パターン, D のファイル名, input_dir）

処理:
1. `concat_order` の順で各利用者の A/B/C を追加
   - "A": `UserPageSource.a_page_pdf_bytes`
   - "B": `{input_dir}/{source_b_pattern.format(name=user_name)}`
   - "C": `{input_dir}/{source_c_pattern.format(name=user_name)}`
   - B/C が欠損している場合は WARN してスキップ（`missing_sources` に記録）
2. `source_d_filename` が設定されていれば末尾に追加
   - 設定あり + ファイル欠損 → FileNotFoundError（明示エラー）
   - 設定なし（空文字列） → スキップ

出力: 単一の PDF ファイル + `MergeReport`

詳細は ADR-008 / docs/handoff/LATEST.md 参照。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import fitz

from wiseman_hub.config import PdfMergeConfig

logger = logging.getLogger(__name__)

_KNOWN_KINDS = frozenset({"A", "B", "C"})


class PdfMergeError(Exception):
    """PDF merger の失敗を表す基底例外。"""


@dataclass(frozen=True)
class UserPageSource:
    """1利用者分の入力。

    user_name: OCR で抽出した氏名（B/C ファイル名の `{name}` プレースホルダ解決に使用）
    a_page_pdf_bytes: splitter の `SplitPage.page_pdf_bytes`（A の1ページ分PDF）
    page_index: 元 A のページインデックス（ログ用）
    """

    user_name: str
    a_page_pdf_bytes: bytes
    page_index: int = 0


@dataclass(frozen=True)
class MergeReport:
    """結合結果。"""

    output_path: Path
    user_count: int
    total_pages: int
    missing_sources: list[tuple[str, str]]  # [(user_name, "B" | "C")]
    d_appended: bool


def _validate_concat_order(concat_order: list[str]) -> None:
    if not concat_order:
        raise ValueError("concat_order is empty; must contain at least one of A/B/C")
    unknown = [k for k in concat_order if k not in _KNOWN_KINDS]
    if unknown:
        raise ValueError(
            f"concat_order contains unknown kinds {unknown}; allowed: {sorted(_KNOWN_KINDS)}"
        )


def _append_pdf_bytes(dst: fitz.Document, pdf_bytes: bytes, source_label: str) -> int:
    """dst に pdf_bytes を追記する。追加ページ数を返す。"""
    try:
        src = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        raise PdfMergeError(f"Failed to open PDF for {source_label}: {e}") from e
    try:
        added = int(src.page_count)
        dst.insert_pdf(src)
        return added
    finally:
        src.close()


def _append_pdf_file(dst: fitz.Document, path: Path, source_label: str) -> int:
    try:
        src = fitz.open(path)
    except Exception as e:
        raise PdfMergeError(f"Failed to open PDF file {path} for {source_label}: {e}") from e
    try:
        added = int(src.page_count)
        dst.insert_pdf(src)
        return added
    finally:
        src.close()


def merge_user_pdfs(
    users: list[UserPageSource],
    config: PdfMergeConfig,
    output_path: Path,
) -> MergeReport:
    """利用者ごとに concat_order で A/B/C を結合、末尾に D を1回追加する。

    Raises:
        ValueError: concat_order が空/未知、または出力が0ページになる
        FileNotFoundError: D が設定されているが存在しない
        PdfMergeError: PDF 読込/書込の失敗
    """
    _validate_concat_order(config.concat_order)

    input_dir = Path(config.input_dir) if config.input_dir else Path()
    missing: list[tuple[str, str]] = []
    total_pages = 0

    dst = fitz.open()
    try:
        for user in users:
            for kind in config.concat_order:
                if kind == "A":
                    total_pages += _append_pdf_bytes(
                        dst, user.a_page_pdf_bytes, f"A:{user.user_name}"
                    )
                else:
                    pattern = (
                        config.source_b_pattern if kind == "B" else config.source_c_pattern
                    )
                    filename = pattern.format(name=user.user_name)
                    path = input_dir / filename
                    if not path.exists():
                        logger.warning(
                            "Missing %s source for user %r: %s (skipping)",
                            kind,
                            user.user_name,
                            path,
                        )
                        missing.append((user.user_name, kind))
                        continue
                    total_pages += _append_pdf_file(dst, path, f"{kind}:{user.user_name}")

        d_appended = False
        if config.source_d_filename:
            d_path = input_dir / config.source_d_filename
            if not d_path.exists():
                raise FileNotFoundError(f"D source not found: {d_path}")
            total_pages += _append_pdf_file(dst, d_path, "D")
            d_appended = True

        if total_pages == 0:
            raise ValueError(
                "Resulting PDF would have no pages "
                "(empty users and no D source configured)"
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        dst.save(str(output_path))
        logger.info(
            "merge_user_pdfs done: users=%d pages=%d output=%s missing=%d",
            len(users),
            total_pages,
            output_path,
            len(missing),
        )
    finally:
        dst.close()

    return MergeReport(
        output_path=output_path,
        user_count=len(users),
        total_pages=total_pages,
        missing_sources=missing,
        d_appended=d_appended,
    )
