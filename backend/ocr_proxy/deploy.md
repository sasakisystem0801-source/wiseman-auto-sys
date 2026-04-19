# Cloud Run デプロイ手順

asia-northeast1 に `wiseman-ocr-proxy` サービスをデプロイする。
初回のみインフラ作成、以降は `gcloud run deploy` で更新する。

## 前提

- `gcloud` 認証済み（`gcloud auth login`）
- 対象プロジェクトがアクティブ（`gcloud config set project <PROJECT_ID>`）
- 必要 API 有効化:
  ```bash
  gcloud services enable \
      run.googleapis.com \
      aiplatform.googleapis.com \
      secretmanager.googleapis.com \
      artifactregistry.googleapis.com \
      cloudbuild.googleapis.com
  ```

## 初回セットアップ

### 1. Service Account を作成（最小権限）

```bash
PROJECT_ID=$(gcloud config get-value project)
SA_NAME=wiseman-ocr-proxy
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud iam service-accounts create "${SA_NAME}" \
    --display-name="Wiseman OCR Proxy Cloud Run SA"

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/aiplatform.user"
```

### 2. API キーを Secret Manager に作成

```bash
# 32バイトのランダムキーを生成して登録
python -c "import secrets; print(secrets.token_urlsafe(32))" > /tmp/ocr-key.txt

gcloud secrets create wiseman-ocr-api-keys \
    --replication-policy=automatic \
    --data-file=/tmp/ocr-key.txt

gcloud secrets add-iam-policy-binding wiseman-ocr-api-keys \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/secretmanager.secretAccessor"

# クライアントに渡すキーを控える（このファイルはリポジトリに含めない）
cat /tmp/ocr-key.txt
rm /tmp/ocr-key.txt
```

複数クライアントに別キーを配る場合は、`API_KEYS` をカンマ区切りで複数登録する。

### 3. Artifact Registry リポジトリを作成

```bash
gcloud artifacts repositories create wiseman-proxy \
    --repository-format=docker \
    --location=asia-northeast1 \
    --description="Wiseman Cloud Run containers"
```

## デプロイ（初回および以降）

`backend/ocr_proxy/` 直下で実行する。

```bash
PROJECT_ID=$(gcloud config get-value project)
REGION=asia-northeast1
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/wiseman-proxy/ocr-proxy:$(date +%Y%m%d-%H%M%S)"

# ビルド（Cloud Build を使用）
gcloud builds submit --tag "${IMAGE}" .

# デプロイ
gcloud run deploy wiseman-ocr-proxy \
    --image "${IMAGE}" \
    --region "${REGION}" \
    --service-account "wiseman-ocr-proxy@${PROJECT_ID}.iam.gserviceaccount.com" \
    --no-allow-unauthenticated \
    --min-instances 0 \
    --max-instances 2 \
    --concurrency 10 \
    --memory 512Mi \
    --cpu 1 \
    --timeout 60 \
    --set-env-vars "GCP_PROJECT_ID=${PROJECT_ID},GCP_LOCATION=${REGION},GEMINI_MODEL=gemini-2.5-flash,RATE_LIMIT=60/minute" \
    --set-secrets "API_KEYS=wiseman-ocr-api-keys:latest"
```

### `--no-allow-unauthenticated` について

クライアントは API Key で認証するため、Cloud Run の IAM 認証は**不要**に見えるが、
二重防御として推奨。クライアント PC には追加で Identity Token を発行して Authorization ヘッダを付与する必要がある。

**1施設1PC の初期運用では、運用簡略化のため `--allow-unauthenticated` を選択する**。
複数施設展開時に IAM 認証 + Identity Token 方式へ切替する（ADR-008 将来対応）。

## デプロイ後の確認

```bash
URL=$(gcloud run services describe wiseman-ocr-proxy --region asia-northeast1 --format='value(status.url)')

# ヘルスチェック
curl -s "${URL}/healthz"
# => {"status":"ok"}

# API Key 未指定で 401 を返すこと
curl -s -o /dev/null -w "%{http_code}\n" \
    -X POST "${URL}/v1/ocr/extract-name" \
    -H "Content-Type: application/json" \
    -d '{"image_base64":"iVBORw0KGgo="}'
# => 401
```

## ロールバック

```bash
# 直近のリビジョン一覧
gcloud run revisions list --service=wiseman-ocr-proxy --region=asia-northeast1

# トラフィックを過去リビジョンに戻す
gcloud run services update-traffic wiseman-ocr-proxy \
    --region=asia-northeast1 \
    --to-revisions=<REVISION_NAME>=100
```

## 監視

- **Cloud Logging**: `resource.type="cloud_run_revision" AND resource.labels.service_name="wiseman-ocr-proxy"`
- **コストアラート**: Cloud Monitoring で Vertex AI の日次コストが閾値（例: $1）超過時に通知
- **レート制限観測**: 429 レスポンスの頻度をログから集計。恒常的に発生するようなら `RATE_LIMIT` 環境変数で緩和

## キーローテーション

1. 新キーを Secret Manager に追加（既存バージョンは残す）
   ```bash
   echo -n "new-key-1,new-key-2" | gcloud secrets versions add wiseman-ocr-api-keys --data-file=-
   ```
2. Cloud Run を再デプロイ（`--set-secrets` で最新バージョンが取り込まれる）
3. クライアントを新キーで更新
4. 旧キーのみを含むバージョンを disable する（最低 30 日グレース）
