# Handoff: "使える Windows デスクトップアプリ" 完成化計画（Session 8 終了時点）

**更新日**: 2026-04-21
**ブランチ**: feature/task-13b-phase-a-integration (PR #65, CI 進行中)
**main**: f23aeb5 (PR #61 squash merged: タスク 13A)

## セッション 8 の成果

### マージ済み
- **PR #61**: タスク 13A（ランチャー GUI 骨格、3 ボタン、コールバック DI）

### マージ待ち（次セッション冒頭で確認→マージ）
- **PR #65**: タスク 13B（Launcher ↔ Phase A 非同期統合、Issue #62 対応）
  - ThreadPoolExecutor(max_workers=1) + busy flag + worker thread 化
  - `__main__.py` で Phase A コールバック注入（TOML を毎回再ロード）
  - 6 Agent + Codex + Evaluator 分離プロトコル通過、CRITICAL 3 件対応済
  - 325 passed / 33 skipped（Tk wiring は Windows CI で実測）

## 次セッションの着手手順

```bash
cd /Users/yyyhhh/Projects/wiseman_auto_sys
# 1. catchup で状況把握
# 2. PR #65 CI 確認
gh pr checks 65
gh pr view 65
# 3. CI 通過していればマージ
gh pr merge 65 --squash --delete-branch
git checkout main
git reset --hard origin/main
# 4. タスク 12B 着手（設定 GUI）
git checkout -b feature/task-12b-settings-gui
```

## 次タスク優先順位

### 優先 1: タスク 12B（設定 GUI）

**スコープ**:
- `src/wiseman_hub/ui/settings.py` 新規
- 必須設定 5 項目 + optional 設定を Tkinter フォームで編集
  - input_dir / output_dir（フォルダ選択ダイアログ）
  - source_a_filename / source_b_pattern / source_c_pattern
  - user_name_bbox / concat_order
  - ocr_backend.endpoint_url / api_key
  - wiseman.exe_path
- Save → `save_config(cfg, path)` 呼出（PR #60 で完成済）
- `ui/launcher.py` の `on_open_settings` に注入（13A の DI 設計活用）
- Phase A 実行中（`launcher._busy`）は Save ボタンを無効化、または warning 表示

**Acceptance Criteria**:
- AC-S-1: 設定 GUI 起動で全フィールドが TOML の現在値で初期化される
- AC-S-2: 各フィールドを編集 → Save → TOML に書き戻される（コメント維持）
- AC-S-3: 必須項目が空のまま Save → エラー表示、保存しない
- AC-S-4: フォルダ選択ダイアログで選択したパスが入力欄に反映される
- AC-S-5: API Key 欄はマスク表示（`show="*"`）

**TDD の流れ**:
1. `tests/unit/ui/test_settings.py` Red（pure logic: validate_form、Tk wiring: save callback）
2. `SettingsDialog` 実装（ConfirmDialog パターン踏襲）
3. `__main__.py` の `Launcher(on_open_settings=...)` に注入

### 優先 2: タスク 13C（ランチャー ↔ 確認 UI / Phase B 統合）

**スコープ**:
- `on_open_review` に NEEDS_REVIEW セッション一覧 → ConfirmDialog → run_phase_b
- Phase B 完了時の出力 PDF 通知
- 13B と同様に worker thread 化（Phase B も時間がかかる）

### 優先 3: タスク 14A（PyInstaller spec + icon 埋め込み）

**Issue #59 対応**: `--icon assets/icon.ico` 指定、生成 exe の resource 検証

### 優先 4: タスク 10-2（Windows 実機 E2E、本田さん実施）

`docs/handoff/windows-e2e-task10.md` に従って TeamViewer で実施。

### 優先 5: タスク 12C / 14C / 14D / 15 / 11

## 積み残し Issue

### Session 8 で対処／新規
- **#62** ランチャー Phase A worker thread 化 → PR #65 で対応
- (レビューで識別した将来対応候補)
  - Protocol 化: `OcrClient` を `contextlib.AbstractContextManager` 準拠にすれば
    `__main__.py` の `hasattr(ocr_client, "__exit__")` ダックタイピング除去可
  - テスト: `test_after_failure_after_root_destroy_logs_sanitized` / 
    `test_executor_shutdown_is_idempotent` 追加

### 継続
- **#58**: `/healthz` Cloud Run GFE intercept（P2、実害なし）
- **#59**: PyInstaller icon 埋め込み（P2、14A スコープ）
- **#63**: Linux CI Tk wiring skip（P2、15 / 別 PR）
- **#64**: `--config` 存在しないパス警告（P2）
- **#51** Windows msvcrt / 跨プロセスロック / 0 ページ PDF (P1、単一 PC では発生せず)
- **#38** atomic_io ユーティリティ抽出（P2、config.py / session.py / merger.py / 新 save_config で重複）
- **#27 #29 #49 #50 #40 #39 #44 #45 #17 #16 #14 #11 #6**: 各種改善

## impl-plan 進捗（Session 8 終了時点）

| タスク | 状態 | PR |
|--------|------|-----|
| 10-1 Cloud Run デプロイ + 疎通確認 | ✅ merged | #60 |
| 10-2 Windows 実機 E2E | ⏳ 本田さん実施待ち | - |
| 12A TOML 書き戻し機能 | ✅ merged | #60 |
| 12B 設定 GUI | ⏳ **次セッション最優先** | - |
| 12C 初回起動ウィザード | ⏳ 12B 後 | - |
| 13A ランチャー GUI 骨格 | ✅ merged | #61 |
| **13B ランチャー ↔ Phase A 統合** | 🔄 **CI 通過待ち、次セッションでマージ** | **#65** |
| 13C ランチャー ↔ 確認 UI 統合 | ⏳ | - |
| 14A PyInstaller spec | ⏳ GUI 完成後 | - |
| 14B アイコン生成 | ✅ merged | #60 |
| 14C ショートカット配布手順 | ⏳ 14A 後 | - |
| 14D ADR-011 執筆 | ⏳ 14A 完了時 | - |
| 15 GitHub Actions + WIF | ⏳ GUI 安定後 | - |
| 11 README + sample TOML | ⏳ 最後 | - |

## 本セッションで確定した設計判断

### Phase A 非同期実行パターン（13B）
- `ThreadPoolExecutor(max_workers=1, thread_name_prefix="phase-a")` を Launcher に保持
- `Launcher.__init__` で生成、`run()` の finally で shutdown（本番経路）
- `__del__` はベストエフォート cleanup（CPython は interpreter shutdown で呼ばない可能性あり）
- busy flag + `_current_future` で二重起動防止（AC-L-2-NoDouble）
- worker thread → main thread 遷移は `root.after(0, callback, arg)` 経由
  - `add_done_callback` は worker thread で同期実行（CPython 仕様）
  - after 失敗時（root destroy 後）は `RuntimeError` / `tk.TclError` 両方捕捉
  - after 失敗時も `future.exception()` を型名でログ（silent failure 防止）
- `_set_busy(False)` は `future.result()` より先に呼ぶ（例外時もボタン再有効化を保証、regression test `test_buttons_reenabled_even_if_callback_raises` で enforce）

### PII 防御（累積）
- logger には例外型名のみ（exception message は path/氏名を含みうる）
- `__main__.py` の最上位 `logger.exception` → `logger.error("...: %s", type(exc).__name__)` に修正
  （`logger.exception` は traceback に args 経由で PII を流す危険）
- tmp ファイル cleanup の warning は basename すら出さない
- `root.report_callback_exception` で PII 防御 sanitize（ConfirmDialog / Launcher 共通）
- API Key は Secret Manager で rotation、docs には平文記載しない

### テスト共有インフラ
- `tests/unit/ui/conftest.py`: `@pytest.mark.tk_required` マーカー + session-scoped fixture
- macOS uv python（Tcl/Tk 非同梱）で複数ファイル連続実行時の Tcl global state 蓄積による hang を回避
- `test_launcher.py` / `test_confirm_dialog.py` / `test_launcher_phase_a_async.py` で共通利用

### Quality Gate の実効性（Session 2-8 累積）
- **/simplify**: 各 PR で IMPORTANT 3-6 件修正（今回: `except BaseException` → `Exception` / executor leak / `wait_until_idle` pump）
- **Evaluator 分離プロトコル**: 5 ファイル以上で起動、REQUEST_CHANGES 対応で `tk.TclError` 網羅など構造的契約を明確化
- **/review-pr 6 Agent + Codex**: 今回は CRITICAL 3 件検出（`logger.exception` PII / `suppress(Exception)` / after 失敗時の future silent）
- **6 Agent レビュー → Codex セカンドオピニオン** の二段構造が PII 漏洩経路を 8 セッション連続検出

## セッション再開手順（コピペ可）

```bash
cd /Users/yyyhhh/Projects/wiseman_auto_sys
# PR #65 確認
gh pr checks 65

# 全て green ならマージ
gh pr merge 65 --squash --delete-branch
git checkout main
git reset --hard origin/main

# 12B 着手
git checkout -b feature/task-12b-settings-gui

# TDD: まず Red
# tests/unit/ui/test_settings.py 新規
```

## 12B 設計メモ（詳細）

### ファイル構成案

```
src/wiseman_hub/ui/settings.py
  class SettingsDialog:
    def __init__(self, config: AppConfig, config_path: Path, *, root=None, save_fn=save_config, ...)
    def run(self) -> SettingsDialogResult  # cancelled / saved (new AppConfig)
```

### バリデーション（pure logic 層）

```python
def validate_settings_form(form: SettingsForm) -> list[str]:
    """必須項目チェック。エラーメッセージ一覧を返す（空 = OK）。"""
    errors = []
    if not form.input_dir.strip(): errors.append("入力フォルダが未入力")
    if not form.output_dir.strip(): errors.append("出力フォルダが未入力")
    if not form.source_a_filename.strip(): errors.append("A.pdf ファイル名が未入力")
    if not form.ocr_endpoint.strip(): errors.append("OCR エンドポイントが未入力")
    if not form.ocr_api_key.strip(): errors.append("OCR API キーが未入力")
    # bbox は 4 要素 int[], concat_order は enum
    return errors
```

### テストパターン

```python
def test_validate_missing_input_dir_returns_error(self): ...
def test_save_writes_toml_and_preserves_comments(self, tmp_path): ...
def test_api_key_field_is_masked(self): ...  # Tk wiring
def test_folder_chooser_updates_entry(self, tmp_path): ...  # Tk wiring
def test_launcher_integration(self, tmp_path): ...  # on_open_settings で SettingsDialog 起動
```

### Launcher 連携

```python
# __main__.py
def _make_settings_callback(config_path: Path, launcher: Launcher) -> Callable[[], None]:
    def open_settings() -> None:
        result = SettingsDialog(
            config=load_config(config_path),
            config_path=config_path,
        ).run()
        if result.saved:
            launcher.reload_config()  # validate_config_ready を再評価するため
    return open_settings
```

`Launcher` に `reload_config()` メソッド追加が必要（13B スコープ外）。

## 参照ファイル（次セッション用）

### 実装対象
- `src/wiseman_hub/ui/settings.py`: 新規、12B 実装ファイル
- `src/wiseman_hub/ui/launcher.py`: `reload_config` 追加（optional）
- `src/wiseman_hub/__main__.py`: `_make_settings_callback` 追加

### 既存資産
- `src/wiseman_hub/config.py`: `save_config`（12A で完成）、`load_config`
- `src/wiseman_hub/ui/confirm_dialog.py`: Tkinter ダイアログパターン
- `src/wiseman_hub/ui/launcher.py`: `validate_config_ready` / DI パターン
- `src/wiseman_hub/ui/common.py`: `assert_main_thread`
- `tests/unit/ui/conftest.py`: `@pytest.mark.tk_required`
