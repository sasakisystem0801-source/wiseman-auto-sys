"""SLSA Provenance v1.0 signature verify + statement claims verify (ADR-016 PR-6 後半)。

PR-6a で実装済 (本 module):
    - 3 形式 (Sigstore Bundle / DSSE envelope / plain JSON Statement) 判定 + statement 抽出
    - claims verify: subject digest / subject name / predicateType / workflow ref /
      repository / builder id allowlist (verify_statement_claims、SLSA v1.0
      §5.1 subject / §6 buildDefinition / §7.2 builder)

PR-6 後半 (本 PR で追加):
    - signature 検証本実装: ``sigstore-python`` の ``Verifier.verify_dsse`` に委譲
      (``_supply_chain/sigstore.py`` 経由、ADR-016 §1.1.3 stdlib only 例外)
    - identity matching は完全一致 (codex C2 反映): manifest の current_version を
      caller (updater.py) が ``expected_version`` として渡し、本 module の
      ``verify_provenance`` 内で ``refs/tags/v{version}`` + 完全 identity URI を
      ``build_expected_identity`` で組み立てる
    - bypass 経路 (``--allow-test-unsigned-provenance`` flag +
      ``WISEMAN_ALLOW_UNSIGNED_PROVENANCE_FOR_TESTS`` env) を完全削除
"""

from __future__ import annotations

import base64
import json
import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .policy import (
    LAUNCHER_EXPECTED_REPO,
    LAUNCHER_EXPECTED_WORKFLOW_REF_PATTERN,
)
from .sigstore import (
    SigstoreVerifyError,
    build_expected_identity,
    verify_dsse_bundle,
)

logger = logging.getLogger(__name__)


# T0 Explore 結果: GitHub-hosted runner の builder id prefix
# self-hosted は本 PR では非許可 (allow_self_hosted=False default)
_ALLOWED_BUILDER_ID_PREFIXES: tuple[str, ...] = (
    "https://github.com/actions/runner@",
    "https://github.com/actions/runner-releases/",
)

# C8 (PR codex S-1): SLSA Provenance v1.x の predicateType を厳格化。
# 元の startswith("https://slsa.dev/provenance/v") は v-anything が通る欠陥。
# v1, v1.0, v1.1, v1.2 等の v1.x 系のみ accept (将来 v2 が出たら明示的に accept 追加要)。
_SLSA_PROVENANCE_TYPE_RE = re.compile(
    r"^https://slsa\.dev/provenance/v1(\.\d+)?$"
)

# Sigstore Bundle mediaType prefix (T0 Explore: v0.3 が current)
_SIGSTORE_BUNDLE_MEDIA_PREFIX = "application/vnd.dev.sigstore.bundle"

# DSSE envelope payloadType: in-toto Statement (Important S-2 反映で厳格化)
_DSSE_PAYLOAD_TYPE_INTOTO = "application/vnd.in-toto+json"


class ProvenanceError(Exception):
    """provenance 検証関連の失敗 (parse / schema / claims 不一致 / signature 不正)。"""


def _detect_format(obj: dict[str, Any]) -> str:
    """provenance JSON の形式を判定する (T0 Explore 結果反映)。

    優先順 (most specific first):
        1. mediaType (Sigstore Bundle が dsseEnvelope を wrap するため最優先)
        2. payloadType (DSSE envelope 必須キー)
        3. _type (plain SLSA Statement の必須キー)

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

    S-2 (PR codex review threadId 019dff53) 反映:
        payloadType を ``application/vnd.in-toto+json`` に厳格化。defense-in-depth
        として後段 claims verify が在るが、形式不正は早期 reject する。

    Args:
        envelope: DSSE envelope dict (`payloadType` + `payload` + `signatures`)

    Returns:
        SLSA Statement dict (`_type` / `subject` / `predicateType` / `predicate`)

    Raises:
        ProvenanceError: payloadType 不正 / base64 decode / JSON parse / dict 型不一致
    """
    payload_type = envelope.get("payloadType")
    if payload_type != _DSSE_PAYLOAD_TYPE_INTOTO:
        raise ProvenanceError(
            f"DSSE payloadType must be {_DSSE_PAYLOAD_TYPE_INTOTO!r}, got {payload_type!r}"
        )
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
        raise ProvenanceError(
            f"DSSE payload JSON parse failed: {type(e).__name__}"
        ) from e
    if not isinstance(statement, dict):
        raise ProvenanceError(
            f"DSSE payload must be JSON object, got {type(statement).__name__}"
        )
    return statement


