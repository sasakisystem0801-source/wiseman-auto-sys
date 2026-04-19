"""Vertex AI Gemini 2.5 Flash を用いた画像→氏名抽出。

Cloud Run 上の Service Account (roles/aiplatform.user) で Vertex AI に認証する。
クライアント認証情報はサーバー内で完結し、呼び出し元には返さない。
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
from typing import Protocol

from google import genai
from google.genai import types

from .models import Confidence, ExtractNameResponse

logger = logging.getLogger(__name__)

# Gemini に期待するプロンプト。v1。
_PROMPT_V1 = """\
あなたは介護事業所の書類から利用者の氏名を抽出する専門家です。
与えられた画像は、介護記録の固定矩形範囲を切り出したものです。

次の JSON 形式でのみ回答してください。他の文字列は出力しないこと。

{
  "name": "抽出された氏名（姓名。例: 田中太郎）。読めない/自信がない場合は null",
  "confidence": "high" | "medium" | "low",
  "raw_text": "画像から読み取った全テキスト（改行は \\n）"
}

判断基準:
- high: 文字が明瞭で、姓名が明確に読める
- medium: 一部の文字に曖昧さがある、または氏名以外の文字が混在
- low: ほぼ判読できない、または画像に氏名が含まれていない
"""


class GenerativeClient(Protocol):
    """テスト用に差し替え可能なクライアントインタフェース。"""

    def extract(self, image_bytes: bytes, mime_type: str) -> ExtractNameResponse: ...


class GeminiClient:
    """google-genai SDK ラッパー。Vertex AI モードで初期化する。"""

    def __init__(self, project_id: str, location: str, model: str) -> None:
        if not project_id:
            raise ValueError("GCP_PROJECT_ID is required")
        self._client = genai.Client(vertexai=True, project=project_id, location=location)
        self._model = model

    def extract(self, image_bytes: bytes, mime_type: str) -> ExtractNameResponse:
        response = self._client.models.generate_content(
            model=self._model,
            contents=[
                _PROMPT_V1,
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.0,
            ),
        )
        return _parse_response(response.text or "")


def _parse_response(text: str) -> ExtractNameResponse:
    """Gemini の JSON レスポンスを ExtractNameResponse にパース。

    パースできない場合は low 信頼度で返す（呼び出し元が判断できるように）。
    """
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Gemini response is not valid JSON, falling back to low confidence")
        return ExtractNameResponse(name=None, confidence="low", raw_text=text[:500])

    name = payload.get("name")
    if name is not None and not isinstance(name, str):
        name = None

    confidence_raw = payload.get("confidence", "low")
    confidence: Confidence = confidence_raw if confidence_raw in ("high", "medium", "low") else "low"

    raw_text = payload.get("raw_text", "")
    if not isinstance(raw_text, str):
        raw_text = ""

    return ExtractNameResponse(name=name, confidence=confidence, raw_text=raw_text)


def decode_image(image_base64: str) -> bytes:
    """base64 デコード。無効な場合は ValueError。"""
    try:
        return base64.b64decode(image_base64, validate=True)
    except (binascii.Error, ValueError) as e:
        raise ValueError(f"invalid base64 image: {e}") from e
