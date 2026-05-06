"""SHA-256 検証 + provenance stub (ADR-016 PR-3)。

PR-3 範囲:
    - verify_sha256: 任意 local file に対する SHA-256 計算 + 定数時間比較
    - verify_provenance: 必ず ProvenanceUnavailable raise（"常に True" stub 禁止）

PR-6 で本実装:
    - in-toto attestation parse + Sigstore 検証 + GitHub workflow 一致確認
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 大きな exe を 1 MiB ずつ chunked read する（PyInstaller onefile は数十 MB）
_CHUNK = 1024 * 1024


class ChecksumError(Exception):
    """SHA-256 検証関連の失敗（一致しない、format 不正、file 不在等）。"""


class ProvenanceUnavailable(Exception):
    """provenance 検証は PR-3 では未実装、PR-6 で本実装。

    "常に True を返す stub" は誤った安全感を与える supply-chain risk のため
    明示的に raise する（codex Suggestion 5 反映）。
    """


def verify_sha256(local_file: Path, expected_hex: str) -> bool:
    """``local_file`` の SHA-256 を計算し ``expected_hex`` と一致比較する。

    比較は ``hmac.compare_digest`` で定数時間（timing attack 耐性、
    本ユースケースでは過剰だが習慣化目的で常用）。

    Args:
        local_file: 検証対象のローカルファイル
        expected_hex: 64 文字の hex（小文字）。大文字混在は normalize する

    Returns:
        一致した場合 True、不一致の場合 False

    Raises:
        FileNotFoundError: local_file が存在しない
        ChecksumError: expected_hex が 64 hex 形式でない
    """
    expected = expected_hex.strip().lower()
    if len(expected) != 64 or not all(c in "0123456789abcdef" for c in expected):
        raise ChecksumError("expected_hex must be 64 hex characters")

    if not local_file.exists():
        raise FileNotFoundError(f"local file not found: {local_file}")

    hasher = hashlib.sha256()
    with open(local_file, "rb") as f:
        while True:
            chunk = f.read(_CHUNK)
            if not chunk:
                break
            hasher.update(chunk)
    actual = hasher.hexdigest()
    return hmac.compare_digest(actual, expected)


def verify_provenance(artifact_path: Path, provenance_path: Path) -> None:
    """provenance 検証 (PR-6 で本実装)。

    PR-3 では呼ばれた時点で ``ProvenanceUnavailable`` を必ず raise する。
    "常に True" 系の sentinel 実装は supply-chain 防御として有害なため避ける。

    Args:
        artifact_path: 検証対象 artifact (PR-6 で SHA-256 突合に使用)
        provenance_path: in-toto attestation file (PR-6 で署名検証に使用)

    Raises:
        ProvenanceUnavailable: 常に raise（PR-3 では未実装）
    """
    # 引数を参照しないと vulture / ruff が unused warn を出すため、log で消費する。
    # （実装方針: `_` で受けるより signature を温存して PR-6 で実装差し替えやすくする）
    logger.debug(
        "verify_provenance not implemented yet (artifact=%s, provenance=%s)",
        artifact_path.name,
        provenance_path.name,
    )
    raise ProvenanceUnavailable("provenance verification is not implemented yet (PR-6)")
