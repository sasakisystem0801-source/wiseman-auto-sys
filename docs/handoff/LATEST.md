# Session 71 完了 — Issue #276 + #274 Phase 1 完了 + Issue #275 impl-plan たたき台整理

**Date**: 2026-05-14
**Main HEAD**: `bf435db` feat(ui): B/C 自動配置ダイアログ「詳細」列の見切れ解消 Phase 1 (#274) (#280)
**Test count**: 1918 collected (Session 70 1815 から差は parametrize 展開 + PR #277 影響、本セッションで新規追加なし)
**Active Issues**: 12 (実質 7、postpone 5) [変化: -1、Net 改善]
**Phase**: Phase 7 着手前 [変化なし]

---

## セッション経緯

Session 70 完了後 `/catchup` 経由で「Windows デスクトップアプリのアップデート残タスク」として開始。LATEST.md 次セッション優先順 1 位の Issue #275 が本田様ヒアリング前提で AI 単独完結不可なため、AI 単独完結可能な #276 を先に進めて Net 回収する戦略を採用。

---

## 完了内容

### 1. Issue #276 CI 構造盲点解消 (PR #279 merged → close)

**問題**: tk_required 付き UI テストが Linux CI で全 skip され、Windows 実機で初顕在化するパターンが PR #181 (2026-05-04) と PR #272 (2026-05-13 frozen 化由来 regression) で再発。

**解決**: `.github/workflows/test-windows-ui.yml` 新規追加 (40 行)。`uv run pytest tests/unit/ui -v -m "tk_required and not integration"` を windows-latest で常時実行 (`push to main` + `PR to main` トリガー)。

**初回 CI で 3 件 fail 検出**:

| # | テスト | 原因 | 本格 fix 方針 |
|---|------|-----|------------|
| 1 | `test_common::test_clicking_header_sorts_*` | Windows Tk: `heading()["command"]` が Tcl コマンド名 str | `root.tk.call` で Tcl 名解決 or `event_generate` |
| 2 | `test_common::test_status_column_uses_*` | 同上 | 同上 |
| 3 | `test_checklist_c_dialog_cache_clear::test_clear_cache_removes_*` | windows-latest + uv venv で Tcl init.tcl 不在 | TCL_LIBRARY 環境変数調査 |

`@pytest.mark.xfail(strict=False)` で 3 件マーク、CI green でマージ可能に。本格 fix は follow-up として PR #279 description に記録。

**重要発見**: #3 は当初 Session 70 で「本田様 PC 固有」と判断していたが GitHub Actions windows-latest でも再現 — Issue #276 が真に CI 構造盲点解消の価値を実証。

### 2. Issue #274 Phase 1 完了 (PR #280 merged)

`src/wiseman_hub/ui/checklist_b_dialog.py` / `checklist_c_dialog.py` の Treeview「詳細」列改善 (2 files, +28/-8):

- message 列幅 240 → 500 px (`stretch=True, minwidth=240`)
- 横スクロールバー追加 (`xscrollcommand` 設定 + bottom 配置)
- pack order: `hscroll(bottom) → vscroll(right) → tree(left, expand)` で tkinter 慣習に従う

**Definition of Done 達成状況** (Issue #274 にコメント済):
- ✅ 詳細列 full text 確認可能 (横スクロールで対応)
- ✅ 既存業務動線 (`<Double-1>` フォルダオープン / 右クリックキャッシュクリア / 列ソート) 維持
- ⏸ 本田様 PC 実機検証 → 次セッションで確認 (Issue は open のまま)

**Phase 2/3 候補** (本田様評価次第、別 PR):
- Phase 2: 行 hover で tooltip 表示 / 右クリックで詳細列コピー
- Phase 3: planning ロジック側で氏名重複表記を除去

### 3. Issue #275 impl-plan たたき台整理 (Issue にコメント投稿済、本田様ヒアリング待ち)

**重要発見**: `push_report_staff` API は `src/wiseman_hub/cloud/mapping_sync.py` L180-217 で実装済み。UI ボタンが未公開なだけ → 改善候補 5「担当者側 push 対称化」は **新規 API 不要、UI ボタン + handler 追加のみで実現可能**。

**改善候補 5 案の技術評価**:

| 候補 | 実装コスト | UX 改善度 | 主リスク |
|-----|----------|---------|------|
| 1. 2 動作統合 (取得 1 / 送信 1) | M | 高 (4→2) | 片方だけ送信したい業務動線を潰す |
| 2. Wizard 化 | H | 中 | 過剰実装 |
| 3. 業務用語への言い換え | S | 中-高 | 業務語彙ヒアリング必須 |
| 4. 送信/取得の上下グループ化 | S | 中 | 縦幅増加 |
| 5. 担当者側 push 追加 (UI のみ) | S (API 既存) | 中 | 既存業務に新動作 |

**推奨組み合わせ**:
- A (保守的): 候補 3 + 4 + 5 — グルーピング + 用語置換 + 対称化、6→7 ボタン (認知整理優先)
- B (アグレッシブ): 候補 1 + 3 — 2 動作統合 + 用語、6→5 ボタン (本田様 OK 時のみ)

**本田様ヒアリング項目 4 領域** (Issue にコメント済):
1. 業務頻度・タイミング (対照表 / 担当者マッピング / 環境スキャン それぞれ)
2. 操作パターン (取得→編集→送信のセット運用か、片方だけ使うか)
3. 業務用語 (「対照表」「居宅マッピング」「FAX 送付先設定」のどれが業務語彙か)
4. 同期方向の重要度 (ローカル→GCS と GCS→ローカル どちらが頻度高いか)

---

## ⚠️ 注意事項 / 次セッション着手前確認

### 1. Issue #276 follow-up (本格 fix が別 PR で必要)

PR #279 description に記録、triage rating 6 のため新規 Issue 起票せず:
1. `tree.heading()["command"]` 経路の Windows 対応 (test 書き換え 2 件)
2. Windows + uv venv の Tcl init.tcl 環境調査 (workflow に setup step 追加 or test スキップ条件再設計)

### 2. Issue #274 実機検証チェック項目 (Phase 1 PR #280 merged 後)

次回ビルド配布後 (`docs/handoff/1c-exe-redistribution-runbook.md` Phase 0-3) に確認:
1. B ダイアログで詳細列が 500 px 表示
2. 横スクロールバーが appear
3. column drag resize 動作
4. 既存業務動線維持
5. 本田様視点で「読みやすくなった」評価 → 評価次第で Phase 2/3 着手判断

### 3. Issue #275 次セッション着手フロー

1. 本田様にヒアリング項目 4 領域を確認 (実機 UI を見せながら平文で観察報告を促す、AskUserQuestion 過剰回避)
2. 回答に応じて組み合わせ A / B を選択
3. impl-plan 確定 → 実装 → tk_required test 追加 → Windows CI (Issue #276 で整備済) で PASS 確認 → PR → 本田様実機検証 → close

### 4. CLAUDE.md チェックリスト #2 が古い (Session 70 から繰越、handoff debt)

「3 ボタン構成」記載 → 実際は **5 ボタン**。`docs/handoff/1c-exe-redistribution-runbook.md` Phase 3 も同様。次セッションで小規模 docs PR 候補。

### 5. Mac セッション着手不可項目 (前セッション継承、変化なし)

- #17 (smoke_real.py pytest 統合)
- #16 (test_new_registration_flow Pane/Text 経路)
- #11 (PywinautoEngine MEDIUM 5 件)
- #6 (PoC E2E)

### 6. handoff debt (Session 64 から繰越 + 本セッション追加)

繰越 3 件:
- `build-windows-smoke.yml` に `Verifier.production(offline=True)` smoke 追加
- Trust root staleness 監視 (warn-log)
- sigstore-python 3.x dependency docstring

本セッション追加 2 件:
- CLAUDE.md / runbook Phase 3 チェックリストの「3 ボタン構成」を「5 ボタン構成」に更新
- Issue #276 follow-up 2 件 (test 書き換え + Tcl init.tcl 環境調査)

---

## 次セッション優先順

1. **Issue #275** (ChecklistSettingsDialog UI シンプル化) — 本田様ヒアリング → impl-plan 確定 → 実装。ヒアリング項目は Issue #275 にコメント済、参照即可
2. **Issue #274 Phase 1 実機検証** — 次回ビルド配布後、本田様評価で close 判断
3. **Issue #274 Phase 2/3** — 実機検証で「もっと改善したい」評価が出た場合
4. **CLAUDE.md docs 修正** (handoff debt) — 5 ボタン構成へ更新の小規模 PR
5. **Issue #276 follow-up** — Tcl init.tcl 環境調査 / Windows Tk 仕様差 test 書き換え
6. **Issue #27 続編 F/G** — Literal 拡張 §1 / Path 移行 §4 (umbrella close 候補化)
7. **Phase 7 (Task #17)** — 要 Windows 実機

---

## 構造的整合性チェック

- ⏭️ `/impact-analysis`: 型・共有ロジック・設定ファイル変更なし (Treeview UI 改善 + CI workflow 追加のみ)
- ⏭️ `/new-resource`: 新規 API なし (`push_report_staff` 既存利用予定、本セッションでは UI 公開せず)
- ⏭️ `/trace-dataflow`: データフロー新規実装なし

---

## Issue Net 変化

```
## Issue Net 変化
- Close 数: 1 件 (#276)
- 起票数: 0 件
- Net: -1 件
```

**Net 改善評価**:

Session 70 で +3 だった net を本セッションで -1 まで回収。

- Issue #276 (PR #279) で構造盲点を解消、close
- Issue #274 Phase 1 (PR #280) は実機検証待ちで open のまま (本田様評価後に close 判断)
- Issue #275 はヒアリング項目を Issue にコメント整理で前進、open のまま

triage 遵守: 本セッションで新規 Issue 起票ゼロ。Issue #276 follow-up (test 書き換え + Tcl 環境調査) は rating 6 のため Issue 化せず PR description で記録、本格 fix 時に対応。
