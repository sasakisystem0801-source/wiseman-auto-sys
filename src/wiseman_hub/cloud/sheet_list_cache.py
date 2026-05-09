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

logger = logging.getLogger(__name__)


_SCHEMA_KEY = "sheet_names"


@dataclass(frozen=True)
class CachedSheetList:
    """sheet_list_cache.load() の戻り値 (Issue #238 Phase 1)。

    Attributes:
        names: シート名 (タブ名) のリスト
        fetched_at: cache 書込時刻 (ISO8601 から parse 済の datetime)。
            旧 schema (fetched_at 欠落) や parse 失敗時は ``None``。
            UI 表示時の「不明」に対応。
    """

    names: list[str]
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
    """payload の fetched_at を datetime にパース。失敗時は None。

    旧 schema (fetched_at 欠落) も None として扱い後方互換を維持。
    """
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return _dt.datetime.fromisoformat(raw)
    except ValueError:
        return None


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
    return CachedSheetList(names=sheets, fetched_at=fetched_at)


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


def format_synced_at_label(
    fetched_at: _dt.datetime | None, now: _dt.datetime
) -> str:
    """「5/9 14:30 (3 分前)」形式で UI 表示用のラベル文字列を生成 (Issue #238 Phase 1)。

    Args:
        fetched_at: cache 取得時刻 (None なら「不明」)
        now: 現在時刻 (テスト容易性のため引数注入、通常は ``datetime.now(tz=UTC)``)

    Returns:
        - ``fetched_at`` が None: ``"不明"``
        - now < fetched_at (時計ずれ等): ``"M/D HH:MM (時刻同期確認中)"``
        - 60 秒未満: ``"M/D HH:MM (たった今)"``
        - 60 分未満: ``"M/D HH:MM (N 分前)"``
        - 24 時間未満: ``"M/D HH:MM (N 時間前)"``
        - それ以上: ``"M/D HH:MM (N 日前)"``

    Note:
        絶対時刻表示は ``fetched_at`` をローカルタイムゾーンに変換した上で
        月/日と時:分を Python 標準の整形 (``f"{m}/{d}"`` 等) で組み立てる。
        ``%-m`` 等の platform 依存指定子を避けクロスプラットフォーム対応。
    """
    if fetched_at is None:
        return "不明"
    local = fetched_at.astimezone()
    abs_str = f"{local.month}/{local.day} {local.hour:02d}:{local.minute:02d}"
    delta = now - fetched_at
    sec = int(delta.total_seconds())
    if sec < 0:
        rel = "時刻同期確認中"
    elif sec < 60:
        rel = "たった今"
    elif sec < 3600:
        rel = f"{sec // 60} 分前"
    elif sec < 86400:
        rel = f"{sec // 3600} 時間前"
    else:
        rel = f"{sec // 86400} 日前"
    return f"{abs_str} ({rel})"
