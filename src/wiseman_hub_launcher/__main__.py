"""wiseman_launcher CLI entry point (ADR-016 PR-3 / PR-4 / PR-6a / PR-6 後半)。

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

PR-6 後半で削除 (本格 fail-closed):
    `--allow-test-unsigned-provenance` flag + `WISEMAN_ALLOW_UNSIGNED_PROVENANCE_FOR_TESTS`
    環境変数を完全削除。signature 検証は sigstore-python に委譲して default 有効、
    bypass 経路は存在しない (本番 PC + test 環境共に同一 path で fail-closed)。

exit code は :class:`LauncherExitCode` 単一ソース (Issue #227)。runbook では
``int(LauncherExitCode.OK) == 0`` のように IntEnum を介して値を引く。
"""

from __future__ import annotations

import argparse
import enum
import logging
import sys
from pathlib import Path
from typing import assert_never

# Issue #217: PyInstaller bundle で `__main__.py` を直接 entrypoint にすると
# relative import が `ImportError: attempted relative import with no known parent
# package` で失敗するため、wiseman_hub/__main__.py と同じく absolute import を使う。
# `python -m wiseman_hub_launcher` 起動でも src/ が pathex にあれば動作する。
from wiseman_hub_launcher import __version__
from wiseman_hub_launcher._runtime import (
    LockHeartbeat,
    LockHeldError,
    acquire_lock,
    release_lock,
)
from wiseman_hub_launcher._supply_chain import (
    ProvenanceError,
    build_expected_identity,
)
from wiseman_hub_launcher.checksum import ChecksumError
from wiseman_hub_launcher.current import CurrentReadError, read_current
from wiseman_hub_launcher.manifest import (
    ManifestError,
    fetch_manifest,
    parse_manifest,
    validate_manifest,
)
from wiseman_hub_launcher.updater import (
    DownloadError,
    PreflightError,
    SpawnFailedNoRollbackError,
    SpawnResult,
    preflight,
    update_and_spawn,
)

logger = logging.getLogger("wiseman_launcher")

# ADR-016 §1.1: release-prod は public read 前提（SA key embed 不要）
DEFAULT_MANIFEST_URL = "https://storage.googleapis.com/wiseman-hub-release-prod/manifest.json"
DEFAULT_HOME = Path.home() / "wiseman-hub"


