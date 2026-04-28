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
  - Phase 2 配布 + config 編集 (`default.toml` または検証用 `test.toml`): 3-5 分
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

## 📦 Phase 2: 配布 + config 編集（3-5 分）

### 2-1. exe 上書き

```powershell
Copy-Item -Force dist\wiseman_hub.exe "$HOME\wiseman-hub\wiseman_hub.exe"
Get-Item "$HOME\wiseman-hub\wiseman_hub.exe" | Format-List LastWriteTime, Length
```

**期待**: LastWriteTime が今、Length がビルド直後のサイズと一致。

### 2-2. config を編集して検証パスを設定（**重要: 本番 config 汚染防止**）

> ℹ️ **config パスについて**: frozen exe (PyInstaller) は `Path(sys.executable).parent / "config" / "default.toml"` を参照する（`__main__._default_config_path`）。本番 config の正しいパスは **`%USERPROFILE%\wiseman-hub\config\default.toml`**（旧記載 `%USERPROFILE%\wiseman-hub\config.toml` は誤り）。

#### 推奨: 検証専用 config (`test.toml`) + `WISEMAN_HUB_CONFIG` 切替

本番 config (`default.toml`) を直接編集すると、`facility_root_dir` が本番 NAS (`\\Tera-station\share\03.FAX(...)`) を指したまま検証用 alias が混ざる、または検証用パスを戻し忘れるリスクがある。**検証では `test.toml` を別途用意し、`WISEMAN_HUB_CONFIG` で参照を切り替える** 方式を推奨する（`__main__._default_config_path` 優先順位 1 位、未編集本番 config はそのまま残る）。

```powershell
# 1. リポジトリの test.toml.example を Windows 機にコピー
Copy-Item "$HOME\Projects\wiseman-auto-sys\config\test.toml.example" `
  "$HOME\wiseman-hub\config\test.toml"

# 2. 検証用ローカルパスを作成（本番 NAS は絶対に使わない）
New-Item -ItemType Directory -Force -Path "$HOME\wiseman-test\ex_source"
New-Item -ItemType Directory -Force -Path "$HOME\wiseman-test\facilities\本田デイサービス"
New-Item -ItemType Directory -Force -Path "$HOME\wiseman-test\facilities\本田訪問サービス"

# 3. test.toml を notepad で開き、検証用 ex_source_dir / facility_root_dir / facility_aliases を編集
notepad "$HOME\wiseman-hub\config\test.toml"
```

`test.toml` の主要編集ポイント:

```toml
[pdf_merge]
ex_source_dir = "C:\\Users\\sasak\\wiseman-test\\ex_source"
facility_root_dir = "C:\\Users\\sasak\\wiseman-test\\facilities"

[pdf_merge.facility_aliases]
"本田デイサービス" = ["HD"]
"本田訪問サービス" = ["HV"]
```

検証用 `.ex_` fixture (3 種: SUCCESS / AMBIGUOUS / UNMATCHED) の調達・命名・配置構造は [`ex-test-fixtures.md`](./ex-test-fixtures.md) 参照。

**重要な検証ルール**（ADR-014 §facility_aliases 入力検証）:
1. canonical（key）は空文字列でない
2. value が list 型（str を直接書くと TypeError で fail-fast）
3. value 要素が非空 str
4. 同じ list 内で alias 重複なし
5. 異なる canonical 間で同じ alias を共有しない（global 一意性）
6. alias が他 canonical と一致しない

違反時は起動時に `ValueError` / `TypeError` で fail-fast。

#### `WISEMAN_HUB_CONFIG` 注入での起動方法（**ショートカット起動の落とし穴に注意**）

PowerShell で `$env:WISEMAN_HUB_CONFIG = "..."` を設定しても、**デスクトップショートカットをエクスプローラーからダブルクリック起動した exe はその環境変数を継承しない**（ショートカット起動は explorer.exe からの spawn で、PowerShell セッションのプロセス環境とは別ツリーになるため）。検証時は **PowerShell 経由で起動** する以下の 2 方式のいずれかを使う:

**方式 A（簡易、その場で投入）**:

```powershell
$env:WISEMAN_HUB_CONFIG = "$HOME\wiseman-hub\config\test.toml"
Start-Process "$HOME\wiseman-hub\wiseman_hub.exe"
```

**方式 B（推奨、検証セッション毎に再現可能）**: 検証専用 `.ps1` ラッパーを作成

```powershell
@'
$env:WISEMAN_HUB_CONFIG = "$HOME\wiseman-hub\config\test.toml"
& "$HOME\wiseman-hub\wiseman_hub.exe"
'@ | Out-File -FilePath "$HOME\wiseman-test\wiseman-test.ps1" -Encoding utf8

