# ハンドオフ履歴アーカイブ: 2026-04

2026-04 の Session 12-14 のハンドオフ内容をアーカイブ。詳細な変更履歴・完了タスク・解決済みの技術的詳細を保持。
現行のハンドオフは `docs/handoff/LATEST.md` を参照。

---

## セッション 14 の成果

### マージ済み（1 PR）
- **PR #94**: 10-2 トラブル切り分けフロー追加 + Cloud Run /health 本番反映
  - 1 file, +43/-1 lines（`docs/handoff/windows-e2e-task10.md` のみ）
  - 症状×原因×対応マトリクス 5 節追加（Phase A / Phase B UI / Phase B 結合 / exe 起動 / SmartScreen）
  - `/healthz` 既知制約記述を「PR #89 で解消済」に更新
  - 軽量 docs 変更のため `/review-pr`（6 エージェント並列）は過剰としてセルフレビューで対応
  - CI 全 SUCCESS（test-unit 3.11 1m4s / 3.12 59s / test-integration 2m22s）

### 本セッションで発見・解消した本番ブロッカー
- **症状**: Cloud Run `/health` が HTTP 404 を返していた
- **原因**: PR #89（Issue #58、/healthz → /health リネーム）は main に merged 済だったが、**Cloud Run 本番リビジョンは旧コードのまま**（openapi.json の paths に `/healthz` が残存、`/health` は存在しない状態）
- **検出経路**: 10-2 実機テスト前の事前準備として macOS から `curl /health` で疎通確認 → HTTP 404 で異常検出
- **対応**: Cloud Run 再デプロイ実施
  - 新リビジョン: `wiseman-ocr-proxy-00003-98m`
  - 反映日時: 2026-04-22 13:31 JST
  - Cloud Build 52 秒 + Cloud Run deploy 約 40 秒
- **検証**:
  - 既存 URL `/health` → HTTP 200 `{"status":"ok"}` ✅
  - 既存 URL `/healthz` → HTTP 404 ✅（ルート削除済、期待通り）
  - openapi.json paths: `['/health', '/v1/ocr/extract-name']` ✅

### 事前検証（10-2 実機テスト前に全 PASS）
- **macOS smoke build**: `uv run pyinstaller --clean wiseman_hub.spec` → 67MB binary 生成、hidden imports 致命警告なし
- **frozen path 回帰テスト**: `tests/unit/test_main_entrypoint.py` に 3 件既存（Codex HIGH #14A 対応分）
- **lint / typecheck / test**: ruff all checks passed / mypy no issues (28 files) / pytest 421 passed, 62 skipped

### 総変更量
- 1 file changed, +43 / -1 lines（docs のみ）
- テスト件数: 421 passed 維持
- **本番 Cloud Run リビジョン更新**: 00002-* → 00003-98m

### Session 14 の学び（次セッションに引継ぐ運用ギャップ）
- **PR merged ≠ 本番反映**: Cloud Run は手動 `gcloud run deploy` 運用のため、PR マージ後にデプロイ実行者が手動トリガーしないと本番は旧コードのまま残る
- **対策候補**:
  1. タスク 15（GitHub Actions Windows runner + WIF）の範囲で、`main` への push 時に `backend/ocr_proxy/**` 変更があれば自動 Cloud Build + Cloud Run deploy を追加
  2. `backend/ocr_proxy/deploy.md` 冒頭に「**main merge 後は速やかに再デプロイ必須**」チェックリストを追記
  3. 10-2 実施前の受入基準に `curl /health` 疎通確認を含める

---

## セッション 13 の成果

