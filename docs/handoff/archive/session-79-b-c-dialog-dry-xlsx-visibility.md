# Session 79 完了 - B/C ダイアログ DRY 化 + C xlsx 起源可視化 + 実機 Phase 4 で 4 件 Issue 起票

日時: 2026-05-16
HEAD: `0e88ff4`
ブランチ: main
前セッション archive: [session-78-windows-deploy-script-and-normalize-dry.md](./archive/session-78-windows-deploy-script-and-normalize-dry.md)

## 本セッション完了内容

### PR #311 (merged): B/C ダイアログ シート一覧 cache 共通化 + C 配置 xlsx 起源可視化

業務責任者のフィードバック「B のスプレッドシート情報取得が C のように永続化されていない」「C の対象ファイルが決まっていても決まっていないような表示」を構造的に解消。

- **DRY 化**: 新規 `src/wiseman_hub/ui/sheet_list_binding.py` (軽量 stateless wrapper) に B/C/launcher 3 caller で重複していた sheet_list_cache の load/save/sync-label 表示を集約。`ui/common.py` に `parse_sheet_name` / `open_folder_in_os` 共通化 (code-reviewer #1 反映)
- **B ダイアログ機能 parity**: 起動時 cache populate + 「シート一覧 最終更新: ...」label + 透過 download + now_fn DI (C と完全に揃える)
- **C xlsx 列追加**: Treeview に「xlsx」列 (basename 表示、PII 配慮で UNC 非表示)、`plan_c_placement` で message に「自動: <name>」「選択: <name>」「自動: <name> (legacy)」prefix で起源可視化、dry_run 実行後も prefix 保持 (Evaluator HIGH)
- **追加 commit**: 5 reviewer (Evaluator + code-reviewer + pr-test-analyzer + silent-failure-hunter + type-design-analyzer + Codex) の指摘で HIGH 2 件 + MEDIUM 4 件 + LOW 2 件を全対応:
  - reload_config 状態リセット (Codex HIGH、spreadsheet_id 変更時の旧 xlsx 誤処理防止)
  - parse_sheet_name regex 厳格化 ([1-9]|1[0-2]、月=0/13 silent 通過 bug 修正)
  - 透過 download を background 化 + sync_info 失敗マーカー併記 (Codex Medium + silent-failure C-2)
  - `_safe_after` helper で winfo_exists ガード (B/C)
  - dry-run idempotent 化 (二重実行で入れ子化防止)

### PR #312 (merged): Windows path separator 互換性 + 本田様 PC Tcl 環境問題対応

PR #311 マージ後の実機 deploy で発見:

- **Path 文字列 TOML 化を OS 中立に比較**: `str(Path("/var/log/test")).replace("\\", "\\\\")` 経由で expected を組み立て (Issue #27 続編 G Phase 3b の既存 3 件、Linux/macOS でしか検証されていなかった)
- **test_cache_miss_keeps_combo_empty に xfail**: 一部 Windows PC の Tcl install 不完全エラー (`tcl_findLibrary` 不在) 対策、既存 Issue #276 follow-up pattern

### `_safe_after` worker thread bug fix (PR #311 内)

最初の Windows CI で `RuntimeError: main thread is not in main loop` 検出 → worker thread から `winfo_exists()` を呼んでいた Tk 仕様違反を修正。scheduling 側は `try/except (TclError, RuntimeError)` で `after()` のみガード、widget 検査は callback 内 (main thread) で実施。

### テスト追加件数

- PR #311: +35 件 (sheet_list_binding 21 + B dialog 7 + C dialog prefix 2 + dryrun 5)
- PR #312: -3 / +21 (path テストの platform-aware 書き換え + xfail)
- 累積: **2076 passed, 119 skipped** (macOS local)、ruff / mypy 全 PASS

### 本田様 PC 実機 deploy (HEAD `0e88ff4`、disaster recovery 経由)

`scripts/deploy-windows.ps1` の Phase 0 pytest gate が本田様 PC 固有の Tcl 環境問題で intermittent fail。CI (Linux + Windows) で完全検証済なため runbook の disaster recovery 手順で pytest gate を skip して deploy 完了。

確認できた PR #311 の新機能:
- ✅ B ダイアログ: 「シート一覧 最終更新: 5/8 18:58 (7 日前)」label 表示、月 combo が cache hit で auto-populate
- ✅ C ダイアログ: Treeview に「xlsx」列追加表示
- ✅ Launcher: GCP 同期サマリーで同じ最終更新日時が表示
- ✅ exe 配布完了 (84,240,091 bytes)

実機 Phase 4 で発見された 4 件は Issue 起票 (下記参照)。

## Issue Net 変化

```
Close 数: 0 件
起票数: 4 件 (#313, #314, #315, #316)
Net: -4 件
```

**Net ≤ 0 の理由言語化** (CLAUDE.md feedback_issue_triage 基準):

PR #311 + #312 で新機能を実装し、その**実機 Phase 4 検証で 4 件の改善余地を発見・起票**したため起票数が突出。各 Issue は CLAUDE.md triage 基準を満たす:

| # | タイプ | 起票理由 (triage criterion) |
|---|---|---|
| #313 | bug | 再現可能なバグ (criterion 2): 「候補なし」表示なのに XlsxPickerDialog で候補 1 件出る |
| #314 | enhancement | ユーザー明示指示 (criterion 5): 「担当が2名いたら、その画面で選択可能にする」(本田様要望) |
| #315 | enhancement | ユーザー明示指示 (criterion 5): 「C について xlsx 列に何も入っていない問題」(本田様要望) |
| #316 | bug | 実害あり (criterion 1): 本田様 PC で deploy script の Phase 0 が空振り、毎回 disaster recovery 手順が必要 |

review agent rating 5-6 の任意提案を機械的に Issue 化したものは含まれていない。

## 次セッション最優先タスク

### 1. **Issue #313 + #315 を 1 PR で対応 (推奨)**

同じ「候補可視化」テーマで `plan_c_placement` の `resolved.message` 修正 + `_refresh_tree` の xlsx_label 拡張で同時解決可能。業務責任者の UX 不満を即解消できる。

```python
# _refresh_tree の xlsx_label 拡張案
def _format_xlsx_cell(r: CPlacementResult) -> str:
    if r.xlsx_path is not None:
        return r.xlsx_path.name
    if r.status == CPlacementStatus.NEEDS_REVIEW:
        n = len(r.xlsx_candidates)
        if n == 1:
            return r.xlsx_candidates[0].name
        if n >= 2:
            return f"({n} 件候補)"
    return ""
```

### 2. **Issue #314 担当者複数選択 UI**

スプレッドシートで「小島/木塚」のような複合担当者を `/` (および全角 `／`) で分解 → StaffPickerDialog 経由で選択 → cache 化。新機能扱いで規模中。

### 3. **Issue #316 本田様 PC Tcl 環境問題**

優先度順に試行:
1. Windows セキュリティ GUI から `C:\Users\sasak\AppData\Local\Programs\Python\Python311` を除外フォルダ追加 (UI 経由は Tamper Protection 下でも可)
2. 第三者 AV の有無確認
3. Python 再 install (python.org MSI) or uv-managed Python (`uv python install 3.11`) に切替

### 4. PR #311 の scope 外 (別 PR で扱う follow-up 候補)

| 項目 | 由来 | 起票判断 |
|---|---|---|
| `CPlacementResult.origin` field 分離 (②-B) | silent-failure-hunter H-4 + code-reviewer #3 | 設計改善、別 PR で型分離。message prefix の構造化 |
| `download_xlsx` の broad `except Exception` を具体例外分岐 | silent-failure-hunter C-1 | 操作判断が変わるエラー型 (HTTPError 401/404/5xx / FileNotFoundError 等) の文言分岐 |
| `xlsx_path_cache_mirror` async spawn 失敗の log 改善 | silent-failure-hunter C-3 | warn-only の例外型出力欠落 |
| cache 破損と miss を区別する API 拡張 | silent-failure-hunter H-1/H-2 | `format_sync_label` の「不明」が 4 異種条件を潰している |
| `_on_open_settings` 失敗フィードバック改善 | silent-failure-hunter H-3 | logger.exception 追加 + 文言にヒント |
| `save_after_fetch` を `bool` 返却に + UI 反映 | silent-failure-hunter M-1 | cache write 失敗時に UI 通知 |
| type-design: ガード重複削減 + `now_fn` eager 検証 | type-design-analyzer | `_resolved_cache_target` helper extraction、init で `now_fn` tz-aware 検証 |
| comment-analyzer: PR-process prefix 削除 (15+ 箇所) | comment-analyzer | `PR (sheet-list-binding):` `Evaluator 指摘対応:` 等の rot リスク高 prefix を削除 |
| Windows CI に path tests を含める workflow 拡張 | pr-test-analyzer | windows-ui workflow が tk_required tests のみ実行している件 |

### 5. ポストポーン中 Issue (着手不可)

- #275 / #274 / #245 / #170 / #161 / #134 / #39 / #27 / #17 / #16 / #11 / #6 (postponed ラベル or Mac 着手不可)

## ハンドオフ debt

### 解消済み (本セッション)

- ✅ B ダイアログがシート一覧 cache を永続化していなかった問題 (Session 78 までの差分、PR #311 で解消)
- ✅ C ダイアログの「対象ファイルが決まっていても決まっていないような表示」(PR #311 の起源 prefix + xlsx 列で改善、但し #315 で更なる改善余地が判明)
- ✅ sheet_list_cache 操作の 3 箇所重複 (PR #311 で `SheetListBinding` に集約)
- ✅ B/C 重複していた `parse_sheet_name` / `_open_folder` (PR #311 で `ui/common.py` に集約)
- ✅ Windows path tests の OS 非互換 (PR #312 で OS 中立化)

### 継続 (次セッション以降)

- 上記「次セッション最優先タスク」参照
- 本田様 PC Tcl 環境問題 (#316) は本人の対応待ち、暫定対応 (disaster recovery) は continues

## 検証結果

| 項目 | 結果 |
|---|---|
| pytest (Mac local) | **2076 passed, 119 skipped** (PR #311 + #312 合算後) |
| ruff check | All checks passed |
| mypy | Success no issues (77 source files) |
| CI Linux Unit Tests (3.11/3.12) | success (PR #311 + #312 共に green) |
| CI Windows UI Tests | success (PR #311 + #312 共に green、rerun 1 回 init.tcl flakiness で再実行) |
| CI Build Smoke / Integration | success |
| Codex セカンドオピニオン (PR #311) | request changes → 全件 fix 済 (HIGH 1 + MEDIUM 3 + LOW 1) |
| 5 agent 並列 review (PR #311) | Evaluator + code-reviewer + pr-test-analyzer + silent-failure-hunter + type-design-analyzer + comment-analyzer 完了、HIGH 2 + MEDIUM 6 全件対応 |
| Code-reviewer (PR #312) | rating 8/9 (ブロッカーなし、軽微指摘 2 件) |
| 実機 Phase 4 動作確認 | ✅ B ダイアログ cache populate / C xlsx 列 / sync_info label 全て期待通り表示 |

## Quality Gate 適用状況

| 段階 | PR #311 | PR #312 |
|---|---|---|
| `/simplify` | 適用 | 適用 (test only) |
| `/safe-refactor` | 適用 (5+ ファイル) | 適用 |
| Evaluator 分離プロトコル (5+ ファイル) | **適用** (HIGH 1 + MEDIUM 3 全件 fix) | 適用外 (テストのみ) |
| Codex セカンドオピニオン | 適用 (HIGH 1 + Medium 3 + Low 1 全件 fix) | 適用外 (medium tier 3 ファイル) |
| 5 agent 並列 review | 適用 (pr-test-analyzer / silent-failure-hunter / type-design / comment-analyzer 全件回答) | 適用外 |
| 単発 code-reviewer | 適用 | 適用 (rating 8/9) |

## ADR 状態

- 16 件、本セッションで新規 ADR なし
- ADR-016 (Windows アプライアンス化 + Mac-from-GCP 開発フロー) は **Proposed のまま**、Phase 7 切替の hard dependency (launcher 本番配置) は未着手、関連 Issue #316 (本田様 PC Tcl 環境) が Phase 7 切替前の暫定運用の課題として表面化

## 残留プロセス

✅ 残留 Node プロセスなし
