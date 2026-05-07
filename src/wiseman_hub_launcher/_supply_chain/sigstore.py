"""Sigstore Bundle v0.3 検証 (ADR-016 PR-6 後半)。

sigstore-python の Verifier に検証を委譲する薄い glue 層。Bundle 読込 + Identity
policy 構築 + ``Verifier.verify_dsse`` 呼出 + 例外正規化のみを担当し、cert chain /
Rekor inclusion proof / TUF trusted root refresh はすべて sigstore-python に任せる。

ADR-016 §1.1.3 (新設):
    launcher runtime stdlib only 制約の唯一の例外として ``sigstore`` のみを許可。
    Sigstore Bundle 検証は真正性ベース supply-chain 防御の本丸であり stdlib only
    では実装不可なため。

設計方針:
    - **identity matching は完全一致** (codex C2 反映): manifest の current_version と
      tag を組み合わせた expected_identity URI を caller (provenance.py) が組み立てて渡す。
      wildcard / prefix match は使わない。
    - **system clock sanity check**: TUF root / cert validity と整合させるため起動時に
      ±2 hour 範囲で UTC clock を確認 (codex C3 反映)
    - **TUF trusted root の運用**: ``Verifier.production()`` 内部で online refresh +
      同梱 cache fallback (sigstore-python が公式 TUF root を内蔵)
    - **戻り値**: DSSE payload を decode した SLSA Statement dict。claims 検証は
      呼出側 (provenance.verify_statement_claims) に委譲する二段構成 (codex C1 反映)
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SigstoreVerifyError(Exception):
    """Sigstore Bundle 検証失敗 (signature 不正 / cert chain / Rekor proof / clock)。"""


_CLOCK_LOWER_BOUND = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
_CLOCK_UPPER_BOUND = dt.datetime(2030, 12, 31, tzinfo=dt.UTC)
_DSSE_PAYLOAD_TYPE_INTOTO = "application/vnd.in-toto+json"
_DEFAULT_GITHUB_OIDC_ISSUER = "https://token.actions.githubusercontent.com"


def _verify_system_clock() -> None:
    now = dt.datetime.now(tz=dt.UTC)
    if not (_CLOCK_LOWER_BOUND <= now <= _CLOCK_UPPER_BOUND):
        raise SigstoreVerifyError(
            f"system clock out of expected range: now={now.isoformat()} "
            f"(expected {_CLOCK_LOWER_BOUND.isoformat()} <= now <= {_CLOCK_UPPER_BOUND.isoformat()})"
        )


def _load_bundle(bundle_path: Path) -> Any:
    """Sigstore Bundle JSON を読み込んで sigstore.models.Bundle インスタンスを返す。"""
    try:
        from sigstore.models import Bundle
    except ImportError as e:
        raise SigstoreVerifyError(
            f"sigstore-python not installed: {type(e).__name__}: {e}"
        ) from e
    try:
        bundle_raw = bundle_path.read_text(encoding="utf-8")
    except OSError as e:
        raise SigstoreVerifyError(f"bundle read failed: {type(e).__name__}") from e
    try:
        return Bundle.from_json(bundle_raw)
    except (ValueError, json.JSONDecodeError) as e:
        raise SigstoreVerifyError(
            f"bundle parse failed: {type(e).__name__}: {e}"
        ) from e


def _build_identity_policy(*, expected_identity: str, expected_issuer: str) -> Any:
    try:
        from sigstore.verify.policy import Identity
    except ImportError as e:
        raise SigstoreVerifyError(
            f"sigstore-python not installed: {type(e).__name__}: {e}"
        ) from e
    return Identity(identity=expected_identity, issuer=expected_issuer)


def _build_verifier() -> Any:
    """Sigstore production Verifier (TUF online refresh + 同梱 cache fallback)。"""
    try:
        from sigstore.verify import Verifier
    except ImportError as e:
        raise SigstoreVerifyError(
            f"sigstore-python not installed: {type(e).__name__}: {e}"
        ) from e
    try:
        return Verifier.production()
    except Exception as e:  # noqa: BLE001 — sigstore TrustedRoot/network 系の例外を一律 wrap
        raise SigstoreVerifyError(
            f"Verifier.production() init failed: {type(e).__name__}: {e}"
        ) from e


def verify_dsse_bundle(
    *,
    bundle_path: Path,
    expected_identity: str,
    expected_issuer: str = _DEFAULT_GITHUB_OIDC_ISSUER,
) -> dict[str, Any]:
    """Sigstore Bundle v0.3 を検証して DSSE statement dict を返す。

    Args:
        bundle_path: download 済 ``.sigstore.json`` bundle path
        expected_identity: 完全一致を要求する OIDC identity URI (caller が組立)。
            例: ``https://github.com/{repo}/.github/workflows/release.yml@refs/tags/v1.2.3``
        expected_issuer: OIDC issuer (default: GitHub Actions OIDC token issuer)

    Returns:
        DSSE payload を decode した SLSA in-toto Statement dict。
        ``_type`` / ``subject`` / ``predicateType`` / ``predicate`` を含むため、
        呼出側で ``provenance.verify_statement_claims`` を続けて呼ぶ二段構成を取る。

    Raises:
        SigstoreVerifyError: clock skew / bundle 読込 / verify_dsse 失敗 /
            payloadType 不正 / payload JSON parse 失敗
    """
    _verify_system_clock()
    bundle = _load_bundle(bundle_path)
    policy = _build_identity_policy(expected_identity=expected_identity, expected_issuer=expected_issuer)
    verifier = _build_verifier()

    try:
        # sigstore-python v3: verify_dsse(bundle, policy) -> (payload_type, payload_bytes)
        payload_type, payload_bytes = verifier.verify_dsse(bundle=bundle, policy=policy)
    except SigstoreVerifyError:
        raise
    except Exception as e:  # noqa: BLE001 — VerificationError / ValueError / RuntimeError 等
        raise SigstoreVerifyError(
            f"verify_dsse failed: {type(e).__name__}: {e}"
        ) from e

    if payload_type != _DSSE_PAYLOAD_TYPE_INTOTO:
        raise SigstoreVerifyError(
            f"DSSE payloadType must be {_DSSE_PAYLOAD_TYPE_INTOTO!r}, got {payload_type!r}"
        )

    if not isinstance(payload_bytes, (bytes, bytearray)):
        raise SigstoreVerifyError(
            f"verify_dsse must return bytes payload, got {type(payload_bytes).__name__}"
        )

    try:
        statement = json.loads(bytes(payload_bytes).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise SigstoreVerifyError(
            f"DSSE payload JSON parse failed: {type(e).__name__}"
        ) from e
    if not isinstance(statement, dict):
        raise SigstoreVerifyError(
            f"DSSE payload must be JSON object, got {type(statement).__name__}"
        )
    return statement


def build_expected_identity(*, repo: str, workflow_path: str, ref: str) -> str:
    """OIDC identity URI を組み立てる (codex C2 完全一致のための helper)。

    Args:
        repo: ``owner/repo`` (例: ``sasakisystem0801-source/wiseman-auto-sys``)
        workflow_path: ``.github/workflows/release.yml`` のような相対 path
        ref: ``refs/tags/v1.2.3`` のような完全 ref 文字列 (manifest の version から組立)

    Returns:
        ``https://github.com/{repo}/{workflow_path}@{ref}`` 形式の URI
    """
    return f"https://github.com/{repo}/{workflow_path}@{ref}"
