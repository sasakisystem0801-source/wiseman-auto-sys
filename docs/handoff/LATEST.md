# Handoff: PDF 分割・条件付き再結合機能の実装（Session 4 終了時点）

**更新日**: 2026-04-20
**ブランチ**: main (clean, origin と同期済み)
**次セッションで `/catchup` を実行して再開可能**

## 機能概要

複数利用者がまとまった PDF (A) を1利用者=1ページで分割し、OCR で利用者名抽出、利用者ごとに別 PDF (B, C) を指定順で結合、末尾に共通 PDF (D) を追加して1つの PDF を生成する機能。誤記/OCR 揺れで類似マッチした場合、Tkinter UI で人間が承認してから結合する（自動結合を回避）。

- **入力**: A（複数利用者PDF、固定矩形OCR）、B/C（利用者別PDF、ファイル名に利用者名）、D（共通PDF）
- **出力**: 全利用者分を連結した1つの PDF
- **環境**: Windows デスクトップアプリ（1施設1PC、ADR-002 の PyInstaller パッケージ）
- **規模**: 1〜20名/回

## アーキテクチャ

```
Windows Desktop App
  ↓ HTTPS (X-API-Key)
Cloud Run (asia-northeast1)  ← OCR プロキシ
  ↓ SA (roles/aiplatform.user)
Vertex AI Gemini 2.5 Flash (GA, asia-northeast1)

確認 UI: Tkinter（stdlib、PyInstaller 依存追加なし、ADR-009）
セッション管理: JSON + atomic write（schema_version v1、ADR-010）
セッションロック: Windows msvcrt / POSIX fcntl（ADR-010, Issue #46）
状態遷移: transition_session API + _VALID_TRANSITIONS（Issue #47）
source A fingerprint: SHA-256 + size + mtime_ns（利用者取り違え防止）
```

## 実装計画（全 13 タスク）

| # | タスク | 状態 | PR / Issue |
|---|-------|------|-----------|
| 1 | ADR-008 起草 | ✅ | PR #26 |
| 2 | Cloud Run プロキシ実装 | ✅ | PR #28 |
| 3 | デプロイ手順書 | ✅ | PR #28（`backend/ocr_proxy/deploy.md`） |
| 4 | config.py 拡張 | ✅ | PR #26 |
| 5 | PDF splitter | ✅ | PR #31 |
| 6 | OCR HTTP クライアント | ✅ | PR #32 |
| 7 | PDF merger | ✅ | PR #33 |
| 8A | ADR-009/010 + matcher + session 基盤 | ✅ | PR #43 |
| 8B | **Pipeline Phase A + CLI 骨格** | ✅ | **PR #52** |
| 8C | 確認UI (Tkinter) + Phase B + Integration tests | ⏳ **次セッション** | Issue #37 |
| 10 | 実 Cloud Run デプロイ + AC2/AC7 実測 | ⏳ Session 5 予定 | - |
| 11 | README + sample TOML | ⏳ 最後 | - |

## Session 4 で完了した PR

### PR #52 - タスク 8B [merged, commit 4e2d54d]

**実装内容**:
- `src/wiseman_hub/pdf/pipeline.py`（新規、343 行）: `run_phase_a()` オーケストレータ
- `scripts/merge_user_pdfs.py`（新規、394 行）: argparse CLI（`--list-sessions` / `--resume` / `--discard`）
- `src/wiseman_hub/pdf/session.py`（拡張、+301 行）:
  - `transition_session(session, next)` + `_VALID_TRANSITIONS` テーブル（ADR-010 符号化）
  - `with_session_lock(sessions_dir, sid)` context manager（Windows msvcrt / POSIX fcntl non-blocking）
  - `ensure_private_dir(path)` POSIX 0o700 強制 helper（既存 dir も検査・補正）
  - `validate_session_id` / `remove_session_artifacts` 公開化
  - `total_pages_a` / `source_a_fingerprint` フィールド追加
  - session_id entropy 16bit → 32bit に拡張
