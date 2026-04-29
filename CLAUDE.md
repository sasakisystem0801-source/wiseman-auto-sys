# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Test Commands

```bash
# Install dependencies
uv sync

# Run all tests
pytest

# Run a single test
pytest tests/unit/test_config.py::test_load_config_from_file

# Lint
ruff check src/
flake8 .          # pre-push hook uses this (config in .flake8)

# Type check
mypy src/

# Run the app
python -m wiseman_hub
```

Note: `pythonpath = ["src"]` is configured in pyproject.toml for pytest.

## Architecture

### What This System Does

Automates the care software "Wiseman System SP" via Python RPA (pywinauto) and syncs extracted data to GCP. The pipeline: **launch Wiseman → navigate to report → export CSV → upload to GCS**. Authentication is USB dongle only — no in-app login screen (see ADR-007).

### Key Architectural Fact

Wiseman is marketed as "ASP" (Application Service Provider) but the client is a **.NET Framework 3.5 native Windows app** (WinForms, MDI), not a browser app. Installed at `C:\Users\{User}\AppData\Local\Programs\WISEMAN\WISEMANVSYSTEM\`. Authentication is via physical USB dongle only — the app has no in-app login screen. Launch flow: exe start → dongle auth wait → main window appears directly (ADR-007).

### Data Flow

```
WisemanHub (app.py)  orchestrates:
  → RPAEngine (rpa/base.py)     GUI automation via pywinauto
    → Wiseman .NET app           MDI windows, WinForms controls
  → storage.py (cloud/)          uploads CSV to GCS
  → config.py                    loads TOML config (dataclass-based)
```

### Module Boundaries

- `rpa/` — **Windows-only**. Uses `sys.platform == "win32"` guard. Must provide mock implementations for macOS testing. All RPA implementations extend `RPAEngine` (abstract base class in `rpa/base.py`).
- `cloud/` — Cross-platform. GCP SDK clients.
- `config.py` — TOML loader with `tomllib` (3.11+) / `tomli` (3.9+) fallback. Config structure is nested dataclasses (`AppConfig` → `WisemanConfig`, `GcpConfig`, `ReportTarget`, etc.).
- `updater/`, `scheduler/`, `ui/` — Planned modules (empty stubs).

### Credentials

Wiseman uses USB dongle authentication only — there is no password to store. The `keyring` dependency was removed in ADR-007. GCP uses a service account key file referenced by path in TOML config.

## Cross-Platform Development

Development happens on macOS; Wiseman runs only on Windows.

- `rpa/` code cannot run on macOS — use mock implementations for unit tests
- Real E2E testing requires TeamViewer → Windows 11 client PC with USB dongle
- Use `Inspect.exe` or `Spy++` on Windows to discover pywinauto selectors
- Always use `pathlib.Path` — never hardcode `\\` path separators

### Windows 実機環境（本田様 PC、TeamViewer 経由）

**ユーザーが「Windows 機への反映」「TeamViewer で PowerShell」「main を実機に反映」と言ったらこのセクションを最初に読むこと**。clone 先を探し直す・誤推測する前に、ここに全情報がある。

#### 環境定数

| 項目 | 値 |
|---|---|
| PowerShell user | `sasak` |
| ソースリポジトリ clone 先 | `C:\Users\sasak\Projects\wiseman-auto-sys`（= `$HOME\Projects\wiseman-auto-sys`） |
| 配布物配置先（本番運用） | `C:\Users\sasak\wiseman-hub\`（= `$HOME\wiseman-hub`）。`wiseman_hub.exe` + `config/` + `assets/`、ADR-011 配布レイアウト |
| デスクトップショートカット | `$HOME\wiseman-hub\wiseman_hub.exe` を起動（作業フォルダ = `$HOME\wiseman-hub`） |
| 本番データ | `\\Tera-station\share\03.FAX(事業所)`（UNC パス、40 事業所、ADR-013） |
| Wiseman 本体 | `C:\Users\sasak\AppData\Local\Programs\WISEMAN\WISEMANVSYSTEM\` |

#### main を実機反映する正規手順

正規 runbook: **`docs/handoff/1c-exe-redistribution-runbook.md`**（Phase 0〜5、rollback / トラブル早見表あり）。

**最小フル手順（コピペ可、検証済 2026-04-29）**:

```powershell
# Phase 0: リポジトリ最新化
cd $HOME\Projects\wiseman-auto-sys
git checkout main
git pull --ff-only
git log --oneline -5

