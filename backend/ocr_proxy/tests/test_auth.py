"""API キー検証のユニットテスト。"""

from __future__ import annotations

import pytest
from app.auth import verify_api_key
from fastapi import HTTPException


def test_accepts_valid_key() -> None:
    keys = frozenset({"abc", "def"})
    assert verify_api_key(keys, "abc") == "abc"


def test_rejects_missing_key() -> None:
    keys = frozenset({"abc"})
    with pytest.raises(HTTPException) as exc:
        verify_api_key(keys, None)
    assert exc.value.status_code == 401
    assert "X-API-Key" in exc.value.detail


def test_rejects_empty_key() -> None:
    keys = frozenset({"abc"})
    with pytest.raises(HTTPException) as exc:
        verify_api_key(keys, "")
    assert exc.value.status_code == 401


def test_rejects_invalid_key() -> None:
    keys = frozenset({"abc", "def"})
    with pytest.raises(HTTPException) as exc:
        verify_api_key(keys, "xyz")
    assert exc.value.status_code == 401


def test_rejects_when_no_keys_configured() -> None:
    """サーバー側に API キーが1つも設定されていない場合は全拒否。"""
    with pytest.raises(HTTPException) as exc:
        verify_api_key(frozenset(), "anything")
    assert exc.value.status_code == 401
