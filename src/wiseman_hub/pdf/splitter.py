"""複数利用者PDFを1ページずつに分割し、固定矩形領域を画像として切り出す。

利用実績PDF（1利用者=1ページ）を想定。各ページに対して:

1. そのページ単体のPDF（page_pdf_bytes）— 後段の再結合処理で利用
2. UserNameBBox で指定された矩形の画像（bbox_image_png）— OCRで利用者名抽出に使用

詳細は ADR-008 / docs/handoff/LATEST.md 参照。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz

from wiseman_hub.config import UserNameBBox


@dataclass(frozen=True)
class SplitPage:
    """PDF分割結果（1ページ分）。"""

    page_index: int  # 0-based
    page_pdf_bytes: bytes  # そのページ単体のPDF
    bbox_image_png: bytes  # UserNameBBox で切り出したPNG画像


def _validate_bbox(bbox: UserNameBBox, page_width: float, page_height: float) -> None:
    if bbox.dpi <= 0:
        raise ValueError(f"bbox dpi must be positive: got {bbox.dpi}")
    if bbox.x0 >= bbox.x1:
        raise ValueError(f"bbox x-order invalid: x0={bbox.x0} >= x1={bbox.x1}")
    if bbox.y0 >= bbox.y1:
        raise ValueError(f"bbox y-order invalid: y0={bbox.y0} >= y1={bbox.y1}")
    if bbox.x0 < 0 or bbox.y0 < 0 or bbox.x1 > page_width or bbox.y1 > page_height:
        raise ValueError(
            f"bbox ({bbox.x0},{bbox.y0})-({bbox.x1},{bbox.y1}) "
            f"outside page bounds ({page_width}x{page_height})"
        )


def _render_bbox_as_png(page: fitz.Page, bbox: UserNameBBox) -> bytes:
    rect = fitz.Rect(bbox.x0, bbox.y0, bbox.x1, bbox.y1)
    matrix = fitz.Matrix(bbox.dpi / 72.0, bbox.dpi / 72.0)
    pixmap = page.get_pixmap(matrix=matrix, clip=rect, alpha=False)
    return bytes(pixmap.tobytes("png"))


def _extract_single_page_pdf(src: fitz.Document, page_index: int) -> bytes:
    """src の page_index ページだけを含む新規PDFを bytes で返す。"""
    dst = fitz.open()
    try:
        dst.insert_pdf(src, from_page=page_index, to_page=page_index)
        return bytes(dst.tobytes())
    finally:
        dst.close()


def split_pdf_with_bbox(pdf_path: Path, bbox: UserNameBBox) -> list[SplitPage]:
    """複数ページPDFを1ページ単位に分割し、各ページから固定矩形を画像として切り出す。

    Args:
        pdf_path: 入力PDFファイルパス
        bbox: 利用者名が印字される矩形座標（ポイント単位）とレンダリングDPI

    Returns:
        ページ数分の SplitPage。元PDFのページ順。

    Raises:
        FileNotFoundError: pdf_path が存在しない
        ValueError: PDFが0ページ、またはbboxが不正（順序・ページ外・dpi<=0）
    """
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    doc = fitz.open(pdf_path)
    try:
        if doc.page_count == 0:
            raise ValueError(f"PDF has no pages: {pdf_path}")

        first_page = doc[0]
        _validate_bbox(bbox, first_page.rect.width, first_page.rect.height)

        results: list[SplitPage] = []
        for i in range(doc.page_count):
            page = doc[i]
            results.append(
                SplitPage(
                    page_index=i,
                    page_pdf_bytes=_extract_single_page_pdf(doc, i),
                    bbox_image_png=_render_bbox_as_png(page, bbox),
                )
            )
        return results
    finally:
        doc.close()
