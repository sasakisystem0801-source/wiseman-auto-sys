# ADR-008: OCRバックエンドの選定 - Cloud Runプロキシ経由でVertex AI Gemini 2.5 Flashを利用

## ステータス
**Accepted (2026-04-20)**

## コンテキスト

利用実績PDF（1利用者=1ページ）から利用者名を抽出し、利用者ごとに別PDFを結合する機能を追加する（PRD: PDF分割・条件付き再結合）。利用者名は固定矩形内に印字されているため、OCRで抽出する必要がある。

クライアントは1施設・1 PCに配布するWindowsデスクトップアプリ（PyInstallerパッケージ、ADR-002）。以下の制約がある:

- **エンドユーザーに認証を要求しない**（運用者は介護職員、IT知識を前提にしない）
- **クライアントにGCP認証情報を持たせたくない**（PyInstallerバイナリは解析でSAキー抽出可能 → 無制限Vertex AIアクセス漏洩リスク）
- **APPI準拠**（ADR-003: asia-northeast1使用、個人情報を海外リージョン経由させない）
- **コスト制御が必要**（Gemini API従量課金、暴走防止）

## 決定

### アーキテクチャ: Cloud Runプロキシ方式

```
Windows Desktop App
  ↓ HTTPS (API Key ヘッダ認証)
Cloud Run (asia-northeast1)
  ↓ Service Account
Vertex AI Gemini 2.5 Flash (asia-northeast1, GA)
```

### 採用技術

| コンポーネント | 選定 | 理由 |
|--------------|------|------|
| **OCRモデル** | Vertex AI Gemini 2.5 Flash (GA) | Multimodal対応、asia-northeast1でGA、固定矩形画像の利用者名抽出に十分な精度、日本語対応 |
| **プロキシランタイム** | Cloud Run (asia-northeast1) | ADR-003更新: 今回のPhaseで採用解禁。コールドスタート許容、min-instances=0でコスト$0ベース |
| **認証（クライアント→プロキシ）** | API Key（ヘッダ `X-API-Key`） | エンドユーザー認証不要の要件を満たす最小実装 |
| **認証（プロキシ→Vertex AI）** | Cloud Run Service Account（`roles/aiplatform.user`） | クライアントにGCP認証を持たせない |
| **API実装** | FastAPI + `google-genai` SDK | 型安全、OpenAPIスキーマ自動生成、最小構成 |
| **レート制限** | Cloud Runのconcurrency + FastAPIミドルウェア（1キーあたりN req/min） | コスト暴走防止の一次防衛 |
| **監視** | Cloud Logging + Cloud Monitoring アラート（日次コスト閾値） | 二次防衛、異常検知 |

### API仕様（初版）

```
POST /v1/ocr/extract-name
Headers:
  X-API-Key: <client-key>
  Content-Type: application/json

Body:
  {
    "image_base64": "...",           # PDFから切出した矩形画像（PNG/JPEG base64）
    "prompt_version": "v1"           # プロンプトバージョニング
  }

Response 200:
  {
    "name": "田中太郎",
    "confidence": "high" | "medium" | "low",
    "raw_text": "氏名: 田中太郎"
  }

Response 401: API Keyなし/無効
Response 429: レート制限超過
Response 503: Vertex AI側のエラー（クライアントはリトライ）
```

### API Key管理

- **生成**: Secret Manager（ADR-003で既に採用）に保管
- **配布**: インストール時に運用者が1回だけ設定ファイル（`config/default.toml`の`ocr_backend.api_key`）に記入
- **ローテーション**: 年1回以上、または漏洩検知時に即時。旧キーは30日グレース期間後に無効化
- **クライアント埋込み禁止**: PyInstallerバイナリには含めない（解析抽出を防ぐ）

## 代替案と却下理由

| 案 | 却下理由 |
|----|---------|
| **SAキーファイルをアプリに同梱** | PyInstallerバイナリから抽出可能。無制限Vertex AIアクセス漏洩リスク。ADR-002と両立不能 |
| **ユーザーOAuth（`gcloud auth application-default login`）** | 初回ログインが必要。介護職員にGoogleアカウント認証フローを要求できない |
| **WIF（Workload Identity Federation）** | 施設に外部IdPが存在しない。IdP構築コスト > Cloud Runプロキシ構築コスト |
| **Tesseract（ローカルOCR）** | 精度が低く、固定矩形の利用者名でも誤認識リスク。モデル更新の運用負担もある |
| **Windows OCR API** | Python連携（`winrt`）の保守性が低い。Windows OSバージョン依存 |
| **Cloud Functions 2nd gen（ADR-003採用サービス）** | メモリ上限とタイムアウトがCloud Runより制約あり。画像処理には向かない |
| **API Gateway前段** | 初期スコープでは過剰。Cloud Runのrate limitで十分。将来複数クライアント化時に導入検討 |

## 影響

- **ADR-003更新**: 「Cloud Run不採用」を「Phase: PDF OCR用途でCloud Run採用」に改訂（本ADRで同時更新ではなく、別PRで差分コミット）
- **新規リポジトリディレクトリ**: `backend/ocr_proxy/`（FastAPI + Dockerfile）
- **新規設定セクション**: `config/default.toml`に`[ocr_backend]`追加
- **GCPリソース追加**:
  - Cloud Run service: `wiseman-ocr-proxy`
  - Service Account: `wiseman-ocr-proxy@{project}.iam.gserviceaccount.com`（`roles/aiplatform.user`のみ）
  - Secret: `wiseman-ocr-api-keys`
- **月額コスト想定**: $0〜$5（1施設・月数十回実行想定、Gemini 2.5 Flash入力画像1件<$0.001）

## スコープ外（将来対応）

- WIF移行（複数施設展開時に再検討）
- API Gateway導入（複数クライアント化時）
- OCRプロンプトA/Bテスト基盤
- 利用者名のふりがな抽出（あいうえお順ソート用）

## 関連

- ADR-002: PyInstallerパッケージング
- ADR-003: GCPサービスの選定（Cloud Run方針を部分的に更新）
- 本機能のPRD: TBD（`docs/prd.md`更新時にリンク）
