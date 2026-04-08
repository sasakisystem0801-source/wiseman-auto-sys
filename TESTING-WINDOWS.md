# Windows統合テスト実行ガイド

Windows実機でPywinautoEngine統合テストを実行・デバッグする手順書。

## 前提条件

- Windows 10 / 11
- Python 3.11+ (uv インストール済み)
- MSBuild (Visual Studio または Build Tools)
- .NET Framework 4.8.1 以上

## テスト実行

### ステップ1: リポジトリ更新

```powershell
cd C:\path\to\wiseman_auto_sys
git pull origin main
uv sync --extra dev
```

### ステップ2: モックアプリのプロセス停止（必須）

```powershell
Get-Process WisemanMock -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 1
```

### ステップ3: テスト実行

```powershell
# 全統合テスト実行
uv run pytest tests/integration -v -m integration --timeout=120

# 個別テスト実行
uv run pytest tests/integration/test_launch.py -v --timeout=120
uv run pytest tests/integration/test_navigate_menu.py -v --timeout=120
uv run pytest tests/integration/test_read_grid.py -v --timeout=120
uv run pytest tests/integration/test_export_csv.py -v --timeout=120
uv run pytest tests/integration/test_close_window.py -v --timeout=120
uv run pytest tests/integration/test_new_registration_flow.py -v --timeout=120
uv run pytest tests/integration/test_full_pipeline.py -v --timeout=120
```

## 推奨実行順序

依存関係に基づく推奨順序（ADR-007: USB ドングル認証のみ、ログイン画面なし）:

1. **test_launch.py** — 基本: アプリ起動、メインウィンドウ出現確認
2. **test_navigate_menu.py** — メニュー操作
3. **test_read_grid.py** — DataGridView読み取り
4. **test_export_csv.py** — CSV出力
5. **test_close_window.py** — ウィンドウ閉じる・終了
6. **test_new_registration_flow.py** — 新規登録フロー
7. **test_full_pipeline.py** — E2Eパイプライン

## よくある失敗パターンと解決方法

### パターン1: `launch` 失敗

**症状:**
```
ElementNotFoundError: メインウィンドウが見つかりません
```

**原因:**
- モックアプリが正しく起動していない
- ウィンドウタイトルが想定と異なる
- 実機では USB ドングルが未接続

**解決方法:**
```powershell
# モックアプリを手動起動してUI検査
Inspect.exe  # Windows標準ツール
# WisemanMock.exe のウィンドウタイトルとコントロールを確認
# 実機の場合: USB ドングルの接続を確認してから exe を起動
```

### パターン2: `navigate_menu` 失敗

**症状:**
```
MDI子ウィンドウが検出されない
または
menu_select失敗、MenuItemクリックフォールバック実行
```

**原因:**
- MenuStripがUIAで正しく公開されていない
- MenuItemタイトルが想定と異なる

**解決方法:**

```python
# テストにデバッグログを追加
import logging
logging.basicConfig(level=logging.DEBUG)

# または Inspect.exe で MainForm の MenuStrip構造を確認:
# - "ケア記録" MenuItemの正確なタイトル/control_type
# - "集計表" 項目の位置
```

### パターン3: `read_grid_data` 失敗

**症状:**
```
グリッドコントロールが見つからない
または
ヘッダー/データ行を読み取れない
```

**原因:**
- DataGridViewが "Table" 以外のcontrol_typeで公開されている
- auto_idが "dgvCareRecord" ではない

**解決方法:**

```powershell
# 1. UIカタログ生成
python scripts/dump_ui.py --output data/ui_catalogs/debug_carerecord.json --text

# 2. JSONファイルで "Table" または "DataGrid" を検索
# → "control_type" と "automation_id" を確認

# 3. 必要に応じて pywinauto_engine.py の read_grid_data() を更新:
#    control_type を実際の値に変更
#    auto_id を実際のIDに変更
```

### パターン4: `export_csv` 失敗

**症状:**
```
SaveFileDialogが表示されない
または
CSVファイルが生成されない
```

**原因:**
- btnPrintクリックが動作していない
- SaveFileDialogのコントロール構造が想定と異なる

**解決方法:**

