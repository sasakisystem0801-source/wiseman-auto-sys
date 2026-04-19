"""OCR HTTP クライアントのユニットテスト。

httpx.MockTransport で Cloud Run プロキシのレスポンスを模擬する。
リトライ時の sleep は monkeypatch で無効化する。
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from wiseman_hub.config import OcrBackendConfig
from wiseman_hub.pdf.ocr_client import (
    ExtractNameResult,
    OcrAuthError,
    OcrClient,
    OcrClientError,
    OcrResponseError,
    OcrServerError,
)

_DUMMY_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """リトライ時のスリープを0秒に短縮してテスト高速化。"""
    monkeypatch.setattr("wiseman_hub.pdf.ocr_client.time.sleep", lambda _: None)


def _make_client(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    max_retries: int = 3,
) -> OcrClient:
    config = OcrBackendConfig(
        endpoint_url="https://example.run.app",
        api_key="test-key",
        timeout_sec=5,
        max_retries=max_retries,
    )
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, timeout=5)
    return OcrClient(config, http_client=http)


# --- 初期化 --------------------------------------------------------


def test_init_raises_on_empty_endpoint() -> None:
    config = OcrBackendConfig(endpoint_url="", api_key="k")
    with pytest.raises(ValueError, match="endpoint_url"):
        OcrClient(config)


def test_init_raises_on_empty_api_key() -> None:
    config = OcrBackendConfig(endpoint_url="https://x.run.app", api_key="")
    with pytest.raises(ValueError, match="api_key"):
        OcrClient(config)


# --- 正常系 --------------------------------------------------------


def test_extract_name_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"name": "田中太郎", "confidence": "high", "raw_text": ""},
        )

    with _make_client(handler) as client:
        result = client.extract_name(_DUMMY_PNG)

    assert isinstance(result, ExtractNameResult)
    assert result.name == "田中太郎"
    assert result.confidence == "high"
    assert result.raw_text == ""


def test_extract_name_sends_api_key_and_base64() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["api_key"] = request.headers.get("X-API-Key")
        captured["body"] = request.content
        return httpx.Response(200, json={"name": None, "confidence": "low", "raw_text": ""})

    with _make_client(handler) as client:
        client.extract_name(_DUMMY_PNG)

    assert captured["url"] == "https://example.run.app/v1/ocr/extract-name"
    assert captured["api_key"] == "test-key"
    import json

    payload = json.loads(captured["body"])  # type: ignore[arg-type]
    assert "image_base64" in payload
    assert payload["include_raw_text"] is False
    # base64 デコードして元に戻ること
    import base64

    assert base64.b64decode(payload["image_base64"]) == _DUMMY_PNG


def test_extract_name_include_raw_text_flag() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"name": None, "confidence": "low", "raw_text": "foo"})

    with _make_client(handler) as client:
        result = client.extract_name(_DUMMY_PNG, include_raw_text=True)

    assert captured["payload"]["include_raw_text"] is True  # type: ignore[index]
    assert result.raw_text == "foo"


def test_endpoint_url_with_trailing_slash_is_normalized() -> None:
    """endpoint_url の末尾スラッシュを剥がしてURLを組み立てる。"""
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"name": None, "confidence": "low", "raw_text": ""})

    config = OcrBackendConfig(endpoint_url="https://x.run.app/", api_key="k")
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    with OcrClient(config, http_client=http) as client:
        client.extract_name(_DUMMY_PNG)

    assert captured["url"] == "https://x.run.app/v1/ocr/extract-name"


# --- 認証エラー ---------------------------------------------------


def test_401_raises_auth_error_without_retry() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(401, json={"detail": "Invalid API key"})

    with _make_client(handler) as client, pytest.raises(OcrAuthError):
        client.extract_name(_DUMMY_PNG)

    assert calls["count"] == 1  # リトライしない


# --- リトライ -----------------------------------------------------


def test_retries_on_5xx_then_succeeds() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] < 3:
            return httpx.Response(503, text="Service Unavailable")
        return httpx.Response(200, json={"name": "佐藤", "confidence": "high", "raw_text": ""})

    with _make_client(handler, max_retries=3) as client:
        result = client.extract_name(_DUMMY_PNG)

    assert calls["count"] == 3
    assert result.name == "佐藤"


def test_retries_exhausted_on_persistent_5xx_raises_server_error() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(500, text="Internal Error")

    with _make_client(handler, max_retries=3) as client, pytest.raises(OcrServerError):
        client.extract_name(_DUMMY_PNG)

    assert calls["count"] == 4  # 初回 + 3回リトライ


def test_retries_on_429() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(429, text="Too Many Requests")
        return httpx.Response(200, json={"name": None, "confidence": "low", "raw_text": ""})

    with _make_client(handler) as client:
        client.extract_name(_DUMMY_PNG)

    assert calls["count"] == 2


def test_retries_on_connection_error() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] < 2:
            raise httpx.ConnectError("connection refused")
        return httpx.Response(200, json={"name": None, "confidence": "low", "raw_text": ""})

    with _make_client(handler) as client:
        client.extract_name(_DUMMY_PNG)

    assert calls["count"] == 2


def test_retries_exhausted_on_persistent_connection_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with _make_client(handler, max_retries=2) as client, pytest.raises(OcrServerError):
        client.extract_name(_DUMMY_PNG)


# --- レスポンス不正 ------------------------------------------------


def test_unexpected_status_raises_response_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(418, text="I'm a teapot")

    with _make_client(handler) as client, pytest.raises(OcrResponseError):
        client.extract_name(_DUMMY_PNG)


def test_malformed_json_raises_response_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    with _make_client(handler) as client, pytest.raises(OcrResponseError):
        client.extract_name(_DUMMY_PNG)


def test_missing_name_field_is_treated_as_null() -> None:
    """name 欠損は null 扱いで通す（low confidence で返す OCR の挙動に沿う）。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"confidence": "low", "raw_text": ""})

    with _make_client(handler) as client:
        result = client.extract_name(_DUMMY_PNG)

    assert result.name is None


