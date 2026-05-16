# Session 82 完了 - Issue #17 close + Issue #27 続編 H1/H2 完遂 (PR #323/#324/#325 マージ)

日時: 2026-05-16
HEAD (main): `66ae0ff`
前セッション archive: [session-81-multi-staff-t2-t10-merge.md](./archive/session-81-multi-staff-t2-t10-merge.md)

## 本セッション完了内容

### PR #323 (merged `b49c5de`): smoke_real.py を pytest に統合し WISEMAN_REAL=1 でゲート (Issue #17 close)

`scripts/smoke_real.py` の 3 ステップ E2E (launch → care system → new registration) を `tests/integration/test_smoke_real.py` で pytest assert 化。CI ゲート設計の実装で、実機検証は次セッション以降。

#### 実装内容

| ファイル | 変更内容 |
|---|---|
| `pyproject.toml` | pytest markers に `wiseman_real` 追加 |
| `tests/integration/conftest.py` | `WISEMAN_REAL=1` 時に `build_mock_app` autouse fixture を skip (MSBuild 不要、本田様 PC 環境対応) |
| `tests/integration/test_smoke_real.py` | 新設 (87 行)、`WISEMAN_REAL=1` でゲート、`WISEMAN_LNK_PATH` 必須 |
| `scripts/smoke_real.py` | docstring に pytest 経路追記 (旧 manual 経路も維持) |

#### Quality Gate 結果

| Reviewer | 判定 | 反映 |
|---|---|---|
| code-reviewer | merge 推奨 | — |
| pr-test-analyzer | merge ready | — |
| **silent-failure-hunter** | **Critical C1/C2 inline 修正推奨** | **C1: `contextlib.suppress(Exception)` → `try/except + logger.exception` (silent leak 防止)。C2: 各 step 後の最小 assert 追加 (`_launcher_window` / `_main_window` / frmKihon 存在検証)** |
| comment-analyzer | merge OK | — |

### PR #324 (merged `8a5393d`): AppConfig.reports を list → tuple 化 (Issue #27 続編 H1)

umbrella Issue #27 続編 H1: mutable leaf 免疫化の第 1 段。`AppConfig.reports: list[ReportTarget]` → `tuple[ReportTarget, ...]` に変更し、frozen=True (PR #272) と合わせて `cfg.reports.append(...)` / `cfg.reports[0] = ...` を `AttributeError` / `TypeError` で構造的に阻止。

#### 実装内容

- `config.py`: 型変更 + `__post_init__` isinstance(tuple) + `load_config` で TOML list → tuple coerce + `_update_reports` 引数型変更 + docstring 更新
- `ui/settings.py`: `form_to_config` の `decoupled_reports` を list comprehension → tuple comprehension 化 + `ReportTarget` import
- `tests/unit/test_config.py`: `cfg.reports.append(...)` 4 件を `replace()` 経由に書き換え + mutation 仕様逆転テスト (`test_app_config_reports_tuple_content_mutation_blocked`)

#### Quality Gate 結果

| Reviewer | 判定 | 反映 |
|---|---|---|
| code-reviewer | merge 推奨、I-1 (rating 6, conf 88) | **4/4 共通指摘 C1 inline 反映** |
| type-design-analyzer | **Critical: ReportTarget docstring rot** | 4 軸平均 **8.5/10** |
| silent-failure-hunter | 0 | — |
| comment-analyzer | **Critical #1 + Important #2 (report_staff 抜け)** | **C2 inline 反映** |
| pr-test-analyzer | **#1 rating 7 (form_to_config tuple verify)** | **C3 inline 反映 (TestFormToConfig +2 件)** |

3 件の Critical / Important を inline 反映: ReportTarget docstring を H1 反映に更新 + AppConfig mutable leaf 列挙に `report_staff` 追加 + `test_form_to_config_preserves_reports_as_tuple` / `test_form_to_config_cuts_menu_path_alias` 2 件追加。

### PR #325 (merged `66ae0ff`): ReportTarget.menu_path / ReportStaffEntry.suggest_patterns を list → tuple 化 (Issue #27 続編 H2)

umbrella Issue #27 続編 H2: H1 で残された mutable leaf list の構造的 immutability 強制を完遂。

#### 実装内容

