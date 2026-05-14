"""Tests for wiseman_hub_launcher._supply_chain.sigstore (Issue #216)。

Issue #216 (rating 7): `sigstore.py` (新規 92 LOC) は test_provenance.py の
``verify_dsse_bundle`` mock 経由でしか integration 化されていなかった。internal
helpers の direct test を追加して以下を gate する:

- ``_verify_system_clock`` の絶対範囲境界値 (2026-01-01 / 2030-12-31)
- ``_load_bundle`` の OSError / JSONDecodeError wrap
- ``_build_verifier`` の TUF/network init 失敗 wrap
- ``verify_dsse_bundle`` の payloadType / payload bytes 型ガード
- ``build_expected_identity`` の URI 組立

dev 依存に freezegun を入れず、``datetime.datetime`` を ``monkeypatch`` で
直接置き換える方針 (stdlib のみで完結)。sigstore-python 自体の挙動 (cert chain
検証等) は Verifier mock 経由で gate するため、ネットワークは触らない。
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from wiseman_hub_launcher._supply_chain import sigstore as sigstore_mod
from wiseman_hub_launcher._supply_chain.sigstore import (
    SigstoreVerifyError,
    build_expected_identity,
    verify_dsse_bundle,
    warn_if_trust_root_stale,
)

_DSSE_INTOTO = "application/vnd.in-toto+json"


# _verify_system_clock --------------------------------------------------------


def _patch_now(monkeypatch: pytest.MonkeyPatch, now: dt.datetime) -> None:
    """`sigstore_mod.dt.datetime.now` を置き換えるため、datetime 全体を差し替える。"""

    class _FrozenDateTime(dt.datetime):
        @classmethod
        def now(cls, tz: dt.tzinfo | None = None) -> dt.datetime:  # type: ignore[override]
            if tz is None:
                return now.replace(tzinfo=None)
            return now.astimezone(tz)

    monkeypatch.setattr(sigstore_mod.dt, "datetime", _FrozenDateTime)


def test_verify_system_clock_inside_range(monkeypatch: pytest.MonkeyPatch) -> None:
    """now=2027 中央 → 例外なし。"""
    _patch_now(monkeypatch, dt.datetime(2027, 6, 15, 12, 0, 0, tzinfo=dt.UTC))
    sigstore_mod._verify_system_clock()


def test_verify_system_clock_at_lower_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    """now=2026-01-01T00:00:00Z (下限ちょうど) → 例外なし。"""
    _patch_now(monkeypatch, dt.datetime(2026, 1, 1, 0, 0, 0, tzinfo=dt.UTC))
    sigstore_mod._verify_system_clock()


def test_verify_system_clock_below_lower_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    """now=2025-12-31 (下限未満) → SigstoreVerifyError。"""
    _patch_now(monkeypatch, dt.datetime(2025, 12, 31, 23, 59, 59, tzinfo=dt.UTC))
    with pytest.raises(SigstoreVerifyError, match="clock out of expected range"):
        sigstore_mod._verify_system_clock()


def test_verify_system_clock_at_upper_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    """now=2030-12-31T00:00:00Z (上限ちょうど) → 例外なし (`<=` 比較の inclusive 確認)。"""
    _patch_now(monkeypatch, dt.datetime(2030, 12, 31, 0, 0, 0, tzinfo=dt.UTC))
    sigstore_mod._verify_system_clock()


def test_verify_system_clock_above_upper_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    """now=2030-12-31T00:00:01Z (上限ちょうど + 1 秒) → SigstoreVerifyError。

    code-reviewer I-1 反映: 下限側 ±1秒境界と対称にするため、上限+1日 (2031-01-01) ではなく
    上限+1秒で「ぎりぎり外」を test。`<=` を `<` にダウングレードする regression を検出可能。
    """
    _patch_now(monkeypatch, dt.datetime(2030, 12, 31, 0, 0, 1, tzinfo=dt.UTC))
    with pytest.raises(SigstoreVerifyError, match="clock out of expected range"):
        sigstore_mod._verify_system_clock()


# _load_bundle ----------------------------------------------------------------


def test_load_bundle_file_not_found(tmp_path: Path) -> None:
    """bundle file 不在 → SigstoreVerifyError (OSError wrap)。"""
    missing = tmp_path / "nope.sigstore.json"
    with pytest.raises(SigstoreVerifyError, match="bundle read failed"):
        sigstore_mod._load_bundle(missing)


def test_load_bundle_malformed_json(tmp_path: Path) -> None:
    """JSON parse 失敗 → SigstoreVerifyError (Bundle.from_json の ValueError wrap)。"""
    bad = tmp_path / "bad.sigstore.json"
    bad.write_text("not-a-json{", encoding="utf-8")
    with pytest.raises(SigstoreVerifyError, match="bundle parse failed|bundle read failed"):
        sigstore_mod._load_bundle(bad)


# sigstore-python 不在時の ImportError wrap (ADR-016 §1.1.3、各 helper 共通) ---


@pytest.mark.parametrize(
    ("invoke", "module_to_break"),
    [
        (lambda: sigstore_mod._load_bundle(Path("/tmp/dummy.sigstore.json")), "sigstore.models"),
        (
            lambda: sigstore_mod._build_identity_policy(
                expected_identity="x", expected_issuer="y"
            ),
            "sigstore.verify.policy",
        ),
        (lambda: sigstore_mod._build_verifier(), "sigstore.verify"),
    ],
    ids=["_load_bundle", "_build_identity_policy", "_build_verifier"],
)
def test_helpers_wrap_sigstore_import_error(invoke: Any, module_to_break: str) -> None:
    """sigstore-python 未 install → SigstoreVerifyError("sigstore-python not installed")。

    ADR-016 §1.1.3 の launcher runtime stdlib only 例外として `sigstore` のみ許可
    という制約を test レベルで pin する。3 helpers 全てに共通の ImportError wrap
    パターンを 1 parametrize で gate。
    """
    with (
        patch.dict("sys.modules", {module_to_break: None}),
        pytest.raises(SigstoreVerifyError, match="sigstore-python not installed"),
    ):
        invoke()


# _build_verifier -------------------------------------------------------------


def test_build_verifier_wraps_production_failure() -> None:
    """``Verifier.production()`` が任意の例外を raise → SigstoreVerifyError wrap。"""
    fake_verifier_module = MagicMock()
    fake_verifier_module.Verifier.production.side_effect = RuntimeError("TUF refresh failed")
    with (
        patch.dict("sys.modules", {"sigstore.verify": fake_verifier_module}),
        pytest.raises(SigstoreVerifyError, match="Verifier.production.*RuntimeError"),
    ):
        sigstore_mod._build_verifier()


# verify_dsse_bundle 統合 (内部 helper を mock してロジック単体を gate) -----------


def _make_fake_bundle_path(tmp_path: Path) -> Path:
    """中身は読まれない (load_bundle 自体を mock) ので空 file で十分。"""
    p = tmp_path / "fake.sigstore.json"
    p.write_text("{}", encoding="utf-8")
    return p


def test_verify_dsse_bundle_rejects_non_intoto_payload_type(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """payload_type が in-toto でない → SigstoreVerifyError。"""
    _patch_now(monkeypatch, dt.datetime(2027, 1, 1, tzinfo=dt.UTC))
    fake_verifier = MagicMock()
    fake_verifier.verify_dsse.return_value = (
        "application/vnd.dev.cosign+json",  # in-toto ではない
        b'{"_type":"x"}',
    )
    with (
        patch.object(sigstore_mod, "_load_bundle", return_value=MagicMock()),
        patch.object(sigstore_mod, "_build_identity_policy", return_value=MagicMock()),
        patch.object(sigstore_mod, "_build_verifier", return_value=fake_verifier),
        pytest.raises(SigstoreVerifyError, match="DSSE payloadType must be"),
    ):
        verify_dsse_bundle(
            bundle_path=_make_fake_bundle_path(tmp_path),
            expected_identity="https://github.com/x/y/.github/workflows/release.yml@refs/tags/v1.2.3",
        )


def test_verify_dsse_bundle_rejects_non_bytes_payload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """payload が bytes 以外 (例: str) → SigstoreVerifyError (type guard)。"""
    _patch_now(monkeypatch, dt.datetime(2027, 1, 1, tzinfo=dt.UTC))
    fake_verifier = MagicMock()
    fake_verifier.verify_dsse.return_value = (_DSSE_INTOTO, "should-be-bytes")
    with (
        patch.object(sigstore_mod, "_load_bundle", return_value=MagicMock()),
        patch.object(sigstore_mod, "_build_identity_policy", return_value=MagicMock()),
        patch.object(sigstore_mod, "_build_verifier", return_value=fake_verifier),
        pytest.raises(SigstoreVerifyError, match="must return bytes payload"),
    ):
        verify_dsse_bundle(
            bundle_path=_make_fake_bundle_path(tmp_path),
            expected_identity="https://github.com/x/y/.github/workflows/release.yml@refs/tags/v1.2.3",
        )


def test_verify_dsse_bundle_wraps_verifier_runtime_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`verify_dsse` の generic Exception (cert chain / Rekor 失敗等) → SigstoreVerifyError wrap。

    pr-test-analyzer I-1 反映: signature 検証本丸の fail-close path。
    `sigstore.errors.VerificationError` / RuntimeError / ValueError 等を一律 wrap する
    line 138 の `except Exception` の動作を gate。
    """
    _patch_now(monkeypatch, dt.datetime(2027, 1, 1, tzinfo=dt.UTC))
    fake_verifier = MagicMock()
    fake_verifier.verify_dsse.side_effect = RuntimeError("cert chain mismatch")
    with (
        patch.object(sigstore_mod, "_load_bundle", return_value=MagicMock()),
        patch.object(sigstore_mod, "_build_identity_policy", return_value=MagicMock()),
        patch.object(sigstore_mod, "_build_verifier", return_value=fake_verifier),
        pytest.raises(SigstoreVerifyError, match=r"verify_dsse failed.*RuntimeError"),
    ):
        verify_dsse_bundle(
            bundle_path=_make_fake_bundle_path(tmp_path),
            expected_identity="https://github.com/x/y/.github/workflows/release.yml@refs/tags/v1.2.3",
        )


