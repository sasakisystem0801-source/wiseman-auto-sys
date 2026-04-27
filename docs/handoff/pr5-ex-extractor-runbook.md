# Session 29 / PR5: ex_extractor Windows 実機検証ランブック

**目的**: ex_extractor デスクトップ UI 統合（PR3 #133 + PR4 #135）の Windows 実機検証を実施し、ADR-014 を `Proposed` → `Accepted` に昇格させる根拠（AC-1〜AC-14 の PASS 記録 + PII 墨塗りスクショ + grep 結果）を取得する。

**前提**:
- Windows 11 PC（本番配布先）に TeamViewer で接続可能
- `main` ブランチに本ランブックの handoff PR が merge 済（main HEAD: 本 PR マージ後）
- 既存 exe が `%USERPROFILE%\wiseman-hub\wiseman_hub.exe` に配置済
- Wiseman SP の USB dongle は今回の検証では不要（`.ex_` 抽出は Wiseman 起動と独立）
- 所要時間: **30-45 分**
  - Phase 0 事前確認 + main 同期 + 依存同期: 5-10 分
  - Phase 1 exe 再ビルド: 5 分
  - Phase 2 配布 + config.toml 設定: 3-5 分
  - Phase 3 動作確認 (AC-1〜AC-14): 15-25 分
  - Phase 5 完走処理: 5 分
  - Phase 4 rollback は問題発生時のみ

**このランブックの完走で達成されること**:
1. ✅ PR3-4 の機能入り exe が本番配布先に配置される
2. ✅ Launcher「ex_ ファイル変換 + 振り分け」ボタンから `ExExtractorDialog` が起動する
3. ✅ AC-1〜AC-14 すべて PASS（誤配布防止 KPI 直撃の項目を含む）
4. ✅ PII ログ防御の grep 結果取得（事業所名 / フルパス / 抽出 PDF 名が log に漏れていないこと）
5. ✅ ADR-014 を `Proposed` → `Accepted` に昇格させる根拠取得（次セッションで反映）

---

## 🔐 PII 取り扱い注意（運用ルール、検証開始前に必読）

ex_extractor の出力には介護施設の事業所名・利用者氏名等の PII が含まれる。本ランブック実施中は以下を厳守:

- **`orphan_alias_canonicals` banner / CLI 警告には canonical 名（事業所正式名）が出る**: 運用者ローカル端末の表示に留め、SaaS log aggregator（Sentry / Datadog 等）への送信禁止
- **スクショ共有時**: 事業所名・PDF ファイル名・利用者氏名が映る箇所は墨塗り or マスク必須
- **stderr ログのファイル化**: `2>run.log` で保存する場合、検証完了後に削除するか暗号化フォルダへ移動
- **Slack / Email でのログ貼付**: 必ず墨塗り後。`grep -E "本田|施設A|施設B"` 等で事業所名を含む行を除外してから共有

ex_extractor モジュール本体の logger は filename と enum 値のみ出力する設計だが、CLI レイヤ（`scripts/process_ex_files.py`）の `_print_summary` は alias 設定不整合通知のために canonical 名を例外的に出力する（ADR-014 §PII 保護方針）。

---

## 🎯 Phase 0: 事前確認（5-10 分）

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

**最低条件**: 本ランブックの handoff PR がマージされた最新 commit が含まれていること（`docs(handoff): PR5 ex_extractor Windows 実機検証 runbook` 等）。

### 0-4. 依存同期

```powershell
uv sync --extra dev
```

**重要**: `uv sync` だけでは dev extras（`pyinstaller` 等）が削除される。Phase 1 のビルドで `Failed to spawn pyinstaller` が出るので **必ず `--extra dev` を付ける**。

`tests/integration/` は Wiseman SP を pywinauto で起動するため実機環境では副作用大。CI で全 SUCCESS 確認済のため再実行不要。unit のみ走らせたい場合のみ `uv run pytest -q tests/unit/` を実行可。

### 0-5. 検証用 .ex_ サンプル配置（事前準備）

実機 PC の `ex_source_dir` に以下のサンプルを配置:

