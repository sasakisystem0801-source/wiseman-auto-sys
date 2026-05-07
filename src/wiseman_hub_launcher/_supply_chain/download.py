"""HTTPS chunked download + size cap + atomic place (ADR-016 PR-4 → PR-6a で分離)。

PR-6a (codex C-1 反映): provenance file (.sigstore.json) も同経路で download。
"""

from __future__ import annotations

import contextlib
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from .._runtime._atomic_io import atomic_replace_and_fsync_dir
from ..checksum import ChecksumError, verify_sha256
from ._http import open_https_get

logger = logging.getLogger(__name__)


# I-1: download size cap (改竄 manifest や誤設定での DoS 防御)
MAX_ARTIFACT_BYTES = 300 * 1024 * 1024  # 300 MiB
# provenance file は数 KB 想定、上限を厳しく
MAX_PROVENANCE_BYTES = 1 * 1024 * 1024  # 1 MiB
_CHUNK = 1024 * 1024  # 1 MiB


class DownloadError(Exception):
    """artifact / provenance download 失敗 (network / size cap / IO)。"""


def _read_to_temp_with_cap(resp: Any, fd: int, cap_bytes: int) -> int:  # noqa: ANN401
    """resp から fd へ chunked 書込し、累計バイト数を返す (I-1: cap)。

    fd は os.fdopen で wrap して fsync 後に close される。caller は fd を再 close しない。
    """
    total = 0
    with os.fdopen(fd, "wb") as f:
        while True:
            chunk = resp.read(_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > cap_bytes:
                raise DownloadError(f"artifact body exceeds {cap_bytes} bytes")
            f.write(chunk)
        f.flush()
        os.fsync(f.fileno())
    return total


def _download_with_atomic_place(
    url: str,
    dest_dir: Path,
    final_name: str,
    *,
    cap_bytes: int,
    timeout_sec: int,
    expected_sha256: str | None,
) -> Path:
    """URL から download し atomic 配置する共通実装。

    Args:
        url: HTTPS の完全 URL
        dest_dir: 配置先ディレクトリ (mkdir parents=True で自動作成)
        final_name: 配置後のファイル名 (例: "wiseman_hub.exe")
        cap_bytes: download 上限 (DoS 防御)
        timeout_sec: HTTPS request timeout
        expected_sha256: 期待 SHA-256 (None なら検証 skip。provenance file は None)

    Returns:
        配置された final path

    Raises:
        DownloadError / ChecksumError
    """
    final_path = dest_dir / final_name
    fd: int = -1
    tmp_path: Path | None = None
    fd_owned = False
    success = False

    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=".artifact.", suffix=".tmp", dir=str(dest_dir)
        )
        tmp_path = Path(tmp_name)
        fd_owned = True

        resp = open_https_get(
            url,
            timeout_sec=timeout_sec,
            error_class=DownloadError,
            label="artifact",
        )
        try:
            try:
                content_length = int(resp.headers.get("Content-Length", "0") or "0")
            except (ValueError, TypeError):
                content_length = 0
            if content_length > cap_bytes:
                raise DownloadError(
                    f"Content-Length {content_length} exceeds {cap_bytes} bytes"
                )

            # ownership 移譲を呼び出し前に確定させて double-close を回避
            fd_owned = False
            _read_to_temp_with_cap(resp, fd, cap_bytes)
        finally:
            with contextlib.suppress(AttributeError, OSError):
                resp.close()

        if expected_sha256 is not None and not verify_sha256(tmp_path, expected_sha256):
            raise ChecksumError(
                f"artifact SHA-256 mismatch (expected {expected_sha256[:8]}...)"
            )

        atomic_replace_and_fsync_dir(tmp_path, final_path, dest_dir)
        success = True
    except OSError as e:
        # review_team A5 second-pass: errno / winerror / filename を含めて Windows AV /
        # NAS / sharing violation 等を debug 可能にする
        raise DownloadError(
            f"artifact write error: {type(e).__name__}: "
            f"errno={e.errno} winerror={getattr(e, 'winerror', None)} "
            f"filename={e.filename!r}: {e}"
        ) from e
    finally:
        if fd_owned:
            with contextlib.suppress(OSError):
                os.close(fd)
        if not success and tmp_path is not None:
            with contextlib.suppress(OSError):
                tmp_path.unlink(missing_ok=True)

    return final_path


def download_artifact(
    artifact_url: str,
    dest_dir: Path,
    expected_sha256: str,
    *,
    timeout_sec: int = 60,
) -> Path:
    """artifact (wiseman_hub.exe) を download + SHA-256 検証 + atomic 配置。

    Returns:
        配置された artifact の絶対 path (`{dest_dir}/wiseman_hub.exe`)

    Raises:
        DownloadError: HTTPS / size cap / IO
        ChecksumError: SHA-256 不一致
    """
    return _download_with_atomic_place(
        artifact_url,
        dest_dir,
        "wiseman_hub.exe",
        cap_bytes=MAX_ARTIFACT_BYTES,
        timeout_sec=timeout_sec,
        expected_sha256=expected_sha256,
    )


def download_provenance(
    provenance_url: str,
    dest_dir: Path,
    *,
    timeout_sec: int = 30,
) -> Path:
    """provenance file (.sigstore.json 等) を download + atomic 配置 (PR-6a)。

    SHA-256 検証は不実施 (provenance 自体が attestation で、SLSA statement の
    subject digest が artifact SHA-256 と突合される)。

    Returns:
        配置された provenance の絶対 path (`{dest_dir}/wiseman_hub.exe.sigstore.json`)
    """
    return _download_with_atomic_place(
        provenance_url,
        dest_dir,
        "wiseman_hub.exe.sigstore.json",
        cap_bytes=MAX_PROVENANCE_BYTES,
        timeout_sec=timeout_sec,
        expected_sha256=None,
    )
