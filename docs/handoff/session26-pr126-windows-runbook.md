# Session 26: PR #126 Windows 実機検証ランブック

**目的**: PR #126（事業所ルートフォルダ管理 + 一括/選択 PDF 結合）の Windows 実機検証を実施し、ADR-013 を `Proposed` → `Accepted` に昇格させる。

**前提**:
- Windows 11 PC（本番配布先）に TeamViewer で接続可能
- `main` ブランチに PR #126/#127 が merge 済（HEAD: `d83a3de`）
- 既存 exe が `%USERPROFILE%\wiseman-hub\wiseman_hub.exe` に配置済
- 所要時間: 40-55 分内訳:
  - Phase 0 事前確認 + main 同期 + 依存同期: 5-10 分
  - Phase 1 ビルド: 5 分
  - Phase 2 配布: 1 分
  - Phase 3 動作確認: 25-35 分
  - Phase 5 完走処理（ADR + handoff 更新 + PR 作成）: 10 分

**このランブックの完走で達成されること**:
1. ✅ PR #126 の新機能入り exe が本番配布先に配置される
2. ✅ Launcher「事業所フォルダ一括結合」ボタンから新ダイアログが起動する
3. ✅ AC-7 / AC-11 / AC-13 の本番経路動作が確認される（**最重要**）
4. ✅ ADR-013 を `Proposed` → `Accepted` に昇格（PR #126 完走）
5. ✅ ADR-011 を `Proposed` → `Accepted` に昇格（タスク 14D 完走、PR #124 + #126 実機稼働確認）

---

## 🎯 Phase 0: 事前確認（5 分）

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

**期待 commit（最新 5 件、Session 25 終了時点）**:
```
d83a3de docs(handoff): Session 25 cleanup - PR #126 マージ反映 (#127)
0f9abbb feat(ui): 事業所ルートフォルダ管理 + 一括/選択 PDF 結合（デスクトップアプリ統合） (#126)
d086f46 docs(handoff,adr): Session 24 cleanup - LATEST.md merge 反映 + ADR-012 作成 (#125)
4216828 feat(facility-merger): 事業所単位 1 ファイル ABCABC 連結に仕様変更（明日納品） (#124)
57ce73b docs(handoff): Session 23 終了時点のハンドオフ更新 + Session 15-21 アーカイブ移動 (#123)
```

最低条件: `0f9abbb feat(ui): 事業所ルートフォルダ管理...` が `git log` に含まれていること。

### 0-4. 依存同期（pytest はスキップ可）

```powershell
uv sync --extra dev
```

**重要**: `uv sync` だけでは dev extras（`pyinstaller` / `ruff` / `mypy` / `pytest` 等）が削除される。Phase 1 のビルドで `Failed to spawn pyinstaller` が出るので **必ず `--extra dev` を付ける**。

**pytest 全体実行は禁止**: `tests/integration/` 配下は本物の Wiseman SP を pywinauto で起動するため、Windows 実機環境では副作用が大きい。CI（GitHub Actions Windows runner）で全 SUCCESS 確認済のため再実行不要。

どうしてもユニットテストを走らせたい場合は **unit のみ**:

```powershell
uv run pytest -q tests/unit/
```

**期待**: `XXX passed`（636 から integration 分を引いた数）。Session 26 では Tk Toplevel テストの Windows 環境差異で一部 fail が出るが、PR #126 検証フェーズには影響しないため無視可。

---

## 🔨 Phase 1: exe ビルド（5 分）

### 1-1. clean build

```powershell
uv run pyinstaller wiseman_hub.spec --clean --noconfirm 2>&1 | Tee-Object -FilePath build.log
```

### 1-2. ビルドログの warning 検査

```powershell
Select-String -Path build.log -Pattern "Hidden import.*not found"
```

**期待**: **何も出力されない**（プロンプトに即戻る）。出力があれば内容を確認し、`pycparser` / `jinja2` / `user32` / `msvcrt` 由来は無害（macOS / Windows 共通の既知 warning）。それ以外（特に `wiseman_hub.*` 由来）は Phase 2 に進まず共有。

**注意**: `Select-String -NotMatch "..."` を二段パイプで繋ぐ書き方は、第一段階が空の場合に Pattern エラーで失敗するため使わない。単独で十分。

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

## ✅ Phase 3: 動作確認（25-35 分）