| サンプル種別 | ファイル名規約 | 期待 status |
|------------|----------------|-------------|
| SUCCESS 経路 | `<本田様の現行運用で alias / 事業所名と一意マッチする ex_>` (1-2 件) | `SUCCESS` |
| SKIPPED_AMBIGUOUS | `<事業所 A と B 両方を部分一致候補に持つ ex_>` (1 件) | `SKIPPED_AMBIGUOUS` |
| SKIPPED_UNMATCHED | `<事業所名・alias と全くマッチしない ex_>` (1 件) | `SKIPPED_UNMATCHED` |

サンプル選定は本田様の現行 `ex_source_dir` 配下から実例を流用するのが最も簡単。検証完了後、抽出された PDF は事業所フォルダに配布されるため、**検証用は本番ルートと隔離した一時フォルダで実施するのを推奨**。

---

## 🔨 Phase 1: exe 再ビルド（5 分）

### 1-1. clean build

```powershell
uv run pyinstaller wiseman_hub.spec --clean --noconfirm 2>&1 | Tee-Object -FilePath build.log
```

### 1-2. ビルドログの warning 検査

```powershell
Select-String -Path build.log -Pattern "Hidden import.*not found"
```

**期待**: 何も出力されない。出力があり `wiseman_hub.*` 由来なら Phase 2 に進まず共有。`pycparser` / `jinja2` / `user32` / `msvcrt` 由来は無害（既知 warning）。

### 1-3. 生成物確認

```powershell
Get-Item dist\wiseman_hub.exe | Format-List Name, Length, LastWriteTime
```

**期待**: サイズ 70-100 MB 程度、LastWriteTime が本手順実行時刻。

---

## 📦 Phase 2: 配布 + config.toml 設定（3-5 分）

### 2-1. exe 上書き

```powershell
Copy-Item -Force dist\wiseman_hub.exe "$HOME\wiseman-hub\wiseman_hub.exe"
Get-Item "$HOME\wiseman-hub\wiseman_hub.exe" | Format-List LastWriteTime, Length
```

**期待**: LastWriteTime が今、Length がビルド直後のサイズと一致。

### 2-2. config.toml 編集（**PR1 で導入された ex_source_dir + facility_aliases**）

`%USERPROFILE%\wiseman-hub\config.toml` を notepad で開き、`[pdf_merge]` セクション内に以下を追記:

```toml
[pdf_merge]
ex_source_dir = "C:\\Users\\sasak\\OneDrive\\デスクトップ\\本田様\\ex_source"  # ← Phase 0-5 でサンプル配置したフォルダ
facility_root_dir = "<既存の事業所ルートパス>"
input_dir = ""
output_dir = ""

[pdf_merge.facility_aliases]
# 例: alias を 1-2 件登録して AC-3 / AC-11 を検証
# canonical（key）は facility_root_dir 配下に実在するフォルダ名と完全一致が必要
# alias（value）は ex_ ファイル名に含まれる短縮名・別表記を列挙
# 値は必ず list 型で書く（"abc" 単独は禁止 — 文字単位分解されるため）
"<本田様の事業所正式名>" = ["<短縮名 1>", "<別表記 1>"]
```

**重要な検証ルール**（ADR-014 §facility_aliases 入力検証）:
1. canonical（key）は空文字列でない
2. value が list 型（str を直接書くと TypeError で fail-fast）
3. value 要素が非空 str
4. 同じ list 内で alias 重複なし
5. 異なる canonical 間で同じ alias を共有しない（global 一意性）
6. alias が他 canonical と一致しない

違反時は起動時に ValueError / TypeError で fail-fast。

### 2-3. orphan alias を意図的に作成（AC-11 検証用、任意）

`facility_root_dir` に存在しない canonical を 1 件追加して `orphan_alias_canonicals` banner を発火させる:

```toml
[pdf_merge.facility_aliases]
"<実在する事業所>" = ["<短縮名>"]
"消えた施設" = ["短縮"]  # ← この canonical は facility_root_dir に存在しない → orphan
```

検証完了後はこの行を削除。

---

## ✅ Phase 3: 動作確認（AC-1〜AC-14、15-25 分）

### AC-1: Launcher 5 ボタン目表示

