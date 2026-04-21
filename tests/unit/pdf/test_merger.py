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
    PdfMergeError,
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
    assert report.has_missing_sources is True
    assert _page_texts(output_path) == ["A:u1", "B1", "A:u2", "C2", "D"]


# --- 入力バリデーション（defense-in-depth）-------------------------


def test_empty_input_dir_raises() -> None:
    cfg = PdfMergeConfig(
        input_dir="",
        concat_order=["A"],
        source_d_filename="",
    )
    with pytest.raises(ValueError, match="input_dir"):
        merge_user_pdfs([_user("u1")], cfg, Path("/tmp/out.pdf"))


def test_user_name_with_path_separator_rejected(
    input_dir: Path, output_path: Path, config: PdfMergeConfig
) -> None:
    bad = UserPageSource(
        user_name="../etc/passwd",
        a_page_pdf_bytes=_make_pdf(["A"]),
    )
    with pytest.raises(PdfMergeError, match="traversal|forbidden"):
        merge_user_pdfs([bad], config, output_path)


def test_user_name_with_backslash_rejected(
    input_dir: Path, output_path: Path, config: PdfMergeConfig
) -> None:
    bad = UserPageSource(
        user_name="a\\b",
        a_page_pdf_bytes=_make_pdf(["A"]),
    )
    with pytest.raises(PdfMergeError, match="forbidden"):
        merge_user_pdfs([bad], config, output_path)


def test_user_name_empty_rejected(
    output_path: Path, config: PdfMergeConfig
) -> None:
    bad = UserPageSource(user_name="   ", a_page_pdf_bytes=_make_pdf(["A"]))
    with pytest.raises(PdfMergeError, match="empty"):
        merge_user_pdfs([bad], config, output_path)


def test_user_name_with_null_byte_rejected(
    output_path: Path, config: PdfMergeConfig
) -> None:
    bad = UserPageSource(user_name="tar\x00o", a_page_pdf_bytes=_make_pdf(["A"]))
    with pytest.raises(PdfMergeError, match="forbidden"):
        merge_user_pdfs([bad], config, output_path)


# --- PDF 読込時の破損 / 非PDF（splitter と同じ方針）-------------------


def test_corrupted_b_file_raises_pdf_merge_error(
    input_dir: Path, output_path: Path, config: PdfMergeConfig
) -> None:
    (input_dir / "B_u1.pdf").write_bytes(b"%PDF-1.4\ngarbage\n%%EOF")
    (input_dir / "C_u1.pdf").write_bytes(_make_pdf(["C"]))
    (input_dir / "D_common.pdf").write_bytes(_make_pdf(["D"]))

    with pytest.raises(PdfMergeError, match="Corrupted|Failed"):
        merge_user_pdfs([_user("u1")], config, output_path)


def test_encrypted_b_file_raises_pdf_merge_error(
    input_dir: Path, output_path: Path, config: PdfMergeConfig
) -> None:
    enc_path = input_dir / "B_u1.pdf"
    doc = fitz.open()
    try:
        doc.new_page(width=595.0, height=842.0).insert_text((50, 50), "x")
        doc.save(
            str(enc_path),
            encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw="o",
            user_pw="u",
        )
    finally:
        doc.close()
    (input_dir / "C_u1.pdf").write_bytes(_make_pdf(["C"]))
    (input_dir / "D_common.pdf").write_bytes(_make_pdf(["D"]))

    with pytest.raises(PdfMergeError, match="Encrypted"):
        merge_user_pdfs([_user("u1")], config, output_path)


# --- save 失敗時のアトミック性 -------------------------------------


