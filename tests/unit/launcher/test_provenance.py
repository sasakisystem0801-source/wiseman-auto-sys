"""Tests for wiseman_hub_launcher._supply_chain.provenance (ADR-016 PR-6a / PR-6 後半)。

AC-2 / AC-3 / AC4 検証:
    - 3 形式 parse: Sigstore Bundle v0.3 / DSSE envelope / plain JSON statement
    - claims verify: subject digest + name + multi-subject 一意性 + predicateType +
      workflow ref + repo + builder id allowlist
    - signature 検証は sigstore-python 委譲 (PR-6 後半、verify_dsse_bundle を mock)
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from wiseman_hub_launcher._supply_chain.provenance import (
    ProvenanceError,
    extract_statement,
    verify_provenance,
    verify_statement_claims,
)
from wiseman_hub_launcher._supply_chain.sigstore import SigstoreVerifyError
from wiseman_hub_launcher.manifest import Sha256Hex, make_sha256hex

# Test fixtures ----------------------------------------------------------------

# 期待値 (Phase 6 canary 2026-05-13: 実 GitHub attest-build-provenance@v2 の builder.id 形式)
_EXPECTED_REPO_SUFFIX = "/sasakisystem0801-source/wiseman-auto-sys"
_VALID_BUILDER_ID = (
    "https://github.com/sasakisystem0801-source/wiseman-auto-sys/"
    ".github/workflows/release.yml@refs/tags/v1.2.3"
)
_VALID_REPO_URL = "https://github.com/sasakisystem0801-source/wiseman-auto-sys"
_VALID_WORKFLOW_PATH = ".github/workflows/release.yml"
_VALID_WORKFLOW_REF = "refs/tags/v1.2.3"
# Issue #209 PR2: Sha256Hex narrow + make_sha256hex validating constructor を exercise。
# `_VALID_SHA: Sha256Hex` で test fixture を NewType narrow し、verify_provenance /
# verify_statement_claims / _verify_subject の Sha256Hex signature に直接渡せる。
_VALID_SHA: Sha256Hex = make_sha256hex("a" * 64)


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


def test_verify_claims_builder_workflow_ref_accepted() -> None:
    """正常系: GitHub Actions attest-build-provenance@v2 の workflow ref builder.id。"""
    verify_statement_claims(
        _good_statement(builder_id=_VALID_BUILDER_ID),
        expected_sha256=_VALID_SHA,
    )


def test_verify_claims_builder_other_repo_rejected() -> None:
    """security: 別 repo の workflow ref → allowlist 外で reject (cross-repo attestation 防御)。"""
    stmt = _good_statement(
        builder_id="https://github.com/evil/repo/.github/workflows/release.yml@refs/tags/v1.2.3"
    )
    with pytest.raises(ProvenanceError, match="not in allowlist"):
        verify_statement_claims(stmt, expected_sha256=_VALID_SHA)


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


# PR-7 タスク D: predicate malformed shape + uppercase digest edge -----------------


def test_verify_claims_predicate_not_dict() -> None:
    """statement["predicate"] が dict でない場合 ProvenanceError (PR-7 AC4)。"""
    stmt = _good_statement()
    stmt["predicate"] = "not a dict"
    with pytest.raises(ProvenanceError, match="statement.predicate must be object"):
        verify_statement_claims(stmt, expected_sha256=_VALID_SHA)


def test_verify_claims_buildDefinition_not_dict() -> None:
    """predicate["buildDefinition"] が dict でない場合 ProvenanceError (PR-7 AC4)。"""
    stmt = _good_statement()
    stmt["predicate"]["buildDefinition"] = "not a dict"
    with pytest.raises(ProvenanceError, match="predicate.buildDefinition must be object"):
        verify_statement_claims(stmt, expected_sha256=_VALID_SHA)


def test_verify_claims_runDetails_not_dict() -> None:
    """predicate["runDetails"] が dict でない場合 ProvenanceError (PR-7 AC4)。"""
    stmt = _good_statement()
    stmt["predicate"]["runDetails"] = "not a dict"
    with pytest.raises(ProvenanceError, match="predicate.runDetails must be object"):
        verify_statement_claims(stmt, expected_sha256=_VALID_SHA)


def test_verify_claims_builder_not_dict() -> None:
    """predicate["runDetails"]["builder"] が dict でない場合 ProvenanceError (PR-7 AC4)。"""
    stmt = _good_statement()
    stmt["predicate"]["runDetails"]["builder"] = "not a dict"
    with pytest.raises(ProvenanceError, match="runDetails.builder must be object"):
        verify_statement_claims(stmt, expected_sha256=_VALID_SHA)


def test_verify_claims_uppercase_digest_rejected() -> None:
    """subject.digest.sha256 が大文字混在の場合 ProvenanceError (PR-7、silent accept 防止)。

    manifest の checksum_sha256 は lowercase 64 hex を強制 (manifest.py validation)。
    provenance subject digest との照合は strict equality (PR-6a Critical fix で
    .lower() を削除)、大文字混在 digest は manifest との不一致として拒否される。
    """
    stmt = _good_statement(sha256=_VALID_SHA.upper())
    with pytest.raises(ProvenanceError, match="subject digest"):
        verify_statement_claims(stmt, expected_sha256=_VALID_SHA)


# verify_provenance E2E (PR-6 後半: sigstore-python verify_dsse 委譲) --------------

_PROVENANCE_MOD = "wiseman_hub_launcher._supply_chain.provenance.verify_dsse_bundle"


def test_verify_provenance_signature_pass(tmp_path: Path) -> None:
    """sigstore mock pass + claims pass → return None (二段検証成功)。"""
    art = tmp_path / "wiseman_hub.exe"
    art.write_bytes(b"x")
    prov = tmp_path / "wiseman_hub.exe.sigstore.json"
    prov.write_text("{}", encoding="utf-8")
    statement = _good_statement()

    with patch(_PROVENANCE_MOD, return_value=statement) as mock_verify:
        verify_provenance(
            art, prov,
            expected_sha256=_VALID_SHA,
            expected_version="1.2.3",
        )
    assert mock_verify.call_count == 1
    # AC4: identity が完全一致 (refs/tags/v{version}) で組み立てられる
    kwargs = mock_verify.call_args.kwargs
    assert kwargs["expected_identity"] == (
        "https://github.com/sasakisystem0801-source/wiseman-auto-sys"
        "/.github/workflows/release.yml@refs/tags/v1.2.3"
    )


def test_verify_provenance_signature_fail_wraps_to_provenance_error(
    tmp_path: Path,
) -> None:
    """sigstore mock raise SigstoreVerifyError → ProvenanceError に wrap。"""
    art = tmp_path / "wiseman_hub.exe"
    art.write_bytes(b"x")
    prov = tmp_path / "wiseman_hub.exe.sigstore.json"
    prov.write_text("{}", encoding="utf-8")

    with (
        patch(_PROVENANCE_MOD, side_effect=SigstoreVerifyError("cert chain broken")),
        pytest.raises(ProvenanceError, match="signature verify failed"),
    ):
        verify_provenance(
            art, prov,
            expected_sha256=_VALID_SHA,
            expected_version="1.2.3",
        )


def test_verify_provenance_claims_fail_after_signature(
    tmp_path: Path,
) -> None:
    """signature pass + claims fail (subject digest 不一致) → ProvenanceError raise。

    sigstore mock が claims 不一致な statement を返す → claims verify 段で raise。
    """
    art = tmp_path / "wiseman_hub.exe"
    art.write_bytes(b"x")
    prov = tmp_path / "wiseman_hub.exe.sigstore.json"
    prov.write_text("{}", encoding="utf-8")
    bad_stmt = _good_statement(sha256="b" * 64)

    with (
        patch(_PROVENANCE_MOD, return_value=bad_stmt),
        pytest.raises(ProvenanceError, match="subject digest"),
    ):
        verify_provenance(
            art, prov,
            expected_sha256=_VALID_SHA,
            expected_version="1.2.3",
        )


def test_verify_provenance_identity_uses_manifest_version(tmp_path: Path) -> None:
    """異なる version (例 2.5.7) でも refs/tags/v{version} 完全一致が組み立てられる (AC4)。"""
    art = tmp_path / "wiseman_hub.exe"
    art.write_bytes(b"x")
    prov = tmp_path / "wiseman_hub.exe.sigstore.json"
    prov.write_text("{}", encoding="utf-8")
    statement = _good_statement()

    with patch(_PROVENANCE_MOD, return_value=statement) as mock_verify:
        verify_provenance(
            art, prov,
            expected_sha256=_VALID_SHA,
            expected_version="2.5.7",
        )
    kwargs = mock_verify.call_args.kwargs
    assert kwargs["expected_identity"].endswith("@refs/tags/v2.5.7")


# PR-6 後半 type-design 反映: expected_version の semver 形式検証 ---------------


@pytest.mark.parametrize(
    "bad_version",
    [
        "1.2",            # 不完全 (semver 3 要素必須)
        "1.2.3-rc1",      # rc/canary は本 PR 非対応
        "1.2.3.4",        # 余分な segment
        "v1.2.3",         # v prefix 不可 (caller が strip 済前提)
        "1.2.3 --evil",   # control / 余分文字
        "../etc/passwd",  # path injection
        "",               # 空
    ],
)
def test_verify_provenance_rejects_malformed_version(
    tmp_path: Path, bad_version: str
) -> None:
    """expected_version が semver X.Y.Z でない → ProvenanceError (identity URI 改竄防止)。"""
    art = tmp_path / "wiseman_hub.exe"
    art.write_bytes(b"x")
    prov = tmp_path / "wiseman_hub.exe.sigstore.json"
    prov.write_text("{}", encoding="utf-8")
    with pytest.raises(ProvenanceError, match="expected_version must be semver"):
        verify_provenance(
            art, prov,
            expected_sha256=_VALID_SHA,
            expected_version=bad_version,
        )
