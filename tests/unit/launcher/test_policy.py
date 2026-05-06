"""Tests for wiseman_hub_launcher._supply_chain.policy (ADR-016 PR-6a)。

C5 (pr-test-analyzer Critical): policy.py の direct test を追加。
PR-6a 実装中は update_and_spawn / __main__ 経路で patch mock していたため、
canonical URL 検証 (C-1) と二重 gate (C-2) のロジックが直接テストされていなかった。
"""

from __future__ import annotations

import pytest

from wiseman_hub_launcher._supply_chain.policy import (
    LAUNCHER_EXPECTED_REPO,
    PROVENANCE_URL_SUFFIX,
    RELEASE_BUCKET_BASE,
    derive_canonical_provenance_url,
    is_production_build,
    is_test_bypass_authorized,
    validate_canonical_provenance_url,
)

# derive_canonical_provenance_url ----------------------------------------------


def test_derive_canonical_appends_sigstore_suffix() -> None:
    """T0 Explore + Q1-A: artifact_url + ".sigstore.json" が canonical。"""
    artifact = RELEASE_BUCKET_BASE + "versions/1.2.3/wiseman_hub.exe"
    assert (
        derive_canonical_provenance_url(artifact)
        == artifact + PROVENANCE_URL_SUFFIX
    )
    assert PROVENANCE_URL_SUFFIX == ".sigstore.json"


# validate_canonical_provenance_url -------------------------------------------


def _release_artifact(version: str = "1.2.3") -> str:
    return RELEASE_BUCKET_BASE + f"versions/{version}/wiseman_hub.exe"


def _release_provenance(version: str = "1.2.3") -> str:
    return _release_artifact(version) + PROVENANCE_URL_SUFFIX


def test_validate_canonical_accepts_exact_match() -> None:
    """正常系: artifact + ".sigstore.json" が canonical で一致 → 例外なし。"""
    art = _release_artifact()
    prov = _release_provenance()
    validate_canonical_provenance_url(prov, art)


def test_validate_canonical_rejects_non_string() -> None:
    """str 以外 → ValueError (PR-6a で ProvenanceError に wrap される、updater.py で)。"""
    with pytest.raises(ValueError, match="must be str"):
        validate_canonical_provenance_url(123, _release_artifact())  # type: ignore[arg-type]


def test_validate_canonical_rejects_http_scheme() -> None:
    """C-1: HTTPS でない URL は reject。"""
    art = _release_artifact()
    bad = art.replace("https://", "http://") + PROVENANCE_URL_SUFFIX
    with pytest.raises(ValueError, match="HTTPS scheme"):
        validate_canonical_provenance_url(bad, art)


def test_validate_canonical_rejects_outside_release_bucket() -> None:
    """C-1: release-prod bucket 外の URL は reject。"""
    art = _release_artifact()
    bad = (
        "https://storage.googleapis.com/wiseman-hub-other-bucket/"
        f"versions/1.2.3/wiseman_hub.exe{PROVENANCE_URL_SUFFIX}"
    )
    with pytest.raises(ValueError, match="release-prod bucket"):
        validate_canonical_provenance_url(bad, art)


def test_validate_canonical_rejects_mismatched_suffix() -> None:
    """C-1: canonical でない suffix (.intoto.jsonl 等) は reject。"""
    art = _release_artifact()
    bad = art + ".intoto.jsonl"  # 旧 PR-3 形式
    with pytest.raises(ValueError, match="does not match canonical"):
        validate_canonical_provenance_url(bad, art)


def test_validate_canonical_rejects_path_hijack() -> None:
    """C-1: artifact URL とは別 path に向ける改竄を reject。"""
    art = _release_artifact("1.2.3")
    other_art = _release_artifact("9.9.9")
    bad = other_art + PROVENANCE_URL_SUFFIX  # 別 version の provenance
    with pytest.raises(ValueError, match="does not match canonical"):
        validate_canonical_provenance_url(bad, art)


def test_validate_canonical_rejects_arbitrary_path_in_bucket() -> None:
    """C-1: release-prod bucket 内でも canonical でない path は reject。"""
    art = _release_artifact()
    bad = RELEASE_BUCKET_BASE + "evil/anywhere.sigstore.json"
    with pytest.raises(ValueError, match="does not match canonical"):
        validate_canonical_provenance_url(bad, art)


# is_test_bypass_authorized (C-2 二重 gate の env var 評価) -----------------------


def test_is_test_bypass_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """env var 未設定 → False (本番 PC の default 状態)。"""
    monkeypatch.delenv("WISEMAN_ALLOW_UNSIGNED_PROVENANCE_FOR_TESTS", raising=False)
    assert is_test_bypass_authorized() is False


def test_is_test_bypass_value_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """env var=1 → True (test/dev 環境のみ)。"""
    monkeypatch.setenv("WISEMAN_ALLOW_UNSIGNED_PROVENANCE_FOR_TESTS", "1")
    assert is_test_bypass_authorized() is True


@pytest.mark.parametrize(
    "value",
    ["true", "yes", "0", "TRUE", " 1", "1 ", "", "false"],
)
def test_is_test_bypass_other_values(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """env var=1 以外の値 → False (誤設定で本番 PC が緩むのを防止)。"""
    monkeypatch.setenv("WISEMAN_ALLOW_UNSIGNED_PROVENANCE_FOR_TESTS", value)
    assert is_test_bypass_authorized() is False


# is_production_build ---------------------------------------------------------


def test_is_production_build_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """WISEMAN_BUILD_FLAVOR 未設定 → False (dev / test default)。"""
    monkeypatch.delenv("WISEMAN_BUILD_FLAVOR", raising=False)
    assert is_production_build() is False


def test_is_production_build_production(monkeypatch: pytest.MonkeyPatch) -> None:
    """WISEMAN_BUILD_FLAVOR=production → True (本番 PyInstaller build)。"""
    monkeypatch.setenv("WISEMAN_BUILD_FLAVOR", "production")
    assert is_production_build() is True


def test_is_production_build_other_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """WISEMAN_BUILD_FLAVOR=other → False (canary 等は production 扱いしない)。"""
    monkeypatch.setenv("WISEMAN_BUILD_FLAVOR", "canary")
    assert is_production_build() is False


# Constants validity (信頼根の固定値が想定通りか) ---------------------------------


def test_launcher_expected_repo_is_owner_repo_format() -> None:
    """LAUNCHER_EXPECTED_REPO が owner/repo 形式の文字列定数。"""
    assert "/" in LAUNCHER_EXPECTED_REPO
    parts = LAUNCHER_EXPECTED_REPO.split("/")
    assert len(parts) == 2
    assert all(parts)


def test_release_bucket_base_is_https_gcs() -> None:
    """RELEASE_BUCKET_BASE が HTTPS + GCS storage.googleapis.com prefix。"""
    assert RELEASE_BUCKET_BASE.startswith("https://storage.googleapis.com/")
    assert RELEASE_BUCKET_BASE.endswith("/")
