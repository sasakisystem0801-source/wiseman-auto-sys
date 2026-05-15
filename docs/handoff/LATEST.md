# Session 80 完了 - C 配置 xlsx 候補可視化 (#313/#315 close) + 本田様 PC Tcl 診断 (#316) + 担当者複数対応 T1 着手 (#314)

日時: 2026-05-16
HEAD (main): `dfedbb0`
進行中ブランチ: `feat/c-multi-staff-picker-314` (T1 commit `42680e3` 残置、PR 未作成)
前セッション archive: [session-79-b-c-dialog-dry-xlsx-visibility.md](./archive/session-79-b-c-dialog-dry-xlsx-visibility.md)

## 本セッション完了内容

### PR #318 (merged `f1a6c54`): xlsx 候補可視化 - 矛盾 message 解消 + Treeview 列件数表示

Session 79 実機 Phase 4 で発見された 2 件 (#313 bug + #315 enhancement) を「C 配置の xlsx 候補可視化」同一テーマで 1 PR にまとめて対応。両 Issue 本文にも 1 PR 想定が明記。

- **#313 fix (resolve_xlsx)**: scan_fallback 経路が fallback 件数を見ずに固定文言「候補なし、フォルダから選択してください」を返していた矛盾を、suggest_patterns hit と同じ「N 件候補あり、確認後に選択してください」分岐に統一。XlsxPickerDialog の候補リスト表示と Treeview 詳細列の整合性確保。
- **#315 enhancement (_format_xlsx_cell)**: NEEDS_REVIEW 行で xlsx 列が空欄だった件、module level に純粋関数を追加して状態別表示 (PENDING basename / NEEDS_REVIEW × {basename, "(N 件候補)", "(候補なし)"} / SKIPPED 空)。
- **テスト**: pdf 側 1 件追加 + 既存 1 件補強、ui 側 9 件新規 (Tk 不要 pure helper)
- **動作確認**: 2086 passed / ruff / mypy / flake8 全 clean
- **3 agent 並列 review (code/test/comment)**: 全員「マージ可」判定、comment-analyzer の Issue 番号陳腐化リスク指摘 → テスト docstring を WHY ベースに書き直し反映済

### PR #319 (merged `dfedbb0`): Tcl init.tcl 連発失敗 (Issue #316) の診断スクリプト + runbook 追記

本田様 PC で intermittent に発生する `_tkinter.TclError: Can't find a usable init.tcl` への AI 側対処。AV 動的スキャン干渉が過去事例での主因、根本対応は実機側操作必須のため Issue は OPEN 維持。

- **新規 `scripts/diagnose-tcl.ps1`**: 5 セクション自動診断 (Python install path / `[System.IO.File]::ReadAllBytes` 5 回 read / `tk.Tk()` 10 回起動 / Windows Defender ExclusionPath / 第三者 AV プロセス検出)
- **runbook 追記**: 「🔬 Tcl init.tcl 連発失敗時の対処」セクション (Step 0-4: 診断 / Windows セキュリティ GUI 除外 / 第三者 AV / Python 再 install / uv-managed Python 切替) + トラブル早見表 1 行追加
- **`deploy-windows.ps1` 修正**: Phase 0-4 で pytest 出力を `New-TemporaryFile` 経由捕捉、TclError 検出時のみ diagnose-tcl.ps1 への誘導 + `-SkipTests` 暫定回避メッセージ表示 (fail-closed 維持)
- **review 反映**: silent-failure-hunter CRITICAL (`ForEach-Object` 内 `catch` の `$_` 上書きバグ → `$attempt = $_` 退避) / code-reviewer Important (AV プロセス false positive 注記 / backtick PS escape) / comment-analyzer Critical (「最有力仮説」緩和 / sasak ハードコード排除 / 業務責任者向け代替経路) 計 11 件全反映

### 進行中: Issue #314 担当者複数 (`/` 区切り) 対応の担当者選択 UI — T1 完了

`feat/c-multi-staff-picker-314` ブランチで `42680e3` commit 済 (push 済、PR 未作成):

- `parse_multi_staff(staff: str) -> list[str]`: 半角 `/` + 全角 `／` 区切り分解、NFKC ベース dedupe、元出現順保持
- `staff_choice_cache_key(staffs, year, month) -> str`: normalize_lookup_key sort + `|` 区切り (TOML quote 回避)
- テスト 13 件追加 (36 passed)

`/impl-plan` で計画策定 → `/codex` セカンドオピニオン (判定: 修正必須、High 4 + Medium 4 + Low 3) を全て計画に反映済。**残り T2-T10 が次セッションタスク**。

## Issue Net 変化

```
Close 数: 2 件 (#313, #315)
起票数: 0 件
Net: -2 件 (進捗あり)
```

Net ≤ 0 を満たす理由: 実害ある bug + ユーザー明示要望の Issue を実装で解消。新規起票は本セッションでは発生せず (Issue #316 は前セッション起票分の部分対応、open 継続)。

## 次セッション最優先タスク

### 1. **Issue #314 T2-T10 継続** (`feat/c-multi-staff-picker-314` ブランチ)

T1 (parse_multi_staff + staff_choice_cache_key + 13 tests) は commit `42680e3` で完了済。残りタスク:

| # | 内容 | 影響ファイル |
|---|---|---|
| T2 | `CPlacementStatus.NEEDS_REVIEW_STAFF` + 4 dict (LABEL/SHORT_LABEL/SORT_PRIORITY/SUMMARY_ORDER) 更新 | checklist_c.py + checklist_c_dialog.py |
| T3 | `CPlacementResult.staff_candidates: list[str]` フィールド | checklist_c.py |
| T4 | `plan_c_placement` の staff 解決を `parse_multi_staff` → `staff_choice_cache` lookup → 単独/複数/部分 hit 分岐 | checklist_c.py |
| T5 | `ChecklistConfig.staff_choice_cache: dict[str,str]` + TOML I/O (value は **normalize_lookup_key 形式**、Codex High #1) | config.py |
| T6 | 新規 `StaffPickerDialog` (radiobutton + 「記憶する」chk + キャンセル) | src/wiseman_hub/ui/staff_picker_dialog.py |
| T7 | ChecklistCDialog の `_on_row_double_click` で status による dispatch 明示分岐、選択 staff で `dataclasses.replace(row, staff=...)` 再 plan | checklist_c_dialog.py |
| T8 | `_format_xlsx_cell` に NEEDS_REVIEW_STAFF 対応、部分 hit は「(担当者 N 名 / 未登録あり)」 | checklist_c_dialog.py |
| T9 | unit tests (plan_c_placement 4 分岐 / TOML round-trip / cache hit / 全 enum 列挙 / 部分 hit message) | test_checklist_c.py + test_config.py |
| T10 | StaffPickerDialog pure helper + `_format_xlsx_cell` 新分岐 + dispatch 回帰テスト | test_staff_picker_dialog.py (新規) + test_checklist_c_dialog_xlsx_cell.py |

**Codex review High 4 件は計画反映済、実装時に必ず確認**:
- `staff_choice_cache` value は **normalize_lookup_key 形式** (表示名ではない、表記揺れ・同姓耐性)
- 再 plan は **`dataclasses.replace(row, staff=selected)` で row copy** (元 row 不変)
- 解決順序: parse → staff_choice_cache lookup → selected staff で通常 xlsx 解決
- 「一部 hit」は miss した未登録者名を message / UI に明示、選択肢 1 件でも自動確定しない

### 2. **Issue #316 実機対処待ち** (本田様 PC、AI 着手不可)

`scripts/diagnose-tcl.ps1` を本田様 PC で 1 度実行してもらい、結果を Issue #316 にコメント。出力に応じて runbook Step 1-4 (Windows セキュリティ GUI 除外 / 第三者 AV / Python 再 install / uv-managed Python) を順試行。改善後に Issue close 判断。

### 3. ポストポーン中 Issue (着手不可、ユーザー明示指示なき限り無視)

#245 / #170 / #161 / #134 / #39 (postponed ラベル、再開条件は各 Issue コメント参照)

### 4. active 残 Issue (#314 完了後の候補、優先順)

- #274 enhancement: B/C 自動配置ダイアログ「詳細」列の見切れ
- #275 enhancement: ChecklistSettingsDialog GCP 同期ボタン UI シンプル化

## ハンドオフ debt

### 解消済み (本セッション)

- ✅ Issue #313 「候補なし」表示なのに XlsxPickerDialog で候補 1 件出る不整合 (PR #318 で resolve_xlsx fallback 経路の message 分岐)
- ✅ Issue #315 C ダイアログ Treeview xlsx 列が NEEDS_REVIEW 行で常に空 (PR #318 で `_format_xlsx_cell` 状態別表示)
- ✅ Issue #316 AI 側対処 (PR #319 で diagnose-tcl.ps1 + runbook、業務責任者が AI 不在でも進められる状態に)

### 継続 (次セッション以降)

- Issue #316 実機対処 (本田様 PC AV 設定、本人の対応待ち、暫定対応 `-SkipTests` で継続可能)
- Issue #314 T2-T10 (`feat/c-multi-staff-picker-314` で継続、T1 commit `42680e3` 押し済み)

## 検証結果

| 項目 | 結果 |
|---|---|
| pytest (Mac local, post PR #319 merged) | **2086 passed, 119 skipped** |
| pytest (Mac local, T1 commit 後) | **2099 passed, 119 skipped** (+13 件追加) |
| ruff check / mypy / flake8 | All clean (PR #318 / #319 / T1 全て) |
| CI Linux Unit Tests (3.11/3.12) | success (PR #318 / #319 共に green) |
| CI Windows UI Tests | success |
| CI Build Smoke / Integration | success |
| 3 agent review (PR #318) | code-reviewer / pr-test-analyzer / comment-analyzer 全員「マージ可」 |
| 3 agent review (PR #319) | silent-failure-hunter CRITICAL 1 + code-reviewer Important 2 + comment-analyzer Critical 4 全件反映 |
| Codex セカンドオピニオン (Issue #314 計画) | 修正必須 → High 4 + Medium 4 + Low 3 全件計画反映 |

## Quality Gate 適用状況

| 段階 | PR #318 (#313 #315) | PR #319 (#316) | T1 (#314) |
|---|---|---|---|
| `/simplify` | 適用相当 (4 ファイル局所修正) | 適用相当 (設定/PS) | スキップ (1 関数追加のみ) |
| `/safe-refactor` | 不要 (3 ファイル未満 src 側) | 適用 (3 ファイル新規/修正) | スキップ |
| Evaluator 分離プロトコル | 不要 (5 ファイル未満) | 不要 (新機能ではない) | T1-T10 完了時に発動 |
| Codex セカンドオピニオン | 不要 (medium tier) | 適用 (large tier の post-fix で実質代替) | **計画段階で実施済** |
| 並列 agent review | 3 並列 (code / test / comment) | 3 並列 (code / silent-failure / comment) | T1-T10 完了時 |
| Single code-reviewer | (上記の 1 部) | (上記の 1 部) | - |

## ADR 状態

- 16 件、本セッションで新規 ADR なし
- ADR-016 (Windows アプライアンス化 + Mac-from-GCP 開発フロー) は **Proposed のまま**。Issue #316 の Phase 0 pytest gate 問題は ADR-016 Phase 7 切替後の launcher 自動更新で根本解消想定だが、本セッションでは暫定運用 (disaster recovery 手動 + diagnose-tcl.ps1) で対応

## 残留プロセス

✅ 残留 Node プロセスなし
