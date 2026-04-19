"""OCR プロキシの API テスト。Vertex AI 呼び出しはモック化する。"""

from __future__ import annotations

import base64
import os

import pytest

# TestClient を import する前に環境変数を設定しないと Settings.from_env が空になる。
os.environ.setdefault("API_KEYS", "test-key-1,test-key-2")
os.environ.setdefault("GCP_PROJECT_ID", "test-project")
os.environ.setdefault("GCP_LOCATION", "asia-northeast1")
os.environ.setdefault("RATE_LIMIT", "1000/minute")  # テスト時はレート制限を緩める

from app import main  # noqa: E402
from app.models import ExtractNameResponse  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


class _FakeClient:
    """テスト用のスタブ。extract() が常に同じ応答を返す。"""

    def __init__(
        self,
        response: ExtractNameResponse | None = None,
        raise_exc: Exception | None = None,
    ) -> None:
        self._response = response or ExtractNameResponse(name="田中太郎", confidence="high", raw_text="田中太郎")
        self._raise_exc = raise_exc
        self.calls: list[tuple[bytes, str]] = []

    def extract(self, image_bytes: bytes, mime_type: str) -> ExtractNameResponse:
        self.calls.append((image_bytes, mime_type))
        if self._raise_exc:
            raise self._raise_exc
        return self._response


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app)


@pytest.fixture(autouse=True)
def _reset_client() -> None:
    """各テスト後にグローバルクライアントをリセット。"""
    yield
    main.set_client(None)


def _png_base64() -> str:
    # 1x1 の有効な PNG（実画像でなくてもテストには十分）
    png_hex = (
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000a49444154789c6300010000000500010d0a2db40000000049454e44ae426082"
    )
    return base64.b64encode(bytes.fromhex(png_hex)).decode("ascii")


def test_healthz(client: TestClient) -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_extract_name_requires_api_key(client: TestClient) -> None:
    resp = client.post(
        "/v1/ocr/extract-name",
        json={"image_base64": _png_base64()},
    )
    assert resp.status_code == 401
    assert "X-API-Key" in resp.json()["detail"]


def test_extract_name_rejects_invalid_api_key(client: TestClient) -> None:
    resp = client.post(
        "/v1/ocr/extract-name",
        headers={"X-API-Key": "wrong-key"},
        json={"image_base64": _png_base64()},
    )
    assert resp.status_code == 401


def test_extract_name_success(client: TestClient) -> None:
    fake = _FakeClient(
        response=ExtractNameResponse(name="佐藤花子", confidence="high", raw_text="氏名: 佐藤花子"),
    )
    main.set_client(fake)

    resp = client.post(
        "/v1/ocr/extract-name",
        headers={"X-API-Key": "test-key-1"},
        json={"image_base64": _png_base64(), "mime_type": "image/png"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"name": "佐藤花子", "confidence": "high", "raw_text": "氏名: 佐藤花子"}
    assert len(fake.calls) == 1
    _, mime = fake.calls[0]
    assert mime == "image/png"


def test_extract_name_accepts_second_api_key(client: TestClient) -> None:
    main.set_client(_FakeClient())
    resp = client.post(
        "/v1/ocr/extract-name",
        headers={"X-API-Key": "test-key-2"},
        json={"image_base64": _png_base64()},
    )
    assert resp.status_code == 200


def test_extract_name_rejects_invalid_base64(client: TestClient) -> None:
    main.set_client(_FakeClient())
    resp = client.post(
        "/v1/ocr/extract-name",
        headers={"X-API-Key": "test-key-1"},
        json={"image_base64": "!!!not-base64!!!"},
    )
    assert resp.status_code == 400


def test_extract_name_vertex_error_returns_503(client: TestClient) -> None:
    main.set_client(_FakeClient(raise_exc=RuntimeError("vertex ai down")))
    resp = client.post(
        "/v1/ocr/extract-name",
        headers={"X-API-Key": "test-key-1"},
        json={"image_base64": _png_base64()},
    )
    assert resp.status_code == 503
    assert resp.json()["detail"] == "OCR backend is temporarily unavailable"


def test_extract_name_confidence_low_preserved(client: TestClient) -> None:
    main.set_client(_FakeClient(response=ExtractNameResponse(name=None, confidence="low", raw_text="")))
    resp = client.post(
        "/v1/ocr/extract-name",
        headers={"X-API-Key": "test-key-1"},
        json={"image_base64": _png_base64()},
    )
    assert resp.status_code == 200
    assert resp.json() == {"name": None, "confidence": "low", "raw_text": ""}