# 以後の起動:
& "$HOME\wiseman-test\wiseman-test.ps1"
```

> ⚠️ **方式 C（ユーザー環境変数として永続設定）は非推奨**: `[Environment]::SetEnvironmentVariable("WISEMAN_HUB_CONFIG", ...)` で永続化すると、検証完了後の解除を忘れると本番起動も `test.toml` を読み続ける致命的事故になる。検証セッション毎にスコープ限定する方式 A / B を使う。

#### `test.toml` が読み込まれたことを確認

Launcher 起動後、ExExtractorDialog を開いて `ex_source_dir` 表示欄を確認:

- ✅ `C:\Users\...\wiseman-test\ex_source` が表示されている → 成功
- ❌ 本番 NAS パス（`\\Tera-station\share\...`）が表示された → `WISEMAN_HUB_CONFIG` が継承されていない。**即終了して起動方法を見直す**（ショートカット起動を疑う）

#### 代替: 本番 `default.toml` を直接編集（非推奨、Phase 5-2 で戻し作業必須）

何らかの理由で `WISEMAN_HUB_CONFIG` 経路を使えない場合のみ、`%USERPROFILE%\wiseman-hub\config\default.toml` を notepad で開き、`[pdf_merge]` セクション内に以下を追記する（Phase 5-2 で必ず元に戻す）:

```toml
[pdf_merge]
ex_source_dir = "C:\\Users\\sasak\\OneDrive\\デスクトップ\\本田様\\ex_source"  # 検証用に一時設定
# facility_root_dir は本番 NAS のまま使う場合は本番 NAS 上に検証用フォルダを作らない／検証用 .ex_ も投入しない こと

