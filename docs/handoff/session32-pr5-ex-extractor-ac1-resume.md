# Session 32 中断メモ: PR5 ex_extractor Windows 実機検証 AC-1（再開用）

**中断日時**: 2026-04-28 朝（TeamViewer タイムリミット）
**Windows 機**: `C:\Users\<USERNAME>\` ユーザー、TeamViewer 経由
**main HEAD**: `f4a242e` (Mac 側 / Windows 側 同期済)

## 今回のスコープ（ユーザー指定）

「**デスクトップアプリ（ショートカット反映含む）へのボタン組み込みが最優先**」

- AC-1 のみ（5 ボタン目「ex_ ファイル変換 + 振り分け」表示 + クリックで `ExExtractorDialog` 起動 + ショートカット経由でも新 exe 起動）
- AC-2〜AC-14 は今回スコープ外（実 .ex_ 投入 / config 編集 / SFX 起動検証は次々回以降）

## 進捗状況

| Phase | 内容 | 状態 |
|-------|------|------|
| 0-2 | exe バックアップ → `wiseman_hub.exe.bak-20260428-075301` 作成 | ✅ |
| 0-3 | `git pull --ff-only` で `f4a242e` まで同期、PR4/PR5 主要ファイル反映確認 | ✅ |
| 0-4 | `uv sync --extra dev`（Resolved 84 / Checked 76、差分なし） | ✅ |
| 0-5 | 検証用 .ex_ サンプル配置 | ⏭️ 今回スコープ外で skip |
| 1-1 | `uv run pyinstaller wiseman_hub.spec --clean --noconfirm` | ✅ Build complete |
| 1-2 | warning 検査（既知の `pycparser` / `jinja2` のみ、`wiseman_hub.*` 由来 0 件） | ✅ |
| 1-3 | `dist\wiseman_hub.exe`: 78,632,876 bytes / 2026-04-28 8:00:08 | ✅ |
| 2-1 | `~/wiseman-hub/wiseman_hub.exe` に上書き配備 | ✅ |
| 2-2 | config.toml に `ex_source_dir` / `facility_aliases` 追記 | ⏭️ 今回スコープ外で skip |
| 3 AC-1 (1) | Launcher 起動 → コンソール出ない | ✅ |
| 3 AC-1 (2) | 5 ボタン目「ex_ ファイル変換 + 振り分け」表示 | ✅（スクショ取得済） |
| 3 AC-1 (3) | 5 ボタン目クリック → `ExExtractorDialog` 起動 | ⏳ **未実施・次回最優先** |
| 追加 | デスクトップショートカット経由起動で新 exe（78,632,876 bytes）が起動 | ⏳ **未実施** |

## 次回再開時の最初のアクション

### 0. 事前確認（30 秒）

新 exe が配備済みであることを確認。LastWriteTime と Length が想定値と一致しなければ **PyInstaller ビルドからやり直し**:

```powershell
Get-Item "$HOME\wiseman-hub\wiseman_hub.exe" | Format-List LastWriteTime, Length
# 期待値: LastWriteTime = 2026-04-28 8:00:08, Length = 78632876
```

不一致の場合は Phase 1（ビルド）からやり直すか、`wiseman_hub.exe.bak-20260428-075301` から rollback する。

### 1. AC-1 (3): 5 ボタン目クリック → ExExtractorDialog 起動確認

```powershell
# PowerShell から起動（環境変数なしで OK、Dialog 起動だけなら本番 config を読んでも問題ない
# = 「実行」を押さなければ ex_source_dir / facility_root_dir には触らない）
Start-Process "$HOME\wiseman-hub\wiseman_hub.exe"
```

| 手順 | 期待 | スクショ |
|------|------|---------|
| 1. Launcher 起動（コンソール非表示） | ✅ | スクショ① Launcher 5 ボタン全表示 |
| 2. **「ex_ ファイル変換 + 振り分け」** ボタンをクリック | ✅ | — |
| 3. `ExExtractorDialog` ウィンドウが表示される | ✅（PR4 #135 統合の決定的確認） | スクショ② Dialog 起動直後 |

> ⚠️ **Dialog 内の「実行」ボタンは絶対に押さない**: AC-1 段階では本番 `default.toml` が読まれるため、`facility_root_dir = \\Tera-station\share\03.FAX(...)` を指したまま実行すると本番 NAS に検証用ファイルが書き込まれる事故になる。`ex_source_dir` も本番のまま操作される。

| 手順 | 期待 | スクショ |
|------|------|---------|
| 4. Dialog の「閉じる」ボタンで Dialog を閉じる | ✅ Launcher に戻る | — |
| 5. Launcher を閉じる | ✅ プロセス終了 | — |

スクショは PII 含まないように Dialog 起動直後の状態（実データなし想定）で取得する。事業所名・パスが万一表示されたら墨塗り。

### 2. デスクトップショートカット経由起動確認

```powershell
# ショートカット存在確認
Get-ChildItem "$HOME\Desktop\*.lnk" | Where-Object { $_.Name -match "wiseman|Wiseman" }

