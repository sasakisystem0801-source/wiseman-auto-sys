"""audit_uploader.scan_and_upload / process_jsonl の単体テスト（GCS は mock）。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from google.api_core import exceptions as gcs_exc

from wiseman_hub.cloud.audit_uploader import (
    AuditUploadConfigError,
    _content_hash,
    _gcs_object_name,
    _normalize_line,
    process_jsonl,
    scan_and_upload,
    start_audit_uploader,
    stop_audit_uploader,
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
        service_account_key_path=fake_sa_key,
    )


@pytest.fixture
def gcp_legacy_bucket_only(fake_sa_key: Path) -> GcpConfig:
    """旧 bucket_name のみ設定（backward compat 検証）。"""
    return GcpConfig(
        project_id="test-proj",
        bucket_name="legacy-bucket",
        service_account_key_path=fake_sa_key,
    )


def _make_audit_file(tmp_path: Path, kind: str, date: str, records: list[dict]) -> Path:
    """audit jsonl を作成する helper。"""
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    jsonl = audit_dir / f"{kind}_{date}.jsonl"
    lines = [json.dumps(r, ensure_ascii=False) for r in records]
    jsonl.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return jsonl


def _make_mock_client() -> tuple[MagicMock, MagicMock]:
    """mock storage.Client + bucket を返す。"""
    bucket = MagicMock()
    blob = MagicMock()
    bucket.blob.return_value = blob
    client = MagicMock()
    client.bucket.return_value = bucket
    return client, blob


class TestContentHash:
    def test_same_content_same_hash(self) -> None:
        line = '{"user": "森川 ひろゑ", "status": "success"}'
        assert _content_hash(line) == _content_hash(line)

    def test_different_content_different_hash(self) -> None:
        a = '{"user": "森川 ひろゑ"}'
        b = '{"user": "森澤 フミ子"}'
        assert _content_hash(a) != _content_hash(b)

    def test_hash_length_32(self) -> None:
        h = _content_hash("any line")
        assert len(h) == 32
        # hex 文字のみ
        int(h, 16)


class TestGcsObjectName:
    def test_format(self) -> None:
        name = _gcs_object_name("c_placement", "2026-05-06", "abc123")
        assert name == "audit/c_placement/2026-05-06/abc123.json"


class TestValidateGcp:
    """過去失敗対策: GCP 設定不足を実 API 呼び出し前に弾く。"""

    def test_empty_project_id_raises(self, fake_sa_key: Path, tmp_path: Path) -> None:
        gcp = GcpConfig(
            project_id="",
            data_bucket_name="b",
            service_account_key_path=fake_sa_key,
        )
        # log_dir + audit ディレクトリがあると進むので、空 dir で start_audit_uploader 経由
        result = start_audit_uploader(tmp_path, gcp)
        assert result is None  # validate 失敗で thread 起動せず

    def test_empty_data_bucket_raises(self, fake_sa_key: Path, tmp_path: Path) -> None:
        gcp = GcpConfig(
            project_id="p",
            data_bucket_name="",
            bucket_name="",  # backward compat fallback も空
            service_account_key_path=fake_sa_key,
        )
        # audit/ ディレクトリを作って validate を必ず通すようにする
        _make_audit_file(tmp_path, "c_placement", "2026-05-06", [{"a": 1}])
        with pytest.raises(AuditUploadConfigError, match="data_bucket"):
            scan_and_upload(tmp_path, gcp, client=MagicMock())

    def test_missing_sa_key_raises(self, tmp_path: Path) -> None:
        gcp = GcpConfig(
            project_id="p",
            data_bucket_name="b",
            service_account_key_path=tmp_path / "no-such.json",
        )
        _make_audit_file(tmp_path, "c_placement", "2026-05-06", [{"a": 1}])
        with pytest.raises(AuditUploadConfigError, match="not found"):
            scan_and_upload(tmp_path, gcp, client=MagicMock())


class TestBackwardCompat:
    """ADR-016 で追加された data_bucket_name の backward compat 動作。"""

    def test_data_bucket_takes_precedence(self, fake_sa_key: Path) -> None:
        gcp = GcpConfig(
            project_id="p",
            bucket_name="legacy",
            data_bucket_name="new-data",
            service_account_key_path=fake_sa_key,
        )
        assert gcp.effective_data_bucket == "new-data"

    def test_bucket_name_fallback_when_data_empty(self, fake_sa_key: Path) -> None:
        gcp = GcpConfig(
            project_id="p",
            bucket_name="legacy",
            data_bucket_name="",
            service_account_key_path=fake_sa_key,
        )
        assert gcp.effective_data_bucket == "legacy"


class TestProcessJsonl:
    def test_uploads_all_records_first_run(self, tmp_path: Path, gcp: GcpConfig) -> None:
        records = [
            {"user": "A", "status": "success"},
            {"user": "B", "status": "success"},
        ]
        jsonl = _make_audit_file(tmp_path, "c_placement", "2026-05-06", records)
        client, blob = _make_mock_client()

        uploaded, skipped, errors = process_jsonl(jsonl, gcp, client=client)

        assert uploaded == 2
        assert skipped == 0
        assert errors == 0
        assert blob.upload_from_string.call_count == 2
        # sidecar が作成され、2 hash が記録されている
        marker = jsonl.with_suffix(".uploaded")
        assert marker.exists()
        assert len(marker.read_text().strip().splitlines()) == 2

    def test_skips_already_uploaded_records(
        self, tmp_path: Path, gcp: GcpConfig
    ) -> None:
        records = [{"user": "A"}, {"user": "B"}]
        jsonl = _make_audit_file(tmp_path, "c_placement", "2026-05-06", records)
        # 1 件目は既に upload 済として sidecar に記録
        marker = jsonl.with_suffix(".uploaded")
        first_hash = _content_hash(json.dumps(records[0], ensure_ascii=False))
        marker.write_text(first_hash + "\n", encoding="utf-8")

        client, blob = _make_mock_client()
        uploaded, skipped, errors = process_jsonl(jsonl, gcp, client=client)

        assert uploaded == 1  # B のみ
        assert skipped == 1  # A は sidecar 経由で skip
        assert errors == 0
        assert blob.upload_from_string.call_count == 1

    def test_412_treated_as_skipped_idempotent(
        self, tmp_path: Path, gcp: GcpConfig
    ) -> None:
        """既存 GCS object と同名 → 412 PreconditionFailed → 治癒扱い (skip)。"""
        records = [{"user": "A"}]
        jsonl = _make_audit_file(tmp_path, "c_placement", "2026-05-06", records)

        client, blob = _make_mock_client()
        blob.upload_from_string.side_effect = gcs_exc.PreconditionFailed(
            "Object already exists"
        )

        uploaded, skipped, errors = process_jsonl(jsonl, gcp, client=client)

        assert uploaded == 0
        assert skipped == 1  # 412 を治癒として skip 扱い
        assert errors == 0
        # sidecar には 412 でも hash を記録（次回はスキップで 412 even 起こさない）
        marker = jsonl.with_suffix(".uploaded")
        assert marker.exists()

    def test_network_error_breaks_loop(
        self, tmp_path: Path, gcp: GcpConfig
    ) -> None:
        """GoogleAPIError → AuditUploadError → loop break、残 record は次回 retry。"""
        records = [{"user": "A"}, {"user": "B"}]
        jsonl = _make_audit_file(tmp_path, "c_placement", "2026-05-06", records)

        client, blob = _make_mock_client()
        blob.upload_from_string.side_effect = gcs_exc.ServiceUnavailable(
            "Service unavailable"
        )

        uploaded, skipped, errors = process_jsonl(jsonl, gcp, client=client)

        assert uploaded == 0
        assert errors == 1  # 1 件目で失敗 → break
        # B は処理されない（次 scan で retry）
        assert blob.upload_from_string.call_count == 1

    def test_invalid_filename_returns_zero(
        self, tmp_path: Path, gcp: GcpConfig
    ) -> None:
        # filename pattern 不一致 → no-op
        bad = tmp_path / "audit" / "garbage.txt"
        bad.parent.mkdir(parents=True)
        bad.write_text("[]", encoding="utf-8")

        client, _ = _make_mock_client()
        result = process_jsonl(bad, gcp, client=client)
        assert result == (0, 0, 0)

    def test_empty_lines_ignored(self, tmp_path: Path, gcp: GcpConfig) -> None:
        jsonl = tmp_path / "audit" / "c_placement_2026-05-06.jsonl"
        jsonl.parent.mkdir(parents=True)
        jsonl.write_text(
            '\n{"a": 1}\n\n{"b": 2}\n\n', encoding="utf-8"
        )
        client, blob = _make_mock_client()
        uploaded, skipped, errors = process_jsonl(jsonl, gcp, client=client)
        assert uploaded == 2
        assert errors == 0


class TestScanAndUpload:
    def test_no_log_dir_noop(self, gcp: GcpConfig) -> None:
        # Issue #27 続編 G §4: log_dir は Path 型、未設定は Path("")
        result = scan_and_upload(Path(""), gcp, client=MagicMock())
        assert result["files"] == 0

    def test_no_audit_dir_noop(self, tmp_path: Path, gcp: GcpConfig) -> None:
        # log_dir はあるが audit/ はない
        result = scan_and_upload(tmp_path, gcp, client=MagicMock())
        assert result["files"] == 0

    def test_aggregate_multiple_files(
        self, tmp_path: Path, gcp: GcpConfig
    ) -> None:
        _make_audit_file(tmp_path, "c_placement", "2026-05-05", [{"a": 1}])
        _make_audit_file(tmp_path, "c_placement", "2026-05-06", [{"b": 1}, {"b": 2}])
        _make_audit_file(tmp_path, "b_placement", "2026-05-06", [{"c": 1}])

        client, _ = _make_mock_client()
        result = scan_and_upload(tmp_path, gcp, client=client)

        assert result["files"] == 3
        assert result["uploaded"] == 4  # 1 + 2 + 1
        assert result["errors"] == 0

    def test_idempotent_second_run(
        self, tmp_path: Path, gcp: GcpConfig
    ) -> None:
        """同じ log_dir に対して 2 回 scan しても、2 回目は全 skip。"""
        _make_audit_file(tmp_path, "c_placement", "2026-05-06", [{"x": 1}])

        client, _ = _make_mock_client()
        first = scan_and_upload(tmp_path, gcp, client=client)
        second = scan_and_upload(tmp_path, gcp, client=client)

        assert first["uploaded"] == 1
        assert second["uploaded"] == 0
        assert second["skipped"] == 1


class TestStartAuditUploader:
    def test_disabled_when_no_log_dir(self, gcp: GcpConfig) -> None:
        # Issue #27 続編 G §4: log_dir は Path 型、未設定は Path("")
        result = start_audit_uploader(Path(""), gcp)
        assert result is None

    def test_disabled_when_invalid_gcp(self, tmp_path: Path) -> None:
        bad_gcp = GcpConfig()  # all empty
        result = start_audit_uploader(tmp_path, bad_gcp)
        assert result is None

    def test_starts_thread_when_valid(
        self, tmp_path: Path, gcp: GcpConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # _client を mock 化して実 GCS 接続を防ぐ
        from wiseman_hub.cloud import audit_uploader

        monkeypatch.setattr(audit_uploader, "_client", lambda g: _make_mock_client()[0])

        thread = start_audit_uploader(tmp_path, gcp, interval_sec=3600)
        assert thread is not None
        assert thread.daemon
        assert thread.is_alive()
        # クリーンアップ: 後続テストへの干渉を防ぐため shutdown
        stop_audit_uploader()
        thread.join(timeout=5)


class TestNormalizeLine:
    """review C-1 対策: hash 計算と upload の正規化責務集約。"""

    def test_strips_whitespace(self) -> None:
        assert _normalize_line("  {\"a\":1}  ") == '{"a":1}'

    def test_strips_bom(self) -> None:
        assert _normalize_line("﻿{\"a\":1}") == '{"a":1}'

    def test_empty_after_strip(self) -> None:
        assert _normalize_line("   \t\n  ") == ""

    def test_preserves_internal_content(self) -> None:
        assert _normalize_line('{"a": "  spaced  "}') == '{"a": "  spaced  "}'


class TestPartialLineHandling:
    """review C-1: audit.py が append 中の partial line を upload しない。"""

    def test_skips_last_line_without_newline(
        self, tmp_path: Path, gcp: GcpConfig
    ) -> None:
        """末尾 \\n が無い = まだ append 中 → 最終行を除外。"""
        jsonl = tmp_path / "audit" / "c_placement_2026-05-06.jsonl"
        jsonl.parent.mkdir(parents=True)
        # 1 行目は完了、2 行目は途中（\n なし）
        jsonl.write_text(
            '{"complete": 1}\n{"incomplet',
            encoding="utf-8",
        )
        client, blob = _make_mock_client()
        uploaded, skipped, errors = process_jsonl(jsonl, gcp, client=client)
        assert uploaded == 1  # 完了行のみ
        assert errors == 0
        assert blob.upload_from_string.call_count == 1

    def test_processes_all_lines_when_complete(
        self, tmp_path: Path, gcp: GcpConfig
    ) -> None:
        """末尾 \\n あり = 全行 append 完了 → 全 record 処理。"""
        jsonl = tmp_path / "audit" / "c_placement_2026-05-06.jsonl"
        jsonl.parent.mkdir(parents=True)
        jsonl.write_text(
            '{"a": 1}\n{"b": 2}\n',
            encoding="utf-8",
        )
        client, _ = _make_mock_client()
        uploaded, _, errors = process_jsonl(jsonl, gcp, client=client)
        assert uploaded == 2
        assert errors == 0

    def test_single_partial_line_returns_zero(
        self, tmp_path: Path, gcp: GcpConfig
    ) -> None:
        """1 行のみで未完成 → 全 skip（0,0,0）。"""
        jsonl = tmp_path / "audit" / "c_placement_2026-05-06.jsonl"
        jsonl.parent.mkdir(parents=True)
        jsonl.write_text('{"unfinished":', encoding="utf-8")
        client, blob = _make_mock_client()
        result = process_jsonl(jsonl, gcp, client=client)
        assert result == (0, 0, 0)
        assert blob.upload_from_string.call_count == 0


class TestUnicodeDecodeError:
    """review I-3: 不正 byte の jsonl を skip して他 file の処理を止めない。"""

    def test_invalid_utf8_returns_zero(
        self, tmp_path: Path, gcp: GcpConfig
    ) -> None:
        jsonl = tmp_path / "audit" / "c_placement_2026-05-06.jsonl"
        jsonl.parent.mkdir(parents=True)
        # 不正 UTF-8 byte (0x80 単独)
        jsonl.write_bytes(b"\x80\x81\n")
        client, _ = _make_mock_client()
        result = process_jsonl(jsonl, gcp, client=client)
        assert result == (0, 0, 0)


class TestSidecarFailureAbort:
    """review I-1: sidecar 書込失敗時に file 処理を中止して retry storm を防ぐ。"""

    def test_aborts_file_when_marker_write_fails(
        self,
        tmp_path: Path,
        gcp: GcpConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        records = [{"a": 1}, {"b": 2}, {"c": 3}]
        jsonl = _make_audit_file(tmp_path, "c_placement", "2026-05-06", records)
        client, _ = _make_mock_client()

        # _append_uploaded_hash を常に False (失敗) を返すよう mock
        from wiseman_hub.cloud import audit_uploader

        monkeypatch.setattr(
            audit_uploader,
            "_append_uploaded_hash",
            lambda marker, h: False,
        )

        uploaded, skipped, errors = process_jsonl(jsonl, gcp, client=client)
        # 1 件目を upload した後 sidecar 失敗 → break、残 2 件は次 scan
        assert uploaded == 1
        assert errors == 1


class TestEarlyValidation:
    """review I-2: audit dir 不存在でも GCP 設定不備は fail-fast で検出。"""

    def test_validates_gcp_before_audit_dir_check(
        self, tmp_path: Path, fake_sa_key: Path
    ) -> None:
        """audit dir が無くても、GCP 設定が壊れていれば error を投げる。"""
        bad_gcp = GcpConfig(
            project_id="",  # 不備
            data_bucket_name="b",
            service_account_key_path=fake_sa_key,
        )
        # audit/ は作らない → 旧実装なら early return で validate がスキップされた
        with pytest.raises(AuditUploadConfigError, match="project_id"):
            scan_and_upload(tmp_path, bad_gcp, client=MagicMock())
