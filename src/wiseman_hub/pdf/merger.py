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
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import fitz

from wiseman_hub.config import VALID_CONCAT_LETTERS, PdfMergeConfig
from wiseman_hub.utils.atomic_io import save_atomically

logger = logging.getLogger(__name__)

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
    matched_b_path / matched_c_path: ConfirmDialog の手動選択や matcher の自動特定で
        得た B/C の絶対パス。``None`` なら従来通り ``source_b_pattern`` / ``source_c_pattern``
        で `input_dir` 配下を解決する。指定時はそちらが優先（pattern バイパス）。
    """

    user_name: str
    a_page_pdf_bytes: bytes
    page_index: int = 0
    matched_b_path: str | None = None
    matched_c_path: str | None = None


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


def _validate_concat_order(concat_order: Sequence[str]) -> None:
    """defensive layer: 値域は PdfMergeConfig.__post_init__ で先行検証済みだが、
    直接 merger を呼ぶ経路（テスト・デバッグ等）からの不正入力に備える。"""
    if not concat_order:
        raise ValueError("concat_order is empty; must contain at least one of A/B/C")
    unknown = [k for k in concat_order if k not in VALID_CONCAT_LETTERS]
    if unknown:
        raise ValueError(
            f"concat_order contains unknown kinds {unknown}; "
            f"allowed: {sorted(VALID_CONCAT_LETTERS)}"
        )


def _validate_user_name(user_name: str) -> None:
    """user_name を B/C ファイル名の埋込値として使うにあたって安全性を検証。

    OCR 由来のため通常は安全だが、誤認識や誤設定で path 脱出文字が入らないよう
    境界で確認する（defense-in-depth）。
    """
    # PII 防御: user_name 自体は氏名 = PII のため message に含めない（Issue #76）。
    # 保証範囲: PdfMergeError.__str__ から user_name を除外。
    # キーワード (empty/traversal/forbidden) は既存テスト互換のため保持。
    if not user_name or not user_name.strip():
        raise PdfMergeError("user_name is empty or whitespace-only")
    if ".." in user_name:
        raise PdfMergeError("user_name contains path traversal")
    if any(c in _FORBIDDEN_NAME_CHARS for c in user_name):
        raise PdfMergeError("user_name contains forbidden characters")


def _open_pdf_file_or_raise(path: Path, source_label: str) -> fitz.Document:
    """fitz.open の結果を PDF として安全に検証して返す。

    splitter._open_pdf_or_raise と同じ方針。破損・空・非PDF・暗号化を
    PdfMergeError に翻訳する。

    PII 防御（Issue #76）: path は氏名を含むパス運用で PII を含みうる。
    `source_label` は呼出側で kind (A/B/C/D) のみに制限してあるため安全。
    `{path}` / `{e}` は message から除外し、型名のみ残す（PR #77 _save_atomically 同パターン）。
    詳細が必要な場合は `__cause__` 経由で呼出側が取得する。
    """
    try:
        doc = fitz.open(path)
    except fitz.EmptyFileError as e:
        raise PdfMergeError(f"Empty PDF for {source_label} ({type(e).__name__})") from e
    except fitz.FileDataError as e:
        raise PdfMergeError(f"Corrupted PDF for {source_label} ({type(e).__name__})") from e
    except Exception as e:
        raise PdfMergeError(f"Failed to open PDF for {source_label} ({type(e).__name__})") from e

    try:
        if not doc.is_pdf:
            raise PdfMergeError(f"Not a PDF for {source_label}")
        if doc.needs_pass or doc.is_encrypted:
            raise PdfMergeError(
                f"Encrypted PDF for {source_label}. "
                f"Disable password protection before processing."
            )
    except Exception:
        doc.close()
        raise
    return doc


def _append_pdf_bytes(dst: fitz.Document, pdf_bytes: bytes, source_label: str) -> int:
    """dst に pdf_bytes を追記する。追加ページ数を返す。

    PII 防御（Issue #76）: `source_label` は呼出側で kind のみに制限済。
    `{e}` は型名に置換（PR #77 同パターン）。
    """
    try:
        src = fitz.open(stream=pdf_bytes, filetype="pdf")
    except fitz.EmptyFileError as e:
        raise PdfMergeError(
            f"Empty PDF stream for {source_label} ({type(e).__name__})"
        ) from e
    except fitz.FileDataError as e:
        raise PdfMergeError(
            f"Corrupted PDF stream for {source_label} ({type(e).__name__})"
        ) from e
    try:
        added = int(src.page_count)
        try:
            dst.insert_pdf(src)
        except MemoryError:
            raise
        except Exception as e:
            raise PdfMergeError(
                f"Failed to insert PDF pages for {source_label} ({type(e).__name__})"
            ) from e
        return added
    finally:
        src.close()


def _append_pdf_file(dst: fitz.Document, path: Path, source_label: str) -> int:
    """PDF ファイルを dst に追記する。

    PII 防御（Issue #76）: `path` / `{e}` は message から除外し、kind のみ残す。
    """
    src = _open_pdf_file_or_raise(path, source_label)
    try:
        added = int(src.page_count)
        try:
            dst.insert_pdf(src)
        except MemoryError:
            raise
        except Exception as e:
            raise PdfMergeError(
                f"Failed to insert PDF pages for {source_label} ({type(e).__name__})"
            ) from e
        return added
    finally:
        src.close()


def _resolve_bc_path(
    user: UserPageSource,
    kind: str,
    input_dir: Path,
    config: PdfMergeConfig,
) -> Path:
    """利用者1名の B/C PDF パスを決定する。

    override（`user.matched_b_path` / `user.matched_c_path`）が指定されていれば
    それを絶対パスとして採用し、`source_b_pattern` / `source_c_pattern` はバイパスする。
    override が None なら従来通り `input_dir / pattern.format(name=user.user_name)` を返す。
    """
    override = user.matched_b_path if kind == "B" else user.matched_c_path
    if override is not None:
        return Path(override)
    pattern = config.source_b_pattern if kind == "B" else config.source_c_pattern
    return input_dir / pattern.format(name=user.user_name)


def _save_atomically(dst: fitz.Document, output_path: Path) -> None:
    """``fitz.Document`` をアトミックに ``output_path`` に保存する。

    内部的には ``wiseman_hub.utils.atomic_io.save_atomically`` を使い、
    tempfile 作成 → ``dst.save`` → fsync → ``os.replace`` を実施する。
    save / replace どちらの失敗でも既存 ``output_path`` は壊さない。

    PII 防御:
        - logger 経路: 完全に型名のみ（Issue #75）
        - PdfMergeError.__str__: 型名 + "save" キーワードのみ
        - GUI Launcher 経路: ``future.result()`` で捕捉 → ``logger.error(type)`` のみ
          （src/wiseman_hub/ui/launcher.py::_on_phase_b_done）
        - CLI 経路: ``_cmd_merge`` で型名のみ表示（test_merge_user_pdfs_cli.py 既存）
        Known limitation:
        - ``raise ... from e`` のため ``__cause__`` chain に元例外 (OSError 等) の
          message が残り、Future 未捕捉 → threading.excepthook 経路で stderr に
          traceback が出る場合、__cause__ の str(e) から path が漏れうる。
          現状 GUI/CLI 両経路で ``future.result()`` / try-except で捕捉済みのため
          実運用経路では発生しないが、将来 async / subprocess 化する際は要再評価。
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        save_atomically(output_path, lambda tmp: dst.save(str(tmp)))
    except Exception as e:
        logger.error("Failed to save merged PDF: %s", type(e).__name__)
        raise PdfMergeError(f"Failed to save merged PDF ({type(e).__name__})") from e


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
                # PII 防御 (Issue #76): source_label は kind (A/B/C/D) のみに制限。
                # user_name を埋め込むと PdfMergeError message 経由で漏洩しうる。
                if kind == "A":
                    total_pages += _append_pdf_bytes(
                        dst, user.a_page_pdf_bytes, "A"
                    )
                else:
                    path = _resolve_bc_path(user, kind, input_dir, config)
                    if not path.exists():
                        # PII 防御: ログに氏名・パスを出さない（医療介護データ扱いのため）。
                        # 詳細は MergeReport.missing_sources に記録され、呼出側が
                        # 画面表示等の適切な経路で利用する。
                        logger.warning(
                            "Missing %s source for user %d/%d (skipping)",
                            kind,
                            user_idx + 1,
                            len(users),
                        )
                        missing.append((user.user_name, kind))
                        continue
                    total_pages += _append_pdf_file(dst, path, kind)

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
            # PII 防御: missing タプルには氏名が含まれるためログ出力しない。件数と kind 別集計のみ。
            b_missing = sum(1 for _, k in missing if k == "B")
            c_missing = sum(1 for _, k in missing if k == "C")
            logger.error(
                "merge_user_pdfs completed with %d missing sources (B=%d, C=%d); "
                "downstream callers MUST inspect MergeReport.missing_sources.",
                len(missing),
                b_missing,
                c_missing,
            )
        logger.info(
            "merge_user_pdfs done: users=%d pages=%d missing=%d",
            len(users),
            total_pages,
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