def test_save_failure_does_not_corrupt_existing_output(
    input_dir: Path,
    output_path: Path,
    config: PdfMergeConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """merger 内部の _save_atomically が失敗しても既存 output_path を破壊しない。"""
    # fixture PDF と既存出力は monkeypatch 前に作成（_make_pdf は内部で save を呼ぶため）
    (input_dir / "B_u1.pdf").write_bytes(_make_pdf(["B"]))
    (input_dir / "C_u1.pdf").write_bytes(_make_pdf(["C"]))
    (input_dir / "D_common.pdf").write_bytes(_make_pdf(["D"]))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    existing_content = _make_pdf(["EXISTING"])
    output_path.write_bytes(existing_content)
    user_source = _user("u1")

    def failing_save(
        dst: fitz.Document, output: Path
    ) -> None:
        raise PdfMergeError(f"Failed to save merged PDF to {output}: disk full simulation")

    monkeypatch.setattr("wiseman_hub.pdf.merger._save_atomically", failing_save)

    with pytest.raises(PdfMergeError, match="save"):
        merge_user_pdfs([user_source], config, output_path)

    # 既存ファイルは破壊されていない
    assert output_path.read_bytes() == existing_content
    # 一時ファイルも残っていない
    leftover = [p.name for p in output_path.parent.iterdir() if p.name.startswith(".merge-")]
    assert leftover == []


def test_save_atomically_cleans_tempfile_on_save_error(tmp_path: Path) -> None:
    """_save_atomically の実装を直接テスト: save 失敗時に一時ファイルを掃除する。"""
    from wiseman_hub.pdf.merger import _save_atomically

    output = tmp_path / "out.pdf"
    existing = _make_pdf(["EXISTING"])
    output.write_bytes(existing)

    class FakeDoc:
        def save(self, path: str) -> None:
            # 一時ファイルが作られていることを確認してから失敗
            assert Path(path).exists()
            raise OSError("disk full")

    with pytest.raises(PdfMergeError, match="save"):
        _save_atomically(FakeDoc(), output)  # type: ignore[arg-type]

    # 既存ファイル保護
    assert output.read_bytes() == existing
    # 一時ファイル削除
    leftover = [p for p in tmp_path.iterdir() if p.name.startswith(".merge-")]
    assert leftover == []


# --- matched_b_path / matched_c_path override (タスク 8C PR #B) -----
#
# ConfirmDialog の手動選択 (MANUALLY_SELECTED) で選ばれたカスタムパスや、matcher が
# 自動特定したパスを merger に渡すための仕組み。指定があれば source_b_pattern 解決を
# バイパスし、そのパスから B/C を読み込む。指定無し (None) なら従来通り pattern 解決。


def _user_with_override(
    name: str,
    *,
    matched_b_path: str | None = None,
    matched_c_path: str | None = None,
) -> UserPageSource:
    return UserPageSource(
        user_name=name,
        a_page_pdf_bytes=_make_pdf([f"A:{name}"]),
        page_index=0,
        matched_b_path=matched_b_path,
        matched_c_path=matched_c_path,
    )


def test_matched_b_path_override_bypasses_pattern(
    input_dir: Path, tmp_path: Path, output_path: Path, config: PdfMergeConfig
) -> None:
    """user.matched_b_path 指定時は source_b_pattern を使わず指定パスから B を読む。"""
    # パターン解決で見つかるはずの B_u1.pdf はわざと作らない
    custom_b = tmp_path / "elsewhere" / "手動選択B.pdf"
    custom_b.parent.mkdir()
    custom_b.write_bytes(_make_pdf(["CUSTOM-B"]))
    (input_dir / "C_u1.pdf").write_bytes(_make_pdf(["C:u1"]))
    (input_dir / "D_common.pdf").write_bytes(_make_pdf(["D"]))

    user = _user_with_override("u1", matched_b_path=str(custom_b))
    report = merge_user_pdfs([user], config, output_path)

    assert report.missing_sources == []
    assert _page_texts(output_path) == ["A:u1", "CUSTOM-B", "C:u1", "D"]


def test_matched_c_path_override_bypasses_pattern(
    input_dir: Path, tmp_path: Path, output_path: Path, config: PdfMergeConfig
) -> None:
    custom_c = tmp_path / "elsewhere" / "C_override.pdf"
    custom_c.parent.mkdir()
    custom_c.write_bytes(_make_pdf(["CUSTOM-C"]))
    (input_dir / "B_u1.pdf").write_bytes(_make_pdf(["B:u1"]))
    (input_dir / "D_common.pdf").write_bytes(_make_pdf(["D"]))

    user = _user_with_override("u1", matched_c_path=str(custom_c))
    merge_user_pdfs([user], config, output_path)

    assert _page_texts(output_path) == ["A:u1", "B:u1", "CUSTOM-C", "D"]


def test_matched_path_none_falls_back_to_pattern(
    input_dir: Path, output_path: Path, config: PdfMergeConfig
) -> None:
    """matched_b_path/c_path=None なら従来通り pattern 解決（後方互換）。"""
    (input_dir / "B_u1.pdf").write_bytes(_make_pdf(["B:u1"]))
    (input_dir / "C_u1.pdf").write_bytes(_make_pdf(["C:u1"]))
    (input_dir / "D_common.pdf").write_bytes(_make_pdf(["D"]))

    user = _user_with_override("u1")  # override 両方 None
    merge_user_pdfs([user], config, output_path)

    assert _page_texts(output_path) == ["A:u1", "B:u1", "C:u1", "D"]


def test_matched_path_override_missing_file_recorded_as_missing(
    input_dir: Path, tmp_path: Path, output_path: Path, config: PdfMergeConfig
) -> None:
    """override 指定したがファイルが存在しない場合は missing_sources に記録（WARN）。

    pattern 解決でファイルが無い場合と同じ扱い。ConfirmDialog 終了後に該当ファイルが
    移動・削除された稀なケースを想定。
    """
    nonexistent = tmp_path / "moved-away.pdf"
    (input_dir / "C_u1.pdf").write_bytes(_make_pdf(["C:u1"]))
    (input_dir / "D_common.pdf").write_bytes(_make_pdf(["D"]))

    user = _user_with_override("u1", matched_b_path=str(nonexistent))
    report = merge_user_pdfs([user], config, output_path)

    assert report.missing_sources == [("u1", "B")]
    assert _page_texts(output_path) == ["A:u1", "C:u1", "D"]


# ===========================================================================
# Issue #75: merger._save_atomically のログ PII 非漏洩
# ===========================================================================


class TestSaveAtomicallyLogPiiDefense:
    """_save_atomically が失敗したとき、output_path / OSError str がログに出ないこと。

    Codex HIGH 指摘: 旧実装は `logger.error("Failed to save merged PDF to %s: %s", output_path, e)`
    で output_path + str(e) を出していた。出力 dir が PII を含むパス運用（例:
    `C:\\Users\\担当者\\介護記録\\利用者氏名\\`）では氏名がログに漏れる。
    """

    def test_save_failure_does_not_log_output_path(
        self,
        input_dir: Path,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import logging

        from wiseman_hub.pdf.merger import _save_atomically

        # 出力先ディレクトリに PII を含める
        pii_parent = tmp_path / "患者-佐藤次郎"
        pii_parent.mkdir()
        target = pii_parent / "merged.pdf"

        # fitz Document を渡すが、save で失敗させるため Document を close してから呼ぶ
        doc = fitz.open()
        doc.new_page(width=100, height=100)
        doc.close()  # → dst.save で例外発生

        with (
            caplog.at_level(logging.ERROR, logger="wiseman_hub.pdf.merger"),
            pytest.raises(PdfMergeError),
        ):
            _save_atomically(doc, target)

        # ログには型名のみ、path / 氏名は残らない
        assert "患者-佐藤次郎" not in caplog.text
        assert str(target) not in caplog.text
        # Error の事実と例外型名は残って良い
        assert "Failed to save merged PDF" in caplog.text

    def test_save_failure_exception_message_does_not_contain_path(
        self,
        input_dir: Path,
        tmp_path: Path,
    ) -> None:
        """PdfMergeError.__str__ に path / 例外 raw が含まれない。

        Future が未捕捉で stderr に traceback が出た場合（threading.excepthook 等）、
        exception message 側から PII が漏れないことを保証する（Codex HIGH 指摘）。
        """
        from wiseman_hub.pdf.merger import _save_atomically

        pii_parent = tmp_path / "患者-佐藤次郎"
        pii_parent.mkdir()
        target = pii_parent / "merged.pdf"

        doc = fitz.open()
        doc.new_page(width=100, height=100)
        doc.close()

        with pytest.raises(PdfMergeError) as exc_info:
            _save_atomically(doc, target)

        msg = str(exc_info.value)
        assert "患者-佐藤次郎" not in msg
        assert str(target) not in msg
        assert "save" in msg.lower()  # 型名 + "save" は残る（既存テスト互換）

    def test_save_failure_cause_chain_preserves_original_exception_type(
        self,
        input_dir: Path,
        tmp_path: Path,
    ) -> None:
        """`__cause__` には元例外が残る（debugging のため）が、PdfMergeError 本体は sanitized。

        保証範囲の明示: `__cause__` 経由で元例外 message (PII 含みうる) が traceback に
        出る経路は本 PR のスコープ外（Launcher / CLI が future.result / try-except で
        捕捉済みのため実運用では塞がっている）。型名チェーンの健全性のみ確認。
        """
        from wiseman_hub.pdf.merger import _save_atomically

        pii_parent = tmp_path / "患者-高橋次郎"
        pii_parent.mkdir()
        target = pii_parent / "merged.pdf"

        doc = fitz.open()
        doc.new_page(width=100, height=100)
        doc.close()

        with pytest.raises(PdfMergeError) as exc_info:
            _save_atomically(doc, target)

        # __cause__ は元例外を保持（デバッガビリティ維持）
        assert exc_info.value.__cause__ is not None
        # PdfMergeError 本体の repr / str 経路では PII が漏れない（message は sanitized）
        assert "患者-高橋次郎" not in repr(exc_info.value)
        assert "患者-高橋次郎" not in str(exc_info.value)