def test_verify_dsse_bundle_passes_through_sigstore_verify_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`verify_dsse` が SigstoreVerifyError raise → 二重 wrap せず原例外を re-raise。

    line 136-137 の `except SigstoreVerifyError: raise` が正しく動作することを gate。
    将来 line 136 を削除すると "verify_dsse failed: SigstoreVerifyError: ..." の
    二重 wrap になり original message が埋もれるため、message 一致で検出可能。
    """
    _patch_now(monkeypatch, dt.datetime(2027, 1, 1, tzinfo=dt.UTC))
    fake_verifier = MagicMock()
    fake_verifier.verify_dsse.side_effect = SigstoreVerifyError("rekor proof invalid")
    with (
        patch.object(sigstore_mod, "_load_bundle", return_value=MagicMock()),
        patch.object(sigstore_mod, "_build_identity_policy", return_value=MagicMock()),
        patch.object(sigstore_mod, "_build_verifier", return_value=fake_verifier),
        pytest.raises(SigstoreVerifyError, match=r"^rekor proof invalid$"),
    ):
        verify_dsse_bundle(
            bundle_path=_make_fake_bundle_path(tmp_path),
            expected_identity="https://github.com/x/y/.github/workflows/release.yml@refs/tags/v1.2.3",
        )


@pytest.mark.parametrize(
    ("payload", "expected_inner"),
    [
        (b"\xff\xfe\xfd", "UnicodeDecodeError"),
        (b"not-a-json", "JSONDecodeError"),
    ],
    ids=["non_utf8", "non_json"],
)
def test_verify_dsse_bundle_rejects_undecodable_payload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    payload: bytes,
    expected_inner: str,
) -> None:
    """payload bytes が UTF-8 不正 / JSON 不正 → SigstoreVerifyError wrap (line 153-158)。"""
    _patch_now(monkeypatch, dt.datetime(2027, 1, 1, tzinfo=dt.UTC))
    fake_verifier = MagicMock()
    fake_verifier.verify_dsse.return_value = (_DSSE_INTOTO, payload)
    with (
        patch.object(sigstore_mod, "_load_bundle", return_value=MagicMock()),
        patch.object(sigstore_mod, "_build_identity_policy", return_value=MagicMock()),
        patch.object(sigstore_mod, "_build_verifier", return_value=fake_verifier),
        pytest.raises(SigstoreVerifyError, match=f"DSSE payload JSON parse failed.*{expected_inner}"),
    ):
        verify_dsse_bundle(
            bundle_path=_make_fake_bundle_path(tmp_path),
            expected_identity="https://github.com/x/y/.github/workflows/release.yml@refs/tags/v1.2.3",
        )


def test_verify_dsse_bundle_rejects_non_object_statement(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """payload が JSON object でない (例: list) → SigstoreVerifyError。"""
    _patch_now(monkeypatch, dt.datetime(2027, 1, 1, tzinfo=dt.UTC))
    fake_verifier = MagicMock()
    fake_verifier.verify_dsse.return_value = (_DSSE_INTOTO, b'["not-an-object"]')
    with (
        patch.object(sigstore_mod, "_load_bundle", return_value=MagicMock()),
        patch.object(sigstore_mod, "_build_identity_policy", return_value=MagicMock()),
        patch.object(sigstore_mod, "_build_verifier", return_value=fake_verifier),
        pytest.raises(SigstoreVerifyError, match="must be JSON object"),
    ):
        verify_dsse_bundle(
            bundle_path=_make_fake_bundle_path(tmp_path),
            expected_identity="https://github.com/x/y/.github/workflows/release.yml@refs/tags/v1.2.3",
        )


def test_verify_dsse_bundle_happy_returns_statement(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """正常系: payload を JSON decode した dict を返す。"""
    _patch_now(monkeypatch, dt.datetime(2027, 1, 1, tzinfo=dt.UTC))
    statement: dict[str, Any] = {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [{"name": "wiseman_hub.exe", "digest": {"sha256": "deadbeef"}}],
        "predicateType": "https://slsa.dev/provenance/v1",
        "predicate": {},
    }
    fake_verifier = MagicMock()
    fake_verifier.verify_dsse.return_value = (
        _DSSE_INTOTO,
        json.dumps(statement).encode("utf-8"),
    )
    with (
        patch.object(sigstore_mod, "_load_bundle", return_value=MagicMock()),
        patch.object(sigstore_mod, "_build_identity_policy", return_value=MagicMock()),
        patch.object(sigstore_mod, "_build_verifier", return_value=fake_verifier),
    ):
        result = verify_dsse_bundle(
            bundle_path=_make_fake_bundle_path(tmp_path),
            expected_identity="https://github.com/x/y/.github/workflows/release.yml@refs/tags/v1.2.3",
        )
    assert result == statement


def test_verify_dsse_bundle_propagates_clock_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """clock 範囲外 → load_bundle に到達せず SigstoreVerifyError raise (fail-close 順序)。"""
    _patch_now(monkeypatch, dt.datetime(2025, 1, 1, tzinfo=dt.UTC))
    load_called = False

    def _spy_load(*_args: object, **_kwargs: object) -> object:
        nonlocal load_called
        load_called = True
        return MagicMock()

    with (
        patch.object(sigstore_mod, "_load_bundle", side_effect=_spy_load),
        pytest.raises(SigstoreVerifyError, match="clock out of expected range"),
    ):
        verify_dsse_bundle(
            bundle_path=_make_fake_bundle_path(tmp_path),
            expected_identity="https://github.com/x/y/.github/workflows/release.yml@refs/tags/v1.2.3",
        )
    assert load_called is False, "clock check 失敗時に bundle load まで進んではならない"


# build_expected_identity ----------------------------------------------------


def test_build_expected_identity_assembles_uri() -> None:
    """正常組立: ``https://github.com/{repo}/{workflow_path}@{ref}``。"""
    uri = build_expected_identity(
        repo="sasakisystem0801-source/wiseman-auto-sys",
        workflow_path=".github/workflows/release.yml",
        ref="refs/tags/v1.2.3",
    )
    assert uri == (
        "https://github.com/sasakisystem0801-source/wiseman-auto-sys/"
        ".github/workflows/release.yml@refs/tags/v1.2.3"
    )


