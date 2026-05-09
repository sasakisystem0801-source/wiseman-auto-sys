"""シート一覧（タブ名リスト）の起動時キャッシュ。

C ダイアログ起動時に毎回 Drive API を叩く UX の改善（PR-δ v1）。
ローカル JSON にキャッシュし、起動時は即座に combo を埋める。

Issue #238 Phase 1 (2026-05-09): load() の戻り値を ``CachedSheetList`` dataclass
化し、cache schema 内の ``fetched_at`` を UI に渡す。これにより
C ダイアログ初期ビューで「最終同期日時」を表示し、ユーザーが background 更新の
鮮度を可視化できるようにする (silent failure の早期発見にも寄与)。

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
from dataclasses import dataclass
from pathlib import Path

# Phase 2-α (Issue #238): format_synced_at_label を共有 helper に集約。
# 旧 import パス (``sheet_list_cache.format_synced_at_label``) を維持するため
# 本モジュールから re-export する。
from wiseman_hub.cloud.sync_label import (
    format_synced_at_label as format_synced_at_label,
)

__all__ = [
    "CachedSheetList",
    "cache_dir_for",
    "format_synced_at_label",
    "load",
    "save",
]

logger = logging.getLogger(__name__)


_SCHEMA_KEY = "sheet_names"


@dataclass(frozen=True)
class CachedSheetList:
    """sheet_list_cache.load() の戻り値 (Issue #238 Phase 1)。

    Attributes:
        names: シート名 (タブ名) の immutable tuple。
            review 反映 (type-design): ``frozen=True`` の名目を実体に揃え、
            caller の不用意な変更で cache が壊れないよう ``tuple[str, ...]`` に。
        fetched_at: cache 書込時刻 (ISO8601 から parse 済の tz-aware datetime)。
            旧 schema (fetched_at 欠落) / parse 失敗 / naive datetime (tz 欠落)
            は ``None``。UI 表示時の「不明」に対応。
    """

    names: tuple[str, ...]
    fetched_at: _dt.datetime | None


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


def _parse_fetched_at(raw: object) -> _dt.datetime | None:
    """payload の fetched_at を tz-aware datetime にパース。失敗時は None。

    review 反映 (code-reviewer Important / silent-failure MEDIUM-1):
    - parse 失敗時は warning ログを出して silent failure を回避
    - naive datetime (tz 欠落) は ``format_synced_at_label`` 内の ``now - fetched_at``
      で TypeError を起こすため、fromisoformat 後に tzinfo を検査して None フォールバック。

    旧 schema (fetched_at 欠落) と区別するため raw が文字列でない場合は warning なし。
    """
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = _dt.datetime.fromisoformat(raw)
    except ValueError as exc:
        logger.warning("sheet list cache fetched_at parse failed: %r: %s", raw, exc)
        return None
    if parsed.tzinfo is None:
        logger.warning(
            "sheet list cache fetched_at is naive (tz欠落): %r — discarding", raw
        )
        return None
    return parsed


def load(cache_dir: Path, spreadsheet_id: str) -> CachedSheetList | None:
    """キャッシュからシート名リスト + 取得時刻を取得。

    Returns:
        存在 + 有効なら ``CachedSheetList``、それ以外は ``None``（呼出側で再取得）。
        旧 schema (fetched_at 欠落) は ``CachedSheetList(names, fetched_at=None)``
        として返し、UI は「不明」相当の表示でフォールバック。
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
    fetched_at = _parse_fetched_at(data.get("fetched_at"))
    return CachedSheetList(names=tuple(sheets), fetched_at=fetched_at)


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


# NOTE: ``format_synced_at_label`` は Phase 2-α (Issue #238) で
# ``cloud.sync_label`` に移動した。本モジュールでは module 冒頭の
# ``from .sync_label import format_synced_at_label`` で re-export している。