- `docs/adr/010-human-confirmation-state.md` 補記（API と schema v1 互換フィールド）

**設計判断**:
- OCR confidence=low は matcher 結果を上書きして NEEDS_CONFIRMATION に昇格（医療誤字事故防止）
- OCR name=None は matcher を呼ばず NO_MATCH（matcher の空文字 ValueError 回避）
- 重複 user_name はページ順保持（dedupe しない）
- Resume 時は split を再実行し未処理 page_index のみ OCR（split は高速）
- source A の SHA-256 + size + mtime_ns を保存し resume 時に検証（利用者取り違え防止）
- CLI 例外経路は KeyboardInterrupt(130) / NEEDS_REVIEW(3) / ERROR(1) / OK(0) を分離
- transition API 経由の遷移（`session.status = ...` 直接代入禁止）

**セキュリティ / APPI 準拠**:
- セッション artifact は POSIX で 0o700 強制（既存ディレクトリも検査・補正）
- PII（氏名）をログに出さない（session_id / page_index / confidence のみ）
- artifact 削除失敗時は JSON を残す fail-hard（孤児化防止）
- sessions_dir 外の artifact パスは `SessionError` で拒否
- resume 時の TOCTOU（discard 競合）を lock 取得後再 load で検知

**Quality Gate 適用順**（5 層、タスク 8A の 4 層から 1 層追加）:
1. `/simplify` 3 並列（reuse/quality/efficiency）→ 7 件反映
2. `evaluator` 第三者評価（Acceptance Criteria 検証）→ 5 件反映（NEEDS_REVISION → APPROVE）
3. `/safe-refactor`（プロジェクト設定外のみ検出、アクションなし）
4. `/review-pr` 6 エージェント並列（code-reviewer / pr-test-analyzer / silent-failure-hunter / comment-analyzer / type-design-analyzer / code-simplifier）→ 7 件反映
5. `/codex review` セカンドオピニオン → 6 件反映（HIGH 3 / MEDIUM 3）

**Codex が検出した HIGH 3 件**（本 PR で解消）:
- PII（氏名）をログに出力 → `logger.info` から削除
- artifact 削除失敗の握り潰しで PII 孤児化 → `remove_session_artifacts` を fail-hard に
- resume 時 source A 同一性未検証で利用者取り違えリスク → SHA-256 fingerprint 導入

これらは 4 層目までの 6 エージェントでは検出されず、セカンドオピニオンの価値を再確認。

## 副次的成果: pre-push hook の再修正（別リポジトリ管理）

Session 3 で `~/.claude/hooks/pre-push-quality-check.sh` に適用した「プロジェクト `.venv/bin` PATH 前置」修正が現在のフックから欠落していたため、本 Session で再適用（ローカルのみ）。プロジェクトが Python 3.11 要求でシステム Python 3.9 で動いてテストが誤検知失敗する問題を解消。

`~/.claude` リポジトリは `yasushi-honda/claude-code-config` 管理で本セッションのトークンには push 権限なし。**次セッション（yasushi-honda アカウント）での対応**が必要。

## 積み残し Issues

### Session 5 優先
- **#37 タスク 8C**: 確認 UI (Tkinter) + Phase B + Integration tests（最大スコープ）
- **#51 Windows msvcrt / 跨プロセスロック / 境界値テスト** (P1): 本番 Windows 11 デプロイ前に必須

### タスク 8 関連の延期事項
- **#49 resume 時 candidates 妥当性検証** (P2): 8C の Phase B 呼出前ガードとして実装するのが自然
- **#50 `--list-sessions` で corrupted 件数表示** (P2): UX 改善、低コスト
- **#38** atomic_io ユーティリティ抽出（merger + session 重複）(P2)
- **#39** フリガナベースのマッチング（B/C PDF 生成機能の仕様確定後）(P2)
- **#40** B と C で異名マッチの扱い (P2)
- **#44** Session/UserCandidate immutable 化（`updated_at` mutation 排除）(P2)
- **#45** SourceKind を StrEnum 化 (P2)