def extract_statement(provenance_path: Path) -> dict[str, Any]:
    """provenance file から SLSA in-toto Statement (v1.0) dict を抽出する。

    3 形式に対応 (順序は `_detect_format` 参照):
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
    """subject[] が期待 digest + name と一意に一致 (SLSA v1.0 §5.1、S-2 invariant)。

    C1 (silent-failure-hunter) 反映:
        - 大文字混在 sha256 を silent accept しない (validate_manifest が
          checksum_sha256 を lowercase 強制済、subject 側も同形式を要求する仕様)
        - malformed subject entry (dict でない / digest が dict でない) は continue で
          skip せず、明示的 ProvenanceError raise (C10 silent skip 防止)

    Args:
        statement: SLSA Statement dict
        expected_sha256: 期待 SHA-256 (manifest.checksum_sha256 と一致、lowercase 64 hex)
        expected_subject_name: 期待 subject name (例: "wiseman_hub.exe")

    Raises:
        ProvenanceError: subject 不在 / 形式不正 / digest 不一致 / 一意性違反 / name 不一致
    """
    subjects = statement.get("subject")
    if not isinstance(subjects, list) or not subjects:
        raise ProvenanceError("statement.subject must be non-empty list")
    matched: list[dict[str, Any]] = []
    for i, subj in enumerate(subjects):
        # C10 (silent-failure-hunter MEDIUM 10): malformed entry は fail-fast、
        # silent skip して digest 不一致に化けさせない
        if not isinstance(subj, dict):
            raise ProvenanceError(
                f"subject[{i}] must be object, got {type(subj).__name__}"
            )
        digest = subj.get("digest")
        if not isinstance(digest, dict):
            raise ProvenanceError(
                f"subject[{i}].digest must be object, got {type(digest).__name__}"
            )
        sha = digest.get("sha256")
        # C1: subject 側も lowercase strict 比較。攻撃者が大文字混在で混乱を狙う
        # 攻撃面を排除（manifest 側は既に lowercase 強制済）
        if isinstance(sha, str) and sha == expected_sha256:
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
    """predicateType が SLSA Provenance v1.x の正規 URI と一致 (PR codex S-1 反映)。

    `^https://slsa.dev/provenance/v1(\\.\\d+)?$` の strict regex。
    元の startswith では `v-anything` も通る欠陥があった。
    """
    ptype = statement.get("predicateType")
    if not isinstance(ptype, str) or not _SLSA_PROVENANCE_TYPE_RE.match(ptype):
        raise ProvenanceError(
            f"predicateType must match SLSA Provenance v1.x: {ptype!r}"
        )


def _verify_workflow_ref(predicate: dict[str, Any]) -> None:
    """workflow ref / repository が launcher 埋め込み constant と一致 (I-2 + C8 反映)。

    C8 (PR codex I-1 反映): repo URL を urllib.parse で scheme/netloc/path 完全一致。
    元の `endswith("/" + LAUNCHER_EXPECTED_REPO)` は
    `https://evil.example/x/sasakisystem0801-source/wiseman-auto-sys` を通す欠陥。
    """
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
    if not isinstance(repo, str):
        raise ProvenanceError(f"workflow.repository must be string, got {type(repo).__name__}")
    parsed = urlparse(repo)
    expected_path = "/" + LAUNCHER_EXPECTED_REPO
    if (
        parsed.scheme != "https"
        or parsed.netloc != "github.com"
        or parsed.path != expected_path
    ):
        raise ProvenanceError(
            f"workflow.repository must be https://github.com{expected_path}, "
            f"got {repo!r}"
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
    """runDetails.builder.id が allowlist に前方一致 (SLSA v1.0 §7.2、S-3 反映)。"""
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

    検証項目 (SLSA v1.0 spec):
        - §5.1: subject digest + name + multi-subject 一意性 invariant
        - predicateType: SLSA Provenance v1.x の正規 URI
        - §6: buildDefinition.externalParameters.workflow.{repository, ref, path}
          が launcher 埋め込み constant と一致 (信頼根)
        - §7.2: runDetails.builder.id が allowlist (GitHub-hosted runner)

    Args:
        statement: extract_statement() の戻り値
        expected_sha256: artifact の期待 SHA-256 (manifest.checksum_sha256 と一致、
            lowercase 64 hex)
        expected_subject_name: subject name (default: "wiseman_hub.exe")

    Raises:
        ProvenanceError: 上記 4 検証 (subject / predicateType / workflow ref / builder)
            のいずれか 1 件でも不一致の場合
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


_SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


def verify_provenance(
    artifact_path: Path,
    provenance_path: Path,
    *,
    expected_sha256: str,
    expected_version: str,
    expected_subject_name: str = "wiseman_hub.exe",
) -> None:
    """artifact + provenance を検証する (PR-6 後半: signature 検証本実装)。

    手順:
        1. ``sigstore.verify_dsse_bundle``: Sigstore Bundle v0.3 を ``Verifier.verify_dsse``
           で検証 (cert chain + Rekor inclusion proof + identity 完全一致)。戻り値は
           DSSE payload を decode した SLSA Statement dict
        2. ``verify_statement_claims``: 返ってきた statement に対して claims 検証
           (subject digest + name + predicateType + workflow ref + repo + builder id)

    identity の組み立て (codex C2 完全一致):
        ``https://github.com/{LAUNCHER_EXPECTED_REPO}/.github/workflows/release.yml@refs/tags/v{expected_version}``
        manifest の current_version を caller (updater.py) が ``expected_version`` として渡す。

    Args:
        artifact_path: download 済 artifact path (sha256 検証は別途 ``checksum.verify_sha256`` で実施)
        provenance_path: download 済 ``.sigstore.json`` Bundle file path
        expected_sha256: manifest.checksum_sha256 (lowercase 64 hex)
        expected_version: manifest.current_version (例: ``"1.2.3"``)。
            ``refs/tags/v{expected_version}`` の組み立てに使用
        expected_subject_name: 期待 subject name (default: ``"wiseman_hub.exe"``)

    Raises:
        ProvenanceError: signature 検証失敗 (``SigstoreVerifyError`` を wrap) または
            claims 不一致 / parse 失敗
    """
    # type-design 反映: caller 経路によらず expected_version の形式を保証。
    # validate_manifest の semver check を経由しない直接呼出 (test/script) でも、
    # identity URI 改竄 (control char / `..` injection 等) を fail-fast で防ぐ。
    if not _SEMVER_RE.match(expected_version):
        raise ProvenanceError(
            f"expected_version must be semver X.Y.Z, got {expected_version!r}"
        )
    expected_identity = build_expected_identity(
        repo=LAUNCHER_EXPECTED_REPO,
        workflow_path=".github/workflows/release.yml",
        ref=f"refs/tags/v{expected_version}",
    )

    try:
        statement = verify_dsse_bundle(
            bundle_path=provenance_path,
            expected_identity=expected_identity,
        )
    except SigstoreVerifyError as e:
        raise ProvenanceError(f"signature verify failed: {e}") from e

    verify_statement_claims(
        statement,
        expected_sha256=expected_sha256,
        expected_subject_name=expected_subject_name,
    )
    logger.info(
        "provenance verified: artifact=%s sha256=%s subject=%s identity=%s",
        artifact_path.name,
        expected_sha256[:16],
        expected_subject_name,
        expected_identity,
    )
