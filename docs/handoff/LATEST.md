# Session 84 完了 - Issue #27 続編 F §1 実質完了済を確認 + 継続 debt 4 件消化 (PR #329 マージ)

日時: 2026-05-17
HEAD (main): `05c4e6e`
前セッション archive: [session-83-issue-27-h3-merge.md](./archive/session-83-issue-27-h3-merge.md)

## 本セッション完了内容

### PR #329 (merged `05c4e6e`): Issue #27 続編 - 継続 debt 4 件を一括消化

PR #324 / #325 review で rating 5-6 と評価された継続 debt 4 件を 1 PR で消化。続編 H シリーズ完遂後の文脈整合性を保ちつつ、scope は config.py / ui/settings.py / test_settings.py の 3 files に限定 (+77/-29 行)。

#### Phase 1 調査での重要発見: **続編 F §1 (Literal 拡張) は実質完了済**

impl-plan の Phase 1 として config.py の Literal 適用状況を実態調査した結果、**続編 F §1 の主要対象 3 Literal はすべて既に dataclass フィールドに実適用済**であることが判明:

| Literal 定義 (config.py:237-253) | 適用先 dataclass | 検証経路 |
|---|---|---|
| `LogLevel = Literal["DEBUG"..."CRITICAL"]` | `AppConfig.log_level: LogLevel` (L977) | `__post_init__` で `_check_literal` (L1002) |
| `OutputFormat = Literal["csv"]` | `ReportTarget.output_format: OutputFormat` (L399) | `__post_init__` で `_check_literal` (L405) |
| `ConcatSourceLetter = Literal["A","B","C"]` | `PdfMergeConfig.concat_order: tuple[ConcatSourceLetter, ...]` (L659) | `_coerce_concat_order` |

config.py:242 のコメント自体に「Issue #27 続編 F Phase 1: 離散集合制約フィールドの Literal 化」と明記されており、PR #328 の Session 83 handoff の「未着手」表現が古かった。

**残候補の実態**: 他 dataclass の文字列フィールド (`GcpConfig.region` / `WisemanConfig.window_title_pattern` / `ScheduleConfig.cron` / `PdfMergeConfig.source_*_pattern` / `UpdaterConfig.release_bucket`) はすべて自由値または GCP region のような開発時拡張余地のあるフィールドで、Literal 化不適。**続編 F §1 は新規実装の根拠なし**として scope 確定。

代替として、handoff の「未反映 review 指摘」5 件のうち continued debt 4 件 (rating 5-6) を一括消化する方針に切替。debt 5 (hotpath helper 化、rating 6-7) は PR #327 merge 時の「局所性とのトレードオフで見送り」判断を尊重して scope 外。

#### 消化した debt 4 件

| # | debt 内容 | 修正方針 | 場所 |
|---|---|---|---|
| 1 | PR #324 type-design Important #1: Sequence vs tuple rationale (rating 6) | `AppConfig` docstring に rationale 集約、leaf 側は参照 | `config.py:935+` / `:378+` / `:707+` |
| 2 | PR #325 type-design I-2: `decoupled_reports` 変数名 misleading (rating 5) | 変数削除 + 直書き、unused import 整理 | `ui/settings.py:215` |
| 3 | PR #325 comment-analyzer I-1: `_coerce_report_staff_entry` docstring 用語ずれ (rating 5-6) | 「coerce」統一 + TypeError 条件分離 + key 欠落フォールバック明示 | `config.py:1059` |
| 4 | PR #325 code-reviewer S-1: `_build_staff_table` の `isinstance(v, list)` dead code (rating 6) | 削除 + 削除根拠コメント | `config.py:1587` |

##### debt 1 (Sequence vs tuple rationale)