@enum.unique
class LauncherExitCode(enum.IntEnum):
    """ADR-016 launcher exit codes (POSIX 0..255 範囲)。

    Issue #227 で旧 ``EXIT_OK = 0`` 等の module-level int 定数を本 IntEnum に統合
    することで以下を実現:

    1. **typo 静的検出** — ``LauncherExitCode.OOK`` のような typo を mypy が
       reject (lock-in test で CI enforce、``test_main_exit_code_lockin.py``)。
    2. **docstring drift 解消** — exit code の意味は本 docstring が単一ソース。
       module docstring からは本 class への参照のみ。
    3. **uniqueness CI 化** — ``test_exit_codes_disjoint`` で値の重複を CI 検出。
    4. **shell 互換維持** — IntEnum なので ``raise SystemExit(LauncherExitCode.OK)``
       は ``int(LauncherExitCode.OK) == 0`` 経由で shell に正しく抜ける。

    triage 軸:
        ==========================  ==========================================
        OK / CONFIG / UNEXPECTED    launcher 自身の状態 (network 未到達)
        MANIFEST                    manifest 段階の HTTPS 取得失敗
        ARTIFACT                    artifact 段階の HTTPS 取得失敗 (Issue #212)
        CHECKSUM_MISMATCH           download 後 SHA-256 不一致 (replay/tamper 疑い)
        PROVENANCE                  sigstore 検証失敗 + claims 不一致 + URL 違反
        ROLLBACK_UNAVAILABLE        現行版 binary 不存在 / preflight 失敗
        SPAWN_FAILED_NO_ROLLBACK    新版 + 旧版とも spawn 失敗
        LOCK_HELD                   多重起動排他で停止
        ==========================  ==========================================

    runbook の triage では「manifest (3) か artifact (10) か」で HTTPS 取得段階を
    切り分け、checksum (5) / provenance (9) は供給チェーン疑いとしてエスカレーション。
    """

    OK = 0
    CONFIG = 2
    MANIFEST = 3
    UNEXPECTED = 4
    CHECKSUM_MISMATCH = 5
    ROLLBACK_UNAVAILABLE = 6
    SPAWN_FAILED_NO_ROLLBACK = 7
    LOCK_HELD = 8
    PROVENANCE = 9
    ARTIFACT = 10


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wiseman_launcher",
        description="Wiseman Hub bootstrapper / updater (ADR-016)",
    )
    parser.add_argument("--version", action="version", version=f"wiseman_launcher {__version__}")
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
            "実 download + provenance verify + current.json 切替 + spawn + rollback。"
            "PR-6 後半: signature 検証は sigstore-python 委譲で default 有効、bypass 経路なし"
        ),
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help=(
            "PyInstaller bundle smoke (Issue #217): sigstore-python + tuf + cryptography "
            "推移依存を eager import + helper 動作確認 + exit 0。CI build-smoke 専用、"
            "manifest/network/file I/O は一切触らない (副作用ゼロ)"
        ),
    )
    parser.add_argument(
        "--no-spawn",
        action="store_true",
        help="--update と併用: download + 切替まで、spawn しない (PR-4)",
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


def run_smoke_test() -> LauncherExitCode:
    """PyInstaller bundle smoke (Issue #217)。

    `--version` は argparse の早期 SystemExit で sigstore.py の関数内 lazy import が
    踏まれず、sigstore-python + tuf + cryptography hidden imports の解決失敗を
    検出できない。本 mode は CI build-smoke 専用で eager import + helper 呼出を
    実行する。manifest fetch / file I/O は一切触らない (副作用ゼロ)。

    成功 = sigstore-python の主要 module + helper が PyInstaller bundle 内で
    解決可能 = 推移依存 (tuf / cryptography / sigstore-protobuf-specs 等) の
    hidden imports が正しく bundled されている。
    """
    try:
        from sigstore.models import Bundle  # noqa: F401
        from sigstore.verify import Verifier  # noqa: F401
        from sigstore.verify.policy import Identity  # noqa: F401
    except ImportError as e:
        print(
            f"smoke test failed (sigstore-python import): {type(e).__name__}: {e}",
            file=sys.stderr,
        )
        return LauncherExitCode.UNEXPECTED

    identity = build_expected_identity(
        repo="example/repo",
        workflow_path=".github/workflows/release.yml",
        ref="refs/tags/v0.0.0",
    )
    if not identity.startswith("https://github.com/"):
        print(
            f"smoke test failed (build_expected_identity malformed): {identity!r}",
            file=sys.stderr,
        )
        return LauncherExitCode.UNEXPECTED

    print("smoke test passed: sigstore-python imports + helpers OK")
    return LauncherExitCode.OK


def run_dry_run(manifest_url: str, current_path: Path, *, verbose: bool = False) -> LauncherExitCode:
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
        return LauncherExitCode.CONFIG

    try:
        raw = fetch_manifest(manifest_url)
    except ManifestError as e:
        logger.error("manifest fetch failed: %s", e)
        return LauncherExitCode.MANIFEST

    try:
        parsed = parse_manifest(raw)
        validated = validate_manifest(parsed)
    except ManifestError as e:
        logger.error("manifest validation failed: %s", e)
        return LauncherExitCode.MANIFEST

    new_version = validated["current_version"]
    download_url = validated["download_url"]

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

    return LauncherExitCode.OK


def _spawn_outcome_to_exit(result: SpawnResult) -> LauncherExitCode:
    """spawn 結果を exit code にマップ (PR #230 review type-design I-1 反映)。

    ``match`` + ``assert_never`` で SpawnResult 拡張時の silent fallthrough を
    mypy が静的検出する (旧 ``in (SUCCESS, OK_EARLY_EXIT)`` fall-through 設計
    では新 variant が暗黙裏に SPAWN_FAILED_NO_ROLLBACK に化けていた)。
    """
    match result:
        case SpawnResult.SUCCESS | SpawnResult.OK_EARLY_EXIT:
            return LauncherExitCode.OK
        case SpawnResult.CRASH | SpawnResult.OS_ERROR:
            return LauncherExitCode.SPAWN_FAILED_NO_ROLLBACK
        case _ as unreachable:
            assert_never(unreachable)


def run_update(  # noqa: PLR0911 — explicit exit code mapping
    manifest_url: str,
    home_dir: Path,
    current_path: Path,
    *,
    no_spawn: bool,
    monitor_timeout_sec: float,
) -> LauncherExitCode:
    """update mode の主処理 (PR-4 / PR-6a / PR-6 後半)。

    Flow:
        1. lock 取得 (多重起動排他) + heartbeat
        2. manifest fetch + validate
        3. current.json 読み (strict_read=True で silent fallback 排除)
        4. preflight (現行版 binary 存在確認)
        5. update_and_spawn (download + signature/claims verify + switch + spawn + rollback)
        6. lock 解放 (finally)

    PR-6 後半: signature 検証は sigstore-python に委譲して default 有効。bypass 経路 +
    flag + env 完全削除、本番 PC + test 環境ともに同一 path で fail-closed。
    """
    if not manifest_url.startswith("https://"):
        logger.error("--manifest-url must use HTTPS scheme")
        return LauncherExitCode.CONFIG

    home_dir.mkdir(parents=True, exist_ok=True)
    lock_path = home_dir / "launcher.lock"

    try:
        lock_fd = acquire_lock(lock_path)
    except LockHeldError as e:
        logger.error("lock held: %s", e)
        return LauncherExitCode.LOCK_HELD

    # review_team A4 second-pass: heartbeat.start() の RuntimeError 等で lock fd が
    # leak しないよう、acquire 直後から release を保証する try/finally で全体を包む
    try:
        with LockHeartbeat(lock_path):
            try:
                raw = fetch_manifest(manifest_url)
                parsed = parse_manifest(raw)
                validated = validate_manifest(parsed)
            except ManifestError as e:
                logger.error("manifest error: %s", e)
                return LauncherExitCode.MANIFEST

            try:
                cur = read_current(current_path, strict_read=True)
            except CurrentReadError as e:
                logger.error("current.json read failed: %s", e)
                return LauncherExitCode.ROLLBACK_UNAVAILABLE

            versions_dir = home_dir / "versions"
            try:
                preflight(cur, versions_dir)
            except PreflightError as e:
                logger.error("preflight failed: %s", e)
                return LauncherExitCode.ROLLBACK_UNAVAILABLE

            try:
                outcome = update_and_spawn(
                    validated,
                    home_dir,
                    current_path=current_path,
                    monitor_timeout_sec=monitor_timeout_sec,
                    no_spawn=no_spawn,
                )
            except ChecksumError as e:
                logger.error("checksum mismatch: %s", e)
                return LauncherExitCode.CHECKSUM_MISMATCH
            except ProvenanceError as e:
                # PR-6 後半: signature 失敗 + claims 不一致 + canonical URL 違反を統合
                logger.error("provenance verification failed: %s", e)
                return LauncherExitCode.PROVENANCE
            except DownloadError:
                # Issue #212 I-1: logger.exception で __cause__ chain (HTTPError 503 /
                # TimeoutError / SSLError(CERTIFICATE_VERIFY_FAILED) 等) を traceback
                # に残し triage 効率化。I-3: LauncherExitCode.ARTIFACT (10) で manifest と分離。
                logger.exception("download error")
                return LauncherExitCode.ARTIFACT
            # C10 (silent-failure / type-design): canonical URL validation の ValueError は
            # updater.py で ProvenanceError に wrap 済。ここで except ValueError を持つと
            # Current invariant / SpawnOutcome invariant 違反 (= coding bug) も
            # LauncherExitCode.PROVENANCE に化けるので持たない (top-level safety net で LauncherExitCode.UNEXPECTED)
            except PreflightError as e:
                logger.error("preflight failed during update: %s", e)
                return LauncherExitCode.ROLLBACK_UNAVAILABLE
            except SpawnFailedNoRollbackError as e:
                logger.error("spawn failed and rollback failed: %s", e)
                return LauncherExitCode.SPAWN_FAILED_NO_ROLLBACK

            return _spawn_outcome_to_exit(outcome.result)
    finally:
        release_lock(lock_fd, lock_path)


def main(
    argv: list[str] | None = None,
) -> LauncherExitCode:  # noqa: PLR0911 — top-level dispatch
    parser = _build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    home_dir: Path = args.home
    current_path: Path = args.current_path or (home_dir / "current.json")

    if args.smoke_test and (args.dry_run or args.update):
        logger.error("--smoke-test cannot be combined with --dry-run / --update")
        return LauncherExitCode.CONFIG
    if args.dry_run and args.update:
        logger.error("--dry-run and --update are mutually exclusive")
        return LauncherExitCode.CONFIG
    if args.no_spawn and not args.update:
        logger.error("--no-spawn requires --update")
        return LauncherExitCode.CONFIG

    if args.smoke_test:
        try:
            return run_smoke_test()
        except Exception:  # noqa: BLE001 — top-level safety net
            logger.exception("unexpected error in smoke-test")
            return LauncherExitCode.UNEXPECTED

    if args.dry_run:
        try:
            return run_dry_run(args.manifest_url, current_path, verbose=args.verbose)
        except Exception:  # noqa: BLE001 — top-level safety net
            logger.exception("unexpected error in dry-run")
            return LauncherExitCode.UNEXPECTED

    if args.update:
        try:
            return run_update(
                args.manifest_url,
                home_dir,
                current_path,
                no_spawn=args.no_spawn,
                monitor_timeout_sec=args.monitor_timeout,
            )
        except Exception:  # noqa: BLE001 — top-level safety net
            logger.exception("unexpected error in update")
            return LauncherExitCode.UNEXPECTED

    logger.error("no mode specified. use --dry-run or --update (see --help for full options).")
    return LauncherExitCode.CONFIG


if __name__ == "__main__":
    raise SystemExit(main())
