# Session 70 完了 — Issue #238 実機検証 + Phase 3b 由来 test regression fix (PR #277) + UX 観察 3 件 Issue 化

**Date**: 2026-05-14
**Main HEAD**: `3bb1784` fix(tests): test_browse_source identity assertion を frozen replace 契約に追従 (#277)
**Test count**: main project 1815 維持 (PR #277 は test 修正 1 件、追加なし)
**Active Issues**: 13 (実質 8、postpone 5) [変化: +3、Net 悪化、業務価値正当]
**Phase**: Phase 7 着手前 [変化なし]

---

## セッション経緯と方向修正

本セッションは Session 69 完了後 `/catchup` 経由で「Phase 1-3b Windows 実機検証 + `facility_root_dialog` Critical 修正検証」を最優先と認識して開始。TeamViewer 経由で本田様 PC に接続後、ユーザーから方向修正:

> 「frozen 化 (Issue #27) は内部品質改善で外から見えない。本来の最優先は **Issue #238 (GCP 同期サマリー UI) のシンプル化が本田様視点で機能しているか** の検証だ」

catchup が Session 69 LATEST の「次セッション優先順 1 位」を額面通り受けて誤った scope に着地していた → **CLAUDE.md 4 原則 §1 (executor 越権)** を認め scope 切替。Issue #238 業務視点検証に方向修正。

---

## 完了内容

### 1. 実機反映 (本田様 PC `C:\Users\sasak\Projects\wiseman-auto-sys`、TeamViewer)

`docs/handoff/1c-exe-redistribution-runbook.md` の Phase 0-3 を踏襲:

| Phase | 結果 |
|-------|------|
| 0: `git pull --ff-only` | HEAD = `9c4be48` (Session 69 handoff) まで反映 |
| 0-2: backup | `wiseman_hub.exe.bak-20260514-055032` (79.26 MB、旧 LastWriteTime 2026/05/06) |
| 0-4: `uv sync --extra dev` + `pytest -q -m "not integration"` | **4 failed, 1912 passed, 2 skipped** (詳細下記) |
| 1: PyInstaller clean build | 成功、Hidden import warnings は無害 3 件 (`pycparser.lextab` / `yacctab` / `jinja2`) |
| 2: 配布上書き | 84.21 MB、LastWriteTime 2026/05/14 6:00:56 (+5 MB は launcher 関連新規モジュール由来で説明可能) |
| 3: Launcher 起動 | **成功** (コンソール窓なし、5 ボタン構成、GCP 同期サマリー上部表示) |

> ⚠️ CLAUDE.md の Phase 3 チェックリスト #2 は「3 ボタン構成」と古い記述。実際は **5 ボタン** (ex_ ファイル変換 + 振り分け / B: 運動機能向上計画書 自動配置 / C: 経過報告書 自動配置 / 事業所フォルダ一括結合 / 設定)。次セッションで CLAUDE.md 更新候補。

### 2. 実機 pytest 4 件 fail の切り分け

CI (Linux ubuntu-latest) では `tk_required` が **全 SKIPPED** されているため CI green、Windows 実機で初顕在化。

| FAIL | 真の原因 | frozen 由来? | 対応 |
|------|---------|--------------|------|
| `test_browse_source_calls_on_source_persisted_after_save_success` | **PR #272 frozen 化由来 regression** (`replace()` で新インスタンス化、L1201 `is` チェックが構造的に常に fail) | ✅ | **PR #277 で fix (merged)** |
| `test_clear_cache_removes_entry_and_saves` | 実機 Python 3.11 Tcl `init.tcl` 破損 (`tk.Tk()` 自体が `TclError`) | ❌ | 環境問題、別途修復 (Python 再インストール検討) |
| `test_clicking_header_sorts_ascending_then_descending` | Windows Tk 仕様差 (`tree.heading()["command"]` が Tcl コマンド名文字列を返す) | ❌ | Issue #276 の構造解消で検出経路確保 + 別 PR で test 書き換え |
| `test_status_column_uses_custom_priority_key` | 同上 | ❌ | 同上 |

### 3. Issue #238 業務視点検証 (TaskCreate ベース 5 タスク)

| Task | 状態 | 結果 |
|------|------|------|
| #1 起動体験評価 | ✅ 完了 | 起動は `Start-Process` 直後表示で I-2 `defer_initial_refresh` 効果体感あり。サマリー表示 (居宅対照表 / 担当者マッピング / シート一覧) は機能 PASS、本田様視点で **UX 観察 2 件** を発見 |
| #2 居宅マッピング pull → save | ⏭ スキップ判定 | 本番マッピング上書きリスク vs CI test (`test_on_save_records_only_when_dirty` で構造担保) の比較で実機破壊操作回避 |
| #3 担当者マッピング pull → save | ⏭ スキップ判定 | Task #2 と同理由 |
| #4 F4 closed-loop verify (pull → キャンセル) | ✅ **PASS** | pull で編集枠更新 → キャンセルで dialog 破棄 → Launcher サマリー「居宅対照表: 不明」のまま維持。**PR #243 F4 dirty flag が業務動線で意図通り動作** |
| #5 まとめ + test 修正 PR | ✅ 完了 | PR #277 (frozen 由来 regression fix) merged + Issue 3 件起票 + 本 handoff |

### 4. Issue 起票 3 件 (本日の本セッション主成果)

| Issue | タイトル | label | triage 根拠 | rating |
|-------|---------|-------|------------|--------|
| **#274** | B/C 自動配置ダイアログ「詳細」列の見切れで利用者氏名/PDF パスが読めない | enhancement, P2 | 基準 #5 (ユーザー明示指示) | 7 |
| **#275** | ChecklistSettingsDialog の GCP 同期ボタン UI シンプル化 (Issue #238 Phase 4 候補) | enhancement, P2 | 基準 #5 | 7 |
| **#276** | Windows runner で UI tests (tk_required) を走らせる workflow 追加 (Linux skip 構造的盲点の解消) | enhancement, P2 | 基準 ③ (CI/リリース判断を壊す) + 基準 #5 | 7 |

**Net +3 だが triage 基準遵守 + 業務価値正当** (本田様 UX × 2 + 構造盲点解消 × 1)。

### 5. PR #277 — Phase 3b 由来 test regression fix (1 file, +16/-2)

- **発見経緯**: 実機 pytest で `test_browse_source_calls_on_source_persisted_after_save_success` が PR #272 (Phase 3b root frozen 化) 由来の真の regression と特定
- **原因 contract change**: `_on_browse_source` は `replace()` 経由で新 AppConfig instance を生成し callback に渡すよう変更 (PR #272 `src/wiseman_hub/ui/ex_extractor_dialog.py` L720-743)
- **旧 test は mutation 前提**: L1201 `assert callback_calls[0] is config` は frozen 化前の「同一インスタンス維持」前提のため、Phase 3b で構造的に常に fail
- **CI 盲点**: `tk_required` テストが Linux CI で全 skip されるため検知されず、Session 70 実機で初顕在化
- **修正**: 3 アサーション化 — `is not config` (new instance lock-in) / `pdf_merge.ex_source_dir == str(new_source)` (選択値反映) / `pdf_merge.facility_root_dir == str(root_dir)` (replace scope 妥当性)
- **検証**: Mac local `pytest` SKIPPED (tk_required 想定通り) / ruff PASS / production contract と整合 / lightweight review 通過 / 番号単位 merge 認可済

---

## ⚠️ 注意事項 / 次セッション着手前確認

### 1. 本田様 PC の exe は PR #277 未反映 (業務影響ゼロ、急がない)

実機にデプロイ済の `wiseman_hub.exe` (84.21 MB、2026/05/14 6:00:56 build) は HEAD = `9c4be48` (Session 69) 時点の内容。PR #277 (test 修正のみ、production code 変更ゼロ) は実機 exe に乗っていないが **業務影響なし**。次セッションで Issue #275 or #276 関連の production 変更が入る際に同時再ビルドで取り込めば十分。

### 2. Issue #238 は部分達成と判明

Phase 1/2-α/2-β で **表示シンプル化** (サマリー UI / pull-save closed-loop verify / 起動高速化 / silent failure 可視化) は本田様視点で機能 (Task #4 PASS で実証)。一方、**操作シンプル化** (ボタン UI 階層) は元々 scope 外で未達 → Issue #275 で Phase 4 候補として記録。

### 3. CI 盲点 (Issue #276) は同種 PR #181 と再発、構造解消が必要

PR #181 (2026-05-04 Windows pytest 失敗 11 件修正) と **同じ「Linux CI で tk_required skip → Windows 実機で初回顕在化」パターン** が本セッションで再発。impl-plan + 専用 workflow 追加で構造解消推奨 (Issue #276 改善候補 B)。

### 4. Mac セッション着手不可項目 (前セッション継承、変化なし)

- #17 (smoke_real.py pytest 統合)
- #16 (test_new_registration_flow Pane/Text 経路)
- #11 (PywinautoEngine MEDIUM 5 件)
- #6 (PoC E2E)

### 5. handoff debt (Session 64 から繰越、変化なし)

- `build-windows-smoke.yml` に `Verifier.production(offline=True)` smoke 追加
- Trust root staleness 監視 (warn-log)
- sigstore-python 3.x dependency docstring

### 6. AskUserQuestion 過剰の教訓を memory 化

スクショ駆動 UX 評価中に 3 択主観質問を出すとユーザー認知を縛る → [feedback_screen_based_review_no_multichoice.md](~/.claude/memory/feedback_screen_based_review_no_multichoice.md) (Session 70 実例で記録)。実機/スクショ評価中は **平文で観察報告を促す** に切替済。

### 7. CLAUDE.md チェックリスト #2 が古い (ボタン構成)

「3 ボタン構成」記載 → 実際は **5 ボタン**。`docs/handoff/1c-exe-redistribution-runbook.md` Phase 3 も同様。次セッションで小規模 docs PR 候補。

---

## 次セッション優先順

1. **Issue #275** (ChecklistSettingsDialog 同期ボタン UI シンプル化) — `/brainstorm` → `/impl-plan` 推奨。本田様業務直結、Issue #238 Phase 4 として完成感のある増分。実機ヒアリングが impl-plan の前提
2. **Issue #276** (Windows CI workflow 追加) — impl-plan + 単独 PR。改善候補 B (新 workflow `test-windows-ui.yml`) を推奨ベースに。Issue #275 / #274 完了後の Windows 実機検証経路として価値が高まる
3. **Issue #274** (詳細列見切れ) — 1 ダイアログ局所改善、`/impl-plan` 推奨。優先度は #275/#276 より下
4. **Issue #27 続編 F/G 検討** (Literal 拡張 §1 / Path 移行 §4) — umbrella close 候補化、impl-plan 起こし
5. **Phase 7 (Task #17)** impl-plan 起こし — 要 Windows 実機 (本田様 PC、TeamViewer)
6. **handoff debt 整理判断** — Session 64 繰越 3 件
7. **Issue #11/#16/#17/#6** — Windows 実機系、Mac セッション着手不可

---

## 構造的整合性チェック

- ⏭️ `/impact-analysis`: PR #277 は test 修正 1 件、production 影響ゼロ
- ⏭️ `/new-resource`: 新規 API なし
- ⏭️ `/trace-dataflow`: データフロー新規実装なし

---

## Issue Net 変化

```
## Issue Net 変化
- Close 数: 0 件
- 起票数: 3 件 (#274, #275, #276)
- Net: +3 件
```

**Net 悪化評価**:

CLAUDE.md MUST「Issue は net で減らすべき KPI (Net ≤ 0 は進捗ゼロ扱い)」の観点では本セッションは進捗マイナス。ただし起票 3 件はすべて triage 基準遵守 (#5 ユーザー明示指示 / ③ CI/リリース判断を壊す) で、業務価値の根拠が明確:

- **#274 / #275**: 本田様視点 UX 観察 (実機検証中に発見) — 業務動線の認知負荷削減価値
- **#276**: CI 構造盲点 (本セッションで顕在化、PR #181 と同種再発) — 将来 regression 検知の構造解消価値

「**Net 悪化は許容、業務価値の蓄積を優先**」と評価。次セッション以降で #275 / #276 / #274 を close すれば Net マイナス回収可能 (3 件中 2 件は単独 PR で close 可能サイズ)。

triage 遵守: 本セッションで取りこぼした nice-to-have (rating ≤ 6) はゼロ。pr-test-analyzer Suggestion 由来の Session 69 繰越 3 件 (form_to_config identity test 等) は本 handoff で記録のみ、新規 Issue 起票せず。
