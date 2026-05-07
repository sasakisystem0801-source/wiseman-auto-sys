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


def test_verify_system_clock_above_upper_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    """now=2031-01-01 (上限超) → SigstoreVerifyError (TODO 2030-12-31 期限超過)。"""
    _patch_now(monkeypatch, dt.datetime(2031, 1, 1, 0, 0, 1, tzinfo=dt.UTC))
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
