# Session 69 完了 — Issue #27 続編 E Phase 3b (AppConfig root frozen 化、続編 E スコープ完了)

**Date**: 2026-05-13
**Main HEAD**: `9c7f5d6` fix(config): AppConfig (root) を frozen 化 (#27 続編 E Phase 3b) (#272)
**Test count**: main project 1801 → **1815** (+14)
**Active Issues**: 10 (実質 5、postpone 5) [変化なし、Net 0]
**Phase**: Phase 7 着手前 [変化なし]

---

## 完了内容

本セッションは Session 68 から /catchup 経由で継続。Session 68 LATEST「次セッション優先順 1 位 #27 続編 E Phase 3b (`AppConfig` frozen 化、影響範囲大、要 `/impl-plan`)」を impl-plan 簡略版 (TaskCreate ベース) で実施。Phase 3b 単独 PR + 同 PR 内で review 指摘 4 件を統合修正し、続編 E 全 4 Phase (9 dataclass frozen 化) を構造的に完遂。

### PR #272 — Issue #27 続編 E Phase 3b: `AppConfig` (root) frozen 化 (9 files, +385/-190)

**PR #258 type-design-analyzer rating 7 対応の最終フェーズ**: root dataclass を frozen 化することで全 9 dataclass の階層全層が post-construction mutation 不可となり、`__post_init__` 型ガード bypass 経路が完全閉鎖された。

- `src/wiseman_hub/config.py`:
  - `AppConfig` に `@dataclass(frozen=True)` 付与
  - docstring を「**直下フィールドの参照差し替え** を構造的に防ぐ」表現に絞り、mutable leaf (list / dict) 内容変更は frozen 対象外と明示 (Codex review Low 指摘対応)
- Production code (UI 3 files):
  - `ui/settings.py` `form_to_config`: `copy.deepcopy(base)` + 個別 attribute 代入を廃止し、`replace(base, pdf_merge=replace(...), ocr_backend=replace(...), wiseman=replace(...))` の 1 段 replace 構造に統一。`copy` import 削除
  - `ui/ex_extractor_dialog.py` `_on_browse`: `self._config = replace(self._config, pdf_merge=replace(...))` の 2 段構造に変更
  - `ui/facility_root_dialog.py` `_do_scan`: 同上 + **silent regression 修正** (後述)
- Test code (5 files): TestSaveConfig / TestChecklistStaffPathExtension 等 17+ 箇所の旧 attribute 代入を `replace()` ベース or AppConfig コンストラクタ経由に変換
- `TestFrozenInstanceImmutability` に AppConfig 検証 14 ケース追加:
  - `test_app_config_frozen_field_assignment_raises` (parametrize 11 フィールド)
  - `test_app_config_replace_reapplies_post_init_validation` (str field 型ガード再評価)
  - `test_app_config_replace_nested_dataclass_reapplies_validation` (階層 replace + bbox 反転検出)
  - `test_app_config_reports_list_content_mutation_not_blocked` (仕様 regression guard)

**Evaluator 評価**: 初回 AC3 FAIL (`test_settings.py:406` の Phase 2 見落とし mutation) → 修正 → **再評価で APPROVE** (AC1-6 全 PASS)

### PR #272 内 — Review 指摘 4 件の統合修正 (commit b1646b6)

5 並列 review (4 agent + Codex CLI) で発見された High / Medium / Low 計 4 件を merge 前に統合修正:

#### High — facility_root_dialog の silent regression (silent-failure-hunter + Codex 共指摘)

- 旧 (frozen でない時代): `self._vm.config.pdf_merge = replace(...)` は shared reference の in-place mutation で、`self._config` と `self._vm.config` が同一 AppConfig instance を指していたため、L547 `save_config_fn(self._config, ...)` で更新後の `facility_root_dir` が永続化されていた
- Phase 3b 後 (frozen 化): ViewModel.set_root_and_rows 内の `self.config = replace(self.config, pdf_merge=replace(...))` は self._vm.config のみ新インスタンスに差し替え、Dialog 側の `self._config` は古い AppConfig (facility_root_dir 未更新) を保持
- **silent regression**: L547 で **古い facility_root_dir が TOML に書き戻される** → 次回起動時にルート未保持 (40 事業所運用での体験劣化)
- **修正**: `_do_scan` で `set_root_and_rows` 直後に `self._config = self._vm.config` で参照を再同期 (mypy 型 narrowing 用 `assert self._vm.config is not None` 付き)
- 同類問題チェック: `ex_extractor_dialog.py` は同パターンを Dialog 側で直接 `self._config = replace(...)` していたため影響なし

#### Medium — form_to_config の mutable leaf alias (Codex 指摘)

- `copy.deepcopy(base)` → `replace(base, ...)` で `base.reports` (list) + `ReportTarget.menu_path` (list) が new_cfg と base 間で shared
- 将来 `new_cfg.reports.append(...)` / `new_cfg.reports[0].menu_path.append(...)` が base 側へ漏れる脆性
- **修正**: `decoupled_reports = [replace(r, menu_path=list(r.menu_path)) for r in base.reports]` で mutable leaf を新 list に再構築、base/new_cfg alias を切る
- tuple 化 (umbrella §1) 完了までの暫定防御として docstring に明記

#### Low — AppConfig docstring 表現緩和 (Codex 指摘)

- 旧 docstring「型ガード bypass を構造的に防ぐ」は強すぎ、mutable leaf 内容変更まで防げると誤読されるリスク
- **修正**: 「直下フィールドの参照差し替えを防ぐ」に絞って表現、frozen 化対象外 (mutable leaf list / dict の内容変更) を明示的に列挙

### ハイライト: Phase 3b の Critical 発見と修正

Phase 1-3a は機械的書換で完了したが、Phase 3b (root frozen) は **Dialog ↔ ViewModel の reference identity** が暗黙の前提だった経路を初めて壊した。5 並列 review (silent-failure-hunter + Codex CLI) が独立に同じ Critical を発見したことで、本セッションのレビュー体制 (4 agent + Codex CLI 並列) の効果が実証された。Mac セッションでテスト化が困難な領域 (Tk Dialog 統合) はコメントとハンドオフで Windows 実機検証に橋渡し。

---

## ⚠️ 注意事項 / 次セッション着手前確認

### 1. 【最優先】Windows 実機検証 (Phase 1-3b 累積 4 PR shadow 消化)

Phase 1-3b の 4 PR (`#267` / `#269` / `#270` / `#272`) はすべて **Mac セッションで完了し Windows 実機未検証**。特に Phase 3b で発見された **facility_root_dialog の Critical 修正** (`self._config = self._vm.config` 同期) は Tk Dialog 統合経路のため Mac での自動テストが困難。次セッション着手前に TeamViewer 経由で必ず実機検証を完了させる。

**実機検証チェックリスト**:

| # | 機能 | 期待動作 | Phase 3b Critical 関連 |
|---|------|---------|---------------------|
| 1 | Launcher 起動 | ImportError / ModuleNotFoundError なし、3 ボタン UI 表示 | ✅ (load_config 経路) |
| 2 | SettingsDialog → OCR endpoint / API key 保存 → 再起動で値保持 | TOML 永続化、値復元 OK | ✅ (form_to_config の replace 階層) |
| 3 | SettingsDialog → wiseman_exe_path 保存 → 再起動で値保持 | 同上 | ✅ |
| 4 | SettingsDialog → pdf_merge 設定 (concat_order / bbox) 保存 → 再起動で値保持 | 同上 (UserNameBBox / PdfMergeConfig frozen 経路) | ✅ |
| 5 | **facility_root_dialog → ルート選択 → スキャン成功 → 再起動でルート保持** | **L547 save_config が新 facility_root_dir で書き戻し成功** | **🔴 Critical 修正の核心** |
| 6 | ex_extractor_dialog → ex_source_dir 選択 → 永続化 → 再起動で保持 | 同上 (ex_extractor 経路) | ✅ |
| 7 | 既存機能 smoke (PDF 結合 / OCR / facility_merger) | regression なし | ✅ |

実機 runbook: `docs/handoff/1c-exe-redistribution-runbook.md`

#### Rollback 手順 (実機で問題発生時)

```powershell
$dist = "$HOME\wiseman-hub"
$latest_bak = Get-ChildItem "$dist\wiseman_hub.exe.bak-*" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Copy-Item -Force $latest_bak.FullName "$dist\wiseman_hub.exe"
```

### 2. Issue #27 umbrella 残作業 (続編 F/G)

続編 E (frozen 化 scope) は完了で **OPEN 維持**。Issue #27 close は以下の §1 / §4 完了が前提:

- **§1 Literal 型導入**: `PdfMergeConfig.concat_order` の `ConcatSourceLetter` のみ完了、他 dataclass の離散集合制約 (`output_format` / `log_level` 等) は未着手
- **§4 Path 型移行**: `input_dir` / `output_dir` 等の str → Path
- **続編 E 追加検討項目** (Issue #27 コメント記録):
  - `AppConfig.reports: list[ReportTarget]` → `tuple[ReportTarget, ...]` 化 (frozen leaf list mutation 阻止、PR #272 Codex Medium で暫定防御済)
  - `ChecklistConfig.facility_routing` / `xlsx_path_cache` の frozen dict 化検討

### 3. pr-test-analyzer Suggestion (任意の品質補強)

PR #272 review で挙がった rating 5-7 の Suggestion 3 件。**rating < 7 のため Issue 化せず本ハンドオフで記録**:

- (rating 7) `form_to_config` の reports list reference identity test: `new_cfg.reports is not base.reports` (Codex Medium 修正の lock-in)
- (rating 6) `tk_required` skip 挙動の Linux/Windows CI 確認 (test_settings.py:406 修正の CI 実行確認)
- (rating 5) ex_extractor_dialog の `self._config = replace(...)` rebinding test (facility_root_dialog の TestPersistRoot と pattern mirror)

### 4. Phase 7 (Task #17) は引き続き pending — 要 Windows 実機

業務 Phase 4 全件配置を新システムで実行。本田様 PC で launcher 経由運用切替、デスクトップショートカット更新等の運用切替計画が必要 (impl-plan 推奨)。

### 5. Windows 実機必須の Issue は Mac セッションで着手不可

- #17: `smoke_real.py` を pytest に統合し `WISEMAN_REAL=1` でゲート
- #16: `test_new_registration_flow` の Pane/Text 経路 (WM_LBUTTON) カバー
- #11: PywinautoEngine MEDIUM 5 件
- #6: PoC E2E (ログイン→CSV抽出→GCSアップロード)

### 6. handoff debt (Session 64 から繰越、整理判断必要)

- `build-windows-smoke.yml` に `Verifier.production(offline=True)` smoke 追加
- Trust root staleness 監視 (warn-log)
- sigstore-python 3.x dependency docstring

### 7. Codex CLI が MCP timeout の代替手段として有効

PR #269 / PR #272 で `mcp__codex__codex` の代替として **Bash 版 codex CLI** (`codex exec --full-auto --sandbox read-only --cd .`) が安定動作することを確認。timeout なし、High/Medium/Low の重要度付き出力が agent と独立した観点を提供する。Phase 3b では silent-failure-hunter agent と独立に同じ Critical を発見し、review プロセスの冗長性を実証した。

---

## 次セッション優先順

1. **【最優先】Windows 実機検証** — TeamViewer 経由で Phase 1-3b 累積 4 PR の動作確認 (上記チェックリスト 7 項目)。Critical 修正 (facility_root_dialog) を必ず先頭で確認
2. **Issue #27 続編 F/G 検討** (Literal 拡張 / Path 移行) — umbrella close 候補化、impl-plan 起こし
3. **pr-test-analyzer Suggestion 消化** (任意) — small follow-up PR で form_to_config identity test 等
4. **Phase 7 (Task #17)** impl-plan 起こし — 要 Windows 実機 (本田様 PC、TeamViewer)
5. **handoff debt 整理判断** — Session 64 繰越 3 件
6. **Issue #11/#16/#17/#6** — Windows 実機系、Mac セッション着手不可

---

## 構造的整合性チェック

- ⏭️ `/impact-analysis`: 9 dataclass の frozen 化は API 互換 (mutation 経路は `replace()` で代替可能)、production code (UI 3 ファイル) / test code (5 ファイル) で完全対応済。既存呼出元への影響は review で発見した Dialog 同期 1 件のみで対応済
- ⏭️ `/new-resource`: 新規テーブル/API 追加なし
- ⏭️ `/trace-dataflow`: データフロー新規実装なし

---

## Issue Net 変化

```
## Issue Net 変化
- Close 数: 0 件
- 起票数: 0 件
- Net: 0 件
```

**Net = 0 だが、umbrella Issue #27 続編 E スコープ (9 dataclass frozen 化) を本セッション PR #272 で構造的に完遂** (Phase 3b 単独で 1 dataclass、累積 Phase 1+2+3a+3b で 9 dataclass)。umbrella 自体は §1 Literal 拡張 / §4 Path 移行が残り close 不可。続編 E 完了は Issue #27 コメント (`#issuecomment-4438204891`) に記録済。

triage 基準遵守: 本セッションで上がった review agent / Codex の Nice-to-have (rating ≤ 6: form_to_config identity test、tk_required CI 確認、rebinding test) は **本ハンドオフで記録**、新規 Issue 起票せず。PR #272 review で発見された High / Medium / Low は **同 PR 内で統合修正 + merge 前解消**、Issue 起票せず Net 削減。
