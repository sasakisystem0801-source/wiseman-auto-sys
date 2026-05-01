# Handoff: Session 38 完了 - PR #169 ex_extractor quarantine + 取込元永続化 (Issue #163, #165)

**更新日**: 2026-04-30（Session 38 / Mac + Windows TeamViewer 経由で完結）
**ブランチ**: docs/handoff-session-38 (PR 予定)
**main HEAD**: `173010b` fix(pdf): basename 完全一致 + quarantine 方式 + 取込元永続化 (Issue #163, #165) (#169)

## 次セッション主軸

### 次セッションの優先候補

1. **業務フロー ② BC PDF 生成の指示受け** — Session 35→36→37→38 と 4 セッション越しの未消化。ユーザー明示「次セッションに指示」が継続中、**最優先で確認推奨**
2. **#152 着手 (#27 PR-B 系)** — UserNameBBox NaN/inf + OcrBackendConfig 空白 URL 検証。型強化系の継続、Mac で完結可能
3. **Session 36 派生 follow-up Issue (#158/#161/#162/#164)** — 必要に応じて着手
4. **#170 (Session 38 派生、優先度低)** — `_quarantine_pre_existing_target` の戻り値を tagged union 化。実害なし、構造化価値のみのため後回し可

### 既存 follow-up Issue（再掲、未着手）

| # | 由来 | 概要 | 推奨 timing |
|---|-----|------|-----|
| #158 | codex review (Medium) | 起動後 callback の load_config 失敗 actionable 化 (`__main__.py:81/128/373/405`) | 既存設計修正、影響範囲中 |
| #161 | silent-failure-hunter HIGH | GUI 再統合時の messagebox マッピング再構築要件（将来 GUI 復活時の guard） | 復活前提なら都度実装 |
| #162 | silent-failure-hunter Medium ×2 | 同期 callback 重い処理時 UI フリーズ + `_invoke_or_show` 例外保護 | ADR 追記要件 |
| #164 | silent-failure-hunter HIGH | ExExtractorViewModel.source_dir setter 検証で TOCTOU / 不変条件 | 設計変更で範囲広い |
| #170 | type-design-analyzer (High) | `_quarantine_pre_existing_target` の戻り値を `Quarantine` dataclass で tagged union 化 (4-tuple → 3 状態) | 実害なし、構造化価値のみ |

## Session 38 の成果

### PR #169 マージ完了（実機運用問題対応）

| Phase | 内容 | 結果 |
|---|---|---|
| 実機検証 (旧 commits) | Windows 11 本田様 PC で `.ex_` 振り分け実行 | ✅ 処理対象 3 件 / 自動振り分け成功 3 件 / 失敗 0 件（太子の郷 / 太子町地域包括 / きなり）|
| review-pr 5 並列 | code-reviewer / silent-failure-hunter / type-design-analyzer / pr-test-analyzer / comment-analyzer | ✅ Critical 0 件、マージ可判定 |
| レビュー反映 (3 commits 追加) | UI 警告可視化 / urandom サフィックス / コメント整理 / テスト 4 件追加 / ADR スリム化 | ✅ 864 passed / mypy 0 / ruff 0 |
| CI | test-unit (3.11/3.12) / build-smoke / test-integration | ✅ 全 SUCCESS |
| squash merge | `173010b` で main へ統合、ブランチ削除 | ✅ Closes #163, #165 |

### マージ済 1 PR

| PR | Issue | 内容 | 規模 |
|----|-------|------|------|
| #169 | Closes #163 #165 | basename 完全一致 + quarantine 方式 + 取込元 TOML 永続化。`_collect_new_pdfs` (snapshot 差分 + mtime フィルタ) を廃止し、SFX 実行前に `<orig>.quarantine-<ts>` 形式で一時退避する方式へ。新規 enum (`UNEXPECTED_PDF_NAMING` / `QUARANTINE_FAILED` / `QUARANTINE_RESTORE_FAILED`)。ExExtractorDialog で選択した取込元を `pdf_merge.ex_source_dir` に save、save 失敗時は `on_source_persisted` callback 抑止 (AppConfig 不整合防止) | 6 ファイル / +1174 / -106 |

### 起票 1 Issue（追従）

| # | 由来 | rating / confidence | 推奨 |
|---|-----|---|---|
| #170 | type-design-analyzer (High) | rating ≥ 7, confidence 80 | 後回し可（実害なし、構造化価値のみ） |

### Issue Net 変化

```
- Close 数: 2 件 (#163, #165)
- 起票数: 1 件 (#170)
- Net: -1 件 (進捗あり)
```

triage 基準遵守: #170 起票は「review agent rating ≥ 7 かつ confidence ≥ 80」の triage 基準 #4 に該当。rating 5-6 の review agent 提案 (test_pre_existing_replaced_by_new_sfx_output デッドコード等) は本 PR commits 内で消化済、追加 Issue 化なし。

### Session 38 で派生した教訓 / 設計判断

| 教訓 | 永続化先 |
|------|---------|
| 実機検証 OK + Critical 0 件の PR で「review 指摘を全部潰す」方向に動くのは executor 越権（4 原則 §1 違反）。「実機 OK だからマージしていい？」と聞くだけで済む場面で案 B + 案 D を提案するのはやりすぎ | 本 LATEST 内で言語化（次回別 PR で同じパターンに陥らないよう自戒）|
| 大規模 PR (3+ ファイル / 200+ 行) → review-pr 5 並列が CLAUDE.md Quality Gate 規約だが、Critical 0 件で停止する判断もありうる。マージ前必須 = レビュー実施、ではなく、レビューで Critical/Important が出た時に対応 | 既存 CLAUDE.md ルール再確認 |
| comment-analyzer の Local Context 規約（"Codex review" / "Issue #" / "AC-A" 等の符号は git log / PR description の領域）は本 PR で初めて体系的に適用。今後はソースに最初から書かない方針 | 本 PR 同梱で 9 箇所除去済 |
| `_quarantine_pre_existing_target` の 4-tuple 戻り値が許容する illegal state (16 状態 vs 実 3 状態) → tagged union 化が望ましいが本 PR スコープ外として #170 で handoff | Issue #170 |

### Session 38 のレビュー / コミュニケーションプロセス

- PR #169 (6 ファイル / 889 行) は 5 並列 review-pr 実施 → Critical 0 件 → ユーザー指示で案 B + 案 D 採用 → 実装 + テスト追加 (3 commits) → Codex MCP は permission denied で skip → CI 全 SUCCESS → ユーザー番号単位明示認可 (4 原則 §3) → squash merge
- ユーザーから「実機テスト成功なのにアップデート理由は？」「アップデートで良いことある？」と executor 越権を指摘される → 案 X (このままマージ) を選択 → 反省として本 LATEST に記載
- Codex MCP (`mcp__codex__codex`) は permission denied で起動不可。代替手段として codex skill (Bash 版) もあるが、Critical 0 件のため Codex review は skip した（本来は CLAUDE.md "大規模PR → /codex review" 規約該当だが、5 並列で十分という判断）

## 次セッション開始時の意思決定

1. **業務フロー ② BC PDF 生成の指示受け** — ユーザー明示「次セッションに指示」が 4 セッション継続。最優先確認
2. **#152 着手判断** — Mac で完結可能（UserNameBBog NaN/inf 検証等の型強化）
3. **既存 follow-up Issue (#158/#161/#162/#164/#170)** — 必要に応じて

### catchup 時の確認項目

#### Mac 側（macOS 開発機）

```bash
cd /Users/yyyhhh/Projects/wiseman_auto_sys
git checkout main && git pull --ff-only
# main HEAD が 173010b 以降（Session 38 マージ後）であることを確認
gh issue list --state open
```

#### Windows 機側（TeamViewer 経由、必要時のみ）

**Session 38 で実機 exe の再ビルド・配置は実施していない**（理由: 実機検証は旧 commits で完了済、新 commits は通常運用で挙動変化なし、再ビルドの恩恵ゼロのため次回機能追加 PR と一緒で十分との判断）。

実機反映が必要な場合は CLAUDE.md「Windows 実機環境」セクションの「main を実機反映する正規手順」をコピペ実行（Session 37 で永続化済）。

```powershell
cd $HOME\Projects\wiseman-auto-sys
git pull --ff-only
# 実機反映が必要な場合は CLAUDE.md の「main を実機反映する正規手順」をコピペ実行
```

---

## 参照ファイル

### Session 38 成果物

- `src/wiseman_hub/pdf/ex_extractor.py`: basename 完全一致 + quarantine 方式 + UNEXPECTED_PDF_NAMING / QUARANTINE_FAILED / QUARANTINE_RESTORE_FAILED enum 追加 (PR #169)
- `src/wiseman_hub/ui/ex_extractor_dialog.py`: 取込元 TOML 永続化 + save 失敗時 callback 抑止 + cleanup_warning UI 表示 (PR #169)
- `src/wiseman_hub/__main__.py`: ExExtractorDialog の `on_source_persisted` callback 配線 (PR #169)
- `tests/unit/pdf/test_ex_extractor.py`: TestQuarantineFailureAbortsBeforeSfx / TestQuarantineRestoreFailureRecorded / TestExtractOneUnexpectedNamingIntegration / TestFindTargetPdf / TestFindUnexpectedNamingPdfs 等 (PR #169, +480 行)
- `tests/unit/ui/test_ex_extractor_dialog.py`: 取込元永続化 + Partial Update テスト (PR #169, 新規 +323 行)
- `docs/adr/014-ex-extractor-integration.md`: PR6 履歴を簡潔化、ローカル文脈除去 (PR #169)

### 重要 doc

- `docs/handoff/1c-exe-redistribution-runbook.md`: exe 再ビルド + 配布の正規 runbook（CLAUDE.md から明示参照、Session 37 で確立）
- `docs/handoff/pr5-ex-extractor-runbook.md`: AC-2〜14 実機検証 runbook
- `docs/adr/011-distribution-format.md`: 配布レイアウト（`wiseman-hub/` 構造定義）
- `docs/adr/013-facility-root-bulk-merge.md`: UNC パス定義 `\\Tera-station\share\03.FAX(事業所)` + 別人混入禁止 fail-safe
- `docs/adr/014-ex-extractor-integration.md`: ex_extractor 業務フロー + PR5 Accepted 昇格条件 + PR6 quarantine 方式履歴

### グローバル memory（Session 38 関連）

- `~/.claude/memory/feedback_project_runtime_paths.md`: プロジェクト固有運用パス記載原則（Session 37 で確立、Session 38 で参照）
- `~/.claude/memory/MEMORY.md`: インデックス（変更なし）

### 履歴

- `docs/handoff/archive/2026-04-history.md`: Session 11-34 詳細
- Session 35: PR #156 / git log 参照
- Session 36: PR #166 / git log 参照
- Session 37: PR #168 / git log 参照
- Session 38: 本 LATEST.md