```powershell
# 1. btnPrintクリック後の画面を確認
# 手動でモックアプリを起動 → メニュー → 印刷クリック
# ダイアログが表示されるか確認

# 2. ダイアログのコントロール構造を確認
Inspect.exe  # SaveFileDialogを検査
# ↓ "ファイル名" 入力欄の control_type/auto_id を確認
# ↓ "保存(&S)" ボタンの正確なタイトルを確認

# 3. 必要に応じて pywinauto_engine.py を更新:
#    FileNameControlHost → 実際のauto_idに変更
#    ".*保存.*" → 実際のボタンタイトルに変更
```

### パターン5: `close_wiseman` 失敗

**症状:**
```
プロセスがタイムアウト
または
確認ダイアログが検出されない
```

**原因:**
- btnExitクリックが動作していない
- 確認ダイアログのタイトル/コントロールが想定と異なる

**解決方法:**

```powershell
# 手動確認:
# 1. モックアプリ → [終了] ボタンクリック
# 2. "確認" ダイアログが表示され、"はい" "いいえ" ボタンがあるか確認
# 3. タイトルとボタンテキストをInspect.exeで確認
```

## 既知の制約事項

### GitHub Actions CI (windows-latest)
- デスクトップセッション制約により一部テストが失敗する可能性あり
- 推奨: ローカルWindows実機またはTeamViewerによるテスト

### フレームワーク互換性
- .NET Framework 4.8.1 必須
- VS Build Tools または Visual Studio Community のインストール必須

## デバッグ方法

### 詳細ログの有効化

```powershell
$env:PYWINAUTO_LOG_LEVEL = "DEBUG"
uv run pytest tests/integration -v -s --timeout=120  # -s: stdout表示
```

### 個別ステップでのテスト

```python
# 一時テストスクリプト: test_debug.py
from wiseman_hub.rpa.pywinauto_engine import PywinautoEngine
from tests.integration.conftest import MOCK_APP_EXE

engine = PywinautoEngine()
try:
    # ステップ1: 起動（USB ドングル認証、ログイン画面なし - ADR-007）
    engine.launch(str(MOCK_APP_EXE))
    print("OK: Launch")

    # ステップ2: メニュー遷移
    engine.navigate_menu(["ケア記録", "集計表"])
    print("OK: Menu")

    # ステップ3: グリッド読み取り
    data = engine.read_grid_data()
    print(f"OK: Grid {len(data)} rows")

finally:
    engine.close_wiseman()
```

実行:
```powershell
uv run python test_debug.py
```

### UIカタログ生成・分析

```powershell
# 1. モックアプリを手動起動
# 2. UIカタログ生成
python scripts/dump_ui.py --text

# 3. 生成ファイルを確認
# data/ui_catalogs/YYYYMMDD_HHMMSS_*.json
# data/ui_catalogs/YYYYMMDD_HHMMSS_*.txt

# JSONファイルをエディタで開いて必要なコントロールを検索
```

## テスト結果の報告

テスト実行後、以下の情報を含めて報告してください:

1. **全体結果**
   ```
   7 passed
   または
   2 passed, 5 failed
   ```

2. **失敗したテストとエラーメッセージ**
   ```
   tests/integration/test_navigate_menu.py::TestNavigateMenu::test_navigate_to_care_record FAILED
   ElementNotFoundError: ...
   ```

3. **Windows環境情報**
   ```powershell
   [System.Environment]::OSVersion
   (Get-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full' -Name Release).Release
   ```

4. **MSBuildバージョン**
   ```powershell
   msbuild /version
   ```

## 次のステップ

### 全7テスト通過後:
1. Issue #3 進行: 実ワイズマンアプリでUIカタログ取得（smoke_real.py 利用）
2. Issue #6 進行: E2Eパイプライン実装（launch → navigate → export_csv → GCS upload）

### GitHub Actions CI安定化（任意）:
- 統合テストをローカルテストとして分類し、CIではスキップ

## 参考

- **pywinautoドキュメント**: https://pywinauto.readthedocs.io/
- **UIAutomation (UIA)**: Windows自動化標準。Inspect.exeで確認可能
- **WinForms MDI**: 多重ドキュメントインターフェイス。MDI子ウィンドウはMDIClient内部のWindow要素
