# Session 67 完了 — Issue #27 続編 E Phase 1 (UserNameBBox + OcrBackendConfig frozen 化、1 PR merge)

**Date**: 2026-05-13
**Main HEAD**: `4e69b21` fix(config): UserNameBBox + OcrBackendConfig を frozen 化 (#27 続編 E Phase 1) (#267)
**Test count**: main project 1736 → **1747** (+11)
**Active Issues**: 10 (実質 5、postpone 5) [変化なし、Net 0]
**Phase**: Phase 7 着手前 [変化なし]

---

## 完了内容

本セッションは Session 66 から /catchup 経由で継続。Session 66 LATEST「次セッション優先順 1 位 #27 続編 E (`frozen=True`)」を impl-plan ベースで段階実施。Phase 1 として umbrella の type-design rating 7 指摘を構造的に解消。

### PR #267 — Issue #27 続編 E Phase 1: `UserNameBBox` + `OcrBackendConfig` の frozen 化 (4 files, +113/-24)

**PR #258 type-design-analyzer rating 7 指摘対応**: post-construction mutation (`cfg.endpoint_url = "  "` 等) で `__post_init__` 型ガード/不変条件チェックを bypass する経路を構造的に防ぐ。

- `src/wiseman_hub/config.py`: UserNameBBox + OcrBackendConfig に `@dataclass(frozen=True)` を付与 + docstring 更新
- `src/wiseman_hub/ui/settings.py`: `form_to_config` の ocr_backend mutation (2 行) を `dataclasses.replace()` ベースに統一
- `tests/unit/test_config.py`: `TestFrozenInstanceImmutability` 11 ケース新規 (FrozenInstanceError parametrize 5+4 + replace 経由 `__post_init__` 再評価 2) + 既存 3 箇所書換 (208-209, 273-277, 969 行付近)
- `tests/unit/ui/test_settings.py`: 既存 mutation 4 箇所書換 (231-235, 276, 311-316 行付近) + imports に `replace, UserNameBBox, OcrBackendConfig` 追加

**4 並列 review 結果**: Critical 0 / rating ≥ 7 Important 0 / Suggestion のみ (rating ≤ 6)。即マージ可判定。

| 軸 | 元 PR #258 | 本 PR 後 |
|----|:---------:|:--------:|
| Encapsulation | 6/10 | **8/10** ✅ |
| Invariant Expression | - | 8/10 |
| Invariant Usefulness | - | 8-9/10 |
| Invariant Enforcement | - | 9/10 |

### ハイライト: frozen 化で隠れていた既存テストの論理欠陥が顕在化

`test_settings.py` の `test_roundtrip_preserves_form_fields` で `replace(bbox, x0=1.5, dpi=300)` した際、元の `x1=0.0` (default) のままで `x0 >= x1` の不変条件違反が発生。mutation 経由では `__post_init__` が再評価されないため隠れていたバグを frozen 化が露呈させた。全フィールド指定 (`UserNameBBox(x0=1.5, y0=2.0, x1=100.0, y1=50.0, dpi=300)`) に書換で解消。**`__post_init__` 再評価が他にも回帰検出に役立つ可能性を示唆**。

---

## ⚠️ 注意事項 / 次セッション着手前確認

### 1. Issue #27 続編 E Phase 2 の設計判断ポイント

Phase 1 で確立したパターン (`@dataclass(frozen=True)` + `replace()` 移行 + 既存テスト書換) を残り 9 dataclass に水平展開する際、優先順位と影響範囲:

**最優先 (Phase 2、silent-failure rating 7 / type-design Phase 2 必須)**:
1. **`PdfMergeConfig` frozen 化** — `concat_order` 不変条件 (空/unknown/重複拒否) を mutation bypass する経路あり
   - **設計判断**: `__post_init__` の `self.concat_order = tuple(self.concat_order)` 内部 mutation を **外出し必須** (`_coerce_concat_order(value) -> tuple[...]` を構築前に適用)
   - 影響範囲: test 30+ 箇所 (`cfg.pdf_merge.concat_order = ...` / `cfg.pdf_merge.input_dir = ...` 系)
2. **`WisemanConfig` 同時 frozen 化** — `form_to_config:188` の `new_config.wiseman.exe_path = ...` mutation 残置を同 PR で `replace()` 化

**Phase 2 後 (低 ROI 順)**:
3. `GcpConfig` / `ScheduleConfig` / `ReportTarget` / `UpdaterConfig` / `ChecklistConfig` / `ReportStaffEntry`
4. `AppConfig` (最終段、全 nested 型 frozen 化完了後)

### 2. Phase 2 で task 化推奨 (review 抽出)

- `form_to_config` の **base 非破壊性テスト** (pr-test rating 5、`base.ocr_backend.api_key` 不変アサート)
- **`replace()` 経由再評価テスト拡充** (pr-test rating 4 / type-design rating 6、現状 2 ケースのみ固定)
- frozen 化型に **`__hash__` 副作用注記** docstring 追加 (type-design rating 5)

### 3. Phase 7 (Task #17) は引き続き pending — 要 Windows 実機

業務 Phase 4 全件配置を新システムで実行。本田様 PC で launcher 経由運用切替、デスクトップショートカット更新等の運用切替計画が必要 (impl-plan 推奨)。

### 4. Windows 実機必須の Issue は Mac セッションで着手不可

- #17: `smoke_real.py` を pytest に統合し `WISEMAN_REAL=1` でゲート
- #16: `test_new_registration_flow` の Pane/Text 経路 (WM_LBUTTON) カバー
- #11: PywinautoEngine MEDIUM 5 件
- #6: PoC E2E (ログイン→CSV抽出→GCSアップロード)

### 5. handoff debt (Session 64 から繰越、整理判断必要)

- `build-windows-smoke.yml` に `Verifier.production(offline=True)` smoke 追加
- Trust root staleness 監視 (warn-log)
- sigstore-python 3.x dependency docstring

### 6. Phase 1 で実機未検証の項目

- **Windows 実機での UI Settings 保存動作**: Mac セッション対象外。次セッション以降で本田様 PC TeamViewer 経由で `uv run python -m wiseman_hub` → SettingsDialog → OCR endpoint 保存実行で確認推奨 (silent-failure-hunter S-3 指摘、Phase 1 は pure logic test カバー済だが production path の検証は未実行)

---

## 次セッション優先順

1. **#27 続編 E Phase 2** (`PdfMergeConfig` + `WisemanConfig` frozen 化) — silent-failure rating 7、影響範囲やや大 (`concat_order` coerce 外出し設計判断 + test 30+ 箇所書換)、要 `/impl-plan`
2. **Phase 7 (Task #17)** impl-plan 起こし — 要 Windows 実機 (本田様 PC、TeamViewer)
3. **handoff debt 整理判断** — Session 64 繰越 3 件
4. **Issue #11/#16/#17/#6** — Windows 実機系、Mac セッション着手不可

---

## 構造的整合性チェック

- ⏭️ `/impact-analysis`: config.py の 2 dataclass frozen 化は API 互換 (mutation 経路は `replace()` で代替可能)、production code 1 ファイル (settings.py:180-181 → `replace()` 化) で完全対応済。既存呼出元への影響なし
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

**Net = 0 だが、umbrella Issue #27 の rating 7 指摘 1 件 (frozen 化) を構造的に解消**。umbrella 自体は Phase 2-N で残作業あり、Issue 数として close 不可。triage 基準遵守: 4 並列 review で上がった Suggestion (rating ≤ 6) は新規 Issue 化せず PR コメント / umbrella #27 集約で吸収。
