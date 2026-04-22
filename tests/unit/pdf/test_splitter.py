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
from wiseman_hub.pdf.splitter import (
    PdfCorruptedError,
    PdfEncryptedError,
    SplitPage,
    split_pdf_with_bbox,
)


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


# --- fitz エラー翻訳 ---------------------------------------------------


def test_empty_file_raises_corrupted_error(
    tmp_path: Path, default_bbox: UserNameBBox
) -> None:
    path = tmp_path / "empty.pdf"
    path.write_bytes(b"")
    with pytest.raises(PdfCorruptedError, match="Empty"):
        split_pdf_with_bbox(path, default_bbox)


def test_corrupted_file_raises_corrupted_error(
    tmp_path: Path, default_bbox: UserNameBBox
) -> None:
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.4\nnot really a pdf\n%%EOF")
    with pytest.raises(PdfCorruptedError, match="Corrupted"):
        split_pdf_with_bbox(path, default_bbox)


def test_zero_page_pdf_raises_corrupted_error(
    tmp_path: Path,
    default_bbox: UserNameBBox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #51 #4: 0 ページ PDF は PdfCorruptedError("PDF has no pages")。

    fitz は page_count=0 状態の Document を save/tobytes しようとすると
    ValueError("cannot save with zero pages") を送出する。そのため
    現実のテスト fixture として 0 ページ PDF ファイルを作れない。
    ここでは page_count を 0 に差し替えた Document を注入して contract を固定する。
    """
    import wiseman_hub.pdf.splitter as splitter_mod

    # 正常に開ける 1 ページ PDF を作っておき、page_count だけ 0 に差し替える
    path = tmp_path / "looks_valid.pdf"
    doc_for_file = fitz.open()
    try:
        doc_for_file.new_page(width=595.0, height=842.0)
        path.write_bytes(bytes(doc_for_file.tobytes()))
    finally:
        doc_for_file.close()

    real_open_pdf_or_raise = splitter_mod._open_pdf_or_raise

    def open_returning_zero_page_doc(pdf_path: Path) -> fitz.Document:
        doc = real_open_pdf_or_raise(pdf_path)
        # page_count プロパティを 0 に差し替える（実体の削除はせず contract 検証のみ）
        monkeypatch.setattr(type(doc), "page_count", 0, raising=False)
        return doc

    monkeypatch.setattr(
        splitter_mod, "_open_pdf_or_raise", open_returning_zero_page_doc
    )

    with pytest.raises(PdfCorruptedError, match="no pages"):
        split_pdf_with_bbox(path, default_bbox)


def test_non_pdf_file_renamed_raises_corrupted_error(
    tmp_path: Path, default_bbox: UserNameBBox
) -> None:
    """PNG を .pdf にリネームしたファイルは fitz では開けるが is_pdf=False。"""
    path = tmp_path / "png_masquerading.pdf"
    # 1x1 透明PNG
    png_bytes = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000a49444154789c6300010000000500010d0a2db40000000049454e44ae426082"
    )
    path.write_bytes(png_bytes)
    with pytest.raises(PdfCorruptedError, match="Not a PDF"):
        split_pdf_with_bbox(path, default_bbox)


def test_encrypted_pdf_raises_encrypted_error(
    tmp_path: Path, default_bbox: UserNameBBox
) -> None:
    path = tmp_path / "encrypted.pdf"
    doc = fitz.open()
    try:
        page = doc.new_page(width=595.0, height=842.0)
        page.insert_text((50, 50), "secret", fontsize=12)
        doc.save(
            str(path),
            encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw="owner",
            user_pw="user",
        )
    finally:
        doc.close()
    with pytest.raises(PdfEncryptedError, match="encrypted"):
        split_pdf_with_bbox(path, default_bbox)


# --- heterogeneous ページサイズ -----------------------------------------


def test_heterogeneous_pages_validates_bbox_per_page(
    tmp_path: Path,
) -> None:
    """page 0 はA4、page 1 は半分サイズ。bbox は page 0 にはフィットするが page 1 では範囲外。"""
    path = tmp_path / "mixed.pdf"
    doc = fitz.open()
    try:
        p0 = doc.new_page(width=595.0, height=842.0)
        p0.insert_text((50, 50), "large page", fontsize=12)
        p1 = doc.new_page(width=200.0, height=300.0)
        p1.insert_text((10, 10), "small page", fontsize=10)
        path.write_bytes(bytes(doc.tobytes()))
    finally:
        doc.close()

    # bbox は page 0 (595x842) にはフィット、page 1 (200x300) では x1=400 が範囲外
    bbox = UserNameBBox(x0=40.0, y0=40.0, x1=400.0, y1=80.0, dpi=150)
    with pytest.raises(ValueError, match="page 1"):
        split_pdf_with_bbox(path, bbox)


def test_heterogeneous_pages_succeed_when_bbox_fits_all(tmp_path: Path) -> None:
    """bbox が全ページ内に収まる場合は正常に処理できる。"""
    path = tmp_path / "mixed_ok.pdf"
    doc = fitz.open()
    try:
        p0 = doc.new_page(width=595.0, height=842.0)
        p0.insert_text((50, 50), "large", fontsize=12)
        p1 = doc.new_page(width=200.0, height=300.0)
        p1.insert_text((10, 10), "small", fontsize=10)
        path.write_bytes(bytes(doc.tobytes()))
    finally:
        doc.close()

    bbox = UserNameBBox(x0=10.0, y0=10.0, x1=100.0, y1=50.0, dpi=100)
    result = split_pdf_with_bbox(path, bbox)
    assert len(result) == 2
