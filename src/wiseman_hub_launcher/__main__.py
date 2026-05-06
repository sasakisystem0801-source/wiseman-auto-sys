"""wiseman_launcher CLI entry point (ADR-016 PR-3)。

PR-3 で実装する subcommand:
    --dry-run            : manifest fetch + validate のみ（download/spawn なし）
    --version            : launcher 自身のバージョン表示
    --manifest-url URL   : manifest URL 上書き（test/canary 用）
    --current-path PATH  : current.json path 上書き
    --verbose            : DEBUG ログ

PR-4 で追加予定（本 PR では未実装）:
    --update             : 実 download + spawn + rollback
    --no-spawn           : update のみ実施し本体は起動しない

exit code:
    0  成功
    2  config / argparse error
    3  ManifestError / network error
    4  想定外
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from . import __version__
from .current import read_current
from .manifest import ManifestError, fetch_manifest, parse_manifest, validate_manifest

logger = logging.getLogger("wiseman_launcher")

# ADR-016 §1.1: release-prod は public read 前提（SA key embed 不要）
DEFAULT_MANIFEST_URL = "https://storage.googleapis.com/wiseman-hub-release-prod/manifest.json"
DEFAULT_CURRENT_PATH = Path.home() / "wiseman-hub" / "current.json"

EXIT_OK = 0
EXIT_CONFIG = 2
EXIT_MANIFEST = 3
EXIT_UNEXPECTED = 4


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wiseman_launcher",
        description="Wiseman Hub bootstrapper / updater (ADR-016)",
    )
    parser.add_argument("--version", action="version", version=f"wiseman_launcher {__version__}")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="manifest fetch + validate のみ実施（download/spawn なし）",
    )
    parser.add_argument(
        "--manifest-url",
        default=DEFAULT_MANIFEST_URL,
        help="manifest URL を上書き（test/canary 用）",
    )
    parser.add_argument(
        "--current-path",
        type=Path,
        default=DEFAULT_CURRENT_PATH,
        help="current.json の path を上書き",
    )
    parser.add_argument("--verbose", action="store_true", help="DEBUG ログを出力")
    return parser


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    # logging.basicConfig は stream を渡さないと sys.stderr が default
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _semver_tuple(s: str) -> tuple[int, int, int]:
    """semver "X.Y.Z" を比較可能な tuple に変換。format 不正は (0,0,0) fallback。"""
    try:
        parts = s.split(".")
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        return (0, 0, 0)


def run_dry_run(manifest_url: str, current_path: Path) -> int:
    """dry-run の主処理。manifest fetch + validate + 比較ログまで。"""
    current = read_current(current_path)
    logger.info("current version: %s (released_at=%s)", current.version, current.released_at or "n/a")

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


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    if not args.dry_run:
        # PR-3 では dry-run のみ実装。本番 update flow は PR-4
        logger.error(
            "PR-3 では --dry-run のみ実装されています（download/spawn は PR-4）。"
            "明示的に --dry-run を指定してください。"
        )
        return EXIT_CONFIG

    try:
        return run_dry_run(args.manifest_url, args.current_path)
    except Exception:  # noqa: BLE001 — top-level safety net
        logger.exception("unexpected error in launcher")
        return EXIT_UNEXPECTED


if __name__ == "__main__":
    raise SystemExit(main())
