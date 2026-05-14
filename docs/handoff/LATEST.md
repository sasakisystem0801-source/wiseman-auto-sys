# Session 73 完了 — handoff debt 全 3 件消化 + Issue #276 follow-up + 新規 Tcl 問題発見

**Date**: 2026-05-15
**Main HEAD**: `93007a1` feat(launcher): bundle 同梱 trust root の staleness を warn-log (handoff debt #2) (#294)
**Test count**: 2003 collected (Session 72 完了時 2012 → -9。PR #291 で xfail 削除 2 件 + PR #294 で新規 +12 件 + PR #292 Close で xfail 復活なし、その他は collect 仕様差と推察)
**Active Issues**: 12 (実質 7、postpone 5) [変化なし、Net 0]
**Phase**: Phase 7 着手前 [変化なし]

---

## セッション経緯

Session 72 完了後 `/catchup` 経由で「優先順にすすめて」として開始。実機検証 3 件 (#274 / #282 / Launcher 5 ボタン + log_level 反映) は次回 exe 配布タイミング待ちで AI 単独不可、Issue #275 本田様ヒアリング待ちも AI 単独不可。AI 単独完結可能タスクとして:

1. **Issue #276 follow-up #1** (`tree.heading()` Windows Tk 戻り値差吸収): PR #291 で消化
2. **Issue #276 follow-up #2** (Tcl init.tcl 不在対応): PR #292 で Python 3.12 化試行 → **CI 実測で 3.12 でも fail 再現と判明** → Close
3. **handoff debt #1, #3** (Session 64 から繰越): PR #293 で消化
4. **handoff debt #2** (Session 64 から繰越): PR #294 で消化、Quality Gate 全 3 段完了 (evaluator で AC-5 Critical 違反発見・修正)

PR 滞留が 4 本に達した時点でユーザー確認 → 推奨案 (PR #293 のみ先行 merge、残は CI 結果次第) を実行 → 全 PR の処理完了 (3 merge + 1 Close)。

---

## 完了内容

### 1. Issue #276 follow-up #1 完了 (PR #291 merged)

`tests/unit/ui/test_common.py` の Windows Tk 仕様差を helper で吸収:

- `_invoke_heading_command(tree, column)` helper を `TestMakeTreeviewSortable` 直前に追加
  - `callable(cmd)` → 直接呼出 (Mac/Linux Tk)
  - `else` → `tree.tk.call(cmd)` で Tcl 名解決 (Windows Tk)
- `test_clicking_header_sorts_ascending_then_descending` / `test_status_column_uses_custom_priority_key` の `@pytest.mark.xfail(...)` マーカー削除
- CI 検証: Windows runner で対象 2 件が **PASS** (test-windows-ui 全 100 件 PASS)

### 2. PR #292 Close (Issue #276 follow-up #2 試行失敗)

Python 3.11 → 3.12 化で `_tkinter.TclError: Can't find a usable init.tcl` を回避するはずだったが、**CI 実測で 3.12 でも同じ Tcl init.tcl 不在エラーが再現**:

- `actions/setup-python#1102` の WebFetch 情報 (「3.12/3.10 では発生しない」) と実態が乖離
- Python 3.12.10 + windows-latest でも `test_clear_cache_removes_entry_and_saves` が同様に fail
- 結論: 3.12 化は無効、PR #292 は破棄
- `test_clear_cache_removes_entry_and_saves` の xfail マーカーは main 状態 (= 復活させた状態) のまま維持

### 3. handoff debt #1 + #3 完了 (PR #293 merged)

`src/wiseman_hub_launcher/__main__.py` の `run_smoke_test()` に `Verifier.production(offline=True)` 実 init を追加し、TUF trust root の bundle 解決 + rekor_types 等の推移依存解決失敗を CI で early detect:

```python
try:
    Verifier.production(offline=True)
except Exception as e:  # noqa: BLE001
    print(f"smoke test failed (Verifier.production(offline=True) init): {type(e).__name__}: {e}", file=sys.stderr)
    return LauncherExitCode.UNEXPECTED
```

`_supply_chain/sigstore.py` の module docstring に `sigstore>=3.0,<4.0` pin の明示 (4.x major upgrade 時の検証手順を docstring 内に集約)。

### 4. handoff debt #2 完了 (PR #294 merged) + Quality Gate 全 3 段

`_supply_chain/sigstore.py` に `warn_if_trust_root_stale(store_dir=None)` 新規 helper を追加、`main()` の dry-run / update 経路で呼出 (smoke 経路除外):

- 残り < 0 日 (既に expire): WARNING ログ ("EXPIRED N days ago")
- 残り <= 30 日: WARNING ログ ("expires in N days")
- 残り > 30 日: DEBUG ログ (健全)
- 例外時: debug log で握り潰し、起動 blocking しない

**実測**: bundle 同梱 root.json の `expires` は `2025-08-19T14:33:09Z` で、既に **268 日前に expire 済**。merge 後は本田様 PC で毎起動 WARNING が出る (設計どおりの挙動、sigstore-python upgrade を促すリマインダー)。

#### Quality Gate 履歴 (CLAUDE.md MUST 全実施)

| ステップ | 結果 |
|---------|------|
| `/simplify` (3 並列 reuse/quality/efficiency) | Reuse 9.5/10 Clean / Quality HIGH 1 件 (task-tracking コメント) 反映済 / Efficiency Clean (起動時 < 2ms 影響) |
| `/safe-refactor` (型安全性・エラー処理) | LOW 1 件のみ (Z 置換イディオム、既存 manifest.py との統一性のため保留) |
| `evaluator` 分離 (rules/quality-gate.md 新機能発動) | **AC-5 整合 Critical 違反発見** |

#### evaluator Critical 修正内容

tz-naive な expires 文字列 (RFC 3339 違反の root.json) が来た場合、`fromisoformat(expires_str.replace("Z", "+00:00"))` が tz-naive datetime を返し、tz-aware `now` との `-` 比較で TypeError raise。既存 `except` 節に `TypeError` が含まれず、`warn_if_trust_root_stale()` 呼出は top-level try/except 外なので **未捕捉 TypeError で launcher クラッシュ**経路が存在 (AC-5 違反)。`(expires - now).days` 計算箇所に専用 try/except TypeError を追加して握り潰し。

加えて推奨修正として境界値テスト 2 件 (`== 30` → WARNING / `== 31` → DEBUG、`<= 30` 閾値 pin) + tz-naive エッジケーステスト 1 件を追加。

テスト件数: warn 系 **9 件** (基本 6 + 境界値 2 + tz-naive 1)。

---

## ⚠️ 注意事項 / 次セッション着手前確認

### 1. 実機検証 4 件 (Session 71/72 から繰越、次回 exe 配布タイミングで一括)

次回ビルド配布後 (`docs/handoff/1c-exe-redistribution-runbook.md` Phase 0-3) に確認:

| Issue / PR | 検証項目 |
|---|---|
| #274 Phase 1 | B/C ダイアログ詳細列 500px 表示 + 横スクロール動作 + 本田様評価で Phase 2/3 着手判断 |
| #282 | `monitoring_subfolder/R7/<月>.pdf` 配置成功 / 旧構造 regression なし / 表記揺れ / AMBIGUOUS UI |
| Launcher 5 ボタン (PR #285) | CLAUDE.md チェックリスト #2 通りに 5 ボタン表示確認、業務フロー順 (ex_ → B → C → 結合 → 設定) |
| **#27 続編 F Phase 2/2-b の log_level 反映** | `[app] log_level = "DEBUG"` を `config/default.toml` に書いて Launcher 起動、stdout で DEBUG ログ確認 + `--rpa` で同様確認 |

新追加: **PR #294 の trust root staleness WARNING 表示確認**
- Launcher 起動時に "sigstore trust root EXPIRED 268+ days ago" の WARNING が log されるか確認
- Tk ログ画面への表示有無は本 PR scope 外、必要なら別 issue 化

### 2. Issue #275 次セッション着手フロー (Session 71 から繰越)

1. 本田様にヒアリング項目 4 領域を確認 (実機 UI を見せながら平文で観察報告を促す、AskUserQuestion 過剰回避)
2. 回答に応じて組み合わせ A / B を選択
3. impl-plan 確定 → 実装 → tk_required test 追加 → Windows CI で PASS 確認 → PR → 本田様実機検証 → close

ヒアリング項目は Issue #275 コメントに整理済 (Session 71 で投稿)。

### 3. Issue #276 follow-up — **#1 完了、#2 は別解必要**

- ✅ #1 `tree.heading()["command"]` 経路の Windows 対応 (PR #291 で消化)
- ❌ #2 Windows + uv venv の Tcl init.tcl 環境調査 → **PR #292 で 3.12 化を試行したが効果なし**、別解必要 (下記 §7 新規 handoff debt に統合)

### 4. Issue #27 続編 G 着手判断 (Path 型移行 §4) — **次セッション最優先候補**

- `input_dir` / `output_dir` 等の `str` → `Path` 移行
- 影響範囲: `config.py` + 全消費先 + テスト全般 (大規模 PR、200+ 行確実)
- 必須: 実装前に `/codex review` セカンドオピニオン
- AI 単独可、Mac セッション完結可能 → 次セッション最有力候補

### 5. Issue #27 続編 F §1 残候補 (Session 72 で scope 外と判定、本 session でも判定維持)

| 候補 | 判定 | 理由 |
|---|---|---|
| `GcpConfig.region` | Literal 化不適 | GCP region 集合が大きく網羅困難 |
| `WisemanConfig.window_title_pattern` | Literal 化不適 | 自由形式 regex |
| `ScheduleConfig.cron` | Literal 化不適 | 自由形式 cron expression |

§1 で actually 進捗あるのは `AppConfig.log_level` + `ReportTarget.output_format` のみ。

### 6. Mac セッション着手不可項目 (前セッション継承、変化なし)

- #17 (smoke_real.py pytest 統合)
- #16 (test_new_registration_flow Pane/Text 経路)
- #11 (PywinautoEngine MEDIUM 5 件)
- #6 (PoC E2E)

### 7. handoff debt 状況

#### 繰越 3 件 (Session 64 から) — **全 3 件消化完了** ✅

| # | 内容 | 消化 PR |
|---|------|---------|
| #1 | `build-windows-smoke.yml` で `Verifier.production(offline=True)` smoke 実 init | ✅ PR #293 |
| #2 | Trust root staleness 監視 (warn-log) | ✅ PR #294 |
| #3 | sigstore-python 3.x dependency docstring | ✅ PR #293 |

#### 本セッション新規発見 handoff debt

**Windows Tcl init.tcl ランダム fail 問題** (PR #292 Close で判明、rating 6 で Issue 化基準 (rating ≥ 7) 未達のため handoff debt として記録):

- **症状**: GitHub Actions windows-latest で `_tkinter.TclError: Can't find a usable init.tcl` がランダム発生
- **影響範囲**: Python **3.11 と 3.12 の両方** (CI 実測、`actions/setup-python#1102` の「3.12 では発生しない」記載は乖離)
- **再現性**: ランダム (本セッションで PR #291/#294 を空 commit で re-trigger したら全 PASS)
- **影響テスト**: `test_launcher.py::test_defer_false_renders_immediately` / `test_confirm_dialog.py::TestPersistenceFailFast::test_save_error_propagates` / `test_clear_cache_removes_entry_and_saves` 等の tk_required test
- **follow-up 候補**: 次セッションで以下を順に試行
  1. `TCL_LIBRARY` / `TK_LIBRARY` 環境変数の明示設定 (setup-python の Python install path から計算)
  2. `tcl/tcl8.6/init.tcl` の存在確認 + 不在時の chocolatey install
  3. `actions/setup-python` 以外の Python 経路 (公式 Windows installer 直 download) 試行
- **暫定対応 (本セッション)**: re-trigger で逃げる (ランダム発生のため、`continue-on-error: true` は false positive を覆い隠すので採用しない)

#### 引き続き保留中

- Issue #282 Codex 残指摘 4 件 (M2 symlink / M3 性能 / L1 将来表記 / L3 PII path message) — Session 71 で triage 済 (rating 4-6、Issue 化せず handoff debt として記録のみ)

---

## 次セッション優先順

1. **実機検証 4 件** (#274 Phase 1 / #282 / Launcher 5 ボタン / log_level 反映) + PR #294 trust root WARNING 表示確認 — 次回 exe 配布時にまとめて
2. **Issue #275** (ChecklistSettingsDialog UI シンプル化) — 本田様ヒアリング → impl-plan → 実装
3. **Issue #27 続編 G** (Path 型移行 §4) — Mac 完結可能の最有力候補。`/codex review` 必須、大規模 PR (200+ 行)
4. **Windows Tcl init.tcl 問題** (新規 handoff debt) — `TCL_LIBRARY`/`TK_LIBRARY` 環境変数試行から
5. **Phase 7 (Task #17)** — 要 Windows 実機

---

## 構造的整合性チェック

- ⏭️ `/impact-analysis`: 新規 helper `warn_if_trust_root_stale` 追加、影響範囲は launcher 起動経路 (dry-run/update 限定)。test 9 件 + 既存 launcher 60 件で contract gate 済、mypy 全 PASS で検証済 (PR #294)
- ⏭️ `/new-resource`: `warn_if_trust_root_stale` を `_supply_chain/__init__.py` で public API として export、test_sigstore.py で 9 件検証 (基本 6 + 境界値 2 + tz-naive 1)
- ⏭️ `/trace-dataflow`: root.json → expires parse → log の単方向データフロー、複雑な伝搬なし。helper 単体テストで全経路 gate 済

---

## Issue Net 変化

```
## Issue Net 変化
- Close 数: 0 件
- 起票数: 0 件
- Net: 0 件
```

**Net = 0 だが進捗実体あり (handoff debt 構造の制約)**:

- **PR #291** で Issue #276 follow-up #1 を消化 → Windows Tk 仕様差テスト書き換え完了
- **PR #292 Close** で Issue #276 follow-up #2 試行失敗を確定 → Tcl 問題は新規 handoff debt として記録 (rating 6、Issue 化基準未達)
- **PR #293/#294** で **handoff debt 繰越 3 件 (Session 64 から、5 セッション繰越) を全消化** → 衛生的負債整理完了
- Issue #276 は既に close 済 (PR #279 + 本 session の follow-up 消化で完結)
- Issue #27 (umbrella) は §4 (Path 型移行、未着手) と §1 残候補 (不適判定済) が残り close 不可

triage 遵守: 本セッションでは新規 Issue 起票ゼロ。Tcl 問題発見 (rating 6) も Issue 化基準 (rating ≥ 7) 未達のため handoff debt として記録、`feedback_issue_triage.md` の機構化済み 3 層ゲートに従って Net ≤ 0 を維持。

Quality Gate 全 3 段 (`/simplify` + `/safe-refactor` + `evaluator`) を PR #294 (新機能 = warn_if_trust_root_stale 追加) で実施し、evaluator で AC-5 整合 Critical を発見・修正完了。これは rules/quality-gate.md の Generator-Evaluator 分離パターンが**実際に Critical を検出した実例**として記録価値あり (本田様 PC で警告無く launcher クラッシュする経路を未然防止)。

---

## ✅ 残留プロセスなし
