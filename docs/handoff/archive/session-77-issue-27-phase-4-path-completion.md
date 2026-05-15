# Session 77 完了 — Issue #27 続編 G §4 Path 移行スコープ完遂 (PR-Debt2 + Phase 3a + Phase 3b、3 PR merged)

**Date**: 2026-05-15
**Main HEAD**: `89c75d7` feat(config): Phase 3b Path 型移行 (ReportStaffEntry.base_dir) — Issue #27 続編 G §4 (#305)
**Test count**: 1977 passed, 109 skipped (Mac uv、Phase 3 累積 +21 件 / PR-Debt2 5 + Phase 3a 10 + Phase 3b 12 - rename 2 / Phase 2b 1956 → 1977)
**Active Issues**: 12 (実質 7、postpone 5) [変化なし、Net 0]
**Phase**: Issue #27 §4 Path 移行スコープ完了 [§1 Literal 拡張 / §E 追加検討は残作業]

---

## セッション経緯

Session 76 完了状態から `/catchup` で再開。ユーザー指示「優先順にすすめて」「TeamViewer 接続可能タイミングがまだなので、それまでに出来ることを進めて」で配布前にできる作業を実行。

実装フロー:
1. debt #3 設計議論 (Path("") sentinel 維持 vs Optional[Path] 移行) → **Option C 採用** (sentinel 維持、Optional[Path] は別途検討、umbrella §G close 前提条件にしない)
2. Phase 3 全体 impl-plan 策定: PR-Debt2 (debt #2 解決) → Phase 3a (karte_root/fax_root) → Phase 3b (ReportStaffEntry.base_dir)
3. 各 PR で Quality Gate 4 段 (5 agent review + Codex セカンドオピニオン + Evaluator 分離) を実施
4. **3 PR 連続 merge**:
   - PR #303 (PR-Debt2): `_redraw` の `is_path_configured` gate
   - PR #304 (Phase 3a): karte_root / fax_root Path 化
   - PR #305 (Phase 3b): ReportStaffEntry.base_dir Path 化

ユーザー承認: 各 PR とも「このまま squash merge して」明示認可で merge 完了。

---

## 完了内容

### Issue #27 続編 G §4 Path 移行スコープ完了 (本セッションで Phase 3 = PR-Debt2 + 3a + 3b を完遂)

| Phase | PR | コミット | 対象 dataclass / field |
|-------|-----|---------|----------------------|
| Phase 1 | #296 | (前セッション) | AppConfig.log_dir / WisemanConfig.exe_path |
| Phase 2a | #298 | (前セッション) | PdfMergeConfig.input_dir / output_dir / ex_source_dir |
| Phase 2b | #301 | (前セッション) | PdfMergeConfig.facility_root_dir |
| **PR-Debt2** | **#303** | `0efbaff` | UI 経路 debt #2 (_redraw is_path_configured gate) |
| **Phase 3a** | **#304** | `e5353ca` | ChecklistConfig.karte_root / fax_root |
| **Phase 3b** | **#305** | `89c75d7` | ReportStaffEntry.base_dir |

これで config dataclass の **全 path field が Path 型統一達成**:
- `AppConfig.log_dir` / `WisemanConfig.exe_path`
- `PdfMergeConfig.input_dir / output_dir / ex_source_dir / facility_root_dir`
- `ChecklistConfig.karte_root / fax_root`
- `ReportStaffEntry.base_dir`

### PR #303 (PR-Debt2) — `_redraw` Label 表示問題解決 (2 files, +188/-10)

- `ui/ex_extractor_dialog.py:_redraw` で `is_path_configured(p) and p.exists()` の二段 gate
- Phase 2b evaluator HIGH 指摘 (`Path("")` の `str()` = `"."` 表示) を debt #2 解決
- 既存 helper `is_path_configured` 流用、新規プロパティ・helper 追加なし
- 新規テスト `TestRedrawUnsetPathLabel` 5 件 (`@pytest.mark.tk_required`)

#### Quality Gate 履歴
| 段階 | 結果 |
|------|------|
| code-reviewer | 設計合格 |
| pr-test-analyzer | APPROVE |
| comment-analyzer 8/10 | Critical 1 件 (comment rot) → 同梱 fix |
| silent-failure-hunter 7/10 | HIGH 1 件 (OSError catch) → scope 外、debt #4 |
| code-simplifier 4/10 | 現状維持推奨 |

### PR #304 (Phase 3a) — karte_root / fax_root Path 化 (9 files, +268/-33)

- `ChecklistConfig.karte_root` / `fax_root` を `str` → `Path` 化
- default UNC を **forward slash 表現** で OS 中立化 (Phase 2b 規約、LATEST.md 199 行)
- consumer 整合 (pdf/checklist_b / pdf/checklist_c / ui/checklist_settings_dialog)
- 新規 `TestIssue27PathMigrationPhase3a` 9 件 (8 基本 + backslash UNC 後方互換)

#### Quality Gate 履歴 (5+ ファイル発動の Evaluator 分離 + Codex 並列)
| 段階 | 結果 |
|------|------|
| code-reviewer | 設計合格 (Critical 1 件 tk_required marker → 同梱 fix) |
| pr-test-analyzer 8/10 | APPROVE |
| comment-analyzer 8/10 | Critical 1 件 (comment rot) → 同梱 fix |
| silent-failure-hunter | API Error 529、他 4 reviewer 代替 |
| code-simplifier 4/10 | 現状維持推奨 |
| **Codex NEEDS_MINOR** | Medium 2 件 (sentinel pattern / fixture) → 同梱 fix |

#### 反映済 review 指摘
- canonical sentinel gate (`str(p) if is_path_configured(p) else ""`) で `_on_scan_env` の CWD 誤スキャン silent 経路を防御
- 既存 fixture (`fax_root=str(tmp_path)`) を Path 直渡しに
- backslash UNC 後方互換テストを 3 reviewer 一致指摘で追加

### PR #305 (Phase 3b) — ReportStaffEntry.base_dir Path 化 (13 files, +307/-63)

- `ReportStaffEntry.base_dir` を `str` → `Path` (nested dataclass field)
- default は UNC を持たない (`Path()` = 未設定 sentinel、Phase 3a と扱いを変える)
- consumer 整合:
  - `cloud/mapping_sync.py`: GCS JSON 境界変換 (push: canonical sentinel pattern / pull: coerce_path)
  - `pdf/staff_path_scanner.py`: scan_candidates の guard を `is_path_configured` に
  - `pdf/checklist_c.py`: resolve_xlsx の guard を `is_path_configured + exists()` 二段 gate に
  - `ui/checklist_settings_dialog.py`: `_staff_to_toml` canonical sentinel + `_parse_staff_toml` coerce_path
- 新規 `TestIssue27PathMigrationPhase3b` 8 件 + GCS push/pull sentinel test 2 件 + type guard 2 件

#### Quality Gate 履歴 (5+ ファイル発動の Evaluator 分離 + Codex 並列)
| 段階 | 結果 |
|------|------|
| code-reviewer | APPROVE (信頼度≥80 指摘なし) |
| pr-test-analyzer 8.5/10 | MERGE 可、Important (a)(b) push/pull sentinel test 推奨 → **同梱追加** |
| silent-failure-hunter 8.5/10 | APPROVE (HIGH は debt #4 継続) |
| evaluator | APPROVE with low notes |
| **Codex NEEDS_MINOR** | Low: fixture 1 件 → 同梱 fix で APPROVE 相当 |

#### 反映済 review 指摘 (3 reviewer 一致)
- Codex Low fixture 修正
- Important (a) push: `Path("")` → JSON `""` の canonical sentinel pattern contract test
- Important (b) pull: JSON `""` → `Path("")` の round-trip 不変条件 test

---

## ⚠️ 注意事項 / 次セッション着手前確認

### 1. 次セッション最優先: **exe 配布実行** (継承、TeamViewer 接続待ち)

Session 76 → 77 で配布タイミングが成立しているが TeamViewer 接続未実施。本セッションで Phase 3 全体が完了したため、配布で反映する内容が**さらに増加**:

- ✅ Phase 2b (PR #301) merged
- ✅ **PR-Debt2 (PR #303) merged** (NEW)
- ✅ **Phase 3a (PR #304) merged** (NEW)
- ✅ **Phase 3b (PR #305) merged** (NEW)
- ⏭️ exe 配布 7 ステップ実行 (`docs/handoff/1c-exe-redistribution-runbook.md` Phase 0-5)

#### 実機検証 11 件 (PR-Debt2 + Phase 3a + Phase 3b 追加分を本セッションで追記)

| Issue / PR | 検証項目 |
|---|---|
| #274 Phase 1 | B/C ダイアログ詳細列 500px 表示 + 横スクロール |
| #282 | `monitoring_subfolder/R7/<月>.pdf` 配置成功 / 旧構造 regression なし |
| Launcher 5 ボタン (PR #285) | 5 ボタン表示確認、業務フロー順 |
| #27 続編 F Phase 2/2-b | `[app] log_level = "DEBUG"` を書いて Launcher 起動 |
| PR #294 trust root WARNING | "sigstore trust root EXPIRED 268+ days ago" log |
| PR #296 Path 型移行 Phase 1 | 既存 `config/default.toml` を Path 化 load_config が正しく解釈 |
| PR #298 Phase 2a | `pdf_merge` `input_dir` / `output_dir` / `ex_source_dir` round-trip |
| PR #301 Phase 2b | `pdf_merge.facility_root_dir` round-trip + `is_path_configured` gate |
| **PR #303 PR-Debt2** | ex_extractor の未設定時 Label が `"."` ではなく `(未設定)` 表示 |
| **PR #304 Phase 3a** | B/C ダイアログ `karte_root` / `fax_root` 表示 + 未設定時の `_on_scan_env` 早期 return |
| **PR #305 Phase 3b** | C ダイアログ report_staff round-trip + GCS push/pull 境界変換 |

所要時間: 30-45 分 (Phase 3 追加分で +5 分目安)。手順 1-6 は AI 伴走 (TeamViewer 経由 PowerShell)、手順 7 は本田様の確認も含む。

### 2. 新規 handoff debt (本セッション発見)

#### debt #4 (NEW): `Path.exists()` の OSError 未捕捉 (silent-failure-hunter HIGH、3 PR で継続指摘)

該当箇所 (Phase 3 全体で残存):
- `src/wiseman_hub/ui/ex_extractor_dialog.py:560-568` (_redraw、PR #303 で is_path_configured gate 追加済だが OSError catch は未対応)
- `src/wiseman_hub/ui/ex_extractor_dialog.py:117-121` (ExExtractorViewModel.can_run、`.exists()` 直呼び)
- `src/wiseman_hub/ui/ex_extractor_dialog.py:1002-1005` (_show_config_missing_modal)
- `src/wiseman_hub/pdf/ex_extractor.py:1130-1133` (extract_directory)
- `src/wiseman_hub/pdf/checklist_c.py:144,164,173` (resolve_xlsx 関連、PR #305 で `.exists()` 1 箇所新規追加)
- `src/wiseman_hub/pdf/staff_path_scanner.py:76,141` (scan_candidates / scan_fallback)

問題:
- `Path.exists()` を catch なしで呼んでおり、Tera-station NAS 切断時 (`OSError [WinError 67]`) に `install_tk_exception_guard` 経由で「内部エラー: OSError」dialog のみ
- 本プロジェクトは UNC パス本番運用 (CLAUDE.md「Windows 実機環境」セクション)、Tera-station NAS 切断時のユーザー混乱リスク

対応方針 (Phase 3 完了後の別 PR 候補):
- `_safe_exists()` helper を `wiseman_hub.config` に追加、`Path.exists()` を OSError catch でラップ
- Label / 状態を 3 種類に分離: `_LBL_NOT_SET` (未設定) / `_LBL_NOT_FOUND` (設定済だが不在) / `_LBL_UNREACHABLE` (OSError、アクセス不可)
- 5-6 箇所の `Path.exists()` を統一

triage 評価:
- silent-failure-hunter rating 7 + confidence 90 → Issue 起票基準を満たす
- ただし Net ≤ 0 KPI のため新規 Issue 起票せず handoff debt 記録
- code-reviewer (PR #303) も「Phase 3 PR-3a/3b で纏めて見直す方が一貫性が出る」と推奨済 (現在 Phase 3 完了で纏めて別 PR が妥当タイミング)

### 3. 引き継ぎ保留 handoff debt

#### debt #1 (継承): Windows OS 差テストの事前検出
- Phase 2a/2b/3a/3b で `Path` 同士比較 + forward slash UNC 表現で OS 差を回避済
- 残課題: UNC `.exists()` / `.iterdir()` 等の path 操作テストは Windows runner 必要、debt #4 統合で `_safe_exists()` 経由テストとして整合可能

#### debt #2 (NEW → PR #303 で解消)
- ~~`_redraw` の `Path("").exists()` Label 表示問題~~ → **PR #303 で is_path_configured gate により解消**

#### debt #3 (継承 → PR #304/#305 で部分解消、Optional[Path] 議論は別途)
- ~~`Optional[Path]` 設計議論~~ → **Option C 採用で当面保留**、umbrella §G の close 前提条件にしない
- Phase 3 完了後の Optional[Path] 移行は別 epic 候補 (triage 基準未達のため Issue 起票せず、umbrella コメントで記録予定)

### 4. 引き続き保留中の handoff debt

#### Windows Tcl init.tcl ランダム fail 問題 (Session 73 発見、rating 6 で Issue 化基準未達)
- 暫定対応: re-trigger で逃げる (PR #303 / #305 で各 1 回発生、rerun で PASS)
- follow-up 候補: `TCL_LIBRARY` / `TK_LIBRARY` 環境変数明示設定

#### Issue #282 Codex 残指摘 4 件 (Session 71 で triage 済、rating 4-6)

### 5. Mac セッション着手不可項目 (前セッション継承、変化なし)

- #17 (smoke_real.py pytest 統合)
- #16 (test_new_registration_flow Pane/Text 経路)
- #11 (PywinautoEngine MEDIUM 5 件)
- #6 (PoC E2E)

### 6. PowerShell 廃止 epic 候補 (本セッション再確認、変化なし)

ADR-016 Proposed → Accepted 昇格 + `updater/` + bootstrapper 実装 → release バケット用意 → GitHub Actions OIDC 設定。Issue #27 続編 G とは独立。

---

## 次セッション優先順

### 次セッション実行手順 (確定)

1. **exe 配布 7 ステップ実行** (Phase 3 全体 + Phase 2b PR #301 含む 11 件検証、`docs/handoff/1c-exe-redistribution-runbook.md` 準拠)
   - 手順 1-6 を AI 伴走 (TeamViewer 経由 PowerShell)
   - 手順 7 で実機検証 11 件を本田様と一緒に確認

2. **実機検証結果を LATEST.md に記録** (Session 78 終了時)
   - 残課題: debt #4 着手判断、Issue #275、Issue #27 §1/§E 残作業の本田様判断

### 配布後の次々セッション以降

3. **debt #4 対応 PR** — `_safe_exists()` helper + Label 3 状態分離 (silent-failure-hunter HIGH 解消、5-6 箇所統一)
4. **Issue #275** — 本田様ヒアリング待ち (実機配布時に同時実施推奨)
5. **Issue #27 §1 Literal 拡張** — 残作業 (本田様判断)
6. **Issue #27 §E 追加検討** — tuple 化 / frozen dict (本田様判断)
7. **Windows Tcl init.tcl 問題** — handoff debt 継続
8. **PowerShell 廃止 epic** — 別途独立して着手判断 (ADR-016 昇格 + updater 実装)

---

## 構造的整合性チェック

- ⏭️ `/impact-analysis`: §4 Path 移行で config dataclass 5 field 型変更、9+ consumer 経路に波及。consumer 整合性確認は pytest 1977 件 PASS + mypy clean で gate 済、CI 全 5 ジョブ PASS で OS 横断検証済
- ⏭️ `/new-resource`: 新規 helper 追加なし (Phase 2a で確立した `coerce_path` / `_check_path` / `is_path_configured` / `stringify_paths_recursive` を流用)
- ⏭️ `/trace-dataflow`: TOML str → Path (load_config) → consumer Path API → str (save_config _stringify_path_values shallow) / JSON str (session._to_dict stringify_paths_recursive 任意深度) / GCS JSON str (mapping_sync 境界変換) の双方向データフロー、Phase 2a/2b/3a で確立した規約を Phase 3b の nested dataclass + GCS 境界に拡張

---

## Issue Net 変化

```
## Issue Net 変化
- Close 数: 0 件
- 起票数: 0 件
- Net: 0 件
```

**Net = 0 だが進捗実体あり**:

- **PR #303** で debt #2 (`_redraw` Label 表示問題) 解消
- **PR #304** で Issue #27 §4 Phase 3a (karte_root / fax_root Path 化) 完遂
- **PR #305** で Issue #27 §4 Phase 3b (ReportStaffEntry.base_dir Path 化) 完遂
- **Issue #27 §4 Path 移行スコープ全体完了** (Phase 1 → 2a → 2b → PR-Debt2 → 3a → 3b)
- Issue #27 umbrella は §1 Literal 拡張 / §E 追加検討 / Optional[Path] 議論が残るため close 不可
- 新規 Issue 起票はゼロ。本セッション発見の 1 件 (handoff debt #4: `Path.exists()` OSError catch) は silent-failure-hunter rating 7 で triage 基準を満たすが、Net ≤ 0 KPI のため新規 Issue 起票せず handoff debt 記録

triage 遵守: 機構化済み 3 層ゲートに従って Net ≤ 0 を維持。

Quality Gate 全 4 段を 3 PR 連続で実施し、`/codex review` セカンドオピニオン (PR #304/#305) で **NEEDS_MINOR → 同梱 fix で APPROVE 相当** 取得。本セッションの白眉:
1. **3 PR 連続 merge による Phase 3 全体完遂**: PR-Debt2 (debt #2 解消) + Phase 3a + Phase 3b で §4 Path 移行スコープ完了
2. **Option C 設計判断の貫徹**: `Path("")` sentinel 維持 + canonical sentinel pattern 4 境界 (TOML save/load + GCS push/pull) で round-trip 不変条件成立
3. **Review 反映の網羅性**: 3 PR で 3 reviewer 一致指摘 (canonical sentinel pattern / fixture 修正 / backslash UNC 後方互換) を全て同梱 fix
4. **debt #4 の明示記録**: silent-failure-hunter HIGH を 3 PR で継続指摘、Phase 3 完了後の別 PR 候補として LATEST.md に記録

---

## ✅ 残留プロセスなし

CI: ✅ 全 3 PR (Phase 3 PR-Debt2 / 3a / 3b) で main push 後の Build Windows Smoke を含む全ジョブ PASS。
