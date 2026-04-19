"""API キー認証。

X-API-Key ヘッダを検証する。設定された API キー集合との定数時間比較を行う。
"""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status


def verify_api_key(
    api_keys: frozenset[str],
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> str:
    """X-API-Key ヘッダを検証し、有効なキーを返す。

    無効な場合は 401 を返す。タイミング攻撃を避けるため、全キーとの比較を
    定数時間で行う（`hmac.compare_digest`）。
    """
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-API-Key header is required",
        )

    # 定数時間比較で全候補をチェック（キー集合が小さいので総当たりでもO(1)同等）
    matched = False
    for valid_key in api_keys:
        if hmac.compare_digest(x_api_key, valid_key):
            matched = True

    if not matched:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    return x_api_key
