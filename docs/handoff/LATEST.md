# Handoff: PDF 分割・条件付き再結合機能の実装（Session 1 終了時点）

**更新日**: 2026-04-20
**ブランチ**: main (clean)
**次セッションで `/catchup` を実行して再開可能**

## 機能概要

複数利用者がまとまった PDF（A）を1利用者=1ページで分割し、利用者ごとに別 PDF（B, C）を指定順で結合、末尾に共通 PDF（D）を追加して1つの PDF を生成する機能。

- **入力**: A（複数利用者PDF、固定矩形OCR）、B/C（利用者別PDF、ファイル名に利用者名）、D（共通PDF）
- **出力**: 全利用者分を連結した1つの PDF
- **環境**: Windows デスクトップアプリ（1施設1PC、ADR-002 の PyInstaller パッケージ）
- **規模**: 1〜20名/回

## アーキテクチャ（ADR-008 で決定）

```
Windows Desktop App
  ↓ HTTPS (X-API-Key)
Cloud Run (asia-northeast1)  ← OCR プロキシ
  ↓ SA (roles/aiplatform.user)
Vertex AI Gemini 2.5 Flash (GA, asia-northeast1)
```

エンドユーザー認証不要。クライアントに GCP 認証情報を持たせない（PyInstaller 解析対策）。

## 実装計画（11タスク中 5件 + 基盤テスト完了）

| # | タスク | 状態 | PR / 備考 |
|---|-------|------|-----------|
| 1 | ADR-008 起草 | ✅ | PR #26 |
| 2 | Cloud Run プロキシ実装 | ✅ | PR #28 |
| 3 | デプロイ手順書 | ✅ | PR #28（`backend/ocr_proxy/deploy.md`） |
| 4 | config.py 拡張 | ✅ | PR #26 |
| 5 | PDF splitter（A を1ページ単位に分割 + 固定矩形切出） | ⏳ | 次セッション候補 |
| 6 | OCR HTTP クライアント（Cloud Run プロキシを叩く） | ⏳ | タスク5後 |
| 7 | PDF merger（利用者単位で [A,B,C] 結合 + D 末尾追加） | ⏳ | タスク5と並列可 |
| 8 | Pipeline + CLI（`scripts/merge_user_pdfs.py`） | ⏳ | タスク5-7後 |
| 9 | Unit tests（モック OCR） | ⏳ | タスク5-8と並走 |
| 10 | Integration test + **実 Cloud Run デプロイ** | ⏳ | AC2 実測、別タスク化可 |
| 11 | README 更新 + sample TOML | ⏳ | 最後 |

## 完了した PR（本セッション）

### PR #26 - Foundation [merged]
- ADR-008（OCR バックエンド選定）
- `src/wiseman_hub/config.py` に `OcrBackendConfig`, `PdfMergeConfig`, `UserNameBBox` 追加
- `load_config()` で `[ocr_backend]` / `[pdf_merge]` TOML セクション対応
- `config/default.toml` にサンプル（コメントアウト）追加
- `src/wiseman_hub/pdf/__init__.py` 雛形
- test: 3件 PASS（`test_load_config_with_ocr_and_pdf_merge_sections` 追加）

### PR #28 - Cloud Run OCR Proxy [merged]
- `backend/ocr_proxy/app/{main,auth,ocr,models,config}.py`
- FastAPI + google-genai SDK + slowapi
- `hmac.compare_digest` による定数時間 API Key 検証
- FastAPI `lifespan` による起動時 fail-fast（API_KEYS / GCP_PROJECT_ID 空なら `RuntimeError`）
- `include_raw_text: bool = False` で APPI 準拠 PII オプトイン
- レビュー指摘対応: 認証を `Depends` 化でレート制限より先に評価
- test: 31件 PASS

## 残課題（次セッション着手時に参照）

### 実装スコープ
1. **タスク5（PDF splitter）から着手** — 以下の依存で PDF 処理を進める
   - `pymupdf` (PyMuPDF) を `pyproject.toml` に追加
   - `src/wiseman_hub/pdf/splitter.py`: A を1ページ単位 + UserNameBBox で画像切出
   - 合わせて `src/wiseman_hub/pdf/ocr_client.py`: Cloud Run プロキシ HTTP クライアント（`ocr_backend.endpoint_url` + `api_key`）

2. **実 Cloud Run デプロイ**（タスク10 の一部）
   - `backend/ocr_proxy/deploy.md` 手順で実施
   - 必要API有効化、SA作成、Secret Manager、Artifact Registry、`gcloud run deploy`
   - AC2（実 Vertex AI で既知 PDF ページから利用者名抽出）の実測
   - デプロイ後: `deploy.md` のエンドポイント URL / API Key をクライアント側の TOML に記入

### 別 Issue として追跡中
- **#27** config dataclass 全体の型設計強化（Literal + `__post_init__` 検証、既存 dataclass 含む）
- **#29** OCR プロキシ Nice-to-have（Dockerfile 非 root / `except Exception` 絞り込み / 429 テスト / 空 project_id テスト / requirements.txt `==` ピン）

### ドキュメント改善（小さな PR 候補）
- **`deploy.md` に Artifact Registry クリーンアップポリシー（最新2件保持）を追記** — グローバル `rules/gcp.md` 準拠。Issue #29 に含めて対応も可
- **ADR-003 に「PDF OCR 用途で Cloud Run 採用」の1行注記追加** — ADR-008 内には記載済みだが、ADR-003 本体にも相互参照を入れると辿りやすい

## Acceptance Criteria 進捗（impl-plan Phase 2.7）

| AC | 内容 | 状態 |
|----|------|------|
| 1 | OCR プロキシ認証（APIキーなしで 401） | ✅ 検証済（test_main.py） |
| 2 | OCR 成功（既知 PDF ページ→利用者名） | 🔶 モック検証のみ、実 Cloud Run で未測定 |
| 3 | A 分割（5人分→5個の単ページ PDF） | ⏳ タスク5 |
| 4 | ファイル名マッチング（欠損時 WARN） | ⏳ タスク7 |
| 5 | 順序設定反映（order=["A","C","B"]） | ⏳ タスク7 |
| 6 | D 末尾連結 | ⏳ タスク7 |
| 7 | 20名入力→1分以内 | ⏳ タスク10 |
| 8 | OCR プロキシダウン時のリトライ3回 | ⏳ タスク6 |

## セッション再開手順

```bash
# 1. 状況再確認
cd /Users/yyyhhh/Projects/wiseman_auto_sys
/catchup
/model   # Opus 4.7 xhigh であること確認

# 2. この handoff を読む
cat docs/handoff/LATEST.md

# 3. 次タスク着手（例: タスク5）
/impl-plan  # は不要（全体計画は本 handoff 記載）
/tdd        # PDF splitter を TDD で実装
```

## 主要ファイル参照

- ADR-008: `docs/adr/008-ocr-backend.md`
- Config 定義: `src/wiseman_hub/config.py:49-82`
- PDF モジュール雛形: `src/wiseman_hub/pdf/__init__.py`
- OCR プロキシ: `backend/ocr_proxy/app/`
- デプロイ手順: `backend/ocr_proxy/deploy.md`
- sample TOML: `config/default.toml:42-75`
