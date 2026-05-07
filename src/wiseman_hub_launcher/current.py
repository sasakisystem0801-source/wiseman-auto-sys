"""current.json atomic read/write + 破損時退避 (ADR-016 PR-3 / PR-4)。

current.json schema (PR-4 で previous_version 追加):
    {
        "version": "1.2.3",                      (semver, 初期値 "0.0.0")
        "released_at": "2026-05-06T13:00:00Z",   (ISO8601 UTC, 初期値 "")
        "previous_version": "1.2.2"              (semver or "", PR-4 で追加。
                                                  rollback 先特定用、初期値 "")
    }

PR-3 形式（previous_version なし）との後方互換: 欠落時は default "" で読み取り、
schema mismatch / quarantine は発生しない (PR-4 codex Suggestion 1 反映)。

破損ハンドリング方針:
    - 存在しない → DEFAULT_CURRENT を返す（初回起動時を想定）
    - JSON 破損 / schema 不一致 / semver 不正 → ``.corrupt-{ts}`` に退避してから DEFAULT
    - すべて warning ログ（fatal にしない、launcher は起動を止めない）

strict_read=True (review_team A2 second-pass、silent-failure I6 反映):
    - 存在しない → DEFAULT_CURRENT (genuine first install を許容)
    - read OSError / JSON 破損 / schema 不一致 / semver 不正 → CurrentReadError raise
    - run_update は本フラグを使用、Windows AV 等の transient 失敗を「first install」と
      誤認して silent に rollback 不能化することを防止

atomic write 方針:
    - 同一ディレクトリに tempfile 作成 → fsync → os.replace
    - 親ディレクトリも fsync (POSIX rename の永続化)
    - Windows でも os.replace は atomic 保証

stdlib only 制約のため src/wiseman_hub/utils/atomic_io.py は import せず、
同等の構造を直接実装する（参考にしたが import はしない）。
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from ._runtime._atomic_io import atomic_replace_and_fsync_dir
from .manifest import is_simple_semver

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Current:
    """現在 active なバージョン情報。

    PR-4 で `previous_version` 追加（rollback 先特定用、初期値 ""）。
    PR-6a (codex review_team type-design Important): __post_init__ で semver invariant
    を強制。read_current 経由でなく直接生成された場合も不正値を弾く。

    `version` と `previous_version` は semver 形式 ("X.Y.Z") を要求する。
    `previous_version` は "" (rollback 先なし) も許容。
    """

    version: str
    released_at: str
    previous_version: str = ""

    def __post_init__(self) -> None:
        # version は常に semver
        if not is_simple_semver(self.version):
            raise ValueError(
                f"Current.version must be semver, got {self.version!r}"
            )
        # previous_version は "" or semver
        if self.previous_version != "" and not is_simple_semver(self.previous_version):
            raise ValueError(
                f"Current.previous_version must be '' or semver, "
                f"got {self.previous_version!r}"
            )
        # released_at は str (空文字も許容、ISO8601 形式は read_current で検証)
        # 型アノテーションで str 強制済、追加検証なし


DEFAULT_CURRENT = Current(version="0.0.0", released_at="", previous_version="")
"""初回起動時 / 破損時の fallback。