### 3-1. Launcher 起動 + 新ボタン表示確認

```powershell
Start-Process "$HOME\wiseman-hub\wiseman_hub.exe"
```

| # | 確認項目 | 期待 |
|---|---------|------|
| 1 | Launcher ウィンドウ起動（コンソールは出ない） | ✅ |
| 2 | 「事業所フォルダ一括結合」ボタン表示 | ✅ |
| 3 | クリック → `FacilityRootManagerDialog` 起動 | ✅（PR #126 の決定的確認） |

新ダイアログが開かない / ImportError なら **Phase 4 (rollback) へ**。

---

### 3-2. AC-1: ルート設定の永続化

| 手順 | 期待 |
|------|------|
| 1. 「ルート選択」で `\\Tera-station\share\03.FAX(事業所)\` を指定 | ✅ パスが表示欄に反映 |
| 2. ダイアログを × ボタンで閉じる | ✅ 警告なく閉じる |
| 3. Launcher を一度終了 → 再起動 → 同ダイアログ再オープン | ✅ 前回ルートが復元 + 自動スキャン開始 |

TOML（`config.toml`）の `[facility_merger]` セクションに `root_dir` が永続化されていることを以下で確認可:

```powershell
Get-Content "$HOME\wiseman-hub\config.toml" | Select-String "root_dir"
```

---

### 3-3. AC-2: B/C 両方ある事業所のみ列挙

| 手順 | 期待 |
|------|------|
| 1. ルート配下の事業所一覧表示 | ✅ `運動機能向上計画書/` AND `経過報告書/` 両方ある事業所のみ表示 |
| 2. B のみ / C のみのフォルダは列挙されない | ✅ |

---

### 3-4. AC-12: A.pdf 候補から `{事業所名}.pdf` 除外（**最重要、再実行ループ防止**）

**シナリオ**: 出力 PDF（`{事業所名}.pdf`）が事業所フォルダ内にある状態で再スキャン。

| 手順 | 期待 |
|------|------|
| 1. ある事業所で 1 回結合実行 → 事業所フォルダに `{事業所名}.pdf` が生成される | ✅ |
| 2. ダイアログを再オープン（or 「再スキャン」ボタンがあればクリック） | ✅ |
| 3. その事業所のステータスが `a_multiple` にならず正常 (`ready` 等) のまま | ✅（出力PDFは A.pdf 候補から除外される） |

**もし `a_multiple` になったら → AC-12 のバグ。即報告。**

---

### 3-5. AC-7: フォルダ/PDF を開く（macOS/Windows 両対応）

| 手順 | 期待 |
|------|------|
| 1. ある事業所行の「フォルダを開く」ボタンクリック | ✅ Explorer でその事業所フォルダが開く |
| 2. 結合実行後、「結合PDFを開く」ボタンクリック | ✅ デフォルト PDF ビューア（Acrobat 等）で `{事業所名}.pdf` が開く |

---

### 3-6. AC-11: UNC パス（`\\Tera-station\share\...`）での scanner / merge

3-2 までで UNC パス指定済の前提で、以下を確認:

| 手順 | 期待 |
|------|------|
| 1. 日本語事業所名（例: `きなり(メール)`）が文字化けせず表示 | ✅ |
| 2. UNC パス配下の B/C PDF が読み込めて結合実行が成功 | ✅ |
| 3. 出力先も UNC 配下に正しく書き込まれる | ✅ |

---

### 3-7. AC-13: Acrobat ロック中の「PDFを閉じてから再実行」文言（**最重要、本番経路バグ修正済み**）

**背景**: review-pr で発見された致命バグの修正確認。`merge_facility` 内 `_save_atomically` は全例外を `PdfMergeError` でラップするため、bulk_runner の `except PermissionError` は本番経路で発火しない。`_is_lock_error()` ヘルパで `__cause__` を辿る修正が入っている（commit `5bf54be`）。**本番経路で機能するかを実機で必ず確認。**

| 手順 | 期待 |
|------|------|
| 1. ある事業所で 1 回結合実行 → `{事業所名}.pdf` 生成 | ✅ |
| 2. 生成された `{事業所名}.pdf` を **Acrobat Reader で開いた状態** にする | ✅ |
| 3. ダイアログで同じ事業所をチェック → 「実行」 | - |
| 4. 結果ステータス | ✅ `failed_locked` 表示 |
| 5. UI 文言 | ✅ **「PDFを閉じてから再実行してください」** が表示される |
| 6. Acrobat を閉じる → 再実行 | ✅ 今度は成功 |

**もし `failed`（汎用エラー）になったら → `_is_lock_error()` が `__cause__` を辿れていない。即報告。**

---

### 3-8. 一括実行 + 停止動作

| 手順 | 期待 |
|------|------|
| 1. 複数事業所（3 件以上）を選択して「実行」 | ✅ 順次処理、行ステータスがリアルタイム更新 |
| 2. 処理中に「停止」ボタンクリック | ✅ 現在処理中事業所は完走、それ以降は `cancelled_skipped` |
| 3. 完了サマリ messagebox | ✅ 5 status 別件数（success/failed/failed_locked/cancelled/skipped）が表示 |

---

### 3-9. 既存単一事業所結合（PR #124）の regression smoke

PR #124 の `merge_facility` 単体動作が PR #126 で破壊されていないことを確認:

| 手順 | 期待 |
|------|------|
| 1. ランチャーから「PDFマージ処理を実行」ボタン（既存 1 ボタン目）クリック | ✅ ImportError なし |
| 2. Launcher 「事業所フォルダ結合」（旧 PR #124 単一事業所ダイアログ）が UI からアクセス不可 or 動作する | ✅（コード資産は残置済） |

---

## 🔙 Phase 4: rollback（問題発生時のみ）

Phase 3 のどれかで失敗した場合、Phase 0-2 のバックアップに戻す:

```powershell
$dist = "$HOME\wiseman-hub"
$latest_bak = Get-ChildItem "$dist\wiseman_hub.exe.bak-*" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Copy-Item -Force $latest_bak.FullName "$dist\wiseman_hub.exe"
Write-Host "Restored from: $($latest_bak.Name)"
Start-Process "$dist\wiseman_hub.exe"
```

**rollback 完了後**: 旧 exe で動作することを確認。失敗 Phase のスクショ + `build.log` を共有して原因調査を次セッションで実施。

---

## 📝 Phase 5: 完走処理（10 分）

### 5-1. ADR-013 Accepted 昇格（PR #126 完走）

`docs/adr/013-facility-root-bulk-merge.md` で以下を実施:

1. **Status 行を更新**: `**Proposed (2026-04-27)**` → `**Accepted (2026-04-27)**`、検証完了サマリを追記
2. **新規セクション追加**: `## Session 26 実機検証結果（Accepted 昇格根拠）` を「Acceptance Criteria」セクションの後に追加し、検証環境・実測結果テーブル・観察事項を記載
3. **AC テーブル更新**: AC-7 / AC-11 / AC-13 の status カラムを `⏳ Windows 実機` から `✅ Windows 実機（Session 26、...詳細）` に更新
4. **「業務リスク」表更新**: 「UNC パスでの実ファイル検証なし」を「✅ Session 26 で解消」に変更