`AppConfig` docstring に新 block 追加。dataclass field 型 (immutability 契約) vs API 引数型 (受け入れ可能性契約) の使い分けを明文化。`Sequence[X]` の silent な list 経路を `tuple[X, ...]` で構造的に遮断する設計意図と、`navigate_menu(menu_path: Sequence[str])` 等の API 引数型では tuple/list 両受けで柔軟性を確保する使い分けを記述。`ReportTarget` / `ReportStaffEntry` docstring からは AppConfig 参照に集約 (重複排除)。

##### debt 2 (decoupled_reports 削除)

PR #272 由来の defensive shallow copy は続編 H1/H2 完了で不要になり PR #325 で削除済だが、`decoupled_reports` 変数名が「decouple している」という誤った印象を残していた。変数自体を削除し `replace(base, reports=base.reports, ...)` 直書きに変更。`reports=` 指定を残した意図 (PR #272 の経緯を読み手に思い出させる navigation hint) は隣接コメントで「冗長だが意図的に残す (DRY 違反として削除しないこと)」と明示。型注釈消失に伴い `ReportTarget` の unused import も削除。

##### debt 3 (_coerce_report_staff_entry docstring)

「強制変換」「正規化」「coerce」の混在を「coerce」に統一。TypeError 発火条件を 4 分岐に分離記述:
- キーが entry_data に存在し、かつ値が `list` 型でない
- キー存在 + 要素のいずれかが `str` でない
- **キー欠落時は raise せず、本関数内 `suggest_patterns_list = []` 初期化値を空 tuple に coerce して明示的に渡す** (`ReportStaffEntry` の dataclass default が triggered する誤解を排除、結果として default と同値)
- キー存在 + 空 list `[]` は正当 (空 tuple に coerce)

##### debt 4 (dead code 削除)

続編 H2 で `ReportStaffEntry.suggest_patterns` が tuple 化された結果、`asdict()` は tuple を tuple のまま保持し (`dataclasses` 仕様)、`isinstance(v, list)` 分岐は常に False で dead code 化していた。tomlkit が tuple を array に透過変換するため、削除しても動作上の差分なし (既存 roundtrip test `test_load_suggest_patterns` 系で検証済)。削除根拠と将来 list/tuple 型 field を追加する場合の確認方法をコメントで明示。

#### 2 並列 light review (light tier)

| Reviewer | Critical | Important | Suggestions |
|---|---|---|---|
| code-reviewer | 0 | 1 (test docstring 旧変数名参照、rating 6-7) → **inline 反映** | 2 (問題なし確認) |
| comment-analyzer | 0 | 3 (navigation hint 表現 / フォールバック源主体 / `rpa/base.py:80` 行番号 rot) → **全 inline 反映** | 3 (rating ≤ 5、後続 PR / コメント記録 OK) |

両 agent とも「Merge 可、Critical なし」判定。Important 4 件すべて 2 commit 目 (af33971) で inline 解消済。

#### 反映した review Important 4 件 (2 commit 目)

1. **code-reviewer Important #1**: `tests/unit/ui/test_settings.py:311` の docstring 内 `settings.py:219 の decoupled_reports` 旧変数名参照を新実装 (`replace(base, reports=base.reports, ...)` 直書き) に整合化
2. **comment-analyzer Important #1**: `ui/settings.py:217` の「`replace` のデフォルト挙動と等価」表現を「冗長だが意図的に残す (DRY 違反として削除しないこと)」に変更。次回読み手が「等価なら削除すべき」と判断する long-term comment rot を comment 自身で予防
3. **comment-analyzer Important #2**: `config.py:1093+` の suggest_patterns キー欠落フォールバック記述を「ReportStaffEntry の default にフォールバック」から「本関数内 suggest_patterns_list = [] 初期化値を空 tuple に coerce して明示的に渡す (結果として default と同値)」に修正
4. **comment-analyzer Important #3**: AppConfig docstring の `rpa/base.py:80` ハードコード行番号を `rpa.base.RPAEngine.navigate_menu` シンボル参照に変更 (line rot 予防)

### 検証結果

