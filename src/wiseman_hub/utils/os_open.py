"""OS のデフォルトアプリでファイル / ディレクトリを開く utility（クロスプラットフォーム）。

事業所結合 PDF や事業所フォルダを一覧 UI から「フォルダを開く」「PDFを開く」で
表示するために使う。

セキュリティ方針:
    - subprocess は ``shell=False`` 固定（パスインジェクション対策）
    - list 引数で渡し、パスを単一トークンとして扱う
    - 不在検出は関数内で先に行い、OS 依存のエラーメッセージ漏洩を避ける

サポート:
    - macOS（``darwin``）: ``open <path>``
    - Windows（``win32``）: ``os.startfile(str(path))``
    - Linux（``linux*``）: ``xdg-open <path>``
    - その他: ``NotImplementedError``
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# os.startfile は Windows でのみ存在。macOS/Linux 環境でテスト時に AttributeError に
# ならないよう、関数経由でアクセスする（テストから monkeypatch しやすくする目的も兼ねる）。
_startfile = getattr(os, "startfile", None)


def open_with_default_app(path: Path) -> None:
    """OS のデフォルトアプリでファイル/ディレクトリを開く。

    Args:
        path: 開く対象（ファイルまたはディレクトリ）。

    Raises:
        FileNotFoundError: path が存在しない。
        NotImplementedError: 未対応プラットフォーム。
        OSError: subprocess 起動失敗（例: xdg-open 未インストール）。
    """
    if not path.exists():
        # 不在検出は関数側で行う。subprocess 経由だと OS / コマンドごとに
        # エラーメッセージが異なり、UI 文言の組み立てがプラットフォーム依存になるため。
        raise FileNotFoundError(f"path does not exist: {path}")

    platform = sys.platform
    if platform == "darwin":
        subprocess.run(["open", str(path)], shell=False, check=True)
    elif platform == "win32":
        if _startfile is None:
            # Windows 判定だが startfile が存在しない（テストで強制的に win32 を
            # 設定した場合のみ到達するパス）。実環境では発生しない。
            raise NotImplementedError("os.startfile is unavailable on this build")
        _startfile(str(path))
    elif platform.startswith("linux"):
        subprocess.run(["xdg-open", str(path)], shell=False, check=True)
    else:
        raise NotImplementedError(f"unsupported platform: {platform}")
