"""mapping_sync.push_routing / pull_routing の単体テスト（GCS は mock）。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from google.api_core import exceptions as gcs_exc
from google.auth import exceptions as auth_exc

from wiseman_hub.cloud.mapping_sync import (
    MAPPING_BLOB_PATH,
    REPORT_STAFF_BLOB_PATH,
    MappingConfigError,
    MappingNotFoundError,
    MappingSyncError,
    pull_report_staff,
    pull_routing,
    push_report_staff,
    push_routing,
)
from wiseman_hub.config import GcpConfig, ReportStaffEntry


@pytest.fixture
def fake_sa_key(tmp_path: Path) -> Path:
    """SA キー存在チェックを通すための dummy ファイル。"""
    p = tmp_path / "sa.json"
    p.write_text("{}", encoding="utf-8")
    return p


@pytest.fixture
def gcp(fake_sa_key: Path) -> GcpConfig:
    return GcpConfig(
        project_id="test-proj",
        bucket_name="test-bucket",
        service_account_key_path=fake_sa_key,
    )


def _make_storage_mock(blob_mock: MagicMock) -> MagicMock:
    """``storage.Client.from_service_account_json`` 全体を置き換える mock 構成。"""
    bucket = MagicMock()
    bucket.blob.return_value = blob_mock
    client = MagicMock()
    client.bucket.return_value = bucket
    factory = MagicMock(return_value=client)
    return factory


class TestValidateGcp:
    """過去失敗対策: GCP 設定不足を実 API 呼び出し前に弾く。"""

    def test_empty_project_id_raises(self, fake_sa_key: Path) -> None:
        gcp = GcpConfig(
            project_id="",
            bucket_name="b",
            service_account_key_path=fake_sa_key,
        )
        with pytest.raises(MappingConfigError, match="project_id"):
            push_routing(gcp, {"a": "b"})

    def test_empty_bucket_name_raises(self, fake_sa_key: Path) -> None:
        gcp = GcpConfig(
            project_id="p",
            bucket_name="",
            service_account_key_path=fake_sa_key,
        )
        with pytest.raises(MappingConfigError, match="bucket_name"):
            pull_routing(gcp)

    def test_missing_sa_key_raises(self, tmp_path: Path) -> None:
        gcp = GcpConfig(
            project_id="p",
            bucket_name="b",
            service_account_key_path=tmp_path / "no-such-file.json",
        )
        with pytest.raises(MappingConfigError, match="SA キー"):
            push_routing(gcp, {"a": "b"})

    def test_missing_sa_key_message_does_not_leak_full_path(
        self, tmp_path: Path
    ) -> None:
        """過去失敗対策（codex LOW-1）: messagebox にユーザー名を含む絶対パスを出さない。"""
        sub = tmp_path / "username-segment"
        sub.mkdir()
        gcp = GcpConfig(
            project_id="p",
            bucket_name="b",
            service_account_key_path=sub / "no-such-file.json",
        )
        with pytest.raises(MappingConfigError) as ei:
            push_routing(gcp, {"a": "b"})
        assert "username-segment" not in str(ei.value)
        assert "no-such-file.json" in str(ei.value)

    def test_invalid_sa_key_json_raises_config_error(
        self, gcp: GcpConfig
    ) -> None:
        """過去失敗対策（codex HIGH-1）: SA キー JSON が壊れていると ValueError が投げられる。

        ``MappingConfigError`` に変換して messagebox にならず crash する事故を防ぐ。
        """
        with patch(
            "wiseman_hub.cloud.mapping_sync.storage.Client.from_service_account_json",
            side_effect=ValueError("malformed key"),
        ), pytest.raises(MappingConfigError, match="SA キーを読み込めません"):
            push_routing(gcp, {"a": "b"})

    def test_auth_error_raises_config_error(self, gcp: GcpConfig) -> None:
        """過去失敗対策（codex HIGH-1）: GoogleAuthError も MappingConfigError に変換。"""
        with patch(
            "wiseman_hub.cloud.mapping_sync.storage.Client.from_service_account_json",
            side_effect=auth_exc.DefaultCredentialsError("bad credentials"),
        ), pytest.raises(MappingConfigError, match="SA キーを読み込めません"):
            pull_routing(gcp)


class TestPushRouting:
    def test_uploads_json_with_required_keys(self, gcp: GcpConfig) -> None:
        blob = MagicMock()
        with patch(
            "wiseman_hub.cloud.mapping_sync.storage.Client.from_service_account_json",
            _make_storage_mock(blob),
        ):
            uri = push_routing(gcp, {"居宅A": "FAX A", "居宅B": "FAX B"})
        assert uri == f"gs://test-bucket/{MAPPING_BLOB_PATH}"
        args, kwargs = blob.upload_from_string.call_args
        body = json.loads(args[0])
        assert body["version"] == "1"
        assert "generated_at" in body
        assert body["mappings"] == {"居宅A": "FAX A", "居宅B": "FAX B"}
        assert kwargs["content_type"] == "application/json; charset=utf-8"

    def test_raises_mapping_sync_error_on_gcs_failure(self, gcp: GcpConfig) -> None:
        blob = MagicMock()
        blob.upload_from_string.side_effect = gcs_exc.Forbidden("denied")
        with patch(
            "wiseman_hub.cloud.mapping_sync.storage.Client.from_service_account_json",
            _make_storage_mock(blob),
        ), pytest.raises(MappingSyncError, match="push failed"):
            push_routing(gcp, {"居宅A": "FAX A"})


class TestPullRouting:
    def test_returns_dict_from_valid_json(self, gcp: GcpConfig) -> None:
        blob = MagicMock()
        blob.download_as_bytes.return_value = json.dumps(
            {
                "version": "1",
                "generated_at": "2026-05-01T12:00:00+09:00",
                "mappings": {"居宅A": "FAX A", "居宅B": "FAX B"},
            },
            ensure_ascii=False,
        ).encode("utf-8")
        with patch(
            "wiseman_hub.cloud.mapping_sync.storage.Client.from_service_account_json",
            _make_storage_mock(blob),
        ):
            result = pull_routing(gcp)
        assert result == {"居宅A": "FAX A", "居宅B": "FAX B"}

    def test_raises_not_found_subclass_when_blob_absent(self, gcp: GcpConfig) -> None:
        """初回利用ガイダンスで識別するため MappingNotFoundError 専用例外。"""
        blob = MagicMock()
        blob.download_as_bytes.side_effect = gcs_exc.NotFound("absent")
        with patch(
            "wiseman_hub.cloud.mapping_sync.storage.Client.from_service_account_json",
            _make_storage_mock(blob),
        ), pytest.raises(MappingNotFoundError):
            pull_routing(gcp)
        # MappingNotFoundError は MappingSyncError のサブクラスでもある
        assert issubclass(MappingNotFoundError, MappingSyncError)

    def test_raises_on_invalid_json(self, gcp: GcpConfig) -> None:
        blob = MagicMock()
        blob.download_as_bytes.return_value = b"not a json{"
        with patch(
            "wiseman_hub.cloud.mapping_sync.storage.Client.from_service_account_json",
            _make_storage_mock(blob),
        ), pytest.raises(MappingSyncError, match="invalid JSON"):
            pull_routing(gcp)

    def test_raises_when_mappings_missing(self, gcp: GcpConfig) -> None:
        blob = MagicMock()
        blob.download_as_bytes.return_value = json.dumps(
            {"version": "1", "generated_at": "x"}
        ).encode("utf-8")
        with patch(
            "wiseman_hub.cloud.mapping_sync.storage.Client.from_service_account_json",
            _make_storage_mock(blob),
        ), pytest.raises(MappingSyncError, match="mappings"):
            pull_routing(gcp)

    def test_raises_on_unsupported_schema_version(self, gcp: GcpConfig) -> None:
        """過去失敗対策（codex MEDIUM-4）: schema version 不一致は静かに受け入れない。"""
        blob = MagicMock()
        blob.download_as_bytes.return_value = json.dumps(
            {"version": "99", "mappings": {"a": "b"}}
        ).encode("utf-8")
        with patch(
            "wiseman_hub.cloud.mapping_sync.storage.Client.from_service_account_json",
            _make_storage_mock(blob),
        ), pytest.raises(MappingSyncError, match="schema version"):
            pull_routing(gcp)

    def test_raises_when_version_missing(self, gcp: GcpConfig) -> None:
        """version キー不在は SCHEMA_VERSION 不一致として弾く。"""
        blob = MagicMock()
        blob.download_as_bytes.return_value = json.dumps(
            {"mappings": {"a": "b"}}
        ).encode("utf-8")
        with patch(
            "wiseman_hub.cloud.mapping_sync.storage.Client.from_service_account_json",
            _make_storage_mock(blob),
        ), pytest.raises(MappingSyncError, match="schema version"):
            pull_routing(gcp)

    def test_raises_on_non_string_value(self, gcp: GcpConfig) -> None:
        blob = MagicMock()
        blob.download_as_bytes.return_value = json.dumps(
            {"version": "1", "mappings": {"居宅A": 123}}
        ).encode("utf-8")
        with patch(
            "wiseman_hub.cloud.mapping_sync.storage.Client.from_service_account_json",
            _make_storage_mock(blob),
        ), pytest.raises(MappingSyncError, match="str -> str"):
            pull_routing(gcp)


class TestRoundTrip:
    """push → pull で内容が完全に保存されることの保証（閉ループ確認の基礎）。"""

    def test_push_then_pull_returns_same_dict(self, gcp: GcpConfig) -> None:
        blob = MagicMock()
        captured: dict[str, bytes] = {}

        def upload(s: str, **_: object) -> None:
            captured["body"] = s.encode("utf-8")

        def download(**_: object) -> bytes:
            return captured["body"]

        blob.upload_from_string.side_effect = upload
        blob.download_as_bytes.side_effect = download
        with patch(
            "wiseman_hub.cloud.mapping_sync.storage.Client.from_service_account_json",
            _make_storage_mock(blob),
        ):
            original = {"居宅A": "FAX A(メール)", "居宅B": "FAX B（FAX）※持参"}
            push_routing(gcp, original)
            recovered = pull_routing(gcp)
        assert recovered == original


# ---------------------------------------------------------------------------
# PR-β v1: report_staff の GCS 同期テスト
# ---------------------------------------------------------------------------


class TestPushReportStaff:
    def test_uploads_json_with_required_keys(self, gcp: GcpConfig) -> None:
        blob = MagicMock()
        original = {
            "宮下": ReportStaffEntry(
                base_dir=Path("\\\\Tera-station\\share\\PT 宮下"),
                suggest_patterns=["リハ経過報告書/令和{era}年/*{month}月*.xlsx"],
            ),
            "小林": ReportStaffEntry(
                base_dir=Path("\\\\Tera-station\\share\\OT小林"),
                suggest_patterns=["経過報告書/R{era}/*{month}月*.xlsx"],
            ),
        }
        with patch(
            "wiseman_hub.cloud.mapping_sync.storage.Client.from_service_account_json",
            _make_storage_mock(blob),
        ):
            uri = push_report_staff(gcp, original)
        assert uri == f"gs://test-bucket/{REPORT_STAFF_BLOB_PATH}"
        args, kwargs = blob.upload_from_string.call_args
        body = json.loads(args[0])
        assert body["version"] == "1"
        assert "generated_at" in body
        assert set(body["staff"].keys()) == {"宮下", "小林"}
        # Issue #27 続編 G Phase 3b: JSON body は str 維持 (push 側で str(Path) 変換)。
        assert body["staff"]["宮下"]["base_dir"] == str(original["宮下"].base_dir)
        assert (
            body["staff"]["宮下"]["suggest_patterns"]
            == original["宮下"].suggest_patterns
        )
        assert kwargs["content_type"] == "application/json; charset=utf-8"

    def test_validates_gcp_before_upload(self, fake_sa_key: Path) -> None:
        bad = GcpConfig(
            project_id="",
            bucket_name="b",
            service_account_key_path=fake_sa_key,
        )
        with pytest.raises(MappingConfigError, match="project_id"):
            push_report_staff(bad, {"宮下": ReportStaffEntry()})

    def test_raises_mapping_sync_error_on_gcs_failure(self, gcp: GcpConfig) -> None:
        blob = MagicMock()
        blob.upload_from_string.side_effect = gcs_exc.Forbidden("denied")
        with patch(
            "wiseman_hub.cloud.mapping_sync.storage.Client.from_service_account_json",
            _make_storage_mock(blob),
        ), pytest.raises(MappingSyncError, match="push failed"):
            push_report_staff(gcp, {"宮下": ReportStaffEntry()})


class TestPullReportStaff:
    def test_returns_dict_from_valid_json(self, gcp: GcpConfig) -> None:
        blob = MagicMock()
        blob.download_as_bytes.return_value = json.dumps(
            {
                "version": "1",
                "generated_at": "2026-05-05T12:00:00+09:00",
                "staff": {
                    "宮下": {
                        "base_dir": "\\\\Tera-station\\share\\PT 宮下",
                        "suggest_patterns": [
                            "リハ経過報告書/令和{era}年/*{month}月*.xlsx",
                        ],
                    },
                },
            },
            ensure_ascii=False,
        ).encode("utf-8")
        with patch(
            "wiseman_hub.cloud.mapping_sync.storage.Client.from_service_account_json",
            _make_storage_mock(blob),
        ):
            result = pull_report_staff(gcp)
        assert set(result.keys()) == {"宮下"}
        # Issue #27 続編 G Phase 3b: pull 経由で Path 型に変換される (coerce_path)。
        assert result["宮下"].base_dir == Path("\\\\Tera-station\\share\\PT 宮下")
        assert result["宮下"].suggest_patterns == [
            "リハ経過報告書/令和{era}年/*{month}月*.xlsx"
        ]

    def test_raises_not_found_when_blob_absent(self, gcp: GcpConfig) -> None:
        """初回利用ガイダンスで識別するため MappingNotFoundError 専用例外。"""
        blob = MagicMock()
        blob.download_as_bytes.side_effect = gcs_exc.NotFound("absent")
        with patch(
            "wiseman_hub.cloud.mapping_sync.storage.Client.from_service_account_json",
            _make_storage_mock(blob),
        ), pytest.raises(MappingNotFoundError):
            pull_report_staff(gcp)

    def test_raises_on_invalid_json(self, gcp: GcpConfig) -> None:
        blob = MagicMock()
        blob.download_as_bytes.return_value = b"not a json{"
        with patch(
            "wiseman_hub.cloud.mapping_sync.storage.Client.from_service_account_json",
            _make_storage_mock(blob),
        ), pytest.raises(MappingSyncError, match="invalid JSON"):
            pull_report_staff(gcp)

    def test_raises_on_unsupported_schema_version(self, gcp: GcpConfig) -> None:
        blob = MagicMock()
        blob.download_as_bytes.return_value = json.dumps(
            {"version": "99", "staff": {}}
        ).encode("utf-8")
        with patch(
            "wiseman_hub.cloud.mapping_sync.storage.Client.from_service_account_json",
            _make_storage_mock(blob),
        ), pytest.raises(MappingSyncError, match="schema version"):
            pull_report_staff(gcp)

    def test_raises_when_staff_missing(self, gcp: GcpConfig) -> None:
        blob = MagicMock()
        blob.download_as_bytes.return_value = json.dumps(
            {"version": "1", "generated_at": "x"}
        ).encode("utf-8")
        with patch(
            "wiseman_hub.cloud.mapping_sync.storage.Client.from_service_account_json",
            _make_storage_mock(blob),
        ), pytest.raises(MappingSyncError, match="staff"):
            pull_report_staff(gcp)

    def test_raises_when_suggest_patterns_not_list(self, gcp: GcpConfig) -> None:
        blob = MagicMock()
        blob.download_as_bytes.return_value = json.dumps(
            {
                "version": "1",
                "staff": {"宮下": {"base_dir": "x", "suggest_patterns": "not list"}},
            }
        ).encode("utf-8")
        with patch(
            "wiseman_hub.cloud.mapping_sync.storage.Client.from_service_account_json",
            _make_storage_mock(blob),
        ), pytest.raises(MappingSyncError, match="suggest_patterns must be a list"):
            pull_report_staff(gcp)

    def test_raises_when_suggest_pattern_element_not_str(
        self, gcp: GcpConfig
    ) -> None:
        blob = MagicMock()
        blob.download_as_bytes.return_value = json.dumps(
            {
                "version": "1",
                "staff": {"宮下": {"base_dir": "x", "suggest_patterns": [1]}},
            }
        ).encode("utf-8")
        with patch(
            "wiseman_hub.cloud.mapping_sync.storage.Client.from_service_account_json",
            _make_storage_mock(blob),
        ), pytest.raises(MappingSyncError, match="elements must be str"):
            pull_report_staff(gcp)


class TestReportStaffRoundTrip:
    def test_push_then_pull_returns_same_entries(self, gcp: GcpConfig) -> None:
        blob = MagicMock()
        captured: dict[str, bytes] = {}

        def upload(s: str, **_: object) -> None:
            captured["body"] = s.encode("utf-8")

        def download(**_: object) -> bytes:
            return captured["body"]

        blob.upload_from_string.side_effect = upload
        blob.download_as_bytes.side_effect = download
        original = {
            "宮下": ReportStaffEntry(
                base_dir=Path("\\\\Tera-station\\share\\PT 宮下"),
                suggest_patterns=[
                    "リハ経過報告書/令和{era}年/リハ経過報告書*{month}月*.xlsx",
                ],
            ),
            "小林": ReportStaffEntry(
                base_dir=Path("\\\\Tera-station\\share\\OT小林"),
                suggest_patterns=["経過報告書/R{era}/*{month}月*.xlsx"],
            ),
        }
        with patch(
            "wiseman_hub.cloud.mapping_sync.storage.Client.from_service_account_json",
            _make_storage_mock(blob),
        ):
            push_report_staff(gcp, original)
            recovered = pull_report_staff(gcp)
        assert set(recovered.keys()) == set(original.keys())
        for name, entry in original.items():
            assert recovered[name].base_dir == entry.base_dir
            assert recovered[name].suggest_patterns == entry.suggest_patterns