[pdf_merge.facility_aliases]
"<本田様の事業所正式名>" = ["<短縮名 1>", "<別表記 1>"]
```

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
| 4 | ExExtractorDialog 起動中、Launcher 側のボタンが操作可能でも `grab_set()` で実質ブロック | ✅（既知挙動） |

新ダイアログが開かない / ImportError なら **Phase 4 (rollback) へ**。

**既知制限**: `launcher.py:_set_busy()` は他処理（PDF マージ等）の実行中に `_btn_ex_extractor` を disabled にしない実装。逆方向（ExExtractorDialog 起動中に Launcher 側を `grab_set()` で blocking）は機能しているため業務影響は限定的。本 runbook スコープ外、PR6 以降で対応検討。

---

### AC-2: ex_source_dir 設定（TOML 直接編集）

| 手順 | 期待 |
|------|------|
| 1. 使用中の config（`default.toml` または `test.toml`）の `ex_source_dir` が ExExtractorDialog の表示欄に反映 | ✅ Phase 2-2 で設定したパスが表示 |
| 2. 「実行」ボタンが活性化（disabled でない） | ✅ |
| 3. ex_source_dir に有効な `.ex_` ファイルが配置されている状態で「実行」が成功する | ✅ |

**実装上の挙動メモ**: `ex_source_dir = ""` の場合、`ex_extractor_dialog.py:313` で `Path(".")`（cwd）にフォールバックする実装。ボタンは `source_dir.exists()` で disabled 判定するため cwd 存在で enabled のまま。空文字列を「未設定」として扱う UI 警告は実装されていない（PR6 settings タブ化で対応予定）。本 AC では Phase 2-2 で正しいパスを設定済の前提で確認する。

---

### AC-3: facility_aliases 設定（TOML 直接編集 + 入力検証）

**正常系**: Phase 2-2 の TOML で起動成功 → 検証ルール（ADR-014 §facility_aliases 入力検証 6 項目）すべて PASS。

**実装上の責任分担**:
- `_coerce_facility_aliases` (`config.py:148-172`): 型検証（value が list / 要素が str）→ 違反は `TypeError`
- `_validate_facility_aliases` (`config.py:175-222`): 値検証（重複・空文字列・global 一意性等）→ 違反は `ValueError`

**異常系（任意、5 分追加）**: 入力検証が fail-fast することを確認:

| 違反パターン | 期待例外 | 検証主体 |
|------------|---------|---------|
| `"事業所A" = "短縮"` (str 直書き) | 起動時 `TypeError` | `_coerce_facility_aliases` |
| `"事業所A" = []` (空 list) | 起動時 `ValueError` | `_validate_facility_aliases` |
| `"事業所A" = ["短縮", "短縮"]` (list 内重複) | 起動時 `ValueError` | `_validate_facility_aliases` |
| `"事業所A" = ["短縮"]` + `"事業所B" = ["短縮"]` (global 重複) | 起動時 `ValueError` | `_validate_facility_aliases` |
| `"事業所A" = ["事業所B"]` (alias が他 canonical と一致) | 起動時 `ValueError` | `_validate_facility_aliases` |

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

**注意**: 手動振り分けで extract_one が失敗（MOVE_CONFLICT 等）した場合、`resolve_result.reason` が `MANUAL_OVERRIDE` のままでも item は `result.failed` に計上される。「手動確定成功」カウントは SUCCESS + MANUAL_OVERRIDE のみで構成される（`ex_extractor_dialog.py:208-214`）。手動振り分け実行で失敗した件数は「失敗」セクションで確認する。

---

### AC-8: mtime フィルタ（SFX 実行中の Desktop 無関係 PDF が誤配布されない）

**シナリオ**: SFX 実行中にユーザーが別途 Desktop に保存した無関係 PDF が `_collect_new_pdfs` の watch_dir に含まれていても誤配布されない。

| 手順 | 期待 |
|------|------|
| 1. SUCCESS 経路サンプル `.ex_` を ex_source_dir に配置 | - |
| 2. 別ターミナルで以下を準備（`.ex_` 実行直前に投入） | - |

```powershell
# Desktop に無関係 PDF を生成するワンライナー（SFX 起動「直前」に実行）
$tmp = Join-Path $env:USERPROFILE "Desktop\無関係_$(Get-Date -Format yyyyMMddHHmmss).pdf"
"%PDF-1.4`ndummy" | Out-File -FilePath $tmp -Encoding ascii
Write-Host "Created: $tmp"
```

**注意**: PowerShell では `%USERPROFILE%` は展開されない（cmd 構文）。`$env:USERPROFILE` を使う。`Set-Content -Encoding Byte` は PS 6+ で削除されているため `Out-File -Encoding ascii` で代替（PDF として有効である必要はなく、mtime フィルタの対象になる任意のファイルで OK）。

| 3. ExExtractorDialog で「実行」を押下した直後に上記コマンドを別ターミナルで実行 | - |
| 4. SFX 完了 → 完了サマリ確認 | ✅ |
| 5. **無関係 PDF が事業所フォルダに移動されていない** | ✅（誤配布 KPI 直撃の構造的防御、ADR-014 PR3-HIGH-D） |
| 6. Desktop に無関係 PDF が残ったまま | ✅ |

mtime フィルタは `ex_extractor.py` の定数 `_MTIME_GRACE_SEC`（current: 5.0 秒）のマージンで NTP 後方ステップを吸収しつつ、SFX 起動前に既存していた PDF を除外する。コード変更で値が変わった場合は本 AC の前提も更新が必要。

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
| 3. 完了サマリの集計行 | ✅ `失敗: 1 件` + `⚠ 要確認 (一部抽出/移動): 1 件` の**両方**が表示される |
| 4. サマリ詳細セクション | ✅ 同じ filename が `--- 失敗 ---` セクションと `--- 要確認 ---` セクションの**両方**に出る（dual rendering、`ex_extractor_dialog.py:472-479`） |
| 5. 該当行に `[MOVE_CONFLICT]` または `[MOVE_IO_ERROR]` 表示 | ✅ |
| 6. 複数 PDF のうち一部移動済の場合 `(一部 PDF 移動済: N 件)` 表示 | ✅（運用情報消失防止、ADR-014 PR3-HIGH-A） |

**注意**: dual rendering は仕様（運用情報の二重可視化、ADR-014 PR3-HIGH-A）。同じ filename が 2 セクションに出ることを「重複バグ」と誤判定しないこと。

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

**チェック 1: フルパス漏洩（最重要、絶対禁止）**

```powershell
# C:\Users\... のフルパスが log に含まれていないこと
Select-String -Path run.log -Pattern "C:\\\\Users\\\\.*\\.(ex_|pdf)"
# 期待: 0 ヒット（実装は OSError.str() を type(e).__name__ のみで伝搬する設計、PR3-HIGH-C）
```

**チェック 2: 事業所名漏洩**

```powershell
# 事業所正式名が log に含まれているのは「設定不整合」セクションの orphan 行のみ許容
# (CLI レイヤの orphan_alias_canonicals 通知、ADR-014 §PII 保護方針)
Select-String -Path run.log -Pattern "<事業所正式名 1>|<事業所正式名 2>" -Context 0,2
# 期待:
#   - ex_extractor モジュール本体の logger 出力にヒットしない
#   - `--- 設定不整合 ---` セクション以下の `! <canonical>` 行のみヒット (Phase 2-3 で orphan を意図的に作成した場合)
# Phase 2-3 で orphan を作っていないなら 0 ヒットが期待
```

**チェック 3: 抽出 PDF 名漏洩（filename のみ許容、フルパス禁止）**

```powershell
# CLI summary の `--- 失敗 ---` `--- 要確認 ---` 等のセクションでは
# .pdf filename が出ることがある (PII 防御範囲外、運用者識別用)
# 一方、ex_extractor logger 由来の pdf.name 出力は stat 失敗時の warning 等
# (ex_extractor.py:275-279) に限定される
# 重要なのは「PDF 名 + フルパス」の同時露出がないこと

