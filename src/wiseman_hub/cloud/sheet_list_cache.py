"""シート一覧（タブ名リスト）の起動時キャッシュ。

C ダイアログ起動時に毎回 Drive API を叩く UX の改善（PR-δ v1）。
ローカル JSON にキャッシュし、起動時は即座に combo を埋める。

cache 配置: ``<config_path.parent.parent>/cache/sheets/<spreadsheet_id>.json``
    例: ``$HOME/wiseman-hub/cache/sheets/abc123.json``

cache schema:
    {
        "spreadsheet_id": "abc123",
        "sheet_names": ["25年12月", "26年1月", ...],
        "fetched_at": "2026-05-05T15:30:00+09:00"
    }

無効/破損したキャッシュは黙って ``None`` 扱いし、再取得を促す。
TOML cache（xlsx_path_cache）と異なり PII は含まない（タブ名のみ）。
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


_SCHEMA_KEY = "sheet_names"


def cache_dir_for(config_path: Path) -> Path:
    """config_path から cache ディレクトリを導出する。

    例: ``$HOME/wiseman-hub/config/default.toml``
        → ``$HOME/wiseman-hub/cache/sheets``
    """
    return config_path.parent.parent / "cache" / "sheets"


def _path_for(cache_dir: Path, spreadsheet_id: str) -> Path:
    """spreadsheet_id 用の JSON ファイルパス。"""
    # spreadsheet_id は Drive API の英数字＋ハイフン＋アンダースコアのみ。
    # 念のため英数字以外の混入を弾く（path traversal 防止）。
    safe = "".join(c for c in spreadsheet_id if c.isalnum() or c in "-_")
    return cache_dir / f"{safe}.json"


def load(cache_dir: Path, spreadsheet_id: str) -> list[str] | None:
    """キャッシュからシート名リストを取得。

    Returns:
        存在 + 有効なら ``list[str]``、それ以外は ``None``（呼出側で再取得）。
    """
    if not spreadsheet_id:
        return None
    path = _path_for(cache_dir, spreadsheet_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("sheet list cache load failed: %s: %s", path, exc)
        return None
    sheets = data.get(_SCHEMA_KEY)
    if not isinstance(sheets, list) or not all(isinstance(s, str) for s in sheets):
        logger.warning("sheet list cache schema invalid: %s", path)
        return None
    return sheets


def save(cache_dir: Path, spreadsheet_id: str, sheet_names: list[str]) -> None:
    """シート名リストをキャッシュに保存。書込失敗は warning のみ（fatal にしない）。"""
    if not spreadsheet_id:
        return
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("sheet list cache mkdir failed: %s: %s", cache_dir, exc)
        return
    path = _path_for(cache_dir, spreadsheet_id)
    payload = {
        "spreadsheet_id": spreadsheet_id,
        _SCHEMA_KEY: list(sheet_names),
        "fetched_at": _dt.datetime.now(tz=_dt.UTC).isoformat(),
    }
    try:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as exc:
        logger.warning("sheet list cache save failed: %s: %s", path, exc)