def test_invalid_confidence_value_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"name": "X", "confidence": "super-high", "raw_text": ""}
        )

    with _make_client(handler) as client, pytest.raises(OcrResponseError, match="confidence"):
        client.extract_name(_DUMMY_PNG)


def test_name_wrong_type_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"name": 123, "confidence": "high", "raw_text": ""}
        )

    with _make_client(handler) as client, pytest.raises(OcrResponseError, match="name"):
        client.extract_name(_DUMMY_PNG)


# --- 非遷移エラーはリトライしない（httpx.TransportError 以外）-----------


def test_non_transient_httpx_error_not_retried() -> None:
    """InvalidURL は設定ミスなのでリトライせず即伝播する。"""
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        calls["count"] += 1
        return httpx.Response(200, json={"name": None, "confidence": "low", "raw_text": ""})

    def raise_invalid_url(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        raise httpx.InvalidURL("bad url")

    config = OcrBackendConfig(
        endpoint_url="https://x.run.app", api_key="k", max_retries=3
    )
    transport = httpx.MockTransport(raise_invalid_url)
    http = httpx.Client(transport=transport)
    with (
        OcrClient(config, http_client=http) as client,
        pytest.raises(httpx.InvalidURL),
    ):
        client.extract_name(_DUMMY_PNG)
    assert calls["count"] == 1  # リトライしていない


# --- raw_text の型検証 ---------------------------------------------


def test_non_string_raw_text_raises() -> None:
    """dict の raw_text は silent に空文字列化せず OcrResponseError を上げる。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"name": "X", "confidence": "low", "raw_text": {"unexpected": "dict"}},
        )

    with _make_client(handler) as client, pytest.raises(OcrResponseError, match="raw_text"):
        client.extract_name(_DUMMY_PNG)


# --- 空白 name の正規化 --------------------------------------------


def test_whitespace_only_name_treated_as_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"name": "   ", "confidence": "low", "raw_text": ""}
        )

    with _make_client(handler) as client:
        result = client.extract_name(_DUMMY_PNG)

    assert result.name is None


def test_empty_name_treated_as_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"name": "", "confidence": "low", "raw_text": ""}
        )

    with _make_client(handler) as client:
        result = client.extract_name(_DUMMY_PNG)

    assert result.name is None


# --- ロギング -------------------------------------------------------


def test_401_logs_error_before_raising(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="bad key")

    import logging

    caplog.set_level(logging.ERROR, logger="wiseman_hub.pdf.ocr_client")
    with _make_client(handler) as client, pytest.raises(OcrAuthError):
        client.extract_name(_DUMMY_PNG)

    assert any("401" in r.message for r in caplog.records if r.levelno >= logging.ERROR)


def test_retry_exhaustion_logs_error_with_history(
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(503, text="down")

    import logging

    caplog.set_level(logging.ERROR, logger="wiseman_hub.pdf.ocr_client")
    with _make_client(handler, max_retries=2) as client, pytest.raises(OcrServerError) as exc_info:
        client.extract_name(_DUMMY_PNG)

    # 全試行の履歴が例外メッセージと logger.error の両方に残る
    assert "attempt 1" in str(exc_info.value)
    assert "attempt 3" in str(exc_info.value)
    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("exhausted" in r.message for r in error_records)


def test_unexpected_status_logs_error(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(418, text="teapot")

    import logging

    caplog.set_level(logging.ERROR, logger="wiseman_hub.pdf.ocr_client")
    with _make_client(handler) as client, pytest.raises(OcrResponseError):
        client.extract_name(_DUMMY_PNG)

    assert any(
        "418" in r.message for r in caplog.records if r.levelno >= logging.ERROR
    )


# --- リソース管理 ---------------------------------------------------


def test_close_is_idempotent() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"name": None, "confidence": "low", "raw_text": ""})

    client = _make_client(handler)
    client.close()
    client.close()  # 二度目でも例外が出ない


def test_extract_name_after_close_raises_client_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"name": None, "confidence": "low", "raw_text": ""})

    client = _make_client(handler)
    client.close()
    with pytest.raises(OcrClientError, match="closed"):
        client.extract_name(_DUMMY_PNG)
