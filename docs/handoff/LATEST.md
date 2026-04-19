# Handoff: PDF 分割・条件付き再結合機能の実装（Session 2 終了時点）

**更新日**: 2026-04-20
**ブランチ**: main (clean → このハンドオフは `docs/handoff-session2` で作業中)
**次セッションで `/catchup` を実行して再開可能**

## 機能概要

複数利用者がまとまった PDF（A）を1利用者=1ページで分割し、利用者ごとに別 PDF（B, C）を指定順で結合、末尾に共通 PDF（D）を追加して1つの PDF を生成する機能。

- **入力**: A（複数利用者PDF、固定矩形OCR）、B/C（利用者別PDF、ファイル名に利用者名）、D（共通PDF）
- **出力**: 全利用者分を連結した1つの PDF
- **環境**: Windows デスクトップアプリ（1施設1PC、ADR-002 の PyInstaller パッケージ）
- **規模**: 1〜20名/回

## アーキテクチャ（ADR-008）

```
Windows Desktop App
  ↓ HTTPS (X-API-Key)
Cloud Run (asia-northeast1)  ← OCR プロキシ
  ↓ SA (roles/aiplatform.user)
Vertex AI Gemini 2.5 Flash (GA, asia-northeast1)
```

## 実装計画（11タスク中 7件完了）

| # | タスク | 状態 | PR / 備考 |
|---|-------|------|-----------|
| 1 | ADR-008 起草 | ✅ | PR #26 |
| 2 | Cloud Run プロキシ実装 | ✅ | PR #28 |
| 3 | デプロイ手順書 | ✅ | PR #28（`backend/ocr_proxy/deploy.md`） |
| 4 | config.py 拡張 | ✅ | PR #26 |
| 5 | **PDF splitter** | ✅ | PR #31 |
| 6 | **OCR HTTP クライアント** | ✅ | PR #32 |
| 7 | **PDF merger** | ✅ | PR #33 |
| 8 | Pipeline + CLI（`scripts/merge_user_pdfs.py`） | ⏳ **次セッション** |
| 9 | Unit tests 追加分（モック OCR で E2E 相当） | ⏳ タスク8に含める |
| 10 | Integration test + **実 Cloud Run デプロイ** | ⏳ AC2/AC7 実測 |
| 11 | README 更新 + sample TOML | ⏳ 最後 |

## Session 2 で完了した PR

### PR #31 - PDF splitter [merged, commit 37a4f48]
- `src/wiseman_hub/pdf/splitter.py`: `split_pdf_with_bbox()` + `SplitPage`
- `PdfSplitError` / `PdfCorruptedError` / `PdfEncryptedError` 例外階層
- 破損/空/非PDF/暗号化を probe してエラー翻訳（fitz 内部例外を漏らさない）
- per-page bbox 検証（heterogeneous PDF のデータ整合性問題を防止）
- `pymupdf>=1.24.0` 依存追加
- test 17件 PASS
- レビュー反映: silent-failure-hunter の Critical 4件 + Important 3件

### PR #32 - OCR HTTP client [merged, commit f053c8e]
- `src/wiseman_hub/pdf/ocr_client.py`: Cloud Run プロキシを叩く HTTP クライアント
- PNG bytes → base64 → POST `/v1/ocr/extract-name` → `ExtractNameResult`
- リトライ: `httpx.TransportError` / 429 / 5xx を指数バックオフで `max_retries` 回
- 401 は即失敗（再試行不可）、非遷移エラー（`InvalidURL` 等）は伝播
- `OcrClientError` / `OcrAuthError` / `OcrServerError` / `OcrResponseError`
- PII 保護: `include_raw_text=False` デフォルト、raw_text 型厳格化
- close() 冪等、closed 後の呼出は `OcrClientError`
- `httpx>=0.27.0` 依存追加
- test 26件 PASS
- レビュー反映: silent-failure-hunter の Critical 3件 + Important 3件

### PR #33 - PDF merger [merged, commit adb4f87]
- `src/wiseman_hub/pdf/merger.py`: `merge_user_pdfs()` + `UserPageSource` + `MergeReport`
- concat_order 順（["A","B","C"] 等）で利用者毎に結合、末尾に D を1回追加
- B/C 欠損: `logger.warning` + `missing_sources` 記録（AC4）
- D 欠損（設定あり）: `FileNotFoundError`（明示エラー）
- save アトミック化: `tempfile.mkstemp` + `os.replace`（ディスクフル時に既存 output を破壊しない）
- user_name パストラバーサル検証（`/\..\x00` 拒否）
- `_open_pdf_file_or_raise` で破損/暗号化/非PDF を probe（splitter と一貫）
- `MergeReport.has_missing_sources` プロパティ
- `PdfMergeError` 例外階層
- test 22件 PASS
- レビュー反映: silent-failure-hunter の Critical 3件 + Important 4件、code-reviewer の Important 2件

## 残課題（次セッション着手時に参照）

### タスク8（最優先）: Pipeline + CLI

**ゴール**: splitter → ocr_client → merger を接続する統合処理 + CLI エントリ

```python
# 期待する構造
src/wiseman_hub/pdf/pipeline.py
  run_pdf_pipeline(config: AppConfig) -> MergeReport
    1. splitter で A を分割（SplitPage のリスト）
    2. 各 SplitPage の bbox_image_png を OCR にかけて user_name を抽出
    3. UserPageSource のリストを構築
    4. merger で結合

scripts/merge_user_pdfs.py
  argparse + config ロード + run_pdf_pipeline 呼出
```