| 項目 | 結果 |
|---|---|
| pytest (Mac local) | 2163 passed (前 session と同数、回帰なし)、120 skipped |
| ruff check src/ / mypy src/ | All clean (78 source files) |
| pytest tests/unit/test_config.py | 434 passed |
| pytest tests/unit/ui/test_settings.py | 27 passed, 11 skipped (既存 Tk gating) |
| CI 1 commit 目 (bb5f75c) | ✅ 全 5 jobs pass (build-smoke 2m33s / test-integration 2m57s / test-unit 3.11 48s / test-unit 3.12 49s / test-windows-ui 41s) |
| CI 2 commit 目 (af33971、review 反映) | ✅ 全 5 jobs pass (build-smoke 3m20s / test-integration 2m31s / test-unit 3.11 43s / test-unit 3.12 47s / test-windows-ui 1m15s) |

## Issue Net 変化

```
Close 数: 0 件
起票数: 0 件
Net: 0 件
```

Net = 0 だが、これは「進捗ゼロ扱い」の悪い意味ではなく、**triage 基準を尊重して新規 Issue 化を抑制した結果**:

- 本セッションの主成果は continued debt 4 件の消化 + 続編 F §1 実質完了済の確認で、いずれも既存 umbrella Issue #27 配下の internal cleanup
- review 指摘 (Important rating 6-7) はすべて inline 反映で消化 → 新規 Issue 化不要
- continued debt 5 (hotpath helper 化、rating 6-7) は PR #327 merge 時の「局所性トレードオフで見送り」判断を尊重して scope 外、新規 Issue 化せず PR #327 コメント既記録のまま継続

Issue #27 umbrella は引き続き OPEN (続編 G 残り Path 移行のため意図的)。続編 F §1 完了確認のみで主要スコープは残作業 §4 Path 移行に絞られた。

## 次セッション最優先タスク

### 1. **Issue #316 実機対処待ち** (本田様 PC、AI 着手不可)

`scripts/diagnose-tcl.ps1` を本田様 PC で 1 度実行してもらい、結果を Issue #316 にコメント。runbook Step 1-4 (Windows セキュリティ GUI 除外 / 第三者 AV / Python 再 install / uv-managed Python) を順試行。Session 83 から状況変化なし、本田様 PC TeamViewer アクセスの機会次第。

### 2. **Windows 実機で複数タスクの一括検証**

本田様 PC TeamViewer アクセスの機会ができたら以下を 1 セッションで消化:

- **Issue #316**: `scripts/deploy-windows.ps1` 実行 → Phase 0 Tcl エラー再現確認 → `diagnose-tcl.ps1` 実行 → runbook Step 1-4
- **Issue #274 Phase 1 動作確認**: exe 配布後、B/C ダイアログ「対象行を読込」で詳細列が 500px 表示 + 横スクロール出現を verify
- **Issue #17 実機検証**: `$env:WISEMAN_REAL = "1"` + `$env:WISEMAN_LNK_PATH = "<.lnk path>"` 設定で `uv run pytest tests/integration/test_smoke_real.py -m wiseman_real` → 1 passed 確認

### 3. **Issue #27 続編 G 残り** (Path 移行、Mac 単独着手可)

続編 F §1 が実質完了済と確定したため、umbrella Issue #27 の残スコープは §4 Path 移行のみ。続編 G Phase 3a で一部完了済 (`karte_root` / `fax_root` / `ReportStaffEntry.base_dir`)、残りの str→Path 候補があるか config.py 全体を再調査して着手判断する。consumer 影響あり、`/codex` セカンドオピニオン推奨。

### 4. **active 残 Issue (Mac 単独可 / 待機状態)**

- **#16** test_new_registration_flow: Pane/Text 経路 (WM_LBUTTON) をカバー — Mac 単独可、`/tdd` で完結する小規模
- **#275** ChecklistSettingsDialog GCP 同期ボタン UI シンプル化 — impl-plan たたき台あり、本田様ヒアリング 4 領域回答待ち

