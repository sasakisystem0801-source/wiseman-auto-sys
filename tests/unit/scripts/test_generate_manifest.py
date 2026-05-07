"""Tests for scripts/release/generate_manifest.py (ADR-016 PR-6 後半)。

Issue #215 (rating 9): production manifest 生成元の direct test 整備。
GitHub Actions release.yml から呼出される唯一の manifest.json 生成器なので、
引数 validation regression / sha256 計算誤り / field 欠落を direct test で gate する。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "release"
    / "generate_manifest.py"
)


@pytest.fixture(scope="module")
def gen_module() -> ModuleType:
    """generate_manifest.py を ad-hoc import (scripts/release/ は package ではない)。"""
    spec = importlib.util.spec_from_file_location("generate_manifest", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def dist_dir(tmp_path: Path) -> Path:
    """exe + sbom が揃った dist 相当 dir を作る (happy path 用)。"""
    d = tmp_path / "dist"
    d.mkdir()
    (d / "wiseman_hub.exe").write_bytes(b"FAKE_EXE_CONTENT_FOR_TEST")
    (d / "sbom.json").write_text('{"bomFormat":"CycloneDX"}', encoding="utf-8")
    return d


def _make_argv(
    *,
    output: Path,
    dist_dir: Path,
    version: str = "1.2.3",
    commit_sha: str = "0" * 40,
    tag: str = "v1.2.3",
    minimum_version: str | None = None,
) -> list[str]:
    argv = [
        "--version", version,
        "--commit-sha", commit_sha,
        "--tag", tag,
        "--output", str(output),
        "--dist-dir", str(dist_dir),
    ]
    if minimum_version is not None:
        argv += ["--minimum-version", minimum_version]
    return argv


# happy path -----------------------------------------------------------------


def test_happy_path_generates_full_manifest(
    gen_module: ModuleType, dist_dir: Path, tmp_path: Path
) -> None:
    """全 12 field 揃った manifest が生成される (深い output path = mkdir parents=True 検証込み)。"""
    output = tmp_path / "out" / "nested" / "manifest.json"
    rc = gen_module.main(_make_argv(output=output, dist_dir=dist_dir))
    assert rc == 0
    assert output.exists()
    data = json.loads(output.read_text(encoding="utf-8"))
    assert set(data.keys()) == {
        "current_version",
        "minimum_version",
        "download_url",
        "checksum_sha256",
        "commit_sha",
        "built_at",
        "released_at",
        "provenance_url",
        "expected_repo",
        "expected_workflow_ref",
        "sbom_url",
        "sbom_sha256",
    }
    assert data["current_version"] == "1.2.3"
    assert data["download_url"] == "versions/1.2.3/wiseman_hub.exe"
    assert data["provenance_url"] == "versions/1.2.3/wiseman_hub.exe.sigstore.json"
    assert data["sbom_url"] == "versions/1.2.3/sbom.json"
    assert data["expected_repo"] == "sasakisystem0801-source/wiseman-auto-sys"


# version validation ---------------------------------------------------------


@pytest.mark.parametrize("bad_version", ["v1.2.3", "v0.0.1", ""])
def test_version_with_v_prefix_or_empty_exits_2(
    gen_module: ModuleType,
    dist_dir: Path,
    tmp_path: Path,
    bad_version: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--version は plain semver 必須 (v prefix / 空 → exit 2)。"""
    output = tmp_path / "manifest.json"
    rc = gen_module.main(
        _make_argv(version=bad_version, output=output, dist_dir=dist_dir)
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "must be plain semver" in err
    assert not output.exists()


# missing artifact -----------------------------------------------------------


def test_missing_exe_exits_2(
    gen_module: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """exe 不在 → exit 2 + stderr ERROR。"""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "sbom.json").write_text("{}", encoding="utf-8")
    output = tmp_path / "manifest.json"
    rc = gen_module.main(_make_argv(output=output, dist_dir=dist))
    assert rc == 2
    err = capsys.readouterr().err
    assert "exe not found" in err
    assert not output.exists()


def test_missing_sbom_exits_2(
    gen_module: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """sbom 不在 → exit 2 + stderr ERROR。"""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "wiseman_hub.exe").write_bytes(b"FAKE")
    output = tmp_path / "manifest.json"
    rc = gen_module.main(_make_argv(output=output, dist_dir=dist))
    assert rc == 2
    err = capsys.readouterr().err
    assert "sbom not found" in err
    assert not output.exists()


# sha256 accuracy ------------------------------------------------------------


def test_sha256_matches_known_content(
    gen_module: ModuleType, tmp_path: Path
) -> None:
    """checksum_sha256 / sbom_sha256 が hashlib.sha256 と一致 (chunk read で binary が崩れないこと)。"""
    dist = tmp_path / "dist"
    dist.mkdir()
    exe_content = b"WISEMAN_HUB_EXE_TEST_CONTENT" * 100
    sbom_content = b'{"bomFormat":"CycloneDX","components":[]}'
    (dist / "wiseman_hub.exe").write_bytes(exe_content)
    (dist / "sbom.json").write_bytes(sbom_content)
    output = tmp_path / "manifest.json"
    rc = gen_module.main(_make_argv(output=output, dist_dir=dist))
    assert rc == 0
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["checksum_sha256"] == hashlib.sha256(exe_content).hexdigest()
    assert data["sbom_sha256"] == hashlib.sha256(sbom_content).hexdigest()


# workflow_ref ---------------------------------------------------------------


def test_workflow_ref_assembled_from_tag(
    gen_module: ModuleType, dist_dir: Path, tmp_path: Path
) -> None:
    """expected_workflow_ref が --tag から組立てられる (sigstore identity 検証で照合される値)。"""
    output = tmp_path / "manifest.json"
    rc = gen_module.main(
        _make_argv(tag="v9.8.7", version="9.8.7", output=output, dist_dir=dist_dir)
    )
    assert rc == 0
    data = json.loads(output.read_text(encoding="utf-8"))
    assert (
        data["expected_workflow_ref"]
        == ".github/workflows/release.yml@refs/tags/v9.8.7"
    )


# commit_sha lowercase -------------------------------------------------------


def test_commit_sha_lowercased(
    gen_module: ModuleType, dist_dir: Path, tmp_path: Path
) -> None:
    """大文字 commit_sha 入力 → 小文字保存 (Git は両方受け入れるが manifest は normalize)。"""
    output = tmp_path / "manifest.json"
    upper_sha = ("ABCDEF0123456789" * 2 + "ABCDEF01")
    assert len(upper_sha) == 40
    rc = gen_module.main(
        _make_argv(commit_sha=upper_sha, output=output, dist_dir=dist_dir)
    )
    assert rc == 0
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["commit_sha"] == upper_sha.lower()
    assert data["commit_sha"] != upper_sha


# minimum_version -----------------------------------------------------------


def test_minimum_version_default(
    gen_module: ModuleType, dist_dir: Path, tmp_path: Path
) -> None:
    """--minimum-version 省略時 default 0.0.1。"""
    output = tmp_path / "manifest.json"
    rc = gen_module.main(_make_argv(output=output, dist_dir=dist_dir))
    assert rc == 0
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["minimum_version"] == "0.0.1"


def test_minimum_version_override(
    gen_module: ModuleType, dist_dir: Path, tmp_path: Path
) -> None:
    """--minimum-version 明示指定で上書き。"""
    output = tmp_path / "manifest.json"
    rc = gen_module.main(
        _make_argv(output=output, dist_dir=dist_dir, minimum_version="1.0.0")
    )
    assert rc == 0
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["minimum_version"] == "1.0.0"