### 別機能の積み残し（優先度低）
- #29 OCR プロキシ Nice-to-have
- #27 config dataclass 型設計強化
- #17 smoke_real.py pytest 統合
- #16 test_new_registration_flow カバレッジ
- #14 PywinautoEngine export_csv 失敗モード区別化
- #11 PywinautoEngine MEDIUM 5 件
- #6 PoC E2E テスト

## Acceptance Criteria 進捗（impl-plan Phase 2.7）

| AC | 内容 | 状態 | 検証箇所 |
|----|------|------|---------|
| AC1 | OCR プロキシ認証（APIキーなしで 401） | ✅ | `backend/ocr_proxy/tests/test_main.py` |
| AC2 | OCR 成功（既知 PDF ページ→利用者名） | 🔶 モックのみ、実 Cloud Run で未測定 | Session 5 タスク10 |
| AC3 | A 分割（5人分→5個の単ページ PDF） | ✅ | `tests/unit/pdf/test_splitter.py` |
| AC4 | ファイル名マッチング（欠損時 WARN） | ✅ | `test_merger.py` |
| AC5 | 順序設定反映（order=["A","C","B"]） | ✅ | `test_merger.py::test_concat_order_respected` |
| AC6 | D 末尾連結 | ✅ | `test_merger.py` |
| AC7 | 20名入力→1分以内 | ⏳ | Session 5 タスク10 |
| AC8 | OCR プロキシダウン時のリトライ3回 | ✅ | `test_ocr_client.py` |
| AC-T1 | transition_session の不正遷移検知 | ✅ | `test_session.py::TestTransitionSessionInvalid` |
| AC-T2 | READY_TO_MERGE 遷移時 all_candidates_resolved 必須 | ✅ | `test_session.py::TestTransitionSessionReadyGuard` |
| AC-T3 | 成功遷移後 session.status 更新 | ✅ | `test_session.py::TestTransitionSessionValid` |
| AC-L1 | with_session_lock 保持中の2回目取得失敗 | ✅ | `test_session.py::TestWithSessionLock` |
| AC-L2 | with 抜けでロック解放 | ✅ | `test_session.py::TestWithSessionLock` |
| AC-P1 | run_phase_a で session JSON 生成 | ✅ | `test_pipeline.py::TestRunPhaseAHappyPath` |
| AC-P1b | total_pages_a と page_*.pdf 数一致 | ✅ | `test_pipeline.py::TestPagePdfPersistence` |
| AC-P2 | confidence=low 強制昇格 | ✅ | `test_pipeline.py::TestConfidenceLow` |
| AC-P3 | OCR name=None バイパス | ✅ | `test_pipeline.py::TestOcrNameNone` |
| AC-P4 | KeyboardInterrupt で INTERRUPTED_PHASE_A 保存 | ✅ | `test_pipeline.py::TestInterruption` |
| AC-P4b | Resume で未処理ページから再開 | ✅ | `test_pipeline.py::TestInterruption` |
| AC-P5 | 確認 UI で needs_confirmation 解決 → ready_to_merge | ⏳ | PR #C |
| AC-P6 | run_phase_b は ready_to_merge のみ実行可 | ⏳ | PR #C |
| AC-P7 | 20名で Phase A < 60秒、Phase B < 5秒 | ⏳ | Session 5 タスク10 |
| AC-P8 | CLI `--list-sessions` / `--resume` / `--discard` | ✅ | `test_merge_user_pdfs_cli.py` |
| AC-P10 | SessionStatus / PairStatus が ADR-010 と一致 | ✅ | `test_session.py::TestSessionStatusTransitions` |
| AC-P11 | schema_version 付き JSON、破損時 SessionCorruptedError | ✅ | `test_session.py::TestLoadErrors` |
| AC-P12 | 日本語氏名の表記揺れ正規化 | ✅ | `test_matcher.py::TestNormalizeName` |
| AC-P13 | source A fingerprint 不一致時 resume 拒否 | ✅ | `test_pipeline.py::TestInterruption::test_resume_rejects_modified_source_a` |
| AC-P14 | resume TOCTOU (discard 競合) 検出 | ✅ | `test_pipeline.py::TestInterruption::test_resume_detects_discard_race` |

