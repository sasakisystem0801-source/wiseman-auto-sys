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


def _provenance_kwargs(*, expected_sha256: str | None = None) -> dict[str, str]:
    """verify_provenance の必須 keyword 引数（I-6 で signature 拡張済）。"""
    return {
        "expected_sha256": expected_sha256 or ("a" * 64),
        "expected_repo": "sasakisystem0801-source/wiseman-auto-sys",
        "expected_workflow_ref": ".github/workflows/release.yml@refs/heads/main",
        "expected_commit_sha": "f976b44",
    }


def test_verify_provenance_always_raises(tmp_path: Path) -> None:
    """PR-3 では provenance 検証は未実装、必ず ProvenanceUnavailable を raise する。"""
    art = tmp_path / "wiseman_hub.exe"
    art.write_bytes(b"fake exe")
    prov = tmp_path / "provenance.intoto.jsonl"
    prov.write_bytes(b"{}")
    with pytest.raises(ProvenanceUnavailable, match="not implemented yet"):
        verify_provenance(art, prov, **_provenance_kwargs())


def test_verify_provenance_raises_even_for_missing_files(tmp_path: Path) -> None:
    """PR-3 stub は引数の存在に関わらず必ず raise する（"常に True" stub 禁止）。"""
    with pytest.raises(ProvenanceUnavailable):
        verify_provenance(
            tmp_path / "nope.exe",
            tmp_path / "nope.jsonl",
            **_provenance_kwargs(),
        )


# I-6: verify_provenance signature 拡張 -----------------------------------

def test_verify_provenance_accepts_pin_kwargs(tmp_path: Path) -> None:
    """I-6: PR-6 で必要な pin 引数が signature に含まれている。"""
    art = tmp_path / "wiseman_hub.exe"
    art.write_bytes(b"fake")
    prov = tmp_path / "p.intoto.jsonl"
    prov.write_bytes(b"{}")
    # PR-3 stub は raise するが、signature 自体は受け付ける
    with pytest.raises(ProvenanceUnavailable):
        verify_provenance(
            art,
            prov,
            expected_sha256="b" * 64,
            expected_repo="org/repo",
            expected_workflow_ref=".github/workflows/build.yml@refs/heads/main",
            expected_commit_sha="abcdef1234567890abcdef1234567890abcdef12",
            expected_issuer="https://token.actions.githubusercontent.com",
        )


def test_verify_provenance_optional_commit_sha_defaults_none(tmp_path: Path) -> None:
    """I-6: expected_commit_sha は optional（None でも signature OK）。"""
    art = tmp_path / "x"
    art.write_bytes(b"x")
    prov = tmp_path / "p"
    prov.write_bytes(b"{}")
    with pytest.raises(ProvenanceUnavailable):
        verify_provenance(
            art,
            prov,
            expected_sha256="a" * 64,
            expected_repo="org/repo",
            expected_workflow_ref=".github/workflows/build.yml@refs/heads/main",
            # expected_commit_sha 省略 → None default
            # expected_issuer 省略 → GitHub default
        )
