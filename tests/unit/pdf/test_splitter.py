"""PDF splitter のユニットテスト。

テスト用PDFはコード内で生成する（fixture依存を最小化）。
"""

from __future__ import annotations

import io
from pathlib import Path

import fitz
import pytest
from PIL import Image

from wiseman_hub.config import UserNameBBox
from wiseman_hub.pdf.splitter import SplitPage, split_pdf_with_bbox


def _make_pdf(num_pages: int, page_size: tuple[float, float] = (595.0, 842.0)) -> bytes:
    """指定ページ数のA4相当PDFを生成してbytesで返す。"""
    doc = fitz.open()
    try:
        for i in range(num_pages):
            page = doc.new_page(width=page_size[0], height=page_size[1])
            page.insert_text((50, 50), f"Page {i + 1}", fontsize=12)
        return bytes(doc.tobytes())
    finally:
        doc.close()


@pytest.fixture
def single_page_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "single.pdf"
    path.write_bytes(_make_pdf(1))
    return path


@pytest.fixture
def five_page_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "multi.pdf"
    path.write_bytes(_make_pdf(5))
    return path


@pytest.fixture
def default_bbox() -> UserNameBBox:
    # A4 (595x842 pt) 左上寄りの小さな矩形
    return UserNameBBox(x0=40.0, y0=40.0, x1=200.0, y1=80.0, dpi=150)


def test_split_single_page_pdf_returns_one_result(
    single_page_pdf: Path, default_bbox: UserNameBBox
) -> None:
    result = split_pdf_with_bbox(single_page_pdf, default_bbox)
    assert len(result) == 1
    assert isinstance(result[0], SplitPage)
    assert result[0].page_index == 0


def test_split_multi_page_pdf_returns_one_per_page(
    five_page_pdf: Path, default_bbox: UserNameBBox
) -> None:
    result = split_pdf_with_bbox(five_page_pdf, default_bbox)
    assert len(result) == 5
    assert [r.page_index for r in result] == [0, 1, 2, 3, 4]


def test_each_result_is_valid_single_page_pdf(
    five_page_pdf: Path, default_bbox: UserNameBBox
) -> None:
    result = split_pdf_with_bbox(five_page_pdf, default_bbox)
    for split in result:
        doc = fitz.open(stream=split.page_pdf_bytes, filetype="pdf")
        try:
            assert doc.page_count == 1
        finally:
            doc.close()


def test_single_page_results_preserve_page_content(
    five_page_pdf: Path, default_bbox: UserNameBBox
) -> None:
    """分割後のPDFが元ページのテキストを保持していること。"""
    result = split_pdf_with_bbox(five_page_pdf, default_bbox)
    for idx, split in enumerate(result):
        doc = fitz.open(stream=split.page_pdf_bytes, filetype="pdf")
        try:
            text = doc[0].get_text()
            assert f"Page {idx + 1}" in text
        finally:
            doc.close()


def test_bbox_image_is_valid_png(
    five_page_pdf: Path, default_bbox: UserNameBBox
) -> None:
    result = split_pdf_with_bbox(five_page_pdf, default_bbox)
    for split in result:
        assert split.bbox_image_png[:8] == b"\x89PNG\r\n\x1a\n"


def test_bbox_image_has_expected_dimensions(
    single_page_pdf: Path, default_bbox: UserNameBBox
) -> None:
    """dpi=150, bbox=(40,40)-(200,80) → 幅160pt*150/72 ≈ 333px, 高40pt*150/72 ≈ 83px"""
    result = split_pdf_with_bbox(single_page_pdf, default_bbox)
    img = Image.open(io.BytesIO(result[0].bbox_image_png))
    assert abs(img.width - 333) <= 2
    assert abs(img.height - 83) <= 2


def test_missing_file_raises_file_not_found(
    tmp_path: Path, default_bbox: UserNameBBox
) -> None:
    with pytest.raises(FileNotFoundError):
        split_pdf_with_bbox(tmp_path / "nonexistent.pdf", default_bbox)


def test_invalid_bbox_x_order_raises(single_page_pdf: Path) -> None:
    invalid = UserNameBBox(x0=200.0, y0=40.0, x1=100.0, y1=80.0, dpi=150)
    with pytest.raises(ValueError, match="bbox"):
        split_pdf_with_bbox(single_page_pdf, invalid)


def test_invalid_bbox_y_order_raises(single_page_pdf: Path) -> None:
    invalid = UserNameBBox(x0=40.0, y0=100.0, x1=200.0, y1=40.0, dpi=150)
    with pytest.raises(ValueError, match="bbox"):
        split_pdf_with_bbox(single_page_pdf, invalid)


def test_bbox_outside_page_raises(single_page_pdf: Path) -> None:
    # A4幅595ptを超える
    out_of_page = UserNameBBox(x0=40.0, y0=40.0, x1=9999.0, y1=80.0, dpi=150)
    with pytest.raises(ValueError, match="bbox"):
        split_pdf_with_bbox(single_page_pdf, out_of_page)


def test_invalid_dpi_raises(single_page_pdf: Path) -> None:
    zero_dpi = UserNameBBox(x0=40.0, y0=40.0, x1=200.0, y1=80.0, dpi=0)
    with pytest.raises(ValueError, match="dpi"):
        split_pdf_with_bbox(single_page_pdf, zero_dpi)