## セッション再開手順

```bash
# 1. 状況再確認
cd /Users/yyyhhh/Projects/wiseman_auto_sys
/catchup
/model   # Opus 4.7 xhigh であること確認

# 2. この handoff を読む
cat docs/handoff/LATEST.md

# 3. 次タスク着手（タスク 8C: 確認 UI + Phase B + Integration tests）
gh issue view 37   # タスク8C の詳細
/impl-plan         # Tkinter UI の設計判断多数あり
```

## 主要ファイル参照

- ADR-008: `docs/adr/008-ocr-backend.md`
- ADR-009: `docs/adr/009-ui-technology.md`
- ADR-010: `docs/adr/010-human-confirmation-state.md`（本 Session で API 実装状況を補記）
- Config 定義: `src/wiseman_hub/config.py`
- PDF モジュール:
  - `src/wiseman_hub/pdf/splitter.py`（タスク 5）
  - `src/wiseman_hub/pdf/ocr_client.py`（タスク 6）
  - `src/wiseman_hub/pdf/merger.py`（タスク 7）
  - `src/wiseman_hub/pdf/matcher.py`（タスク 8A）
  - `src/wiseman_hub/pdf/session.py`（タスク 8A + 8B 拡張）
  - **`src/wiseman_hub/pdf/pipeline.py`**（タスク 8B、新規）
- CLI: **`scripts/merge_user_pdfs.py`**（タスク 8B、新規）
- テスト: `tests/unit/pdf/test_{splitter,ocr_client,merger,matcher,session,pipeline}.py` + `tests/unit/test_merge_user_pdfs_cli.py`（計 250 件）
- OCR プロキシ: `backend/ocr_proxy/app/`
- デプロイ手順: `backend/ocr_proxy/deploy.md`
- sample TOML: `config/default.toml:42-75`

## Session 4 の学び（将来の参考）

### Quality Gate の 5 層化（Session 3 の 4 層から拡張）
Session 3 では `/simplify` → `evaluator` → `/review-pr` → `/codex review` の 4 層で High 2 件を検出。Session 4 で `/safe-refactor` を 3 層目に明示追加し 5 層化したが、実質的な指摘増は `/codex review` から来た。

### Codex セカンドオピニオンの継続的価値
5 層目の `/codex review` で検出した HIGH 3 件は 4 層目までの 6 エージェント並列でも検出されなかった:
- PII ログ出力（運用視点）
- artifact 削除の fail-hard（データ整合性）
- source A fingerprint（業務事故防止）

これらは「個別ファイルの良し悪し」ではなく「運用ワークフロー全体で何が起きるか」という俯瞰視点。Codex は別モデル（GPT）で別のバイアスを持つため、同種レビューでの補完価値が高い。

### テスト規模の増え方
- Session 2 (PDF merger): 111 件
- Session 3 (8A): 203 件 (+92)
- Session 4 (8B): 250 件 (+47)

機能 1 ユニット ≒ テスト 40〜90 件が目安。Quality Gate 層の指摘で追加されるテストは層あたり 1〜3 件。

### 次 Session へのスコープ注意
タスク 8C は本 PR より大きい可能性がある（Tkinter UI + Phase B オーケストレータ + E2E 統合テスト）。`/impl-plan` で PR を A/B/C に分割することを検討すること。