def test_build_expected_identity_does_not_url_encode() -> None:
    """codex C2 完全一致仕様: caller が組立てる URI を一切エスケープせず concat する。"""
    uri = build_expected_identity(
        repo="org/repo-with-dash",
        workflow_path=".github/workflows/release.yml",
        ref="refs/tags/v0.0.0-rc1",
    )
    assert "org/repo-with-dash" in uri
    assert "@refs/tags/v0.0.0-rc1" in uri
    assert uri.startswith("https://github.com/")


# warn_if_trust_root_stale ---------------------------------------------------


def _write_fake_root_json(store_dir: Path, *, expires_iso: str) -> None:
    """テスト用の最小 root.json (TUF root metadata format) を書き出す。"""
    store_dir.mkdir(parents=True, exist_ok=True)
    (store_dir / "root.json").write_text(
        json.dumps({"signed": {"expires": expires_iso}, "signatures": []}),
        encoding="utf-8",
    )


def test_warn_if_trust_root_stale_emits_warning_when_expired(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """既に expire 済 → WARNING ログ (EXPIRED 表記)。"""
    fixed_now = dt.datetime(2026, 5, 14, tzinfo=dt.UTC)
    _patch_now(monkeypatch, fixed_now)
    _write_fake_root_json(tmp_path, expires_iso="2025-08-19T14:33:09Z")

    with caplog.at_level("DEBUG", logger="wiseman_hub_launcher._supply_chain.sigstore"):
        warn_if_trust_root_stale(store_dir=tmp_path)

    assert any(
        "EXPIRED" in r.getMessage() and r.levelname == "WARNING" for r in caplog.records
    ), caplog.text


def test_warn_if_trust_root_stale_emits_warning_within_window(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """残り 10 日 → WARNING ログ (近日 expire の合図)。"""
    fixed_now = dt.datetime(2026, 5, 14, tzinfo=dt.UTC)
    _patch_now(monkeypatch, fixed_now)
    _write_fake_root_json(tmp_path, expires_iso="2026-05-24T00:00:00Z")

    with caplog.at_level("DEBUG", logger="wiseman_hub_launcher._supply_chain.sigstore"):
        warn_if_trust_root_stale(store_dir=tmp_path)

    warns = [
        r for r in caplog.records if r.levelname == "WARNING" and "expires in" in r.getMessage()
    ]
    assert warns, caplog.text


def test_warn_if_trust_root_stale_debug_when_healthy(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """残り 100 日 → DEBUG ログのみ (健全、WARNING 出さない)。"""
    fixed_now = dt.datetime(2026, 5, 14, tzinfo=dt.UTC)
    _patch_now(monkeypatch, fixed_now)
    _write_fake_root_json(tmp_path, expires_iso="2026-08-22T00:00:00Z")

    with caplog.at_level("DEBUG", logger="wiseman_hub_launcher._supply_chain.sigstore"):
        warn_if_trust_root_stale(store_dir=tmp_path)

    warns = [r for r in caplog.records if r.levelname == "WARNING"]
    assert not warns, f"unexpected WARNING: {caplog.text}"


def test_warn_if_trust_root_stale_missing_file_is_silent(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """root.json 不在 → 起動 blocking しない (debug log のみ、WARNING/ERROR なし)。"""
    with caplog.at_level("DEBUG", logger="wiseman_hub_launcher._supply_chain.sigstore"):
        warn_if_trust_root_stale(store_dir=tmp_path)  # 空 dir

    elevated = [r for r in caplog.records if r.levelname in ("WARNING", "ERROR")]
    assert not elevated, f"unexpected elevated log: {caplog.text}"


def test_warn_if_trust_root_stale_malformed_json_is_silent(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """不正 JSON → 起動 blocking しない (debug log のみ、WARNING/ERROR なし)。"""
    (tmp_path / "root.json").write_text("not a json {{{", encoding="utf-8")

    with caplog.at_level("DEBUG", logger="wiseman_hub_launcher._supply_chain.sigstore"):
        warn_if_trust_root_stale(store_dir=tmp_path)

    elevated = [r for r in caplog.records if r.levelname in ("WARNING", "ERROR")]
    assert not elevated, f"unexpected elevated log: {caplog.text}"


def test_warn_if_trust_root_stale_missing_expires_key_is_silent(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`signed.expires` キー不在 → 起動 blocking しない (debug log のみ)。"""
    (tmp_path / "root.json").write_text(
        json.dumps({"signed": {}, "signatures": []}), encoding="utf-8"
    )

    with caplog.at_level("DEBUG", logger="wiseman_hub_launcher._supply_chain.sigstore"):
        warn_if_trust_root_stale(store_dir=tmp_path)

    elevated = [r for r in caplog.records if r.levelname in ("WARNING", "ERROR")]
    assert not elevated, f"unexpected elevated log: {caplog.text}"


def test_warn_if_trust_root_stale_tz_naive_expires_is_silent(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """tz-naive な expires 文字列 → TypeError 握り潰し (debug log のみ、起動継続)。

    expires が RFC 3339 違反 (`Z` 接尾辞も `+HH:MM` もない) の場合、
    `fromisoformat` は tz-naive datetime を返し、tz-aware now との比較で TypeError。
    AC-5 (例外時は起動 blocking しない) を保つため握り潰す経路を gate する。
    """
    _write_fake_root_json(tmp_path, expires_iso="2026-08-22T00:00:00")  # tz なし

    with caplog.at_level("DEBUG", logger="wiseman_hub_launcher._supply_chain.sigstore"):
        warn_if_trust_root_stale(store_dir=tmp_path)

    elevated = [r for r in caplog.records if r.levelname in ("WARNING", "ERROR")]
    assert not elevated, f"unexpected elevated log: {caplog.text}"


def test_warn_if_trust_root_stale_at_warn_threshold_boundary(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """境界値: 残り 30 日 ちょうど → WARNING を出す (`<= 30` の `=` 側 pin)。"""
    fixed_now = dt.datetime(2026, 5, 14, tzinfo=dt.UTC)
    _patch_now(monkeypatch, fixed_now)
    # 30 日後 ちょうど
    _write_fake_root_json(tmp_path, expires_iso="2026-06-13T00:00:00Z")

    with caplog.at_level("DEBUG", logger="wiseman_hub_launcher._supply_chain.sigstore"):
        warn_if_trust_root_stale(store_dir=tmp_path)

    warns = [
        r for r in caplog.records if r.levelname == "WARNING" and "expires in" in r.getMessage()
    ]
    assert warns, caplog.text


def test_warn_if_trust_root_stale_above_warn_threshold_is_debug(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """境界値: 残り 31 日 → WARNING を出さない (`<= 30` の `<` 側 pin)。"""
    fixed_now = dt.datetime(2026, 5, 14, tzinfo=dt.UTC)
    _patch_now(monkeypatch, fixed_now)
    # 31 日後
    _write_fake_root_json(tmp_path, expires_iso="2026-06-14T00:00:00Z")

    with caplog.at_level("DEBUG", logger="wiseman_hub_launcher._supply_chain.sigstore"):
        warn_if_trust_root_stale(store_dir=tmp_path)

    warns = [r for r in caplog.records if r.levelname == "WARNING"]
    assert not warns, f"unexpected WARNING: {caplog.text}"
