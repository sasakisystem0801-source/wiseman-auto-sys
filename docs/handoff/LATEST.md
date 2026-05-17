# Session 85 完了 - Issue #16 / Issue #332 解消 + Issue #27 続編 G 実態調査完了 (PR #331/#333 マージ)

日時: 2026-05-17
HEAD (main): `d0b6332`
前セッション archive: [session-84-issue-27-debt-cleanup.md](./archive/session-84-issue-27-debt-cleanup.md)

## 本セッション完了内容

### Phase 1: Issue #27 続編 G (Path 移行) 実態調査完了

Session 84 で続編 F §1 (Literal 拡張) を「実質完了済」と確定したのに続き、続編 G (§4 Path 移行) を Mac 単独で再調査した結果、**こちらも実質完了済**と確定。Issue #27 に [investigative comment](https://github.com/sasakisystem0801-source/wiseman-auto-sys/issues/27#issuecomment-4469830366) を追記し、新規実装 PR なし。

#### 調査結果

`src/wiseman_hub/config.py` (1778 行) の全 dataclass フィールドを grep + 個別確認し、残存 `str` フィールド 16 件を Path 化適性で分類:

| 分類 | 件数 | フィールド例 |
|---|---|---|
| Path 化不適 (識別子 / pattern / template) | 11 | `window_title_pattern` (regex), `cron`, `project_id`, `region`, `api_key`, `source_b_pattern` (format string), `spreadsheet_id`, `version` |
| Path 化候補 (path 部品 / basename) | 5 | `PdfMergeConfig.source_a_filename` / `source_d_filename`, `ChecklistConfig.monitoring_subfolder` / `b_output_subfolder` / `c_output_subfolder` |

#### 5 候補の評価

**Pro**: 型自己記述性、TOML 入力で os 不正文字早期検出 (`_check_path` 再利用可)。

**Con**:
- TOML / UI 入力はいずれも `str` → 内部表現だけ Path 化する付加価値が小さい
- consumer は `Path / str` で正常動作 → 既存挙動を変えるリスクのみ発生
- basename-only な値を `Path` 型で持つのは pathlib 慣習に逆行 (pathlib 自身も basename は `Path.name: str` で返す)
- 続編 E (frozen=True) + H シリーズで immutability は構造的に完遂済、残務として Path 化する優先度低

#### umbrella Issue #27 の取り扱い