```powershell
Start-Process "$HOME\wiseman-hub\wiseman_hub.exe"
```

| # | 確認項目 | 期待 |
|---|---------|------|
| 1 | Launcher ウィンドウ起動（コンソールは出ない） | ✅ |
| 2 | **「ex_ ファイル変換 + 振り分け」** ボタン表示（5 ボタン目） | ✅ |
| 3 | クリック → `ExExtractorDialog` 起動 | ✅（PR4 #135 の決定的確認） |

新ダイアログが開かない / ImportError なら **Phase 4 (rollback) へ**。

---

### AC-2: ex_source_dir 設定（TOML 直接編集）

| 手順 | 期待 |
|------|------|
| 1. config.toml の `ex_source_dir` が ExExtractorDialog の表示欄に反映 | ✅ Phase 2-2 で設定したパスが表示 |
| 2. 「実行」ボタンが活性化（disabled でない） | ✅ |

ex_source_dir が空文字列だと「実行」ボタンが disabled になることを確認するなら、一度 config.toml で `ex_source_dir = ""` にして再起動 → ボタン disabled を確認 → 元に戻す。

---

### AC-3: facility_aliases 設定（TOML 直接編集 + 入力検証）

**正常系**: Phase 2-2 の TOML で起動成功 → 設定 6 項目すべて PASS。

**異常系（任意、5 分追加）**: 入力検証が fail-fast することを確認:

| 違反パターン | 期待 |
|------------|------|
| `"事業所A" = "短縮"` (str 直書き) | 起動時 TypeError |
| `"事業所A" = ["短縮", "短縮"]` (list 内重複) | 起動時 ValueError |
| `"事業所A" = ["短縮"]` + `"事業所B" = ["短縮"]` (global 重複) | 起動時 ValueError |
| `"事業所A" = ["事業所B"]` (alias が他 canonical と一致) | 起動時 ValueError |

違反確認後は元の正常 TOML に戻す。

---

### AC-4: SUCCESS 経路（自動振り分け CONFIRMED）

| 手順 | 期待 |
|------|------|
| 1. SUCCESS 経路サンプル（事業所名 / alias と一意マッチする `.ex_`）のみが ex_source_dir にある状態で「実行」 | - |
| 2. 進捗表示「**処理中... (最大 数分かかる場合があります)**」が表示 | ✅（IT 非専門者の「固まった」誤認防止） |
| 3. SFX ダイアログが自動クリックされる（pywinauto 動作） | ✅ |
| 4. 完了サマリ表示 | ✅ 以下フォーマットで表示 |

完了サマリの期待文言:
```
処理対象: 1 件
自動振り分け成功: 1 件
手動確定成功: 0 件
失敗: 0 件
手動振り分け待ち: 0 件
```

事業所フォルダに PDF が配置されたことを Explorer で確認。元 `.ex_` ファイルは ex_source_dir から削除されている（クリーンアップ済）。

---

### AC-5: SKIPPED_AMBIGUOUS → 手動振り分け（候補表示 + 確定前確認）

| 手順 | 期待 |
|------|------|
| 1. AMBIGUOUS サンプル（事業所 A と B 両方を部分一致候補に持つ `.ex_`）のみ配置 → 「実行」 | - |
| 2. 完了サマリで `手動振り分け待ち: 1 件` 表示 | ✅ |
| 3. 「手動振り分けへ」ボタン押下 → `ManualDistributionDialog` 起動 | ✅ |
| 4. 候補プルダウンに事業所 A と B が並ぶ、**既定選択は `(未選択)`** | ✅（先頭 facility 誤選択を構造的に遮断） |
| 5. 事業所 A を選択 → 「次へ」 → 確定前確認画面 | ✅ |
| 6. 確認画面で以下が表示される | ✅ |

確認画面の表示項目:
```
以下の内容で確定します。よろしいですか？
ファイル: <ex_ ファイル名>
振り分け先事業所: <選択した事業所名>
出力先パス: <facility_root_dir/事業所名>
```

| 7. 「確定」押下 → SFX 自動操作 → 事業所 A フォルダに PDF 配置 | ✅ |

---

