# タスク 1-C: exe 再ビルド + 配布先差し替え 実機ランブック

**目的**: Session 19 完成の `facility_merger`（事業所フォルダ結合）機能を、配布済 exe に反映してエンドユーザーが使える状態にする。

**前提条件**:
- Windows 11 PC（本番配布先）に TeamViewer で接続可能
- `main` ブランチに Session 20 までの成果（PR #110 / #111）が merge 済
- 既存 exe が `%USERPROFILE%\wiseman-hub\wiseman_hub.exe` に配置済
- 所要時間: 20-30 分（ビルド 3-5 分 + 配布 1 分 + 動作確認 10-15 分）

**このランブックの完走で達成されること**:
1. ✅ 新機能入り exe が本番配布先に配置される
2. ✅ Launcher 4 ボタン目「事業所フォルダ結合」が動作する
3. ✅ Session 19 と同じシナリオで 19 件結合を再現
4. ✅ ADR-011 Status を `Proposed` → `Accepted` に昇格（14D 完走）

---

## 🎯 Phase 0: 事前確認（3 分）

### 0-1. TeamViewer で Windows PC に接続、PowerShell 起動

管理者権限不要。通常 PowerShell で OK。

### 0-2. 現行 exe のバックアップ（**rollback 用、必須**）

```powershell
$dist = "$HOME\wiseman-hub"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
Copy-Item "$dist\wiseman_hub.exe" "$dist\wiseman_hub.exe.bak-$stamp"
Get-ChildItem "$dist\wiseman_hub.exe*"
```

**期待**: `wiseman_hub.exe` と `wiseman_hub.exe.bak-YYYYMMDD-HHMMSS` の 2 ファイル表示。

### 0-3. リポジトリ最新化

```powershell
cd $HOME\Projects\wiseman-auto-sys
git checkout main
git pull --ff-only
git log --oneline -5
```

**期待 commit（最新 5 件、Session 22 終了時点）**:
```
af46db7 docs(handoff): Session 22 終了時点のハンドオフ更新 (#121)
5f19e08 fix(session): Issue #49 page_index invariant 検証を load 時に追加 (P1 bug) (#120)
b7e62b2 docs(handoff): Session 21 終了時点のハンドオフ更新 (#119)
28c1440 refactor(session): Issue #44 Session/UserCandidate 完全 immutable 化 (#116)
0eedb5e docs(runbook): 1-C に Phase 3-B（既存機能 regression smoke）追加（Issue #80 手動部分カバー） (#115)
```

最低条件: `5059823 feat(spec): ... facility_merger モジュールの hiddenimports 追加 (#111)` が `git log` に含まれていること。含まれていない場合は **Phase 1 に進まない**（spec が未更新＝ビルドが落ちるリスク）。

### 0-4. 依存同期 + ユニットテスト

```powershell
uv sync --extra dev
uv run pytest -q
```

**重要**: `uv sync` だけでは dev extras（`pyinstaller` / `ruff` / `mypy` / `pytest` 等）が削除される。Phase 1 のビルドで `Failed to spawn pyinstaller` が出るので **必ず `--extra dev` を付ける**。

**期待**: `559 passed, 68 skipped`（Session 22 終了時点。`538 passed` は Session 19 時点の旧値）。fail があれば Phase 1 に進まず原因を共有。

---

## 🔨 Phase 1: exe ビルド（5 分）

### 1-1. clean build

```powershell
uv run pyinstaller wiseman_hub.spec --clean --noconfirm 2>&1 | Tee-Object -FilePath build.log
```

### 1-2. ビルドログの warning 検査

```powershell
Select-String -Path build.log -Pattern "Hidden import.*not found" | Select-String -NotMatch "pycparser|jinja2|user32|msvcrt"
```

**期待**: **何も出力されない**（facility_merger 関連 3 モジュールの警告なし）。

出力があれば `wiseman_hub.spec` と `.py` のモジュール名が一致していない可能性。**Phase 2 に進まず共有**。

