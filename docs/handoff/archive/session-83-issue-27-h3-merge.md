# Session 83 完了 - Issue #27 続編 H3 完遂 (PR #327 マージ、H シリーズ全完了)

日時: 2026-05-16
HEAD (main): `73c0709`
前セッション archive: [session-82-issue-17-close-and-issue-27-h1-h2-merge.md](./archive/session-82-issue-17-close-and-issue-27-h1-h2-merge.md)

## 本セッション完了内容

### PR #327 (merged `73c0709`): ChecklistConfig 4 dict を MappingProxyType 化 (Issue #27 続編 H3)

umbrella Issue #27 続編 H シリーズ最終段。`ChecklistConfig.{facility_routing, report_staff, xlsx_path_cache, staff_choice_cache}` の 4 dict を `Mapping[str, ...]` + `MappingProxyType` ラップ化し、dict 内容変更 (`cfg.checklist.X[k] = v` / `del cfg.checklist.X[k]`) を構造的に阻止。続編 E (frozen=True) + H1 (root tuple) + H2 (leaf tuple) + **H3 (dict ProxyType)** で `AppConfig` 配下の immutability 強化が完遂し、mutable leaf は構造的に存在しない状態を達成。

#### 実装内容 (8 files, +524/-47)

| ファイル | 変更内容 |
|---|---|
| `src/wiseman_hub/config.py` | ChecklistConfig 4 dict 型注釈 `dict[str, T]` → `Mapping[str, T]`、`__post_init__` 末尾で `MappingProxyType(dict(self.X))` ラップ (防御コピー込み)、`_check_dict_str_to_str` の `isinstance(value, dict)` → `Mapping` 緩和 (replace() rewrap 経路通過)、`_update_checklist` の `asdict(checklist)` を fields() iteration に変更 (mappingproxy が copy.deepcopy 非対応のため、`_CHECKLIST_DICT_FIELDS` 集合で除外)、AppConfig/ChecklistConfig docstring 更新 |
| `src/wiseman_hub/ui/checklist_c_dialog.py` | hotpath 3 箇所 (`_clear_cache_for_row` / `_open_staff_picker_for_review` / `_open_picker_for_review`) を `dataclasses.replace()` 経由に変更、`self._config` を新 AppConfig に差し替える経路に統一 (PR #272 教訓: facility_root_dialog 永続化 silent regression パターン構造的予防) |
| `src/wiseman_hub/pdf/checklist_b.py` / `pdf/checklist_c.py` / `ui/checklist_settings_dialog.py` | consumer 側 `dict[str, T]` → `Mapping[str, T]` (read-only 契約の API 表現、mypy 整合) |
| `tests/unit/test_config.py` | 新規 `TestChecklistConfigDictImmutability` クラス (14 件): MappingProxyType ラップ確認 / `__setitem__` / `__delitem__` の TypeError / 防御コピーによる参照断絶 / `replace()` 経路 / load_config + save_config ラウンドトリップ |
| `tests/unit/ui/test_checklist_c_dialog_staff_picker_persistence.py` | 既存 5 件を `dlg._config` 参照に更新 (PR #272 教訓)、新規 3 件追加: `test_staff_picker_replaces_self_config_with_new_appconfig` + `test_xlsx_picker_replaces_self_config_with_new_appconfig` (pr-test-analyzer Gap 1 反映) + `test_clear_cache_replaces_self_config_with_new_appconfig` (Gap 2 反映) |
| `tests/unit/ui/test_checklist_c_dialog_cache_clear.py` | tk_required xfail テスト 3 件を MappingProxyType 対応に更新 (将来 Tk 環境で実行可能になった時の broken-when-enabled 防止) |

#### Quality Gate 結果 (large tier、6 並列 review)

| Reviewer | 判定 | 反映 |
|---|---|---|
| code-reviewer | merge ready | I-1 (rating 6-7、hotpath helper 化) はトレードオフで見送り |
| type-design-analyzer | **APPROVE** | 4 軸平均 **35/40** (Enc 9 / Expr 8 / Useful 9 / Enforce 9) |
| silent-failure-hunter | merge ready | **I2 `_CHECKLIST_DICT_FIELDS` ドリフトリスク (rating 6, conf 80) inline 反映** |
| **comment-analyzer** | **C1 fix 後 merge OK** | **C1 (field block コメント rot) + Important #2-4 inline 反映** |
| **pr-test-analyzer** | **Gap 1/2 マージ前推奨** | **Gap 1 (xlsx picker identity test rating 8 conf 85) + Gap 2 (clear cache identity test rating 7 conf 80) inline 反映** |
| evaluator | **APPROVE** | LOW × 2 (PR コメント記録) |

**CRITICAL C1 + Important × 4 を 2 commit 目で inline 反映**:
- C1: ChecklistConfig 4 dict field 直前の block コメントが `_check_dict_str_to_str` の Mapping 緩和と矛盾 (「型ガード側が dict を要求」記述) → 防御コピー意図と rewrap 経路を正しく説明する記述に修正
- Error msg docstring: `must be dict` 表現を TOML 運用者向けに維持する判断を docstring に明示
- `_CHECKLIST_DICT_FIELDS` を module-level `Final[frozenset[str]]` に昇格 + 「⚠ MAINTENANCE NOTE: 新 Mapping field 追加時の更新警告」コメント追加
- AppConfig docstring に「続編 H シリーズ完遂 (mutable leaf は構造的に存在しない)」を明示
- hotpath 3 箇所中 1 箇所しかなかった identity 差し替えテストを 3 箇所すべてに揃える (新規 2 件追加で完備)

### 検証結果

| 項目 | 結果 |
|---|---|
| pytest (Mac local) | PR #325 完了時 2146 → PR #327 完了時 **2163 passed** (+17 件 H3 累計、回帰なし)、120 skipped |
| ruff check src/ / mypy src/ | All clean (0 errors / 78 files) |
| CI Unit Tests (macOS/Linux 3.11/3.12) | ✅ success |
| CI Windows UI Tests | ✅ success |
| CI Windows Integration Tests | ✅ success |
| CI Build Windows Smoke | ✅ success |

## Issue Net 変化

```
Close 数: 0 件
起票数: 0 件
Net: 0 件 (進捗なし扱い)
```

Issue Net は 0 だが、本セッションは Issue #27 umbrella の続編 H3 完遂で **H シリーズ全体 (H1/H2/H3) を構造的 immutability 強化の完了状態にした** 進捗。umbrella Issue #27 は §1 Literal 拡張・§4 Path 移行残作業のため意図的に OPEN 維持 (続編 F/G 候補)。新規起票 0 件はレビュー指摘の triage 基準 (rating ≥ 7 + confidence ≥ 80) を満たす項目を全て inline 反映または PR コメント記録で処理した結果であり、postponement / silent suppression ではない。

## 次セッション最優先タスク

### 1. **Issue #316 実機対処待ち** (本田様 PC、AI 着手不可)

`scripts/diagnose-tcl.ps1` を本田様 PC で 1 度実行してもらい、結果を Issue #316 にコメント。runbook Step 1-4 (Windows セキュリティ GUI 除外 / 第三者 AV / Python 再 install / uv-managed Python) を順試行。

### 2. **Issue #17 実機検証** (本田様 PC、TeamViewer 経由)

`$env:WISEMAN_REAL = "1"` + `$env:WISEMAN_LNK_PATH = "<.lnk path>"` を設定して `uv run pytest tests/integration/test_smoke_real.py -m wiseman_real` を実行 → 1 passed 確認。失敗時の挙動 (LNK_PATH 不在 → `pytest.fail`、Wiseman 起動失敗 → engine 例外伝播) も確認可能。

### 3. **Issue #27 続編 F / G 残作業** (AI 単独着手可能)

H シリーズ完遂後の umbrella 残スコープ:
- **§1 Literal 型導入**: `PdfMergeConfig.concat_order` の `ConcatSourceLetter` のみ完了済、他 dataclass の離散集合制約は未着手 (e.g. `WisemanConfig` 等の固定値フィールド)
- **§4 Path 型移行**: 続編 G Phase 3a で一部完了 (`karte_root` / `fax_root` / `ReportStaffEntry.base_dir`)、残りの str→Path 候補あり

frozen/immutability テーマからは独立した型強化トピックのため、続編 F (Literal 拡張) / 続編 G 残り (Path 移行) を別 PR シリーズで段階実施。

### 4. **active 残 Issue (実機 + ヒアリング待ち)**

- **#274** B/C 自動配置ダイアログ「詳細」列の見切れ (Phase 1 完了済、実機検証待ち)
- **#275** ChecklistSettingsDialog GCP 同期ボタン UI シンプル化 (impl-plan たたき台あり、本田様ヒアリング 4 領域回答待ち)
- **#16** test_new_registration_flow: Pane/Text 経路 (WM_LBUTTON) をカバー
- **#11** PywinautoEngine: コードレビュー残件 (MEDIUM 5件)

### 5. ポストポーン中 Issue (着手不可、ユーザー明示指示なき限り無視)

#245 / #170 / #161 / #134 / #39 (postponed ラベル、再開条件は各 Issue コメント参照)

## ハンドオフ debt

### 解消済み (本セッション)

- ✅ Issue #27 続編 H3: ChecklistConfig 4 dict → MappingProxyType 化 + hotpath 3 箇所 replace() 統一 (PR #327 merge)
- ✅ 続編 H シリーズ全体完遂 (E→H1→H2→H3、`AppConfig` 配下の mutable leaf は構造的に存在しない状態を達成)
- ✅ 前 session 持ち越し review 指摘 (PR #325 type-design I-2: `decoupled_reports` 変数名) → H3 で touch するファイル外のため引き続き継続 debt

### 継続 (次セッション以降)

- Issue #316 実機対処 (本田様 PC AV 設定、本人の対応待ち)
- Issue #17 実機検証 (本田様 PC で WISEMAN_REAL=1 + WISEMAN_LNK_PATH 設定下の pytest 実行)
- Issue #27 続編 F (Literal 拡張) / G 残り (Path 移行) — frozen/immutability テーマからは独立
- Issue #274 / #275 (実機検証 + 本田様ヒアリング待ち)

### 未反映 review 指摘 (rating ≤ 6、PR コメント or 続編 F/G PR で取り込み候補)

- PR #324 type-design Important #1: `Sequence` vs `tuple` rationale の docstring 追記 (rating 6)
- PR #325 type-design I-2: `decoupled_reports` 変数名 misleading (rating 5、続編 F/G で touch するファイルで同時 rename 推奨)
- PR #325 comment-analyzer I-1: `_coerce_report_staff_entry` docstring 用語ずれ (rating 5-6)
- PR #325 code-reviewer S-1: `_build_staff_table` の `isinstance(v, list)` dead code (rating 6、tomlkit 透過変換で動作中、次回 helper 整理時に対応)
- PR #327 code-reviewer I-1: hotpath 3 箇所 `_update_checklist_field()` helper 化 (rating 6-7、局所性とのトレードオフで見送り、将来の hotpath 追加時に再評価)
- PR #327 silent-failure-hunter I1: `_check_dict_str_to_str` の Mapping ABC over-acceptance (rating 6、ChainMap 等の特殊 Mapping、実害なし)
- PR #327 silent-failure-hunter I3 / O1: OSError msg / 例外捕捉狭め (rating 4-5、既存パターン、別 Issue 検討)
- PR #327 pr-test-analyzer Gap 3-4 / O2: optional テストカバー (rating < 7)
- PR #327 evaluator LOW: `ChecklistConfig.__deepcopy__` override / `replace()` 経由参照断絶の explicit テスト (LOW)

## Quality Gate 適用状況

| 段階 | PR #327 (#27 H3) |
|---|---|
| `/simplify` | スキップ (8 files、型変更の機械的反映 + hotpath 局所変更) |
| `/safe-refactor` | 適用相当 (ruff/mypy 全 clean) |
| Evaluator 分離プロトコル | **適用** (8 files = 5+ 該当) |
| 6 並列 agent review | **適用** (code-reviewer / type-design-analyzer / silent-failure-hunter / comment-analyzer / pr-test-analyzer / evaluator、large tier) |
| Codex セカンドオピニオン | 不要相当 (8 files / 524 行で large tier だが 6 並列 review で代替) |
| 番号単位明示認可 merge | ✅ (CLAUDE.md 4 原則 §3 準拠、ユーザー「PR #327 をマージしてよい」を確認) |
| review 指摘 inline 反映 | **CRITICAL C1 + Important × 4 を 2 commit 目で反映** |

## ADR 状態

- 16 件、本セッションで新規 ADR なし
- 続編 H3 は ADR-014/-015 + PR #258/#267/#269/#270/#272 (続編 E) の延長線上で、新規 ADR を起こすほどの設計判断は含まれない (umbrella Issue #27 の段階的 immutability 強制パターンを踏襲)
- ADR-016 (Windows アプライアンス化) は Proposed のまま、状況変化なし

## 残留プロセス

✅ 残留 Node プロセスなし
