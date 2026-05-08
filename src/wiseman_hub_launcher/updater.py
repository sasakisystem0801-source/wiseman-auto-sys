"""updater.py — orchestration: preflight + update_and_spawn + rollback (ADR-016 PR-4 → PR-6a)。

PR-6a で `_runtime/` と `_supply_chain/` に責務分割 (codex review threadId 019dfd9e
Critical C-3 反映)。本 module は orchestration のみで constituent operations は
subpackage を import する。

設計判断 (PR-4 codex review threadId 019dfd43 / 019dfd5d、PR-6a 019dfd9e 反映):
    - returncode != 0 のみ rollback、returncode == 0 早期終了は OK_EARLY_EXIT (D2')
    - download size cap = 300 MiB (`_supply_chain.download` 内)
    - lock file は run_update が acquire/release (`_runtime.lock`)
    - PR-6 後半で provenance signature 検証本実装、`--allow-test-unsigned-provenance`
      除去
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TypeAlias

from ._runtime import (
    DEFAULT_SPAWN_MONITOR_SEC,
    LOCK_HEARTBEAT_SEC,
    LOCK_STALE_SEC,
    LockHeartbeat,
    LockHeldError,
    SpawnFailedNoRollbackError,
    SpawnOutcome,
    SpawnResult,
    acquire_lock,
    release_lock,
    spawn_with_monitor,
)
from ._supply_chain import (
    MAX_ARTIFACT_BYTES,
    RELEASE_BUCKET_BASE,
    DownloadError,
    ProvenanceError,
    download_artifact,
    download_provenance,
    validate_canonical_provenance_url,
    verify_provenance,
)
from .checksum import ChecksumError, verify_sha256
from .current import DEFAULT_CURRENT, Current, read_current, write_current_atomic
from .manifest import ManifestData, Sha256Hex, is_simple_semver

logger = logging.getLogger(__name__)

# Issue #212 I-4 (review type-design C1): JSON 互換 scalar 型の単一ソース。
# _coerce_log_value の戻り値を narrow し、log analytics filter (e.g. `error_count > 3`)
# で int/float/bool が機能する scalar を type 上で表現する。
LogScalar: TypeAlias = str | int | float | bool | None


class UpdaterError(Exception):
    """updater 経路の base exception (PR-6a で他例外は subpackage に移動)。"""


def _coerce_log_value(v: object) -> LogScalar:
    """log payload field 値の type 保持 / str 化 (Issue #212 I-4 反映)。

    JSON serializable な scalar (str / int / float / bool / None) はそのまま、
    その他 (Path / dataclass / Exception 等) のみ str() 化する。
    旧仕様の全 field str() 化では log analytics filter (e.g. ``error_count > 3``)
    が機能しなくなる silent-failure があったため、scalar 型を保持する。

    Note: ``bool`` は ``int`` の subclass なので isinstance(True, int) は True。
    bool 値は int として match されるが、戻り値は元の bool object (identity 保持)
    なので JSON では ``true`` / ``false`` literal で出力される (review type-design C2)。
    """
    if isinstance(v, (str, int, float)) or v is None:
        return v
    return str(v)


def _phase_log(phase: str, **fields: object) -> None:
    """update_and_spawn 各 phase で構造化 JSON 1 行 log を出す (PR-7 AC5)。

    silent-failure 残対応: 失敗時の triage で「どこで止まったか」を機械可読化。
    Issue #212 I-4: scalar 型 (int/float/bool/None) は保持して log analytics 可能化。
    """
    payload = {"phase": phase, **{k: _coerce_log_value(v) for k, v in fields.items()}}
    logger.info("launcher_phase %s", json.dumps(payload, ensure_ascii=False))


class PreflightError(UpdaterError):
    """C-4: 初期配置不完全 / rollback 不能 (versions/X.Y.Z/ 不在等)。"""


# Re-export for backward compatibility with PR-3 / PR-4 / PR-5 imports
# (PR-6a で module 分割、既存テストと外部 import の互換維持。
# 将来削除予定だが PR-6a スコープ外、別 PR で deprecation warning + 削除)
__all__ = [
    "DEFAULT_SPAWN_MONITOR_SEC",
    "LOCK_HEARTBEAT_SEC",
    "LOCK_STALE_SEC",
    "MAX_ARTIFACT_BYTES",
    "RELEASE_BUCKET_BASE",
    "ChecksumError",
    "Current",
    "DEFAULT_CURRENT",
    "DownloadError",
    "LockHeartbeat",
    "LockHeldError",
    "PreflightError",
    "ProvenanceError",
    "SpawnFailedNoRollbackError",
    "SpawnOutcome",
    "SpawnResult",
    "UpdaterError",
    "acquire_lock",
    "download_artifact",
    "download_provenance",
    "is_simple_semver",
    "preflight",
    "read_current",
    "release_lock",
    "rollback_to_previous",
    "spawn_with_monitor",
    "update_and_spawn",
    "validate_canonical_provenance_url",
    "verify_provenance",
    "verify_sha256",
    "write_current_atomic",
]


# C-4: preflight ---------------------------------------------------------------


def preflight(current: Current, versions_dir: Path) -> None:
    """C-4: 業務継続可能性の事前確認。

    1. current.version が DEFAULT_CURRENT.version ("0.0.0") = 初期値
       → rollback 不能を WARN ログするが raise はしない (初回 update 自体は許可)
    2. それ以外で versions/{current.version}/wiseman_hub.exe が不在
       → PreflightError raise (caller で exit 6 ROLLBACK_UNAVAILABLE)

    seed runbook 反映は ADR-016 §2.2 (PR-5 改訂タスク、本 PR では runbook 改訂なし)。
    """
    if current.version == DEFAULT_CURRENT.version:
        logger.warning(
            "current.version is initial (%s): rollback unavailable for first update",
            DEFAULT_CURRENT.version,
        )
        return

    expected = versions_dir / current.version / "wiseman_hub.exe"
    if not expected.is_file():
        raise PreflightError(
            f"current binary missing: versions/{current.version}/wiseman_hub.exe"
        )


# Rollback ---------------------------------------------------------------------


def rollback_to_previous(
    current_path: Path,
    versions_dir: Path,
    *,
    monitor_timeout_sec: float = DEFAULT_SPAWN_MONITOR_SEC,
) -> SpawnOutcome:
    """current.json の previous_version で旧版 spawn。

    手順:
        1. current.json を読む
        2. previous_version が "" / non-semver → PreflightError (caller で exit 6)
        3. versions/{previous_version}/wiseman_hub.exe 不在 → PreflightError
        4. current.json を {version: previous_version, previous_version: "", ...} に
           atomic write (履歴は 1 段保持なので前々版は失念)
        5. spawn_with_monitor で旧版起動

    Returns:
        旧版起動の SpawnOutcome (caller は SUCCESS/OK_EARLY_EXIT → exit 0、
        CRASH/OS_ERROR → exit 7)。
    """
    cur = read_current(current_path)
    prev_ver = cur.previous_version
    if not prev_ver or not is_simple_semver(prev_ver):
        raise PreflightError(
            f"rollback unavailable: previous_version={prev_ver!r}"
        )

    prev_binary = versions_dir / prev_ver / "wiseman_hub.exe"
    if not prev_binary.is_file():
        raise PreflightError(
            f"rollback unavailable: versions/{prev_ver}/wiseman_hub.exe not found"
        )

    new_current = Current(
        version=prev_ver,
        released_at=cur.released_at,
        previous_version="",
    )
    write_current_atomic(current_path, new_current)
    logger.info("rolled back current.json to version=%s", prev_ver)

    return spawn_with_monitor(prev_binary, monitor_timeout_sec=monitor_timeout_sec)


# Main flow --------------------------------------------------------------------


def _download_with_provenance(
    manifest: ManifestData,
    new_dir: Path,
) -> tuple[Path, Path]:
    """artifact + provenance を download し canonical URL 検証 + verify_provenance。

    PR-6 後半: signature 検証本実装 (sigstore-python 委譲)。bypass 経路完全削除。

    Args:
        manifest: validate_manifest 通過後の ManifestData (PR-7 で TypedDict 化)
        new_dir: 新版 artifact の配置 dir

    Returns:
        (artifact_path, provenance_path)

    Raises:
        DownloadError / ChecksumError / ProvenanceError
    """
    download_url = manifest["download_url"]
    # Issue #209 PR1: ManifestData["checksum_sha256"] は Sha256Hex NewType として narrow 済。
    # 局所変数も Sha256Hex で受けることで、PR2 で download_artifact / verify_provenance の
    # signature を Sha256Hex に切り替えた際の type propagation が痛みなく成立する。
    checksum: Sha256Hex = manifest["checksum_sha256"]
    provenance_url_rel = manifest["provenance_url"]
    expected_version = manifest["current_version"]

    artifact_url = RELEASE_BUCKET_BASE + download_url
    provenance_url = RELEASE_BUCKET_BASE + provenance_url_rel
    # C-1: manifest 由来の provenance_url が canonical derived URL と一致必須。
    # C10 (silent-failure / type-design): policy.py が ValueError raise するのを
    # ProvenanceError 階層に統合 (Current invariant 等の他 ValueError と混同回避)
    try:
        validate_canonical_provenance_url(provenance_url, artifact_url)
    except ValueError as e:
        raise ProvenanceError(f"canonical provenance URL validation failed: {e}") from e

    artifact_path = download_artifact(artifact_url, new_dir, checksum, timeout_sec=60)
    provenance_path = download_provenance(provenance_url, new_dir, timeout_sec=30)

    # PR-6 後半: signature + claims 二段検証 (sigstore.verify_dsse + verify_statement_claims)
    verify_provenance(
        artifact_path,
        provenance_path,
        expected_sha256=checksum,
        expected_version=expected_version,
    )
    return artifact_path, provenance_path


def update_and_spawn(
    manifest: ManifestData,
    home_dir: Path,
    *,
    current_path: Path | None = None,
    monitor_timeout_sec: float = DEFAULT_SPAWN_MONITOR_SEC,
    no_spawn: bool = False,
) -> SpawnOutcome:
    """主フロー: manifest から決まる新版を download → verify → switch → spawn → rollback。

    PR-6 後半: bypass 経路完全削除、signature 検証本実装 (sigstore-python 委譲)。

    Args:
        manifest: validate_manifest 通過後の ManifestData (PR-7 で TypedDict 化、
            PR-6a 拡張 schema 含む)
        home_dir: $HOME/wiseman-hub (versions/ ディレクトリの親)。
            lock file は本関数では扱わない (caller の run_update が acquire/release)
        current_path: current.json の path 上書き (canary/test override で
            preflight と update が別 file を見る不整合を防ぐ)。
            None なら ``home_dir / "current.json"``
        monitor_timeout_sec: spawn_with_monitor の timeout (test では小さい値)
        no_spawn: True なら download + current.json 切替まで、spawn しない (AC-6)

    Returns:
        最終的な SpawnOutcome (no_spawn=True の場合は SUCCESS sentinel)

    Raises:
        DownloadError / ChecksumError / PreflightError / SpawnFailedNoRollbackError
        ProvenanceError (signature 検証失敗 + claims 不一致 を共に含む)
    """
    if current_path is None:
        current_path = home_dir / "current.json"
    versions_dir = home_dir / "versions"

    cur = read_current(current_path)

    new_ver = manifest["current_version"]
    released_at = manifest["released_at"]
    _phase_log("read_current", current_version=cur.version, target_version=new_ver)

    if cur.version == new_ver:
        logger.info("already at version %s, skipping download", new_ver)
        _phase_log("already_up_to_date", version=new_ver)
        if no_spawn:
            return SpawnOutcome.success()
        existing = versions_dir / cur.version / "wiseman_hub.exe"
        if not existing.is_file():
            # PR-7 review C-2 反映: 失敗 phase fingerprint で triage 可能化
            _phase_log("preflight_existing_missing", version=cur.version, expected=existing.name)
            raise PreflightError(f"binary missing for current version: {existing.name}")
        return spawn_with_monitor(existing, monitor_timeout_sec=monitor_timeout_sec)

    new_dir = versions_dir / new_ver
    _phase_log("download_start", new_version=new_ver, dest=str(new_dir))
    try:
        new_binary, _provenance_path = _download_with_provenance(manifest, new_dir)
    except (DownloadError, ChecksumError, ProvenanceError) as e:
        # PR-7 review C-2 反映: download 経路の失敗 phase fingerprint
        # (DownloadError = network/size/IO、ChecksumError = SHA-256 mismatch、
        # ProvenanceError = signature 失敗 / claims 不一致 / canonical URL 違反)
        _phase_log(
            "download_failed",
            new_version=new_ver,
            error_class=type(e).__name__,
            message=str(e)[:200],
        )
        raise
    logger.info("downloaded version %s to %s", new_ver, new_binary.name)
    _phase_log("download_complete", new_version=new_ver)

    new_current = Current(
        version=new_ver,
        released_at=released_at,
        previous_version=cur.version if cur.version != DEFAULT_CURRENT.version else "",
    )
    try:
        write_current_atomic(current_path, new_current)
    except OSError as e:
        # PR-7 review C-2 反映: current.json 切替失敗 phase fingerprint
        # (ENOSPC / EROFS / FileNotFoundError 等。raise させて上位で EXIT_UNEXPECTED)
        _phase_log(
            "current_switch_failed",
            new_version=new_ver,
            error_class=type(e).__name__,
            errno=e.errno,
        )
        raise
    logger.info("switched current.json to version %s", new_ver)
    _phase_log("current_switched", new_version=new_ver, previous_version=cur.version)

    if no_spawn:
        # silent-failure HIGH 5 反映: download + 切替まで完了で spawn skip した事実を
        # 必ず log。caller の run_update も SUCCESS で exit 0 になるため、ログなしだと
        # 「実機の wiseman_hub.exe が起動したか / no-spawn で停止したか」区別不能
        logger.info(
            "no-spawn requested: download + current.json switch completed for version=%s, "
            "spawn intentionally skipped (caller will exit 0 without launching binary)",
            new_ver,
        )
        return SpawnOutcome.success()

    _phase_log("spawn_start", new_version=new_ver, binary=new_binary.name)
    outcome = spawn_with_monitor(new_binary, monitor_timeout_sec=monitor_timeout_sec)

    if not outcome.is_rollback_candidate():
        _phase_log("spawn_complete", new_version=new_ver, result=outcome.result.value)
        return outcome

    logger.warning("new version spawn failed (%s), rolling back", outcome.result.value)
    _phase_log("rollback_start", failed_version=new_ver, result=outcome.result.value)
    rollback_outcome = rollback_to_previous(
        current_path, versions_dir, monitor_timeout_sec=monitor_timeout_sec
    )
    if not rollback_outcome.is_rollback_candidate():
        # PR-7 review C-2 反映: rollback 成功 fingerprint
        _phase_log(
            "rollback_complete",
            failed_version=new_ver,
            rollback_result=rollback_outcome.result.value,
        )
        return rollback_outcome

    # PR-7 review C-2 反映: rollback も失敗した致命状態 fingerprint
    _phase_log(
        "rollback_failed",
        failed_version=new_ver,
        rollback_result=rollback_outcome.result.value,
        rollback_returncode=rollback_outcome.returncode,
    )
    raise SpawnFailedNoRollbackError(
        f"both new ({outcome.returncode}) and previous "
        f"({rollback_outcome.returncode}) versions failed to spawn"
    )


# verify_sha256 を re-export (既存 test との互換維持)
_ = verify_sha256
