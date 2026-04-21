# Handoff: "使える Windows デスクトップアプリ" 完成化計画（Session 7 終了時点）

**更新日**: 2026-04-21
**ブランチ**: feature/task-13a-launcher-gui (PR #61, CI 完了後マージ待ち)
**main**: 5f00d18 (PR #60 squash merged: タスク 10-1 + 12A + 14B)

## セッション 7 の成果

### マージ済み
- **PR #60**: タスク 10-1（Cloud Run デプロイ + 疎通確認）+ 12A（TOML 書き戻し）+ 14B（デスクトップアイコン）

### マージ待ち（次セッション冒頭で確認→マージ）
- **PR #61**: タスク 13A（ランチャー GUI 骨格、3 ボタン、コールバック DI）

## 次セッションの着手手順

```bash
cd /Users/yyyhhh/Projects/wiseman_auto_sys
# 1. catchup で状況把握
# 2. PR #61 CI 確認
gh pr checks 61
gh pr view 61
# 3. CI 通過していればマージ
gh pr merge 61 --squash --delete-branch
git checkout main
git reset --hard origin/main
# 4. タスク 13B 着手（Issue #62 対応含む）
git checkout -b feature/task-13b-phase-a-integration
```

## 次タスク優先順位

### 優先 1: タスク 13B（ランチャー ↔ Phase A 統合）

**スコープ**:
- `Launcher.__init__` の `on_run_pdf_merge` に `run_phase_a` 呼出を注入
- **Issue #62 対応必須**: Worker thread 化 + repeated-click 防止
  - `concurrent.futures.ThreadPoolExecutor(max_workers=1)` を Launcher に保持
  - Tk 更新は `root.after()` 経由
  - 実行中は全 3 ボタン disable
- 進捗ダイアログ（Phase A 中のステータス表示）
- 完了時に NEEDS_REVIEW セッション一覧を通知（完了通知 → 次の確認ボタン押下を促す）

**Acceptance Criteria**:
- AC-L-2: Phase A 実行、完了通知、NEEDS_REVIEW があれば一覧遷移
- AC-L-2-Async: Phase A 実行中も mainloop が応答（Windows「応答なし」防止）
- AC-L-2-NoDouble: 実行中の 2 回目 click が無視される

**TDD の流れ**:
1. `tests/unit/ui/test_launcher_phase_a_integration.py` を Red で作成
2. `Launcher` に `_run_phase_a_async()` を最小実装で Green
3. worker thread + busy flag を段階的に追加
4. caplog で PII 漏洩しないことを確認

### 優先 2: タスク 12B（設定 GUI）

**スコープ**:
- `src/wiseman_hub/ui/settings.py` 新規
- 必須設定 5 項目 + optional 設定を Tkinter フォームで編集
- Save → `save_config(cfg, path)` 呼出（PR #60 で完成済）
- `ui/launcher.py` の `on_open_settings` に注入

### 優先 3: タスク 13C（ランチャー ↔ 確認 UI / Phase B 統合）

**スコープ**:
- `on_open_review` に NEEDS_REVIEW セッション一覧 → ConfirmDialog → run_phase_b
- Phase B 完了時の出力 PDF 通知

### 優先 4: タスク 14A（PyInstaller spec + icon 埋め込み）

**Issue #59 対応**: `--icon assets/icon.ico` 指定、生成 exe の resource 検証

### 優先 5: タスク 10-2（Windows 実機 E2E、本田さん実施）

`docs/handoff/windows-e2e-task10.md` に従って TeamViewer で実施。

### 優先 6: タスク 14C/14D/15/11

- 14C: PowerShell ショートカット作成スクリプト
- 14D: ADR-011（配布形態決定）
- 15: GitHub Actions + WIF（Issue #63 CI Tk 対応含むかも）
- 11: README + sample TOML（最後）

## 積み残し Issue

### Session 7 で新規追加
- **#58**: `/healthz` Cloud Run GFE intercept（P2、実害なし）
- **#59**: PyInstaller icon 埋め込み（P2、14A スコープ）
- **#62**: 13B worker thread + repeated-click（P1、13B 必須）
- **#63**: Linux CI Tk wiring skip（P2、15 / 別 PR）
- **#64**: `--config` 存在しないパス警告（P2）

### 継続
- **#51** Windows msvcrt / 跨プロセスロック / 0 ページ PDF (P1、単一 PC では発生せず)
- **#38** atomic_io ユーティリティ抽出（P2、config.py / session.py / merger.py / 新 save_config で重複）
- **#27 #29 #49 #50 #40 #39 #44 #45 #17 #16 #14 #11 #6**: 各種改善

## impl-plan 進捗（Session 7 終了時点）

| タスク | 状態 | PR |
|--------|------|-----|
| 10-1 Cloud Run デプロイ + 疎通確認 | ✅ merged | #60 |
| 10-2 Windows 実機 E2E | ⏳ 本田さん実施待ち | - |
| 12A TOML 書き戻し機能 | ✅ merged | #60 |
| 12B 設定 GUI | ⏳ 優先 2 | - |
| 12C 初回起動ウィザード | ⏳ 12B 後 | - |
| **13A ランチャー GUI 骨格** | 🔄 CI 通過待ち、次セッションでマージ | **#61** |
| **13B ランチャー ↔ Phase A 統合** | ⏳ **次セッション最優先** | - |
| 13C ランチャー ↔ 確認 UI 統合 | ⏳ | - |
| 14A PyInstaller spec | ⏳ GUI 完成後 | - |
| 14B アイコン生成 | ✅ merged | #60 |
| 14C ショートカット配布手順 | ⏳ 14A 後 | - |
| 14D ADR-011 執筆 | ⏳ 14A 完了時 | - |
| 15 GitHub Actions + WIF | ⏳ GUI 安定後 | - |
| 11 README + sample TOML | ⏳ 最後 | - |

## 本セッションで確定した設計判断

### 配布形態
- ダブルクリック起動の .exe（PyInstaller + 青背景 "W" アイコン + デスクトップショートカット）
- Windows 11 単一 PC、USB ドングル認証、PII 医療介護データ

### 認証レイヤ（再確認）
- **Cloud Run → Vertex AI**: attached SA（キーレス）✅
- **Windows クライアント → Cloud Run**: X-API-Key（ADR-008 維持）✅
- **開発/デプロイ → GCP**: WIF（タスク 15、GitHub Actions OIDC）⏳

### PII 防御パターン
- logger には例外型名のみ（message は path/氏名を含みうる）
- tmp ファイル cleanup の warning は basename すら出さない
- `root.report_callback_exception` で PII 防御 sanitize（ConfirmDialog / Launcher 共通）
- API Key は Secret Manager で rotation、docs には平文記載しない

### Quality Gate の実効性（Session 2-7 累積）
- **/simplify**: 各 PR で 6-8 件の DRY / stringly-typed / unnecessary comments を修正
- **Evaluator**: 実装スコープ宣言と AC の齟齬検出に有効（例: AC-L-4「設定誘導」の欠落）
- **Codex セカンドオピニオン**: PII 漏洩経路・運用経路・worker thread 化を 6 セッション連続検出
- **/review-pr**: 6 Agent 並列で観点網羅

## セッション再開手順（コピペ可）

```bash
cd /Users/yyyhhh/Projects/wiseman_auto_sys
# PR #61 確認
gh pr checks 61

# 全て green ならマージ
gh pr merge 61 --squash --delete-branch
git checkout main
git reset --hard origin/main

# 13B 着手
git checkout -b feature/task-13b-phase-a-integration

# TDD: まず Red
# tests/unit/ui/test_launcher_phase_a_integration.py 新規
```

## 13B 設計メモ（詳細）

### Worker thread 化パターン（Issue #62）

```python
# launcher.py
import concurrent.futures
from typing import Callable

class Launcher:
    def __init__(self, ...):
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self._busy = False

    def _handle_run_pdf_merge(self) -> None:
        if self._busy:
            return  # repeated-click 防止
        if not validate_config_ready(self._config):
            # ... エラー + 誘導 (既存)
            return
        if self._on_run_pdf_merge is None:
            self._invoke_or_show(None, ...)
            return

        self._set_busy(True)
        future = self._executor.submit(self._on_run_pdf_merge)
        future.add_done_callback(lambda f: self._root.after(0, self._on_phase_a_done, f))

    def _on_phase_a_done(self, future: concurrent.futures.Future) -> None:
        self._set_busy(False)
        try:
            future.result()
        except Exception:  # PII 防御
            logger.error("phase_a failed: %s", type(sys.exc_info()[1]).__name__)
            self._messagebox.showerror("エラー", "Phase A 実行中にエラー...")
            return
        self._messagebox.showinfo("完了", "Phase A 完了")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = ["disabled"] if busy else ["!disabled"]
        for btn in (self._btn_run, self._btn_review, self._btn_settings):
            btn.state(state)
```

### テストパターン（Phase A Async）

```python
def test_phase_a_runs_in_worker_thread(self, tmp_path):
    # run_phase_a が main thread 以外で呼ばれることを確認
    thread_ids = []
    def fake_phase_a():
        thread_ids.append(threading.get_ident())

    launcher = Launcher(..., on_run_pdf_merge=fake_phase_a)
    main_id = threading.get_ident()
    launcher.invoke_action(LauncherAction.RUN_PDF_MERGE)
    # future.result() を待って確認
    launcher._executor.shutdown(wait=True)
    assert thread_ids[0] != main_id

def test_repeated_click_ignored_while_busy(self, tmp_path):
    # busy 中の invoke_action は何もしない
    blocker = threading.Event()
    def slow():
        blocker.wait(timeout=5)

    launcher = Launcher(..., on_run_pdf_merge=slow)
    launcher.invoke_action(LauncherAction.RUN_PDF_MERGE)
    launcher.invoke_action(LauncherAction.RUN_PDF_MERGE)  # 2 回目、無視期待
    blocker.set()
    launcher._executor.shutdown(wait=True)
    # slow の呼出回数が 1 回であることを確認
```

## 参照ファイル（次セッション用）

### 実装対象
- `src/wiseman_hub/ui/launcher.py`: `_handle_run_pdf_merge` を async 化
- `src/wiseman_hub/pdf/pipeline.py:254 run_phase_a`: 直接呼び出し対象（dict パラメータ）
- `scripts/merge_user_pdfs.py`: 既存 CLI 実装の参考

### 既存資産
- `src/wiseman_hub/ui/confirm_dialog.py`: `_on_callback_exception` パターン
- `src/wiseman_hub/ui/common.py`: `assert_main_thread`
- `src/wiseman_hub/config.py`: `save_config` (12B で使用)
