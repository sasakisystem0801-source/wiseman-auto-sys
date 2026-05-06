# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for wiseman_launcher (ADR-016 PR-3)。

ビルド:
    uv run pyinstaller wiseman_launcher.spec --clean --noconfirm

生成物:
    - Windows: dist/wiseman_launcher.exe (--onefile)
    - macOS:   dist/wiseman_launcher (smoke build 用、本番配布対象外)

設計判断:
    - --onefile（launcher は 1 exe 配布、本体 wiseman_hub.exe とは独立）
    - PR-3 では console=True（debug 用）。PR-4 で windowed 化を再評価
    - stdlib only なので hidden imports は最小（むしろ重量依存が混入したら fail させる）
    - icon は wiseman_hub.spec と共有（assets/icon.ico）
    - launcher は本体と独立 package のため pathex に src/ を含める
      （src/wiseman_hub_launcher/ を解決させる）

ADR-002 / ADR-016 §2 (bootstrapper / updater 分離) 参照。
"""

from pathlib import Path

# PyInstaller の spec グローバル（Analysis/EXE/PYZ 等）は実行時に注入される。
# 静的解析を通すため明示的に名前を列挙（flake8 / ruff の F821 回避）。
# ruff: noqa: F821

# SPECPATH は PyInstaller が spec ファイルの絶対パスを注入するグローバル変数。
# CWD 依存を排除し、任意 dir からの実行でも安定して動く。
ROOT = Path(SPECPATH)  # noqa: F821 — SPECPATH は PyInstaller が spec 実行時に注入

block_cipher = None


a = Analysis(
    [str(ROOT / "src" / "wiseman_hub_launcher" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[],
    hiddenimports=[
        # stdlib only なので原則不要だが、urllib.request は環境によって自動検出が
        # 抜けるケースが報告されているため明示する（最小限の補強）。
        "urllib.request",
        "urllib.error",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 本番 launcher では test / lint ツールは不要
        "pytest",
        "mypy",
        "ruff",
        # ★重量依存の混入防止: stdlib only を逸脱したら build を fail させる目的で
        # excludes に挙げる（ADR-016 PR-3 の AC #7 を bundle レベルでも担保）
        "google",
        "google.cloud",
        "google.auth",
        "google.oauth2",
        "requests",
        "tomlkit",
        "tomli",
        "pywinauto",
        "pyautogui",
        "pystray",
        "PIL",
        "pandas",
        "fitz",        # PyMuPDF
        "pymupdf",
        "openpyxl",
        "httpx",
        "win32com",
        "pywin32",
        "wiseman_hub",  # 本体への依存禁止（ADR-016 PR-3 AC #9）
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Windows .ico、macOS は icon を無視（warning のみ）。本番は Windows のみ。
_ICON = str(ROOT / "assets" / "icon.ico")

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="wiseman_launcher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX 圧縮は Windows Defender 誤検知リスクがあるため無効
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # PR-3: debug 用、PR-4 で windowed 検討
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_ICON,
)
