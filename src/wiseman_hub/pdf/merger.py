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

書込の原子性: 一時ファイルに書き出してから `os.replace` で差し替える。
ディスクフル等で失敗しても既存 output_path は破壊されない。

詳細は ADR-008 / docs/handoff/LATEST.md 参照。
"""

from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import fitz

from wiseman_hub.config import PdfMergeConfig

logger = logging.getLogger(__name__)

_KNOWN_KINDS = frozenset({"A", "B", "C"})
# user_name に含まれてはいけない文字（パス操作・ヌルバイト）
_FORBIDDEN_NAME_CHARS = frozenset("/\\\x00")


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

    @property
    def has_missing_sources(self) -> bool:
        return bool(self.missing_sources)


def _validate_concat_order(concat_order: list[str]) -> None:
    if not concat_order:
        raise ValueError("concat_order is empty; must contain at least one of A/B/C")
    unknown = [k for k in concat_order if k not in _KNOWN_KINDS]
    if unknown:
        raise ValueError(
            f"concat_order contains unknown kinds {unknown}; allowed: {sorted(_KNOWN_KINDS)}"
        )


def _validate_user_name(user_name: str) -> None:
    """user_name を B/C ファイル名の埋込値として使うにあたって安全性を検証。

    OCR 由来のため通常は安全だが、誤認識や誤設定で path 脱出文字が入らないよう
    境界で確認する（defense-in-depth）。
    """
    if not user_name or not user_name.strip():
        raise PdfMergeError("user_name is empty or whitespace-only")
    if ".." in user_name:
        raise PdfMergeError(f"user_name contains path traversal: {user_name!r}")
    bad = sorted({c for c in user_name if c in _FORBIDDEN_NAME_CHARS})
    if bad:
        raise PdfMergeError(
            f"user_name contains forbidden characters {bad}: {user_name!r}"
        )


def _open_pdf_file_or_raise(path: Path, source_label: str) -> fitz.Document:
    """fitz.open の結果を PDF として安全に検証して返す。

    splitter._open_pdf_or_raise と同じ方針。破損・空・非PDF・暗号化を
    PdfMergeError に翻訳する。
    """
    try:
        doc = fitz.open(path)
    except fitz.EmptyFileError as e:
        raise PdfMergeError(f"Empty PDF for {source_label}: {path}") from e
    except fitz.FileDataError as e:
        raise PdfMergeError(f"Corrupted PDF for {source_label}: {path}") from e
    except Exception as e:
        raise PdfMergeError(f"Failed to open PDF for {source_label}: {path}: {e}") from e

    try:
        if not doc.is_pdf:
            raise PdfMergeError(f"Not a PDF for {source_label}: {path}")
        if doc.needs_pass or doc.is_encrypted:
            raise PdfMergeError(
                f"Encrypted PDF for {source_label}: {path}. "
                f"Disable password protection before processing."
            )
    except Exception:
        doc.close()
        raise
    return doc


def _append_pdf_bytes(dst: fitz.Document, pdf_bytes: bytes, source_label: str) -> int:
    """dst に pdf_bytes を追記する。追加ページ数を返す。"""
    try:
        src = fitz.open(stream=pdf_bytes, filetype="pdf")
    except fitz.EmptyFileError as e:
        raise PdfMergeError(f"Empty PDF stream for {source_label}") from e
    except fitz.FileDataError as e:
        raise PdfMergeError(f"Corrupted PDF stream for {source_label}") from e
    try:
        added = int(src.page_count)
        try:
            dst.insert_pdf(src)
        except MemoryError:
            raise
        except Exception as e:
            raise PdfMergeError(
                f"Failed to insert PDF pages for {source_label}: {e}"
            ) from e
        return added
    finally:
        src.close()


def _append_pdf_file(dst: fitz.Document, path: Path, source_label: str) -> int:
    src = _open_pdf_file_or_raise(path, source_label)
    try:
        added = int(src.page_count)
        try:
            dst.insert_pdf(src)
        except MemoryError:
            raise
        except Exception as e:
            raise PdfMergeError(
                f"Failed to insert PDF pages for {source_label} from {path}: {e}"
            ) from e
        return added
    finally:
        src.close()


def _save_atomically(dst: fitz.Document, output_path: Path) -> None:
    """一時ファイルに保存してから os.replace で差し替える。

    save 失敗時に既存 output_path を壊さない。
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_name = tempfile.mkstemp(
        suffix=".pdf", prefix=".merge-", dir=str(output_path.parent)
    )
    os.close(tmp_fd)
    tmp_path = Path(tmp_name)
    try:
        dst.save(str(tmp_path))
    except Exception as e:
        tmp_path.unlink(missing_ok=True)
        logger.error("Failed to save merged PDF to %s: %s", output_path, e)
        raise PdfMergeError(f"Failed to save merged PDF to {output_path}: {e}") from e
    os.replace(tmp_path, output_path)


def merge_user_pdfs(
    users: list[UserPageSource],
    config: PdfMergeConfig,
    output_path: Path,
) -> MergeReport:
    """利用者ごとに concat_order で A/B/C を結合、末尾に D を1回追加する。

    Raises:
        ValueError: concat_order が空/未知、input_dir 未設定、または出力が0ページ
        FileNotFoundError: D が設定されているが存在しない
        PdfMergeError: user_name 不正、PDF 読込/書込失敗
    """
    _validate_concat_order(config.concat_order)
    if not config.input_dir:
        raise ValueError(
            "PdfMergeConfig.input_dir is empty; must point to the directory "
            "containing B/C/D PDF files"
        )

    input_dir = Path(config.input_dir)
    missing: list[tuple[str, str]] = []
    total_pages = 0

    dst = fitz.open()
    try:
        for user_idx, user in enumerate(users):
            _validate_user_name(user.user_name)
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
                            "Missing %s source for user %d/%d %r: %s (skipping)",
                            kind,
                            user_idx + 1,
                            len(users),
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

        _save_atomically(dst, output_path)
        if missing:
            logger.error(
                "merge_user_pdfs completed with %d missing sources; "
                "downstream callers MUST inspect MergeReport.missing_sources. "
                "First 5: %s",
                len(missing),
                missing[:5],
            )
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
