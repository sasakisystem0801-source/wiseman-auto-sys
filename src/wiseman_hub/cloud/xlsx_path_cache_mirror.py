"""xlsx_path_cache の GCS ミラー（ADR-016 Phase 3 PR-2）。

業務責任者 PC で確定した ``xlsx_path_cache``（``checklist.xlsx_path_cache``）の
TOML 内容を、key 単位で GCS にミラーする。目的:

    1. PC 入替・config 巻き戻し時の cache 復旧
    2. Mac dev 機からの cache 状態 read-only 確認

GCS object 配置:
    gs://{data_bucket}/cache/xlsx_path/{sha256(key)[:32]}.json

object schema (alive entry):
    {
        "key": "宮下:2026:3",
        "xlsx_path": "\\\\Tera-station\\share\\PT 宮下\\...",
        "generated_at": "2026-05-06T05:23:11.123456+00:00",
        "machine_id": "<UUIDv4>",
        "config_revision": "<generated_at>:<base_config_sha256[:12]>",
        "base_config_sha256": "<64 hex>"
    }

object schema (tombstone, 削除時):
    {
        "key": "宮下:2026:3",
        "deleted_at": "2026-05-06T05:30:00+00:00",
        "machine_id": "...",
        "config_revision": "...",
        "base_config_sha256": "..."
    }
    ※ ``xlsx_path`` フィールドが**欠如**することで tombstone 判別する
      （明示的な ``deleted: true`` フラグより schema 上の対称性が高い）。

設計判断:
    - **per-key per-object**: object name に key の hash を使うことで latest-state を
      mirror。key を path に直接含めると PII （担当者名）が GCS object 名に出るため
      hash 化（audit_uploader.py の content hash と同じ手口）
    - **mutable overwrite (no if_generation_match)**: cache の最新状態を mirror する
      用途のため、ローカルの確定値を覆い得る挙動が必要。冪等 retry も同名 object
      への上書きで自然収束
    - **tombstone**: GCS の「object 削除」ではなく「``deleted_at`` 付き JSON で上書き」
      にすることで、過去履歴（generation 経由）と削除事実を両立。Bucket lifecycle
      で後から物理削除可能
    - **machine_id**: hostname/HW ID の代わりに UUIDv4 を ``~/wiseman-hub/machine_id``
      に永続化（PII 配慮、ADR-016 PII 5 年保持と整合）。ファイル作成は
      ``open(..., "x")`` atomic create で並行 race 回避（codex I-2 反映）
    - **base_config_sha256**: save_config 後の TOML bytes 全体の hash。これにより
      「どの config 状態で書かれた entry か」を識別でき、巻き戻し時の差分検出が可能

並列 upload と整合性 (codex review threadId 019dfceb 反映):
    本モジュールは per-key per-object で異なる key は完全独立。**同一 key への
    並列 upload には順序保証なし**。GCS は last-writer-wins だが「最後に完了した
    upload」が勝つだけで「最後にユーザーが確定した操作」が勝つ保証ではない。
    例: PC A で delete tombstone を投げる→ PC B で alive 再 upload → B が先に完了
    し A が後で完了すると、ローカルは alive で GCS は tombstone になる。

    **復旧時の真実は local TOML (``xlsx_path_cache``) であり、GCS は monitor +
    recovery hint**。Mac CLI / 復旧スクリプトは GCS を無条件採用せず、
    ``base_config_sha256`` と local TOML を比較して stale mirror を検出すること。

    ローカル UI の write/delete hook 内では、cache write/delete は同一スレッド内で
    逐次呼ばれるため、単一 PC 内の race は無い（C-1 反映で daemon thread 化したが
    ThreadPoolExecutor max_workers=1 で順序維持する設計、UI 側で実装）。
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import logging
import threading
import uuid
from collections.abc import Callable
from pathlib import Path

from google.api_core import exceptions as gcs_exc
from google.cloud import storage

from wiseman_hub.config import GcpConfig

logger = logging.getLogger(__name__)

_OBJECT_PREFIX = "cache/xlsx_path"
_GCS_TIMEOUT_SEC = 30
_MACHINE_ID_PATH = Path.home() / "wiseman-hub" / "machine_id"


class XlsxPathCacheMirrorError(Exception):
    """GCS API / ネットワーク / 認証エラーを統合（呼出側は warn-only で扱う）。"""


def _str_or_empty(value: object) -> str:
    """value を安全に str 化（None / 非 str は空文字列に正規化、I-4 反映）。

    GcpConfig の field は dataclass で str 型注釈だが、TOML 経由 / dict 直渡し
    で None や非 str が混入し得るため `.strip()` AttributeError を防ぐ。
    """
    if isinstance(value, str):
        return value
    return ""


def _validate_gcp(gcp: GcpConfig) -> list[str]:
    """GcpConfig の必須項目を検証して missing field 名のリストを返す。

    audit_uploader._validate_gcp と異なり、本モジュールは「失敗しても warn-only」
    の運用のため、raise せず list を返す。呼出側が空 list なら proceed する。

    I-4 反映: None / 非 str 混入で AttributeError しないよう ``_str_or_empty`` 経由で
    防御。``GcpConfig()`` デフォルト・空文字・空 dict 直渡しすべて safe に no-op 判定。
    """
    missing: list[str] = []
    if not _str_or_empty(getattr(gcp, "project_id", None)).strip():
        missing.append("project_id")
    if not _str_or_empty(getattr(gcp, "effective_data_bucket", None)).strip():
        missing.append("data_bucket_name (or bucket_name)")
    sa_key_path = _str_or_empty(getattr(gcp, "service_account_key_path", None)).strip()
    if not sa_key_path:
        missing.append("service_account_key_path")
    elif not Path(sa_key_path).exists():
        missing.append("service_account_key_path (file not found)")
    return missing


def _client(gcp: GcpConfig) -> storage.Client:
    """GCS client factory（テストでは patch される）。"""
    return storage.Client.from_service_account_json(
        gcp.service_account_key_path, project=gcp.project_id
    )


def _validate_uuid_str(s: str) -> bool:
    """文字列が UUIDv4 として parse 可能か判定 (I-3 反映)。"""
    try:
        uuid.UUID(s)
    except (ValueError, TypeError, AttributeError):
        return False
    return True


def _quarantine_invalid_machine_id(reason: str) -> None:
    """不正な machine_id ファイルを ``.invalid-{ts}`` 退避する (I-3 反映)。

    rename 失敗は warn のみ（regenerate 経路で同名 file を上書きするため致命ではない）。
    """
    ts = _dt.datetime.now(tz=_dt.UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    backup = _MACHINE_ID_PATH.with_name(_MACHINE_ID_PATH.name + f".invalid-{ts}")
    try:
        _MACHINE_ID_PATH.rename(backup)
        logger.warning(
            "machine_id quarantined (reason=%s) -> %s",
            reason,
            backup.name,
        )
    except OSError as exc:
        logger.warning(
            "machine_id quarantine failed (reason=%s, type=%s)",
            reason,
            type(exc).__name__,
        )


def get_or_create_machine_id() -> str:
    """``~/wiseman-hub/machine_id`` から machine_id を読み出し、なければ UUIDv4 を生成。

    冪等: 同一 PC で複数回呼ばれても同じ ID が返る（再起動間で安定）。

    並行 race 回避 (I-2 反映):
        ``open(path, "x")`` で atomic create する。既存ファイルがあれば
        FileExistsError を catch して reread することで、2 process 同時起動でも
        どちらかの UUID に collapse する。

    形式検証 (I-3 反映):
        既存ファイルの内容が UUIDv4 として parse 不能なら ``.invalid-{ts}`` 退避
        + 新規生成。空文字も同様。

    読み取り / 書き込み失敗時は ephemeral UUID を返し、warn ログを残す（運用継続優先）。

    PII 配慮:
        hostname / MAC アドレス / Windows machine GUID は使わず、必ず UUIDv4 を
        新規生成する（ADR-016 PII 5 年保持と整合）。
    """
    try:
        # 既存読込
        if _MACHINE_ID_PATH.exists():
            content = _MACHINE_ID_PATH.read_text(encoding="utf-8").strip()
            if content and _validate_uuid_str(content):
                return content
            # 不正 / 空 → 退避 + regenerate
            reason = "empty" if not content else "invalid-uuid-format"
            _quarantine_invalid_machine_id(reason)

        # 新規生成 + atomic create (FileExistsError で並行 race 解決)
        _MACHINE_ID_PATH.parent.mkdir(parents=True, exist_ok=True)
        new_id = str(uuid.uuid4())
        try:
            with open(_MACHINE_ID_PATH, "x", encoding="utf-8") as f:
                f.write(new_id + "\n")
            return new_id
        except FileExistsError:
            # 並行 process が先に作った → reread して collapse
            content = _MACHINE_ID_PATH.read_text(encoding="utf-8").strip()
            if content and _validate_uuid_str(content):
                return content
            # reread しても不正 → ephemeral fallback
            logger.warning(
                "machine_id concurrent create succeeded but content invalid; "
                "using ephemeral UUID for this session"
            )
            return str(uuid.uuid4())
    except OSError as exc:
        # 書き込み失敗 → ephemeral UUID を返す（次回起動時に再試行）
        logger.warning(
            "machine_id read/write failed (errno=%s, type=%s); using ephemeral UUID",
            getattr(exc, "errno", "n/a"),
            type(exc).__name__,
        )
        return str(uuid.uuid4())


def compute_base_config_sha256(config_path: Path) -> str:
    """``config_path`` の bytes 全体の SHA-256 hex（64 文字）を計算する。

    決定性:
        同一 file bytes に対して常に同じ hash を返す。改行コードや空白の違いも
        bytes 比較で反映される（TOML の論理同一は反映しない）。

    エラー時は空文字列を返す（呼出側で空判定可能）。
    """
    try:
        data = config_path.read_bytes()
    except OSError as exc:
        logger.warning(
            "config bytes read failed for sha256: %s (errno=%s, type=%s)",
            config_path.name,
            getattr(exc, "errno", "n/a"),
            type(exc).__name__,
        )
        return ""
    return hashlib.sha256(data).hexdigest()


def make_config_revision(generated_at: str, base_sha: str) -> str:
    """``{generated_at}:{base_config_sha256[:12]}`` の形式で revision 文字列を構築。

    base_sha が空文字列の場合は ``{generated_at}:`` で終端する（hash 失敗時の
    識別子として generated_at が機能、巻き戻し検出は劣化）。
    """
    return f"{generated_at}:{base_sha[:12]}"


def object_name_for(key: str) -> str:
    """key（``staff:year:month``）から GCS object 名を導出する。

    PII 配慮で key の生値は object 名に含めない（SHA-256 先頭 32 hex のみ）。
    32 hex = 128 bit で実用上衝突なし（audit_uploader と同じ方針）。
    """
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
    return f"{_OBJECT_PREFIX}/{digest}.json"


def _now_utc_iso() -> str:
    """UTC ISO8601 文字列（``+00:00`` 表記、microsecond 含む）を返す。"""
    return _dt.datetime.now(tz=_dt.UTC).isoformat()


def _build_alive_payload(
    key: str,
    xlsx_path: str,
    config_path: Path,
) -> dict[str, str]:
    """alive entry の payload dict を組み立てる。"""
    generated_at = _now_utc_iso()
    base_sha = compute_base_config_sha256(config_path)
    return {
        "key": key,
        "xlsx_path": xlsx_path,
        "generated_at": generated_at,
        "machine_id": get_or_create_machine_id(),
        "config_revision": make_config_revision(generated_at, base_sha),
        "base_config_sha256": base_sha,
    }


def _build_tombstone_payload(key: str, config_path: Path) -> dict[str, str]:
    """tombstone payload を組み立てる（``xlsx_path`` 欠如で削除判別）。"""
    deleted_at = _now_utc_iso()
    base_sha = compute_base_config_sha256(config_path)
    return {
        "key": key,
        "deleted_at": deleted_at,
        "machine_id": get_or_create_machine_id(),
        "config_revision": make_config_revision(deleted_at, base_sha),
        "base_config_sha256": base_sha,
    }


def _upload_payload(
    gcp: GcpConfig,
    key: str,
    payload: dict[str, str],
    *,
    client: storage.Client | None,
) -> bool:
    """payload を GCS にアップロード（mutable overwrite）。

    Returns:
        True = upload 成功、False = GCP 設定不足 / API エラー（warn-only）
    """
    missing = _validate_gcp(gcp)
    if missing:
        logger.warning(
            "xlsx_path_cache mirror skipped (gcp config missing): %s",
            ", ".join(missing),
        )
        return False

    obj_name = object_name_for(key)
    try:
        cli = client or _client(gcp)
        bucket = cli.bucket(gcp.effective_data_bucket)
        blob = bucket.blob(obj_name)
        # mutable overwrite (no if_generation_match)
        # 設計理由: latest-state mirror のため、ローカル確定値で常に上書きする。
        # 並列 upload race は GCS の last-writer-wins で自然解決。
        body = json.dumps(payload, ensure_ascii=False, indent=2)
        blob.upload_from_string(
            body,
            content_type="application/json; charset=utf-8",
            timeout=_GCS_TIMEOUT_SEC,
        )
        return True
    except (gcs_exc.GoogleAPIError, OSError) as exc:
        logger.warning(
            "xlsx_path_cache mirror upload failed: object=%s, type=%s",
            obj_name,
            type(exc).__name__,
        )
        return False


def upload_entry(
    key: str,
    xlsx_path: str,
    gcp: GcpConfig,
    *,
    config_path: Path,
    client: storage.Client | None = None,
) -> bool:
    """alive entry を GCS にミラー。

    Args:
        key: ``"{staff}:{year}:{month}"`` 形式（cache_key()）
        xlsx_path: 確定済の xlsx 絶対パス（UNC 等）
        gcp: GCP 接続設定。未設定（bucket 等空）なら no-op で warn ログのみ
        config_path: save_config() 直後の TOML パス（base_config_sha256 計算用）
        client: テスト用 mock client

    Returns:
        True = upload 成功、False = 設定不足 / API エラー
    """
    payload = _build_alive_payload(key, xlsx_path, config_path)
    return _upload_payload(gcp, key, payload, client=client)


def delete_entry(
    key: str,
    gcp: GcpConfig,
    *,
    config_path: Path,
    client: storage.Client | None = None,
) -> bool:
    """tombstone を GCS にミラー（``xlsx_path`` 欠如、``deleted_at`` 付き）。

    GCS object 自体は削除せず、tombstone JSON で上書きする。これにより:
        - 過去 generation 経由で履歴参照可能
        - bucket lifecycle で N 日後に物理削除する運用が可能
        - Mac CLI の ``--include-deleted`` で監査可能

    復旧時の重要な制約 (codex review I-5 反映):
        delete は「local TOML 保存後 → tombstone を GCS に投げる」順序であり、
        mirror が warn-only で失敗しても TOML 永続化は成功している。よって:

        - **local TOML が真実、GCS は monitor + recovery hint** として扱う
        - 復旧時、GCS で alive entry が見つかっても **無条件採用してはいけない**:
          local TOML に同 key が無ければ既に削除済（GCS が古い alive を保持）
        - ``base_config_sha256`` を local TOML と比較し、差分があれば stale mirror
          として扱う（write-back 復元 PR で実装予定）

    Returns:
        True = upload 成功、False = 設定不足 / API エラー
    """
    payload = _build_tombstone_payload(key, config_path)
    return _upload_payload(gcp, key, payload, client=client)


def fetch_one(
    key: str,
    gcp: GcpConfig,
    *,
    client: storage.Client | None = None,
) -> dict[str, str] | None:
    """単一 key の entry を GCS から取得。

    Returns:
        存在 + JSON parse 成功なら dict（alive / tombstone どちらも）。
        存在しない / GCP 設定不足 / API エラーなら None。

    呼出側は ``"xlsx_path"`` キーの有無で alive / tombstone を判別する。
    """
    missing = _validate_gcp(gcp)
    if missing:
        logger.warning(
            "xlsx_path_cache fetch skipped (gcp config missing): %s",
            ", ".join(missing),
        )
        return None
    obj_name = object_name_for(key)
    try:
        cli = client or _client(gcp)
        bucket = cli.bucket(gcp.effective_data_bucket)
        blob = bucket.blob(obj_name)
        if not blob.exists(timeout=_GCS_TIMEOUT_SEC):
            return None
        data = blob.download_as_bytes(timeout=_GCS_TIMEOUT_SEC)
    except (gcs_exc.GoogleAPIError, OSError) as exc:
        logger.warning(
            "xlsx_path_cache fetch_one failed: object=%s, type=%s",
            obj_name,
            type(exc).__name__,
        )
        return None
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        logger.warning(
            "xlsx_path_cache fetch_one parse failed: object=%s, type=%s",
            obj_name,
            type(exc).__name__,
        )
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


# C-1 反映: UI thread から呼ばれる write/delete hook を非同期化。
# Tk UI thread を 30 秒 timeout でブロックすると現場運用が破綻するため、
# daemon thread に upload/delete を投げ、UI 側は即時継続する。
# warn-only 仕様のため worker 内で全例外を catch、UI に messagebox を出さない。


def _async_run(
    target_label: str,
    fn: Callable[..., object],
    *args: object,
    **kwargs: object,
) -> threading.Thread:
    """fn を daemon thread で起動し、例外は warn ログに吸収する (C-1)。"""

    def _worker() -> None:
        try:
            fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 — worker 内吸収必須
            logger.warning(
                "xlsx_path_cache mirror async %s failed (non-fatal): %s",
                target_label,
                type(exc).__name__,
            )

    t = threading.Thread(
        target=_worker,
        name=f"xlsx-path-cache-mirror-{target_label}",
        daemon=True,
    )
    t.start()
    return t


def upload_entry_async(
    key: str,
    xlsx_path: str,
    gcp: GcpConfig,
    *,
    config_path: Path,
    client: storage.Client | None = None,
) -> threading.Thread:
    """C-1: ``upload_entry`` を daemon thread で実行（UI thread を blocking しない）。

    Returns:
        起動された Thread オブジェクト（呼出側はテスト時に join 可能）。
        通常運用では呼出側が結果を待つ必要はない（warn-only）。

    上位の write/delete hook 配置点（ui/checklist_c_dialog.py）から本 async 版を
    呼ぶことで、GCP 遅延 / 認証詰まり / ネット不調による Tk UI freeze を回避する。
    """
    return _async_run(
        "upload",
        upload_entry,
        key,
        xlsx_path,
        gcp,
        config_path=config_path,
        client=client,
    )


def delete_entry_async(
    key: str,
    gcp: GcpConfig,
    *,
    config_path: Path,
    client: storage.Client | None = None,
) -> threading.Thread:
    """C-1: ``delete_entry`` を daemon thread で実行（UI thread を blocking しない）。

    Returns:
        起動された Thread オブジェクト（呼出側はテスト時に join 可能）。
    """
    return _async_run(
        "delete",
        delete_entry,
        key,
        gcp,
        config_path=config_path,
        client=client,
    )


def fetch_all(
    gcp: GcpConfig,
    *,
    client: storage.Client | None = None,
) -> list[dict[str, str]]:
    """``cache/xlsx_path/`` 配下の全 entry を取得（alive + tombstone）。

    Returns:
        各 entry の dict（パース成功分のみ）。alive / tombstone は呼出側で
        ``"xlsx_path"`` キーの有無で判別する。GCP 設定不足 / API エラー時は空 list。

    並列 upload の race:
        本関数は read-only で副作用なし。list_blobs と download の間に
        別 PC が upload しても snapshot として取得される（古い generation を
        読む可能性はあるが、Mac CLI 用途では許容）。

    Note (codex I-1 反映): エラー伝播が必要な CLI 用途では
    ``fetch_all_with_errors()`` を使うこと。本関数は warn-only fallback で
    空 list を返すため、CLI exit code を network 失敗で 3 にするには errors を
    別に取得する必要がある。
    """
    entries, _errors = fetch_all_with_errors(gcp, client=client)
    return entries


def fetch_all_with_errors(
    gcp: GcpConfig,
    *,
    client: storage.Client | None = None,
) -> tuple[list[dict[str, str]], list[Exception]]:
    """``cache/xlsx_path/`` 配下の全 entry を取得し、エラーも併せて返す (I-1)。

    Returns:
        (entries, errors) のタプル:
            - entries: パース成功した entry の list
            - errors: download / parse / list_blobs で発生した例外のリスト

    呼出側 (Mac CLI など) は errors の非空を検知して exit code を区別できる。
    GCP 設定不足は errors に ``XlsxPathCacheMirrorError`` を入れて返す。
    """
    errors: list[Exception] = []
    missing = _validate_gcp(gcp)
    if missing:
        msg = "gcp config missing: " + ", ".join(missing)
        logger.warning("xlsx_path_cache fetch_all skipped (%s)", msg)
        errors.append(XlsxPathCacheMirrorError(msg))
        return ([], errors)

    results: list[dict[str, str]] = []
    try:
        cli = client or _client(gcp)
        bucket = cli.bucket(gcp.effective_data_bucket)
        # prefix 指定で `cache/xlsx_path/` 配下のみ
        for blob in cli.list_blobs(
            bucket, prefix=_OBJECT_PREFIX + "/", timeout=_GCS_TIMEOUT_SEC
        ):
            try:
                data = blob.download_as_bytes(timeout=_GCS_TIMEOUT_SEC)
            except (gcs_exc.GoogleAPIError, OSError) as exc:
                logger.warning(
                    "xlsx_path_cache fetch_all blob download failed: name=%s, type=%s",
                    getattr(blob, "name", "?"),
                    type(exc).__name__,
                )
                errors.append(exc)
                continue
            try:
                parsed = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                logger.warning(
                    "xlsx_path_cache fetch_all parse failed: name=%s, type=%s",
                    getattr(blob, "name", "?"),
                    type(exc).__name__,
                )
                errors.append(exc)
                continue
            if isinstance(parsed, dict):
                results.append(parsed)
    except (gcs_exc.GoogleAPIError, OSError) as exc:
        logger.warning(
            "xlsx_path_cache fetch_all list_blobs failed: type=%s",
            type(exc).__name__,
        )
        errors.append(exc)
        return (results, errors)  # 部分結果 + エラーを返す（partial を許容）
    return (results, errors)
