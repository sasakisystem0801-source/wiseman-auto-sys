"""Cloud Run OCR プロキシ（ADR-008）の HTTP クライアント。

画像（PNG bytes）を送信して利用者名を抽出する。
サーバー側一時障害（429 / 5xx / transport error）に対しては指数バックオフで
`OcrBackendConfig.max_retries` 回まで再試行する。認証失敗（401）は再試行しない。

PII 取り扱い: デフォルトは `include_raw_text=False` でレスポンスから raw_text を除外する
（サーバー側が `models.ExtractNameRequest.include_raw_text` に従って空文字列で返す）。

リソース管理: `with OcrClient(...) as client:` での利用を推奨。context manager を使わない
場合は finally で `close()` を必ず呼ぶこと（http.Client の接続プールがリークする）。
"""

from __future__ import annotations

import base64
import json
import logging
import time
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Literal

import httpx

from wiseman_hub.config import OcrBackendConfig

logger = logging.getLogger(__name__)

Confidence = Literal["high", "medium", "low"]

_ENDPOINT_PATH = "/v1/ocr/extract-name"
_MAX_BACKOFF_SEC = 10.0


class OcrClientError(Exception):
    """OCR クライアントの失敗を表す基底例外。"""


class OcrAuthError(OcrClientError):
    """API Key 認証失敗（401）。再試行不可。"""


class OcrServerError(OcrClientError):
    """サーバー側エラー（5xx / 429 / transport error）がリトライ上限に達した。"""


class OcrResponseError(OcrClientError):
    """レスポンスのステータスまたはボディが期待と異なる。"""


@dataclass(frozen=True)
class ExtractNameResult:
    """OCR 抽出結果。

    name: 抽出された氏名。OCR が判読できない、または空白のみの場合は None。
    confidence: high / medium / low。
    raw_text: include_raw_text=True の場合に画像内テキスト全体が入る。
              デフォルトは空文字列（PII 保護）。
    """

    name: str | None
    confidence: Confidence
    raw_text: str = ""


def _backoff_seconds(attempt: int) -> float:
    """指数バックオフ。attempt は 0-based。"""
    return min(2.0**attempt, _MAX_BACKOFF_SEC)


class OcrClient:
    """Cloud Run OCR プロキシの HTTP クライアント。"""

    def __init__(
        self,
        config: OcrBackendConfig,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        if not config.endpoint_url:
            raise ValueError("OcrBackendConfig.endpoint_url is empty")
        if not config.api_key:
            raise ValueError("OcrBackendConfig.api_key is empty")
        self._config = config
        self._url = f"{config.endpoint_url.rstrip('/')}{_ENDPOINT_PATH}"
        self._client = http_client or httpx.Client(timeout=config.timeout_sec)
        self._owns_client = http_client is None
        self._closed = False

    def extract_name(
        self, image_png: bytes, *, include_raw_text: bool = False
    ) -> ExtractNameResult:
        """画像を送信して利用者名を抽出する。

        Raises:
            OcrClientError: close() 後に呼ばれた
            OcrAuthError: 401（再試行しない）
            OcrServerError: 429 / 5xx / transport error がリトライ上限に達した
            OcrResponseError: 想定外のステータスまたは不正なレスポンスボディ
        """
        if self._closed:
            raise OcrClientError("OcrClient is closed")

        payload = {
            "image_base64": base64.b64encode(image_png).decode("ascii"),
            "include_raw_text": include_raw_text,
        }
        headers = {"X-API-Key": self._config.api_key}
        total_attempts = self._config.max_retries + 1

        transient_history: list[str] = []
        for attempt in range(total_attempts):
            try:
                response = self._client.post(self._url, json=payload, headers=headers)
            except httpx.TransportError as e:
                # TransportError 系（ConnectError/ReadError/Timeout 等）のみ retryable。
                # InvalidURL/StreamError/DecodingError 等は設定・プログラミングの誤りのため
                # そのまま伝播させる。
                reason = f"attempt {attempt + 1}: {type(e).__name__}: {e}"
                transient_history.append(reason)
                logger.warning(
                    "OCR transport error (attempt %d/%d): %s: %s",
                    attempt + 1,
                    total_attempts,
                    type(e).__name__,
                    e,
                )
                if attempt + 1 < total_attempts:
                    time.sleep(_backoff_seconds(attempt))
                continue

            if response.status_code == 200:
                return _parse_response(response)
            if response.status_code == 401:
                body = response.text[:200]
                logger.error(
                    "OCR proxy authentication failed (401). "
                    "Check OcrBackendConfig.api_key. Body: %s",
                    body,
                )
                raise OcrAuthError(f"OCR proxy authentication failed (401): {body}")
            if response.status_code == 429 or 500 <= response.status_code < 600:
                reason = f"attempt {attempt + 1}: HTTP {response.status_code}: {response.text[:200]}"
                transient_history.append(reason)
                logger.warning(
                    "OCR transient error (attempt %d/%d): HTTP %d",
                    attempt + 1,
                    total_attempts,
                    response.status_code,
                )
                if attempt + 1 < total_attempts:
                    time.sleep(_backoff_seconds(attempt))
                continue

            body = response.text[:200]
            logger.error(
                "OCR proxy returned unexpected status %d: %s",
                response.status_code,
                body,
            )
            raise OcrResponseError(
                f"Unexpected OCR proxy status {response.status_code}: {body}"
            )

        history_str = "; ".join(transient_history) if transient_history else "no attempt made"
        logger.error(
            "OCR proxy exhausted %d attempts; giving up. History: %s",
            total_attempts,
            history_str,
        )
        raise OcrServerError(
            f"OCR proxy failed after {total_attempts} attempts: {history_str}"
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> OcrClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def _parse_response(response: httpx.Response) -> ExtractNameResult:
    try:
        payload: Any = response.json()
    except json.JSONDecodeError as e:
        raise OcrResponseError(f"OCR proxy returned non-JSON body: {e}") from e

    if not isinstance(payload, dict):
        raise OcrResponseError(f"OCR proxy returned non-object body: {type(payload).__name__}")

    name = payload.get("name")
    if name is not None and not isinstance(name, str):
        raise OcrResponseError(f"name must be str or None, got {type(name).__name__}")
    # 空白のみ/空文字列は OCR 不調とみなし None 扱い（下流が "high confidence + empty" で
    # garbage を保存しないよう防御）
    if isinstance(name, str) and not name.strip():
        name = None

    confidence = payload.get("confidence")
    if confidence not in ("high", "medium", "low"):
        raise OcrResponseError(f"unknown confidence value: {confidence!r}")

    raw_text = payload.get("raw_text", "")
    if not isinstance(raw_text, str):
        raise OcrResponseError(f"raw_text must be str, got {type(raw_text).__name__}")

    return ExtractNameResult(name=name, confidence=confidence, raw_text=raw_text)