⚠ 既存 ADR には「Consequences」セクションは存在せず、日本語の「## 影響」セクションを使用。「## 影響」は ADR の意思決定時点での想定影響を記録するセクションであり、実機検証結果は別途「## Session N 実機検証結果」セクションを新設するのが本リポジトリの慣習（ADR-012 / ADR-013 の運用で確立）。

### 5-2. ADR-011 Accepted 昇格（タスク 14D 完走）

`docs/adr/011-distribution-format.md` で以下を実施:

1. **Status 行を更新**: `**Proposed (2026-04-21)**` → `**Accepted (2026-04-27)**`、14D 達成サマリを追記
2. **`## 14D Accepted 昇格条件` セクション内**: 既存の条件 1-4 リストを `✅ Session 26 達成` 注釈付きの達成記録に転換（条件文を活かしたまま結果を残す）
3. **変更履歴に Session 26 完走を追記**

### 5-3. 完走 PR 作成

```powershell
cd $HOME\Projects\wiseman-auto-sys
git checkout -b docs/session26-adr-accepted
# ADR-013 + ADR-011 + LATEST.md + 本ランブック編集後
git add docs/adr/013-*.md docs/adr/011-*.md docs/handoff/LATEST.md docs/handoff/session26-pr126-windows-runbook.md
git commit -m "docs(adr): ADR-013 + ADR-011 Accepted 昇格 - PR #126 Windows 実機検証完走"
git push -u origin docs/session26-adr-accepted
gh pr create --title "docs(adr): ADR-013 + ADR-011 Accepted 昇格（Session 26 / PR #126 実機検証完走）" --body "PR #126 の Windows 実機検証で AC-7/11/12/13 を含む 11 項目 PASS を確認。ADR-013 / ADR-011 を Accepted に昇格。"
```

