"""xlsx_path_cache GCS mirror viewer（ADR-016 Phase 3 PR-2）。

Mac dev 機から GCS 上にミラーされた cache 状態を read-only 確認する CLI。
業務責任者 PC で確定した cache を Mac から覗き見られるため:

    - PC 入替前の cache 棚卸し
    - 巻き戻し検出（``config_revision`` の差分確認）
    - 90 日超の STALE entry 棚卸し

実行例:
    # 全件（tombstone 非表示）
    uv run python scripts/checklist_c_cache_view.py --all

    # 全件 + tombstone
    uv run python scripts/checklist_c_cache_view.py --all --include-deleted

    # 単一 key
    uv run python scripts/checklist_c_cache_view.py --key "宮下:2026:3"

    # config を明示
    uv run python scripts/checklist_c_cache_view.py --all --config /path/to/default.toml

exit code:
    0 = 成功
    1 = 引数エラー（key 形式不正など）
    2 = 設定不足（config 読込失敗 / GCP 未設定）
    3 = network / API 失敗（fetch_all で空 list 返却 + log にエラー記録）
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys
from pathlib import Path

from wiseman_hub.cloud.xlsx_path_cache_mirror import (
    _validate_gcp,
    fetch_all,
    fetch_one,
)
from wiseman_hub.config import load_config

# JST 表示用（生成された generated_at は UTC、表示時に JST 併記）
_JST = _dt.timezone(_dt.timedelta(hours=9), name="JST")
_STALE_DAYS = 90


def _resolve_config_path(arg: str | None) -> Path | None:
    """``--config`` 引数 / ``WISEMAN_HUB_CONFIG`` env / default の優先順で解決。"""
    if arg:
        return Path(arg)
    env = os.environ.get("WISEMAN_HUB_CONFIG")
    if env:
        return Path(env)
    return None  # load_config が config/default.toml を解決


def _validate_key(key: str) -> bool:
    """key 形式 ``staff:year:month`` の単純検証（``:`` の数 = 2、staff に ``:`` 含まない）。

    `staff` は normalize_lookup_key 経由で全角空白等を含み得るため、空文字以外なら
    許容する（厳密な担当者名検証は config/default.toml と突き合わせる別 CLI の仕事）。
    """
    parts = key.split(":")
    if len(parts) != 3:
        return False
    staff, year_s, month_s = parts
    if not staff:
        return False
    try:
        int(year_s)
        m = int(month_s)
    except ValueError:
        return False
    return 1 <= m <= 12


def _parse_iso_utc(ts: str) -> _dt.datetime | None:
    """ISO8601 文字列を datetime にパース。失敗時 None。"""
    try:
        # Python 3.11+ では `+00:00` / `Z` 両方に対応（fromisoformat は 3.11 で改善済）
        return _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _format_age_days(generated_at: str | None) -> str:
    """generated_at から現在までの経過日数を ``"12 日"`` 形式で返す。"""
    if not generated_at:
        return "?"
    parsed = _parse_iso_utc(generated_at)
    if parsed is None:
        return "?"
    now = _dt.datetime.now(tz=_dt.UTC)
    delta = now - parsed
    return f"{delta.days} 日"


def _format_jst(ts: str | None) -> str:
    """UTC ISO8601 を ``"<UTC> (<JST>)"`` 形式で表示。"""
    if not ts:
        return "?"
    parsed = _parse_iso_utc(ts)
    if parsed is None:
        return ts
    jst = parsed.astimezone(_JST)
    return f"{ts} (JST: {jst.strftime('%Y-%m-%d %H:%M:%S')})"


def _is_tombstone(entry: dict) -> bool:
    """``xlsx_path`` フィールドの欠如で tombstone と判別する。"""
    return "xlsx_path" not in entry


def _is_stale(entry: dict) -> bool:
    """alive entry が 90 日以上経過しているか。"""
    if _is_tombstone(entry):
        return False
    parsed = _parse_iso_utc(entry.get("generated_at", ""))
    if parsed is None:
        return False
    now = _dt.datetime.now(tz=_dt.UTC)
    return (now - parsed).days >= _STALE_DAYS


def _print_entry(entry: dict) -> None:
    """1 entry を 5-7 行で人間可読に表示。"""
    is_dead = _is_tombstone(entry)
    markers: list[str] = []
    if is_dead:
        markers.append("DELETED")
    elif _is_stale(entry):
        markers.append(f"STALE (>={_STALE_DAYS}d)")
    marker_str = f"  [{', '.join(markers)}]" if markers else ""

    key = entry.get("key", "?")
    print(f"\n=== {key}{marker_str} ===")
    if is_dead:
        print("  xlsx_path:        <deleted>")
        print(f"  deleted_at:       {_format_jst(entry.get('deleted_at'))}")
    else:
        print(f"  xlsx_path:        {entry.get('xlsx_path', '?')}")
        print(f"  generated_at:     {_format_jst(entry.get('generated_at'))}")
        print(f"  age_days:         {_format_age_days(entry.get('generated_at'))}")
    print(f"  machine_id:       {entry.get('machine_id', '?')}")
    print(f"  config_revision:  {entry.get('config_revision', '?')}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "xlsx_path_cache GCS mirror viewer (ADR-016 PR-2)。"
            "Mac から GCS 上の cache 状態を read-only 確認する。"
        )
    )
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--all",
        action="store_true",
        help="全 entry を表示（tombstone は default 非表示）",
    )
    group.add_argument(
        "--key",
        default=None,
        metavar="KEY",
        help='単一 entry を表示（例: "宮下:2026:3"）',
    )
    ap.add_argument(
        "--include-deleted",
        action="store_true",
        help="--all 時に tombstone も含める",
    )
    ap.add_argument(
        "--config",
        default=None,
        help=(
            "config TOML のパス（省略時は WISEMAN_HUB_CONFIG env or "
            "config/default.toml）"
        ),
    )
    args = ap.parse_args()

    if args.key is not None and not _validate_key(args.key):
        print(
            f"ERROR: --key 形式不正: {args.key!r} "
            '(期待: "staff:year:month" 例: "宮下:2026:3")',
            file=sys.stderr,
        )
        return 1

    config_path = _resolve_config_path(args.config)
    try:
        config = load_config(config_path)
    except (OSError, ValueError, TypeError) as exc:
        print(
            f"ERROR: 設定ファイル読込失敗 (config={config_path}): "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 2

    missing = _validate_gcp(config.gcp)
    if missing:
        print(
            f"ERROR: GCP 設定不足: {', '.join(missing)}",
            file=sys.stderr,
        )
        return 2

    if args.key is not None:
        entry = fetch_one(args.key, config.gcp)
        if entry is None:
            print(
                f"key={args.key!r} は GCS に存在しません（または fetch 失敗、ログ参照）",
                file=sys.stderr,
            )
            return 0
        _print_entry(entry)
        return 0

    # --all
    entries = fetch_all(config.gcp)
    if not entries:
        # GCS が空 or fetch 失敗（後者は logger.warning に出る）
        print("entries: 0 (GCS 上に entry なし、または fetch 失敗)")
        return 0

    if not args.include_deleted:
        entries = [e for e in entries if not _is_tombstone(e)]

    # key で sort（PII 配慮で staff は表示するが、CLI 利用者 = 業務責任者なので OK）
    entries.sort(key=lambda e: e.get("key", ""))

    alive_count = sum(1 for e in entries if not _is_tombstone(e))
    dead_count = sum(1 for e in entries if _is_tombstone(e))
    stale_count = sum(1 for e in entries if _is_stale(e))

    print(
        f"entries: {len(entries)} "
        f"(alive={alive_count}, deleted={dead_count}, stale>={_STALE_DAYS}d={stale_count})"
    )
    for entry in entries:
        _print_entry(entry)

    return 0


if __name__ == "__main__":
    sys.exit(main())
