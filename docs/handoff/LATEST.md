# Handoff: "使える Windows デスクトップアプリ" 完成化計画（Session 12 終了時点）

**更新日**: 2026-04-22
**ブランチ**: main（clean、全 PR マージ済）
**main**: bdca87c (PR #86 squash merged: Issue #51 #1/#2 テスト)

## セッション 12 の成果

### マージ済み（本セッション、3 PR 連続）
- **PR #84**: Issue #76 - merger 全 PdfMergeError message PII 除外
  - 2 files, +221/-18（`src/wiseman_hub/pdf/merger.py` + `tests/unit/pdf/test_merger.py`）
  - 8 箇所の `PdfMergeError` 生成箇所を型名ベースに統一、`source_label` 呼出側で kind (A/B/C/D) のみに制限
  - 4 エージェント並列レビュー（code-reviewer / pr-test-analyzer / silent-failure-hunter / comment-analyzer）: Critical 0 / Important 8 件は defense-in-depth 強化系として PR #84 コメントに TODO 記録
  - 新規 PII 非漏洩回帰テスト +10 件（TestMergerPiiDefense）
  - CI 全 SUCCESS

- **PR #85**: タスク 11 - README 運用者セクション + default.toml.sample + §7.2 ログ取得手順
  - 3 files, +218/-9（`README.md` + `config/default.toml.sample` 新規 + `docs/handoff/14c-deploy.md`）
  - 2 エージェント並列レビュー（code-reviewer / comment-analyzer）: Critical 2 / Important 3 / Suggestion 3 → **8/8 修正済**
  - 主な修正: README「リネーム」→「コピー保存」整合、§2.3 フィールド名実装整合（source_dir 削除）、README リンクに GitHub anchor slug 付与、[gcp] project_id 直書き警告追加
  - CI 全 SUCCESS

- **PR #86**: Issue #51 #1/#2 - Windows msvcrt mock + 跨プロセスロックテスト
  - 1 file, +282（`tests/unit/pdf/test_session.py`、テストのみ）
  - TestLockWindowsMsvcrt (5 件): `sys.modules` 経由の fake msvcrt 注入で Windows 分岐を macOS/Linux でも検証
  - TestCrossProcessLock (3 件): multiprocessing.spawn で親子プロセス間の lock 競合検証
  - 2 エージェント並列レビュー（pr-test-analyzer / code-reviewer）: Critical 0 / Important 0 (blocking) → Merge as-is 推奨
  - Issue #51 は残項目 #3-#6 のため **open 維持**（feedback_issue_postpone_pattern.md 準拠）
  - CI 全 SUCCESS

### 総変更量（Session 12）
- 6 files changed, +721 lines（テスト +300 / docs +420 / code +1）
- 全 CI SUCCESS、全レビュー blocking issue 0
- 前セッション 400 passed → **現在 408 passed**（+8 テスト）

## 前セッション（11）の成果

### マージ済み
- **PR #82**: タスク 14C（ショートカット配布手順、ADR-011 具体化）
  - 3 files, +449/-11（`scripts/create_shortcut.ps1` + `docs/handoff/14c-deploy.md` + ADR-011 更新）
  - Claude 3 並列レビュー（code-reviewer / silent-failure-hunter / comment-analyzer）: HIGH 3 件検出 + MEDIUM 多数
  - Codex セカンドオピニオン: Claude 見落としの HIGH 2 件 + MEDIUM 3 件検出
  - **計 HIGH 5 件 + MEDIUM 8 件すべて修正反映**
  - CI 全 SUCCESS（test-unit 3.11/3.12 各 56s、test-integration 3m13s）

### PR #82 で修正した主な指摘

**Claude HIGH**:
1. COM リソースリーク: `Save()` 失敗で `ReleaseComObject` 未到達 → `try/finally`
2. OneDrive Desktop リダイレクト: `Save()` 時 `0x80070005` が汎用 COMException → 個別 catch + 明示メッセージ
3. WSH 無効 / ConstrainedLanguage: `New-Object -ComObject` 失敗 → 個別 `try/catch` + §4 手動 fallback 誘導

**Codex HIGH（Claude 見落とし）**:
1. `C:\wiseman-hub\` が「管理者権限不要」は誤り（標準ユーザーは C:\ 直下書込不可）→ `%USERPROFILE%\wiseman-hub\` を MVP 既定化
2. 未署名 exe で `FilePublisher` allowlist は不正確 → Hash / FilePath ルールのみに限定、FilePublisher は 14D コードサイニング採用後

**MEDIUM 計 8 件**: PS 5.1 BOM 付与、ADR-011 ↔ 14c-deploy 整合、v0.1.0 → vX.Y.Z placeholder、Resolve-Path 非存在時の明示 check、検証用ドラフト注記、`Bypass -Scope Process` 表現、out-of-band SHA256 共有、Win11 22H2+ SmartScreen 文言注記

## 次タスク優先順位

### 優先 1: タスク 10-2（Windows 実機 E2E、本田さん実施）

**前提**: 14A / 14C 完了により `wiseman_hub.spec` + ビルド手順書 + ショートカット配布手順書が揃ったため、Windows 実機でパッケージング〜E2E〜配布リハーサルまで同時検証できる状態。

**スコープ**（`docs/handoff/14a-build.md` + `docs/handoff/14c-deploy.md` + `docs/handoff/windows-e2e-task10.md`）:
1. TeamViewer 経由で Windows 11 PC にアクセス
2. `uv sync --extra dev` → `uv run pyinstaller --clean wiseman_hub.spec` で exe 生成
3. 配布 ZIP をエミュレート: `dist/wiseman_hub.exe` + `config/default.toml.sample` + `assets/icon.ico` + `scripts/create_shortcut.ps1` を `%USERPROFILE%\wiseman-hub\` にコピー
4. `Set-ExecutionPolicy -Scope Process Bypass` + `.\scripts\create_shortcut.ps1` 実行
5. Desktop の「Wiseman PDF ツール」ショートカットからダブルクリック起動
6. Launcher GUI で以下を実測:
   - 3 ボタン表示、アイコン表示（taskbar / alt-tab / .lnk）
   - PDF マージ処理ボタン → Phase A → セッション生成
   - 確認待ちセッション → SessionPicker → ConfirmDialog → Phase B → 出力 PDF
   - 設定 → SettingsDialog → TOML 書き戻し → 即反映
7. SmartScreen 初回警告の挙動記録（ボタン文言 / Enterprise policy 有無）
8. `create_shortcut.ps1` の exit code 1/2/3 の挙動確認（exe 不在・WSH 無効・書込失敗）

**Acceptance Criteria**:
- AC2: 実 Cloud Run 経由 OCR 成功
- AC-UI-6〜10: Tkinter 実描画確認
- AC-L-2/3/4: Launcher 統合
- AC-DIST-1〜4: exe 起動 / アイコン / config 配置 / SmartScreen 挙動
- AC-14C-1/2/4: PS 実行成功 / Desktop ダブルクリック起動 / icon 埋め込み

### 優先 2: タスク 14D（ADR-011 Accepted 昇格）

**前提**: 10-2 実機検証結果が必須。

**スコープ**:
- ADR-011 Status を Proposed → Accepted に昇格
- 10-2 の SmartScreen 実画面記録を反映（`14c-deploy.md` §5.1 のボタン文言更新）
- コードサイニング要否の運用判断を追記:
  - 1 施設目: 未署名で運用、SmartScreen 警告を IT 担当で対応
  - 2 施設目以降: 証明書投資の合理性を 10-2 の実際の警告頻度 / Enterprise 環境遭遇率で判断
- `14c-deploy.md` 冒頭の「検証用ドラフト」注記を「正式版」に差し替え

### 優先 3: タスク 11（README + sample TOML）

**前提**: 14D 完了後が理想だが、並行可能。

**スコープ**:
- `README.md`: インストール / 起動 / 設定 / よくあるエラー（介護施設運用者向け、非技術者）
- `config/default.toml.sample`: 施設別に編集するテンプレート
- `14c-deploy.md` §7.2 の TBD（exe 起動失敗時のログ出力）を確定

### 優先 4: Issue #76（P2、PdfMergeError 全般 PII 除外）

他 8 箇所の `PdfMergeError` message から path/user_name 除外（Issue #75 follow-up）。30 分の小作業、PR #77 と同パターン。

### 優先 5: タスク 15 / 12C

- 15: GitHub Actions Windows runner + WIF デプロイ CI（Issue #80 の smoke test 統合含む）
- 12C: 初回起動ウィザード（優先度低、12B でカバー済）

## 積み残し Issue / 技術負債

### P1
- **#51**: Windows msvcrt / 跨プロセスロック / 0 ページ PDF（**Session 12 で #1/#2 部分解消、PR #86**、残項目 #3-#6 は open 維持）

### P2（Session 8-12 で新規、継続）
- **#68**（Session 8）: `validate_form` 戻り値を error code enum 化 + `ValidatedForm` newtype
- **#71**（Session 9）: guard の exc_type=None / BaseException 契約テスト
- **#72**（Session 9）: `review_flow.resolve_review_session` 共通化
- **#73**（Session 9）: `ReviewCallbackResult` dataclass
- ~~**#76**（Session 9）: 他 PdfMergeError 生成箇所の PII 除外~~ → **Session 12 で PR #84 解消、closed**
- **#80**（Session 10）: Windows 実機 smoke で Phase B / OCR import 検証

### P2（継続）
- **#58**: `/healthz` Cloud Run GFE intercept（実害なし）
- **#63**: Linux CI Tk wiring skip（別 PR）
- **#64**: `--config` 存在しないパス警告
- **#38**: `atomic_io` ユーティリティ抽出
- **#27 #29 #49 #50 #40 #39 #44 #45 #17 #16 #14 #11 #6**: 各種改善

## impl-plan 進捗（Session 12 終了時点）

| タスク | 状態 | PR |
|--------|------|-----|
| 10-1 Cloud Run デプロイ + 疎通確認 | ✅ merged | #60 |
| **10-2 Windows 実機 E2E** | ⏳ **本田さん実施待ち（14A / 14C / 11 完了、exe + 配布リハ + README 揃い済）** | - |
| **11 README + sample TOML** | ✅ merged | **#85** |
| 12A TOML 書き戻し機能 | ✅ merged | #60 |
| 12B 設定 GUI | ✅ merged | #66 |
| 12C 初回起動ウィザード | ⏳ 優先度低 | - |
| 13A ランチャー GUI 骨格 | ✅ merged | #61 |
| 13B ランチャー ↔ Phase A 統合 | ✅ merged | #65 |
| 13C ランチャー ↔ 確認 UI / Phase B 統合 | ✅ merged | #74 |
| 14A PyInstaller spec | ✅ merged | #79 |
| 14B アイコン生成 | ✅ merged | #60 |
| **14C ショートカット配布手順** | ✅ merged | #82 |
| **14D ADR-011 Accepted 昇格** | ⏳ **10-2 結果反映後** | - |
| 15 GitHub Actions + WIF | ⏳ GUI 安定後 | - |

## Session 11 で確定した設計判断

### タスク 14C

**ADR-011 への反映（変更履歴に記載）**
- 配布レイアウト: `config/default.toml` → `config/default.toml.sample` 命名変更（上書き事故防止、施設側でコピーして `default.toml` 作成）
- 配布物: `scripts/create_shortcut.ps1` を追加
- バージョン表記: `v0.1.0` → `vX.Y.Z` placeholder に変更

**`14c-deploy.md` への反映（運用手順書、ADR とは別ドキュメント）**

*MVP 配置先の既定化（Codex HIGH 指摘反映）*:
- 標準ユーザー権限で書込可能な `%USERPROFILE%\wiseman-hub\` を既定（= `C:\Users\<user>\wiseman-hub\`）
- `C:\wiseman-hub\` は「管理者権限必要」と明記（標準ユーザーは C:\ 直下に新規作成不可）
- `%LOCALAPPDATA%\wiseman-hub\` をエクスプローラ非表示運用の代替に

*allowlist 登録ルールの明確化（Codex HIGH 指摘反映）*:
- 未署名 exe の間は Hash / FilePath ルールのみ実効性あり
- FilePublisher / Publisher ルールは 14D コードサイニング採用後の選択肢として分離
- SHA256 共有は **out-of-band**（電話 / 既存チャット / 別メール）で ZIP とは別経路必須

**`scripts/create_shortcut.ps1` の構造化（Claude HIGH 指摘反映）**
- PS スクリプト exit code: 1 = 設定不備、2 = WSH 無効 / ConstrainedLanguage、3 = 書込失敗
- `try/finally` で COM リソース解放を保証（Save 失敗時のリーク防止）
- OneDrive / ASR / ACL の個別診断メッセージを追加

### Quality Gate の実効性（Session 2-11 累積）
- **/simplify** 3 並列: 各 PR で IMPORTANT 3-6 件修正
- **Evaluator 分離**: 5+ files 発動、13C で REQUEST_CHANGES 1 件検出
- **6 Agent + Codex 二段レビュー**:
  - Session 9: 13C で Codex HIGH 2 件（TOCTOU + logger.exception PII）検出
  - Session 10: 14A で Codex HIGH 2 件（config CWD バグ + SmartScreen 過小評価）検出
  - Session 11: 14C で Codex HIGH 2 件（USERPROFILE 既定 + FilePublisher 不正確）検出
  - **直近 3 セッション（9-11）連続で Codex が Claude 見落としの HIGH を検出 → 継続運用が合理的**

## セッション再開手順（コピペ可）

```bash
cd /Users/yyyhhh/Projects/wiseman_auto_sys
git checkout main
git pull --ff-only

# 10-2 Windows 実機 E2E（本田さん実施、TeamViewer）
# → docs/handoff/14a-build.md + 14c-deploy.md + windows-e2e-task10.md に従う
# → README.md 運用者セクション + config/default.toml.sample で配布物最小セット揃い済

# または 14D ADR-011 Accepted 昇格（10-2 結果反映）
# または Issue #51 残項目（#3-#6、各 1-2 時間）:
#   #3 非 KeyboardInterrupt Exception 経路（OcrServerError / TimeoutError）
#   #4 0/1 ページ境界（splitter boundary）
#   #5 disk-full save_session（既存 test_save_failure_cleans_tmp_file 同パターン）
#   #6 gc_old_sessions 並行 resume（設計判断が必要）
# または その他 P2（#63/#64/#68/#71/#72/#73/#80）
```

## Session 12 での設計判断

### Issue #76 の PII 除外拡張
- PR #77 で `_save_atomically` のみ型名ベースに統一済だったが、残り 8 箇所の `PdfMergeError` 生成箇所（`_validate_user_name` / `_open_pdf_file_or_raise` / `_append_pdf_bytes` / `_append_pdf_file`）にも適用
- `source_label` を呼出側で kind (A/B/C/D) のみに制限し、関数シグネチャ非破壊で user_name 埋込を原理的に排除
- `from e` は全箇所で維持 → `__cause__` 経由で元例外情報にアクセス可能

### タスク 11（docs 整備）
- `config/default.toml.sample` を新規作成、`config/default.toml`（dev 用）は残存
- README は先頭に運用者セクションを挿入、既存 dev 内容は維持（分離ファイル回避で GitHub プレビュー改善）
- `14c-deploy.md §7.2` に `startup.log` 取得コマンド（PowerShell `*>` / cmd `2>&1`）を具体化

### Issue #51 の scope 絞込
- P1 #1 (Windows msvcrt) + #2 (跨プロセスロック) のみに絞り、#3-#6 は follow-up
- Windows msvcrt は `sys.modules` 経由の fake 注入で macOS/Linux でも検証
- 跨プロセスロックは `multiprocessing.spawn` で fork の fd 継承を回避、Windows exe 二重起動と等価な挙動を再現

### Issue triage pattern の再適用（memory 教訓）
- review agent の rating 5-7 指摘は Issue 化せず PR コメント TODO で可視化（3 PR 連続で適用）
- Issue #51 は残項目 #3-#6 のため **open 維持**、再開条件を PR #86 本文で機械的に判定可能な形で記述

## 14D 着手メモ（10-2 結果反映）

10-2 完了後の 14D で更新すべき箇所:

### ADR-011
- Status: `Proposed (2026-04-21)` → `Accepted (10-2 完了日)`
- 実機検証結果の「14A 完了時点の実装」節に追記（SmartScreen 実画面 / 配布 PS 動作結果 / 起動時間実測）
- コードサイニング投資の判断記録（SmartScreen 警告頻度 / Enterprise 遭遇率で再評価）

### 14c-deploy.md
- 冒頭「検証用ドラフト」注記を削除
- §5.1 SmartScreen ボタン文言を実画面記録に差し替え
- §7.1 exit code 表を実機動作の追加ケースで補強
- §8 実測報告項目に 10-2 結果を反映

### 本 handoff
- Session 12 として 14D 成果 + 10-2 結果を別途まとめ直し

## 参照ファイル（次セッション用）

### 10-2 実機検証対象
- `wiseman_hub.spec`
- `docs/handoff/14a-build.md`: macOS smoke / Windows 実機ビルド手順
- `docs/handoff/14c-deploy.md`: 施設 IT 担当者向け配布・展開手順書
- `docs/handoff/windows-e2e-task10.md`: E2E 検証手順
- `docs/adr/011-distribution-format.md`: 配布形式 ADR（Proposed、10-2 結果で Accepted 昇格）

### 14D 更新対象
- `docs/adr/011-distribution-format.md`
- `docs/handoff/14c-deploy.md`

### 既存資産
- `assets/icon.ico`
- `scripts/create_shortcut.ps1`（14C）
- `src/wiseman_hub/__main__.py::_default_config_path`（14A、frozen 対応）
