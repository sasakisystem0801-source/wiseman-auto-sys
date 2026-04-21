# Handoff: "使える Windows デスクトップアプリ" 完成化計画（Session 10 終了時点）

**更新日**: 2026-04-21
**ブランチ**: main（clean、全 PR マージ済）
**main**: 57f1455 (PR #79 squash merged: タスク 14A)

## セッション 10 の成果

### マージ済み
- **PR #79**: タスク 14A（PyInstaller spec + icon 埋め込み、Issue #59）
  - 7 files, +466/-13（wiseman_hub.spec + ADR-011 + ビルド手順書 + config 解決修正）
  - Claude code-reviewer + comment-analyzer レビュー + Codex セカンドオピニオン
  - **Codex HIGH 2 件検出**: (a) `__main__.py` の config CWD 相対バグ（exe ショートカット起動で空設定） (b) SmartScreen リスク過小評価
  - Claude comment-analyzer 3 件: ADR-004 誤認、ROOT 脆弱性、handoff 不整合 → すべて修正反映
  - macOS smoke build 成功（`dist/wiseman_hub` 66 MB、hidden imports 妥当性検証済）
  - 390 passed / 62 skipped（+4 TestDefaultConfigPath）

### 新規作成 Issue（Session 10）
- **#80**（P2）: Windows 実機 smoke build で Phase B / OCR import まで実行（タスク 15 CI 統合時）

## 次セッションの着手手順

```bash
cd /Users/yyyhhh/Projects/wiseman_auto_sys
git checkout main
git pull --ff-only
```

## 次タスク優先順位

### 優先 1: タスク 10-2（Windows 実機 E2E、本田さん実施）

**前提**: 14A 完了により `wiseman_hub.spec` + ビルド手順書が揃ったため、Windows 実機でパッケージング〜E2E を同時検証できる状態。

**スコープ**（`docs/handoff/14a-build.md` + `docs/handoff/windows-e2e-task10.md`）:
1. TeamViewer 経由で Windows 11 PC にアクセス
2. `uv sync --extra dev` → `uv run pyinstaller --clean wiseman_hub.spec` で exe 生成
3. `dist/wiseman_hub.exe` + `config/default.toml` をダブルクリック起動
4. Launcher GUI で以下を実測:
   - 3 ボタン表示、アイコン表示（taskbar / alt-tab）
   - PDF マージ処理ボタン → Phase A → セッション生成
   - 確認待ちセッション → SessionPicker → ConfirmDialog → Phase B → 出力 PDF
   - 設定 → SettingsDialog → TOML 書き戻し → 即反映
5. SmartScreen 初回警告の挙動記録（Enterprise policy 有無含む）

**Acceptance Criteria**:
- AC2: 実 Cloud Run 経由 OCR 成功
- AC-UI-6〜10: Tkinter 実描画確認
- AC-L-2/3/4: Launcher 統合
- AC-DIST-1〜4: exe 起動 / アイコン / config 配置 / SmartScreen 挙動

### 優先 2: タスク 14C（ショートカット配布手順）

**スコープ**:
- PowerShell スクリプト `scripts/create_shortcut.ps1`（Desktop にショートカット配置）
- 配布 ZIP の構成手順（exe + config/ + assets/ + README + ショートカット作成 ps1）
- 施設 IT 担当向け展開手順書

**前提**: 14A 完了、10-2 で exe 起動確認後が理想（挙動ベースで手順確定できる）。14C だけ先行も可。

### 優先 3: Issue #76（P2、PdfMergeError 全般 PII 除外）

他 8 箇所の `PdfMergeError` message から path/user_name 除外（Issue #75 follow-up）。30 分の小作業、PR #77 と同パターン。

### 優先 4: タスク 14D / 15 / 11 / 12C

- 14D: ADR-011 Accepted 昇格（10-2 実機検証結果反映、コードサイニング判断）
- 15: GitHub Actions Windows runner + WIF デプロイ CI（Issue #80 の smoke test 統合含む）
- 11: README + sample TOML（最後）
- 12C: 初回起動ウィザード（優先度低、12B でカバー済）

## 積み残し Issue / 技術負債

### P1
- **#51**: Windows msvcrt / 跨プロセスロック / 0 ページ PDF（単一 PC では発生せず）

### P2（Session 8-10 で新規、継続）
- **#68**（Session 8）: `validate_form` 戻り値を error code enum 化 + `ValidatedForm` newtype
- **#71**（Session 9）: guard の exc_type=None / BaseException 契約テスト
- **#72**（Session 9）: `review_flow.resolve_review_session` 共通化
- **#73**（Session 9）: `ReviewCallbackResult` dataclass
- **#76**（Session 9）: 他 PdfMergeError 生成箇所の PII 除外
- **#80**（Session 10）: Windows 実機 smoke で Phase B / OCR import 検証

### P2（継続）
- **#58**: `/healthz` Cloud Run GFE intercept（実害なし）
- **#63**: Linux CI Tk wiring skip（別 PR）
- **#64**: `--config` 存在しないパス警告
- **#38**: `atomic_io` ユーティリティ抽出
- **#27 #29 #49 #50 #40 #39 #44 #45 #17 #16 #14 #11 #6**: 各種改善

## impl-plan 進捗（Session 10 終了時点）

| タスク | 状態 | PR |
|--------|------|-----|
| 10-1 Cloud Run デプロイ + 疎通確認 | ✅ merged | #60 |
| **10-2 Windows 実機 E2E** | ⏳ **本田さん実施待ち（14A 完了、exe ビルド可能）** | - |
| 12A TOML 書き戻し機能 | ✅ merged | #60 |
| 12B 設定 GUI | ✅ merged | #66 |
| 12C 初回起動ウィザード | ⏳ 優先度低 | - |
| 13A ランチャー GUI 骨格 | ✅ merged | #61 |
| 13B ランチャー ↔ Phase A 統合 | ✅ merged | #65 |
| 13C ランチャー ↔ 確認 UI / Phase B 統合 | ✅ merged | #74 |
| 14A PyInstaller spec | ✅ merged | #79 |
| 14B アイコン生成 | ✅ merged | #60 |
| **14C ショートカット配布手順** | ⏳ **14A 後の次候補** | - |
| 14D ADR-011 執筆 | ⏳ 10-2 実機検証後に Accepted 昇格 | - |
| 15 GitHub Actions + WIF | ⏳ GUI 安定後 | - |
| 11 README + sample TOML | ⏳ 最後 | - |

## Session 10 で確定した設計判断

### タスク 14A

**配布形式の確定（ADR-011）**
- `--onefile --windowed`、UPX 無効、icon 埋め込み、未署名 exe で MVP 配布
- `config/default.toml` は exe 外（隣配置）で運用し、設定 GUI から書き戻し可能
- PyInstaller version を `>=6.11.0,<7.0` に固定（v7 破壊的変更回避）

**config パス解決の frozen 対応（Codex HIGH 指摘反映）**
- `__main__._default_config_path()` で以下の優先順位:
  1. `WISEMAN_HUB_CONFIG` 環境変数
  2. frozen 実行時 → `sys.executable` 同階層
  3. 通常実行 → `config/default.toml`（CWD = プロジェクトルート前提）
- exe ショートカット起動で CWD が別ディレクトリでも設定を見失わない

**SmartScreen 運用補強（Codex HIGH 指摘反映）**
- 「警告 1 回のみ」は理想論。現実は新ビルドで reputation リセット、Enterprise policy で導線消失の可能性
- 補強: 事前 hash 共有、Microsoft Security Intelligence 提出、施設 IT allowlist、USB 直接配布優先
- 2 施設目以降でコードサイニング投資の合理性を 14D で再評価

### Quality Gate の実効性（Session 2-10 累積）
- **/simplify** 3 並列: 各 PR で IMPORTANT 3-6 件修正
- **Evaluator 分離**: 5+ files 発動、13C で REQUEST_CHANGES 1 件検出
- **6 Agent + Codex 二段レビュー**:
  - Session 9: 13C で Codex HIGH 2 件（TOCTOU + logger.exception PII）検出
  - Session 10: 14A で Codex HIGH 2 件（config CWD バグ + SmartScreen 過小評価）検出
  - **6 セッション連続で Codex が Claude 見落としの HIGH を検出 → 継続運用が合理的**

## セッション再開手順（コピペ可）

```bash
cd /Users/yyyhhh/Projects/wiseman_auto_sys
git checkout main
git pull --ff-only

# 10-2 Windows 実機 E2E（本田さん実施、TeamViewer）
# → docs/handoff/14a-build.md + windows-e2e-task10.md に従う

# または 14C ショートカット配布手順を先行
git checkout -b feature/task-14c-shortcut-distribution
```

## 14C 設計メモ（詳細）

### スコープ

配布 ZIP を施設 PC に展開した後、Desktop にショートカットを作成する仕組み。

1. `scripts/create_shortcut.ps1` 新規:
   - 実行場所（CWD）から `wiseman_hub.exe` を解決
   - `icon.ico` を指定してショートカット作成
   - `[Desktop]\Wiseman PDF ツール.lnk` に配置
   - 管理者権限不要（ユーザーごとの Desktop に作成）
2. 配布 ZIP 構成:
   ```
   wiseman-hub-v0.1.0-win-x64.zip
   ├── wiseman_hub.exe
   ├── config/
   │   └── default.toml.sample
   ├── assets/
   │   └── icon.ico
   ├── scripts/
   │   └── create_shortcut.ps1
   └── README.txt
   ```
3. 施設 IT 担当向け手順書（`docs/handoff/14c-deploy.md`）:
   - 展開場所の推奨（`C:\wiseman-hub\` or `C:\Program Files\wiseman-hub\`）
   - `default.toml.sample` → `default.toml` リネーム + 施設別編集
   - `create_shortcut.ps1` 実行（PowerShell 実行ポリシーの一時設定方法含む）
   - SmartScreen 警告への対処

### 既存資産

- `assets/icon.ico`: 14B 生成済
- `wiseman_hub.exe`: 14A でビルド可能
- ADR-011: 配布形式確定

### 注意点

- PowerShell 実行ポリシー（`Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process`）の使い方を IT 担当に周知
- ショートカット作成失敗時の fallback（手動作成手順）
- アンインストール手順（ZIP 削除 + ショートカット削除のみ、レジストリ変更なし）

## 参照ファイル（次セッション用）

### 10-2 実機検証対象
- `wiseman_hub.spec`
- `docs/handoff/14a-build.md`: macOS smoke / Windows 実機ビルド手順
- `docs/handoff/windows-e2e-task10.md`: E2E 検証手順
- `docs/adr/011-distribution-format.md`: 配布形式 ADR（Proposed、10-2 結果で Accepted 昇格）

### 14C 実装対象
- `scripts/create_shortcut.ps1`（新規）
- `docs/handoff/14c-deploy.md`（新規、施設 IT 担当向け）

### 既存資産
- `assets/icon.ico`
- `src/wiseman_hub/__main__.py::_default_config_path`（14A で追加、frozen 対応済）
