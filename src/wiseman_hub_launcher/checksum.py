"""SHA-256 検証 (ADR-016 PR-3 → PR-6a で provenance 関連を `_supply_chain/` に移動)。

PR-6a 後の責務:
    - verify_sha256: 任意 local file に対する SHA-256 計算 + 定数時間比較

PR-3 で `verify_provenance` stub を保持していたが、PR-6a で本実装し
`_supply_chain/provenance.py` に移動。`ProvenanceUnavailable` も同 module 経由で参照。
"""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Issue #209 PR2: Sha256Hex を型注釈のみ import (runtime overhead ゼロ、circular 回避)。
    # checksum.py は stdlib only を維持、manifest.py は _supply_chain._http に依存するが
    # runtime には呼ばれない (verify_sha256 は引数注釈のみで Sha256Hex(...) 呼出なし)。
    from .manifest import Sha256Hex

# 大きな exe を 1 MiB ずつ chunked read する（PyInstaller onefile は数十 MB）
_CHUNK = 1024 * 1024


class ChecksumError(Exception):
    """SHA-256 検証関連の失敗（一致しない、format 不正、file 不在等）。"""


def verify_sha256(local_file: Path, expected_hex: Sha256Hex) -> bool:
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