### AC-6: SKIPPED_UNMATCHED → 手動振り分け（既定空 + 確定前確認 + 全 facility プルダウン）

| 手順 | 期待 |
|------|------|
| 1. UNMATCHED サンプル（事業所名 / alias とマッチしない `.ex_`）配置 → 「実行」 | - |
| 2. `手動振り分け待ち: 1 件` 表示 → 「手動振り分けへ」 | ✅ |
| 3. プルダウンに `facility_root_dir` 配下の**全事業所**が並ぶ、**既定選択は `(未選択)`** | ✅（**最重要**: 全 facility プルダウンの誤選択を構造的に防ぐ、PR4-HIGH-3） |
| 4. 「未選択のまま次へ」押下 → エラーまたは disabled で進めない | ✅ |
| 5. 事業所選択 → 「次へ」 → 確定前確認画面 | ✅ AC-5 と同じ確認画面 |
| 6. 「確定」押下 → SFX 自動操作 → 選択事業所フォルダに PDF 配置 | ✅ |

**もしプルダウン既定が先頭事業所になっていたら → AC-6 のバグ。即中止 + 報告。**

---

### AC-7: MANUAL_OVERRIDE がサマリで自動と区別表示

AC-5 / AC-6 完了後、ExExtractorDialog の最終サマリで以下が分離表示されること:

```
自動振り分け成功: <N> 件     ← AC-4 経由
手動確定成功: <M> 件          ← AC-5 + AC-6 経由（MANUAL_OVERRIDE reason）
```

監査経路として「自動振り分けされた件数」と「手動で確定した件数」が常に区別可能であること。

---

### AC-8: mtime フィルタ（SFX 実行中の Desktop 無関係 PDF が誤配布されない）

**シナリオ**: SFX 実行中にユーザーが別途 Desktop に保存した無関係 PDF が `_collect_new_pdfs` の watch_dir に含まれていても誤配布されない。

| 手順 | 期待 |
|------|------|
| 1. SUCCESS 経路サンプル `.ex_` を ex_source_dir に配置 | - |
| 2. 別ターミナルで以下を準備（`.ex_` 実行直前に投入） | - |

```powershell
# Desktop に無関係 PDF を生成するワンライナー（SFX 起動「直前」に実行）
"%USERPROFILE%\Desktop\無関係_$(Get-Date -Format yyyyMMddHHmmss).pdf" |
  ForEach-Object { Set-Content -Path $_ -Value "dummy pdf" -Encoding Byte }
```

| 3. ExExtractorDialog で「実行」を押下した直後に上記コマンドを別ターミナルで実行 | - |
| 4. SFX 完了 → 完了サマリ確認 | ✅ |
| 5. **無関係 PDF が事業所フォルダに移動されていない** | ✅（誤配布 KPI 直撃の構造的防御、ADR-014 PR3-HIGH-D） |
| 6. Desktop に無関係 PDF が残ったまま | ✅ |

mtime フィルタは `_MTIME_GRACE_SEC = 5.0` 秒のマージンで NTP 後方ステップを吸収しつつ、SFX 起動前に既存していた PDF を除外する。

---

### AC-9: PARTIAL_OUTPUT 警告表示（要確認セクション）

PARTIAL_OUTPUT は SFX 例外で PDF が一部生成されたが移動されなかった状態。再現は難しいため**通常運用では発生しない**ことを確認するレベルで OK:

| 手順 | 期待 |
|------|------|
| 1. 通常運用での 10-20 件投入で PARTIAL_OUTPUT が**発生しないこと** | ✅ |
| 2. もし発生した場合のサマリ表示形式 | ✅ 以下文言が表示 |

```
⚠ 要確認 (一部抽出/移動): <N> 件
--- 要確認 ---
  x <ファイル名> [<error_code>]
```

PARTIAL_OUTPUT が頻発する場合は SFX adapter の実装バグ可能性 → 即中止 + 報告。

---

### AC-10: MOVE_FAILED + partially_moved 件数表示

**シナリオ**: 抽出成功だが移動失敗（衝突 / 権限エラー）。再現は事業所フォルダに同名 PDF を事前配置することで可能:

