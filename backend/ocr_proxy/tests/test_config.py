"""Settings.from_env() のパーステスト。

誤デプロイ時の fail-closed 挙動（空 API_KEYS → 全拒否）を保証する。
"""

from __future__ import annotations

import pytest
from app.config import Settings


def test_defaults_when_env_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """環境変数未設定時は安全なデフォルト値（空 API Keys、空 project_id）を返す。"""
    for var in ("API_KEYS", "GCP_PROJECT_ID", "GCP_LOCATION", "GEMINI_MODEL", "RATE_LIMIT", "LOG_LEVEL"):
        monkeypatch.delenv(var, raising=False)

    s = Settings.from_env()
    # fail-closed: キー無しなら空集合（全リクエスト 401）
    assert s.api_keys == frozenset()
    assert s.gcp_project_id == ""
    assert s.gcp_location == "asia-northeast1"
    assert s.gemini_model == "gemini-2.5-flash"
    assert s.rate_limit == "60/minute"
    assert s.log_level == "INFO"


def test_single_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEYS", "single-key")
    s = Settings.from_env()
    assert s.api_keys == frozenset({"single-key"})


def test_multiple_api_keys_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    """複数キーをカンマ区切りで解釈する（ローテーション時の過渡期用途）。"""
    monkeypatch.setenv("API_KEYS", "key-a,key-b,key-c")
    s = Settings.from_env()
    assert s.api_keys == frozenset({"key-a", "key-b", "key-c"})


def test_api_keys_trim_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    """Secret Manager の多行記入などで混入する余白・空要素を正規化する。"""
    monkeypatch.setenv("API_KEYS", " key-a , , key-b \n")
    s = Settings.from_env()
    assert s.api_keys == frozenset({"key-a", "key-b"})


def test_empty_api_keys_string_yields_empty_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """空文字 API_KEYS は fail-closed（全拒否）になること。誤デプロイ時の安全装置。"""
    monkeypatch.setenv("API_KEYS", "")
    s = Settings.from_env()
    assert s.api_keys == frozenset()


def test_custom_location_and_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GCP_LOCATION", "us-central1")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-pro")
    s = Settings.from_env()
    assert s.gcp_location == "us-central1"
    assert s.gemini_model == "gemini-2.5-pro"


def test_rate_limit_and_log_level_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RATE_LIMIT", "30/minute")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    s = Settings.from_env()
    assert s.rate_limit == "30/minute"
    assert s.log_level == "DEBUG"