§1 §4 とも実質完了確定だが、過去 PR コメント (#258 / #259 / #260 / #261 の review 指摘) で「新規 Issue 起票せず本 umbrella に集約」と明記された rating 5-6 級の小修正候補が集約状態で残存 (TOML datetime メッセージ改善 / PII default 反転検討 / `reports` section の `_require_section_table` 統一)。これらの消化先確保のため、**umbrella Issue #27 は引き続き OPEN 維持**。

### Phase 2: PR #331 (merged `730d385`) - Issue #16 解消

PR #13 review I5 で指摘された「`select_care_system()` の Pane/Text 分岐 (PostMessage WM_LBUTTONDOWN/UP) が 1 度もテストされない」を解消。実装変更ゼロ、テストカバレッジ補完のみ。

#### 変更内容

`tests/unit/test_pywinauto_engine.py::TestSelectCareSystem` の `test_pane_fallback_uses_post_message` を `test_non_button_fallback_uses_post_message` に rename し、`pytest.mark.parametrize` で `Pane / Text / Hyperlink` の 3 control_type を網羅:

```python
@pytest.mark.parametrize(
    "matching_ct",
    ["Pane", "Text", "Hyperlink"],
    ids=["pane", "text", "hyperlink"],
)
def test_non_button_fallback_uses_post_message(...) -> None:
    ...
```

加えて `WM_LBUTTONDOWN` の wparam (`MK_LBUTTON=0x0001`) と `WM_LBUTTONUP` の wparam (`0`) もチェック追加 (マウスボタン状態整合性)。`_mock_user32.PostMessageW.reset_mock()` で parametrize 間の状態リーク防止。

#### 2 並列 light review

| Reviewer | Critical | Important | 結論 |
|---|---|---|---|
| code-reviewer | 0 | 0 | Merge 可 (Suggestion 2 件は informational) |
| pr-test-analyzer | 0 | **G1**: `target_hwnd == 0` 経路未カバー (rating 7、conf 80+) | Merge 推奨、G1 は別 Issue 化 |

`PR #331 — test(rpa): select_care_system の Pane/Text/Hyperlink 経路を parametrize 化 (Issue #16) (1 files, +33/-9)` 形式の番号認可受領、CI green 確認後 merge。

### Phase 3: Issue #332 起票 + PR #333 (merged `d0b6332`) で即解消

PR #331 pr-test-analyzer G1 (rating 7、conf 80+) を triage 基準充足で Issue #332 として新規起票 (`bug,P2`)、そのまま同セッション内で PR #333 として実装 → merge して close。

#### Issue #332 の対象

`PywinautoEngine.select_care_system()` (`src/wiseman_hub/rpa/pywinauto_engine.py:204`) の `if target_hwnd is None or target_hwnd == 0:` 分岐のうち、`target_hwnd == 0` 側が unit test で未カバー。UIA wrapper が一時無効化された瞬間 (comtypes COM プロキシ非同期破棄中、別アプリへのフォーカス切替直後等) に `wrapper.handle = 0` を返すケースで、ガード退化時に `PostMessageW(0, ...)` が `ERROR_INVALID_WINDOW_HANDLE` (1400) を返す silent failure 経路。

#### PR #333 の変更内容

`TestSelectCareSystem` に `test_target_hwnd_zero_raises` を追加 (実装変更ゼロ、structural guard の retention テスト 1 件):

| 検証項目 | assertion |
|---|---|
| ガード発火 | `pytest.raises(RuntimeError, match="ケア記録選択要素が見つかりません")` |
| `SendMessageW(0, ...)` 未呼出 | `call_args_list` フィルタで `args[0] == 0` 件数 = 0 |
| `PostMessageW(0, ...)` 未呼出 | 同上 |

`wrapper.handle = 0` を Button 分岐 (fallback 先頭) で意図的にマッチさせ、ガードが弾けば後続 fallback には流れず Send/PostMessage も hwnd=0 で呼ばれないはず。**ガード退化時は assert メッセージ「ガード退化: ...」で明示検出**される設計。

#### 1 並列 light review

| Reviewer | Critical | Important | 結論 |
|---|---|---|---|
| code-reviewer | 0 | 0 | Merge 可 (Suggestion 1 件 rating 5、scope 外) |

pr-test-analyzer は前 PR #331 で挙がった G1 の直接実装のため再実行不要と判断、code-reviewer 1 つに絞った。

#### CI flaky test 対処

初回 `test-windows-ui` が `_tkinter.TclError: invalid command name "tcl_findLibrary"` で fail (`test_confirm_dialog.py::TestPersistenceFailFast::test_save_error_propagates` の setup フェーズで `tk.Tk()` 自体が失敗、テストロジック未到達)。本 PR の変更は `test_pywinauto_engine.py` への +46 行のみで Tk 一切触らず、同様の最小 PR #331 は同 job で pass していたことから **transient な GitHub Actions runner 環境問題** (Issue #316 で議論されている本田様 PC 症状と類似) と判定し、re-run で pass 確認後 merge。

### 検証結果

| 項目 | 結果 |
|---|---|
| pytest -m "not integration" (Mac local) | Session 84 末 2163 → **2166 passed** (+3 件: parametrize 3 ケース置換で +2 + target_hwnd=0 ガードで +1)、120 skipped、回帰なし |
| ruff check src/ tests/ | All clean |
| mypy src/ | Success: no issues found (78 files) |
| CI PR #331 全 jobs | ✅ pass (build-smoke 4m3s / test-integration 2m23s / test-unit 3.11 50s / 3.12 54s / test-windows-ui 44s) |
| CI PR #333 全 jobs | ✅ pass (build-smoke 2m55s / test-integration 2m36s / test-unit 3.11 50s / 3.12 54s / test-windows-ui 52s re-run) |

## Issue Net 変化

```
Close 数: 2 件 (#16, #332)
起票数: 1 件 (#332)
Net: -1 件 ✅ (進捗あり)
```

- #16 (Pane/Text/Hyperlink 経路カバー) は PR #331 で `Closes #16` により auto-close
- #332 (target_hwnd=0 retention test) は本セッション内で起票 + PR #333 で `Closes #332` により auto-close、Issue Net では起票 1 件として計上 (同セッション close でも triage 基準を満たした起票は計上の上、close も計上する)

## 次セッション最優先タスク

### 1. **Issue #316 実機対処待ち** (本田様 PC、AI 着手不可)

`scripts/diagnose-tcl.ps1` を本田様 PC で 1 度実行してもらい、結果を Issue #316 にコメント。runbook Step 1-4 (Windows セキュリティ GUI 除外 / 第三者 AV / Python 再 install / uv-managed Python) を順試行。Session 83 から状況変化なし、本田様 PC TeamViewer アクセスの機会次第。

**本セッションで観測した補強情報**: PR #333 の CI `test-windows-ui` で `_tkinter.TclError: invalid command name "tcl_findLibrary"` が transient に発生 (re-run で pass)。本田様 PC の Tcl 症状と同根の可能性があり、Issue #316 調査時に GitHub Actions Windows runner の Tcl 環境差分 (Python 3.11.9 hostedtoolcache 配下) も比較対象に加える価値がある。

### 2. **Windows 実機で複数タスクの一括検証**

本田様 PC TeamViewer アクセスの機会ができたら以下を 1 セッションで消化:

- **Issue #316**: `scripts/deploy-windows.ps1` 実行 → Phase 0 Tcl エラー再現確認 → `diagnose-tcl.ps1` 実行 → runbook Step 1-4
- **Issue #274 Phase 1 動作確認**: exe 配布後、B/C ダイアログ「対象行を読込」で詳細列が 500px 表示 + 横スクロール出現を verify
- **Issue #17 実機検証**: `$env:WISEMAN_REAL = "1"` + `$env:WISEMAN_LNK_PATH = "<.lnk path>"` 設定で `uv run pytest tests/integration/test_smoke_real.py -m wiseman_real` → 1 passed 確認

### 3. **Issue #27 umbrella の小修正候補消化** (Mac 単独可)

§1 §4 とも実質完了確定後の残務として、過去 PR コメントで集約された rating 5-6 級の小修正候補:

- **TOML datetime メッセージの運用者向けヒント追記** (PR #259 silent-failure-hunter、rating 5-6)
- **PII default 反転検討**: `_check_str(echo_value=False)` (PR #260 type-design-analyzer、rating 5)
- **`reports` section の `_require_section_table` 統一 + `user_name_bbox` 名前付きエラー** (PR #261 silent-failure-hunter、rating 6)

scope が膨らまない範囲で 1-2 件ずつ消化して umbrella を縮小。

### 4. **active 残 Issue (Mac 単独可 / 待機状態)**

- **#275** ChecklistSettingsDialog GCP 同期ボタン UI シンプル化 — impl-plan たたき台あり、本田様ヒアリング 4 領域回答待ち

### 5. ポストポーン中 Issue (着手不可、ユーザー明示指示なき限り無視)

#245 / #170 / #161 / #134 / #39 (postponed ラベル、再開条件は各 Issue コメント参照)

## ハンドオフ debt

### 解消済み (本セッション)

- ✅ Issue #16 (PR #13 review I5 残件、Pane/Text/Hyperlink 経路カバー) を PR #331 で解消
- ✅ Issue #27 続編 G (Path 移行) の実態調査完了 → 実質完了済確定、新規実装不要を明確化
- ✅ Issue #332 (target_hwnd=0 silent failure 経路 retention test、PR #331 review G1 由来) を起票 + 即 PR #333 で解消
- ✅ test_pywinauto_engine.py の `TestSelectCareSystem` クラスを 2 ケース増強 (Pane 1 → Pane/Text/Hyperlink 3 + target_hwnd=0 = 計 5 ケース、`is None` 経路は `test_all_control_types_fail_raises` が継続カバー)

### 継続 (次セッション以降)

- Issue #316 実機対処 (本田様 PC AV 設定、本人の対応待ち)
- Issue #17 実機検証 (本田様 PC で WISEMAN_REAL=1 + WISEMAN_LNK_PATH 設定下の pytest 実行)
- Issue #274 / #275 (実機検証 + 本田様ヒアリング待ち)
- Issue #27 umbrella の小修正候補消化 (rating 5-6 級、scope 限定で機会消化)

### 未反映 review 指摘 (rating ≤ 5、後続 PR / コメント記録で OK)

- PR #331 code-reviewer Suggestion S1 (`pywinauto_engine.py:181` 行番号参照の rot リスク、rating 4): grep 復旧可能なため修正不要
- PR #331 code-reviewer Suggestion S2 (lparam pin、rating 3): 過剰検証になるため追加不要
- PR #333 code-reviewer Suggestion (autouse `reset_mock` fixture、rating 5): 本 PR scope 外、entry-reset パターンの既存慣習に従い対応見送り

## Quality Gate 適用状況

| 段階 | PR #331 (Issue #16) | PR #333 (Issue #332) |
|---|---|---|
| `/impl-plan` | スキップ (1 file, テスト追加のみ、Issue #16 が明確な scope) | スキップ (極小、scope 明確) |
| `/simplify` | スキップ (1 file <100 行) | スキップ (1 file <100 行) |
| `/safe-refactor` | 適用相当 (ruff/mypy/pytest 全 clean) | 適用相当 (同上) |
| Evaluator 分離プロトコル | 該当外 (1 file、5 files 未満) | 該当外 |
| Light tier review | **2 並列** (code-reviewer + pr-test-analyzer、testing 観点必須のため) | **1 並列** (code-reviewer のみ、pr-test-analyzer 再実行不要と判断) |
| Codex セカンドオピニオン | 不要 (small tier、テスト追加のみ) | 不要 (同上) |
| 番号単位明示認可 merge | ✅ CLAUDE.md 4 原則 §3 準拠、`PR #331 — ... (1 file, +33/-9)` 形式で要約 + CI green 確認後 `gh pr merge 331 --squash --delete-branch` | ✅ 同形式 `PR #333 — ... (1 file, +46/-0)`、CI flaky の `test-windows-ui` を re-run で transient 確認後 `gh pr merge 333 --squash --delete-branch` |
| review 指摘 inline 反映 | Important G1 は scope 外として別 Issue #332 化 (CRITICAL「Don't add features beyond what the task requires」遵守)、Suggestions rating ≤ 5 は handoff debt 記録 | Critical / Important なし、Suggestion 1 件は本 PR scope 外として継続記録 |

## ADR 状態

- 16 件、本セッションで新規 ADR なし
- テスト追加のみで設計判断を含まず、新規 ADR 起こすほどのアーキテクチャ変化なし
- ADR-016 (Windows アプライアンス化) は Proposed のまま、状況変化なし

## 残留プロセス

✅ 残留 Node プロセスなし
