# Wiseman OCR Proxy

PDF 切出画像から利用者名を抽出する FastAPI プロキシ。
Vertex AI Gemini 2.5 Flash を呼び出す。

詳細な設計判断は [`docs/adr/008-ocr-backend.md`](../../docs/adr/008-ocr-backend.md) 参照。

## API

### `POST /v1/ocr/extract-name`

リクエスト:

```http
POST /v1/ocr/extract-name
Content-Type: application/json
X-API-Key: <client-key>

{
  "image_base64": "iVBORw0KGgo...",
  "mime_type": "image/png",
  "prompt_version": "v1"
}
```

レスポンス 200:

```json
{
  "name": "田中太郎",
  "confidence": "high",
  "raw_text": "氏名: 田中太郎"
}
```

エラー:
- `401 Unauthorized`: `X-API-Key` がない / 無効
- `400 Bad Request`: base64 デコード失敗
- `429 Too Many Requests`: レート制限超過（既定 60/minute/API key）
- `503 Service Unavailable`: Vertex AI 呼び出し失敗（クライアントはリトライ）

### `GET /healthz`

Cloud Run のヘルスチェック用。`{"status": "ok"}` を返す。

## ローカル開発

```bash
cd backend/ocr_proxy
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest pytest-asyncio httpx

# テスト
pytest

# 起動（ダミー設定）
export API_KEYS=dev-key-1
export GCP_PROJECT_ID=your-project-id
export GCP_LOCATION=asia-northeast1
uvicorn app.main:app --reload
```

実 Vertex AI 呼び出しには GCP 認証が必要（`gcloud auth application-default login`）。
テスト実行時は `app.main.set_client()` でクライアントをモック化すれば認証不要。

## デプロイ

[`deploy.md`](./deploy.md) を参照。