**設計ポイント（次セッションで検討）**:
- OCR confidence が "low" のケースの扱い（skip?  WARN?  fail?）
- 重複 user_name（OCR が同じ名前を返す）の扱い
- OCR 失敗時のリトライ済み → それでも失敗したらそのページを skip？ or fail 全体？
- progress bar / 進捗表示（20名処理で数十秒かかる想定）

**前提依存**: タスク5-7 完了済み、config 拡張済み（PR #26）

### タスク10: 実 Cloud Run デプロイ + AC2/AC7 実測

- `backend/ocr_proxy/deploy.md` 手順で GCP `wiseman-hub-prod` にデプロイ
- named config (`wiseman-auto-sys`) が有効、gcloud そのまま実行可
- AC2: 既知 PDF ページから利用者名抽出（実 Vertex AI で実測）
- AC7: 20名入力で1分以内
- デプロイ後: エンドポイント URL / API Key を `config/default.toml` の `[ocr_backend]` に記入

### 別 Issue として追跡中

- **#27** config dataclass 全体の型設計強化（Literal + `__post_init__` 検証）
- **#29** OCR プロキシ Nice-to-have（Dockerfile 非 root / `except Exception` 絞込 等）
- **#17** smoke_real.py を pytest に統合
- **#16** test_new_registration_flow: Pane/Text 経路カバー
- **#14** PywinautoEngine: export_csv の6失敗モード区別化
- **#11** PywinautoEngine: コードレビュー残件 (MEDIUM 5件)
- **#6** PoC E2Eテスト

### ドキュメント改善（小PR候補）

- `deploy.md` に Artifact Registry クリーンアップポリシー追記（rules/gcp.md 準拠、Issue #29 と兼ねても可）
- ADR-003 に「PDF OCR 用途で Cloud Run 採用」1行注記（ADR-008 との相互参照）

## Acceptance Criteria 進捗（impl-plan Phase 2.7）

| AC | 内容 | 状態 | 検証箇所 |
|----|------|------|---------|
| 1 | OCR プロキシ認証（APIキーなしで 401） | ✅ 検証済 | `backend/ocr_proxy/tests/test_main.py` |
| 2 | OCR 成功（既知 PDF ページ→利用者名） | 🔶 モックのみ、実 Cloud Run で未測定 | タスク10 |
| 3 | A 分割（5人分→5個の単ページ PDF） | ✅ 検証済 | `tests/unit/pdf/test_splitter.py::test_split_multi_page_pdf_returns_one_per_page` |
| 4 | ファイル名マッチング（欠損時 WARN） | ✅ 検証済 | `test_merger.py::test_missing_b_file_warns_and_continues` 他 |
| 5 | 順序設定反映（order=["A","C","B"]） | ✅ 検証済 | `test_merger.py::test_concat_order_respected` |
| 6 | D 末尾連結 | ✅ 検証済 | `test_merger.py::test_merge_two_users_abc_order_with_d` |
| 7 | 20名入力→1分以内 | ⏳ | タスク10 |
| 8 | OCR プロキシダウン時のリトライ3回 | ✅ 検証済 | `test_ocr_client.py::test_retries_exhausted_on_persistent_5xx_raises_server_error` 他 |

## セッション再開手順

```bash
# 1. 状況再確認
cd /Users/yyyhhh/Projects/wiseman_auto_sys
/catchup
/model   # Opus 4.7 xhigh であること確認

# 2. この handoff を読む
cat docs/handoff/LATEST.md

# 3. 次タスク着手（タスク8: Pipeline + CLI）
/impl-plan  # 必須（OCR confidence 低い時の扱い等、設計判断あり）
# または /tdd で直接実装
```

## 主要ファイル参照

- ADR-008: `docs/adr/008-ocr-backend.md`
- Config 定義: `src/wiseman_hub/config.py:49-95`
- PDF モジュール:
  - `src/wiseman_hub/pdf/splitter.py`
  - `src/wiseman_hub/pdf/ocr_client.py`
  - `src/wiseman_hub/pdf/merger.py`
- テスト: `tests/unit/pdf/test_{splitter,ocr_client,merger}.py`（56件）
- OCR プロキシ: `backend/ocr_proxy/app/`
- デプロイ手順: `backend/ocr_proxy/deploy.md`
- sample TOML: `config/default.toml:42-75`

## Session 2 で学んだ知見（将来の参考）

### silent-failure-hunter のレビュー指摘パターン
3 PRs すべてで同系統の指摘が出た:
- broad `except Exception` → 具体型に絞込、`MemoryError` は伝播
- fitz / httpx 内部例外の翻訳（呼び出し元が安定した契約で catch できるように）
- 失敗経路の `logger.error` 不在
- silent な型強制（`raw_text` を `""` に無言変換等）
- リソース管理の冪等性（`close()` を複数回呼んでも安全）

次の PR（タスク8 pipeline）でも同じ観点が出るはず。**最初から** この方針で書けば review サイクル短縮可能。

### fitz の Document/Pixmap リソース管理
- `doc.close()` は `finally` で必ず呼ぶ
- `Pixmap` は `__del__` で解放（明示 close なし、参照スコープで管理）
- `tobytes()` は内部で `write()` → `save()` を呼ぶ（テスト monkeypatch 時に注意）

### httpx の retryable 例外
- `httpx.TransportError` が正しい retry 基底（`ConnectError`, `ReadError`, `Timeout` 系）
- `httpx.HTTPError` は広すぎ（`InvalidURL`, `DecodingError`, `StreamError` 等 retryable でないものも含む）
