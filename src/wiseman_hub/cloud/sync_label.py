"""GCP 同期日時 UI 表示の共有ヘルパー (Issue #238 Phase 2-α)。

Phase 1 で sheet_list_cache 内に置いた ``format_synced_at_label`` を本モジュールに
集約し、汎用の ``write_sync_timestamp`` / ``read_sync_timestamp`` を提供する。

責務:
    - 単純な「最終同期日時」の永続化と読み出し (mapping_routing / report_staff 等)
    - sheet_list_cache (タブ名キャッシュ + fetched_at) 等の専用 cache とは分離

cache 配置:
    ``<config_path.parent.parent>/cache/sync/<name>.json``
    例: ``$HOME/wiseman-hub/cache/sync/mapping_routing.json``

cache schema:
    ``{"fetched_at": "<ISO8601 UTC>"}``

設計判断:
    - 旧 ``sheet_list_cache.format_synced_at_label`` は本モジュールへの re-export
      で後方互換を維持 (caller 影響ゼロ)
    - tz naive / parse 失敗 / future timestamp はすべて UI 側で displayable な
      フォールバック表現に変換 (TypeError / 例外を UI まで届けない)
    - name の path traversal は ValueError で拒否 (sanitize ではなく強制) ─
      caller 側で hard-coded 識別子のみ使う前提
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


# 英数 + `-_` のみ通す (path traversal / セパレータ混入を防止)。
_NAME_RE = re.compile(r"\A[A-Za-z0-9_\-]+\Z")


def sync_cache_dir_for(config_path: Path) -> Path:
    """config_path から sync timestamp の cache ディレクトリを導出する。

    例: ``$HOME/wiseman-hub/config/default.toml``
        → ``$HOME/wiseman-hub/cache/sync``
    """
    return config_path.parent.parent / "cache" / "sync"


def _validate_name(name: str) -> None:
    """name の path traversal / セパレータ混入を構造的に弾く。

    sanitize ではなく ValueError で拒否する設計理由:
        - caller は hard-coded 識別子 ("mapping_routing" 等) のみ使う前提
        - ユーザー入力由来の name は本モジュールに渡らない (UI が受けない)
        - sanitize で落とすと caller bug が silent に通る
    """
    if not _NAME_RE.match(name):
        raise ValueError(
            f"sync timestamp name must match {_NAME_RE.pattern}, got {name!r}"
        )


def _path_for(cache_dir: Path, name: str) -> Path:
    """name 用の JSON ファイルパス (validate 済前提)。"""
    return cache_dir / f"{name}.json"


def write_sync_timestamp(
    cache_dir: Path,
    name: str,
    *,
    ts: _dt.datetime | None = None,
) -> bool:
    """指定 ``name`` の sync timestamp を JSON として書き込む。

    Args:
        cache_dir: cache ディレクトリ (存在しなければ自動作成)
        name: 識別子 ([A-Za-z0-9_-]+)、path traversal は ValueError で拒否
        ts: 書き込む時刻。``None`` なら呼出時の ``datetime.now(tz=UTC)`` で
            上書きする (既存値があれば置換)。**過去時刻を保持したい migration
            用途では必ず明示的に tz-aware datetime を渡すこと**。

    Returns:
        ``True``: 書込成功 (mkdir + write_text 完了)
        ``False``: I/O 失敗 (mkdir / write_text の OSError)。caller は warn ログ
        を出して UI 進行を継続すること。

    Raises:
        ValueError: ``name`` が制約違反 / ``ts`` が naive (tz 欠落) datetime。

    review 反映 (code-reviewer I-1 rating 7): ``read_sync_timestamp`` は naive
    datetime を None フォールバックして「不明」表示にするため、書込側で naive
    を受け入れると「書いた直後に read で消える」asymmetric が発生する。
    対称性を担保するため write 側で構造的に reject。

    Phase 2-β (silent-failure F1 rating 6): 書込失敗 (OSError) は raise せず
    ``False`` を返す契約に変更。caller (Tk handler) は False を見て warn ログ
    を emit し UI 進行を継続する。**入力不正 (ValueError) と I/O 失敗 (False)
    の境界を保つ**: caller bug は例外、I/O 経路は戻り値で signal。
    """
    _validate_name(name)
    if ts is None:
        ts = _dt.datetime.now(tz=_dt.UTC)
    elif ts.tzinfo is None:
        # I-1 反映: read 側が naive を None 化するので書込側でも reject。
        raise ValueError(
            f"ts must be timezone-aware (got naive datetime: {ts!r})"
        )
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning(
            "sync timestamp mkdir failed: %s: %s", cache_dir, type(exc).__name__
        )
        return False
    path = _path_for(cache_dir, name)
    payload = {"fetched_at": ts.isoformat()}
    try:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as exc:
        logger.warning(
            "sync timestamp write failed: %s: %s", path, type(exc).__name__
        )
        return False
    return True


def read_sync_timestamp(cache_dir: Path, name: str) -> _dt.datetime | None:
    """指定 ``name`` の sync timestamp を JSON から読み出す。

    Returns:
        - tz-aware datetime (parse + tzinfo 検証成功時)
        - ``None``: 不在 / parse 失敗 / schema 不正 / tz naive

    読み込み / parse 失敗時の warning ログ:
        - 不在: ログなし (genuine "未同期" 状態)
        - JSON 破損 / schema 不正 / naive datetime: warning (silent failure 回避)
    """
    _validate_name(name)
    path = _path_for(cache_dir, name)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning(
            "sync timestamp load failed: %s: %s", path, type(exc).__name__
        )
        return None
    if not isinstance(data, dict):
        logger.warning("sync timestamp schema invalid (not a dict): %s", path)
        return None
    raw = data.get("fetched_at")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = _dt.datetime.fromisoformat(raw)
    except ValueError as exc:
        logger.warning(
            "sync timestamp fetched_at parse failed: %r: %s", raw, exc
        )
        return None
    if parsed.tzinfo is None:
        logger.warning(
            "sync timestamp fetched_at is naive (tz欠落): %r — discarding", raw
        )
        return None
    return parsed


def format_synced_at_label(
    fetched_at: _dt.datetime | None, now: _dt.datetime
) -> str:
    """「5/9 14:30 (3 分前)」形式で UI 表示用のラベル文字列を生成する。

    Phase 1 で ``cloud.sheet_list_cache`` に実装した本関数を Phase 2-α で
    本モジュール (sync_label) に移動。``sheet_list_cache.format_synced_at_label``
    は本実装を re-export することで後方互換を維持 (caller 影響ゼロ)。

    Args:
        fetched_at: cache 取得時刻 (None なら「不明」)
        now: 現在時刻 (テスト容易性のため引数注入、通常は ``datetime.now(tz=UTC)``)

    Returns:
        - ``fetched_at`` が None: ``"不明"``
        - now < fetched_at (時計ずれ): ``"M/D HH:MM (時刻同期確認中)"``
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