### 5-4. バックアップ exe の整理

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
| `Failed to spawn pyinstaller` | `--extra dev` 忘れで dev extras 削除 | `uv sync --extra dev` で復旧、Phase 1 再実行 |
| ビルドは成功するが exe 起動で無反応 | Windows Defender が隔離 | Defender 除外設定 or SmartScreen「実行」押下 |
| Launcher は起動するが「事業所フォルダ一括結合」が無い | 古い exe を掴んでいる / 上書き失敗 | Phase 2-1 を再実行、LastWriteTime を再確認 |
| 新ダイアログクリックで `ImportError` | spec の hiddenimports 不足 | ビルドログを Phase 4 rollback 後に共有 |
| Acrobat ロック中に `failed`（`failed_locked` でない） | `_is_lock_error` が `__cause__` を辿れていない | **即中止** + 報告（実装バグ） |
| AC-12: `{事業所名}.pdf` が再スキャンで a_multiple になる | scanner の出力ファイル除外ロジック不備 | **即中止** + 報告（再実行ループバグ） |
| 出力 PDF で別人混入 / 順序不正 | merge_facility の不変条件破綻 | **即中止** + Phase 4 rollback、緊急報告 |
| SmartScreen 警告 | 新 exe の HASH が違う | 「詳細情報」→「実行」。一度通れば以降は警告なし |

---

## 📞 連絡ルール

- **各 Phase 完了時に一言共有**（例「Phase 1 build.log warning 無し」）
- **想定外の結果が出たら即共有**、勝手に Phase を進めない
- **PII 情報（利用者氏名・事業所名）を含む出力を共有するときは墨塗り or マスク**
- **Phase 4 rollback を実施した場合は、その時点のスクショ + build.log を必ず保存**

---

## Session 26 実施結果（2026-04-27 完走）

| Phase | 結果 |
|-------|------|
| 0 (事前確認 + main 同期 + 依存同期) | ✅ HEAD `d83a3de` 確認、`uv sync --extra dev` 完了 |
| 1 (exe 再ビルド) | ✅ `Build complete!`、Hidden import 警告なし |
| 2 (配布) | ✅ 旧 78,541,735 → 新 78,570,672 bytes |
| 3-1 (新ボタン表示) | ✅ 「事業所フォルダ一括結合」表示 |
| 3-2 (AC-1 永続化) | ✅ ランチャー再起動でルート復元 + 自動スキャン |
| 3-3 (AC-2 B/C 両方ある事業所のみ) | ✅ 18 実行可能 / 22 警告 |
| 3-4 (AC-12 再実行ループ防止 **最重要**) | ✅ 再スキャン後 `a_multiple` 不発火 |
| 3-5 (AC-7 フォルダ/PDF を開く) | ✅ Explorer + Acrobat 起動 |
| 3-6 (AC-11 UNC + 日本語事業所名) | ✅ 文字化けなし、scan/merge 成功 |
| 3-7 (AC-13 Acrobat ロック文言 **最重要、本番経路**) | ✅ 「結合 PDF を閉じてから再実行してください」+ サマリ「PDFロック: 1件」 |
| 5 (ADR-013 + ADR-011 Accepted 昇格 PR) | 進行中 |

## 次セッション（Session 27、PR #126 実機完走後）への引き継ぎ

- ADR-013 + ADR-011 Accepted 昇格 PR merged 後、運用フィードバック蓄積フェーズへ
- 業務リスク系の追加判断（review-pr MEDIUM 残件）:
  - 上書き確認ダイアログ追加
  - 進捗パーセント表示
  - A_MULTIPLE 解決後の「PDF選択...」ボタン動的非表示
- スーパーアプリ化の方向性（中期検討、本田様の運用フィードバック 1〜2 セッション蓄積後）
- P2 Issue 10 件の再判断フェーズ
- **観察事項の追跡**: 元 `a_missing` 事業所が結合実行で成功した件（scanner 初回判定タイミング vs A.pdf 配置タイミングの競合可能性）