（参考: macOS build でも出る既知の無害 warning — `pycparser.lextab`, `pycparser.yacctab`, `jinja2`, `user32`, `msvcrt` — は Windows でも同様に出るが無視して良い。）

### 1-3. 生成物確認

```powershell
Get-Item dist\wiseman_hub.exe | Format-List Name, Length, LastWriteTime
```

**期待**: サイズ数十〜百 MB、LastWriteTime が本手順実行時刻。

---

## 📦 Phase 2: 配布（1 分）

### 2-1. exe 上書き

```powershell
Copy-Item -Force dist\wiseman_hub.exe "$HOME\wiseman-hub\wiseman_hub.exe"
Get-Item "$HOME\wiseman-hub\wiseman_hub.exe" | Format-List LastWriteTime, Length
```

**期待**: LastWriteTime が今、Length がビルド直後のサイズと一致。

---

## ✅ Phase 3: 動作確認（10-15 分）

### 3-1. Launcher 起動 + 4 ボタン目表示確認

```powershell
Start-Process "$HOME\wiseman-hub\wiseman_hub.exe"
```

| # | 確認項目 | 期待 |
|---|---------|------|
| 1 | Launcher ウィンドウ起動（コンソールは出ない） | ✅ |
| 2 | ボタン 4 個表示（PDFマージ / 確認 / **事業所フォルダ結合** / 設定） | ✅ |
| 3 | 「事業所フォルダ結合」クリック → ダイアログ表示 | ✅（新機能の決定的確認） |

「事業所フォルダ結合」ボタンが無い / クリックでエラーなら **Phase 4 (rollback) へ**。

### 3-2. Session 19 と同一シナリオで smoke test

ダイアログに以下を入力:

