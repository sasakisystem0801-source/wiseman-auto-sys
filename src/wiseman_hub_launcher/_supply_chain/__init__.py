"""supply_chain subpackage — download + provenance + policy (ADR-016 PR-6a)。

constraint: ADR-016 §1.2 で `_supply_chain/` ≤ 350 LOC。

PR-6a で実装:
    - download.py: artifact + provenance file の atomic download (PR-4 から移動)
    - policy.py: canonical URL derivation + LAUNCHER_EXPECTED_REPO 等の信頼根
    - provenance.py: SLSA v1.0 statement parse (Sigstore Bundle / DSSE / plain JSON)

PR-6 後半で:
    - sigstore-python 依存追加 + signature verifier 本実装
    - `--allow-test-unsigned-provenance` 削除
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
    is_test_bypass_authorized,
    validate_canonical_provenance_url,
)
from .provenance import (
    ProvenanceError,
    ProvenanceUnavailable,
    extract_statement,
    verify_provenance,
    verify_statement_claims,
)

__all__ = [
    "LAUNCHER_EXPECTED_REPO",
    "LAUNCHER_EXPECTED_WORKFLOW_REF_PATTERN",
    "MAX_ARTIFACT_BYTES",
    "PROVENANCE_URL_SUFFIX",
    "RELEASE_BUCKET_BASE",
    "DownloadError",
    "ProvenanceError",
    "ProvenanceUnavailable",
    "derive_canonical_provenance_url",
    "download_artifact",
    "download_provenance",
    "extract_statement",
    "is_production_build",
    "is_test_bypass_authorized",
    "validate_canonical_provenance_url",
    "verify_provenance",
    "verify_statement_claims",
]
