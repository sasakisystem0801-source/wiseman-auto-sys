"""Sigstore Bundle v0.3 検証 (ADR-016 PR-6 後半)。

sigstore-python の Verifier に検証を委譲する薄い glue 層。Bundle 読込 + Identity
policy 構築 + ``Verifier.verify_dsse`` 呼出 + 例外正規化のみを担当し、cert chain /
Rekor inclusion proof / TUF trusted root refresh はすべて sigstore-python に任せる。

依存:
    ``sigstore>=3.0,<4.0`` に pin (pyproject.toml)。3.x 以降は trust roots レイアウト
    (``sigstore/_store/prod/{root,trusted_root}.json``) と ``Verifier.production``
    の API がこの実装の前提。4.x への major upgrade は API breaking change
    (TrustedRoot 構築経路 / verify_dsse 戻り値型) の可能性があるため、bound 緩和は
    必ず build-windows-smoke.yml の ``--smoke-test`` で
    ``Verifier.production(offline=True)`` 初期化が成功すること + tests/unit/launcher/
    の sigstore 系 unit tests + 実機検証 (PR-6 後半 verify_dsse 経路) を 1 セット
    通してから判断する。

ADR-016 §1.1.3 (新設):
    launcher runtime stdlib only 制約の唯一の例外として ``sigstore`` のみを許可。
    Sigstore Bundle 検証は真正性ベース supply-chain 防御の本丸であり stdlib only
    では実装不可なため。

設計方針:
    - **identity matching は完全一致** (codex C2 反映): manifest の current_version と
      tag を組み合わせた expected_identity URI を caller (provenance.verify_provenance) が
      ``build_expected_identity`` で組み立てて渡す。wildcard / prefix match は使わない。
    - **system clock sanity check**: 起動時に UTC clock が **2026-01-01〜2030-12-31** の
      絶対範囲内であることを確認 (codex C3 反映)。範囲外は ``SigstoreVerifyError`` raise。
      2030 上限は本 appliance のサポート期限と整合 — 期限到来前に再検討必須 (TODO)。
    - **TUF trusted root の運用 (offline=True)**: ``Verifier.production(offline=True)``
      で TUF online refresh を skip し、bundle 済 trust roots
      (``sigstore/_store/prod/{root,trusted_root}.json``) のみで verify する。
      online refresh は Windows 上で ``root_history/N.root.json`` への symlink を
      作成する経路があり、非管理者 user では ``WinError 1314`` で失敗する
      (Phase 6 canary 検証 2026-05-13、PR #254 後継)。launcher は集中型運用
      (1 台で 40 事業所データを処理) で **launcher 再 build 時に新 trust roots を
      取り込むモデル**のため online refresh は不要。失敗時は引き続き
      ``SigstoreVerifyError`` に wrap して fail-close。
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
# TODO(2030-12-31 expiry): 本 appliance のサポート期限。期限到来前に再検討必須。
# 期限超過で launcher 起動拒否 (signature 改竄ではなく時計範囲外として fail-close)。
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
    """Sigstore production Verifier (offline=True: TUF online refresh を skip)。

    ``offline=True`` は bundle 済 trust roots のみで verify する。Windows symlink
    権限要件 (``WinError 1314``) を回避し、launcher の集中型運用モデル
    (1 台 / launcher 再 build 時に trust root 更新) と整合させる。
    詳細はモジュール docstring 参照。
    """
    try:
        from sigstore.verify import Verifier
    except ImportError as e:
        raise SigstoreVerifyError(
            f"sigstore-python not installed: {type(e).__name__}: {e}"
        ) from e
    try:
        return Verifier.production(offline=True)
    except Exception as e:  # noqa: BLE001 — sigstore TrustedRoot 系の例外を一律 wrap
        raise SigstoreVerifyError(
            f"Verifier.production(offline=True) init failed: {type(e).__name__}: {e}"
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
