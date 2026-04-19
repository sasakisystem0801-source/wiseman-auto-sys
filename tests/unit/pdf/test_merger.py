"""PDF merger のユニットテスト。

テスト用PDFはコード内で生成する。
"""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from wiseman_hub.config import PdfMergeConfig
from wiseman_hub.pdf.merger import (
    MergeReport,
    UserPageSource,
    merge_user_pdfs,
)


def _make_pdf(labels: list[str], page_size: tuple[float, float] = (595.0, 842.0)) -> bytes:
    """各ページに `labels[i]` のテキストを書き込んだPDFを返す。"""
    doc = fitz.open()
    try:
        for label in labels:
            page = doc.new_page(width=page_size[0], height=page_size[1])
            page.insert_text((50, 50), label, fontsize=12)
        return bytes(doc.tobytes())
    finally:
        doc.close()


def _page_texts(pdf_path: Path) -> list[str]:
    doc = fitz.open(pdf_path)
    try:
        return [doc[i].get_text().strip() for i in range(doc.page_count)]
    finally:
        doc.close()


@pytest.fixture
def input_dir(tmp_path: Path) -> Path:
    d = tmp_path / "input"
    d.mkdir()
    return d


@pytest.fixture
def output_path(tmp_path: Path) -> Path:
    return tmp_path / "output" / "merged.pdf"


@pytest.fixture
def config(input_dir: Path) -> PdfMergeConfig:
    return PdfMergeConfig(
        input_dir=str(input_dir),
        source_b_pattern="B_{name}.pdf",
        source_c_pattern="C_{name}.pdf",
        source_d_filename="D_common.pdf",
        concat_order=["A", "B", "C"],
    )


def _user(name: str, a_label: str = "A") -> UserPageSource:
    return UserPageSource(
        user_name=name,
        a_page_pdf_bytes=_make_pdf([f"{a_label}:{name}"]),
        page_index=0,
    )


# --- 正常系 --------------------------------------------------------


def test_merge_two_users_abc_order_with_d(
    input_dir: Path, output_path: Path, config: PdfMergeConfig
) -> None:
    (input_dir / "B_u1.pdf").write_bytes(_make_pdf(["B:u1-p1", "B:u1-p2"]))
    (input_dir / "C_u1.pdf").write_bytes(_make_pdf(["C:u1"]))
    (input_dir / "B_u2.pdf").write_bytes(_make_pdf(["B:u2"]))
    (input_dir / "C_u2.pdf").write_bytes(_make_pdf(["C:u2"]))
    (input_dir / "D_common.pdf").write_bytes(_make_pdf(["D:common1", "D:common2"]))

    users = [_user("u1"), _user("u2")]
    report = merge_user_pdfs(users, config, output_path)

    assert isinstance(report, MergeReport)
    assert report.user_count == 2
    assert report.missing_sources == []
    assert report.d_appended is True
    assert output_path.exists()

    texts = _page_texts(output_path)
    # u1: A, B(x2), C  → u2: A, B, C  → D(x2)
    assert texts == [
        "A:u1",
        "B:u1-p1",
        "B:u1-p2",
        "C:u1",
        "A:u2",
        "B:u2",
        "C:u2",
        "D:common1",
        "D:common2",
    ]
    assert report.total_pages == 9


def test_concat_order_respected(
    input_dir: Path, output_path: Path, config: PdfMergeConfig
) -> None:
    """concat_order=[C, A, B] でも反映されること（AC5）。"""
    (input_dir / "B_u1.pdf").write_bytes(_make_pdf(["B:u1"]))
    (input_dir / "C_u1.pdf").write_bytes(_make_pdf(["C:u1"]))

    reordered = PdfMergeConfig(
        input_dir=config.input_dir,
        source_b_pattern=config.source_b_pattern,
        source_c_pattern=config.source_c_pattern,
        source_d_filename="",  # D なし
        concat_order=["C", "A", "B"],
    )
    users = [_user("u1")]
    report = merge_user_pdfs(users, reordered, output_path)

    assert _page_texts(output_path) == ["C:u1", "A:u1", "B:u1"]
    assert report.d_appended is False


def test_empty_source_d_filename_skips_d_silently(
    input_dir: Path, output_path: Path
) -> None:
    (input_dir / "B_u1.pdf").write_bytes(_make_pdf(["B:u1"]))
    (input_dir / "C_u1.pdf").write_bytes(_make_pdf(["C:u1"]))

    cfg = PdfMergeConfig(
        input_dir=str(input_dir),
        source_b_pattern="B_{name}.pdf",
        source_c_pattern="C_{name}.pdf",
        source_d_filename="",
        concat_order=["A", "B", "C"],
    )
    report = merge_user_pdfs([_user("u1")], cfg, output_path)
    assert report.d_appended is False
    assert len(_page_texts(output_path)) == 3


def test_output_parent_directory_created(
    input_dir: Path, tmp_path: Path, config: PdfMergeConfig
) -> None:
    """output_path の親ディレクトリが存在しなくても作成される。"""
    (input_dir / "B_u1.pdf").write_bytes(_make_pdf(["B"]))
    (input_dir / "C_u1.pdf").write_bytes(_make_pdf(["C"]))
    (input_dir / "D_common.pdf").write_bytes(_make_pdf(["D"]))

    deep_output = tmp_path / "a" / "b" / "c" / "out.pdf"
    assert not deep_output.parent.exists()
    merge_user_pdfs([_user("u1")], config, deep_output)
    assert deep_output.exists()


