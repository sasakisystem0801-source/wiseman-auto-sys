# Session 32 中断メモ: PR5 ex_extractor Windows 実機検証 AC-1（再開用）

**中断日時**: 2026-04-28 朝（TeamViewer タイムリミット）
**Windows 機**: `C:\Users\sasak\` ユーザー、TeamViewer 経由
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

1. TeamViewer で Windows PC 接続、PowerShell 起動
2. **Launcher 起動**: `Start-Process "$HOME\wiseman-hub\wiseman_hub.exe"`
3. **「ex_ ファイル変換 + 振り分け」ボタンをクリック** → `ExExtractorDialog` が開くこと確認
   - 重要: Dialog 内の「実行」ボタンは押さない（config 未設定のため）
   - スクショ取得（PII 注意、Dialog 起動直後は実データなし想定）
4. Dialog 「閉じる」→ Launcher 閉じる
5. **デスクトップショートカット経由起動確認**:
   - ショートカット存在確認: `Get-ChildItem "$HOME\Desktop\*.lnk" | Where-Object { $_.Name -match "wiseman|Wiseman" }`
   - ショートカットダブルクリック → 新 exe（LastWriteTime 2026-04-28 8:00:08）が起動することを確認
   - ショートカットのターゲットパス確認: `(New-Object -ComObject WScript.Shell).CreateShortcut("$HOME\Desktop\<ショートカット名>.lnk").TargetPath`

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

### 3. config 検証戦略（後日 AC-2〜14 実施時の課題）

`facility_root_dir = "\\Tera-station\share\03.FAX(...)"` が本番 NAS を指しているため、AC-2〜14 検証時は以下のいずれかで本番フォルダ汚染を防ぐ必要あり:
- 案 A: `~/wiseman-hub/config/test.toml` を新規作成 + `WISEMAN_HUB_CONFIG` で参照切替（推奨）
- 案 B: 本番 config を一時編集 + 検証後に手動削除（リスクあり）
- 案 C: `facility_root_dir` を一時的にローカルパスに書き換え（戻し忘れリスク）

加えて検証用 .ex_ ファイル（SUCCESS / SKIPPED_AMBIGUOUS / SKIPPED_UNMATCHED の 3 種）を本田様の運用環境からコピーする必要がある。

## Issue Net 変化（Session 32 途中）

- Close: 0
- 起票: 0
- Net: 0（次回完走時に再計上）