Select-String -Path run.log -Pattern "C:\\\\.*\.pdf|/[a-zA-Z]+/.*\.pdf"
# 期待: 0 ヒット (Windows パス + UNIX パス両方の絶対パス検査)
```

**期待結果**:
- フルパスが run.log に一切含まれない (チェック 1: 0 ヒット必須)
- 事業所名は CLI 設定不整合セクション内 orphan 行に限定 (チェック 2)
- PDF 名 + フルパスの同時露出なし (チェック 3: 0 ヒット必須)

**もしチェック 1 / チェック 3 でヒットしたら → 即中止 + run.log の該当行を墨塗りしてから報告**（PII 防御退化、ADR-014 §PII 保護方針退化）。チェック 2 で `--- 設定不整合 ---` セクション**以外**でヒットしたら同様に即中止 + 報告。

---

### AC-13: CLI 終了コード 0/1/2（process_ex_files.py 経由）

UI とは独立した CLI 経路の動作確認。各シナリオ実行前に **ex_source_dir を空にして該当サンプルのみ配置** すること（成功した `.ex_` は移動でクリーンアップされるため、再投入しないと次回 0 件で実行される）。

| シナリオ | 期待 exit code | サンプル構成 |
|---------|---------------|------------|
| 全件 SUCCESS | `0` | AC-4 用サンプル 1 件のみ |
| pending あり、failed なし | `2` | AC-5 (AMBIGUOUS) または AC-6 (UNMATCHED) サンプル 1 件のみ |
| failed あり、pending なし | `1` | AC-10 用 MOVE_CONFLICT サンプル 1 件のみ |
| failed あり + pending あり（優先順検証） | `1`（pending 2 が無視される） | AC-5 + AC-10 サンプル各 1 件 |

```powershell
cd $HOME\Projects\wiseman-auto-sys
$exSrc = "<使用中の config (default.toml または test.toml) の ex_source_dir パス>"

