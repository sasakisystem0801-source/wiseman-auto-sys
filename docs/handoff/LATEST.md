# Handoff: "使える Windows デスクトップアプリ" 完成化計画（Session 7 終了時点）

**更新日**: 2026-04-21
**ブランチ**: feature/task-12a-toml-writeback (PR #60, CI 待ち)
**main ブランチ**: PR #60 マージ後に同期

## セッション 7 の成果

### 完了したタスク
- **タスク 10-1**: Cloud Run デプロイ（asia-northeast1、Gemini 2.5 Flash、allow-unauthenticated + X-API-Key、AC-DEPLOY-1 代替検証 PASS）
- **タスク 12A**: `save_config()` 実装（tomlkit、atomic write、create_if_missing=False 既定、InlineTable 対応、_require_table helper）
- **タスク 14B**: デスクトップアイコン生成（Pillow、6 サイズ ICO、`assets/icon.ico`）
- **タスク 10-2 準備**: Windows 実機 E2E 手順書（`docs/handoff/windows-e2e-task10.md`）

### セキュリティ対応（Codex 指摘）
- 初回 API Key 漏洩 → Secret Manager v1 disable + v2 rotation、平文削除
- `_sweep_stale_tmp()` 追加: クラッシュ時 PII 残置防止
- cleanup warning log を型名のみに抑制（PII/tmp path 漏洩防止）
- Windows 手順書を `uv run python` 統一、`gcloud` は運用者端末のみに変更

### Quality Gate 通過
- `/simplify` 3 並列 / `/safe-refactor` / Evaluator 分離 / `/review-pr` 6 Agent / `/codex review`
- 324 tests passed / ruff clean / mypy clean

## 次のセッション着手ポイント

### 優先 1: PR #60 のマージ確認
```bash
gh pr checks 60
gh pr view 60
# すべて green なら:
gh pr merge 60 --squash --delete-branch
git checkout main
git reset --hard origin/main
```

### 優先 2: タスク 13A（ランチャー GUI 骨格）

**新規ファイル**: `src/wiseman_hub/ui/launcher.py`

**設計方針（確定済）**:
- Tkinter/ttk で 3 ボタンのシンプルなランチャー画面
- **3 ボタン構成**:
  1. **「PDF マージ処理を実行」**: `scripts/merge_user_pdfs.py` の `run_phase_a` を subprocess ではなく関数直呼びで実行（進捗ダイアログ、NEEDS_REVIEW セッションは一覧遷移）
  2. **「確認待ちセッション」**: 既存 session から NEEDS_REVIEW を一覧 → 選択 → `ConfirmDialog` → `run_phase_b`
  3. **「設定」**: タスク 12B で実装予定、13A ではプレースホルダ（"未実装" メッセージ）

**既存資産の活用**:
- `src/wiseman_hub/ui/confirm_dialog.py`: タスク 8C PR #A で実装済（ConfirmDialog 本体）
- `src/wiseman_hub/pdf/pipeline.py:254 run_phase_a` / `:444 run_phase_b`: Phase 実行関数
- `src/wiseman_hub/pdf/session.py`: `load_session` / `save_session` / `with_session_lock` / `transition_session`
- `scripts/merge_user_pdfs.py`: CLI 1 本、`--review` / `--merge` 等（参考実装）

**`__main__.py` の変更**:
- 現在: `WisemanHub.run()` を直接呼ぶ（RPA パイプライン）
- 変更後: CLI 引数で `--rpa`（従来 RPA 起動）/ デフォルト（ランチャー GUI）を切替
- `python -m wiseman_hub` → ランチャー GUI が立ち上がる

**Acceptance Criteria（再掲）**:
- AC-L-1: アプリ起動 → 3 ボタン画面表示（検証: 目視 + smoke test）
- AC-L-2: 「処理開始」押下 → `run_phase_a` 実行、進捗表示、完了通知、NEEDS_REVIEW セッションがあれば一覧遷移（検証: Windows 実機）
- AC-L-3: 「確認待ち一覧」押下 → セッション一覧、選択 → ConfirmDialog → 完了時 `run_phase_b` → 出力 PDF 生成（検証: Windows 実機）
- AC-L-4: 設定未完了時に「処理開始」押下 → エラーダイアログ + 設定 GUI へ誘導（検証: 手動）

**TDD 手順**:
1. `tests/unit/ui/test_launcher.py` を Red で作成（AC-L-1〜3 に対応）
2. `ui/launcher.py` 最小実装で Green
3. 3 ボタンそれぞれの click ハンドラを段階的に追加
4. ConfirmDialog と同様、DI 設計（`run_phase_a_fn` / `confirm_dialog_factory` を注入可能に）

**PR 分割**:
- **PR #Z-1 (13A)**: ランチャー骨格 + `__main__.py` 切替（CLI mode / GUI mode）+ 最小 smoke test
- **PR #Z-2 (13B)**: Phase A 統合（ボタン 1 の実装 + 進捗ダイアログ）
- **PR #Z-3 (13C)**: Phase B / 確認 UI 統合（ボタン 2 の実装）

### 優先 3: タスク 12B（設定 GUI）
PR #60 で `save_config()` が完成したので、12B 着手可能。
- `src/wiseman_hub/ui/settings.py` 新規
- パス選択ダイアログ（`filedialog.askdirectory`）
- バリデーション（input_dir/output_dir 存在チェック、TOML セクション不備）
- Save ボタン → `save_config(cfg, path)` → 成功メッセージ

### 優先 4: タスク 15（GitHub Actions + WIF）
**推奨構成**（前セッションで合意済）:
- Workload Identity Pool + Provider（GitHub OIDC 信頼）
- Deploy 用 SA: `roles/run.admin`, `roles/artifactregistry.writer`, `roles/iam.serviceAccountUser`
- `.github/workflows/deploy.yml`: `google-github-actions/auth@v2` でフェデレーション
- SA key 不要、push から自動デプロイ

**別 PR（#Z の後で）**:
- 現在ローカル `gcloud` でのみデプロイ可能。CI 化は重要だが MVP 動作確認優先

## 積み残し Issue

### 新規追加（Session 7）
- **#58**: `/healthz` が Cloud Run GFE intercept（実害なし、P2）
- **#59**: PyInstaller spec で icon 埋め込み（タスク 14A スコープ、P2）

### 既存（MVP スコープ外、維持）
- **#51** Windows msvcrt / 跨プロセスロック / 0 ページ PDF (P1 だが単一 PC では発生せず)
- **#49** resume 時 candidates 妥当性検証 (P2)
- **#50** `--list-sessions` で corrupted 件数表示 (P2)
- **#38** atomic_io ユーティリティ抽出 (P2) — config.py / session.py / merger.py で重複、save_config も含めて統合検討
- **#44 #45 #40 #39 #27 #29 #17 #16 #14 #11 #6**: 各種改善系

## 全体進捗（impl-plan 対応）

| タスク | 状態 | PR |
|--------|------|-----|
| 10-1 Cloud Run デプロイ + 疎通確認 | ✅ | PR #60 |
| 10-2 Windows 実機 E2E | ⏳ 本田さん実施待ち | - |
| 12A TOML 書き戻し機能 | ✅ | PR #60 |
| 12B 設定 GUI | ⏳ 次セッション以降 | - |
| 12C 初回起動ウィザード | ⏳ 12B 後 | - |
| 13A ランチャー GUI 骨格 | ⏳ **次セッション最優先** | - |
| 13B ランチャー ↔ Phase A 統合 | ⏳ | - |
| 13C ランチャー ↔ 確認 UI 統合 | ⏳ | - |
| 14A PyInstaller spec | ⏳ GUI 完成後 | - |
| 14B アイコン生成 | ✅ | PR #60 |
| 14C ショートカット配布手順 | ⏳ 14A 後 | - |
| 14D ADR-011 執筆 | ⏳ 14A 完了時 | - |
| 15 GitHub Actions + WIF | ⏳ GUI 安定後 | - |
| 11 README + sample TOML | ⏳ 最後 | - |

## セッション再開手順

```bash
cd /Users/yyyhhh/Projects/wiseman_auto_sys
# catchup 実行で現状把握
# gh pr view 60 で CI 確認 → マージ
# git checkout main && git reset --hard origin/main
# 13A 着手: mkdir -p src/wiseman_hub/ui と新規 launcher.py
```

## 主要ファイル参照

### 今セッションで追加・変更
- `src/wiseman_hub/config.py`: `save_config()` + helpers（+130 行）
- `tests/unit/test_config.py`: TestSaveConfig 20 テスト
- `scripts/generate_icon.py`: アイコン生成スクリプト
- `assets/icon.ico`: 6 サイズ ICO
- `docs/handoff/windows-e2e-task10.md`: Windows 実機 E2E 手順書

### 13A で参照する既存ファイル
- `src/wiseman_hub/__main__.py`: 9 行のエントリポイント、ランチャー起動に変更
- `src/wiseman_hub/app.py`: `WisemanHub` (RPA オーケストレータ)、13A では呼び出し側
- `src/wiseman_hub/ui/confirm_dialog.py`: タスク 8C PR #A で完成、13C で再利用
- `src/wiseman_hub/pdf/pipeline.py`: `run_phase_a` / `run_phase_b` 関数
- `scripts/merge_user_pdfs.py`: CLI、13A-13C の参考実装

## Session 7 の学び

### Codex セカンドオピニオンの一貫した価値
Session 3/4/5/6 に続き Session 7 も、Codex が Claude 6 Agent + Evaluator 全員が見落とした問題を検出:
- **CRITICAL/HIGH**: API Key 平文コミット（comment-analyzer は検出、Codex は別経路でも再検出）
- **HIGH**: クラッシュ時の tmp 平文残置で PII/API Key が `{config}.{random}.tmp` に残る
- **HIGH**: cleanup warning log に tmp path + PII が漏れる
- **HIGH**: Windows 手順書の `python` 直接呼び出しで venv 迂回
- **HIGH**: `gcloud secrets` を現場端末で実行する前提の運用破綻

Codex は「データフロー全体 + ログ集約 + 運用経路」を俯瞰するレビューが一貫して強い。

### 本番デプロイ時の permission classifier
- Auto mode でも本番 GCP 操作は都度明示承認が必要（classifier で block される）
- 最初の `/permissions add` で CLI 権限は通せるが、classifier 層は「操作単位」で追加承認要求
- 今回は「wiseman-hub-prod へ Cloud Build + Cloud Run デプロイを承認します」の明示文で通過

### MVP 配布形態の確定
- ダブルクリック起動の .exe が最終形（タスク 14A）
- PyInstaller + icon 埋め込み + デスクトップショートカット配布
- Workload Identity Federation は「層 3: GitHub Actions からのデプロイ」に適用予定（層 2: Windows クライアント → Cloud Run は WIF 不適用、X-API-Key 継続）