# --- 欠損ファイル（AC4） -------------------------------------------


def test_missing_b_file_warns_and_continues(
    input_dir: Path, output_path: Path, config: PdfMergeConfig
) -> None:
    # B_u1.pdf を作らない（欠損）
    (input_dir / "C_u1.pdf").write_bytes(_make_pdf(["C:u1"]))
    (input_dir / "D_common.pdf").write_bytes(_make_pdf(["D"]))

    report = merge_user_pdfs([_user("u1")], config, output_path)

    assert report.missing_sources == [("u1", "B")]
    texts = _page_texts(output_path)
    # A, C, D （B はスキップ）
    assert texts == ["A:u1", "C:u1", "D"]


def test_missing_c_file_warns_and_continues(
    input_dir: Path, output_path: Path, config: PdfMergeConfig
) -> None:
    (input_dir / "B_u1.pdf").write_bytes(_make_pdf(["B:u1"]))
    # C_u1.pdf は欠損
    (input_dir / "D_common.pdf").write_bytes(_make_pdf(["D"]))

    report = merge_user_pdfs([_user("u1")], config, output_path)

    assert report.missing_sources == [("u1", "C")]
    assert _page_texts(output_path) == ["A:u1", "B:u1", "D"]


def test_missing_d_file_raises_when_configured(
    input_dir: Path, output_path: Path, config: PdfMergeConfig
) -> None:
    """D が config 指定されているのに存在しない場合は明示エラー。"""
    (input_dir / "B_u1.pdf").write_bytes(_make_pdf(["B"]))
    (input_dir / "C_u1.pdf").write_bytes(_make_pdf(["C"]))
    # D_common.pdf を作らない

    with pytest.raises(FileNotFoundError, match="D_common.pdf"):
        merge_user_pdfs([_user("u1")], config, output_path)


# --- 設定エラー ---------------------------------------------------


def test_unknown_concat_order_kind_raises(
    input_dir: Path, output_path: Path
) -> None:
    cfg = PdfMergeConfig(
        input_dir=str(input_dir),
        concat_order=["A", "X"],  # "X" は未知
        source_d_filename="",
    )
    with pytest.raises(ValueError, match="concat_order"):
        merge_user_pdfs([_user("u1")], cfg, output_path)


def test_empty_concat_order_raises(input_dir: Path, output_path: Path) -> None:
    cfg = PdfMergeConfig(
        input_dir=str(input_dir),
        concat_order=[],
        source_d_filename="",
    )
    with pytest.raises(ValueError, match="concat_order"):
        merge_user_pdfs([_user("u1")], cfg, output_path)


def test_empty_users_with_only_d(
    input_dir: Path, output_path: Path, config: PdfMergeConfig
) -> None:
    """利用者ゼロでも D だけ入った PDF を生成する。"""
    (input_dir / "D_common.pdf").write_bytes(_make_pdf(["D"]))
    report = merge_user_pdfs([], config, output_path)
    assert report.user_count == 0
    assert report.d_appended is True
    assert _page_texts(output_path) == ["D"]


def test_empty_users_and_no_d_raises(
    input_dir: Path, output_path: Path
) -> None:
    """結果が0ページになる場合はエラー（空PDFを生成しない）。"""
    cfg = PdfMergeConfig(
        input_dir=str(input_dir),
        source_d_filename="",
        concat_order=["A", "B", "C"],
    )
    with pytest.raises(ValueError, match="no pages"):
        merge_user_pdfs([], cfg, output_path)


# --- 複数名・重複 -------------------------------------------------


def test_order_a_only_works(
    input_dir: Path, output_path: Path
) -> None:
    """concat_order=['A'] だけでも動作する。"""
    cfg = PdfMergeConfig(
        input_dir=str(input_dir),
        source_d_filename="",
        concat_order=["A"],
    )
    users = [_user("u1"), _user("u2"), _user("u3")]
    merge_user_pdfs(users, cfg, output_path)
    assert _page_texts(output_path) == ["A:u1", "A:u2", "A:u3"]


def test_multiple_users_missing_various(
    input_dir: Path, output_path: Path, config: PdfMergeConfig
) -> None:
    """複数利用者で欠損がバラバラの場合、missing_sources に全部記録される。"""
    (input_dir / "B_u1.pdf").write_bytes(_make_pdf(["B1"]))
    # C_u1.pdf 欠損
    # B_u2.pdf 欠損
    (input_dir / "C_u2.pdf").write_bytes(_make_pdf(["C2"]))
    (input_dir / "D_common.pdf").write_bytes(_make_pdf(["D"]))

    report = merge_user_pdfs([_user("u1"), _user("u2")], config, output_path)
    assert sorted(report.missing_sources) == [("u1", "C"), ("u2", "B")]
    assert _page_texts(output_path) == ["A:u1", "B1", "A:u2", "C2", "D"]
