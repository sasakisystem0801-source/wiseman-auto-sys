"""複数利用者PDFを1ページずつに分割し、固定矩形領域を画像として切り出す。

利用実績PDF（1利用者=1ページ）を想定。各ページに対して:

1. そのページ単体のPDF（page_pdf_bytes）— 後段の再結合処理で利用
2. UserNameBBox で指定された矩形の画像（bbox_image_png）— OCRで利用者名抽出に使用

失敗方針: fail-fast。途中ページで失敗すると処理済みの結果も破棄して例外を上げる。
医療データを扱うため、ページ毎 isolation よりも明示的なエラー伝播を優先する。

詳細は ADR-008 / docs/handoff/LATEST.md 参照。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import fitz

from wiseman_hub.config import UserNameBBox

logger = logging.getLogger(__name__)


class PdfSplitError(Exception):
    """PDF splitter の失敗を表す基底例外。"""


class PdfCorruptedError(PdfSplitError):
    """PDFが破損・空・PDF以外のファイル。"""


class PdfEncryptedError(PdfSplitError):
    """PDFが暗号化されており処理できない。"""


@dataclass(frozen=True)
class SplitPage:
    """PDF分割結果（1ページ分）。"""

    page_index: int  # 0-based
    page_pdf_bytes: bytes  # そのページ単体のPDF
    bbox_image_png: bytes  # UserNameBBox で切り出したPNG画像


def _validate_bbox(
    bbox: UserNameBBox, page_width: float, page_height: float, page_index: int
) -> None:
    if bbox.dpi <= 0:
        raise ValueError(f"bbox dpi must be positive: got {bbox.dpi}")
    if bbox.x0 >= bbox.x1:
        raise ValueError(f"bbox x-order invalid: x0={bbox.x0} >= x1={bbox.x1}")
    if bbox.y0 >= bbox.y1:
        raise ValueError(f"bbox y-order invalid: y0={bbox.y0} >= y1={bbox.y1}")
    if bbox.x0 < 0 or bbox.y0 < 0 or bbox.x1 > page_width or bbox.y1 > page_height:
        raise ValueError(
            f"bbox ({bbox.x0},{bbox.y0})-({bbox.x1},{bbox.y1}) "
            f"outside page {page_index} bounds ({page_width}x{page_height})"
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


def _open_pdf_or_raise(pdf_path: Path) -> fitz.Document:
    """pdf_path を開いて Document を返す。不正な場合は PdfCorruptedError / PdfEncryptedError。

    fitz.open の素の例外（FileDataError/EmptyFileError 等）は内部ライブラリ型のため
    呼び出し元に漏らさず、プロジェクト固有の PdfSplitError 系に翻訳する。
    """
    try:
        doc = fitz.open(pdf_path)
    except fitz.EmptyFileError as e:
        logger.error("PDF is empty: %s", pdf_path)
        raise PdfCorruptedError(f"Empty PDF: {pdf_path}") from e
    except fitz.FileDataError as e:
        logger.error("PDF is corrupted: %s", pdf_path)
        raise PdfCorruptedError(f"Corrupted PDF: {pdf_path}") from e

    try:
        if not doc.is_pdf:
            logger.error("File opened but is not a PDF: %s", pdf_path)
            raise PdfCorruptedError(f"Not a PDF file: {pdf_path}")
        if doc.needs_pass or doc.is_encrypted:
            logger.error("PDF is encrypted: %s", pdf_path)
            raise PdfEncryptedError(
                f"PDF is encrypted: {pdf_path}. "
                f"Disable password protection in the export settings before processing."
            )
    except Exception:
        doc.close()
        raise

    return doc


def split_pdf_with_bbox(pdf_path: Path, bbox: UserNameBBox) -> list[SplitPage]:
    """複数ページPDFを1ページ単位に分割し、各ページから固定矩形を画像として切り出す。

    Args:
        pdf_path: 入力PDFファイルパス
        bbox: 利用者名が印字される矩形座標（ポイント単位）とレンダリングDPI

    Returns:
        ページ数分の SplitPage。元PDFのページ順。

    Raises:
        FileNotFoundError: pdf_path が存在しない
        PdfCorruptedError: PDFが空・破損・非PDFファイル・0ページ
        PdfEncryptedError: PDFが暗号化されている
        ValueError: bbox が不正（順序・いずれかのページ外・dpi<=0）
        PdfSplitError: 上記以外のページ処理失敗（内部 fitz エラーのラップ）
    """
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    logger.info("split_pdf_with_bbox start: %s", pdf_path)
    doc = _open_pdf_or_raise(pdf_path)
    try:
        if doc.page_count == 0:
            raise PdfCorruptedError(f"PDF has no pages: {pdf_path}")

        results: list[SplitPage] = []
        for i in range(doc.page_count):
            try:
                page = doc[i]
                _validate_bbox(bbox, page.rect.width, page.rect.height, page_index=i)
                results.append(
                    SplitPage(
                        page_index=i,
                        page_pdf_bytes=_extract_single_page_pdf(doc, i),
                        bbox_image_png=_render_bbox_as_png(page, bbox),
                    )
                )
            except (ValueError, PdfSplitError):
                raise
            except Exception as e:
                logger.error(
                    "split_pdf_with_bbox failed at page %d of %d: %s",
                    i,
                    doc.page_count,
                    pdf_path,
                    exc_info=True,
                )
                raise PdfSplitError(
                    f"Failed to process page {i} of {doc.page_count} in {pdf_path}: {e}"
                ) from e

        logger.info("split_pdf_with_bbox done: %s pages=%d", pdf_path, len(results))
        return results
    finally:
        doc.close()
