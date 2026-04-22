"""アトミック書込ユーティリティ。

同一ディレクトリに tempfile を作成 → fsync → ``os.replace`` で差し替える共通実装。
クラッシュや ``os.replace`` 失敗時も既存 target を破壊しない。

責務範囲:
    - 低レベル I/O（tempfile 作成、fsync、os.replace、tmp cleanup）のみ
    - ドメイン例外（PdfMergeError 等）へのラップは呼び出し元責務
    - 親ディレクトリ作成は呼び出し元責務（mkdir / ensure_private_dir / create_if_missing
      などの契約が呼び出し元ごとに異なるため）
    - ログには path / 例外 message を出さない（PII/API key 防御）

挙動契約:
    - 成功時: target が置換され、tmp ファイルは残らない
    - 失敗時: 既存 target は保たれ、tmp ファイルは可能な限り削除、元例外を再送出
    - BaseException（KeyboardInterrupt 等）でも tmp cleanup を実施してから伝播
"""

from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)

_TMP_PREFIX = "."
_TMP_SUFFIX = ".tmp"


def _cleanup_tmp(tmp_path: Path) -> None:
    """tmp ファイルを best-effort で削除する。

    失敗しても呼び出し元に伝播させない（元例外を優先させるため）。
    ログには path / 例外 message を出さず、型名のみ（PII 防御）。
    """
    try:
        tmp_path.unlink(missing_ok=True)
    except OSError as e:
        logger.warning("Failed to clean up tmp file: %s", type(e).__name__)


def write_bytes_atomically(
    target: Path,
    payload: bytes,
    *,
    prefix: str = _TMP_PREFIX,
) -> None:
    """``payload`` を ``target`` にアトミックに書き込む（fsync 標準）。

    target と同じディレクトリに tempfile を作成し、write → flush → fsync →
    ``os.replace`` の順で差し替える。``os.replace`` は同一ファイルシステム上で
    atomic（Windows/POSIX とも保証）。

    親ディレクトリは事前に存在している必要がある（呼び出し元で作成）。

    Args:
        target: 最終的に配置する path
        payload: 書き込む bytes
        prefix: tempfile 名の prefix。既定は ``"."`` だが、呼び出し元が過去クラッシュ
            残留 tmp を sweep するために独自パターンを必要とする場合に指定する
            （例: ``config.py`` の ``_sweep_stale_tmp`` が ``{path.name}.*.tmp`` を
            前提にしているため ``prefix=path.name + "."`` を渡す）。

    Raises:
        OSError: tempfile 作成・書込・fsync・replace 失敗時（元例外をそのまま伝播）
    """
    fd, tmp_name = tempfile.mkstemp(
        prefix=prefix, suffix=_TMP_SUFFIX, dir=str(target.parent)
    )
    # fd は即座に close し、以降は path 経由で再オープンする。save_atomically と
    # 構造を揃えることで fd lifetime の非対称性を排除する。
    os.close(fd)
    tmp_path = Path(tmp_name)
    success = False
    try:
        with open(tmp_path, "wb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, target)
        success = True
    finally:
        if not success:
            _cleanup_tmp(tmp_path)


def save_atomically(
    target: Path,
    writer: Callable[[Path], None],
    *,
    fsync: bool = True,
    prefix: str = _TMP_PREFIX,
) -> None:
    """``writer`` に tmp path を渡して書き込ませ、成功時に ``target`` と差し替える。

    外部ライブラリ（PyMuPDF の ``fitz.Document.save`` 等）が自前で path を開いて
    書き込むケース向け。writer 成功後、fsync=True ならファイルを再オープンして
    ``os.fsync`` を適用してから ``os.replace`` する。

    親ディレクトリは事前に存在している必要がある（呼び出し元で作成）。

    Args:
        target: 最終的に配置する path
        writer: tmp Path を受け取り、そこに書き込む callback
        fsync: True の場合、writer 完了後に tmp を再オープンして fsync する
        prefix: tempfile 名の prefix（呼び出し元の sweep パターンと整合させたい場合に指定）

    Raises:
        Exception: writer / fsync / replace 失敗時（元例外をそのまま伝播）
    """
    fd, tmp_name = tempfile.mkstemp(
        prefix=prefix, suffix=_TMP_SUFFIX, dir=str(target.parent)
    )
    os.close(fd)
    tmp_path = Path(tmp_name)
    success = False
    try:
        writer(tmp_path)
        if fsync:
            # "r+b" で書込可能 FD を確保し、POSIX 実装依存の「read-only FD では
            # metadata 同期を保証しない」挙動を回避する。
            with open(tmp_path, "r+b") as f:
                os.fsync(f.fileno())
        os.replace(tmp_path, target)
        success = True
    finally:
        if not success:
            _cleanup_tmp(tmp_path)
