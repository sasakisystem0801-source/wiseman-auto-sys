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

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)


def _hidden(pkg: str) -> list[str]:
    """`collect_submodules` の silent 漏れを構造的に排除する wrapper。

    default の ``on_error='warn once'`` は誤字 / 未インストールでも 0 件返して
    build を完走させ、Phase 6 canary 検証で初めて ``ModuleNotFoundError`` が
    露見する事故あり (review I2 反映、PR #254)。``on_error='raise'`` で
    spec parse 時点で fail-fast させる。
    """
    return collect_submodules(pkg, on_error="raise")

# PyInstaller の spec グローバル（Analysis/EXE/PYZ 等）は実行時に注入される。
# 静的解析を通すため明示的に名前を列挙（flake8 / ruff の F821 回避）。
# ruff: noqa: F821

# SPECPATH は PyInstaller が spec ファイルの絶対パスを注入するグローバル変数。
# CWD 依存を排除し、任意 dir からの実行でも安定して動く。
ROOT = Path(SPECPATH)  # noqa: F821 — SPECPATH は PyInstaller が spec 実行時に注入

block_cipher = None


# sigstore-python の Verifier.production() に必要な supply chain 依存を網羅。
#
# 旧戦略 (明示列挙) は内部 module (`sigstore._store` 等) の漏れで実機
# `Verifier.production()` init が ModuleNotFoundError で fail (Phase 6 canary
# 検証 2026-05-12、PR #254 review C1/C2 反映)。修正方針:
#
# 1. collect_data_files("sigstore") — TUF trust roots (`_store/prod/*.json`)
#    を data file に含める。`collect_submodules` だけでは .json が含まれず
#    `TrustedRoot.production()` で FileNotFoundError 再発する
# 2. collect_dynamic_libs("cryptography") — OpenSSL ベースの compiled
#    extension (`_rust.abi3.pyd`) を binaries に含めるため
# 3. collect_data_files("certifi") — TLS 検証用 CA bundle (`cacert.pem`)
# 4. PyPI 名 ≠ import 名: `sigstore-rekor-types` → `rekor_types`、
#    `pyopenssl` → `OpenSSL`、`pyjwt` → `jwt`、`rfc3161-client` → `rfc3161_client`
# 5. `_hidden(...)` で on_error='raise' を強制し silent 漏れを構造的排除
#
# NOTE: `collect_all(pkg)` を使わない理由 — PyInstaller 6.x で sigstore /
# cryptography / certifi に対し datas を 0 件で返す挙動を確認 (2026-05-12)。
# `collect_data_files` / `collect_dynamic_libs` を個別呼出しすると正しく取得
# できるため、確実性を優先して明示分離する。
_SIGSTORE_HIDDEN = (
    _hidden("sigstore")
    + _hidden("sigstore_protobuf_specs")
    + _hidden("rekor_types")
    + _hidden("tuf")
    + _hidden("securesystemslib")
    + _hidden("cryptography")
    + _hidden("certifi")
    + _hidden("OpenSSL")
    + _hidden("pyasn1")
    + _hidden("pyasn1_modules")
    + _hidden("rfc3161_client")
    + _hidden("id")
    + _hidden("jwt")
    + _hidden("rfc8785")
)
_SIGSTORE_DATAS = (
    collect_data_files("sigstore")
    + collect_data_files("cryptography")
    + collect_data_files("certifi")
)
_SIGSTORE_BINARIES = (
    collect_dynamic_libs("sigstore")
    + collect_dynamic_libs("cryptography")
    + collect_dynamic_libs("certifi")
)

a = Analysis(
    [str(ROOT / "src" / "wiseman_hub_launcher" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=_SIGSTORE_BINARIES,
    datas=_SIGSTORE_DATAS,
    hiddenimports=[
        # stdlib only なので原則不要だが、urllib.request は環境によって自動検出が
        # 抜けるケースが報告されているため明示する（最小限の補強）。
        "urllib.request",
        "urllib.error",
        # PR-6 後半: sigstore-python 統合 (ADR-016 §1.1.3 stdlib only 例外)
        *_SIGSTORE_HIDDEN,
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 本番 launcher では test / lint ツールは不要
        "pytest",
        "mypy",
        "ruff",
        # ★重量依存の混入防止: stdlib only + sigstore 例外 (§1.1.3) を逸脱したら build を fail
        # させる目的で excludes に挙げる（ADR-016 PR-3 の AC #7 を bundle レベルでも担保）。
        # PR-6 後半で sigstore + 推移依存 (cryptography / requests / tuf 等) が許可された
        # ため、これらを excludes から **除外** する (= sigstore に必要な dep は通す)。
        "google",
        "google.cloud",
        "google.auth",
        "google.oauth2",
        # "requests" は sigstore-python 推移依存のため excludes から削除 (PR-6 後半)
        # "tomli" は setuptools が vendored alias で追加するため excludes すると
        # PyInstaller の `setuptools.pre_safe_import_module` hook で
        # `Target module "tomli" already imported as ExcludedModule` ValueError を起こす。
        # sigstore-python が setuptools を推移引きするため、launcher.spec では tomli を
        # excludes に入れない (Issue #217、build-windows-smoke 失敗の root cause)。
        "tomlkit",
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
# Sug-4 (codex review threadId 019dfce6) 反映: icon 不在で silent build 完走 →
# 環境差で気づかぬ regression を生むため、spec parse 時点で fail-fast する。
_ICON_PATH = ROOT / "assets" / "icon.ico"
if not _ICON_PATH.exists():
    raise FileNotFoundError(f"icon asset not found: {_ICON_PATH}")
_ICON = str(_ICON_PATH)

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