| 手順 | 期待 |
|------|------|
| 1. SUCCESS 経路サンプルの抽出予定 PDF と**同名のダミー PDF**を事業所フォルダに事前配置 | - |
| 2. ExExtractorDialog で「実行」 | - |
| 3. 完了サマリで `失敗: 1 件` + 「要確認」セクション表示 | ✅ |
| 4. 該当行に `[MOVE_CONFLICT]` または `[MOVE_IO_ERROR]` 表示 | ✅ |
| 5. 複数 PDF のうち一部移動済の場合 `(一部 PDF 移動済: N 件)` 表示 | ✅（運用情報消失防止、ADR-014 PR3-HIGH-A） |

---

### AC-11: orphan_alias_canonicals banner（alias 設定不整合の常時表示）

Phase 2-3 で `"消えた施設" = ["短縮"]` を追加した状態で:

| 手順 | 期待 |
|------|------|
| 1. ExExtractorDialog で「実行」 | - |
| 2. 結果フレーム上部に banner 常時表示 | ✅ 以下文言 |

```
⚠ alias 設定不整合: 1 件 — 実フォルダが存在しない canonical があります。TOML を修正してください。
```

| 3. サマリにも `⚠ alias 設定不整合: 1 件` 表示 | ✅ |
| 4. CLI 経由（`scripts/process_ex_files.py`）でも canonical 名がログに出る | ✅（`--- 設定不整合 ---` セクション） |

検証完了後 `"消えた施設"` 行を TOML から削除して banner 解消を確認。

---

### AC-12: PII ログ防御（log 出力に事業所名/フルパス/PDF名なし）

**最重要 AC**。事業所名 / フルパス / 抽出 PDF 名が ex_extractor モジュールの logger 出力に漏れていないことを確認。

| 手順 | 期待 |
|------|------|
| 1. AC-4〜AC-7 を `2>run.log` で stderr キャプチャしながら実行 | - |

```powershell
& "$HOME\wiseman-hub\wiseman_hub.exe" 2>run.log
# (UI 操作後、ダイアログを閉じてアプリ終了)
```

| 2. run.log を grep で PII 漏洩チェック | ✅ |

```powershell
# 事業所名（本田様の運用で使う実名）が log に含まれていないこと
# ex_extractor モジュール本体の logger 出力には事業所名は含まれない
# CLI レイヤの orphan_alias_canonicals 通知のみ canonical 名が出る（運用ローカル端末限定）
Select-String -Path run.log -Pattern "<事業所正式名 1>|<事業所正式名 2>"
# 期待: 何もヒットしない（または `--- 設定不整合 ---` セクション内の orphan 行のみ）

# フルパスが log に含まれていないこと（C:\Users\... 等）
Select-String -Path run.log -Pattern "C:\\\\Users\\\\.*\\.(ex_|pdf)"
# 期待: 何もヒットしない

# 抽出 PDF 名が log に含まれていないこと
Select-String -Path run.log -Pattern "[a-zA-Z0-9_\-]+\.pdf"
# 期待: 何もヒットしない（CLI summary の filename のみ許容、PDF 名は出ない設計）
```

**期待結果**: ex_extractor モジュール本体の logger 出力には PII（事業所名 / フルパス / PDF 名）が一切含まれない。CLI レイヤの `orphan_alias_canonicals` 通知のみ canonical 名が例外的に出る（ADR-014 §PII 保護方針）。

**もしフルパスや抽出 PDF 名がヒットしたら → 即中止 + run.log の該当行を**墨塗り**してから報告**。

---

### AC-13: CLI 終了コード 0/1/2（process_ex_files.py 経由）

UI とは独立した CLI 経路の動作確認:

| シナリオ | 期待 exit code |
|---------|---------------|
| 全件 SUCCESS | `0` |
| pending（AMBIGUOUS / UNMATCHED）あり、failed なし | `2` |
| failed あり | `1`（pending あっても 1 が優先） |