# シナリオ 1: 全件 SUCCESS
Remove-Item "$exSrc\*.ex_" -ErrorAction SilentlyContinue
Copy-Item "<AC-4 サンプル.ex_>" "$exSrc\"
uv run python scripts/process_ex_files.py
echo $LASTEXITCODE
# 期待: 0

# シナリオ 2: pending あり (AMBIGUOUS or UNMATCHED)
Remove-Item "$exSrc\*.ex_" -ErrorAction SilentlyContinue
Copy-Item "<AC-5 サンプル.ex_>" "$exSrc\"
uv run python scripts/process_ex_files.py
echo $LASTEXITCODE
# 期待: 2

# シナリオ 3: failed あり (MOVE_CONFLICT、pending なし)
Remove-Item "$exSrc\*.ex_" -ErrorAction SilentlyContinue
Copy-Item "<AC-10 サンプル.ex_>" "$exSrc\"
# 事業所フォルダに同名 PDF を事前配置（AC-10 と同じセットアップ）
uv run python scripts/process_ex_files.py
echo $LASTEXITCODE
# 期待: 1

# シナリオ 4: failed + pending 同時 → 1 が優先することを確認（最重要）
Remove-Item "$exSrc\*.ex_" -ErrorAction SilentlyContinue
Copy-Item "<AC-5 サンプル.ex_>", "<AC-10 サンプル.ex_>" "$exSrc\"
uv run python scripts/process_ex_files.py
echo $LASTEXITCODE
# 期待: 1（failed が 1 件以上なら pending の有無に関わらず 1、process_ex_files.py:127-132）
```

CLI の stderr 出力フォーマット（`--- 手動振り分け待ち ---` / `--- 失敗 ---` / `--- 設定不整合 ---`）も合わせて確認。シナリオ 4 で exit code が 2 になったら exit code 判定ロジックの退化バグ → 即中止 + 報告。

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
1. **最優先**:
   - 検証で `test.toml` 経路を使った場合: `WISEMAN_HUB_CONFIG` 環境変数を解除（`Remove-Item Env:\WISEMAN_HUB_CONFIG -ErrorAction SilentlyContinue`）。本番 `default.toml` は未編集のはずなので追加クリーンアップ不要。
   - 万一 `default.toml` を直接編集していた場合: 検証用 alias（`"消えた施設"` 等）と `ex_source_dir` 検証用パスを削除し、元の運用設定に戻す（旧 exe は本 PR で導入された TOML スキーマを期待しないため、検証用設定を残すと旧 exe の動作に影響する可能性）
2. 旧 exe で動作することを確認
3. 失敗 Phase のスクショ + `build.log` + `run.log`（PII 墨塗り済）を共有
4. 次セッションで原因調査

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

### 5-2. 検証用 config / 環境変数のクリーンアップ

**検証で `test.toml` 経路を使った場合（推奨方式）**:

```powershell
# 1. WISEMAN_HUB_CONFIG 環境変数を解除（本番起動で本番 config が読まれるよう戻す）
Remove-Item Env:\WISEMAN_HUB_CONFIG -ErrorAction SilentlyContinue

# 2. 検証用 .ex_ + 振り分け済 PDF + 事業所フォルダを完全削除（PII 含むため確実に削除）
Remove-Item -Recurse -Force "$HOME\wiseman-test"

# 3. test.toml そのものの削除（次回検証時に test.toml.example から作り直す）
Remove-Item "$HOME\wiseman-hub\config\test.toml" -ErrorAction SilentlyContinue
```

**`default.toml` を直接編集していた場合（非推奨方式）**:

検証で追加した orphan alias（`"消えた施設"` 等）と検証用 `ex_source_dir` を削除し、本番運用の `facility_aliases` 設定に戻す。本番 `facility_root_dir` も検証パスに書き換えていた場合は元の本番 NAS パスに戻す。

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
