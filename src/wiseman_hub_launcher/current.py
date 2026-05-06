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

from .manifest import is_simple_semver

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Current:
    """現在 active なバージョン情報。

    PR-4 で `previous_version` 追加（rollback 先特定用、初期値 ""）。
    `version` と `previous_version` は semver 形式 ("X.Y.Z") を要求する
    （read_current で検証、不正なら quarantine）。
    """

    version: str
    released_at: str
    previous_version: str = ""


DEFAULT_CURRENT = Current(version="0.0.0", released_at="", previous_version="")
"""初回起動時 / 破損時の fallback。

version="0.0.0" は manifest semver 比較で常に小さくなるため
manifest 側の current_version > 0.0.0 で必ず update 候補になる。
previous_version="" は「rollback 先なし」を明示（初回 update では rollback 不能）。
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


def read_current(
    path: Path,
    *,
    quarantine_corrupt: bool = True,
    verbose: bool = False,
) -> Current:
    """current.json を読む。破損時は退避 + DEFAULT_CURRENT 返却。

    fail-fast はしない（launcher は起動を止めない方針）。すべて warning ログのみ。

    Args:
        path: current.json のパス
        quarantine_corrupt: True なら破損ファイルを ``.corrupt-{ts}-{pid}-{rand}``
            にリネーム退避。False なら退避せず warn のみ（I-3: dry-run 副作用ゼロ用）
        verbose: True なら full path をログ表示。False なら machine-specific path を
            隠蔽し、汎用 message のみ（I-5: PII / privacy 配慮）
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
        logger.warning("current.json read error: %s", type(e).__name__)
        return DEFAULT_CURRENT

    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        reason = f"json-decode-{type(e).__name__}"
        if quarantine_corrupt:
            _quarantine_corrupt(path, reason)
        else:
            logger.warning("current.json corrupt (%s), not quarantined (dry-run)", reason)
        return DEFAULT_CURRENT

    if not isinstance(parsed, dict):
        if quarantine_corrupt:
            _quarantine_corrupt(path, "not-a-dict")
        else:
            logger.warning("current.json not-a-dict, not quarantined (dry-run)")
        return DEFAULT_CURRENT

    version = parsed.get("version")
    released_at = parsed.get("released_at")
    # PR-4: previous_version は任意 field（PR-3 形式との後方互換、欠落時 ""）
    previous_version = parsed.get("previous_version", "")

    if (
        not isinstance(version, str)
        or not isinstance(released_at, str)
        or not isinstance(previous_version, str)
    ):
        if quarantine_corrupt:
            _quarantine_corrupt(path, "schema-mismatch")
        else:
            logger.warning("current.json schema-mismatch, not quarantined (dry-run)")
        return DEFAULT_CURRENT

    # PR-4: semver 検証 (Suggestion 1 反映、rollback 先誤記の早期検知)
    if not is_simple_semver(version):
        if quarantine_corrupt:
            _quarantine_corrupt(path, "version-not-semver")
        else:
            logger.warning("current.json version not semver, not quarantined (dry-run)")
        return DEFAULT_CURRENT

    # previous_version は "" (rollback 先なし) または semver
    if previous_version != "" and not is_simple_semver(previous_version):
        if quarantine_corrupt:
            _quarantine_corrupt(path, "previous-version-not-semver")
        else:
            logger.warning(
                "current.json previous_version not semver, not quarantined (dry-run)"
            )
        return DEFAULT_CURRENT

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
        3. os.replace で target を差替（同一 FS で atomic 保証）
        4. 親ディレクトリを fsync（POSIX rename 永続化、Windows では no-op だがエラーにしない）

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
        os.replace(tmp_path, path)
        success = True
    finally:
        if not success:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError as e:
                logger.warning("failed to clean up tmp file: %s", type(e).__name__)

    # 親ディレクトリ fsync (POSIX のみ意味あり、Windows では PermissionError 等で no-op)
    try:
        dir_fd = os.open(str(parent), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        # Windows では directory fsync 不可、無視
        pass
    finally:
        os.close(dir_fd)
