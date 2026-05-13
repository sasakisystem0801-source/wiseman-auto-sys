"""OCR プロキシのレート制限 (slowapi 429) テスト。

Issue #29 §3 対応。``RATE_LIMIT`` 環境変数を test_main.py の ``1000/minute``
から ``2/minute`` に切り替えて ``app.main`` を reload する。テスト終了時に元の
設定 (``"1000/minute"`` 固定値) に reload し、後続テストへの side effect を防ぐ。

slowapi の Limiter は API Key (X-API-Key) ベースで集計するため、同一 key で
3 連続 POST すると 3 回目が 429 になることを確認する。

注意 (pytest-xdist 非対応): このファイルは process-global な
``os.environ`` と module キャッシュを mutate する。``pytest-xdist`` の worker
間ではプロセスが分かれているため worker 跨ぎでは破綻しないが、**同一 worker
内の他テストが ``app.main.app`` の reference を import レベルでキャッシュして
いる場合は再 reload で stale になる**。本リポジトリでは test_main.py が
``from app import main`` (module reference) のみで ``app.main.app`` を直接
キャッシュしていないため安全。新規テストで ``from app.main import app``
パターンを導入する際は本 fixture との競合に注意。
"""

from __future__ import annotations

import base64
import importlib
import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

# Evaluator REQUEST_CHANGES 対応: teardown で固定値リセットして xdist 競合防止。
# test_main.py が setdefault している "1000/minute" を明示再現する (動的退避は
# 環境変数が事前に未設定だった場合の None ハンドリングで競合余地があった)。
_RESTORE_RATE_LIMIT = "1000/minute"


def _png_base64() -> str:
    """1x1 の有効な PNG。実画像でなくてもテストには十分。"""
    png_hex = (
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000a49444154789c6300010000000500010d0a2db40000000049454e44ae426082"
    )
    return base64.b64encode(bytes.fromhex(png_hex)).decode("ascii")


@pytest.fixture
def main_with_2_per_minute_limit() -> Iterator[object]:
    """``RATE_LIMIT=2/minute`` で app.main を reload した module を yield。

    teardown では固定値 ``"1000/minute"`` に戻して reload する (xdist 競合防止)。
    silent-failure-hunter Important #3 対応: slowapi の Limiter ストレージは
    module-global にキャッシュされるため、reload 後も旧 counter が残るリスクが
    ある。yield 前後で ``limiter.reset()`` を呼んで明示クリアする。
    """
    from app.models import ExtractNameResponse

    os.environ["RATE_LIMIT"] = "2/minute"
    os.environ.setdefault("API_KEYS", "test-key-1,test-key-2")
    os.environ.setdefault("GCP_PROJECT_ID", "test-project")
    os.environ.setdefault("GCP_LOCATION", "asia-northeast1")

    from app import main as _main

    importlib.reload(_main)
    # slowapi storage の事前クリア (前テスト残カウンター混入防止)
    _main.limiter.reset()

    class _FakeClient:
        """常に同じ応答を返すスタブ (test_main.py の _FakeClient と同等)。"""

        def extract(self, image_bytes: bytes, mime_type: str) -> ExtractNameResponse:
            return ExtractNameResponse(name="test", confidence="high", raw_text="")

    _main.set_client(_FakeClient())

    try:
        yield _main
    finally:
        # 固定値で復元 (xdist 競合防止、原値退避の None ハンドリング廃止)
        os.environ["RATE_LIMIT"] = _RESTORE_RATE_LIMIT
        importlib.reload(_main)
        _main.limiter.reset()  # teardown でも明示クリア
        _main.set_client(None)


def test_rate_limit_third_request_returns_429(
    main_with_2_per_minute_limit: object,
) -> None:
    """``RATE_LIMIT=2/minute`` で 3 連続リクエストすると 3 回目が 429 になる。

    slowapi のレート制限が decorator 設定だけでなく **実際に発火する** ことを
    e2e で固定する。設定文字列のフォーマットや slowapi 内部の挙動変化を検知する。
    """
    main = main_with_2_per_minute_limit
    client = TestClient(main.app)  # type: ignore[attr-defined]
    payload = {"image_base64": _png_base64()}
    headers = {"X-API-Key": "test-key-1"}

    # 1 回目: 200 OK
    resp1 = client.post("/v1/ocr/extract-name", headers=headers, json=payload)
    assert resp1.status_code == 200, (
        f"1st request should pass: got {resp1.status_code} {resp1.text}"
    )

    # 2 回目: 200 OK
    resp2 = client.post("/v1/ocr/extract-name", headers=headers, json=payload)
    assert resp2.status_code == 200, (
        f"2nd request should pass: got {resp2.status_code} {resp2.text}"
    )

    # 3 回目: 429 (rate limit exceeded)
    resp3 = client.post("/v1/ocr/extract-name", headers=headers, json=payload)
    assert resp3.status_code == 429, (
        f"3rd request should be rate-limited: got {resp3.status_code} {resp3.text}"
    )
    body = resp3.json()
    assert body["error"] == "rate_limit_exceeded"


def test_rate_limit_separate_api_keys_have_independent_quota(
    main_with_2_per_minute_limit: object,
) -> None:
    """異なる API Key は独立した quota を持つ (key_func が X-API-Key ベース)。

    Key-1 で 2 回 (上限) 使い切った後、Key-2 で 1 回叩いても 429 にならず 200 が返る。
    """
    main = main_with_2_per_minute_limit
    client = TestClient(main.app)  # type: ignore[attr-defined]
    payload = {"image_base64": _png_base64()}

    # Key-1 で上限まで消費 (2 / 2)
    for _ in range(2):
        resp = client.post(
            "/v1/ocr/extract-name", headers={"X-API-Key": "test-key-1"}, json=payload
        )
        assert resp.status_code == 200

    # Key-2 は独立した quota なので 200 が返るべき
    resp = client.post(
        "/v1/ocr/extract-name", headers={"X-API-Key": "test-key-2"}, json=payload
    )
    assert resp.status_code == 200, (
        f"Different API Key should have independent quota: got {resp.status_code}"
    )
