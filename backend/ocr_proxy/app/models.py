"""API リクエスト/レスポンスの Pydantic モデル。

ADR-008 の API 仕様に対応する。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Confidence = Literal["high", "medium", "low"]


class ExtractNameRequest(BaseModel):
    image_base64: str = Field(
        ...,
        min_length=1,
        description="PDF から切り出した矩形画像（base64 エンコード、PNG または JPEG）",
    )
    mime_type: Literal["image/png", "image/jpeg"] = Field(
        default="image/png",
        description="画像の MIME タイプ",
    )
    prompt_version: Literal["v1"] = Field(
        default="v1",
        description="プロンプトのバージョニング（将来の A/B テスト用）",
    )
    include_raw_text: bool = Field(
        default=False,
        description=(
            "True の場合、レスポンスの raw_text に Gemini が読み取った全テキスト（PII 含む）を含める。"
            "APPI 準拠のため既定で False。デバッグ用途でのみ有効化すること。"
        ),
    )


class ExtractNameResponse(BaseModel):
    name: str | None = Field(
        ...,
        description="抽出された氏名。認識できない場合は null",
    )
    confidence: Confidence = Field(
        ...,
        description="抽出の信頼度",
    )
    raw_text: str = Field(
        default="",
        description="Gemini が画像から読み取った全テキスト（デバッグ用、PII 含みうる）",
    )


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None
