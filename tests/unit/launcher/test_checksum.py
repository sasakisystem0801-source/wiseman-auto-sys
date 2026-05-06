"""Tests for wiseman_hub_launcher.checksum (ADR-016 PR-3)。"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from wiseman_hub_launcher.checksum import (
    ChecksumError,
    ProvenanceUnavailable,
    verify_provenance,
    verify_sha256,
)


def test_verify_sha256_match(tmp_path: Path) -> None:
    payload = b"hello world\n"
    expected = hashlib.sha256(payload).hexdigest()
    f = tmp_path / "data.bin"
    f.write_bytes(payload)
    assert verify_sha256(f, expected) is True


def test_verify_sha256_mismatch(tmp_path: Path) -> None:
    f = tmp_path / "data.bin"
    f.write_bytes(b"hello world\n")
    expected = hashlib.sha256(b"different content").hexdigest()
    assert verify_sha256(f, expected) is False


def test_verify_sha256_missing_file(tmp_path: Path) -> None:
    expected = "a" * 64
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
    f = tmp_path / "data.bin"
    f.write_bytes(b"x")
    with pytest.raises(ChecksumError, match="64 hex"):
        verify_sha256(f, bad_hex)


def test_verify_sha256_uppercase_normalized(tmp_path: Path) -> None:
    payload = b"abc"
    expected = hashlib.sha256(payload).hexdigest().upper()
    f = tmp_path / "data.bin"
    f.write_bytes(payload)
    # uppercase は normalize されるので一致すべき
    assert verify_sha256(f, expected) is True


def test_verify_sha256_large_chunked(tmp_path: Path) -> None:
    """1 MiB chunk 境界を跨いでも正しく hash される。"""
    payload = b"A" * (1024 * 1024 * 2 + 17)  # 2 MiB + 17 bytes
    expected = hashlib.sha256(payload).hexdigest()
    f = tmp_path / "big.bin"
    f.write_bytes(payload)
    assert verify_sha256(f, expected) is True


def test_verify_provenance_always_raises(tmp_path: Path) -> None:
    """PR-3 では provenance 検証は未実装であり、必ず ProvenanceUnavailable を raise する。"""
    art = tmp_path / "wiseman_hub.exe"
    art.write_bytes(b"fake exe")
    prov = tmp_path / "provenance.intoto.jsonl"
    prov.write_bytes(b"{}")
    with pytest.raises(ProvenanceUnavailable, match="not implemented yet"):
        verify_provenance(art, prov)


def test_verify_provenance_raises_even_for_missing_files(tmp_path: Path) -> None:
    """PR-3 stub は引数の存在に関わらず必ず raise する（"常に True" stub 禁止）。"""
    with pytest.raises(ProvenanceUnavailable):
        verify_provenance(tmp_path / "nope.exe", tmp_path / "nope.jsonl")
