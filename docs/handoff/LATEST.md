# Session 71 完了 — Issue #276 + #274 Phase 1 + #282 完了 + Issue #275 impl-plan たたき台

**Date**: 2026-05-14
**Main HEAD**: `9490e4a` feat(b): B 自動配置の月.pdf 探索を R<年> サブフォルダに対応 (#282) (#283)
**Test count**: 1979 collected (Session 71 開始時 1918 から +61、PR #283 で 43 件追加)
**Active Issues**: 11 (実質 6、postpone 5) [変化: -2、Net 改善]
**Phase**: Phase 7 着手前 [変化なし]

---

## セッション経緯

Session 70 完了後 `/catchup` 経由で「Windows デスクトップアプリのアップデート残タスク」として開始。LATEST.md 次セッション優先順 1 位の Issue #275 が本田様ヒアリング前提で AI 単独完結不可なため、AI 単独完結可能な #276 → #274 Phase 1 を先に進めて Net 回収する戦略を採用。`/handoff` 後、ユーザーから追加案件として「R7 サブフォルダ + 表記揺れ吸収」の Issue #282 を受領し、Codex review セカンドオピニオン経由で誤確定リスクを発見・修正してマージ。

---

## 完了内容

### 1. Issue #276 CI 構造盲点解消 (PR #279 merged → close)

`.github/workflows/test-windows-ui.yml` 新規追加 (40 行)。tk_required 付き UI テストを windows-latest で常時実行。初回 CI で 3 件 fail 検出 → `@pytest.mark.xfail(strict=False)` でマーク。

**重要発見**: `test_clear_cache_*` の Tcl init.tcl 不在は Session 70 で「本田様 PC 固有」と判断していたが GitHub Actions windows-latest でも再現 — CI 構造盲点解消の価値を実証。

### 2. Issue #274 Phase 1 完了 (PR #280 merged、Issue は実機検証待ちで open)

`src/wiseman_hub/ui/checklist_b_dialog.py` / `checklist_c_dialog.py` の Treeview「詳細」列改善 (2 files, +28/-8):
- message 列幅 240 → 500 px (`stretch=True, minwidth=240`)
- 横スクロールバー追加 (`xscrollcommand` 設定 + bottom 配置)

### 3. Issue #275 impl-plan たたき台 (Issue にコメント投稿済、本田様ヒアリング待ち)

**重要発見**: `push_report_staff` API は `mapping_sync.py` L180-217 で実装済み (UI 未公開のみ)。改善候補 5 「担当者側 push」は API 追加不要。

改善候補 5 案 + 推奨組み合わせ A/B + 本田様ヒアリング項目 4 領域を Issue #275 にコメント投稿。

### 4. Issue #282 R<年> フォルダ対応 + 表記揺れ吸収 (PR #283 merged → close)

`src/wiseman_hub/pdf/checklist_b.py` の `find_month_pdf` を改修 (2 files, +446/-9):

- 旧構造 `monitoring_dir/<月>.pdf` 維持 + 新構造 `monitoring_dir/R<年>/<月>.pdf` 対応
- `_parse_year_folder_name` (NFKC 正規化 + 正規表現) で R 表記揺れ 9 パターン吸収:
  - R7 / R７ / Ｒ7 / Ｒ７ (全角/半角)
  - R 7 / R　7 (スペース挿入)
  - R.7 / R-7 (区切り文字)
  - r7 (小文字)
- R 数字降順で最新年から走査、複数年なら R8 → R7 → R6 順
- 43 件のテスト追加

**Codex review セカンドオピニオン経由で誤確定リスクを発見・修正**:
- High-1: `_match_month_pdf_in_dir` が AMBIGUOUS とゼロを潰す → 3-tuple 化 + 早期 return
- High-2: 年フォルダ内 AMBIGUOUS で古い年に誤フォールバック → 早期 return
- High-3: `iterdir` の OSError 未捕捉 → try/except + PII フリー warn ログ
- Medium-1: 同一論理年で複数物理フォルダ (R7 + Ｒ７) 非決定的 → year_groups dict で AMBIGUOUS
- Low-2: テスト乖離修正 + 新規 AMBIGUOUS テスト 5 件追加

---

## ⚠️ 注意事項 / 次セッション着手前確認

### 1. Issue #276 follow-up (本格 fix が別 PR で必要)

PR #279 description に記録、triage rating 6 のため新規 Issue 起票せず:
1. `tree.heading()["command"]` 経路の Windows 対応 (test 書き換え 2 件)
2. Windows + uv venv の Tcl init.tcl 環境調査 (workflow に setup step 追加 or test スキップ条件再設計)

### 2. Issue #274 実機検証チェック項目 (Phase 1 PR #280 merged 後)

次回ビルド配布後 (`docs/handoff/1c-exe-redistribution-runbook.md` Phase 0-3) に確認:
1. B ダイアログで詳細列が 500 px 表示
2. 横スクロールバー appear
3. column drag resize 動作
4. 既存業務動線維持
5. 本田様視点で「読みやすくなった」評価 → 評価次第で Phase 2/3 着手判断

### 3. Issue #282 実機検証チェック項目 (PR #283 merged 後)

次回ビルド配布後に確認:
1. `monitoring_subfolder/R7/<月>.pdf` 構造の利用者で B 配置成功
2. 旧構造 (直配置) 利用者で regression なし
3. 表記揺れフォルダ (R7 以外、もしあれば) で配置成功
4. AMBIGUOUS 検出パターン (同年複数フォルダ等) で人間判断 UI が出る

### 4. Issue #275 次セッション着手フロー

1. 本田様にヒアリング項目 4 領域を確認 (実機 UI を見せながら平文で観察報告を促す、AskUserQuestion 過剰回避)
2. 回答に応じて組み合わせ A / B を選択
3. impl-plan 確定 → 実装 → tk_required test 追加 → Windows CI で PASS 確認 → PR → 本田様実機検証 → close

### 5. Issue #282 Codex review 残指摘 (本 PR scope 外、triage rating 4-6 で Issue 化せず)

- M2 (symlink): NAS 運用上稀、コメント追加程度で別 PR 可
- M3 (大量ファイル materialize 性能): 現状規模で問題なし
- L1 (将来表記 R7年/令和7/2025): 実機発見次第対応 (PR description に記載)
- L3 (`plan_b_placement` メッセージに full path PII): 既存コード起因、別 Issue 案件

### 6. CLAUDE.md チェックリスト #2 が古い (Session 70 から繰越、handoff debt)

「3 ボタン構成」記載 → 実際は **5 ボタン**。`docs/handoff/1c-exe-redistribution-runbook.md` Phase 3 も同様。次セッションで小規模 docs PR 候補。

### 7. Mac セッション着手不可項目 (前セッション継承、変化なし)

- #17 (smoke_real.py pytest 統合)
- #16 (test_new_registration_flow Pane/Text 経路)
- #11 (PywinautoEngine MEDIUM 5 件)
- #6 (PoC E2E)

### 8. handoff debt (Session 64 から繰越 + 本セッション追加)

繰越 3 件:
- `build-windows-smoke.yml` に `Verifier.production(offline=True)` smoke 追加
- Trust root staleness 監視 (warn-log)
- sigstore-python 3.x dependency docstring

本セッション追加:
- CLAUDE.md / runbook Phase 3 チェックリストの「3 ボタン構成」を「5 ボタン構成」に更新
- Issue #276 follow-up 2 件 (test 書き換え + Tcl init.tcl 環境調査)
- Issue #282 Codex 残指摘 4 件 (M2 symlink / M3 性能 / L1 将来表記 / L3 PII path message)

---

## 次セッション優先順

1. **Issue #275** (ChecklistSettingsDialog UI シンプル化) — 本田様ヒアリング → impl-plan 確定 → 実装。ヒアリング項目は Issue にコメント済、参照即可
2. **Issue #274 Phase 1 実機検証** — 次回ビルド配布後、本田様評価で close 判断
3. **Issue #282 実機検証** — 次回ビルド配布後、R7 構造の利用者で配置成功確認
4. **CLAUDE.md docs 修正** (handoff debt) — 5 ボタン構成へ更新の小規模 PR
5. **Issue #276 follow-up** — Tcl init.tcl 環境調査 / Windows Tk 仕様差 test 書き換え
6. **Issue #27 続編 F/G** — Literal 拡張 §1 / Path 移行 §4 (umbrella close 候補化)
7. **Phase 7 (Task #17)** — 要 Windows 実機

---

## 構造的整合性チェック

- ⏭️ `/impact-analysis`: 型・共有ロジック・設定ファイル変更なし (`_match_month_pdf_in_dir` の戻り値型は internal contract のみ変化、外部 API `find_month_pdf` の戻り値型は維持)
- ⏭️ `/new-resource`: 新規 API なし
- ⏭️ `/trace-dataflow`: データフロー新規実装なし

---

## Issue Net 変化

```
## Issue Net 変化
- Close 数: 2 件 (#276, #282)
- 起票数: 1 件 (#282)
- Net: -1 件
```

**Net 改善評価**:

Session 70 で +3 だった net を本セッションで -1 まで回収。

- Issue #276 (PR #279) で CI 構造盲点解消、close
- Issue #274 Phase 1 (PR #280) は実機検証待ちで open のまま
- Issue #275 はヒアリング項目を Issue にコメント整理、open のまま
- Issue #282 (PR #283) は本セッション中に起票 + Codex review 経由で誤確定リスク 3 件発見・修正 + close

triage 遵守: 起票は #282 のみ (基準 ① 実害 + ⑤ ユーザー明示指示、rating 8)。Codex review 残指摘 4 件 (M2/M3/L1/L3) は rating 4-6 で Issue 化せず PR description で記録。
