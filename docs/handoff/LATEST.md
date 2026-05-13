# Session 68 完了 — Issue #27 続編 E Phase 2 + 3a (frozen 化 8 dataclass、2 PR merge)

**Date**: 2026-05-13
**Main HEAD**: `0d67ccd` fix(config): 残 6 dataclass を frozen 化 (#27 続編 E Phase 3a) (#270)
**Test count**: main project 1747 → **1801** (+54)
**Active Issues**: 10 (実質 5、postpone 5) [変化なし、Net 0]
**Phase**: Phase 7 着手前 [変化なし]

---

## 完了内容

本セッションは Session 67 から /catchup 経由で継続。Session 67 LATEST「次セッション優先順 1 位 #27 続編 E Phase 2 (PdfMergeConfig + WisemanConfig)」を impl-plan ベースで段階実施。Phase 1 で確立した frozen 化パターンを **8 dataclass に水平展開** (umbrella 9 dataclass 中、残 1 = `AppConfig` のみ)。

### PR #269 — Issue #27 続編 E Phase 2: `PdfMergeConfig` + `WisemanConfig` frozen 化 (10 files, +320/-106)

**PR #258 type-design-analyzer rating 7 対応**: post-construction mutation (`cfg.concat_order = ("X",)` 等) で `__post_init__` 不変条件チェック / 型ガードを bypass する経路を構造的に防ぐ。

- `src/wiseman_hub/config.py`:
  - `PdfMergeConfig` / `WisemanConfig` に `@dataclass(frozen=True)` を付与 + docstring 更新
  - 旧 `__post_init__` 内の `self.concat_order = tuple(self.concat_order)` 自己代入を **`_coerce_concat_order()` helper に外出し** (新規 helper 関数)
  - `__post_init__` は入力が tuple であることを確認後、値域検証のみ実施する fail-safe 層に役割変更 (object.__setattr__ 経由の黒魔術は採らない)
  - `load_config` 内の TOML 経由 `list[str]` → `tuple` coerce 呼出を組込
- UI 3 ファイル (`settings.py` / `ex_extractor_dialog.py` / `facility_root_dialog.py`): post-construction mutation を `dataclasses.replace()` ベースに統一
- テスト 6 ファイル: フィールド代入 mutation を `replace()` に書換、`concat_order=["..."]` list 渡し 9 箇所を tuple 渡しに変更
- 新規 `TestFrozenInstanceImmutability` 16 ケース + `TestCoerceConcatOrder` 5 ケース = +21 ケース

**Evaluator 評価**: 9/10 GO、AC 6 件全 PASS、Blocker なし

### PR #270 — Issue #27 続編 E Phase 3a: 残 6 dataclass frozen 化 (3 files, +208/-7)

`ScheduleConfig` / `ReportTarget` / `GcpConfig` / `UpdaterConfig` / `ReportStaffEntry` / `ChecklistConfig` に `@dataclass(frozen=True)` を付与。Phase 2 と異なり `__post_init__` に自己代入 mutation なし (型ガードのみ) だったため、helper 外出し不要、書換も 1 箇所 (`base.schedule.cron = ...` → `replace()`) のみで極めて軽量に完了。

- `TestFrozenInstanceImmutability` に 33 ケース追加 (各 dataclass の setattr parametrize + replace 再評価 1 ケース)
- ChecklistConfig docstring に「dict 内容変更 (`cfg.facility_routing["X"] = "Y"`) は frozen 対象外」を明記

**Evaluator 評価**: 9/10 GO。AC3 文書補足 (production 側 `xlsx_path_cache[key] = value` の dict mutation 経路) は self-review comment で補足済。

### ハイライト: Phase 3a の軽量化

Phase 2 と異なり 6 dataclass が **全て mutation なしの単純型ガード** で、想定 (impl-plan 当初) より大幅に簡略化。grep 結果が事実上 1 件のみで、Phase 2 の helper 外出し設計議論が再度発生しなかった。新規テストの parametrize 化でカバレッジを担保。

---

## ⚠️ 注意事項 / 次セッション着手前確認

### 1. Issue #27 続編 E Phase 3b (AppConfig frozen 化) の設計判断

残 1 dataclass `AppConfig` の frozen 化で Issue #27 続編 E (frozen 化 scope) は完了。ただし以下の論点が impl-plan 必須:

**影響範囲が広い**:
- Phase 1/2 で導入した `cfg.pdf_merge = replace(cfg.pdf_merge, ...)` パターンが大量に存在 (`new_config.wiseman = replace(...)` / `cfg.ocr_backend = replace(...)` 等)
- AppConfig frozen 化後はこれらが全て `cfg = replace(cfg, pdf_merge=replace(cfg.pdf_merge, ...))` のネスト書換に変更必要
- production code (UI 4 ファイル) + テスト (6+ ファイル) の **大規模書換**

**コンテナ frozen 化の設計判断**:
- `AppConfig.reports: list[ReportTarget]` の list 内容変更 (`cfg.reports.append(...)`) は frozen でも防げない (参照差し替えのみ阻止)
- ChecklistConfig 内 dict と同じく docstring で明記 vs tuple 型化で構造的に阻止、いずれの設計を採るかの議論が必要
- ReportTarget docstring に「list append は対象外」を Phase 3a で既に明記済み

**推奨着手フロー**:
1. `/impl-plan` で AppConfig frozen 化の WBS + 影響範囲詳細 + 設計判断列挙
2. evaluator agent で Phase 3b の AC 設計妥当性検証
3. 実装 → PR → evaluator GO → merge
4. Issue #27 続編 E close 候補化 (umbrella 自体は §1 Literal 導入 / §4 Path 移行 等の残作業あり)

### 2. Issue #27 umbrella の残作業 (続編 E 完了後)

Issue #27 body から、本 umbrella は以下のスコープを含む:
- §1: **Literal 型導入** (`concat_order` 等の離散集合制約) — Phase 1-3a で部分実施 (PdfMergeConfig の `ConcatSourceLetter`)、他 dataclass は未着手
- §2: **`__post_init__` 不変条件検証** — Phase 1-3a で完了
- §3: **`is_configured()` プロパティ** — OcrBackendConfig / UserNameBBox で実装済、他は未検討
- §4: **Path 型への移行** — 未着手 (input_dir / output_dir 等が str のまま)
- §5: **続編 E (`frozen=True` 化)** — Phase 1-3a で 8 dataclass 完了、Phase 3b で AppConfig 完了予定

Issue #27 close は §1 / §4 / Phase 3b すべて完了後 (umbrella で **続編 E のみ完了では close 不可**)。続編 F (Literal 拡張) / 続編 G (Path 移行) を別 PR シリーズで段階実施する流れ。

### 3. Phase 1/2/3a で実機未検証の項目

- **Windows 実機での UI Settings 保存動作** (PR #267/#269): TeamViewer 経由で本田様 PC で `uv run python -m wiseman_hub` → SettingsDialog → OCR endpoint 保存 / ex_source_dir 選択 / facility_root 選択 を実行して runtime regression がないか確認推奨
- **Windows 実機での AppConfig load → 各 dataclass 構築動作** (PR #270): TOML 既存ファイル経由で全 dataclass が frozen 化後も正しく構築されるか

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

### 7. Codex MCP timeout (本セッション発生)

PR #269 のセカンドオピニオン依頼で `mcp__codex__codex` が 300s timeout。evaluator agent で代替済。同事象再発時は **Bash 版 codex CLI** の利用を検討 (codex skill 説明参照)。

---

## 次セッション優先順

1. **#27 続編 E Phase 3b** (`AppConfig` frozen 化) — 影響範囲大、要 `/impl-plan`、完了で続編 E close
2. **#27 続編 F/G 検討** (Literal 拡張 / Path 移行) — umbrella close 候補化
3. **Phase 7 (Task #17)** impl-plan 起こし — 要 Windows 実機 (本田様 PC、TeamViewer)
4. **handoff debt 整理判断** — Session 64 繰越 3 件
5. **Issue #11/#16/#17/#6** — Windows 実機系、Mac セッション着手不可

---

## 構造的整合性チェック

- ⏭️ `/impact-analysis`: 8 dataclass の frozen 化は API 互換 (mutation 経路は `replace()` で代替可能)、production code 4 ファイル / test 7 ファイルで完全対応済。既存呼出元への影響なし
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

**Net = 0 だが、umbrella Issue #27 続編 E の 8 dataclass frozen 化を構造的に解消** (Phase 1 PR #267 = 2 dataclass、Phase 2 PR #269 = 2 dataclass、Phase 3a PR #270 = 6 dataclass、計 8 dataclass)。umbrella 自体は続編 E Phase 3b (AppConfig) + 元 scope §1 §4 で残作業あり、Issue 数として close 不可。

triage 基準遵守: 本セッションで上がった review agent の Nice-to-have (rating ≤ 6: docstring 注記、Phase 3a self-review) は **PR comment / docstring 内補足で吸収**、新規 Issue 起票せず。