| 項目 | 値 |
|------|-----|
| A.pdf | Session 19 検証時と同じ `提供実績チェックリスト` PDF |
| 事業所フォルダ | Session 19 検証時と同じ `きなり(メール)` 配下（`運動機能向上計画書/` + `経過報告書/` 構成） |
| 出力ルート | 任意の空ディレクトリ（例: `C:\Users\%USER%\Desktop\1c_smoke\`） |

[実行] クリック後、結果 Text 欄のサマリを確認:

| 項目 | Session 19 実測 | 1-C 再現期待 |
|------|-----------------|-------------|
| 成功件数 | 19 件 | 19 件 |
| A+B+C 結合 | 2 件（塩津・尾島） | 2 件 |
| A+B 結合 | 1 件（藤野） | 1 件 |
| A+C 結合 | 4 件 | 4 件 |
| A のみ | 11 件 | 11 件 |
| Phase 2（B+C のみ） | 1 件（asao） | 1 件 |

**誤差 ±1 件以内なら OK**（実データが細かく変わっている可能性があるため）。大幅差があれば Phase 4。

### 3-3. 出力 PDF の目視確認（最低 1 件）

```powershell
Start-Process "C:\Users\$env:USERNAME\Desktop\1c_smoke\きなり(メール)\塩津.pdf"
```

| # | 項目 | 期待 |
|---|------|------|
| 1 | ページ 1: 提供実績チェックリスト + 氏名「塩津」 | ✅ |
| 2 | ページ 2: 運動器機能向上計画書 + 氏名「塩津」 | ✅ |
| 3 | ページ 3: 利用経過報告書 + 氏名「塩津」 | ✅ |
| 4 | 別人の書類が紛れ込んでいない | **絶対必須** |

全項目 ✅ なら **Phase 3-B へ（余裕があれば）または Phase 5 へ**（1-C 完走）。

---

## 📎 Phase 3-B: 既存機能の regression smoke（任意、Issue #80 関連）

**趣旨**: 1-C で配布した新 exe で、`facility_merger` 以外の既存機能（Phase A マージ / Phase B 確認）が**起動可能か**を軽く確認する。fitz (pymupdf) / httpx (OCR client) の import 解決を実機で検証することで Issue #80 の手動 smoke 部分をカバーする（Issue #80 本体の CI 自動化はタスク 15 で別途実施）。

**実施判断**: Phase 3-3 まで PASS し Phase 5 へ進む前に、余裕があれば実施。なければスキップして Phase 5 へ。**失敗しても 1-C 完走判定には影響しない**。

### 3-B-1. Launcher 1 ボタン目「PDF マージ処理を実行」

Launcher は既に Phase 3-1 で起動済。1 ボタン目をクリック:

| # | 確認項目 | 期待 | 備考 |
|---|---------|------|------|
| 1 | クリックで `ImportError` / `ModuleNotFoundError` ダイアログが**出ない** | ✅ | fitz / pymupdf の import 成功の証拠 |
| 2 | 設定済環境: Phase A パイプライン開始（ログ/進捗表示）／未設定環境: 「設定が未完了」ダイアログ | ✅ | 本番配布先 PC は設定済の想定だが、両挙動ともに正常 |
| 3 | エラーダイアログが出たら内容をスクショ | — | regression の証拠として保存 |

※ 設定済環境で Phase A が開始した場合、**実行中ボタン disable + ログ進捗** が確認できれば OK。完走まで待つ必要なし（Launcher ごと閉じて良い）。

### 3-B-2. Launcher 2 ボタン目「確認待ちセッション」

| # | 確認項目 | 期待 | 備考 |
|---|---------|------|------|
| 1 | クリックで `ImportError` / `ModuleNotFoundError` ダイアログが**出ない** | ✅ | httpx / OCR client の import 成功の証拠 |
| 2 | session 選択ダイアログ or 「確認待ちなし」メッセージ表示 | ✅ | `review_flow` 経路の起動確認 |

### 3-B-3. 結果記録

- **両方 ✅**: Issue #80 に実機 smoke 結果をコメント（下記テンプレート使用）。Issue 自体は CI 自動化（タスク 15）まで open 維持
- **どちらか失敗**: 失敗ボタンのスクショ + エラーメッセージを保存。**1-C 完走判定には影響しない別件 regression** として次セッションで調査。Phase 5 は予定通り進める

**Issue #80 コメント テンプレート**:

```
### 手動 smoke 結果（1-C Phase 3-B）

- 日時: YYYY-MM-DD HH:MM JST
- 実施環境: Windows 11 実機（配布先 PC）
- exe: `wiseman_hub.exe` (LastWriteTime: ...)
- 結果:
  - Launcher 1 ボタン目（PDF マージ）: ✅ ImportError なし
  - Launcher 2 ボタン目（確認待ち）: ✅ ImportError なし
