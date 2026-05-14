"""supply_chain subpackage — download + provenance + policy + sigstore (ADR-016 PR-6 後半)。

constraint: ADR-016 §1.2 で `_supply_chain/` ≤ 415 LOC。

PR-6a で実装済:
    - download.py: artifact + provenance file の atomic download
    - policy.py: canonical URL derivation + LAUNCHER_EXPECTED_REPO 等の信頼根
    - provenance.py: SLSA v1.0 statement parse + claims verify
    - _http.py: HTTPS GET 共通 helper (PR-7 で DRY 化)

PR-6 後半で追加 (本 PR):
    - sigstore.py: sigstore-python 委譲の signature 検証 (ADR-016 §1.1.3 stdlib 例外)
    - provenance.verify_provenance: signature 検証本実装、bypass 経路完全削除
"""

from __future__ import annotations

from .download import (
    MAX_ARTIFACT_BYTES,
    DownloadError,
    download_artifact,
    download_provenance,
)
from .policy import (
    LAUNCHER_EXPECTED_REPO,
    LAUNCHER_EXPECTED_WORKFLOW_REF_PATTERN,
    PROVENANCE_URL_SUFFIX,
    RELEASE_BUCKET_BASE,
    derive_canonical_provenance_url,
    is_production_build,
    validate_canonical_provenance_url,
)
from .provenance import (
    ProvenanceError,
    extract_statement,
    verify_provenance,
    verify_statement_claims,
)
from .sigstore import (
    SigstoreVerifyError,
    build_expected_identity,
    verify_dsse_bundle,
    warn_if_trust_root_stale,
)

__all__ = [
    "LAUNCHER_EXPECTED_REPO",
    "LAUNCHER_EXPECTED_WORKFLOW_REF_PATTERN",
    "MAX_ARTIFACT_BYTES",
    "PROVENANCE_URL_SUFFIX",
    "RELEASE_BUCKET_BASE",
    "DownloadError",
    "ProvenanceError",
    "SigstoreVerifyError",
    "build_expected_identity",
    "derive_canonical_provenance_url",
    "download_artifact",
    "download_provenance",
    "extract_statement",
    "is_production_build",
    "validate_canonical_provenance_url",
    "verify_dsse_bundle",
    "verify_provenance",
    "verify_statement_claims",
    "warn_if_trust_root_stale",
]