# ショートカットのターゲットパス確認（新 exe を指していること）
(New-Object -ComObject WScript.Shell).CreateShortcut(
  "$HOME\Desktop\<ショートカット名>.lnk"
).TargetPath
```

ショートカットをダブルクリック → Launcher 起動を確認。**起動した exe が新版（78,632,876 bytes / 2026-04-28 8:00:08）であること** をタスクマネージャー or Get-Process で確認:

```powershell
Get-Process wiseman_hub | Select-Object Path, StartTime
# Path が $HOME\wiseman-hub\wiseman_hub.exe であること
```

### 3. 失敗時の rollback（必要時のみ）

新 exe で Launcher が起動しない / Dialog が開かない / ImportError が出る等の致命的失敗が発生した場合:

```powershell
$bak = "$HOME\wiseman-hub\wiseman_hub.exe.bak-20260428-075301"
Copy-Item -Force $bak "$HOME\wiseman-hub\wiseman_hub.exe"
Write-Host "Rolled back to: $(Split-Path -Leaf $bak)"
Start-Process "$HOME\wiseman-hub\wiseman_hub.exe"
# 旧 exe での起動を確認（ex_ ボタンは存在しない）
```

その後、失敗 Phase のスクショと `build.log`（Phase 1 で生成）を取得して次セッションで原因調査。

## Windows 機の現状

- `~/wiseman-hub/wiseman_hub.exe`: **新版（PR4 統合済 78,632,876 bytes）配備済**
- `~/wiseman-hub/wiseman_hub.exe.bak-20260428-075301`: rollback 用（旧版 78,570,672 bytes）
- `~/wiseman-hub/config/default.toml`: **未編集**（`ex_source_dir` / `facility_aliases` セクションなし、`facility_root_dir` は本番 NAS `\\Tera-station\share\03.FAX(...)` のまま）
- `dist\wiseman_hub.exe`: ビルド成果物（配備済と同一）
- `build.log`: Phase 1 ビルドログ

## 発見事項（次回以降の課題）

### 1. runbook §2-2 の config パス誤記

- runbook 記載: `%USERPROFILE%\wiseman-hub\config.toml`
- 実際の解決パス（frozen exe 時）: `%USERPROFILE%\wiseman-hub\config\default.toml`
- 根拠: `src/wiseman_hub/__main__.py:43-44` の `_default_config_path()` で `Path(sys.executable).parent / "config" / "default.toml"`
- 対応: runbook §2-2 を修正する PR を起こす（Phase 5 完走時にまとめて）

### 2. Launcher の未使用ボタン削除（ユーザー提案、別 Issue 化）

ユーザーから「今つかってないボタンは削除すべき」提案あり。Launcher 5 ボタン構成:
1. PDF マージ処理を実行
2. 確認待ちセッション
3. 事業所フォルダ一括結合
4. ex_ ファイル変換 + 振り分け（PR4 新規）
5. 設定

ADR-014 §業務フロー上の位置づけ より、新ワークフロー = ① ex_ → ②a 事業所フォルダ一括結合。「PDF マージ処理」「確認待ちセッション」は旧ワークフロー（ADR-010 人間確認 state machine 由来）。

**方針**: AC-1 完了後に
- ユーザーに削除候補（どのボタンが本当に未使用か）を確認
- 別 Issue 起票（triage 基準 #5 ユーザー明示指示）
- 別 PR で UI 変更 + テスト変更を一体で実施
- 今回 PR と混ぜない（コミット粒度のため）

### 3. config 検証戦略（後日 AC-2〜14 実施時の課題）— **本セッションで対策実装済**

中断時点の課題:
- `facility_root_dir = "\\Tera-station\share\03.FAX(...)"` が本番 NAS を指している
- 検証用 .ex_ ファイル（SUCCESS / SKIPPED_AMBIGUOUS / SKIPPED_UNMATCHED）を運用環境からコピー必要
- PowerShell `$env:WISEMAN_HUB_CONFIG` はショートカット起動に継承されない落とし穴あり（Codex セカンドオピニオン指摘、Mac セッション中に発覚）

実装した対策（A1〜A5、本セッション中断記録の続編で追加）:
- ✅ `config/test.toml.example` 新規 — 本番 NAS を絶対に指さない検証用テンプレート
- ✅ `docs/handoff/ex-test-fixtures.md` 新規 — 3 種 fixture の発火条件・命名・運用環境からの調達手順
- ✅ `docs/handoff/pr5-ex-extractor-runbook.md` §2-2 全面再構成 — `test.toml` + `WISEMAN_HUB_CONFIG` 経路を推奨化、PowerShell `Start-Process` / `.ps1` ラッパー（方式 A/B）でショートカット起動の落とし穴を回避、ユーザー環境変数永続化（方式 C）を非推奨と明記
- ✅ runbook §5-2 — `test.toml` 経路でのクリーンアップ手順（環境変数解除 + ローカル fixture 削除）

**AC-2〜14 実施時の手順**: runbook §2-2 の方式 A or B で起動 → ExExtractorDialog で `ex_source_dir` 表示が `wiseman-test\ex_source` になっていることを目視確認 → AC ごとに fixture を投入。

## Issue Net 変化（Session 32 途中）

- Close: 0
- 起票: 0
- Net: 0（次回完走時に再計上）