- 備考: 手動 smoke は PASS。CI 自動化（タスク 15）で同等チェックを組込み予定のため Issue は open 維持。
```

---

## 🔙 Phase 4: rollback（問題発生時のみ）

Phase 3 のどれかで失敗した場合、Phase 0-2 で取ったバックアップに戻す:

```powershell
$dist = "$HOME\wiseman-hub"
$latest_bak = Get-ChildItem "$dist\wiseman_hub.exe.bak-*" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Copy-Item -Force $latest_bak.FullName "$dist\wiseman_hub.exe"
Write-Host "Restored from: $($latest_bak.Name)"
Start-Process "$dist\wiseman_hub.exe"
```

**rollback 完了後**: 旧 exe で Launcher 3 ボタン構成が表示されることを確認。その後、ビルドログ（`build.log`）と Phase 3 の失敗スクショを共有して原因調査を次セッションで実施。

---

## 📝 Phase 5: 完走処理（5 分）

### 5-1. ADR-011 Accepted 昇格（タスク 14D 完了）

`docs/adr/011-*.md` の Status を `Proposed` → `Accepted` に変更、Windows 実機検証の実測結果（19 件結合 / SmartScreen 警告なし 等）を「Consequences」セクションに追記。

### 5-2. 1-C 完走 PR 作成

```powershell
cd $HOME\Projects\wiseman-auto-sys
git checkout -b docs/1c-complete-adr-011-accepted
# ADR-011 編集後
git add docs/adr/011-*.md
git commit -m "docs(adr): ADR-011 Accepted 昇格 (タスク 14D 完走) - 1-C Windows 実機配布成功を反映"
git push -u origin docs/1c-complete-adr-011-accepted
gh pr create --title "docs(adr): ADR-011 Accepted 昇格（タスク 14D / 1-C 完走）" --body "1-C Windows 実機配布成功の実測結果を ADR に反映。"
```

### 5-3. バックアップ exe の整理

3 日以上動作に問題なければ `.bak-*` を削除:

```powershell
Get-ChildItem "$HOME\wiseman-hub\wiseman_hub.exe.bak-*"
# 問題なしが確認できたら:
# Remove-Item "$HOME\wiseman-hub\wiseman_hub.exe.bak-*"
```

---

## 🚨 トラブル早見表

| 症状 | 原因候補 | 対応 |
|------|---------|------|
| `uv sync --extra dev` で失敗 | 仮想環境破損 | `Remove-Item .venv -Recurse -Force; uv sync --extra dev` |
| `Failed to spawn pyinstaller` | `--extra dev` 忘れで dev extras 削除 | `uv sync --extra dev` で dev tools 復旧、Phase 1 再実行 |
| pyinstaller が `ModuleNotFoundError` | spec の hiddenimports 漏れ | ビルドログを Phase 4 rollback 後に共有 |
| ビルドは成功するが exe 起動で無反応 | Windows Defender が隔離 | Defender 除外設定 or SmartScreen「実行」押下 |
| Launcher は起動するが 4 ボタン目が無い | 古い exe を掴んでいる / 上書き失敗 | Phase 2-1 を再実行、LastWriteTime を再確認 |
| 「事業所フォルダ結合」クリックで `ImportError` | PR #111 の hiddenimports が足りていない（稀） | ビルドログの warning を精査、Phase 4 rollback |
| Session 19 シナリオで 19 件 → 0 件 | 入力パスの typo / ネットワーク切断 | `\\Tera-station\share` を Explorer で開けるか確認 |
| 出力 PDF で別人混入 | **即中止** | Phase 4 rollback、実装バグとして緊急報告（Codex 検証済の fail-safe が破綻の可能性） |
| SmartScreen 警告 | 新 exe の署名が違う（spec 変更で HASH が変わる） | 「詳細情報」→「実行」。一度通れば以降は警告なし |
| 3-B で Launcher 1/2 ボタン目が `ImportError` | spec の hiddenimports 漏れ（fitz / httpx / pymupdf 周辺） | 1-C 本体は成功扱いで Phase 5 進行。エラー詳細を Issue #80 にコメント、別件 PR で spec 更新を次セッションで実施 |

---

## 📞 連絡ルール

- **各 Phase 完了時に一言共有**（例「Phase 1 build.log warning 無し」）
- **想定外の結果が出たら即共有**、勝手に Phase を進めない
- **PII 情報（利用者氏名・事業所名）を含む出力を共有するときは墨塗り or user_key のみに絞る**
- **Phase 4 rollback を実施した場合は、その時点のスクショ + build.log を必ず保存**（次セッション原因調査の材料）

---

## 次セッション（1-C 完走後）への引き継ぎ

- 1-C 完了: ADR-011 Accepted 昇格 PR merged、Session 20 ハンドオフに実機結果を追記
- 次タスク: **1-B（B/C PDF 内容抽出によるファイル名非依存マッチ）**。設計メモは Session 20 ハンドオフ「1-B 着手メモ」参照
- 1-A は 1-B 実装後に「残った表記揺れの観測頻度」を見て判断（Codex 方針）
