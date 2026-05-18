# Session 89 完了 - Issue #274 close (Phase 1 追加修正で実機 UX 完成) + Issue #316 retry 実機実証

日時: 2026-05-18
HEAD (main): `a820d41` (本セッション merge)、handoff PR で更新予定
前セッション archive: [session-88-issue-11-closed.md](./archive/session-88-issue-11-closed.md)

## セッション概要

ユーザーから「Windows 側処理を優先的に再開」の指示を受け、本田様 PC (TeamViewer) で Issue #274 Phase 1 実機検証に着手。**Phase 1 PR #280 配布済 exe で実機検証したところ、ダイアログ初期幅 780x520 が 5 列合計 1020px の詳細列を画面外に押し出していた問題が発覚**。Mac 側で即修正 PR (#348) 作成・merge → 本田様 PC で再 deploy → 実機で「B/C とも読みやすくなった」評価獲得 → **Issue #274 close**。

主要成果:

- **PR #347 マージ**: `.gitignore` に WisemanMock C# build artifacts + diagnostic outputs 追加 (housekeeping)
- **PR #348 マージ**: B/C ダイアログ初期 geometry 780x520→1100x600 + retention テスト (Issue #274 Phase 1 追加修正)
- **Issue #274 close** (Phase 1 完遂: 列幅拡大 PR #280 + geometry 拡大 PR #348 + 本田様評価で B/C とも完了)
- **Issue #316 retry 機構実機実証**: 本田様 PC pytest で `2310 passed, 1 rerun in 30.63s` を確認、retry 吸収が production 環境で動作することを実証
- **active Issue**: 4 (#6, #27, #274, #275) → **3** (#6, #27, #275)

## 本セッション完了内容

### Phase 1: 状況把握と方向選択

`/catchup` 結果 → 「Windows 側処理を優先的に再開」指示。Session 88 と同じ文脈で active Issue (#6/#274/#275) は外部条件待ち。AskUserQuestion で「本田様 PC で実機反映・検証 (TeamViewer)」を選択 → Issue #274 Phase 1 実機検証に着手。

### Phase 2: 実機状況確認 + git pull + .gitignore PR

本田様 PC PowerShell で:
- HEAD `68054d2` (Session 87 完了時点、Session 88 の `0ae15d1` まで 3 commits 後ろ)
- pytest 実行で **`2310 passed, 1 rerun in 30.63s`** = Issue #316 retry 機構の実機実証 ✅
- untracked 4 件 (`mock_wiseman_app/WisemanMock/{bin,obj}/`, `diagnose-output.txt`, `pytest-retry-verify.txt`) が `.gitignore` 未登録判明
- `git pull` で `0ae15d1` まで fast-forward (production 影響ゼロの docs + test ファイルのみ)

→ Mac 側で並行 **PR #347** (`.gitignore` 4 件追加) 作成・push (commit `9308ebd`)。

### Phase 3: Issue #274 Phase 1 実機検証 → 問題発見

本田様 PC で Launcher 起動 → B ダイアログを開いてスクショ確認:
- **詳細列ヘッダ「詳細」が画面外** で見えない (4 列 [氏名/居宅/担当/ステータス] のみ表示)
- ダイアログを横に広げると詳細列が見える → 初期表示で UX 完成度が不十分

ソース確認: `src/wiseman_hub/ui/checklist_b_dialog.py:61` で `self._top.geometry("780x520")` 設定、5 列合計 1020px に対し 240px 不足。`stretch=True` も初期幅では効かず詳細列が画面外。

### Phase 4: Phase 1 追加修正 PR #348 実装

`fix/issue-274-phase1-dialog-geometry` ブランチで:
- `checklist_b_dialog.py:61` `geometry("780x520")` → `geometry("1100x600")` + コメント
- `checklist_c_dialog.py:170` 同上 (B と feature parity)
- `tests/unit/ui/test_checklist_dialogs_geometry.py` 新規作成 (initial geometry + column message width/stretch + xscrollcommand 接続の retention テスト、`@pytest.mark.parametrize` で B/C 両方検証)

#### Quality Gate

| 段階 | 結果 |
|---|---|
| `/simplify` 3 並列 | Reuse / Efficiency clean、Quality I#1 (parametrize 化、rating 6 conf 85) 採用 → 2 メソッド → 1 メソッド + parametrize に圧縮 |
| Medium tier 4 並列 review | 採用 5 件 (T1+C1 update_idletasks、T2+I1 column retention 追加、CO1 C dialog コメント圧縮、CO2 docstring/定数重複削減、C2 xfail を `condition=sys.platform == "win32"` で Windows 限定) |
| `/safe-refactor` | skip (production code 1 行 + コメント変更、test code mypy clean) |
| ruff/mypy/pytest | ✅ 全 PASS、`pytest -m "not integration"` で 2196 passed, 122 skipped, 回帰なし |
| CI 5/5 SUCCESS | ✅ build-smoke / test-integration / test-unit 3.11/3.12 / test-windows-ui 全 SUCCESS |
| ユーザー番号単位明示認可 | ✅ `#347 #348 マージしてよい` |

### Phase 5: 本田様 PC で再 deploy → 実機検証

本田様 PC で:
- `git pull` で `0ae15d1..a820d41` fast-forward
- `.\scripts\deploy-windows.ps1` 実行: Phase 0 (pytest `2310 passed, 2 xfailed, 3 xpassed, 1 rerun`) → Phase 1 (clean build 80.4 MB, warning なし) → Phase 2 (exe 上書き、`y` 認可) → Phase 3 (Launcher 起動 1 プロセス) → Phase 4 (人手判定)
- Launcher 「Wiseman PDF ツール」起動 (コンソール窓なし、5 ボタン構成) ✅

B ダイアログを開いて検証:
- ✅ **5 列ヘッダ「氏名/居宅/担当/ステータス/詳細」全て初期表示で見える** (Phase 1 fix 成功)
- ✅ 横スクロールバー下端表示
- ✅ 「対象行を読込」後 53 件表示、行ダブルクリックで Explorer フォルダオープン (既存業務動線維持)

C ダイアログを開いて検証:
- ✅ 詳細列ヘッダ初期表示で見える (Phase 1 fix 効果)
- 🔍 **新発見**: C ダイアログは 6 列構成 (`xlsx` 列追加、合計 1240px 要求)、1100px geometry では 140px 不足だが `stretch=True` で動的調整して機能
- 「対象行を読込」後 82 件表示、`xlsx` 列にファイル名表示

本田様評価: **「B/C とも読みやすくなった」** ✅

### Phase 6: Issue #274 close

Issue #274 にコメント投稿で Phase 1 完了経緯 (PR #280 + PR #348 + 本田様評価 + C ダイアログ 6 列新発見) を記録 → `gh issue close 274 --reason completed` 実行。

## 学んだこと (今セッション固有の知見)

### 「初期 geometry 未指定」は ttk.Treeview の stretch=True で隠蔽されやすい silent UX 不具合

Phase 1 PR #280 では column message=500 + stretch=True + 横スクロールバーで「詳細列を読める」設計だったが、Toplevel の初期幅が不足していると stretch では救済できない (Treeview の column width はリクエスト値、画面外押し出しは別問題)。

開発時の Mac で `tk.geometry("780x520")` を見ても問題に気付きにくく (Tk 非同梱 uv venv で skip)、Windows 実機の初期表示で初めて発覚。**今後 Treeview 列追加・拡大時は Toplevel geometry が `sum(column widths) + 余白` を満たすかをコードレビューで明示確認すべき** → 新規 memory 化候補 (本セッション末尾で要否判断)。

### medium tier review C2 「xfail strict=False が permanent silent」採用の意義

silent-failure-hunter rating 9 conf 90 の指摘で `condition=sys.platform == "win32"` を追加したが、本セッションでは Mac で skip / Windows runner で xfail として処理。`condition=` の効果は将来 Issue #276 (Windows + uv venv の Tcl init.tcl 不在) が解決された時に retention テストが Windows でも実機検証として復活する経路を残すこと。今すぐの値はなくとも、設計負債を残さない判断として価値あり。

### C ダイアログ 6 列構成の発見は scope creep を避けて Phase 2 候補に温存

本 PR #348 着手時点で B/C 両方の geometry を一律 1100x600 に拡大したが、C ダイアログが 6 列 (xlsx 列追加) で 1240px 要求と判明。本田様評価で十分と判定されたため Phase 2 着手不要、ただし将来 C ダイアログで詳細列が窮屈と感じた場合のみ Phase 2 (geometry を 1340 等に拡大) を triage する旨を Issue #274 close コメントに明記。

## Quality Gate 適用状況

| 段階 | PR #347 (.gitignore) | PR #348 (Phase 1 fix) |
|---|---|---|
| `/impl-plan` | スキップ (1 file housekeeping) | スキップ (修正方針明確 + 1-2 行 × 2 ファイル) |
| `/simplify` | スキップ (1 file / 8 行) | ✅ 3 並列、Quality I#1 採用 (parametrize 化) |
| `/safe-refactor` | スキップ | スキップ (透明性のため PR description で skip 理由明記) |
| Evaluator 分離プロトコル | 該当外 | 該当外 (3 ファイル) |
| Medium tier 4 並列 review | 軽量チェックリスト review | ✅ 4 並列、採用 5 件反映 |
| Codex セカンドオピニオン | 不要 | 不要 (Phase 1 PR #280 と同パターンで先例あり) |
| 番号単位明示認可 merge | ✅ `#347 #348 マージしてよい` | 同左 |
| CI 5/5 SUCCESS | ✅ | ✅ |

## ADR 状態

- 新規 ADR なし
- 既存 ADR-009 (Tkinter UI) の補足知見として Phase 1 追加修正の経緯は Issue #274 コメント記録で完結 (ADR 追加不要)
- 既存 ADR (001-017): 状況変化なし、変更不要

## 残留プロセス

✅ 残留 Node プロセスなし

## CI 状態

main `a820d41` の CI:
- ✅ PR #347 マージ時点で 5/5 SUCCESS
- ✅ PR #348 マージ時点で 5/5 SUCCESS

本 handoff PR push 後の main CI は走行予定。

## Issue Net 変化 (CLAUDE.md MUST)

- **Close 数**: 1 件 (#274)
- **起票数**: 0 件
- **Net: -1 件 ✅** (CLAUDE.md MUST「Net ≤ 0 は進捗ゼロ扱い」をクリア)

セッション開始時: open active 4 + postponed 5 = 9
セッション終了時: open active 3 + postponed 5 = 8

## 次セッション最優先

### AI 単独で着手可能 (decision-maker 判断不要)

1. **Issue #27 umbrella 残務消化判断**
   - 残務: PII default 反転検討 (`_check_str(echo_value=False)`、rating 5、ユーザー判断待ち)
   - umbrella close の最終トリガー
   - 着手時はユーザーに方針確認 (decision-maker 領分)

### 外部条件待ち (AI 着手不可)

2. **Issue #275 本田様ヒアリング 4 領域**: impl-plan たたき台投稿済 (Session 71)、回答待ち
3. **Issue #6 PoC E2E パイプライン**: WISEMAN_REAL=1 環境必須、本田様 PC TeamViewer + 環境変数設定
4. **Issue #316 follow-up**: 本セッションで実機実証完了、Issue は引き続き close 状態 (reopen 不要)

### Phase 2 候補 (本田様評価次第)

5. **Issue #274 Phase 2 (将来発生時)**: C ダイアログ 6 列 1240px 要求への geometry 拡大 (現状 stretch=True で動的調整で OK、本田様が窮屈と感じた場合のみ reopen or 新規 Issue)

## 関連 PR / コミット

- PR #347 (merge `f036953`): chore(gitignore): WisemanMock C# build artifacts + diagnostic outputs を ignore 追加
- PR #348 (merge `a820d41`): fix(ui): B/C ダイアログ初期 geometry を 1100x600 に拡大 (Issue #274 Phase 1 追加修正)
- (本 handoff PR): Session 89 handoff 記録

## 関連 Issue

- Closed: #274 (Phase 1 完遂: PR #280 + PR #348 + 本田様評価)
- Open active: #6, #27, #275
- Open postponed: #39, #134, #161, #170, #245