# Phase 0-2: 現行 exe バックアップ（rollback 用、必須）
$dist = "$HOME\wiseman-hub"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
Copy-Item "$dist\wiseman_hub.exe" "$dist\wiseman_hub.exe.bak-$stamp"

# Phase 0-4: 依存同期 + テスト（VS Build Tools 不要、integration 除外）
uv sync --extra dev
uv run pytest -q -m "not integration"

# Phase 1: clean ビルド
uv run pyinstaller wiseman_hub.spec --clean --noconfirm 2>&1 | Tee-Object -FilePath build.log

# Phase 1-2: warning 検査（PowerShell パイプ解釈の問題回避のため 1 行で実行）
Select-String -Path build.log -Pattern "Hidden import.*not found"
# ↑ 出力された warning が pycparser.lextab / pycparser.yacctab / jinja2 / user32 / msvcrt のいずれかなら無害（無視）。
#   それ以外（特に wiseman_hub / facility_merger / ex_extractor 等プロジェクト由来）が出たら進まず共有。

# Phase 2: 配布先に上書き
Copy-Item -Force dist\wiseman_hub.exe "$dist\wiseman_hub.exe"
Get-Item "$dist\wiseman_hub.exe" | Format-List Name, Length, LastWriteTime

# Phase 3: 動作確認
Start-Process "$dist\wiseman_hub.exe"
```

#### 動作確認チェックリスト（Phase 3）

| # | 項目 | 期待 |
|---|------|------|
| 1 | コンソール窓が出ずに Launcher ウィンドウ「Wiseman PDF ツール」が起動 | ✅ |
| 2 | **3 ボタン構成**（ex_ ファイル変換 + 振り分け / 事業所フォルダ一括結合 / 設定）— 旧 4 ボタンではない | ✅ PR #160 反映確認 |
| 3 | 各ボタンクリックで `ImportError` / `ModuleNotFoundError` ダイアログが出ない | ✅ |
| 4 | 機能追加 PR がある場合は対応する UI 変化を確認（runbook Phase 3 参照） | 機能依存 |

#### 既知の挙動（落とし穴）

- **VS Build Tools が無い PC でも `uv run pytest -q -m "not integration"` で完走可能**。`pytest -q` フルだと `tests/integration/` の `WisemanMock.exe` ビルドで MSBuild が呼ばれ fail する
- **`pytest` から実 Wiseman は起動されない**。`scripts/smoke_real.py` のみが実機 Wiseman を触る（pytest 非経由）
- **`uv sync` だけだと dev extras（pyinstaller / ruff / mypy / pytest）が削除される**。`uv sync --extra dev` 必須
- **PowerShell の `Select-String` パイプチェーンで `-NotMatch "..."` を使うと引数解釈が壊れることがある**。1 行 `Select-String` を 2 回叩くか、上記のように単発で出して目視判定するのが安全
- **`dist\wiseman_hub.exe` への `Copy-Item -Force` は exe 起動中だと file lock で失敗**。事前に Launcher を閉じる

#### rollback

```powershell
$dist = "$HOME\wiseman-hub"
$latest_bak = Get-ChildItem "$dist\wiseman_hub.exe.bak-*" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Copy-Item -Force $latest_bak.FullName "$dist\wiseman_hub.exe"
Write-Host "Restored from: $($latest_bak.Name)"
```

3 日以上動作問題なければ古いバックアップは削除可: `Remove-Item "$dist\wiseman_hub.exe.bak-*"`

#### ソース変更のみで exe 化不要な開発検証

```powershell
cd $HOME\Projects\wiseman-auto-sys
git pull
uv run python -m wiseman_hub
```

## Design Decisions

ADRs in `docs/adr/` (001–014). Wiseman technical spec in `docs/wiseman-system-spec.md`. PRD in `docs/prd.md`.

Key decisions: pywinauto over Playwright (ADR-001), PyInstaller for packaging (ADR-002), GCP tokyo region for APPI compliance (ADR-003), GCS manifest polling for auto-update (ADR-004), TOML config format (ADR-005), USB dongle authentication (ADR-007), OCR backend selection (ADR-008), Tkinter UI (ADR-009), human-confirmation state machine (ADR-010), distribution format (ADR-011), facility_merger output (ADR-012), facility root bulk merge (ADR-013), ex_extractor integration (ADR-014).

## Wiseman UI Structure (confirmed from real environment)

MDI parent window titled `通所・訪問リハビリ管理システム SP(ケア記録) [施設名]` with child windows. Standard WinForms controls: Button, ComboBox, CheckBox, RadioButton, DataGrid (with colored cells for abnormal values). See `docs/wiseman-system-spec.md` for full control tree and selector details.