- `config.py`: `_check_list_of_str` → `_check_tuple_of_str` rename + 2 dataclass 型変更 + `load_config` / `_coerce_report_staff_entry` の coerce + docstring 更新
- `ui/settings.py`: `form_to_config` の PR #272 暫定 defensive shallow copy 削除 (`base.reports` 直接渡し、leaf も immutable で alias 無害)
- `ui/checklist_settings_dialog.py` / `cloud/mapping_sync.py`: suggest_patterns accumulate → tuple 化
- `rpa/{base,mock_engine,pywinauto_engine}.py`: `navigate_menu` 引数型を `Sequence[str]` に拡張 (tuple/list 両対応)
- `tests/` (10 ファイル): 全 list リテラル → tuple、assertion 追随、helper test rename、regression guard 2 件 (`test_report_target_menu_path_tuple_content_mutation_blocked` / `test_report_staff_entry_suggest_patterns_tuple_content_mutation_blocked`)

#### Quality Gate 結果 (large tier、6 並列 review)

| Reviewer | 判定 | 反映 |
|---|---|---|
| code-reviewer | merge 推奨 | — |
| type-design-analyzer | I-1 (Sequence foot-gun rating 6.5) | 4 軸平均 **8.5/10** (H1 と同水準) |
| pr-test-analyzer | **#1 #2 rating 7 (isinstance verify) + Q1 (identity sharing assert)** | **3 件 inline 反映** |
| silent-failure-hunter | APPROVE | — |
| comment-analyzer | merge OK | — |
| evaluator | (途中 stuck、結果取得失敗) | 他 5 reviewer で判定 |

**3 reviewer 共通指摘 navigate_menu Sequence[str] foot-gun を inline 反映**: `engine.navigate_menu("ABC")` で `["A","B","C"]` に分解される silent corruption を防ぐ runtime guard を `MockEngine` / `PywinautoEngine` の navigate_menu 冒頭に追加 + `test_navigate_menu_accepts_tuple` / `test_navigate_menu_rejects_bare_str` の 2 件追加。

### 検証結果 (各 PR 共通)

| 項目 | 結果 |
|---|---|
| pytest (Mac local) | PR #323 完了時 **2140 passed**、PR #324 完了時 **2142 passed** (+2)、PR #325 完了時 **2146 passed** (+4) |
| ruff check / mypy / flake8 | All clean (本 PR 由来エラーなし、既存 E999 は main にも存在) |
| CI Unit Tests (macOS/Linux 3.11/3.12) | ✅ success (3 PR 全) |
| CI Windows UI Tests | ✅ success (3 PR 全) |
| CI Windows Integration Tests | ✅ success (3 PR 全) |
| CI Build Windows Smoke | ✅ success (3 PR 全) |

## Issue Net 変化

```
Close 数: 1 件 (#17)
起票数: 0 件
Net: -1 件 (進捗あり)
```

Net ≤ 0 を満たす理由: Issue #17 (smoke_real pytest 統合) を PR #323 で close。新規起票は本セッションで発生せず、umbrella Issue #27 への続編 H1/H2 進捗反映のみ (H3 残作業のため umbrella OPEN 維持)。

## 次セッション最優先タスク

### 1. **Issue #316 実機対処待ち** (本田様 PC、AI 着手不可)

`scripts/diagnose-tcl.ps1` を本田様 PC で 1 度実行してもらい、結果を Issue #316 にコメント。runbook Step 1-4 (Windows セキュリティ GUI 除外 / 第三者 AV / Python 再 install / uv-managed Python) を順試行。

### 2. **Issue #17 実機検証** (本田様 PC、TeamViewer 経由)

`$env:WISEMAN_REAL = "1"` + `$env:WISEMAN_LNK_PATH = "<.lnk path>"` を設定して `uv run pytest tests/integration/test_smoke_real.py -m wiseman_real` を実行 → 1 passed 確認。失敗時の挙動 (LNK_PATH 不在 → `pytest.fail`、Wiseman 起動失敗 → engine 例外伝播) も確認可能。

### 3. **Issue #27 続編 H3** (AI 単独着手可能、ホットパス書き換え必要)

`ChecklistConfig.{facility_routing, report_staff, xlsx_path_cache, staff_choice_cache}` の 4 dict を immutable 化。`checklist_c_dialog.py:746,804` の `cache[k] = ...` ホットパスを `replace(cfg.checklist, ...)` に書き換える侵襲的 PR シリーズ。**毎回 ChecklistConfig 全体を再生成するコストが発生するため、xlsx 選択 / staff 確定時のパフォーマンスを実機で検証してから本格着手するのが安全**。