```powershell
# 全件 SUCCESS シナリオ（AC-4 と同じサンプルで）
cd $HOME\Projects\wiseman-auto-sys
uv run python scripts/process_ex_files.py
echo $LASTEXITCODE
# 期待: 0

# pending あり（AC-5 のサンプル投入）
uv run python scripts/process_ex_files.py
echo $LASTEXITCODE
# 期待: 2

# failed あり（AC-10 のサンプル投入で MOVE_CONFLICT 発生させる）
uv run python scripts/process_ex_files.py
echo $LASTEXITCODE
# 期待: 1
```

CLI の stderr 出力フォーマット（`--- 手動振り分け待ち ---` / `--- 失敗 ---` / `--- 設定不整合 ---`）も合わせて確認。

---

### AC-14: 既存機能 regression smoke

PR3-4 の追加が既存機能を破壊していないことを最低限の操作で確認:

| 手順 | 期待 |
|------|------|
| 1. Launcher の他のボタン（「事業所フォルダ一括結合」「PDFマージ処理」等）が表示・クリック可能 | ✅ |
| 2. 「事業所フォルダ一括結合」（PR #126）クリック → `FacilityRootManagerDialog` 起動 | ✅ |
| 3. ダイアログを × で閉じる → Launcher に戻る | ✅ ImportError なし |

regression が出た場合は **Phase 4 rollback へ**。

---

## 🔙 Phase 4: rollback（問題発生時のみ）

Phase 3 のどれかで失敗した場合、Phase 0-2 のバックアップに戻す:

```powershell
$dist = "$HOME\wiseman-hub"
$latest_bak = Get-ChildItem "$dist\wiseman_hub.exe.bak-*" |
  Sort-Object LastWriteTime -Descending | Select-Object -First 1
Copy-Item -Force $latest_bak.FullName "$dist\wiseman_hub.exe"
Write-Host "Restored from: $($latest_bak.Name)"
Start-Process "$dist\wiseman_hub.exe"
```

**rollback 完了後**:
1. 旧 exe で動作することを確認
2. 失敗 Phase のスクショ + `build.log` + `run.log`（PII 墨塗り済）を共有
3. 次セッションで原因調査
4. config.toml の検証用 alias（`"消えた施設"` 等）を削除して元の運用設定に戻す

---

## 📝 Phase 5: 完走処理（5 分）

### 5-1. 検証結果サマリの記録

以下のテーブルを実機で記入し、Slack / Email で運用者へ共有:

| AC | 結果 | 観察事項 |
|----|------|---------|
| AC-1 Launcher 5 ボタン目表示 | ✅ / ❌ | |
| AC-2 ex_source_dir 設定 | ✅ / ❌ | |
| AC-3 facility_aliases 入力検証 | ✅ / ❌ | |
| AC-4 SUCCESS 経路（自動振り分け） | ✅ / ❌ | |
| AC-5 SKIPPED_AMBIGUOUS → 手動 | ✅ / ❌ | |
| AC-6 SKIPPED_UNMATCHED → 手動（既定空） | ✅ / ❌ | |
| AC-7 MANUAL_OVERRIDE サマリ分離 | ✅ / ❌ | |
| AC-8 mtime フィルタ | ✅ / ❌ | |
| AC-9 PARTIAL_OUTPUT | ✅ / ❌ | |
| AC-10 MOVE_FAILED + partially_moved | ✅ / ❌ | |
| AC-11 orphan_alias_canonicals banner | ✅ / ❌ | |
| AC-12 PII ログ防御（grep 結果） | ✅ / ❌ | grep ヒット数を記載 |
| AC-13 CLI 終了コード 0/1/2 | ✅ / ❌ | |
| AC-14 既存機能 regression smoke | ✅ / ❌ | |

### 5-2. config.toml の検証用設定をクリーンアップ

検証で追加した orphan alias（`"消えた施設"` 等）を削除し、本番運用の facility_aliases 設定に戻す。

### 5-3. バックアップ exe の整理

3 日以上動作に問題なければ `.bak-*` を削除:

```powershell
Get-ChildItem "$HOME\wiseman-hub\wiseman_hub.exe.bak-*"
# 問題なしが確認できたら:
# Remove-Item "$HOME\wiseman-hub\wiseman_hub.exe.bak-*"
```

### 5-4. 次セッション（Session 30）への引き継ぎ

