# Handoff: "使える Windows デスクトップアプリ" 完成化計画（Session 8 終了時点）

**更新日**: 2026-04-21
**ブランチ**: main（clean、全 PR マージ済）
**main**: a85eef5 (PR #66 squash merged: タスク 12B)

## セッション 8 の成果

### マージ済み
- **PR #61**: タスク 13A（ランチャー GUI 骨格、3 ボタン）
- **PR #65**: タスク 13B（Launcher ↔ Phase A 非同期統合、Issue #62 対応 → close）
- **PR #66**: タスク 12B（設定 GUI、SettingsDialog + Toplevel モーダル化）
  - 343 passed / 44 skipped
  - /simplify 3 並列 + Evaluator APPROVE
  - 6 Agent + Codex 二段レビュー → CRITICAL 3 件 + IMPORTANT 2 件反映済
  - CI: test-unit 3.11/3.12 + test-integration 全 pass

## 次セッションの着手手順

```bash
cd /Users/yyyhhh/Projects/wiseman_auto_sys
# 1. catchup で状況把握
# 2. 13C 着手（ランチャー ↔ 確認 UI / Phase B 統合）
git checkout main
git pull --ff-only
git checkout -b feature/task-13c-phase-b-integration
```

## 次タスク優先順位

### 優先 1: タスク 13C（ランチャー ↔ 確認 UI / Phase B 統合）

**スコープ**:
- `on_open_review` 実装: NEEDS_REVIEW セッション一覧 → ConfirmDialog → `run_phase_b`
- 13B と同様 worker thread 化（Phase B も時間がかかるため）
- SettingsDialog と同じ Toplevel モーダル化パターン（`_make_settings_callback` 参照）
- Phase B 完了時の出力 PDF 通知

**Acceptance Criteria**:
- AC-L-3: 確認待ちボタン → セッション一覧 → 選択 → ConfirmDialog 起動
- AC-L-3-Async: Phase B 実行中も mainloop 応答（13B パターン流用）
- AC-L-3-Done: 完了時に出力 PDF パス通知 + ログには型名のみ（PII 防御）

### 優先 2: タスク 14A（PyInstaller spec + icon 埋め込み）

**Issue #59 対応**: `--icon assets/icon.ico` 指定、生成 exe の resource 検証

### 優先 3: タスク 10-2（Windows 実機 E2E、本田さん実施）

`docs/handoff/windows-e2e-task10.md` に従って TeamViewer で実施。

### 優先 4: タスク 12C / 14C / 14D / 15 / 11

## 積み残し Issue / 技術負債

### Session 8 で新規 Issue 化
- **#67**: `_on_callback_exception` を `install_tk_exception_guard` に共通化（P2、13C 着手前に対応で SessionPicker でも再利用可能）
- **#68**: `validate_form` 戻り値を error code enum 化 + `ValidatedForm` newtype（P2、i18n + illegal-state-unrepresentable）

### Session 8 で識別（Issue 未化、記録のみ）
- **type-design**: `SettingsDialogResult.config` が AppConfig（frozen でない）で mutation 可能。deepcopy on construction 検討
- **test**: 重複 `concat_order` "A,A,B" の仕様判断（許可 or 検出）
- **test**: `reload_config` + `validate_config_ready` の結合遷移テスト（AC-L-4 の実運用フロー検証）
- **security**: API Key 平文が StringVar / Tcl interpreter / clipboard に残る（`show="*"` だけでは不十分な脅威モデル）
- **UX**: TOML 構文エラー時に設定ダイアログで修復する UI なし（現状は Launcher の messagebox で型名通知のみ）
- **robustness**: `ttk.Entry` の改行・制御文字混入を拒否していない（Windows 実機で検証必要）

### 継続
- **#58**: `/healthz` Cloud Run GFE intercept（P2、実害なし）
- **#59**: PyInstaller icon 埋め込み（P2、14A スコープ）
- **#62**: ~~Phase A worker thread 化~~ → PR #65 で対応済
- **#63**: Linux CI Tk wiring skip（P2、15 / 別 PR）
- **#64**: `--config` 存在しないパス警告（P2）
- **#51**: Windows msvcrt / 跨プロセスロック / 0 ページ PDF (P1、単一 PC では発生せず)
- **#38**: atomic_io ユーティリティ抽出（P2、config.py / session.py / merger.py / save_config で重複）
- **#27 #29 #49 #50 #40 #39 #44 #45 #17 #16 #14 #11 #6**: 各種改善

## impl-plan 進捗（Session 8 終了時点）

| タスク | 状態 | PR |
|--------|------|-----|
| 10-1 Cloud Run デプロイ + 疎通確認 | ✅ merged | #60 |
| 10-2 Windows 実機 E2E | ⏳ 本田さん実施待ち | - |
| 12A TOML 書き戻し機能 | ✅ merged | #60 |
| 12B 設定 GUI | ✅ merged | #66 |
| 12C 初回起動ウィザード | ⏳ 優先度低（12B で必須設定編集カバー） | - |
| 13A ランチャー GUI 骨格 | ✅ merged | #61 |
| 13B ランチャー ↔ Phase A 統合 | ✅ merged | #65 |
| **13C ランチャー ↔ 確認 UI 統合** | ⏳ **次セッション最優先** | - |
| 14A PyInstaller spec | ⏳ GUI 完成後 | - |
| 14B アイコン生成 | ✅ merged | #60 |
| 14C ショートカット配布手順 | ⏳ 14A 後 | - |
| 14D ADR-011 執筆 | ⏳ 14A 完了時 | - |
| 15 GitHub Actions + WIF | ⏳ GUI 安定後 | - |
| 11 README + sample TOML | ⏳ 最後 | - |

## 本セッションで確定した設計判断

### 設定 GUI（12B）の Toplevel モーダル化
- `SettingsDialog(parent=...)` 指定時は `tk.Toplevel(parent) + transient + grab_set + wait_window` でモーダル動作
- 設定編集中は Launcher の他ボタンが押せない（race 構造的排除、医療 PII 誤配置防止）
- 親なしで起動（テスト / standalone）時は従来の `tk.Tk() + mainloop()` を使う 2 モード設計
- Launcher に `get_root() -> tk.Tk` を追加、`_LauncherLike` Protocol に反映

### Launcher ↔ SettingsDialog 双方向バインド
- `_make_settings_callback(config_path, get_launcher)` が `launcher_ref: list[Launcher | None] = [None]` を参照
- `Launcher(on_open_settings=callback)` → `launcher_ref[0] = launcher` の順で初期化
- `_get_launcher()` 関数で None チェックを `raise RuntimeError`（`python -O` で assert strip リスク回避）
- 設定保存成功時は `launcher.reload_config(new_config)` を呼び `validate_config_ready` 判定を新値で行う（再起動不要）

### PII 防御（12B で強化）
- `validate_form`: エラーメッセージに入力値 raw を埋め込まない（URL 欄に API Key 誤入力時の露出防止）
- `attempt_save` の except は `(OSError, ValueError, TypeError)` のみ捕捉、想定外は `_on_callback_exception` で fail-fast
- `_on_callback_exception` の二次 showerror 失敗を warning ログで握り潰し（ConfirmDialog と同等）
- `open_settings` で `load_config` 失敗を型名のみ通知、Launcher は継続

### Quality Gate 実効性（Session 2-8 累積）
- **/simplify**: 各 PR で IMPORTANT 3-6 件修正
- **Evaluator 分離プロトコル**: 5 ファイル以上で起動、構造的契約を明確化
- **/review-pr 6 Agent + Codex**: 12B では CRITICAL 3 件検出（Toplevel モーダル化 / assert strip / except 過剰広域）、PII 漏洩経路 8 セッション連続検出

## セッション再開手順（コピペ可）

```bash
cd /Users/yyyhhh/Projects/wiseman_auto_sys
# main 同期確認（全 PR マージ済）
git checkout main
git pull --ff-only

# 13C 着手
git checkout -b feature/task-13c-phase-b-integration

# TDD: まず Red
# tests/unit/ui/test_launcher_phase_b_integration.py 新規
```

## 13C 設計メモ（詳細）

### スコープ

ランチャーの「確認待ちセッション」ボタンから Phase B（最終 PDF 結合）を実行できるようにする。

1. `on_open_review` に実装注入:
   - `list_sessions(sessions_dir)` で NEEDS_REVIEW / READY_TO_MERGE セッション列挙
   - セッション選択 UI（リスト表示 + 選択）→ 既存 `scripts/merge_user_pdfs.py::_cmd_review` のロジックを参考
   - NEEDS_REVIEW なら ConfirmDialog 起動（既存）→ 解決後 run_phase_b
   - READY_TO_MERGE なら直接 run_phase_b
2. Phase B は worker thread 化（13B の `_schedule_phase_a_done` パターン流用）
3. 完了時は出力 PDF パスを showinfo、例外時は型名のみログ

### ファイル構成案

```
src/wiseman_hub/ui/session_picker.py  # 新規、セッション一覧 + 選択 Toplevel
src/wiseman_hub/ui/launcher.py        # _handle_open_review を async 化
src/wiseman_hub/__main__.py           # _make_review_callback 追加
```

### 既存資産

- `scripts/merge_user_pdfs.py::_cmd_review`（list → ConfirmDialog → transition）
- `scripts/merge_user_pdfs.py::_cmd_merge`（READY_TO_MERGE → run_phase_b）
- `src/wiseman_hub/ui/confirm_dialog.py::ConfirmDialog`（Toplevel 化が必要）
- `src/wiseman_hub/ui/launcher.py::_schedule_phase_a_done`（Phase B にも同パターン）

### 注意点

- ConfirmDialog も Toplevel モーダル化すべき（Launcher を parent に渡す）
- session lock は既存 `with_session_lock(sessions_dir, session_id)` で確保（二重起動防止）
- Phase B 実行中の Launcher ボタン disable（13B の `_set_busy` と同じ）
- **最優先**: ConfirmDialog を Toplevel 化しないと、「確認 UI 中に Launcher ボタンが押せる」という同じ race が残る（12B で Codex に指摘された通り）

## 参照ファイル（次セッション用）

### 実装対象
- `src/wiseman_hub/ui/session_picker.py`（新規）
- `src/wiseman_hub/ui/launcher.py`: `_handle_open_review` 追加
- `src/wiseman_hub/__main__.py`: `_make_review_callback` 追加
- `src/wiseman_hub/ui/confirm_dialog.py`: `parent` 引数追加、Toplevel モード対応

### 既存資産
- `scripts/merge_user_pdfs.py`: CLI ロジック参考
- `src/wiseman_hub/pdf/session.py`: `list_sessions` / `load_session` / `with_session_lock`
- `src/wiseman_hub/pdf/pipeline.py::run_phase_b`
- `src/wiseman_hub/ui/common.py`: `assert_main_thread`
