"""FastAPI エントリポイント。

Cloud Run で `uvicorn app.main:app` として起動する想定。
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from .auth import verify_api_key
from .config import Settings, configure_logging
from .models import ErrorResponse, ExtractNameRequest, ExtractNameResponse
from .ocr import GeminiClient, GenerativeClient, decode_image

logger = logging.getLogger(__name__)

_settings = Settings.from_env()
configure_logging(_settings.log_level)


def _key_func(request: Request) -> str:
    """レート制限のキー。API キーがあればそれを、なければ IP を使う。"""
    return request.headers.get("X-API-Key") or get_remote_address(request)


limiter = Limiter(key_func=_key_func, default_limits=[_settings.rate_limit])


def _build_client() -> GenerativeClient:
    return GeminiClient(
        project_id=_settings.gcp_project_id,
        location=_settings.gcp_location,
        model=_settings.gemini_model,
    )


# Cloud Run コールドスタート時に遅延初期化（テストから差し替え可能）
_client_instance: GenerativeClient | None = None


def get_client() -> GenerativeClient:
    global _client_instance
    if _client_instance is None:
        _client_instance = _build_client()
    return _client_instance


def set_client(client: GenerativeClient | None) -> None:
    """テスト用: クライアント実装を差し替える。"""
    global _client_instance
    _client_instance = client


def get_settings() -> Settings:
    return _settings


app = FastAPI(
    title="Wiseman OCR Proxy",
    description="PDF 切出画像から利用者名を抽出するプロキシ（Vertex AI Gemini 2.5 Flash）",
    version="0.1.0",
)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content=ErrorResponse(error="rate_limit_exceeded", detail=str(exc.detail)).model_dump(),
    )


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/v1/ocr/extract-name",
    response_model=ExtractNameResponse,
    responses={
        401: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
@limiter.limit(_settings.rate_limit)
def extract_name(
    request: Request,
    body: ExtractNameRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    client: Annotated[GenerativeClient, Depends(get_client)],
) -> ExtractNameResponse:
    # Depends 経由で API Key 検証（FastAPI の Header 依存をここで実行）
    verify_api_key(settings.api_keys, request.headers.get("X-API-Key"))

    request_id = str(uuid.uuid4())
    logger.info("extract_name request: id=%s mime=%s", request_id, body.mime_type)

    try:
        image_bytes = decode_image(body.image_base64)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    try:
        result = client.extract(image_bytes, body.mime_type)
    except Exception as e:  # noqa: BLE001 - Vertex AI からの多様な例外を 503 に集約
        logger.exception("Gemini call failed: id=%s", request_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OCR backend is temporarily unavailable",
        ) from e

    # PII（利用者名・raw_text）は本番ログに出さない
    logger.info("extract_name done: id=%s confidence=%s", request_id, result.confidence)
    return result
