"""Tests for wiseman_hub_launcher._supply_chain.provenance (ADR-016 PR-6a)。

AC-2 / AC-3 検証:
    - 3 形式 parse: Sigstore Bundle v0.3 / DSSE envelope / plain JSON statement
    - claims verify: subject digest + name + multi-subject 一意性 + predicateType +
      workflow ref + repo + builder id allowlist
    - signature 検証は stub (allow_unsigned + env var AND で bypass)

T0 Explore agent 結果反映:
    - default 形式 = Sigstore Bundle v0.3 (mediaType: vnd.dev.sigstore.bundle)
    - subject = 1 件が標準、multi-subject は invariant で raise
    - builder id = "https://github.com/actions/runner@" prefix match
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from wiseman_hub_launcher._supply_chain.provenance import (
    ProvenanceError,
    ProvenanceUnavailable,
    extract_statement,
    verify_provenance,
    verify_statement_claims,
)

# Test fixtures ----------------------------------------------------------------

# 期待値 (T0 Explore で確認した GitHub Actions hosted runner の builder id)
_EXPECTED_REPO_SUFFIX = "/sasakisystem0801-source/wiseman-auto-sys"
_VALID_BUILDER_ID = "https://github.com/actions/runner@v2.300.0"
_VALID_REPO_URL = "https://github.com/sasakisystem0801-source/wiseman-auto-sys"
_VALID_WORKFLOW_PATH = ".github/workflows/release.yml"
_VALID_WORKFLOW_REF = "refs/tags/v1.2.3"
_VALID_SHA = "a" * 64


def _good_statement(
    *,
    sha256: str = _VALID_SHA,
    subject_name: str = "wiseman_hub.exe",
    predicate_type: str = "https://slsa.dev/provenance/v1",
    repo: str = _VALID_REPO_URL,
    workflow_ref: str = _VALID_WORKFLOW_REF,
    workflow_path: str = _VALID_WORKFLOW_PATH,
    builder_id: str = _VALID_BUILDER_ID,
    extra_subjects: list[dict] | None = None,
) -> dict:
    """SLSA v1.0 statement の正常系 fixture。各引数で項目を変更してエラー系も生成。"""
    subjects = [{"name": subject_name, "digest": {"sha256": sha256}}]
    if extra_subjects:
        subjects.extend(extra_subjects)
    return {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": subjects,
        "predicateType": predicate_type,
        "predicate": {
            "buildDefinition": {
                "buildType": "https://actions.github.io/buildtypes/workflow/v1",
                "externalParameters": {
                    "workflow": {
                        "ref": workflow_ref,
                        "repository": repo,
                        "path": workflow_path,
                    },
                },
            },
            "runDetails": {
                "builder": {"id": builder_id},
            },
        },
    }


def _dsse_envelope(payload_obj: dict) -> dict:
    """DSSE envelope wrapping a SLSA statement."""
    payload_b64 = base64.b64encode(
        json.dumps(payload_obj).encode("utf-8")
    ).decode("ascii")
    return {
        "payloadType": "application/vnd.in-toto+json",
        "payload": payload_b64,
        "signatures": [{"keyid": "k1", "sig": "stub-sig"}],
    }


def _sigstore_bundle(payload_obj: dict) -> dict:
    """Sigstore Bundle v0.3 wrapping a DSSE envelope (T0 Explore canonical 形式)."""
    return {
        "mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json",
        "verificationMaterial": {"x509CertificateChain": {"certificates": []}},
        "dsseEnvelope": _dsse_envelope(payload_obj),
    }


def _write_provenance(tmp_path: Path, content: dict | str) -> Path:
    """provenance file を tmp_path に書き出してその Path を返す。"""
    path = tmp_path / "wiseman_hub.exe.sigstore.json"
    if isinstance(content, dict):
        path.write_text(json.dumps(content), encoding="utf-8")
    else:
        path.write_text(content, encoding="utf-8")
    return path


# extract_statement: 3 形式 + parse error ----------------------------------------


def test_extract_statement_plain_json(tmp_path: Path) -> None:
    """plain JSON statement (`_type` + `subject` 直接) を parse できる。"""
    stmt = _good_statement()
    p = _write_provenance(tmp_path, stmt)
    extracted = extract_statement(p)
    assert extracted == stmt


def test_extract_statement_dsse_envelope(tmp_path: Path) -> None:
    """DSSE envelope (payload base64) を decode して statement を取得。"""
    stmt = _good_statement()
    p = _write_provenance(tmp_path, _dsse_envelope(stmt))
    extracted = extract_statement(p)
    assert extracted["_type"] == stmt["_type"]
    assert extracted["subject"][0]["digest"]["sha256"] == _VALID_SHA


def test_extract_statement_sigstore_bundle(tmp_path: Path) -> None:
    """Sigstore Bundle v0.3 (T0 Explore default) から dsseEnvelope.payload を抽出。"""
    stmt = _good_statement()
    p = _write_provenance(tmp_path, _sigstore_bundle(stmt))
    extracted = extract_statement(p)
    assert extracted["_type"] == stmt["_type"]


def test_extract_statement_unknown_format(tmp_path: Path) -> None:
    """3 形式どれにも該当しない JSON は ProvenanceError raise。"""
    p = _write_provenance(tmp_path, {"random": "object"})
    with pytest.raises(ProvenanceError, match="does not match"):
        extract_statement(p)


def test_extract_statement_invalid_json(tmp_path: Path) -> None:
    """JSON 破損 → ProvenanceError。"""
    p = _write_provenance(tmp_path, "{broken json")
    with pytest.raises(ProvenanceError, match="JSON parse failed"):
        extract_statement(p)


def test_extract_statement_top_level_not_dict(tmp_path: Path) -> None:
    """top-level が array → ProvenanceError。"""
    p = tmp_path / "wiseman_hub.exe.sigstore.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ProvenanceError, match="must be object"):
        extract_statement(p)


def test_extract_statement_file_not_found(tmp_path: Path) -> None:
    """file 不在 → ProvenanceError。"""
    p = tmp_path / "nope.sigstore.json"
    with pytest.raises(ProvenanceError, match="read failed"):
        extract_statement(p)


def test_extract_statement_dsse_payload_invalid_base64(tmp_path: Path) -> None:
    """DSSE envelope の payload が base64 として無効 → ProvenanceError。"""
    envelope = {
        "payloadType": "application/vnd.in-toto+json",
        "payload": "not-base64!@#",
        "signatures": [{"keyid": "k1", "sig": "x"}],
    }
    p = _write_provenance(tmp_path, envelope)
    with pytest.raises(ProvenanceError, match="base64 decode failed"):
        extract_statement(p)


def test_extract_statement_dsse_payload_invalid_json(tmp_path: Path) -> None:
    """DSSE envelope の payload が valid base64 だが JSON parse 不可。"""
    bad = base64.b64encode(b"{broken").decode("ascii")
    envelope = {
        "payloadType": "application/vnd.in-toto+json",
        "payload": bad,
        "signatures": [{"keyid": "k1", "sig": "x"}],
    }
    p = _write_provenance(tmp_path, envelope)
    with pytest.raises(ProvenanceError, match="JSON parse failed"):
        extract_statement(p)


def test_extract_statement_sigstore_bundle_missing_envelope(tmp_path: Path) -> None:
    """Sigstore Bundle に dsseEnvelope が無い → ProvenanceError。"""
    p = _write_provenance(
        tmp_path,
        {
            "mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json",
            "verificationMaterial": {},
        },
    )
    with pytest.raises(ProvenanceError, match="missing dsseEnvelope"):
        extract_statement(p)


# verify_statement_claims: subject ----------------------------------------------


def test_verify_claims_success() -> None:
    """正常系: 全項目一致 → 例外なし。"""
    verify_statement_claims(_good_statement(), expected_sha256=_VALID_SHA)


def test_verify_claims_subject_digest_mismatch() -> None:
    """subject digest 不一致 → ProvenanceError。"""
    stmt = _good_statement(sha256="b" * 64)
    with pytest.raises(ProvenanceError, match="subject digest mismatch"):
        verify_statement_claims(stmt, expected_sha256=_VALID_SHA)


def test_verify_claims_subject_name_mismatch() -> None:
    """subject name が expected と異なる → ProvenanceError。"""
    stmt = _good_statement(subject_name="malicious.exe")
    with pytest.raises(ProvenanceError, match="subject name mismatch"):
        verify_statement_claims(stmt, expected_sha256=_VALID_SHA)


def test_verify_claims_multi_subject_unique_match() -> None:
    """複数 subject で 1 件のみ digest 一致 → 一意性 invariant 通過。"""
    stmt = _good_statement(
        extra_subjects=[
            {"name": "other.zip", "digest": {"sha256": "c" * 64}}
        ]
    )
    verify_statement_claims(stmt, expected_sha256=_VALID_SHA)


def test_verify_claims_multi_subject_multiple_match() -> None:
    """複数 subject で 2 件以上 digest 一致 → 一意性 invariant 違反 (S-2)。"""
    stmt = _good_statement(
        extra_subjects=[
            {"name": "duplicate.exe", "digest": {"sha256": _VALID_SHA}}
        ]
    )
    with pytest.raises(ProvenanceError, match="multiple subjects match"):
        verify_statement_claims(stmt, expected_sha256=_VALID_SHA)


def test_verify_claims_empty_subject_list() -> None:
    """subject が空 list → ProvenanceError。"""
    stmt = _good_statement()
    stmt["subject"] = []
    with pytest.raises(ProvenanceError, match="non-empty list"):
        verify_statement_claims(stmt, expected_sha256=_VALID_SHA)


# verify_statement_claims: predicateType ----------------------------------------


def test_verify_claims_predicate_type_v10() -> None:
    """SLSA v1.0 → OK。"""
    verify_statement_claims(
        _good_statement(predicate_type="https://slsa.dev/provenance/v1"),
        expected_sha256=_VALID_SHA,
    )


def test_verify_claims_predicate_type_v12() -> None:
    """SLSA v1.x prefix で future-proof (T0 Explore: v1.2 も accept)。"""
    verify_statement_claims(
        _good_statement(predicate_type="https://slsa.dev/provenance/v1.2"),
        expected_sha256=_VALID_SHA,
    )


def test_verify_claims_predicate_type_non_slsa() -> None:
    """SBOM や custom predicate → ProvenanceError (T0 Explore 警告反映)。"""
    stmt = _good_statement(predicate_type="https://cyclonedx.org/bom")
    with pytest.raises(ProvenanceError, match="SLSA Provenance"):
        verify_statement_claims(stmt, expected_sha256=_VALID_SHA)


# verify_statement_claims: workflow ref + repo ----------------------------------


def test_verify_claims_workflow_ref_full_match() -> None:
    """正常系: 期待値完全一致。"""
    verify_statement_claims(_good_statement(), expected_sha256=_VALID_SHA)


def test_verify_claims_repo_mismatch() -> None:
    """異なる repo の attestation → ProvenanceError (C8: urlparse strict 比較)。"""
    stmt = _good_statement(repo="https://github.com/attacker/forked-repo")
    with pytest.raises(ProvenanceError, match="must be https://github.com"):
        verify_statement_claims(stmt, expected_sha256=_VALID_SHA)


def test_verify_claims_repo_path_traversal_blocked() -> None:
    """C8 (PR codex I-1): suffix だけ一致する偽 host を urlparse で reject。"""
    stmt = _good_statement(
        repo="https://evil.example/x/sasakisystem0801-source/wiseman-auto-sys"
    )
    with pytest.raises(ProvenanceError, match="must be https://github.com"):
        verify_statement_claims(stmt, expected_sha256=_VALID_SHA)


def test_verify_claims_repo_http_scheme_blocked() -> None:
    """C8: HTTPS でない URL も urlparse で reject。"""
    stmt = _good_statement(
        repo="http://github.com/sasakisystem0801-source/wiseman-auto-sys"
    )
    with pytest.raises(ProvenanceError, match="must be https://github.com"):
        verify_statement_claims(stmt, expected_sha256=_VALID_SHA)


def test_verify_claims_workflow_ref_pattern_mismatch() -> None:
    """release.yml@refs/tags/vX.Y.Z 以外の ref → ProvenanceError。"""
    stmt = _good_statement(workflow_ref="refs/heads/main")
    with pytest.raises(ProvenanceError, match="workflow ref pattern"):
        verify_statement_claims(stmt, expected_sha256=_VALID_SHA)


def test_verify_claims_workflow_path_mismatch() -> None:
    """release.yml 以外の workflow path → ProvenanceError (pattern 違反)。"""
    stmt = _good_statement(workflow_path=".github/workflows/test.yml")
    with pytest.raises(ProvenanceError, match="workflow ref pattern"):
        verify_statement_claims(stmt, expected_sha256=_VALID_SHA)


def test_verify_claims_workflow_missing_fields() -> None:
    """externalParameters.workflow が存在しない → ProvenanceError。"""
    stmt = _good_statement()
    del stmt["predicate"]["buildDefinition"]["externalParameters"]["workflow"]
    with pytest.raises(ProvenanceError, match="workflow"):
        verify_statement_claims(stmt, expected_sha256=_VALID_SHA)


# verify_statement_claims: builder id allowlist ---------------------------------


def test_verify_claims_builder_actions_runner() -> None:
    """正常系: GitHub-hosted runner builder id (T0 Explore allowlist)。"""
    verify_statement_claims(
        _good_statement(builder_id="https://github.com/actions/runner@v2.300.0"),
        expected_sha256=_VALID_SHA,
    )


def test_verify_claims_builder_runner_releases() -> None:
    """正常系: legacy runner-releases prefix も allowlist。"""
    verify_statement_claims(
        _good_statement(
            builder_id="https://github.com/actions/runner-releases/v2.299.0"
        ),
        expected_sha256=_VALID_SHA,
    )


def test_verify_claims_builder_self_hosted_rejected() -> None:
    """self-hosted runner や custom builder id → allowlist 外で reject。"""
    stmt = _good_statement(builder_id="https://example.com/our-runner@v1")
    with pytest.raises(ProvenanceError, match="not in allowlist"):
        verify_statement_claims(stmt, expected_sha256=_VALID_SHA)


def test_verify_claims_builder_missing() -> None:
    """runDetails.builder が存在しない → ProvenanceError。"""
    stmt = _good_statement()
    del stmt["predicate"]["runDetails"]["builder"]
    with pytest.raises(ProvenanceError, match="builder"):
        verify_statement_claims(stmt, expected_sha256=_VALID_SHA)


# verify_provenance E2E (signature stub bypass logic) --------------------------


def test_verify_provenance_stub_raises_without_bypass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """allow_unsigned=False または env var なし → ProvenanceUnavailable。"""
    monkeypatch.delenv("WISEMAN_ALLOW_UNSIGNED_PROVENANCE_FOR_TESTS", raising=False)
    art = tmp_path / "wiseman_hub.exe"
    art.write_bytes(b"x")
    prov = _write_provenance(tmp_path, _good_statement())
    with pytest.raises(ProvenanceUnavailable, match="signature verification"):
        verify_provenance(art, prov, expected_sha256=_VALID_SHA, allow_unsigned=False)


def test_verify_provenance_stub_raises_with_flag_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """allow_unsigned=True だけでは bypass されず、env なしで stub raise (C-2 二重 gate)。"""
    monkeypatch.delenv("WISEMAN_ALLOW_UNSIGNED_PROVENANCE_FOR_TESTS", raising=False)
    art = tmp_path / "wiseman_hub.exe"
    art.write_bytes(b"x")
    prov = _write_provenance(tmp_path, _good_statement())
    with pytest.raises(ProvenanceUnavailable):
        verify_provenance(art, prov, expected_sha256=_VALID_SHA, allow_unsigned=True)


def test_verify_provenance_stub_raises_with_env_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """env var だけでは bypass されず、CLI flag なしで stub raise (C-2 二重 gate)。"""
    monkeypatch.setenv("WISEMAN_ALLOW_UNSIGNED_PROVENANCE_FOR_TESTS", "1")
    art = tmp_path / "wiseman_hub.exe"
    art.write_bytes(b"x")
    prov = _write_provenance(tmp_path, _good_statement())
    with pytest.raises(ProvenanceUnavailable):
        verify_provenance(art, prov, expected_sha256=_VALID_SHA, allow_unsigned=False)


def test_verify_provenance_bypass_with_both(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """allow_unsigned=True + env var=1 の AND 条件で bypass、claims pass なら return None。"""
    monkeypatch.setenv("WISEMAN_ALLOW_UNSIGNED_PROVENANCE_FOR_TESTS", "1")
    art = tmp_path / "wiseman_hub.exe"
    art.write_bytes(b"x")
    prov = _write_provenance(tmp_path, _good_statement())
    # claims valid + bypass authorized → return None (例外なし)
    verify_provenance(art, prov, expected_sha256=_VALID_SHA, allow_unsigned=True)


def test_verify_provenance_claims_fail_before_signature_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """claims 不一致は bypass の有無に関わらず ProvenanceError raise (signature stub に到達しない)。"""
    monkeypatch.setenv("WISEMAN_ALLOW_UNSIGNED_PROVENANCE_FOR_TESTS", "1")
    art = tmp_path / "wiseman_hub.exe"
    art.write_bytes(b"x")
    # subject digest 不一致 statement
    stmt = _good_statement(sha256="b" * 64)
    prov = _write_provenance(tmp_path, stmt)
    with pytest.raises(ProvenanceError, match="subject digest"):
        verify_provenance(art, prov, expected_sha256=_VALID_SHA, allow_unsigned=True)
