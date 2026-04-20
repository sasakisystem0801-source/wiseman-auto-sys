# Handoff: PDF 分割・条件付き再結合機能の実装（Session 6 終了時点）

**更新日**: 2026-04-21
**ブランチ**: main (clean, origin と同期済み、PR #56 squash merged @ 9684b8f)
**次セッションで `/catchup` を実行して再開可能**

## 機能概要

複数利用者がまとまった PDF (A) を1利用者=1ページで分割し、OCR で利用者名抽出、利用者ごとに別 PDF (B, C) を指定順で結合、末尾に共通 PDF (D) を追加して1つの PDF を生成する機能。誤記/OCR 揺れで類似マッチした場合、Tkinter UI で人間が承認してから結合する（自動結合を回避）。

- **入力**: A（複数利用者PDF、固定矩形OCR）、B/C（利用者別PDF、ファイル名に利用者名）、D（共通PDF）
- **出力**: 全利用者分を連結した1つの PDF
- **環境**: Windows デスクトップアプリ（1施設1PC、ADR-002 の PyInstaller パッケージ）
- **MVP 対象規模**: 1〜3 名/バッチ（実運用ほぼ 1 名）。AC7 の 20 名性能測定は範囲外

## アーキテクチャ

```
Windows Desktop App
  ↓ HTTPS (X-API-Key)
Cloud Run (asia-northeast1)  ← OCR プロキシ
  ↓ SA (roles/aiplatform.user)
Vertex AI Gemini 2.5 Flash (GA, asia-northeast1)

確認 UI: Tkinter（stdlib、ADR-009）— ConfirmDialog (PR #54)
Pipeline: run_phase_a + run_phase_b (PR #56) — ADR-010 state machine
CLI: scripts/merge_user_pdfs.py 1 本
  ├─ 引数なし / --resume / --discard / --list-sessions (タスク 8B)
  └─ --review / --merge (タスク 8C PR #B、NEW)
Tkinter: _default_dialog_factory 内で lazy import（macOS 開発機で Tk 非依存）
```

## 実装計画

| # | タスク | 状態 | PR |
|---|-------|------|-----|
| 1〜7 | ADR-008 / Cloud Run / config / splitter / OCR client / merger | ✅ | #26〜#33 |
| 8A | ADR-009/010 + matcher + session 基盤 | ✅ | #43 |
| 8B | Pipeline Phase A + CLI 骨格 | ✅ | #52 |
| 8C (PR #A) | 確認 UI (Tkinter) ConfirmDialog | ✅ | #54 |
| **8C (PR #B)** | **run_phase_b + CLI --review/--merge** | ✅ | **#56 (本セッション)** |
| 8C (PR #C) | E2E 統合テスト自動化 | ❌ **MVP スコープ外** | - |
| 10 | 実 Cloud Run デプロイ + Windows 実機 E2E | ⏳ **次セッション最優先** | - |
| 11 | README + sample TOML | ⏳ 最後 | - |

**MVP 方針転換**（Session 6）: 対象 1〜3 名運用を前提に、PR #C 自動 E2E / AC7 性能測定 / #51 跨プロセスロック / updater / scheduler を明示スコープ外に。「シンプルに使えるレベル」を最短で到達する方針。

## Session 6 で完了した PR

### PR #56 - タスク 8C PR #B: run_phase_b + CLI --review/--merge [merged, commit 9684b8f]

**実装内容**:
- `src/wiseman_hub/pdf/pipeline.py`（+190 行）: `run_phase_b()` / `_build_user_page_sources()` / `_page_pdf_filename()` / `_PHASE_B_START_STATUSES` / `_MERGEABLE_PAIR_STATUSES` + OPEN との isdisjoint invariant / `_unlink_with_warning()`
- `src/wiseman_hub/pdf/merger.py`（+51 行）: `UserPageSource` に `matched_b_path` / `matched_c_path` optional 追加、`_resolve_bc_path()` helper、PII 防御のためログから氏名・フルパス削除
- `scripts/merge_user_pdfs.py`（+275 行）: `--review` / `--merge` サブコマンド、`_cmd_review` / `_cmd_merge` / `_resolve_merge_output_path()`、`_DialogFactory` Protocol、Tkinter lazy import
- テスト 3 ファイル +700 行、30 新規テスト（28 + PII 防御 2）

**設計判断（主要）**:
- **REJECTED / SKIPPED は利用者ごと丸ごと除外**（A も出さない）。MVP 1〜3 名では「一部だけ抜けた PDF」を作らない方針
- **MANUALLY_SELECTED の matched_b/c_path 優先**: merger で `source_b_pattern` をバイパスする override 経路を追加し、ConfirmDialog の手動選択を反映
- **CLI 統合方針**: 別ファイル `review_ui.py` は作らず、`merge_user_pdfs.py` 1 本に `--review` / `--merge` を統合（運用者の学習コスト低減）
- **RUNNING_PHASE_B stuck 検出**: disk full 等で INTERRUPTED 保存自体が失敗した稀ケースを CLI 入口で検知し、手動復旧手順（session JSON 編集 or --discard）を案内
- **ロック二分割の既知リスク**: UI 実行中のロック解放 → transition 再取得の間に別プロセスが触るレース窓。MVP 単一 PC 運用では発生しない前提で受容、コメントで明示化
- **欠損 B/C は fail-hard**（Codex 指摘）: `MergeReport.has_missing_sources` True なら `PdfMergeError` で INTERRUPTED_PHASE_B 停止 + 不完全 output PDF を自動削除。欠損付き PDF の誤配布を防ぐ

**Quality Gate 6 段通過**:
1. `/simplify` 3 並列 → 3 件反映（`_page_pdf_filename` 抽出 / `_ConfirmDialogLike` Protocol を `ConfirmDialogResult` に絞って `getattr` 排除 / task-ID コメント削除）
2. `/safe-refactor` → 1 件反映（aborted コメント実装乖離修正）
3. `evaluator` 第三者評価 → REQUEST_CHANGES 3 件反映（AC-CLI-R2/M2 等値化、`--merge` 拒否 parametrize 4 件、ロックレース既知リスク明示）
4. `/review-pr` 6 エージェント並列 → 6 件反映（MERGEABLE invariant assert、サマリログ、stuck 検出、FileNotFoundError parametrize、output_path=None assert、コメント訂正）
5. `/codex review` セカンドオピニオン → **CRITICAL 1 + HIGH 3 反映**:
   - [CRITICAL] `MergeReport.missing_sources` 検知漏れ → fail-hard + output 削除
   - [HIGH] merger warning ログの氏名・パス漏洩 → 件数のみ
   - [HIGH] missing サマリログの氏名漏洩 → B/C 別件数集計
   - [HIGH] `_cmd_merge` の `print(f"error: ...{e}")` で PdfMergeError message の氏名・パス漏洩 → 型名 + session_id に抑制、`logger.exception` → `logger.error`

### Codex の追加価値が確認された層
Claude 側 5 層（simplify / safe-refactor / evaluator / review-pr 6 エージェント / type-analyzer）全てが見落とした **医療介護 PII 漏洩経路 3 件 + 業務事故経路 1 件** を検出。個別ファイルレビューでは見つからない「データフロー全体 + ログ集約 + CLI 出力」の俯瞰が必要な指摘で、Codex (GPT) の別モデルバイアスの補完価値を再確認。

## 積み残し Issues

### Session 7 最優先（MVP "使える" まで）
- **タスク 10 実 Cloud Run デプロイ**（`backend/ocr_proxy/deploy.md` 参照、AC2 実測）
- **タスク 10 Windows 実機 E2E**: `--review` の Tkinter 描画 + `--merge` 経由の出力 PDF 確認
- **タスク 11 README + sample TOML**: インストール・起動・よくあるエラー

### MVP 後回し可（明示スコープ外）
- **#51** Windows msvcrt / 跨プロセスロック / 0 ページ PDF (P1 だが単一 PC では発生せず)
- **#49** resume 時 candidates 妥当性検証 (P2)
- **#50** `--list-sessions` で corrupted 件数表示 (P2)
- **#38** atomic_io ユーティリティ抽出 (P2)
- **#39** フリガナベースのマッチング (P2)
- **#40** B と C で異名マッチの扱い (P2)
- **#44** Session/UserCandidate immutable 化 (P2)
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
| AC1 | OCR プロキシ認証（401） | ✅ | `backend/ocr_proxy/tests/test_main.py` |
| AC2 | OCR 成功（既知 PDF → 氏名） | 🔶 モックのみ | Session 7 タスク 10 |
| AC3 | A 分割（5人分→5個） | ✅ | `test_splitter.py` |
| AC4 | ファイル名マッチング | ✅ | `test_merger.py` |
| AC5 | 順序設定反映 | ✅ | `test_merger.py::test_concat_order_respected` |
| AC6 | D 末尾連結 | ✅ | `test_merger.py` |
| AC7 | 20名で1分以内 | ❌ **MVP スコープ外**（1〜3 名想定） | - |
| AC8 | OCR リトライ3回 | ✅ | `test_ocr_client.py` |
| AC-T1〜3 / L1〜2 | session.py 状態遷移・ロック | ✅ | `test_session.py` |
| AC-P1〜4 | run_phase_a | ✅ | `test_pipeline.py` |
| **AC-P5** | 確認 UI → ready_to_merge | ✅ **Session 6** | `test_merge_user_pdfs_cli.py::TestReviewCommand` |
| **AC-P6** | run_phase_b は ready_to_merge のみ | ✅ **Session 6** | `test_pipeline.py::TestRunPhaseBStateGuard` |
| AC-P7 | 性能 | ❌ MVP スコープ外 | - |
| AC-P8 | CLI `--list-sessions` / `--resume` / `--discard` | ✅ | `test_merge_user_pdfs_cli.py` |
| **AC-P8b** | CLI `--review` / `--merge` | ✅ **Session 6** | `test_merge_user_pdfs_cli.py::TestReviewCommand, TestMergeCommand` |
| AC-P10〜14 | ADR-010 整合 / fingerprint / TOCTOU | ✅ | `test_session.py, test_pipeline.py` |
| **AC-PB-1** | READY_TO_MERGE → COMPLETED + PDF 生成 | ✅ **Session 6** | `test_pipeline.py::TestRunPhaseBHappyPath` |
| **AC-PB-2** | merger 失敗 → INTERRUPTED_PHASE_B | ✅ **Session 6** | `test_pipeline.py::TestRunPhaseBInterrupted` |
| **AC-PB-3** | REJECTED/SKIPPED 除外 | ✅ **Session 6** | `test_pipeline.py::TestRunPhaseBExclusion` |
| **AC-PB-4** | MANUALLY_SELECTED のカスタムパス優先 | ✅ **Session 6** | `test_pipeline.py::TestRunPhaseBManualSelected` + `test_merger.py` |
| **AC-PB-5** | INTERRUPTED_PHASE_B → リトライ COMPLETED | ✅ **Session 6** | `test_pipeline.py::TestRunPhaseBInterrupted` |
| **AC-Missing** | 欠損 B/C で fail-hard + output 削除 | ✅ **Session 6** | `test_pipeline.py::test_missing_b_source_is_fatal_and_removes_output` |
| **AC-PII-CLI** | merger 由来の PdfMergeError の氏名/path が stderr に漏れない | ✅ **Session 6** | `test_merge_user_pdfs_cli.py::test_merge_error_stderr_does_not_leak_pii` |
| AC-UI-1〜5, 9, 11 | Pure logic | ✅ Layer 1 | `test_confirm_dialog.py` |
| AC-UI-6, 7, 8, 10 | UI wiring | ✅ Layer 2 定義済み | **Session 7 Windows 実機で実行** |

## セッション再開手順

```bash
# 1. 状況再確認
cd /Users/yyyhhh/Projects/wiseman_auto_sys
/catchup
/model   # Opus 4.7 xhigh であること確認

# 2. この handoff を読む
cat docs/handoff/LATEST.md

# 3. 次タスク着手: タスク 10（Cloud Run デプロイ + Windows 実機 E2E）
cat backend/ocr_proxy/deploy.md      # デプロイ手順
# Windows 実機での確認項目:
#   - merge_user_pdfs.py で A.pdf を処理し NEEDS_REVIEW 到達
#   - --review で Tkinter ダイアログが実描画されること（AC-UI-6〜10）
#   - --merge で output PDF が生成されること
#   - --discard で session + artifact 削除
```

## 主要ファイル参照

- ADR-008: `docs/adr/008-ocr-backend.md`
- ADR-009: `docs/adr/009-ui-technology.md`
- ADR-010: `docs/adr/010-human-confirmation-state.md`
- Config 定義: `src/wiseman_hub/config.py`
- PDF モジュール:
  - `src/wiseman_hub/pdf/splitter.py`（タスク 5）
  - `src/wiseman_hub/pdf/ocr_client.py`（タスク 6）
  - `src/wiseman_hub/pdf/merger.py`（タスク 7 + 8C PR #B 拡張）
  - `src/wiseman_hub/pdf/matcher.py`（タスク 8A）
  - `src/wiseman_hub/pdf/session.py`（タスク 8A + 8B + 8C PR #A 拡張）
  - `src/wiseman_hub/pdf/pipeline.py`（タスク 8B + **8C PR #B で run_phase_b 追加**）
- UI: `src/wiseman_hub/ui/confirm_dialog.py`（タスク 8C PR #A）
- **CLI**: `scripts/merge_user_pdfs.py`（タスク 8B + **8C PR #B で --review / --merge 追加**）
- テスト: `tests/unit/pdf/test_{splitter,ocr_client,merger,matcher,session,pipeline}.py` + `tests/unit/test_merge_user_pdfs_cli.py` + `tests/unit/ui/test_confirm_dialog.py`（計 307 件）
- OCR プロキシ: `backend/ocr_proxy/app/`
- デプロイ手順: `backend/ocr_proxy/deploy.md`
- sample TOML: `config/default.toml:42-75`
- 仕様書: `docs/ui-mockups/confirm-dialog-spec.md`

## Session 6 の学び（将来の参考）

### MVP スコープ明示化の効果
Session 6 冒頭で「対象 1〜3 名」という運用前提を確認し、以下を明示スコープ外に設定:
- PR #C 自動 E2E 統合テスト（手動 E2E で代替）
- AC7 性能測定（20 名は想定外規模）
- #51 跨プロセスロック（単一 PC では発生せず）
- updater / scheduler / PyInstaller パッケージング（直接配布で足りる）

結果、PR #B 一本で「使える」に必要な機能（Phase B + CLI 統合）を集中実装できた。handoff 冒頭の **「対象規模と運用前提の明示」が後続意思決定の質を決める** ことが再確認された。

### Codex セカンドオピニオンの再現性
Session 3/4/5 に続き Session 6 も、Codex は層 4 までの 6 エージェントが見落とす問題を検出:
- CRITICAL: `MergeReport.missing_sources` 検知漏れ → 欠損付き PDF の誤配布
- HIGH ×3: PII（氏名・パス）がログ・stderr 経由で漏洩する 3 経路

いずれも **「merger 単体テストで確認済みの正常動作」と「CLI 統合後に生まれる運用経路」のギャップ** に起因する。個別ファイルの review では見つからない。Codex の別モデル（GPT）バイアスの補完価値は 4 セッション連続で有効。

### テスト規模の増え方
- Session 2 (PDF merger): 111 件
- Session 3 (8A): 203 件 (+92)
- Session 4 (8B): 250 件 (+47)
- Session 5 (8C PR #A): 298 件 (+48)
- **Session 6 (8C PR #B): 307 件 (+9)** ※ 28 新規テスト追加 - 既存差し替えあり

PR #B は Phase B + CLI 統合の規模に対してテスト件数の増え方は控えめ。理由は既存 `test_pipeline.py` / `test_merge_user_pdfs_cli.py` に統合する形で、重複を避けたため。`TestRunPhaseB*` と `TestReviewCommand/TestMergeCommand` の各クラスでパラメータ化を活用。

### MVP "使える" への距離
Session 6 終了時点で、コア機能は完成。残り 3 段階:
1. **実デプロイ**（`backend/ocr_proxy/deploy.md` を実行）
2. **Windows 実機確認**（Tkinter 描画 + RPA 連携）
3. **README**（運用者向け最小ドキュメント）

Session 7 で (1)(3) を確定、(2) は実機アクセス可否次第。完成後も「自動更新」「スケジューラ」「PyInstaller exe 化」は意図的に未実装（必要になったら別 Issue）。