### 5. ポストポーン中 Issue (着手不可、ユーザー明示指示なき限り無視)

#245 / #170 / #161 / #134 / #39 (postponed ラベル、再開条件は各 Issue コメント参照)

## ハンドオフ debt

### 解消済み (本セッション)

- ✅ continued debt 4 件 (PR #324/#325 review rating 5-6) を PR #329 で一括消化
- ✅ Issue #27 続編 F §1 (Literal 拡張) の実態調査完了 → 実質完了済確定、新規実装不要を明確化
- ✅ Sequence vs tuple rationale を AppConfig docstring に集約 (PR #324 type-design Important #1 対応)
- ✅ `_build_staff_table` dead code 削除 (PR #325 code-reviewer S-1 対応)
- ✅ ハードコード行番号 (`rpa/base.py:80`) を `rpa.base.RPAEngine.navigate_menu` シンボル参照に変更 (line rot 予防)

### 継続 (次セッション以降)

- Issue #316 実機対処 (本田様 PC AV 設定、本人の対応待ち)
- Issue #17 実機検証 (本田様 PC で WISEMAN_REAL=1 + WISEMAN_LNK_PATH 設定下の pytest 実行)
- Issue #27 続編 G 残り (Path 移行) — umbrella の最後のスコープ
- Issue #274 / #275 (実機検証 + 本田様ヒアリング待ち)

### 未反映 review 指摘 (rating ≤ 5、後続 PR / コメント記録で OK)

- PR #329 comment-analyzer Suggestion #4: `_build_staff_table` dead code 削除コメントの「将来 list field 追加時の確認方法」のヒント強化 (rating 4)
- PR #329 comment-analyzer Suggestion #5: PR #260 番号参照のアクセス容易性 (rating 5、本 repo 慣習で許容範囲)
- PR #329 comment-analyzer Suggestion #6: AppConfig docstring の block 見出し引用による cross-reference アクセシビリティ向上 (rating 5)
- PR #325 code-reviewer S-1 補遺: `_build_staff_table` 周辺の helper 再整理は将来 list 型 field 追加時に再評価
- PR #327 code-reviewer I-1: hotpath 3 箇所 `_update_checklist_field()` helper 化 (rating 6-7、局所性トレードオフで継続見送り)

## Quality Gate 適用状況

| 段階 | PR #329 (debt 消化) |
|---|---|
| `/impl-plan` | **適用** (3 ステップ以上、impl-plan skill 経由で Phase 1 調査 + Phase 2 タスク分解 + Phase 2.7 AC 定義) |
| `/simplify` | スキップ (2-3 files、小規模、docstring 中心) |
| `/safe-refactor` | 適用相当 (ruff/mypy/pytest 全 clean) |
| Evaluator 分離プロトコル | 該当外 (3 files、5 files 未満) |
| 2 並列 light review | **適用** (code-reviewer + comment-analyzer、small tier、6 並列は過剰判断) |
| Codex セカンドオピニオン | 不要 (3 files / 77 行で small tier、debt 消化 + docstring 中心) |
| 番号単位明示認可 merge | ✅ (ユーザー「CI 全 pass 確認したら merge お願い」を事前認可として、CI green 確認後に gh pr merge 329 --squash --delete-branch 実行) |
| review 指摘 inline 反映 | **Important × 4 を 2 commit 目で全反映** (Critical 0、Suggestions rating ≤ 5 は本ハンドオフ debt 記録のみ) |

## ADR 状態

- 16 件、本セッションで新規 ADR なし
- continued debt 消化 + docstring 更新は ADR-014/-015 + PR #258/#267/#269/#270/#272/#324/#325/#327 (続編 E/H シリーズ) の延長線上で、新規 ADR を起こすほどの設計判断は含まれない
- ADR-016 (Windows アプライアンス化) は Proposed のまま、状況変化なし

## 残留プロセス

✅ 残留 Node プロセスなし
