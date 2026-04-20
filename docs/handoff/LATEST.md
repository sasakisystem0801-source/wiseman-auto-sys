# Handoff: PDF 分割・条件付き再結合機能の実装（Session 5 終了時点）

**更新日**: 2026-04-21
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
  ├─ Pure logic (resolve_candidate / compute_approve_decision / log_operation) — Tk 非依存
  └─ ConfirmDialog UI wiring — main thread 専用、report_callback_exception で fail-fast 復元
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
| 8B | Pipeline Phase A + CLI 骨格 | ✅ | PR #52 |
| 8C (PR #A) | **確認 UI (Tkinter) ConfirmDialog** | ✅ | **PR #54** |
| 8C (PR #B) | CLI + run_phase_b + session.status 遷移 | ⏳ **次セッション** | Issue #37 |
| 8C (PR #C) | E2E 統合テスト（A→OCR→matcher→UI→merger） | ⏳ 次セッション | Issue #37 |
| 10 | 実 Cloud Run デプロイ + AC2/AC7 実測 + Windows 実機 UI 確認 | ⏳ Session 5+ 予定 | - |
| 11 | README + sample TOML | ⏳ 最後 | - |

## Session 5 で完了した PR

### PR #54 - タスク 8C PR #A: ConfirmDialog 実装 [merged, commit b0433a9]

**実装内容**:
- `src/wiseman_hub/ui/confirm_dialog.py`（新規、650+ 行）: Tkinter 確認 UI + Pure logic (`resolve_candidate` / `compute_approve_decision` / `log_operation` / helpers)
- `src/wiseman_hub/pdf/session.py`（+12 行）: `OPEN_PAIR_STATUSES` 定数 + 網羅性 `assert`
- `tests/unit/ui/test_confirm_dialog.py`（新規、1040 行、48 テスト）: Layer 1 Pure logic (30 件) + Layer 2 UI wiring (18 件)
- `docs/ui-mockups/confirm-dialog-spec.md`（新規、195 行）: 仕様書（ADR-009/010 参照）

**設計判断（主要）**:
- **fail-fast 復元**: Tkinter 既定の callback 例外握り潰しを `_on_callback_exception` で上書き。`logger.error` + `messagebox.showerror` + `root.quit()`。医療介護分野の「操作できたように見える silent failure」を防止
- **`ConfirmDialogResult.aborted` フラグ**: save 失敗時、メモリ上は全件解決済みでもディスクは旧状態。`aborted=True` のとき `resolved_all` を False 固定し、呼出側が `READY_TO_MERGE` に進む業務事故経路を塞ぐ安全網
- **PII 防御**: 例外 message はファイルパス（`matched_b/c_path`）を含みうるため、ログには `type(e).__name__` のみ出力（画面 messagebox は PII 露出可）。`logger.exception` は traceback に path が入るので使わない
- **main thread 検証**: `__init__` で `threading.current_thread()` 確認、worker thread 呼出時 `RuntimeError`（tkinter thread-unsafe 対策）
- **ADR-010 整合**: `candidate.status` と `matched_b/c_path` のみ更新、`session.status` 遷移は呼出側（PR #B）責務。`ConfirmDialog` 本体は `transition_session` を呼ばない
- **2 層テスト構成**: Pure logic (Tk 不要) で AC の大半を検証、UI wiring (Tk 必要) は Layer 2 で skip ガード。macOS uv python は Tcl/Tk 非同梱のため skip、Linux/Windows で実行

**Quality Gate 適用順**（5 層 + Codex セカンドオピニオン）:
1. `/simplify` 3 並列（reuse/quality/efficiency）→ 7 件反映（commit 968025d）
2. `/safe-refactor` → 問題ゼロ
3. `evaluator` 第三者評価 → APPROVE、MEDIUM 1 + LOW 1 反映
4. `/review-pr` 6 エージェント並列（code-reviewer / pr-test-analyzer / silent-failure-hunter / comment-analyzer / type-design-analyzer / code-simplifier）→ CRITICAL 1 + IMPORTANT 10 + NICE 11 反映
5. `/codex review` セカンドオピニオン → HIGH 1 + MEDIUM 2 反映

**各層で検出された主要 HIGH/CRITICAL**（全て本 PR で解消）:
- silent-failure-hunter [CRITICAL]: Tkinter `report_callback_exception` 未設定 → `_on_callback_exception` 実装
- /codex review [HIGH]: save 失敗時の `resolved_all=True` 業務事故経路 → `aborted` フラグ
- /codex review [MEDIUM]: `logger.exception` / `logger.warning` の PII パス漏洩 → `type(e).__name__` のみ出力
- /codex review [MEDIUM]: tkinter main-thread 契約未防御 → `__init__` で検証

### 副次対応: Session 5 運用知見
- Windows Integration Tests が一時的に失敗することがある（`astral-sh/setup-uv@v4` zipball download で `C401:1469` の GitHub API 一時エラー）。`gh run rerun <id>` で復旧可能、コード起因ではない

## 積み残し Issues

### Session 6 最優先
- **#37 タスク 8C PR #B**: `scripts/review_ui.py` CLI + `run_phase_b()` + `session.status NEEDS_REVIEW → READY_TO_MERGE` 遷移。呼出側契約として `aborted=True` 時はメモリ破棄 + 再ロードを実装
- **#37 タスク 8C PR #C**: E2E 統合テスト（A 3 名 PDF → 2 名自動マッチ + 1 名確認 UI → merger で結合まで一気通貫）
- **#51 Windows msvcrt / 跨プロセスロック / 0 ページ PDF** (P1): 本番 Windows 11 デプロイ前に必須

### タスク 8 関連の延期事項
- **#49 resume 時 candidates 妥当性検証** (P2): 8C PR #B の Phase B 呼出前ガードとして実装するのが自然
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
| AC2 | OCR 成功（既知 PDF ページ→利用者名） | 🔶 モックのみ、実 Cloud Run で未測定 | Session 5+ タスク 10 |
| AC3 | A 分割（5人分→5個の単ページ PDF） | ✅ | `tests/unit/pdf/test_splitter.py` |
| AC4 | ファイル名マッチング（欠損時 WARN） | ✅ | `test_merger.py` |
| AC5 | 順序設定反映（order=["A","C","B"]） | ✅ | `test_merger.py::test_concat_order_respected` |
| AC6 | D 末尾連結 | ✅ | `test_merger.py` |
| AC7 | 20名入力→1分以内 | ⏳ | Session 5+ タスク 10 |
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
| AC-P5 | 確認 UI で needs_confirmation 解決 → ready_to_merge | 🔶 UI 側 ✅ / pipeline 統合 ⏳ | PR #B |
| AC-P6 | run_phase_b は ready_to_merge のみ実行可 | ⏳ | PR #B |
| AC-P7 | 20名で Phase A < 60秒、Phase B < 5秒 | ⏳ | Session 5+ タスク 10 |
| AC-P8 | CLI `--list-sessions` / `--resume` / `--discard` | ✅ | `test_merge_user_pdfs_cli.py` |
| AC-P10 | SessionStatus / PairStatus が ADR-010 と一致 | ✅ | `test_session.py::TestSessionStatusTransitions` |
| AC-P11 | schema_version 付き JSON、破損時 SessionCorruptedError | ✅ | `test_session.py::TestLoadErrors` |
| AC-P12 | 日本語氏名の表記揺れ正規化 | ✅ | `test_matcher.py::TestNormalizeName` |
| AC-P13 | source A fingerprint 不一致時 resume 拒否 | ✅ | `test_pipeline.py::TestInterruption::test_resume_rejects_modified_source_a` |
| AC-P14 | resume TOCTOU (discard 競合) 検出 | ✅ | `test_pipeline.py::TestInterruption::test_resume_detects_discard_race` |
| AC-UI-1〜5, 9, 11 | ConfirmDialog 承認/却下/手動/スキップ操作、PII 保護、stdlib-only | ✅ Layer 1 | `test_confirm_dialog.py`（macOS で 31 件実行） |
| AC-UI-6, 7, 8, 10 | save 呼出、X クローズ、全件解決検知、fail-fast | ✅ Layer 2 定義済み | Windows 実機で検証（Session 5+ タスク 10） |

## セッション再開手順

```bash
# 1. 状況再確認
cd /Users/yyyhhh/Projects/wiseman_auto_sys
/catchup
/model   # Opus 4.7 xhigh であること確認

# 2. この handoff を読む
cat docs/handoff/LATEST.md

# 3. 次タスク着手（タスク 8C PR #B: CLI + run_phase_b + transition_session）
gh issue view 37   # タスク 8C の全体スコープ
/impl-plan         # PR #A の呼出側契約（aborted 時の再ロード）に注意
```

## 主要ファイル参照

- ADR-008: `docs/adr/008-ocr-backend.md`
- ADR-009: `docs/adr/009-ui-technology.md`
- ADR-010: `docs/adr/010-human-confirmation-state.md`
- Config 定義: `src/wiseman_hub/config.py`
- PDF モジュール:
  - `src/wiseman_hub/pdf/splitter.py`（タスク 5）
  - `src/wiseman_hub/pdf/ocr_client.py`（タスク 6）
  - `src/wiseman_hub/pdf/merger.py`（タスク 7）
  - `src/wiseman_hub/pdf/matcher.py`（タスク 8A）
  - `src/wiseman_hub/pdf/session.py`（タスク 8A + 8B + 8C PR #A 拡張）
  - `src/wiseman_hub/pdf/pipeline.py`（タスク 8B、`run_phase_b` 追加は PR #B）
- UI:
  - **`src/wiseman_hub/ui/confirm_dialog.py`**（タスク 8C PR #A、新規）
  - `scripts/review_ui.py`（PR #B で新規）
- CLI: `scripts/merge_user_pdfs.py`（タスク 8B）+ PR #B で `review_ui` サブコマンド追加予定
- テスト: `tests/unit/pdf/test_{splitter,ocr_client,merger,matcher,session,pipeline}.py` + `tests/unit/test_merge_user_pdfs_cli.py` + `tests/unit/ui/test_confirm_dialog.py`（計 298 件）
- OCR プロキシ: `backend/ocr_proxy/app/`
- デプロイ手順: `backend/ocr_proxy/deploy.md`
- sample TOML: `config/default.toml:42-75`
- 仕様書: `docs/ui-mockups/confirm-dialog-spec.md`

## Session 5 の学び（将来の参考）

### Quality Gate 5 層 + Codex セカンドオピニオンの補完価値
Session 3/4 に続き、Codex は層 4 までの 6 エージェントが見落とす「運用ワークフロー全体で起きる」問題を検出:
- **HIGH**: save 失敗時の `resolved_all=True` 業務事故経路（最終候補でのディスク書込失敗 → メモリ全解決 → 呼出側が READY_TO_MERGE に誤遷移）
- **MEDIUM**: `logger.exception` による PII 漏洩（例外 message のファイルパス）
- **MEDIUM**: tkinter main-thread 契約の未防御

これらは個別ファイルのレビューでは発見できず、**データフロー + フレームワーク契約 + スレッドモデル**を俯瞰する視点でのみ見つかる。Codex の別モデル（GPT）バイアスの補完価値を継続確認。

### UI テストの 2 層化
macOS 開発機では Tcl/Tk 非同梱のため Layer 2 (UI wiring) テストは skip が必須。Pure logic を Tk 非依存で切り出すことで AC の大半を Layer 1 でカバーでき、macOS でも 31/48 件が実行できる。Layer 2 は Windows 実機 + Linux CI (Xvfb) で検証。

### CI インフラ起因の一時失敗への対応
`astral-sh/setup-uv@v4` の zipball download で GitHub API 側の 5xx が発生することがある（Session 5 で遭遇、エラーコード `C401:1469`）。**コード起因ではないので `gh run rerun <id>` で復旧**。handoff ではこの経験を記録し、次セッションで同種失敗を見たときに無駄な調査を避ける。

### テスト規模の増え方
- Session 2 (PDF merger): 111 件
- Session 3 (8A): 203 件 (+92)
- Session 4 (8B): 250 件 (+47)
- Session 5 (8C PR #A): 298 件 (+48)

PR #A（UI 単体）で +48 件は「UI 操作 4 種 × 境界値複数 + 2 層構成 + Quality Gate 追加分」の合計。PR #B（pipeline 統合）では integration テストで +20〜30 件を想定。

### PR 分割の有効性
タスク 8C を PR #A (UI) / PR #B (pipeline) / PR #C (E2E) に分割した判断は正解。PR #A は +1914 行で、Quality Gate 5 層 + 大量のレビュー指摘を一度に反映できた。PR #B は UI に対する呼出側契約（`aborted` 再ロード、`transition_session`）に集中できる。PR #C は両方を結合した E2E テストに専念できる。