### マージ済み（5 PR 連続）
- **PR #88**: Issue #51 #3-#6 - 残タスク 4 件のテストカバレッジ追加
  - 3 files, +209 lines（tests/unit/pdf/ 配下のみ、本体コード変更なし）
  - #3: `test_ocr_server_error_saves_interrupted_state`（非 KI Exception 経路で INTERRUPTED 保存）
  - #4: `test_zero_page_pdf_raises_corrupted_error`（fitz 0-page は save できないため monkeypatch で page_count=0 注入）
  - #5: `test_save_failure_during_interrupt_does_not_mask_original_exception`（INTERRUPTED 保存失敗で元例外が masked されない契約）
  - #6: `test_gc_coexists_with_interrupted_sessions`（gc_old_sessions が COMPLETED のみ削除、INTERRUPTED/NEEDS_REVIEW はロック不要で保全）
  - /review-pr 3 エージェント並列: Critical 0 / Important 3 → 全対応
  - **Issue #51 CLOSED**（#1-#6 全完了）

- **PR #89**: Issue #58 - /healthz を /health にリネーム（Cloud Run GFE 404 回避）
  - 4 files, +22/-7
  - Cloud Run GFE が `/healthz` を intercept して 404 HTML を返す問題の修正
  - **Issue #58 CLOSED**

- **PR #90**: Issue #71 - install_tk_exception_guard 契約テスト追加
  - 1 file, +62
  - exc_type=None で AttributeError 伝播、SystemExit / KeyboardInterrupt 伝播の defense-in-depth
  - **Issue #71 CLOSED**

- **PR #91**: Issue #50 - --list-sessions 集計行（healthy/corrupted 件数表示）
  - 2 files, +88
  - **Issue #50 CLOSED**

- **PR #92**: Issue #64 - --config 存在しないパス警告ログ
  - 2 files, +112
  - **Issue #64 CLOSED**

### 総変更量
- 12 files changed, +493 lines
- **5 Issue CLOSED**: #51, #58, #71, #50, #64
- 全 CI SUCCESS、全レビュー Critical 0
- 前セッション 400 passed → **421 passed**（+13 テスト）

---

## セッション 12 の成果

### マージ済み（3 PR 連続）
- **PR #84**: Issue #76 - merger 全 PdfMergeError message PII 除外
  - 2 files, +221/-18
  - 8 箇所の `PdfMergeError` 生成箇所を型名ベースに統一、`source_label` 呼出側で kind (A/B/C/D) のみに制限
  - 新規 PII 非漏洩回帰テスト +10 件（TestMergerPiiDefense）

- **PR #85**: タスク 11 - README 運用者セクション + default.toml.sample + §7.2 ログ取得手順
  - 3 files, +218/-9
  - 2 エージェント並列レビュー: Critical 2 / Important 3 / Suggestion 3 → **8/8 修正済**

- **PR #86**: Issue #51 #1/#2 - Windows msvcrt mock + 跨プロセスロックテスト
  - 1 file, +282
  - TestLockWindowsMsvcrt (5 件): `sys.modules` 経由の fake msvcrt 注入
  - TestCrossProcessLock (3 件): multiprocessing.spawn で親子プロセス間の lock 競合検証

### 総変更量
- 6 files changed, +721 / -27 lines
- 前セッション 400 passed → **408 passed**（+8 テスト）

### Session 12 での設計判断
- **Issue #76 PII 除外拡張**: `source_label` を呼出側で kind (A/B/C/D) のみに制限、関数シグネチャ非破壊で user_name 埋込を呼出規約レベルで排除
- **タスク 11 docs 整備**: `config/default.toml.sample` 新規作成、README 先頭に運用者セクション挿入
- **Issue #51 scope 絞込**: P1 #1 (Windows msvcrt) + #2 (跨プロセスロック) のみに絞り、#3-#6 は follow-up

---

## セッション 11 の成果（サマリー）

- **PR #82**: タスク 14C（ショートカット配布手順、ADR-011 具体化）
  - 3 files, +449/-11
  - Claude 3 並列レビュー + Codex セカンドオピニオンで HIGH 5 件 + MEDIUM 8 件修正
  - 主な指摘:
    - COM リソースリーク（`try/finally`）
    - OneDrive Desktop リダイレクト対応
    - WSH 無効 / ConstrainedLanguage fallback
    - `%USERPROFILE%\wiseman-hub\` を MVP 既定化（C:\ 直下は標準ユーザー書込不可）
    - FilePublisher allowlist は未署名 exe に不正確 → Hash / FilePath ルールのみ
