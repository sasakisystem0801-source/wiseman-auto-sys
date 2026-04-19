"""Wiseman OCR プロキシ (Cloud Run)。

Vertex AI Gemini 2.5 Flash を用いて PDF 切出画像から利用者名を抽出するプロキシサービス。
クライアント（Windows デスクトップアプリ）に GCP 認証情報を持たせないための中継層。

詳細は ADR-008 (docs/adr/008-ocr-backend.md) 参照。
"""
