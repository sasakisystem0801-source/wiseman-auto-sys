# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Wiseman PDF ツール（タスク 14A / Issue #59）。

ビルド:
    uv run pyinstaller wiseman_hub.spec

生成物:
    - Windows: dist/wiseman_hub.exe （--onefile --windowed）
    - macOS:   dist/wiseman_hub.app （開発時の smoke build 用、.app は本番配布対象外）

設計判断:
    - --onefile（単一 exe で配布、介護施設 PC への USB 配布運用に最適）
    - --windowed（コンソールを出さず GUI のみ、Launcher がユーザー接点）
    - icon は assets/icon.ico（14B で生成、6 サイズマルチ ICO）
    - Tk / tomlkit / httpx / fitz の hidden imports を明示
      （PyInstaller の自動検出で落ちる間接 import を補完）
    - TOML（config/default.toml）は exe と同ディレクトリ運用を想定し、
      data に埋め込まない（設定 GUI の編集結果が書き戻せるようファイル実体として配置）

ADR-002 参照。
"""

from pathlib import Path

# PyInstaller の spec グローバル（Analysis/EXE/BUNDLE 等）は実行時に注入される。
# 静的解析を通すため明示的に名前を列挙（flake8 / ruff の F821 回避）。
# ruff: noqa: F821

# SPECPATH は PyInstaller が spec ファイルの絶対パスを注入するグローバル変数。
# CWD 依存を排除し、任意 dir からの実行でも安定して動く（Claude comment-analyzer 指摘）。
ROOT = Path(SPECPATH)  # noqa: F821 — SPECPATH は PyInstaller が spec 実行時に注入


block_cipher = None


a = Analysis(
    [str(ROOT / "src" / "wiseman_hub" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[],
    hiddenimports=[
        # Tkinter: __main__ では TYPE_CHECKING だが UI サブモジュールでは実 import。
        # PyInstaller の自動検出を補強する（特に ttk / filedialog / messagebox）。
        "tkinter",
        "tkinter.ttk",
        "tkinter.filedialog",
        "tkinter.messagebox",
        # tomlkit: 設定 GUI の TOML 書き戻しで使用（遅延 import 経路あり）
        "tomlkit",
        # wiseman_hub 内部の遅延 import（__main__._make_*_callback で from 経由で import）
        "wiseman_hub.ui.launcher",
        "wiseman_hub.ui.confirm_dialog",
        "wiseman_hub.ui.session_picker",
        "wiseman_hub.ui.settings",
        "wiseman_hub.ui.common",
        "wiseman_hub.ui.facility_merger_dialog",
        "wiseman_hub.pdf.pipeline",
        "wiseman_hub.pdf.merger",
        "wiseman_hub.pdf.matcher",
        "wiseman_hub.pdf.ocr_client",
        "wiseman_hub.pdf.session",
        "wiseman_hub.pdf.splitter",
        "wiseman_hub.pdf.facility_merger",
        "wiseman_hub.pdf.text_name_extractor",
        "wiseman_hub.config",
        # --rpa フラグで WisemanHub (app.py) を遅延 import する経路
        # （__main__.main() の `from wiseman_hub.app import WisemanHub`）
        "wiseman_hub.app",
        # チェックリスト連携 B/C 自動配置機能（feature/checklist-bc-mvp）
        "wiseman_hub.cloud.sheets",
        "wiseman_hub.cloud.env_scanner",
        "wiseman_hub.pdf.checklist_b",
        "wiseman_hub.pdf.checklist_c",
        "wiseman_hub.pdf.excel_com",
        "wiseman_hub.ui.checklist_b_dialog",
        "wiseman_hub.ui.checklist_c_dialog",
        "wiseman_hub.ui.checklist_settings_dialog",
        # openpyxl の遅延 import 補強
        "openpyxl",
        "openpyxl.workbook",
        "openpyxl.reader.excel",
        # google.oauth2.service_account の依存
        "google.oauth2.service_account",
        "google.auth.transport.requests",
        # Excel COM (Windows のみ実 import、macOS smoke では除外される)
        "win32com",
        "win32com.client",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 本番 GUI 配布では pytest / mypy / ruff は不要
        "pytest",
        "mypy",
        "ruff",
    ],
    # `win_no_prefer_redirects` / `win_private_assemblies` は PyInstaller 6.x で
    # 非推奨扱い。v7 で signature から削除予定のため渡さない（Codex MEDIUM 指摘）。
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Windows 向けは .ico、macOS は .icns 推奨だが本番は Windows のみなので .ico で統一。
# macOS smoke build 時は PyInstaller が icon を無視する（warning のみ、実害なし）。
_ICON = str(ROOT / "assets" / "icon.ico")

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="wiseman_hub",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX 圧縮は Windows Defender 誤検知リスクがあるため無効（介護施設運用）
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # --windowed 相当、Launcher GUI のみ表示
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_ICON,
)

# macOS .app の BUNDLE は --onefile と組合せが v7.0 で error 化するため作らない。
# 介護施設本番は Windows のみ。macOS 開発機では `dist/wiseman_hub` 単一バイナリで
# hidden imports 妥当性を smoke test する（起動確認は Windows 実機 / CI で実施）。
