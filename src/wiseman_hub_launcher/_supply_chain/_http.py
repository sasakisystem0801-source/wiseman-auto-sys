"""HTTPS GET 共通 helper (PR-7、code-simplifier I-1 反映)。

PR-3 / PR-6a までは ``manifest.fetch_manifest`` と ``download._open_https_get`` が
HTTPS pin + redirect downgrade 防御 + error wrapping を独立実装していたが、
boilerplate が ~80 LOC 重複していたため共通化した (PR-7 タスク A)。

設計方針:
    - HTTPS scheme 検証 (input + redirect 後の最終 URL)
    - urllib の 6 系統例外 (HTTPError / URLError / TimeoutError / SSLError /
      ConnectionError / OSError) を caller 指定の error_class + label で正規化
    - streaming 用 ``open_https_get`` (artifact download など) と
      bounded 用 ``https_get_bounded`` (manifest など) を 2 layer 分離
    - ADR-016 §1.2 階層: 供給チェーン入力境界として ``_supply_chain/`` 配下に配置
"""

from __future__ import annotations

import contextlib
import ssl
import urllib.error
import urllib.request
from typing import Any


def open_https_get(
    url: str,
    *,
    timeout_sec: int,
    error_class: type[Exception],
    label: str,
) -> Any:  # noqa: ANN401 — urllib response 型は public 安定でないため Any
    """HTTPS GET 接続を開く。HTTPS pin + redirect downgrade 防御を含む共通実装。

    Args:
        url: 対象 URL (HTTPS 必須)
        timeout_sec: HTTPS request timeout 秒
        error_class: 失敗時に raise する例外クラス (DownloadError / ManifestError 等)
        label: error message に含めるラベル ("artifact" / "manifest" 等)

    Returns:
        urllib response (caller が close する)。型は安定 public 化されていない。

    Raises:
        error_class: HTTPS scheme 不正、HTTP error、URL error、timeout、SSL、
            network、redirect 後 non-HTTPS のいずれか
    """
    if not isinstance(url, str) or not url.startswith("https://"):
        raise error_class(f"{label} URL must use HTTPS scheme")
    req = urllib.request.Request(url, method="GET")
    # NOTE: 例外順序は subclass 関係依存 (do not reorder alphabetically):
    #   HTTPError < URLError       (HTTPError must come first)
    #   TimeoutError < OSError     (TimeoutError must precede OSError)
    # 並び替えると親クラス側で先に捕捉され、子クラス固有の triage 情報が失われる。
    try:
        resp = urllib.request.urlopen(req, timeout=timeout_sec)  # noqa: S310
    except urllib.error.HTTPError as e:
        # Issue #212 I-1: code に加え reason + Retry-After を含める。
        # 503 Service Unavailable / 429 Too Many Requests + Retry-After=N の triage を高速化。
        retry_after = e.headers.get("Retry-After") if e.headers else None
        raise error_class(
            f"{label} fetch HTTP error: {e.code} {e.reason} retry_after={retry_after}"
        ) from e
    except urllib.error.URLError as e:
        # Issue #212 I-1: reason が OSError なら errno / strerror を残し、
        # それ以外 (str / 任意 Exception) は repr で保持する (review IMPORTANT-1 反映)。
        # 旧形式 ``getattr(reason, 'errno', None)`` だと URLError("proxy auth failed")
        # の reason=str が "str(errno=None, strerror=None)" に化けて元文字列が失われる
        # silent-failure があった。
        reason = e.reason
        if isinstance(reason, OSError):
            # subclass 名 (ConnectionRefusedError 等) を残しつつ errno/strerror で詳細化。
            detail = (
                f"{type(reason).__name__}(errno={reason.errno},"
                f" strerror={reason.strerror})"
            )
        else:
            detail = f"{type(reason).__name__}({reason!r})"
        raise error_class(f"{label} fetch URL error: {detail}") from e
    except TimeoutError as e:
        raise error_class(f"{label} fetch timed out") from e
    except ssl.SSLError as e:
        # Issue #212 I-1: args[0] (CERTIFICATE_VERIFY_FAILED 等) を含める
        # (cert 期限切れ / hostname mismatch / CA chain 失敗を区別可能化)。
        ssl_detail = e.args[0] if e.args else type(e).__name__
        raise error_class(
            f"{label} fetch SSL error: {type(e).__name__}({ssl_detail})"
        ) from e
    except (ConnectionError, OSError) as e:
        raise error_class(
            f"{label} fetch network error: {type(e).__name__}"
        ) from e

    final_url = resp.geturl()
    if not isinstance(final_url, str) or not final_url.startswith("https://"):
        with contextlib.suppress(AttributeError, OSError):
            resp.close()
        raise error_class(f"{label} URL redirected to non-HTTPS scheme")
    return resp


def https_get_bounded(
    url: str,
    *,
    timeout_sec: int,
    max_bytes: int,
    error_class: type[Exception],
    label: str,
) -> bytes:
    """HTTPS GET で bounded body を一括取得する (small file 用)。

    manifest / status 確認等で stream 不要かつ DoS 防御が必要な場合に使用。
    artifact / provenance 等の大容量 + streaming は ``open_https_get`` を直接使うこと。

    Args:
        url: 対象 URL (HTTPS 必須)
        timeout_sec: HTTPS request timeout 秒
        max_bytes: body 上限 (超過時は error_class raise)
        error_class: 失敗時に raise する例外クラス
        label: error message に含めるラベル

    Returns:
        body bytes (max_bytes 以下を保証)

    Raises:
        error_class: open_https_get の全失敗 + status != 200 + size 超過
    """
    resp = open_https_get(
        url, timeout_sec=timeout_sec, error_class=error_class, label=label
    )
    try:
        status = getattr(resp, "status", 200)
        if status != 200:
            raise error_class(f"{label} fetch returned non-200 status: {status}")
        # max_bytes + 1 まで読んで cap 超過を検知
        body = resp.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise error_class(
                f"{label} body exceeds {max_bytes} bytes (DoS guard)"
            )
        return bytes(body)
    finally:
        with contextlib.suppress(AttributeError, OSError):
            resp.close()
