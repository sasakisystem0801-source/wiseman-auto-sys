"""supply-chain policy: canonical URL derivation + 信頼根 constants (ADR-016 PR-6a)。

codex review threadId 019dfd9e:
    - C-1: provenance_url を manifest の信頼入力にせず、canonical derived URL と
      一致必須 (HTTPS + release-prod prefix allowlist + path traversal 禁止)
    - I-2: expected_repo / expected_workflow_ref は launcher 埋め込み constant、
      manifest 値は表示/監査用のみ (二重検証)
    - C-2: --allow-test-unsigned-provenance は環境変数との AND 条件で本番 PC 拒否
"""

from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger(__name__)


# release-prod bucket の public URL prefix (ADR-016 §1.1)
RELEASE_BUCKET_BASE = "https://storage.googleapis.com/wiseman-hub-release-prod/"

# I-2: 信頼根 = launcher 埋め込み constant (manifest 値ではない)
LAUNCHER_EXPECTED_REPO = "sasakisystem0801-source/wiseman-auto-sys"
"""GitHub repo 'owner/repo' 形式。manifest 値とも一致確認するが、信頼根はこの定数。"""

LAUNCHER_EXPECTED_WORKFLOW_REF_PATTERN = re.compile(
    r"^\.github/workflows/release\.yml@refs/tags/v\d+\.\d+\.\d+$"
)
"""workflow ref の許容 pattern。release.yml + tags/vX.Y.Z 形式のみ許可。"""

# Q1-A 修正版 + T0 Explore 結果反映: actions/attest v4 の default 出力は Sigstore
# Bundle JSON、拡張子 .sigstore.json (PR-6a 計画書補正)
PROVENANCE_URL_SUFFIX = ".sigstore.json"

# C-2 二重 gate (本番 PC 配布での誤用防止)
_TEST_BYPASS_ENV_VAR = "WISEMAN_ALLOW_UNSIGNED_PROVENANCE_FOR_TESTS"
_BUILD_FLAVOR_ENV_VAR = "WISEMAN_BUILD_FLAVOR"


def derive_canonical_provenance_url(artifact_url: str) -> str:
    """artifact URL から canonical provenance URL を導出する (C-1)。

    Args:
        artifact_url: HTTPS の artifact 完全 URL (例: https://.../versions/1.2.3/wiseman_hub.exe)

    Returns:
        artifact_url + PROVENANCE_URL_SUFFIX (例: ...wiseman_hub.exe.sigstore.json)

    HTTPS 検証も release-prod prefix 検証も呼び出し側で実施 (本関数は単純 derivation)。
    """
    return artifact_url + PROVENANCE_URL_SUFFIX


def validate_canonical_provenance_url(
    candidate_url: str,
    artifact_url: str,
) -> None:
    """manifest 由来の provenance_url が canonical derived URL と一致するか検証 (C-1)。

    Args:
        candidate_url: manifest から取り出した provenance 完全 URL
        artifact_url: 同 manifest から取り出した artifact 完全 URL

    Raises:
        ValueError: HTTPS 違反 / release-prod prefix 違反 / canonical URL 不一致
    """
    expected = derive_canonical_provenance_url(artifact_url)
    if not isinstance(candidate_url, str):
        raise ValueError(
            f"provenance_url must be str, got {type(candidate_url).__name__}"
        )
    if not candidate_url.startswith("https://"):
        raise ValueError("provenance_url must use HTTPS scheme")
    if not candidate_url.startswith(RELEASE_BUCKET_BASE):
        raise ValueError(
            f"provenance_url must be under release-prod bucket: {RELEASE_BUCKET_BASE}"
        )
    if candidate_url != expected:
        raise ValueError(
            "provenance_url does not match canonical derivation: "
            f"got={candidate_url!r}, expected={expected!r}"
        )


def is_production_build() -> bool:
    """本番 build (PyInstaller wiseman_launcher.exe with WISEMAN_BUILD_FLAVOR=production)。

    本 PR-6a では PyInstaller build 時に環境変数を埋め込む手段を提供せず、
    実行時 env で判定する (PR-6 後半 release workflow で hardcode 化予定)。
    """
    return os.environ.get(_BUILD_FLAVOR_ENV_VAR, "") == "production"


def is_test_bypass_authorized() -> bool:
    """C-2: --allow-test-unsigned-provenance + 環境変数の AND 条件で bypass 許可。

    環境変数 WISEMAN_ALLOW_UNSIGNED_PROVENANCE_FOR_TESTS=1 が設定されている場合のみ
    True。CLI flag だけでは bypass 不可 (本番 PC 配布で flag を渡されても拒否)。

    Returns:
        True なら CLI flag 併用で signature 検証を skip 可能。
    """
    return os.environ.get(_TEST_BYPASS_ENV_VAR, "") == "1"
