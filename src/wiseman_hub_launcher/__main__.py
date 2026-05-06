"""wiseman_launcher CLI entry point (ADR-016 PR-3 / PR-4)。

PR-3 で実装済 mode:
    --dry-run            : manifest fetch + validate のみ（download/spawn なし）
    --version            : launcher 自身のバージョン表示
    --manifest-url URL   : manifest URL 上書き（test/canary 用）
    --current-path PATH  : current.json path 上書き
    --verbose            : DEBUG ログ

PR-4 で追加:
    --update             : 実 download + current.json 切替 + spawn + rollback
    --no-spawn           : --update と組み合わせ、download + 切替のみ (spawn なし)
    --home PATH          : $HOME/wiseman-hub の上書き (test/canary 用)
    --monitor-timeout SEC: spawn 監視 timeout 上書き (test 高速化)
    --allow-insecure-checksum-only : SHA-256 のみで update を許可（PR-6 で provenance
                            実装まで本番 update は禁止、本フラグなしは fail-closed）

exit code:
    0  成功 (SUCCESS / OK_EARLY_EXIT、--dry-run / --no-spawn 完了)
    2  CONFIG (argparse / HTTPS pre-check / mode 不正 / fail-closed)
    3  MANIFEST / network / artifact size error
    4  UNEXPECTED
    5  CHECKSUM_MISMATCH (PR-4)
    6  ROLLBACK_UNAVAILABLE / preflight 失敗 (PR-4)
    7  SPAWN_FAILED_NO_ROLLBACK (新版 + 旧版とも spawn 失敗、PR-4)
    8  LOCK_HELD (多重起動、PR-4)
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from . import __version__
from .checksum import ChecksumError
from .current import read_current
from .manifest import (
    ManifestError,
    fetch_manifest,
    parse_manifest,
    validate_manifest,
)
from .updater import (
    DownloadError,
    LockHeartbeat,
    LockHeldError,
    PreflightError,
    SpawnFailedNoRollbackError,
    SpawnResult,
    acquire_lock,
    preflight,
    release_lock,
    update_and_spawn,
)

logger = logging.getLogger("wiseman_launcher")

# ADR-016 §1.1: release-prod は public read 前提（SA key embed 不要）
DEFAULT_MANIFEST_URL = "https://storage.googleapis.com/wiseman-hub-release-prod/manifest.json"
DEFAULT_HOME = Path.home() / "wiseman-hub"

EXIT_OK = 0
EXIT_CONFIG = 2
EXIT_MANIFEST = 3
EXIT_UNEXPECTED = 4
EXIT_CHECKSUM_MISMATCH = 5
EXIT_ROLLBACK_UNAVAILABLE = 6
EXIT_SPAWN_FAILED_NO_ROLLBACK = 7
EXIT_LOCK_HELD = 8


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wiseman_launcher",
        description="Wiseman Hub bootstrapper / updater (ADR-016)",
    )
    parser.add_argument(
        "--version", action="version", version=f"wiseman_launcher {__version__}"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "manifest fetch + validate のみ実施（download/spawn なし、"
            "副作用ゼロ: corrupt current.json の quarantine もしない）"
        ),
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help=(
            "実 download + current.json 切替 + spawn + rollback "
            "(PR-4、--allow-insecure-checksum-only 必須、PR-6 で gate 解除)"
        ),
    )
    parser.add_argument(
        "--no-spawn",
        action="store_true",
        help="--update と併用: download + 切替まで、spawn しない (PR-4)",
    )
    parser.add_argument(
        "--allow-insecure-checksum-only",
        action="store_true",
        help=(
            "PR-4 の supply-chain ゲート (provenance 未実装) を bypass。"
            "本番配布禁止、test/dev 限定 (PR-6 で除去)"
        ),
    )
    parser.add_argument(
        "--manifest-url",
        default=DEFAULT_MANIFEST_URL,
        help="manifest URL を上書き（test/canary 用）",
    )
    parser.add_argument(
        "--home",
        type=Path,
        default=DEFAULT_HOME,
        help=f"$HOME/wiseman-hub を上書き (default: {DEFAULT_HOME})",
    )
    parser.add_argument(
        "--current-path",
        type=Path,
        default=None,
        help="current.json の path 上書き (default: --home/current.json)",
    )
    parser.add_argument(
        "--monitor-timeout",
        type=_positive_float,
        default=30.0,
        help="spawn 監視 timeout 秒 (正値、test 用、default 30.0)",
    )
    parser.add_argument("--verbose", action="store_true", help="DEBUG ログを出力")
    return parser


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _positive_float(s: str) -> float:
    """argparse type: 正値の float (Suggestion 2、threadId 019dfd5d)。"""
    try:
        v = float(s)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"not a float: {s!r}") from e
    if v <= 0:
        raise argparse.ArgumentTypeError(f"must be positive: {v}")
    return v


def _semver_tuple(s: str) -> tuple[int, int, int]:
    """semver "X.Y.Z" を比較可能な tuple に変換。format 不正は (0,0,0) fallback。"""
    try:
        parts = s.split(".")
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        return (0, 0, 0)


def run_dry_run(manifest_url: str, current_path: Path, *, verbose: bool = False) -> int:
    """dry-run の主処理。manifest fetch + validate + 比較ログまで。

    副作用ゼロ保証 (codex I-3 反映):
        - current.json の破損 quarantine もしない (read_current に quarantine_corrupt=False)
        - manifest を fetch + validate + 比較するだけ、ファイル書込なし
    """
    current = read_current(current_path, quarantine_corrupt=False, verbose=verbose)
    logger.info(
        "current version: %s (released_at=%s)",
        current.version,
        current.released_at or "n/a",
    )

    if not manifest_url.startswith("https://"):
        logger.error("--manifest-url must use HTTPS scheme")
        return EXIT_CONFIG

    try:
        raw = fetch_manifest(manifest_url)
    except ManifestError as e:
        logger.error("manifest fetch failed: %s", e)
        return EXIT_MANIFEST

    try:
        manifest = parse_manifest(raw)
        validate_manifest(manifest)
    except ManifestError as e:
        logger.error("manifest validation failed: %s", e)
        return EXIT_MANIFEST

    new_version = manifest["current_version"]
    download_url = manifest["download_url"]
    assert isinstance(new_version, str)  # noqa: S101 — validate_manifest で str 検証済
    assert isinstance(download_url, str)  # noqa: S101

    cur_t = _semver_tuple(current.version)
    new_t = _semver_tuple(new_version)

    if new_t > cur_t:
        logger.info(
            "would download %s if confirmed (current=%s -> new=%s) [PR-4 で実装]",
            download_url,
            current.version,
            new_version,
        )
    elif new_t == cur_t:
        logger.info("already up-to-date (version=%s)", current.version)
    else:
        logger.warning(
            "manifest version (%s) is older than current (%s); skipping",
            new_version,
            current.version,
        )

    return EXIT_OK


def _spawn_outcome_to_exit(result: SpawnResult) -> int:
    """spawn 結果を exit code にマップ。"""
    if result in (SpawnResult.SUCCESS, SpawnResult.OK_EARLY_EXIT):
        return EXIT_OK
    return EXIT_SPAWN_FAILED_NO_ROLLBACK


def run_update(
    manifest_url: str,
    home_dir: Path,
    current_path: Path,
    *,
    no_spawn: bool,
    monitor_timeout_sec: float,
    allow_insecure: bool,
) -> int:
    """update mode の主処理 (PR-4)。

    Flow:
        1. supply-chain gate (allow_insecure=False なら fail-closed)
        2. lock 取得 (多重起動排他)
        3. manifest fetch + validate
        4. preflight (現行版 binary 存在確認)
        5. update_and_spawn (download + switch + spawn + rollback)
        6. lock 解放 (finally)
    """
    if not allow_insecure:
        logger.error(
            "PR-4 update mode requires --allow-insecure-checksum-only "
            "(provenance verification is not implemented until PR-6). "
            "Production update is fail-closed."
        )
        return EXIT_CONFIG

    if not manifest_url.startswith("https://"):
        logger.error("--manifest-url must use HTTPS scheme")
        return EXIT_CONFIG

    home_dir.mkdir(parents=True, exist_ok=True)
    lock_path = home_dir / "launcher.lock"

    try:
        lock_fd = acquire_lock(lock_path)
    except LockHeldError as e:
        logger.error("lock held: %s", e)
        return EXIT_LOCK_HELD

    # C-2 second-pass: heartbeat thread で stale 化を防止
    heartbeat = LockHeartbeat(lock_path)
    heartbeat.start()

    try:
        try:
            raw = fetch_manifest(manifest_url)
            manifest = parse_manifest(raw)
            validate_manifest(manifest)
        except ManifestError as e:
            logger.error("manifest error: %s", e)
            return EXIT_MANIFEST

        cur = read_current(current_path)
        versions_dir = home_dir / "versions"
        try:
            preflight(cur, versions_dir)
        except PreflightError as e:
            logger.error("preflight failed: %s", e)
            return EXIT_ROLLBACK_UNAVAILABLE

        try:
            outcome = update_and_spawn(
                manifest,
                home_dir,
                current_path=current_path,  # I-1 second-pass: --current-path 引き継ぎ
                monitor_timeout_sec=monitor_timeout_sec,
                no_spawn=no_spawn,
            )
        except ChecksumError as e:
            logger.error("checksum mismatch: %s", e)
            return EXIT_CHECKSUM_MISMATCH
        except DownloadError as e:
            logger.error("download error: %s", e)
            return EXIT_MANIFEST
        except PreflightError as e:
            logger.error("preflight failed during update: %s", e)
            return EXIT_ROLLBACK_UNAVAILABLE
        except SpawnFailedNoRollbackError as e:
            logger.error("spawn failed and rollback failed: %s", e)
            return EXIT_SPAWN_FAILED_NO_ROLLBACK

        return _spawn_outcome_to_exit(outcome.result)
    finally:
        heartbeat.stop()
        release_lock(lock_fd, lock_path)


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0911 — top-level dispatch
    parser = _build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    home_dir: Path = args.home
    current_path: Path = args.current_path or (home_dir / "current.json")

    if args.dry_run and args.update:
        logger.error("--dry-run and --update are mutually exclusive")
        return EXIT_CONFIG
    if args.no_spawn and not args.update:
        logger.error("--no-spawn requires --update")
        return EXIT_CONFIG

    if args.dry_run:
        try:
            return run_dry_run(args.manifest_url, current_path, verbose=args.verbose)
        except Exception:  # noqa: BLE001 — top-level safety net
            logger.exception("unexpected error in dry-run")
            return EXIT_UNEXPECTED

    if args.update:
        try:
            return run_update(
                args.manifest_url,
                home_dir,
                current_path,
                no_spawn=args.no_spawn,
                monitor_timeout_sec=args.monitor_timeout,
                allow_insecure=args.allow_insecure_checksum_only,
            )
        except Exception:  # noqa: BLE001 — top-level safety net
            logger.exception("unexpected error in update")
            return EXIT_UNEXPECTED

    logger.error(
        "no mode specified. use --dry-run or --update "
        "(see --help for full options)."
    )
    return EXIT_CONFIG


if __name__ == "__main__":
    raise SystemExit(main())
