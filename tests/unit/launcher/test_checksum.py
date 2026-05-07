"""Tests for wiseman_hub_launcher.checksum (ADR-016 PR-3 → PR-6a → Issue #209 PR2)。

PR-6a: verify_provenance を `_supply_chain/provenance.py` に移動 + 本実装。
本 file は verify_sha256 のみテスト、provenance 検証 test は test_provenance.py へ。

Issue #209 PR2: verify_sha256 を Sha256Hex 受けに変更。test fixture も Sha256Hex 化、
形式不正 path は cast() で型 bypass して runtime 二重検証 (ChecksumError raise) を確認。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import cast

import pytest

from wiseman_hub_launcher.checksum import ChecksumError, verify_sha256
from wiseman_hub_launcher.manifest import Sha256Hex, make_sha256hex


def test_verify_sha256_match(tmp_path: Path) -> None:
    payload = b"hello world\n"
    expected = make_sha256hex(hashlib.sha256(payload).hexdigest())
    f = tmp_path / "data.bin"
    f.write_bytes(payload)
    assert verify_sha256(f, expected) is True


def test_verify_sha256_mismatch(tmp_path: Path) -> None:
    f = tmp_path / "data.bin"
    f.write_bytes(b"hello world\n")
    expected = make_sha256hex(hashlib.sha256(b"different content").hexdigest())
    assert verify_sha256(f, expected) is False


def test_verify_sha256_missing_file(tmp_path: Path) -> None:
    expected = make_sha256hex("a" * 64)
    with pytest.raises(FileNotFoundError):
        verify_sha256(tmp_path / "does-not-exist.bin", expected)


@pytest.mark.parametrize(
    "bad_hex",
    [
        "tooshort",
        "g" * 64,        # non-hex chars
        "a" * 63,         # 63 chars
        "a" * 65,         # 65 chars
        "",
    ],
)
def test_verify_sha256_invalid_expected_hex(tmp_path: Path, bad_hex: str) -> None:
    """Issue #209 PR2: 型 system を bypass した値でも runtime 二重検証で弾く。

    本 PR で verify_sha256 signature を Sha256Hex に変更したが、test fixture や
    test_helpers が cast() で形式不正値を渡すケースを想定し、関数本体の
    `len != 64 / non-hex chars` runtime check が残っていることを確認する。
    型 gate (mypy) と runtime gate (ChecksumError) は冗長ではなく fail-close 二重防御。
    """
    f = tmp_path / "data.bin"
    f.write_bytes(b"x")
    with pytest.raises(ChecksumError, match="64 hex"):
        verify_sha256(f, cast(Sha256Hex, bad_hex))


def test_verify_sha256_uppercase_normalized(tmp_path: Path) -> None:
    """uppercase 値は make_sha256hex を通れない (lowercase 強制) ため cast bypass。

    Issue #209 PR2: make_sha256hex は 64 lowercase hex のみ受ける。本テストは
    verify_sha256 内部の uppercase normalize 動作を検証するため、`cast(Sha256Hex, ...)`
    で型 gate を意図的に飛ばす (runtime に uppercase 値が verify_sha256 の `.lower()`
    正規化で一致することを確認)。
    """
    payload = b"abc"
    expected_upper = hashlib.sha256(payload).hexdigest().upper()
    f = tmp_path / "data.bin"
    f.write_bytes(payload)
    # uppercase は normalize されるので一致すべき
    assert verify_sha256(f, cast(Sha256Hex, expected_upper)) is True


def test_verify_sha256_large_chunked(tmp_path: Path) -> None:
    """1 MiB chunk 境界を跨いでも正しく hash される。"""
    payload = b"A" * (1024 * 1024 * 2 + 17)  # 2 MiB + 17 bytes
    expected = make_sha256hex(hashlib.sha256(payload).hexdigest())
    f = tmp_path / "big.bin"
    f.write_bytes(payload)
    assert verify_sha256(f, expected) is True
