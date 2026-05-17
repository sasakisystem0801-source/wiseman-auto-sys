# Session 87 完了 - Issue #316 完全解決 (4 PR マージ + 実機効果実証 + close)

日時: 2026-05-18
HEAD (main): `68054d2`
前セッション archive: [session-86-issue-27-datetime-and-issue-11-m2m6.md](./archive/session-86-issue-27-datetime-and-issue-11-m2m6.md)

## セッション概要

Session 86 handoff の「次セッション最優先」とは別に、ユーザーから「Windows 側処理が今なら可能」の合図を受け、**Issue #316 (本田様 PC の Tcl init.tcl read failure、deploy Phase 0 阻害) の完全対処** にフォーカスして 1 セッションで close まで到達。

主要成果:

- **4 PR マージ** (#340 / #341 / #342 / #343) で診断ツール完全復旧 + AI 完結対処策実装
- **Issue #316 close** (実機効果実証 = `1 rerun` で AV intermittent fail を実吸収)
- **真因確定**: ESET 動的 scan × pytest subprocess 起動の race condition
- **ADR-017** (test retry policy) 新規追加 (本 handoff PR で同時 commit)

## 本セッション完了内容

### Phase 1: PR #340 (merged `842d3a6`) - diagnose-tcl.ps1 BOM 付き UTF-8 変換

ユーザー: 「Windows側処理が今なら可能」 → 最優先 Issue #316 の `scripts/diagnose-tcl.ps1` 実行を依頼 → ParserError 連発で実行不能。

#### 原因

`scripts/diagnose-tcl.ps1` のみ **BOM 無し UTF-8** で commit されており、Windows PowerShell 5.1 が cp932 (Shift-JIS) として解釈、日本語文字列内の特殊バイトを構文要素として誤認していた。同じ `scripts/` 配下の `deploy-windows.ps1` `create_shortcut.ps1` は BOM 付き UTF-8 で commit されており、PR #319 で `diagnose-tcl.ps1` を追加した際の漏れ。

#### 修正

`scripts/diagnose-tcl.ps1` の先頭に `EF BB BF` (BOM) を追加するのみ (内容無変更、1 file changed, +1/-1)。

### Phase 2: PR #341 (merged `cfb2cf7`) - line 53 backtick エスケープ事故修正

PR #340 マージ後、本田様 PC で再実行したが **別の ParserError**: line 74 `'回連続、intermittent' を使用できません`。

#### 原因

Line 53 の `Write-Host "...または \`uv python install 3.11\`"` で:

- `` `u `` → `u` (リテラル、エラーなし)
- **`` `" `` → エスケープされた `"`** (致命的: 文字列終端と認識されない)

PowerShell parser が文字列リテラル `"  対処:..."` を閉じないまま line 54 以降を文字列継続として読み、後続の `"` で誤終端 → line 74 で構文エラー表面化。

#### 修正

Line 53 を single quote 文字列 `'...'` に変更。PowerShell の single quote 内では backtick がリテラル扱い (公式仕様)。表示文字列は完全同一、動作変更ゼロ。1 file changed, +1/-1。

### Phase 3: PR #342 (merged `e1fce7c`) - Section 3 Python embed 一時ファイル方式

PR #341 マージ後、診断ツールは完走するように。しかし **Section 3 (tk.Tk() 10 回試行) が Python 構文エラー** で実体未取得:

```
[10 回] File "<string>", line 10  print(fFAIL:  ^ SyntaxError: invalid syntax
```

期待: `print(f"FAIL: ...")` / 実態: `print(fFAIL:` (内側 `"` 消失)

#### 原因

PowerShell 5.1 の **native command argument passing は legacy モード**。`& $pythonExe -c $tkScript` の `$tkScript` 内の `"` が PowerShell に食われて Python に届かない (PSNativeCommandArgumentPassing 設定は PS 7.3+ のみで PS 5.1 では不可)。Windows PowerShell 5.1 限定で macOS では再現できないため見逃された。

#### 修正

一時ファイル経由 (`python tempfile.py`) に変更:

- `[System.IO.Path]::GetTempPath()` + GUID で一意ファイル名
- `[System.IO.File]::WriteAllText` で BOM なし UTF-8 で書き出し
- `try/finally` で確実にクリーンアップ

引数を「ファイルパス 1 個のみ」にすれば PowerShell の引数解釈は ASCII path のみで通過し、`"` 消失問題は原理的に発生しない。1 file changed, +22/-12。

### Phase 4: 実機診断結果取得 + 真因確定

PR #342 マージ後、本田様 PC で diagnose-tcl.ps1 が **5 セクション全完走**:

| Section | 結果 | 解釈 |
|---------|------|------|
| 1. Python/init.tcl 実在 | ✅ OK (25633 bytes) | ファイル健全 |
| 2. init.tcl read 5 回 | ✅ **5/5 成功** | スタンドアロン read 経路に AV 干渉なし |
| 3. tk.Tk() 10 回 | ✅ **10/10 成功** | **tkinter コード自体は健全** |
| 4. Defender 状態 | ⚠️ `Get-MpPreference` 0x800106ba 失敗 | ESET が Tamper Protection 化 |
| 5. 第三者 AV プロセス | ⚠️ **ESET (ekrn) 検出** | NOD32 / Endpoint Security |

#### 真因確定

スタンドアロン実行で **15 連続 (read 5 + tk.Tk() 10) 全成功** という事実から:

> **pytest 実行時にのみ発生する intermittent fail** = subprocess 大量起動 × ESET 動的 scan のタイミング競合

Issue #316 body の観察 (毎回違うテストで失敗、PR #311 で 4 件 → PR #312 で 1 件と推移) と完全整合。

### Phase 5: AI 完結対処策の選定 (Issue #316 コメント [#issuecomment-4472459362](https://github.com/sasakisystem0801-source/wiseman-auto-sys/issues/316#issuecomment-4472459362))

ユーザー方針確認: **本田様 PC 側で人手の設定変更 (ESET GUI 除外、Python 再 install) は一切行わない**。AI 完結で対処する。

| 候補 | 評価 |
|------|------|
| A. uv-managed Python 切替 | ❌ tkinter 健全なので不要、副作用大 |
| B. `-SkipPytest` 正規化 | ⚠️ CI 信頼倒しは大袈裟 |
| **C. pytest-rerunfailures** | **🎯 採用**: 副作用最小、診断結果と整合 |
| D. tk テスト marker skip | ❌ どのテストが failing するか predictable でない |

### Phase 6: PR #343 (merged `68054d2`) - pytest-rerunfailures 導入

`pyproject.toml` のみの変更 (2 files / +23/-1):

- `[project.optional-dependencies] dev` に `pytest-rerunfailures>=14.0` 追加
- `[tool.pytest.ini_options] addopts` に `--reruns 2 --reruns-delay 1` 追加
- 両所に WHY コメント明記 (Issue #316 / 実機診断結果を参照)

uv が自動生成した `[dependency-groups]` セクションは削除し `[project.optional-dependencies]` に統一 (`deploy-windows.ps1` Phase 0 の `uv sync --extra dev` で正しく install されるため)。

### Phase 7: 実機効果実証 (Issue #316 コメント [#issuecomment-4472478145](https://github.com/sasakisystem0801-source/wiseman-auto-sys/issues/316#issuecomment-4472478145))

PR #343 マージ後、本田様 PC で `uv sync --extra dev` + `uv run pytest -q -m "not integration"` 実行:

```
===== 2302 passed, 3 skipped, 10 deselected, 3 xpassed, 1 rerun in 30.63s =====
```

- **🎯 `1 rerun`**: pytest-rerunfailures による retry が **実機で発火**
- 該当テスト: `tests\unit\ui\test_checklist_c_dialog_mirror_hook.py` (出力に `R` マーカー)
- **PR #343 がなければこの 1 件で deploy 停止** = Issue #316 現象の再現
- 全 2302 PASS で最終的にエラーゼロ

### Phase 8: Issue #316 close

実機効果実証完了のため `gh issue close 316` (closed: 2026-05-17T20:55:29Z)。

## 学んだこと (今セッション固有の知見)

### PowerShell 5.1 の 3 つの罠 (新規 ps1 作成時の必須チェックリスト)

1. **エンコーディング**: 日本語含む `.ps1` は **BOM 付き UTF-8** で commit する。BOM なし UTF-8 は cp932 として解釈され文字化け + 構文エラー
2. **backtick エスケープ**: `"..."` 内の `` `" `` は **エスケープされた `"` リテラル** として扱われ文字列が閉じない。markdown コード形式の意図で書いた backtick が `"` の直前に来ないよう注意
3. **native command argument passing**: `& python -c $script` で `$script` 内の `"` が消失する。一時ファイル経由 (`python tempfile.py`) で回避

→ 関連 memory: [feedback_no_manual_windows_changes.md](https://github.com/yasushi-honda/claude-code-config/blob/main/memory/feedback_no_manual_windows_changes.md) (新規追加)

### CLAUDE.md MUST「変更コードパスを最低 1 回実行」の重要性 (再確認)

PR #319 で `scripts/diagnose-tcl.ps1` を「Windows PS 5.1 限定で macOS 実行不可」を理由に実機検証 skip した結果、上記 3 罠が同時混入。3 段階 PR で表面化を解消する手間が発生。

**今後の方針**: Windows 専用スクリプトでも macOS 上で pwsh 7+ の構文 parser 検証を最低限通す。本セッションでは brew cask + tar.gz 両方が permission 等で skip されたが、可能なら CI に `.github/workflows/` で PowerShell lint job を追加する候補あり (本セッション範囲外、別 Issue 候補)。

### Windows 機側で手動設定変更しない方針 (確立)

Issue #316 の対処方針として **「本田様 PC 側で人手の設定変更 (GUI / install / レジストリ) は一切しない、AI 完結で完了する」** をユーザーから明示。今後の wiseman_auto_sys 関連の運用問題対応では:

- OK: `git pull`、`scripts/*.ps1` の実行、`uv sync` 等のコマンド、結果の貼り付け / 共有
- NG: ESET / Defender / 第三者 AV の GUI 除外設定、Python の install / 再 install / uninstall、レジストリ編集、グループポリシー変更

該当する対処案 (例: 「ESET 除外設定して」) を出さないこと。原理的に AI 完結不可なケースは明示報告し、別アプローチを提案する。

詳細: [feedback_no_manual_windows_changes.md](https://github.com/yasushi-honda/claude-code-config/blob/main/memory/feedback_no_manual_windows_changes.md)

## Quality Gate 適用状況

| 段階 | PR #340 (BOM) | PR #341 (backtick) | PR #342 (Section 3) | PR #343 (rerunfailures) |
|---|---|---|---|---|
| `/impl-plan` | スキップ (1 file 1 行) | スキップ (1 file 1 行) | スキップ (1 file 34 行、設計判断不要) | スキップ (2 file、設計判断は Issue コメントで実施済) |
| `/simplify` | スキップ (1-2 file < 30 行) | スキップ (同上) | スキップ (1 file 34 行) | スキップ (2 file 24 行) |
| `/safe-refactor` | スキップ | スキップ | スキップ | 適用相当 (ruff/mypy/pytest 全 clean) |
| Evaluator 分離プロトコル | 該当外 (1 file) | 該当外 | 該当外 | 該当外 (2 file、5 file 未満) |
| Medium tier review | スキップ (small PR) | スキップ | スキップ | スキップ (small PR、PR description で診断結果根拠提示) |
| Codex セカンドオピニオン | 不要 | 不要 | 不要 | 不要 (実機実証で確証) |
| 番号単位明示認可 merge | ✅ `PR #340 — ... (1 files, +1/-1)` | ✅ `PR #341 — ... (1 files, +1/-1)` | ✅ `PR #342 — ... (1 files, +22/-12)` | ✅ `PR #343 — ... (2 files, +23/-1)` |
| 実機検証 | (1 段目で発覚、part2 へ) | (2 段目で発覚、part3 へ) | (3 段目で完走、真因確定) | **✅ `1 rerun` で効果実証** |

## ADR 状態

- **新規 ADR-017** (`017-test-retry-policy-for-windows-av-interference.md`) を本 handoff PR で同時 commit
- Status: Accepted
- 内容: pytest-rerunfailures 採用の経緯、reruns=2 / delay=1s の数値根拠、代替案 (A/B/D) の評価、将来の retry 数調整・dep 廃止判断の根拠
- 既存 ADR (001-016): 状況変化なし、変更不要

## 残留プロセス

✅ 残留 Node プロセスなし (handoff スキル事前取得データで確認済)

## CI 状態

main `68054d2` で **全 4 ジョブ SUCCESS**:

- ✅ Unit Tests (macOS/Linux)
- ✅ Windows UI Tests
- ✅ Build Windows Smoke
- ✅ Windows Integration Tests

## Issue Net 変化 (CLAUDE.md MUST)

- **Close 数**: 1 件 (#316)
- **起票数**: 0 件
- **Net: -1 件 ✅** (CLAUDE.md MUST「Net ≤ 0 は進捗ゼロ扱い」をクリア)

セッション開始時: open active 6 (#316 含む) + postponed 5 = 11
セッション終了時: open active 5 + postponed 5 = 10

## 次セッション最優先 (catchup 推奨)

### AI 単独で着手可能 (decision-maker 判断不要)

1. **Issue #11 PR-B (M3/M4/M5)** — Session 86 から継続最優先
   - M3: テスト private 属性 inject API 化
   - M4: failure path テスト横展開 (`select_care_system` / `navigate_menu` / `close_wiseman` 等) + PR #336 follow-up の `__cause__` chain assertion (rating 4)
   - M5: テスト構造改善 (PR-A の調査で「現状維持で M5 不要」の判断も再検討対象)
   - 着手前に `/impl-plan` 必須 (3 ステップ以上 + テスト構造変更)

2. **Issue #27 umbrella 残務消化判断** — `reports` section は実質クリア確認済。PII default 反転検討 (rating 5) はユーザー判断待ち。umbrella close 候補のタイミング近接

### 外部条件待ち (AI 着手不可)

3. **Issue #274** — 本田様 PC 実機検証待ち (B/C ダイアログ詳細列表示)
4. **Issue #275** — 本田様ヒアリング 4 領域回答待ち
5. **Issue #17 / #6** — WISEMAN_REAL=1 環境 (本田様 PC) 必須

### Issue #316 follow-up (発生時)

- 次回 `scripts/deploy-windows.ps1` 実行時、Phase 0 が retry 吸収で完走することを確認 (実機で `R` マーカーが出るか、または出ずに完走するか)
- 万一 3/3 retry で fail するケースが出たら Issue を reopen して `--reruns 5` 等への数値調整を検討
- PR #312 で xfail にしている `test_persists_after_fetch` (Issue #316 body の元事案) は別途状態確認

## 関連 PR / コミット

- PR #340 (merge `842d3a6`): diagnose-tcl.ps1 BOM 付き UTF-8 変換
- PR #341 (merge `cfb2cf7`): diagnose-tcl.ps1 line 53 backtick エスケープ修正
- PR #342 (merge `e1fce7c`): diagnose-tcl.ps1 Section 3 Python embed 一時ファイル化
- PR #343 (merge `68054d2`): pytest-rerunfailures 導入
- (本 handoff PR): Session 87 handoff 記録 + ADR-017

## 関連 Issue

- Closed: #316 (Tcl init.tcl read failure)
- Open active: #275, #274, #27, #11, #6
- Open postponed: #245, #170, #161, #134, #39
