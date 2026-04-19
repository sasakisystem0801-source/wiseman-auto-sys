"""環境変数からプロキシの設定を読み込む。

Cloud Run では以下の環境変数を設定する:

- API_KEYS          : カンマ区切りの許可された API キー（Secret Manager からマウント推奨）
- GCP_PROJECT_ID    : Vertex AI 呼び出し対象の GCP プロジェクト ID
- GCP_LOCATION      : Vertex AI のリージョン（既定: asia-northeast1）
- GEMINI_MODEL      : 使用モデル（既定: gemini-2.5-flash）
- RATE_LIMIT        : 1 API キーあたりのレート制限（既定: "60/minute"）
- LOG_LEVEL         : Python ログレベル（既定: INFO）
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    api_keys: frozenset[str]
    gcp_project_id: str
    gcp_location: str
    gemini_model: str
    rate_limit: str
    log_level: str

    @classmethod
    def from_env(cls) -> Settings:
        raw_keys = os.environ.get("API_KEYS", "")
        keys = frozenset(k.strip() for k in raw_keys.split(",") if k.strip())
        return cls(
            api_keys=keys,
            gcp_project_id=os.environ.get("GCP_PROJECT_ID", ""),
            gcp_location=os.environ.get("GCP_LOCATION", "asia-northeast1"),
            gemini_model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
            rate_limit=os.environ.get("RATE_LIMIT", "60/minute"),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
        )


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
    )
