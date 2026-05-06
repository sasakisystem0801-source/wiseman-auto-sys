"""SLSA Provenance v1.0 statement parse + claims verify (ADR-016 PR-6a)。

codex T0 Explore 調査結果反映:
    - default 形式 = Sigstore Bundle v0.3 JSON (mediaType: vnd.dev.sigstore.bundle)
    - DSSE envelope (payloadType + payload + signatures): actions/attest v1 互換
    - plain JSON statement (`_type` + `subject` + `predicate`): 一部 CI で使用

PR-6a スコープ (Q2-C):
    - 3 形式判定 + statement 抽出 (extract_statement)
    - claims verify: subject digest / subject name / predicateType / workflow ref /
      repository / builder id allowlist (verify_statement_claims)
    - signature 検証は **stub interface のみ** (verify_signature は NotImplementedError、
      `--allow-test-unsigned-provenance` + 環境変数 AND で bypass 可)

PR-6 後半:
    - sigstore-python 依存追加 + Sigstore Bundle 検証本実装
    - signature stub を本実装に置換
    - --allow-test-unsigned-provenance 削除
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any

from .policy import (
    LAUNCHER_EXPECTED_REPO,
    LAUNCHER_EXPECTED_WORKFLOW_REF_PATTERN,
    is_test_bypass_authorized,
)

logger = logging.getLogger(__name__)


# T0 Explore 結果: GitHub-hosted runner の builder id prefix
# self-hosted は本 PR では非許可 (allow_self_hosted=False default)
_ALLOWED_BUILDER_ID_PREFIXES: tuple[str, ...] = (
    "https://github.com/actions/runner@",
    "https://github.com/actions/runner-releases/",
)

# SLSA v1.0 / v1.x 共通の predicateType prefix (T0 Explore で v1.0 / v1.2 確認)
_SLSA_PROVENANCE_TYPE_PREFIX = "https://slsa.dev/provenance/v"

# Sigstore Bundle mediaType prefix (T0 Explore: v0.3 が current)
_SIGSTORE_BUNDLE_MEDIA_PREFIX = "application/vnd.dev.sigstore.bundle"


class ProvenanceError(Exception):
    """provenance 検証関連の失敗 (parse / schema / claims 不一致)。"""


class ProvenanceUnavailable(ProvenanceError):
    """signature 検証 stub の bypass 未認可 (PR-6 後半で本実装)。

    PR-6a では `--allow-test-unsigned-provenance` + WISEMAN_ALLOW_UNSIGNED_PROVENANCE_FOR_TESTS=1
    の AND 条件で bypass、それ以外で raise。
    """


def _detect_format(obj: dict[str, Any]) -> str:
    """provenance JSON の形式を判定する (T0 Explore 結果反映)。

    Returns:
        "sigstore_bundle" | "dsse_envelope" | "plain_statement"

    Raises:
        ProvenanceError: いずれにも一致しない
    """
    media = obj.get("mediaType")
    if isinstance(media, str) and media.startswith(_SIGSTORE_BUNDLE_MEDIA_PREFIX):
        return "sigstore_bundle"
    if "payloadType" in obj and "payload" in obj and "signatures" in obj:
        return "dsse_envelope"
    if "_type" in obj and "subject" in obj:
        return "plain_statement"
    raise ProvenanceError(
        "provenance does not match Sigstore Bundle / DSSE envelope / plain Statement"
    )


def _decode_dsse_payload(envelope: dict[str, Any]) -> dict[str, Any]:
    """DSSE envelope の payload (base64) を decode して SLSA statement dict を返す。

    Raises:
        ProvenanceError: base64 decode / JSON parse / dict 型不一致
    """
    payload_b64 = envelope.get("payload")
    if not isinstance(payload_b64, str):
        raise ProvenanceError("DSSE envelope payload must be string")
    try:
        decoded = base64.b64decode(payload_b64, validate=True)
    except (ValueError, base64.binascii.Error) as e:  # type: ignore[attr-defined]
        raise ProvenanceError(f"DSSE payload base64 decode failed: {e}") from e
    try:
        statement = json.loads(decoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ProvenanceError(f"DSSE payload JSON parse failed: {type(e).__name__}") from e
    if not isinstance(statement, dict):
        raise ProvenanceError(
            f"DSSE payload must be JSON object, got {type(statement).__name__}"
        )
    return statement


def extract_statement(provenance_path: Path) -> dict[str, Any]:
    """provenance file から SLSA in-toto Statement (v1.0) dict を抽出する。

    3 形式に対応:
        1. Sigstore Bundle v0.3+ JSON (default): dsseEnvelope.payload を base64 decode
        2. DSSE envelope (actions/attest v1 互換): payload を base64 decode
        3. Plain JSON statement: そのまま返す

    Args:
        provenance_path: download 済 provenance file path

    Returns:
        SLSA in-toto Statement dict (`_type`, `subject`, `predicateType`, `predicate`)

    Raises:
        ProvenanceError: file 不在 / JSON parse / 形式判定 / payload 抽出失敗
    """
    try:
        raw = provenance_path.read_bytes()
    except OSError as e:
        raise ProvenanceError(f"provenance read failed: {type(e).__name__}") from e
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ProvenanceError(
            f"provenance JSON parse failed: {type(e).__name__}"
        ) from e
    if not isinstance(obj, dict):
        raise ProvenanceError(
            f"provenance top-level must be object, got {type(obj).__name__}"
        )

    fmt = _detect_format(obj)
    if fmt == "plain_statement":
        return obj
    if fmt == "dsse_envelope":
        return _decode_dsse_payload(obj)
    # sigstore_bundle: dsseEnvelope を取り出して再帰
    envelope = obj.get("dsseEnvelope")
    if not isinstance(envelope, dict):
        raise ProvenanceError("Sigstore Bundle is missing dsseEnvelope")
    return _decode_dsse_payload(envelope)


def _verify_subject(
    statement: dict[str, Any],
    expected_sha256: str,
    expected_subject_name: str,
) -> None:
    """subject[] が期待 digest + name と一意に一致 (S-2)。"""
    subjects = statement.get("subject")
    if not isinstance(subjects, list) or not subjects:
        raise ProvenanceError("statement.subject must be non-empty list")
    matched = []
    for subj in subjects:
        if not isinstance(subj, dict):
            continue
        digest = subj.get("digest")
        if not isinstance(digest, dict):
            continue
        sha = digest.get("sha256")
        if isinstance(sha, str) and sha.lower() == expected_sha256.lower():
            matched.append(subj)
    if len(matched) == 0:
        raise ProvenanceError(
            f"subject digest mismatch (expected sha256={expected_sha256[:8]}...)"
        )
    if len(matched) > 1:
        raise ProvenanceError(
            f"multiple subjects match digest (expected exactly 1, got {len(matched)})"
        )
    name = matched[0].get("name")
    if not isinstance(name, str) or name != expected_subject_name:
        raise ProvenanceError(
            f"subject name mismatch (expected {expected_subject_name!r}, got {name!r})"
        )


def _verify_predicate(statement: dict[str, Any]) -> None:
    """predicateType が SLSA Provenance v1.x の prefix と一致。"""
    ptype = statement.get("predicateType")
    if not isinstance(ptype, str) or not ptype.startswith(_SLSA_PROVENANCE_TYPE_PREFIX):
        raise ProvenanceError(
            f"predicateType must be SLSA Provenance v1.x: {ptype!r}"
        )


def _verify_workflow_ref(predicate: dict[str, Any]) -> None:
    """workflow ref / repository が launcher 埋め込み constant と一致 (I-2)。"""
    bd = predicate.get("buildDefinition")
    if not isinstance(bd, dict):
        raise ProvenanceError("predicate.buildDefinition must be object")
    ext = bd.get("externalParameters")
    if not isinstance(ext, dict):
        raise ProvenanceError("buildDefinition.externalParameters must be object")
    workflow = ext.get("workflow")
    if not isinstance(workflow, dict):
        raise ProvenanceError("externalParameters.workflow must be object")

    repo = workflow.get("repository")
    if not isinstance(repo, str) or not repo.endswith("/" + LAUNCHER_EXPECTED_REPO):
        raise ProvenanceError(
            f"workflow.repository mismatch (expected suffix /{LAUNCHER_EXPECTED_REPO}, "
            f"got {repo!r})"
        )

    ref_value = workflow.get("ref")
    path_value = workflow.get("path")
    if not isinstance(ref_value, str) or not isinstance(path_value, str):
        raise ProvenanceError("workflow.ref and workflow.path must be string")
    composed = f"{path_value}@{ref_value}"
    if not LAUNCHER_EXPECTED_WORKFLOW_REF_PATTERN.match(composed):
        raise ProvenanceError(
            f"workflow ref pattern mismatch (got {composed!r})"
        )


def _verify_builder(predicate: dict[str, Any]) -> None:
    """runDetails.builder.id が allowlist に前方一致 (S-3)。"""
    rd = predicate.get("runDetails")
    if not isinstance(rd, dict):
        raise ProvenanceError("predicate.runDetails must be object")
    builder = rd.get("builder")
    if not isinstance(builder, dict):
        raise ProvenanceError("runDetails.builder must be object")
    builder_id = builder.get("id")
    if not isinstance(builder_id, str):
        raise ProvenanceError("builder.id must be string")
    if not any(builder_id.startswith(p) for p in _ALLOWED_BUILDER_ID_PREFIXES):
        raise ProvenanceError(
            f"builder.id not in allowlist: {builder_id!r}"
        )


def verify_statement_claims(
    statement: dict[str, Any],
    *,
    expected_sha256: str,
    expected_subject_name: str = "wiseman_hub.exe",
) -> None:
    """SLSA statement claims (signature 以外) を検証する (PR-6a)。

    Args:
        statement: extract_statement() の戻り値
        expected_sha256: artifact の期待 SHA-256 (manifest.checksum_sha256 と一致)
        expected_subject_name: subject name (default: "wiseman_hub.exe")

    Raises:
        ProvenanceError: 上記 4 検証 (subject / predicateType / workflow ref / builder) 失敗
    """
    if not isinstance(statement, dict):
        raise ProvenanceError("statement must be dict")
    _verify_subject(statement, expected_sha256, expected_subject_name)
    _verify_predicate(statement)
    predicate = statement.get("predicate")
    if not isinstance(predicate, dict):
        raise ProvenanceError("statement.predicate must be object")
    _verify_workflow_ref(predicate)
    _verify_builder(predicate)


def verify_provenance(
    artifact_path: Path,
    provenance_path: Path,
    *,
    expected_sha256: str,
    allow_unsigned: bool = False,
) -> None:
    """artifact + provenance を検証する (PR-6a 高水準 API)。

    Args:
        artifact_path: download 済 artifact path (verify_sha256 を別途呼ぶ前提、本関数では未検証)
        provenance_path: download 済 provenance path
        expected_sha256: manifest.checksum_sha256
        allow_unsigned: True かつ環境変数 AND で signature 検証 stub を bypass。
            False or 環境変数なしで ProvenanceUnavailable raise。

    Raises:
        ProvenanceError (claims 不一致 / parse 失敗)
        ProvenanceUnavailable (allow_unsigned=False で signature stub 到達)
    """
    statement = extract_statement(provenance_path)
    verify_statement_claims(statement, expected_sha256=expected_sha256)

    if not (allow_unsigned and is_test_bypass_authorized()):
        raise ProvenanceUnavailable(
            "signature verification not implemented yet (PR-6 後半 sigstore-python 統合)"
        )
    logger.warning(
        "provenance signature verification skipped (allow_unsigned=True + env var); "
        "PR-6 後半で sigstore-python 本実装"
    )
    # 引数を参照しないと vulture / ruff が unused warn を出すため、log で消費する
    logger.debug("verify_provenance bypass for artifact=%s", artifact_path.name)
