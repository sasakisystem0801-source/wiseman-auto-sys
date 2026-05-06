"""xlsx_path_cache_mirror の単体テスト（GCS は mock）。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from google.api_core import exceptions as gcs_exc

from wiseman_hub.cloud import xlsx_path_cache_mirror as mod
from wiseman_hub.cloud.xlsx_path_cache_mirror import (
    _build_alive_payload,
    _build_tombstone_payload,
    compute_base_config_sha256,
    delete_entry,
    fetch_all,
    fetch_one,
    get_or_create_machine_id,
    make_config_revision,
    object_name_for,
    upload_entry,
)
from wiseman_hub.config import GcpConfig


@pytest.fixture
def fake_sa_key(tmp_path: Path) -> Path:
    p = tmp_path / "sa.json"
    p.write_text("{}", encoding="utf-8")
    return p


@pytest.fixture
def gcp(fake_sa_key: Path) -> GcpConfig:
    return GcpConfig(
        project_id="test-proj",
        data_bucket_name="test-data-bucket",
        service_account_key_path=str(fake_sa_key),
    )


@pytest.fixture
def fake_config(tmp_path: Path) -> Path:
    p = tmp_path / "default.toml"
    p.write_text('[checklist]\nfax_root = ""\n', encoding="utf-8")
    return p


@pytest.fixture
def fake_machine_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """``~/wiseman-hub/machine_id`` を tmp_path 配下に差し替える。"""
    mid_path = tmp_path / "wiseman-hub" / "machine_id"
    monkeypatch.setattr(mod, "_MACHINE_ID_PATH", mid_path)
    return mid_path


def _make_mock_client() -> tuple[MagicMock, MagicMock, MagicMock]:
    """mock storage.Client + bucket + blob を返す。"""
    blob = MagicMock()
    bucket = MagicMock()
    bucket.blob.return_value = blob
    client = MagicMock()
    client.bucket.return_value = bucket
    return client, bucket, blob


class TestObjectNameFor:
    def test_hash_uniqueness(self) -> None:
        a = object_name_for("宮下:2026:3")
        b = object_name_for("宮下:2026:4")
        c = object_name_for("木塚:2026:3")
        assert a != b
        assert a != c
        assert b != c

    def test_format_prefix(self) -> None:
        name = object_name_for("宮下:2026:3")
        assert name.startswith("cache/xlsx_path/")
        assert name.endswith(".json")

    def test_hash_length_32(self) -> None:
        name = object_name_for("宮下:2026:3")
        # cache/xlsx_path/<32 hex>.json
        digest = name[len("cache/xlsx_path/"):-len(".json")]
        assert len(digest) == 32
        int(digest, 16)  # hex 検証

    def test_hash_determinism(self) -> None:
        """同じ key に対しては同じ object 名になる。"""
        a = object_name_for("宮下:2026:3")
        b = object_name_for("宮下:2026:3")
        assert a == b

    def test_hash_uses_utf8(self) -> None:
        """SHA-256 が UTF-8 encode に基づく（PII 配慮で生 key 出ない確認）。"""
        key = "宮下:2026:3"
        name = object_name_for(key)
        expected_digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
        assert name == f"cache/xlsx_path/{expected_digest}.json"


class TestMachineId:
    def test_creates_uuid_when_missing(
        self, fake_machine_id: Path
    ) -> None:
        assert not fake_machine_id.exists()
        mid = get_or_create_machine_id()
        # UUIDv4 形式（8-4-4-4-12 hex）
        assert len(mid) == 36
        assert mid.count("-") == 4
        assert fake_machine_id.exists()
        assert fake_machine_id.read_text(encoding="utf-8").strip() == mid

    def test_idempotent_across_calls(
        self, fake_machine_id: Path
    ) -> None:
        first = get_or_create_machine_id()
        second = get_or_create_machine_id()
        third = get_or_create_machine_id()
        assert first == second == third

    def test_reads_existing_file(
        self, fake_machine_id: Path
    ) -> None:
        fake_machine_id.parent.mkdir(parents=True, exist_ok=True)
        fake_machine_id.write_text(
            "550e8400-e29b-41d4-a716-446655440000\n", encoding="utf-8"
        )
        mid = get_or_create_machine_id()
        assert mid == "550e8400-e29b-41d4-a716-446655440000"

    def test_empty_file_regenerates(
        self, fake_machine_id: Path
    ) -> None:
        """空 file（破損ケース）の場合は新規 UUID を生成して書き戻す。"""
        fake_machine_id.parent.mkdir(parents=True, exist_ok=True)
        fake_machine_id.write_text("", encoding="utf-8")
        mid = get_or_create_machine_id()
        assert len(mid) == 36
        # ※ 空 file の場合 read_text().strip() で空 → 新規生成パスに入るが、
        #    実装は「空でなければ既存値を返す」。空文字なら新規生成 + 書込
        assert fake_machine_id.read_text(encoding="utf-8").strip() == mid


class TestComputeBaseConfigSha256:
    def test_deterministic(self, tmp_path: Path) -> None:
        p = tmp_path / "a.toml"
        p.write_text("[checklist]\n", encoding="utf-8")
        a = compute_base_config_sha256(p)
        b = compute_base_config_sha256(p)
        assert a == b
        assert len(a) == 64  # SHA-256 = 64 hex
        int(a, 16)

    def test_different_content_different_hash(self, tmp_path: Path) -> None:
        p1 = tmp_path / "a.toml"
        p2 = tmp_path / "b.toml"
        p1.write_text("[a]\n", encoding="utf-8")
        p2.write_text("[b]\n", encoding="utf-8")
        assert compute_base_config_sha256(p1) != compute_base_config_sha256(p2)

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        h = compute_base_config_sha256(tmp_path / "no-such.toml")
        assert h == ""


class TestMakeConfigRevision:
    def test_format(self) -> None:
        rev = make_config_revision(
            "2026-05-06T05:23:11.123456+00:00", "abc123def456789"
        )
        assert rev == "2026-05-06T05:23:11.123456+00:00:abc123def456"

    def test_short_hash_truncated_to_12(self) -> None:
        rev = make_config_revision("2026-05-06T00:00:00+00:00", "abcdef")
        # 短い hash はそのまま末尾に
        assert rev == "2026-05-06T00:00:00+00:00:abcdef"

    def test_empty_hash(self) -> None:
        rev = make_config_revision("2026-05-06T00:00:00+00:00", "")
        # 空 hash は空文字で終端
        assert rev == "2026-05-06T00:00:00+00:00:"


class TestBuildPayload:
    def test_alive_payload_schema(
        self,
        fake_config: Path,
        fake_machine_id: Path,
    ) -> None:
        payload = _build_alive_payload(
            "宮下:2026:3",
            r"\\Tera-station\share\PT 宮下\3月.xlsx",
            fake_config,
        )
        assert set(payload.keys()) == {
            "key",
            "xlsx_path",
            "generated_at",
            "machine_id",
            "config_revision",
            "base_config_sha256",
        }
        assert payload["key"] == "宮下:2026:3"
        assert payload["xlsx_path"] == r"\\Tera-station\share\PT 宮下\3月.xlsx"
        assert payload["generated_at"].endswith("+00:00")
        # machine_id は UUIDv4 形式
        assert len(payload["machine_id"]) == 36
        # config_revision = generated_at:base_sha[:12]
        assert payload["config_revision"].startswith(payload["generated_at"] + ":")
        # base_config_sha256 は 64 hex
        assert len(payload["base_config_sha256"]) == 64

    def test_tombstone_payload_schema(
        self, fake_config: Path, fake_machine_id: Path
    ) -> None:
        payload = _build_tombstone_payload("宮下:2026:3", fake_config)
        # ``xlsx_path`` フィールド欠如で tombstone 判別
        assert "xlsx_path" not in payload
        assert payload["key"] == "宮下:2026:3"
        assert payload["deleted_at"].endswith("+00:00")
        assert len(payload["machine_id"]) == 36
        assert "base_config_sha256" in payload
        assert "config_revision" in payload


class TestUploadEntry:
    def test_uploads_alive_payload(
        self,
        gcp: GcpConfig,
        fake_config: Path,
        fake_machine_id: Path,
    ) -> None:
        client, bucket, blob = _make_mock_client()
        ok = upload_entry(
            "宮下:2026:3",
            r"\\Tera-station\share\PT 宮下\3月.xlsx",
            gcp,
            config_path=fake_config,
            client=client,
        )
        assert ok is True
        bucket.blob.assert_called_once()
        called_obj_name = bucket.blob.call_args[0][0]
        assert called_obj_name == object_name_for("宮下:2026:3")
        # upload_from_string が呼ばれ、payload に xlsx_path が含まれる
        blob.upload_from_string.assert_called_once()
        body = blob.upload_from_string.call_args[0][0]
        parsed = json.loads(body)
        assert parsed["key"] == "宮下:2026:3"
        assert parsed["xlsx_path"] == r"\\Tera-station\share\PT 宮下\3月.xlsx"
        assert "generated_at" in parsed
        # if_generation_match は使わない（mutable overwrite）
        kwargs = blob.upload_from_string.call_args.kwargs
        assert "if_generation_match" not in kwargs
        # content_type / timeout / ensure_ascii=False
        assert kwargs.get("content_type") == "application/json; charset=utf-8"
        assert kwargs.get("timeout") == 30

    def test_no_op_when_gcp_missing(
        self, fake_config: Path, fake_machine_id: Path
    ) -> None:
        bad = GcpConfig()  # 全空
        client, _, blob = _make_mock_client()
        ok = upload_entry(
            "宮下:2026:3",
            "x.xlsx",
            bad,
            config_path=fake_config,
            client=client,
        )
        assert ok is False
        blob.upload_from_string.assert_not_called()

    def test_no_op_when_sa_key_missing(
        self,
        fake_config: Path,
        fake_machine_id: Path,
        tmp_path: Path,
    ) -> None:
        gcp_no_sa = GcpConfig(
            project_id="p",
            data_bucket_name="b",
            service_account_key_path=str(tmp_path / "no-such.json"),
        )
        client, _, blob = _make_mock_client()
        ok = upload_entry(
            "宮下:2026:3", "x.xlsx", gcp_no_sa, config_path=fake_config, client=client
        )
        assert ok is False
        blob.upload_from_string.assert_not_called()

    def test_returns_false_on_api_error(
        self,
        gcp: GcpConfig,
        fake_config: Path,
        fake_machine_id: Path,
    ) -> None:
        client, _, blob = _make_mock_client()
        blob.upload_from_string.side_effect = gcs_exc.ServiceUnavailable("503")
        ok = upload_entry(
            "宮下:2026:3", "x.xlsx", gcp, config_path=fake_config, client=client
        )
        assert ok is False

    def test_payload_uses_ensure_ascii_false(
        self,
        gcp: GcpConfig,
        fake_config: Path,
        fake_machine_id: Path,
    ) -> None:
        """payload の JSON 内に日本語が ASCII エスケープされない（PII 視認性）。"""
        client, _, blob = _make_mock_client()
        upload_entry(
            "宮下:2026:3",
            "テスト.xlsx",
            gcp,
            config_path=fake_config,
            client=client,
        )
        body = blob.upload_from_string.call_args[0][0]
        # ensure_ascii=False なら日本語そのまま含まれる
        assert "宮下" in body
        assert "テスト.xlsx" in body
        # ensure_ascii=True だと "宮" などになる
        assert "\\u" not in body or "テスト" in body  # 日本語が plain で出る


class TestDeleteEntry:
    def test_uploads_tombstone(
        self, gcp: GcpConfig, fake_config: Path, fake_machine_id: Path
    ) -> None:
        client, bucket, blob = _make_mock_client()
        ok = delete_entry(
            "宮下:2026:3", gcp, config_path=fake_config, client=client
        )
        assert ok is True
        bucket.blob.assert_called_once()
        body = blob.upload_from_string.call_args[0][0]
        parsed = json.loads(body)
        assert parsed["key"] == "宮下:2026:3"
        # tombstone は xlsx_path 欠如 + deleted_at あり
        assert "xlsx_path" not in parsed
        assert "deleted_at" in parsed

    def test_no_op_when_gcp_missing(
        self, fake_config: Path, fake_machine_id: Path
    ) -> None:
        client, _, blob = _make_mock_client()
        ok = delete_entry(
            "宮下:2026:3", GcpConfig(), config_path=fake_config, client=client
        )
        assert ok is False
        blob.upload_from_string.assert_not_called()


class TestFetchOne:
    def test_returns_parsed_dict(
        self, gcp: GcpConfig, fake_machine_id: Path
    ) -> None:
        client, bucket, blob = _make_mock_client()
        blob.exists.return_value = True
        payload = {
            "key": "宮下:2026:3",
            "xlsx_path": "x.xlsx",
            "generated_at": "2026-05-06T05:23:11+00:00",
            "machine_id": "550e8400-e29b-41d4-a716-446655440000",
            "config_revision": "2026-05-06T05:23:11+00:00:abc",
            "base_config_sha256": "a" * 64,
        }
        blob.download_as_bytes.return_value = json.dumps(payload).encode("utf-8")
        result = fetch_one("宮下:2026:3", gcp, client=client)
        assert result == payload

    def test_returns_none_when_missing(
        self, gcp: GcpConfig, fake_machine_id: Path
    ) -> None:
        client, _, blob = _make_mock_client()
        blob.exists.return_value = False
        result = fetch_one("宮下:2026:3", gcp, client=client)
        assert result is None

    def test_returns_none_on_invalid_json(
        self, gcp: GcpConfig, fake_machine_id: Path
    ) -> None:
        client, _, blob = _make_mock_client()
        blob.exists.return_value = True
        blob.download_as_bytes.return_value = b"not json"
        result = fetch_one("宮下:2026:3", gcp, client=client)
        assert result is None

    def test_returns_none_on_api_error(
        self, gcp: GcpConfig, fake_machine_id: Path
    ) -> None:
        client, _, blob = _make_mock_client()
        blob.exists.side_effect = gcs_exc.ServiceUnavailable("503")
        result = fetch_one("宮下:2026:3", gcp, client=client)
        assert result is None

    def test_returns_none_when_gcp_missing(self, fake_machine_id: Path) -> None:
        result = fetch_one("宮下:2026:3", GcpConfig())
        assert result is None


class TestFetchAll:
    def test_returns_all_entries(
        self, gcp: GcpConfig, fake_machine_id: Path
    ) -> None:
        client, bucket, _ = _make_mock_client()
        # alive 1 件 + tombstone 1 件
        alive_payload = {
            "key": "宮下:2026:3",
            "xlsx_path": "x.xlsx",
            "generated_at": "2026-05-06T05:23:11+00:00",
            "machine_id": "m1",
            "config_revision": "rev1",
            "base_config_sha256": "a" * 64,
        }
        tomb_payload = {
            "key": "木塚:2026:4",
            "deleted_at": "2026-05-06T06:00:00+00:00",
            "machine_id": "m2",
            "config_revision": "rev2",
            "base_config_sha256": "b" * 64,
        }
        b1 = MagicMock()
        b1.name = "cache/xlsx_path/aaa.json"
        b1.download_as_bytes.return_value = json.dumps(alive_payload).encode("utf-8")
        b2 = MagicMock()
        b2.name = "cache/xlsx_path/bbb.json"
        b2.download_as_bytes.return_value = json.dumps(tomb_payload).encode("utf-8")
        client.list_blobs.return_value = [b1, b2]

        results = fetch_all(gcp, client=client)
        assert len(results) == 2
        keys = sorted(r["key"] for r in results)
        assert keys == ["宮下:2026:3", "木塚:2026:4"]

    def test_skips_invalid_json_blob(
        self, gcp: GcpConfig, fake_machine_id: Path
    ) -> None:
        client, _, _ = _make_mock_client()
        b1 = MagicMock()
        b1.name = "cache/xlsx_path/aaa.json"
        b1.download_as_bytes.return_value = b"not json"
        b2 = MagicMock()
        b2.name = "cache/xlsx_path/bbb.json"
        b2.download_as_bytes.return_value = json.dumps(
            {"key": "valid", "xlsx_path": "x"}
        ).encode("utf-8")
        client.list_blobs.return_value = [b1, b2]

        results = fetch_all(gcp, client=client)
        assert len(results) == 1
        assert results[0]["key"] == "valid"

    def test_returns_empty_when_gcp_missing(self) -> None:
        results = fetch_all(GcpConfig())
        assert results == []

    def test_returns_partial_on_list_error(
        self, gcp: GcpConfig, fake_machine_id: Path
    ) -> None:
        client, _, _ = _make_mock_client()
        client.list_blobs.side_effect = gcs_exc.ServiceUnavailable("503")
        results = fetch_all(gcp, client=client)
        assert results == []


class TestAliveTombstoneDistinction:
    """Mirror payload と fetch 結果から alive / tombstone を判別できる。"""

    def test_alive_has_xlsx_path(
        self, fake_config: Path, fake_machine_id: Path
    ) -> None:
        payload = _build_alive_payload("宮下:2026:3", "x.xlsx", fake_config)
        assert "xlsx_path" in payload
        assert "deleted_at" not in payload

    def test_tombstone_lacks_xlsx_path(
        self, fake_config: Path, fake_machine_id: Path
    ) -> None:
        payload = _build_tombstone_payload("宮下:2026:3", fake_config)
        assert "xlsx_path" not in payload
        assert "deleted_at" in payload


class TestParallelUploadRace:
    """並列 upload race の挙動（doc コメント記載の方針確認）。

    本モジュールは per-key per-object のため、異なる key は完全独立。
    同一 key への並列 upload は GCS の last-writer-wins で自然解決される。
    本テストでは「同一 key に対する 2 回 upload は両方とも成功扱いになる」
    ことだけ確認する（GCS 側の write 順序は本テストで担保しない）。
    """

    def test_two_uploads_same_key_both_succeed(
        self,
        gcp: GcpConfig,
        fake_config: Path,
        fake_machine_id: Path,
    ) -> None:
        client, _, blob = _make_mock_client()
        ok1 = upload_entry(
            "宮下:2026:3", "x1.xlsx", gcp, config_path=fake_config, client=client
        )
        ok2 = upload_entry(
            "宮下:2026:3", "x2.xlsx", gcp, config_path=fake_config, client=client
        )
        # 両方とも upload_from_string 成功（mock のため）
        assert ok1 is True
        assert ok2 is True
        # mutable overwrite なので 2 回目は同じ object 名に書き直す
        assert blob.upload_from_string.call_count == 2
