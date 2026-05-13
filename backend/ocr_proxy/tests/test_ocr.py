"""OCR レスポンスパースのユニットテスト。"""

from __future__ import annotations

import base64

import pytest
from app.ocr import _parse_response, decode_image


def test_parse_valid_json() -> None:
    text = '{"name": "田中太郎", "confidence": "high", "raw_text": "氏名: 田中太郎"}'
    result = _parse_response(text)
    assert result.name == "田中太郎"
    assert result.confidence == "high"
    assert result.raw_text == "氏名: 田中太郎"


def test_parse_null_name() -> None:
    text = '{"name": null, "confidence": "low", "raw_text": ""}'
    result = _parse_response(text)
    assert result.name is None
    assert result.confidence == "low"


def test_parse_invalid_confidence_fallbacks_to_low() -> None:
    text = '{"name": "佐藤", "confidence": "maybe", "raw_text": ""}'
    result = _parse_response(text)
    assert result.confidence == "low"


def test_parse_non_json_returns_low() -> None:
    text = "Sorry, I cannot read the image"
    result = _parse_response(text)
    assert result.name is None
    assert result.confidence == "low"
    assert "Sorry" in result.raw_text


def test_parse_empty_string() -> None:
    result = _parse_response("")
    assert result.name is None
    assert result.confidence == "low"


def test_parse_non_string_name_becomes_null() -> None:
    # name が数値などで返ってきたケース（Gemini の誤出力）
    text = '{"name": 123, "confidence": "high", "raw_text": ""}'
    result = _parse_response(text)
    assert result.name is None


def test_decode_image_success() -> None:
    data = base64.b64encode(b"hello").decode("ascii")
    assert decode_image(data) == b"hello"


def test_decode_image_invalid_raises() -> None:
    with pytest.raises(ValueError):
        decode_image("!!!not-base64!!!")


def test_gemini_client_empty_project_id_raises() -> None:
    """Issue #29 §4: GeminiClient は空 project_id を起動時 ValueError で拒否する。

    Cloud Run 起動時に lifespan で ``Settings.gcp_project_id`` 空チェックが先に
    効くため通常は発火しないが、テスト・スクリプト等から直接構築するケースで
    fail-fast することを固定する (genai.Client 呼出前に raise されるため
    Vertex AI 接続を試みない)。
    """
    from app.ocr import GeminiClient

    with pytest.raises(ValueError, match="GCP_PROJECT_ID is required"):
        GeminiClient(
            project_id="",
            location="asia-northeast1",
            model="gemini-2.5-flash",
        )
