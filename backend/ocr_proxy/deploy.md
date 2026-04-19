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
    --allow-unauthenticated \
    --min-instances 0 \
    --max-instances 2 \
    --concurrency 10 \
    --memory 512Mi \
    --cpu 1 \
    --timeout 60 \
    --set-env-vars "GCP_PROJECT_ID=${PROJECT_ID},GCP_LOCATION=${REGION},GEMINI_MODEL=gemini-2.5-flash,RATE_LIMIT=60/minute" \
    --set-secrets "API_KEYS=wiseman-ocr-api-keys:latest"
```

### 認証方針: `--allow-unauthenticated`

1施設1PC の初期運用のため、Cloud Run の IAM 認証は使わず、アプリケーション層の API Key 認証のみで運用する。
クライアント（Windows デスクトップアプリ）は `X-API-Key` ヘッダのみで呼び出せば良く、Identity Token の取得は不要。

将来複数施設展開する場合は、`--no-allow-unauthenticated` に変更して IAM 認証（`roles/run.invoker`）を追加する。
そのタイミングで ADR-008 を改訂し、クライアント側に Identity Token 取得フローを実装する。

### レート制限の制約（重要）

`RATE_LIMIT=60/minute` は slowapi の **in-memory 実装**。
`--max-instances 2` でスケールした場合、実効制限はインスタンス数倍（例: 120/minute）となる。
1施設1PC の想定トラフィックでは問題にならないが、本格的なコスト暴走防止には以下のいずれかが必要:

- Redis 等の共有ストレージで slowapi を backend 化する
- API Gateway / Cloud Armor の前段 WAF でレート制限する
- `--max-instances 1` に絞る（ただしスケール不可）

Cloud Monitoring で日次コストアラートを設定し、二次防衛とする。

## デプロイ後の確認

```bash
URL=$(gcloud run services describe wiseman-ocr-proxy --region asia-northeast1 --format='value(status.url)')

# ヘルスチェック（--allow-unauthenticated のため認証ヘッダ不要）
curl -s "${URL}/healthz"
# => {"status":"ok"}

# API Key 未指定で 401 を返すこと（IAM 認証ではなくアプリ層の認証）
curl -s -o /dev/null -w "%{http_code}\n" \
    -X POST "${URL}/v1/ocr/extract-name" \
    -H "Content-Type: application/json" \
    -d '{"image_base64":"iVBORw0KGgo="}'
# => 401

# 正しい API Key で 200 を返すこと（画像は 1x1 透明 PNG）
PNG_B64=$(python -c "import base64; print(base64.b64encode(bytes.fromhex('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000a49444154789c6300010000000500010d0a2db40000000049454e44ae426082')).decode())")
curl -s \
    -X POST "${URL}/v1/ocr/extract-name" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: <API_KEY>" \
    -d "{\"image_base64\":\"${PNG_B64}\"}"
# => {"name":null,"confidence":"low","raw_text":""}  # 1x1 画像では文字が読めないので low が正常
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
