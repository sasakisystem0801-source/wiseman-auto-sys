"""OCR プロキシの API テスト。Vertex AI 呼び出しはモック化する。"""

from __future__ import annotations

import base64
import os

import pytest
from google.api_core import exceptions as gax_exceptions

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


def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_healthz_route_is_not_registered() -> None:
    """Issue #58: /healthz は Cloud Run GFE 404 と衝突するため登録禁止。

    catch-all ハンドラ追加等で 404 が隠蔽される脆さを避け、
    ルート表から /healthz が除外されていることを直接検証する。
    """
    registered_paths = {getattr(r, "path", None) for r in main.app.routes}
    assert "/healthz" not in registered_paths
    assert "/health" in registered_paths


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


def test_extract_name_success_strips_raw_text_by_default(client: TestClient) -> None:
    """APPI 準拠: include_raw_text 未指定なら raw_text は空で返す（PII 漏洩防止）。"""
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
    # name と confidence は返すが、raw_text は PII のため空に落とされる
    assert body == {"name": "佐藤花子", "confidence": "high", "raw_text": ""}
    assert len(fake.calls) == 1
    _, mime = fake.calls[0]
    assert mime == "image/png"


def test_extract_name_returns_raw_text_when_opted_in(client: TestClient) -> None:
    """include_raw_text=True で明示的にオプトインした場合のみ raw_text を返す。"""
    main.set_client(
        _FakeClient(response=ExtractNameResponse(name="田中", confidence="high", raw_text="氏名: 田中"))
    )
    resp = client.post(
        "/v1/ocr/extract-name",
        headers={"X-API-Key": "test-key-1"},
        json={"image_base64": _png_base64(), "include_raw_text": True},
    )
    assert resp.status_code == 200
    assert resp.json() == {"name": "田中", "confidence": "high", "raw_text": "氏名: 田中"}


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


@pytest.mark.parametrize(
    "exc_class",
    [
        gax_exceptions.ServiceUnavailable,
        gax_exceptions.ResourceExhausted,
        gax_exceptions.DeadlineExceeded,
        gax_exceptions.InternalServerError,
    ],
    ids=["503_unavailable", "429_quota", "504_timeout", "500_internal"],
)
def test_extract_name_transient_gax_errors_return_503(
    client: TestClient, exc_class: type[gax_exceptions.GoogleAPICallError]
) -> None:
    """Issue #29 §2: Vertex AI / Gemini SDK が投げる 4 種類の transient 例外は 503 集約。

    旧コード ``except Exception`` の代替として、明示的に google.api_core の
    transient 系のみを 503 に変換することを固定する。
    """
    main.set_client(_FakeClient(raise_exc=exc_class("simulated transient")))
    resp = client.post(
        "/v1/ocr/extract-name",
        headers={"X-API-Key": "test-key-1"},
        json={"image_base64": _png_base64()},
    )
    assert resp.status_code == 503
    assert resp.json()["detail"] == "OCR backend is temporarily unavailable"


def test_extract_name_logic_bug_does_not_return_503() -> None:
    """Issue #29 §2: ロジックバグ (ValueError 等) が 503 に変換されないことを確認。

    旧 ``except Exception`` はプログラミングバグも 503 として返し、クライアントの
    自動リトライで無限に再発させていた。新挙動では transient 例外以外は捕捉せず、
    production では FastAPI のデフォルトハンドラに任せて 500 を返す
    (透過的に表面化させて修正につなげる)。

    ``raise_server_exceptions=False`` で TestClient を構築することで、production
    挙動 (500 レスポンス) を再現する。デフォルト True ではテスト側で再 raise される。
    """
    main.set_client(_FakeClient(raise_exc=ValueError("programming bug")))
    test_client = TestClient(main.app, raise_server_exceptions=False)
    resp = test_client.post(
        "/v1/ocr/extract-name",
        headers={"X-API-Key": "test-key-1"},
        json={"image_base64": _png_base64()},
    )
    # 503 ではなく 500 (Internal Server Error) になることを確認
    assert resp.status_code == 500


def test_extract_name_runtime_error_does_not_return_503() -> None:
    """同上 §2: 旧テストの ``RuntimeError`` も 503 ではなく 500 fallthrough になる。"""
    main.set_client(_FakeClient(raise_exc=RuntimeError("not a Vertex transient")))
    test_client = TestClient(main.app, raise_server_exceptions=False)
    resp = test_client.post(
        "/v1/ocr/extract-name",
        headers={"X-API-Key": "test-key-1"},
        json={"image_base64": _png_base64()},
    )
    assert resp.status_code == 500


def test_extract_name_confidence_low_preserved(client: TestClient) -> None:
    main.set_client(_FakeClient(response=ExtractNameResponse(name=None, confidence="low", raw_text="")))
    resp = client.post(
        "/v1/ocr/extract-name",
        headers={"X-API-Key": "test-key-1"},
        json={"image_base64": _png_base64()},
    )
    assert resp.status_code == 200
    assert resp.json() == {"name": None, "confidence": "low", "raw_text": ""}


def test_lifespan_preserves_injected_client() -> None:
    """lifespan は既に set_client() で差し替えられたクライアントを上書きしない。
    これによりテストでは実 Vertex AI 初期化を回避でき、本番では未設定時のみ fail-fast する。"""
    fake = _FakeClient()
    main.set_client(fake)
    with TestClient(main.app) as ctx_client:
        resp = ctx_client.get("/health")
        assert resp.status_code == 200
    assert main._client_instance is fake


def test_lifespan_fails_fast_without_api_keys() -> None:
    """API_KEYS が空の場合、lifespan は RuntimeError を上げてコンテナ起動を失敗させる。
    fail-open（認証無しで稼働）の誤デプロイを構造的に防ぐ。"""
    from app.config import Settings
    from fastapi import FastAPI

    # 現在の _settings を退避して API_KEYS 空のものに差し替え
    original = main._settings
    main._settings = Settings(
        api_keys=frozenset(),
        gcp_project_id="test",
        gcp_location="asia-northeast1",
        gemini_model="gemini-2.5-flash",
        rate_limit="60/minute",
        log_level="INFO",
    )
    try:
        temp_app = FastAPI(lifespan=main.lifespan)
        with pytest.raises(RuntimeError, match="API_KEYS"), TestClient(temp_app):
            pass
    finally:
        main._settings = original
        main.set_client(None)