**全 AC PASS の場合**:
- Session 30 で `docs/adr/014-ex-extractor-integration.md` の Status を `Proposed (2026-04-27)` → `Accepted (YYYY-MM-DD)` に昇格させる PR を作成
- 「Session 29 実機検証結果」セクションを ADR-014 に追加（5-1 のサマリテーブル + PII grep 結果 + 観察事項）
- handoff/LATEST.md を更新（PR5 完走 → 次タスク選定フェーズへ）

**一部 AC FAIL の場合**:
- Session 30 で FAIL 項目の修正 PR を作成（PR5.1 として独立評価）
- 修正完了後に再度本ランブックで再検証

---

## 🚨 トラブル早見表

| 症状 | 原因候補 | 対応 |
|------|---------|------|
| `uv sync --extra dev` で失敗 | 仮想環境破損 | `Remove-Item .venv -Recurse -Force; uv sync --extra dev` |
| `Failed to spawn pyinstaller` | `--extra dev` 忘れで dev extras 削除 | `uv sync --extra dev` で復旧、Phase 1 再実行 |
| ビルドは成功するが exe 起動で無反応 | Windows Defender が隔離 | Defender 除外設定 or SmartScreen「実行」押下 |
| Launcher は起動するが「ex_ ファイル変換 + 振り分け」が無い | 古い exe を掴んでいる / 上書き失敗 | Phase 2-1 を再実行、LastWriteTime を再確認 |
| 新ダイアログクリックで `ImportError` | spec の hiddenimports 不足 | ビルドログを Phase 4 rollback 後に共有 |
| 起動時 `TypeError`/`ValueError` で immediately 終了 | facility_aliases 入力検証失敗 | エラーメッセージ確認 + TOML を AC-3 異常系に従って修正 |
| AMBIGUOUS のプルダウン既定が先頭 facility | UI 既定値設計バグ | **即中止** + 報告（PR4-HIGH-3 退化） |
| UNMATCHED のプルダウン既定が先頭 facility | UI 既定値設計バグ | **即中止** + 報告（誤配布リスク直撃） |
| Desktop の無関係 PDF が事業所フォルダに移動された | mtime フィルタ退化 | **即中止** + Phase 4 rollback、緊急報告（PR3-HIGH-D 退化） |
| run.log にフルパスや事業所名が混入 | PII 防御退化 | **即中止** + run.log 墨塗り後共有（ADR-014 §PII 退化） |
| CLI exit code が常に 0 | exit code 判定ロジック退化 | 即報告（PR3 新規仕様の退化） |
| SmartScreen 警告 | 新 exe の HASH が違う | 「詳細情報」→「実行」。一度通れば以降は警告なし |

---

## 📞 連絡ルール

- **各 Phase 完了時に一言共有**（例「Phase 1 build.log warning 無し」）
- **想定外の結果が出たら即共有**、勝手に Phase を進めない
- **PII 情報（利用者氏名・事業所名）を含む出力を共有するときは墨塗り or マスク**
- **Phase 4 rollback を実施した場合は、その時点のスクショ + build.log + run.log（PII 墨塗り済）を必ず保存**
- **AC-8 / AC-12 で退化が観測された場合は最優先報告**（誤配布 / PII 漏洩は業務事故直結）

---

## 📚 参照

- ADR-014: ex_extractor 統合（`docs/adr/014-ex-extractor-integration.md`）
- ADR-013: 事業所ルートフォルダ管理 + 一括結合（`docs/adr/013-facility-root-bulk-merge.md`）
- 前 runbook（参考構造元）: `docs/handoff/session26-pr126-windows-runbook.md`
- PR3 #133: ex_extractor core + SFX adapter
- PR4 #135: ex_extractor デスクトップ UI 統合
- 公開 API: `src/wiseman_hub/pdf/ex_extractor.py` (`extract_one` / `extract_directory`)
- UI: `src/wiseman_hub/ui/ex_extractor_dialog.py` / `manual_distribution_dialog.py`
- CLI: `scripts/process_ex_files.py`
- 設定: `src/wiseman_hub/config.py` の `PdfMergeConfig.ex_source_dir` + `facility_aliases`