version="0.0.0" は manifest semver 比較で常に小さくなるため
manifest 側の current_version > 0.0.0 で必ず update 候補になる。
previous_version="" は「rollback 先なし」を明示（初回 update では rollback 不能）。
"""


class CurrentReadError(Exception):
    """current.json の read 失敗 / 破損 / schema 不一致 (review_team A2 second-pass)。

    strict_read=True 時のみ raise。透過的な fallback (DEFAULT_CURRENT) で
    silent に rollback 能力を喪失するのを防止する。file 不在 (genuine first install)
    では raise しない。
    """


def _now_iso_utc_microsec() -> str:
    """ISO8601 UTC + microseconds（ファイル名 suffix 用、コロン除去、I-4 衝突回避）。"""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")


def _quarantine_corrupt(path: Path, reason: str) -> None:
    """破損 current.json を ``.corrupt-{ts}-{pid}-{rand}`` suffix にリネームして退避する。

    I-4 (codex review threadId 019dfce6) 反映:
        - 秒精度の timestamp は同一秒に複数 corrupt が走ると衝突するため、
          microseconds + pid + 4 桁 random suffix で衝突確率を実用上ゼロ化
    rename 失敗時はログのみ（read 側は DEFAULT に fallback するので致命ではない）。
    """
    ts = _now_iso_utc_microsec()
    rand = secrets.token_hex(2)
    pid = os.getpid()
    quarantine = path.with_suffix(f"{path.suffix}.corrupt-{ts}-{pid}-{rand}")
    try:
        os.replace(path, quarantine)
        logger.warning(
            "current.json quarantined to %s (reason: %s)",
            quarantine.name,
            reason,
        )
    except OSError as e:
        logger.warning(
            "failed to quarantine corrupt current.json (%s): %s",
            reason,
            type(e).__name__,
        )


def _fail_or_default(
    path: Path,
    reason: str,
    *,
    strict_read: bool,
    quarantine_corrupt: bool,
    dry_run_msg: str,
) -> Current:
    """破損 / 不正時の dispatcher。

    - strict_read=True: CurrentReadError raise (rollback 能力喪失を防止)
    - strict_read=False + quarantine_corrupt=True: 退避 + DEFAULT
    - strict_read=False + quarantine_corrupt=False: log warn のみ + DEFAULT (dry-run)
    """
    if strict_read:
        raise CurrentReadError(f"current.json {reason}")
    if quarantine_corrupt:
        _quarantine_corrupt(path, reason)
    else:
        logger.warning("current.json %s, not quarantined (dry-run)", dry_run_msg)
    return DEFAULT_CURRENT


def read_current(
    path: Path,
    *,
    quarantine_corrupt: bool = True,
    verbose: bool = False,
    strict_read: bool = False,
) -> Current:
    """current.json を読む。破損時は退避 + DEFAULT_CURRENT 返却 (strict_read=False)。

    Args:
        path: current.json のパス
        quarantine_corrupt: True なら破損ファイルを ``.corrupt-{ts}-{pid}-{rand}``
            にリネーム退避。False なら退避せず warn のみ（dry-run 副作用ゼロ用）
        verbose: True なら full path をログ表示。False なら machine-specific path を
            隠蔽し、汎用 message のみ（PII / privacy 配慮）
        strict_read: True なら read OSError / 破損 / schema 不一致で CurrentReadError
            raise (review_team A2 second-pass、silent-failure I6 反映)。file 不在は
            raise しない (genuine first install を許容)。run_update が使用、
            Windows AV 等の transient ロックを silent に「first install」と誤認させない

    Raises:
        CurrentReadError: strict_read=True 時の read 失敗 / 破損 / schema / semver 不正
    """
    if not path.exists():
        if verbose:
            logger.info("current.json not found at %s, using DEFAULT_CURRENT", path)
        else:
            logger.info("current.json not found, using DEFAULT_CURRENT")
        return DEFAULT_CURRENT

    try:
        raw = path.read_bytes()
    except OSError as e:
        if strict_read:
            raise CurrentReadError(
                f"current.json read error: {type(e).__name__}: "
                f"errno={e.errno} filename={e.filename!r}"
            ) from e
        logger.warning(
            "current.json read error: %s errno=%s", type(e).__name__, e.errno
        )
        return DEFAULT_CURRENT

    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        return _fail_or_default(
            path,
            f"json-decode-{type(e).__name__}",
            strict_read=strict_read,
            quarantine_corrupt=quarantine_corrupt,
            dry_run_msg=f"corrupt ({type(e).__name__})",
        )

    if not isinstance(parsed, dict):
        return _fail_or_default(
            path, "not-a-dict",
            strict_read=strict_read,
            quarantine_corrupt=quarantine_corrupt,
            dry_run_msg="not-a-dict",
        )

    version = parsed.get("version")
    released_at = parsed.get("released_at")
    previous_version = parsed.get("previous_version", "")  # PR-3 後方互換

    if (
        not isinstance(version, str)
        or not isinstance(released_at, str)
        or not isinstance(previous_version, str)
    ):
        return _fail_or_default(
            path, "schema-mismatch",
            strict_read=strict_read,
            quarantine_corrupt=quarantine_corrupt,
            dry_run_msg="schema-mismatch",
        )

    if not is_simple_semver(version):
        return _fail_or_default(
            path, "version-not-semver",
            strict_read=strict_read,
            quarantine_corrupt=quarantine_corrupt,
            dry_run_msg="version not semver",
        )

    if previous_version != "" and not is_simple_semver(previous_version):
        return _fail_or_default(
            path, "previous-version-not-semver",
            strict_read=strict_read,
            quarantine_corrupt=quarantine_corrupt,
            dry_run_msg="previous_version not semver",
        )

    return Current(
        version=version,
        released_at=released_at,
        previous_version=previous_version,
    )


def write_current_atomic(path: Path, current: Current) -> None:
    """current.json を atomic に書く。

    手順:
        1. 同ディレクトリに tempfile 作成
        2. JSON write → flush → fsync
        3. atomic_replace_and_fsync_dir で os.replace + 親 dir fsync を実施
           (`_runtime/_atomic_io.py` に共通化、PR-7 review I-3 反映で docstring 同期)。
           dir fsync は POSIX のみ意味あり、Windows では debug ログで suppress、
           POSIX では errno 付き warning ログで ENOSPC/EIO/EROFS を可視化。

    親ディレクトリは事前に存在している必要がある。
    """
    parent = path.parent
    if not parent.exists():
        raise FileNotFoundError(f"parent directory does not exist: {parent}")

    payload = json.dumps(asdict(current), ensure_ascii=False, indent=2).encode("utf-8")

    fd, tmp_name = tempfile.mkstemp(prefix=".current.", suffix=".tmp", dir=str(parent))
    os.close(fd)
    tmp_path = Path(tmp_name)
    success = False
    try:
        with open(tmp_path, "wb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        # atomic replace + 親 dir fsync を共通 helper に集約 (PR-7 タスク B)
        atomic_replace_and_fsync_dir(tmp_path, path, parent)
        success = True
    finally:
        if not success:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError as e:
                logger.warning("failed to clean up tmp file: %s", type(e).__name__)