### 4. **active 残 Issue (実機 + ヒアリング待ち)**

- **#274** B/C 自動配置ダイアログ「詳細」列の見切れ (Phase 1 完了済、実機検証待ち)
- **#275** ChecklistSettingsDialog GCP 同期ボタン UI シンプル化 (impl-plan たたき台あり、本田様ヒアリング 4 領域回答待ち)

### 5. ポストポーン中 Issue (着手不可、ユーザー明示指示なき限り無視)

#245 / #170 / #161 / #134 / #39 (postponed ラベル、再開条件は各 Issue コメント参照)

## ハンドオフ debt

### 解消済み (本セッション)

- ✅ Issue #17: smoke_real.py を pytest に統合し WISEMAN_REAL=1 でゲート (PR #323 close)
- ✅ Issue #27 続編 H1: AppConfig.reports tuple 化 (PR #324 merge)
- ✅ Issue #27 続編 H2: ReportTarget.menu_path / ReportStaffEntry.suggest_patterns tuple 化 + navigate_menu bare-str guard (PR #325 merge)
- ✅ Codex Medium 2 件 triage 判断 (Session 81 持ち越し): `|` 区切り衝突は実機データ確認後判断、frozen dict 直接変更は続編 H3 で一括対応 → Issue 化なし

### 継続 (次セッション以降)

- Issue #316 実機対処 (本田様 PC AV 設定、本人の対応待ち)
- Issue #17 実機検証 (本田様 PC で WISEMAN_REAL=1 + WISEMAN_LNK_PATH 設定下の pytest 実行)
- Issue #27 続編 H3 (ChecklistConfig dict 群 immutable 化、ホットパス書き換え)
- Issue #274 / #275 (実機検証 + 本田様ヒアリング待ち)

### 未反映 review 指摘 (rating ≤ 6、PR コメント or 続編 H3 PR で取り込み候補)

- PR #324 type-design Important #1: `Sequence` vs `tuple` rationale の docstring 追記 (rating 6)
- PR #325 type-design I-2: `decoupled_reports` 変数名 misleading (rating 5、続編 H3 で touch するファイルで同時 rename 推奨)
- PR #325 comment-analyzer I-1: `_coerce_report_staff_entry` docstring 用語ずれ (rating 5-6)
- PR #325 code-reviewer S-1: `_build_staff_table` の `isinstance(v, list)` dead code (rating 6、tomlkit 透過変換で動作中、次回 helper 整理時に対応)

## Quality Gate 適用状況

| 段階 | PR #323 (Issue #17) | PR #324 (#27 H1) | PR #325 (#27 H2) |
|---|---|---|---|
| `/simplify` | スキップ (4 files、小規模) | スキップ (3 files) | スキップ (16+ files だが型変更の機械的反映) |
| `/safe-refactor` | 適用相当 (ruff/mypy/flake8 全 clean) | 適用相当 | 適用相当 |
| Evaluator 分離プロトコル | 該当外 (4 files) | 該当外 (3 files) | **適用** (5+ files、evaluator 並列起動、途中 stuck) |
| 4 並列 agent review | **適用** (code-reviewer / pr-test-analyzer / silent-failure-hunter / comment-analyzer) | — | — |
| 5 並列 agent review | — | **適用** (4 並列 + type-design-analyzer) | — |
| 6 並列 agent review | — | — | **適用** (5 並列 + evaluator、large tier) |
| Codex セカンドオピニオン | 不要 (4 files / 103 行) | 不要 (3 files / 142 行) | 不要相当 (16 files / 268 行で境界だが 6 並列 review で代替) |
| 番号単位明示認可 merge | ✅ (CLAUDE.md 4 原則 §3 準拠) | ✅ | ✅ |

## ADR 状態

- 16 件、本セッションで新規 ADR なし
- 続編 H1/H2 は ADR-014/-015 の延長線上で、新規 ADR を起こすほどの設計判断は含まれない (umbrella Issue #27 の段階的 immutability 強制パターンを踏襲)
- ADR-016 (Windows アプライアンス化) は Proposed のまま、状況変化なし

## 残留プロセス

✅ 残留 Node プロセスなし
