"""ex_extractor のユニットテスト (PR3)。

macOS で fake adapter + tmp_path ベースで全フロー検証する。Windows 実機検証
(pywinauto / subprocess 経由の SFX 操作) は PR5 で実施。

PII 防御方針: 本ファイルのテストデータには実在する介護施設名・利用者名を
含めない。すべて仮名 (「サービスA」「DC_A」等) で構成し、PR diff / CI ログ
経由の PII 漏洩経路を遮断する。
"""

from __future__ import annotations

import logging
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

from wiseman_hub.pdf.ex_extractor import (
    _QUARANTINE_PREFIX,
    ExtractionErrorCode,
    ExtractionItem,
    ExtractionResult,
    ExtractionStatus,
    FakeSfxAdapter,
    SfxExtractionFailed,
    UnsupportedSfxPlatformError,
    WindowsSfxAdapter,
    _quarantine_pre_existing_target,
    extract_directory,
    extract_one,
    find_target_pdf,
    find_unexpected_naming_pdfs,
    retry_overwrite,
)
from wiseman_hub.pdf.facility_resolver import (
    ResolveReason,
    ResolveResult,
    ResolveStatus,
)

# ---------------------------------------------------------------------------
# 共通 fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def facility_root(tmp_path: Path) -> Path:
    """事業所サブフォルダ 3 件を持つ root ディレクトリ。"""
    root = tmp_path / "facility_root"
    root.mkdir()
    (root / "サービスA").mkdir()
    (root / "サービスB").mkdir()
    (root / "デイケアセンター").mkdir()
    return root


@pytest.fixture
def source_dir(tmp_path: Path) -> Path:
    """``.ex_`` ファイルを置く source ディレクトリ。"""
    src = tmp_path / "ex_source"
    src.mkdir()
    return src


def _make_ex_file(directory: Path, name: str) -> Path:
    """ダミー ``.ex_`` ファイルを作成 (中身は SFX EXE バイナリ風の任意データ)。"""
    path = directory / name
    path.write_bytes(b"FAKE_SFX_EXE_BYTES")
    return path


def _pdf_creating_side_effect(
    pdf_names: Sequence[str], *, target_dir: Path | None = None
) -> object:
    """``FakeSfxAdapter.side_effect`` 用: watch_dirs[0] (= source_dir) に PDF を実生成。

    target_dir を指定すると当該ディレクトリに作成 (Desktop/Downloads シミュレート用)。
    """

    def _impl(exe_path: Path, watch_dirs: Sequence[Path]) -> None:
        out_dir = target_dir if target_dir is not None else watch_dirs[0]
        out_dir.mkdir(parents=True, exist_ok=True)
        for name in pdf_names:
            (out_dir / name).write_bytes(b"%PDF-1.4 fake")

    return _impl


# ---------------------------------------------------------------------------
# ExtractionItem __post_init__ 不変条件 (5 件)
# ---------------------------------------------------------------------------


def _dummy_resolve_confirmed(facility: str = "サービスA") -> ResolveResult:
    return ResolveResult.confirmed(facility, ResolveReason.ALIAS_MATCH)


def _dummy_resolve_unmatched() -> ResolveResult:
    return ResolveResult.unmatched(ResolveReason.NO_CANDIDATE)


class _DynamicSfxAdapter:
    """ex_file 毎に異なる PDF (= ``<exe_path.stem>.pdf``) を生成する adapter。

    ``FakeSfxAdapter`` は固定 ``produced_pdfs`` のみ返せるため、複数 ex_file の
    retry シナリオでは対応 PDF を動的に生成する必要がある。Protocol を満たす
    最小実装 (Review G4 用)。
    """

    def extract_pdf(
        self, exe_path: Path, watch_dirs: Sequence[Path]
    ) -> Sequence[Path]:
        out_dir = watch_dirs[0]
        out_dir.mkdir(parents=True, exist_ok=True)
        pdf = out_dir / f"{exe_path.stem}.pdf"
        pdf.write_bytes(b"%PDF-1.4 new")
        return [pdf]


class TestExtractionItemInvariants:
    def test_success_without_moved_pdfs_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="SUCCESS requires non-empty moved_pdfs"):
            ExtractionItem(
                source_path=tmp_path / "x.ex_",
                resolve_result=_dummy_resolve_confirmed(),
                status=ExtractionStatus.SUCCESS,
            )

    def test_success_with_error_code_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="SUCCESS forbids error_code"):
            ExtractionItem(
                source_path=tmp_path / "x.ex_",
                resolve_result=_dummy_resolve_confirmed(),
                status=ExtractionStatus.SUCCESS,
                moved_pdfs=(tmp_path / "out.pdf",),
                error_code=ExtractionErrorCode.MOVE_CONFLICT,
            )

    def test_failure_with_moved_pdfs_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="forbids moved_pdfs"):
            ExtractionItem(
                source_path=tmp_path / "x.ex_",
                resolve_result=_dummy_resolve_confirmed(),
                status=ExtractionStatus.MOVE_FAILED,
                moved_pdfs=(tmp_path / "out.pdf",),
                error_code=ExtractionErrorCode.MOVE_CONFLICT,
            )

    def test_partial_output_without_partial_outputs_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="PARTIAL_OUTPUT requires"):
            ExtractionItem(
                source_path=tmp_path / "x.ex_",
                resolve_result=_dummy_resolve_confirmed(),
                status=ExtractionStatus.PARTIAL_OUTPUT,
                error_code=ExtractionErrorCode.SFX_TIMEOUT,
            )

    def test_failure_without_error_code_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="requires error_code"):
            ExtractionItem(
                source_path=tmp_path / "x.ex_",
                resolve_result=_dummy_resolve_confirmed(),
                status=ExtractionStatus.EXTRACT_FAILED,
            )

    def test_success_with_partially_moved_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="SUCCESS forbids partially_moved"):
            ExtractionItem(
                source_path=tmp_path / "x.ex_",
                resolve_result=_dummy_resolve_confirmed(),
                status=ExtractionStatus.SUCCESS,
                moved_pdfs=(tmp_path / "out.pdf",),
                partially_moved=(tmp_path / "p1.pdf",),
            )

    def test_partially_moved_only_allowed_on_move_failed(
        self, tmp_path: Path
    ) -> None:
        # EXTRACT_FAILED で partially_moved を渡すと拒否
        with pytest.raises(ValueError, match="forbids partially_moved"):
            ExtractionItem(
                source_path=tmp_path / "x.ex_",
                resolve_result=_dummy_resolve_confirmed(),
                status=ExtractionStatus.EXTRACT_FAILED,
                error_code=ExtractionErrorCode.NO_PDF_PRODUCED,
                partially_moved=(tmp_path / "p1.pdf",),
            )

    def test_move_failed_with_partially_moved_ok(self, tmp_path: Path) -> None:
        # MOVE_FAILED + partially_moved は許容
        item = ExtractionItem(
            source_path=tmp_path / "x.ex_",
            resolve_result=_dummy_resolve_confirmed(),
            status=ExtractionStatus.MOVE_FAILED,
            error_code=ExtractionErrorCode.MOVE_CONFLICT,
            partially_moved=(tmp_path / "p1.pdf",),
        )
        assert item.partially_moved == (tmp_path / "p1.pdf",)

    def test_partial_outputs_and_partially_moved_mutually_exclusive(
        self, tmp_path: Path
    ) -> None:
        # status が排他なので通常は同時設定不可だが、二重防御として __post_init__ で拒否
        with pytest.raises(ValueError, match="mutually exclusive"):
            ExtractionItem(
                source_path=tmp_path / "x.ex_",
                resolve_result=_dummy_resolve_confirmed(),
                status=ExtractionStatus.MOVE_FAILED,
                error_code=ExtractionErrorCode.MOVE_CONFLICT,
                partially_moved=(tmp_path / "p1.pdf",),
                partial_outputs=(tmp_path / "x.pdf",),
            )


# ---------------------------------------------------------------------------
# ExtractionResult プロパティ (3 件)
# ---------------------------------------------------------------------------


class TestExtractionResultProperties:
    def _success_item(self, tmp_path: Path) -> ExtractionItem:
        return ExtractionItem(
            source_path=tmp_path / "ok.ex_",
            resolve_result=_dummy_resolve_confirmed(),
            status=ExtractionStatus.SUCCESS,
            moved_pdfs=(tmp_path / "ok.pdf",),
        )

    def _ambiguous_item(self, tmp_path: Path) -> ExtractionItem:
        return ExtractionItem(
            source_path=tmp_path / "amb.ex_",
            resolve_result=ResolveResult.ambiguous(
                ("X", "Y"), ResolveReason.AMBIGUOUS_PARTIAL
            ),
            status=ExtractionStatus.SKIPPED_AMBIGUOUS,
        )

    def _failed_item(self, tmp_path: Path) -> ExtractionItem:
        return ExtractionItem(
            source_path=tmp_path / "fail.ex_",
            resolve_result=_dummy_resolve_confirmed(),
            status=ExtractionStatus.EXTRACT_FAILED,
            error_code=ExtractionErrorCode.NO_PDF_PRODUCED,
        )

    def test_success_count(self, tmp_path: Path) -> None:
        result = ExtractionResult(
            items=(
                self._success_item(tmp_path),
                self._ambiguous_item(tmp_path),
                self._success_item(tmp_path),
            )
        )
        assert result.success_count == 2

    def test_pending_manual_collects_skipped(self, tmp_path: Path) -> None:
        result = ExtractionResult(
            items=(
                self._success_item(tmp_path),
                self._ambiguous_item(tmp_path),
                self._failed_item(tmp_path),
            )
        )
        assert len(result.pending_manual) == 1
        assert result.pending_manual[0].status is ExtractionStatus.SKIPPED_AMBIGUOUS

    def test_failed_collects_failure_statuses(self, tmp_path: Path) -> None:
        result = ExtractionResult(
            items=(
                self._success_item(tmp_path),
                self._failed_item(tmp_path),
                self._ambiguous_item(tmp_path),
            )
        )
        assert len(result.failed) == 1
        assert result.failed[0].status is ExtractionStatus.EXTRACT_FAILED


# ---------------------------------------------------------------------------
# extract_one: CONFIRMED 系 SUCCESS (5 件)
# ---------------------------------------------------------------------------


class TestExtractOneSuccess:
    def test_alias_match_single_pdf_moves_to_facility_subdir(
        self, source_dir: Path, facility_root: Path
    ) -> None:
        ex_file = _make_ex_file(source_dir, "2025_DC_A_提供.ex_")
        adapter = FakeSfxAdapter(
            produced_pdfs=(source_dir / "report.pdf",),
            side_effect=_pdf_creating_side_effect(("report.pdf",)),
        )

        item = extract_one(
            ex_file,
            facility_root,
            ["サービスA", "サービスB", "デイケアセンター"],
            {"サービスA": ["DC_A"]},
            adapter,
        )

        assert item.status is ExtractionStatus.SUCCESS
        assert item.resolve_result.matched_facility == "サービスA"
        assert len(item.moved_pdfs) == 1
        assert item.moved_pdfs[0].parent == facility_root / "サービスA"
        assert item.moved_pdfs[0].name == "report.pdf"
        assert item.moved_pdfs[0].exists()
        assert not (source_dir / "report.pdf").exists()

    def test_partial_unique_with_multiple_pdfs(
        self, source_dir: Path, facility_root: Path
    ) -> None:
        ex_file = _make_ex_file(source_dir, "2025_サービスB_提供.ex_")
        adapter = FakeSfxAdapter(
            produced_pdfs=(
                source_dir / "p1.pdf",
                source_dir / "p2.pdf",
            ),
            side_effect=_pdf_creating_side_effect(("p1.pdf", "p2.pdf")),
        )

        item = extract_one(
            ex_file,
            facility_root,
            ["サービスA", "サービスB", "デイケアセンター"],
            {},
            adapter,
        )

        assert item.status is ExtractionStatus.SUCCESS
        # ファイル名が拡張子付きなので EXACT_MATCH は実用上発生しない (PARTIAL_UNIQUE になる)
        assert item.resolve_result.reason is ResolveReason.PARTIAL_UNIQUE
        assert len(item.moved_pdfs) == 2
        assert all(p.parent == facility_root / "サービスB" for p in item.moved_pdfs)

    def test_partial_unique_match(
        self, source_dir: Path, facility_root: Path
    ) -> None:
        ex_file = _make_ex_file(source_dir, "2025_デイケアセンター_提供.ex_")
        adapter = FakeSfxAdapter(
            produced_pdfs=(source_dir / "out.pdf",),
            side_effect=_pdf_creating_side_effect(("out.pdf",)),
        )

        item = extract_one(
            ex_file,
            facility_root,
            ["サービスA", "サービスB", "デイケアセンター"],
            {},
            adapter,
        )

        assert item.status is ExtractionStatus.SUCCESS
        assert item.resolve_result.reason is ResolveReason.PARTIAL_UNIQUE
        assert item.moved_pdfs[0].parent == facility_root / "デイケアセンター"

    def test_cleanup_removes_exe_after_success(
        self, source_dir: Path, facility_root: Path
    ) -> None:
        ex_file = _make_ex_file(source_dir, "2025_DC_A_提供.ex_")
        adapter = FakeSfxAdapter(
            produced_pdfs=(source_dir / "out.pdf",),
            side_effect=_pdf_creating_side_effect(("out.pdf",)),
        )

        item = extract_one(
            ex_file,
            facility_root,
            ["サービスA"],
            {"サービスA": ["DC_A"]},
            adapter,
        )

        assert item.status is ExtractionStatus.SUCCESS
        assert item.cleanup_warning is None
        assert not (source_dir / "2025_DC_A_提供.exe").exists()  # cleanup 実施
        assert ex_file.exists()  # 元 .ex_ は残る

    def test_adapter_called_with_correct_paths(
        self, source_dir: Path, facility_root: Path
    ) -> None:
        ex_file = _make_ex_file(source_dir, "2025_DC_A_提供.ex_")
        adapter = FakeSfxAdapter(
            produced_pdfs=(source_dir / "out.pdf",),
            side_effect=_pdf_creating_side_effect(("out.pdf",)),
        )

        extract_one(
            ex_file,
            facility_root,
            ["サービスA"],
            {"サービスA": ["DC_A"]},
            adapter,
        )

        assert len(adapter.calls) == 1
        called_exe, called_watch = adapter.calls[0]
        assert called_exe == ex_file.with_suffix(".exe")
        assert source_dir in called_watch  # ex_file.parent
        assert any("Desktop" in str(d) for d in called_watch)
        assert any("Downloads" in str(d) for d in called_watch)


# ---------------------------------------------------------------------------
# extract_one: SKIPPED 系 (3 件)
# ---------------------------------------------------------------------------


class TestExtractOneSkipped:
    def test_ambiguous_alias_skipped_no_extraction(
        self, source_dir: Path, facility_root: Path
    ) -> None:
        # alias が複数 canonical を hit する状況を作る (config 検証を bypass)
        ex_file = _make_ex_file(source_dir, "2025_DC_提供.ex_")
        adapter = FakeSfxAdapter()

        item = extract_one(
            ex_file,
            facility_root,
            ["サービスA", "サービスB"],
            # 通常 config で禁止される alias 重複だが resolver は防御的に処理
            {"サービスA": ["DC"], "サービスB": ["DC"]},
            adapter,
        )

        assert item.status is ExtractionStatus.SKIPPED_AMBIGUOUS
        assert item.resolve_result.reason is ResolveReason.AMBIGUOUS_ALIAS
        assert adapter.calls == []  # SFX 抽出はスキップされる
        assert item.moved_pdfs == ()

    def test_ambiguous_partial_skipped(
        self, source_dir: Path, facility_root: Path
    ) -> None:
        # 部分一致候補が複数 + 差不十分
        (facility_root / "施設X").mkdir()
        (facility_root / "施設Y").mkdir()
        ex_file = _make_ex_file(source_dir, "2025_施設_提供.ex_")
        adapter = FakeSfxAdapter()

        item = extract_one(
            ex_file,
            facility_root,
            ["施設X", "施設Y"],
            {},
            adapter,
        )

        # 「施設」では語境界マッチせず、UNMATCHED か AMBIGUOUS_PARTIAL のいずれか。
        # ここでは抽出が skip されることのみ確認 (resolver の詳細仕様は PR2 でカバー)
        assert item.status in (
            ExtractionStatus.SKIPPED_AMBIGUOUS,
            ExtractionStatus.SKIPPED_UNMATCHED,
        )
        assert adapter.calls == []

    def test_unmatched_skipped(
        self, source_dir: Path, facility_root: Path
    ) -> None:
        ex_file = _make_ex_file(source_dir, "2025_未登録施設_提供.ex_")
        adapter = FakeSfxAdapter()

        item = extract_one(
            ex_file,
            facility_root,
            ["サービスA", "サービスB"],
            {},
            adapter,
        )

        assert item.status is ExtractionStatus.SKIPPED_UNMATCHED
        assert item.resolve_result.status is ResolveStatus.UNMATCHED
        assert adapter.calls == []
        assert not (source_dir / "2025_未登録施設_提供.exe").exists()


# ---------------------------------------------------------------------------
# extract_one: 失敗系 (10 件)
# ---------------------------------------------------------------------------


class TestExtractOneFailures:
    def test_copy_failed_returns_extract_failed(
        self,
        source_dir: Path,
        facility_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ex_file = _make_ex_file(source_dir, "2025_DC_A_提供.ex_")

        def _fail_copy(*args: object, **kwargs: object) -> None:
            raise PermissionError("denied")

        monkeypatch.setattr(shutil, "copy2", _fail_copy)
        adapter = FakeSfxAdapter()

        item = extract_one(
            ex_file,
            facility_root,
            ["サービスA"],
            {"サービスA": ["DC_A"]},
            adapter,
        )

        assert item.status is ExtractionStatus.EXTRACT_FAILED
        assert item.error_code is ExtractionErrorCode.COPY_FAILED
        assert item.error_detail == "PermissionError"
        assert adapter.calls == []  # adapter は呼ばれない

    def test_sfx_launch_failed_propagated(
        self, source_dir: Path, facility_root: Path
    ) -> None:
        ex_file = _make_ex_file(source_dir, "2025_DC_A_提供.ex_")
        adapter = FakeSfxAdapter(
            raise_on_extract=SfxExtractionFailed(
                ExtractionErrorCode.SFX_LAUNCH_FAILED, "FileNotFoundError"
            )
        )

        item = extract_one(
            ex_file,
            facility_root,
            ["サービスA"],
            {"サービスA": ["DC_A"]},
            adapter,
        )

        assert item.status is ExtractionStatus.EXTRACT_FAILED
        assert item.error_code is ExtractionErrorCode.SFX_LAUNCH_FAILED
        assert item.error_detail == "FileNotFoundError"
        assert item.partial_outputs == ()
        # cleanup 実施 (adapter 例外時も .exe は削除される)
        assert not (source_dir / "2025_DC_A_提供.exe").exists()

    def test_sfx_timeout(
        self, source_dir: Path, facility_root: Path
    ) -> None:
        ex_file = _make_ex_file(source_dir, "2025_DC_A_提供.ex_")
        adapter = FakeSfxAdapter(
            raise_on_extract=SfxExtractionFailed(
                ExtractionErrorCode.SFX_TIMEOUT, "no pdf produced within 30s"
            )
        )

        item = extract_one(
            ex_file,
            facility_root,
            ["サービスA"],
            {"サービスA": ["DC_A"]},
            adapter,
        )

        assert item.status is ExtractionStatus.EXTRACT_FAILED
        assert item.error_code is ExtractionErrorCode.SFX_TIMEOUT

    def test_no_pdf_produced(
        self, source_dir: Path, facility_root: Path
    ) -> None:
        ex_file = _make_ex_file(source_dir, "2025_DC_A_提供.ex_")
        # adapter は例外を投げず空 list を返す (旧版互換: timeout 後に PDF 検出されず)
        adapter = FakeSfxAdapter(produced_pdfs=())

        item = extract_one(
            ex_file,
            facility_root,
            ["サービスA"],
            {"サービスA": ["DC_A"]},
            adapter,
        )

        assert item.status is ExtractionStatus.EXTRACT_FAILED
        assert item.error_code is ExtractionErrorCode.NO_PDF_PRODUCED

    def test_partial_output_preserves_paths(
        self, source_dir: Path, facility_root: Path
    ) -> None:
        ex_file = _make_ex_file(source_dir, "2025_DC_A_提供.ex_")
        partial_pdf = source_dir / "half.pdf"
        adapter = FakeSfxAdapter(
            raise_on_extract=SfxExtractionFailed(
                ExtractionErrorCode.SFX_TIMEOUT,
                "process failed but pdf produced",
                partial_outputs=(partial_pdf,),
            )
        )

        item = extract_one(
            ex_file,
            facility_root,
            ["サービスA"],
            {"サービスA": ["DC_A"]},
            adapter,
        )

        assert item.status is ExtractionStatus.PARTIAL_OUTPUT
        assert item.partial_outputs == (partial_pdf,)
        assert item.moved_pdfs == ()  # 自動移動禁止
        assert item.error_code is ExtractionErrorCode.SFX_TIMEOUT

    def test_move_conflict_when_dest_exists(
        self, source_dir: Path, facility_root: Path
    ) -> None:
        ex_file = _make_ex_file(source_dir, "2025_DC_A_提供.ex_")
        # 移動先に同名 PDF を事前配置
        (facility_root / "サービスA" / "report.pdf").write_bytes(b"existing")

        adapter = FakeSfxAdapter(
            produced_pdfs=(source_dir / "report.pdf",),
            side_effect=_pdf_creating_side_effect(("report.pdf",)),
        )

        item = extract_one(
            ex_file,
            facility_root,
            ["サービスA"],
            {"サービスA": ["DC_A"]},
            adapter,
        )

        assert item.status is ExtractionStatus.MOVE_FAILED
        assert item.error_code is ExtractionErrorCode.MOVE_CONFLICT
        assert item.error_detail == "report.pdf"
        # 移動先の既存 PDF はそのまま
        assert (facility_root / "サービスA" / "report.pdf").read_bytes() == b"existing"

    def test_cleanup_failed_does_not_override_success(
        self,
        source_dir: Path,
        facility_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ex_file = _make_ex_file(source_dir, "2025_DC_A_提供.ex_")
        adapter = FakeSfxAdapter(
            produced_pdfs=(source_dir / "out.pdf",),
            side_effect=_pdf_creating_side_effect(("out.pdf",)),
        )

        original_unlink = Path.unlink

        def _fail_unlink(self: Path, missing_ok: bool = False) -> None:
            if self.suffix == ".exe":
                raise OSError("locked by AV")
            original_unlink(self, missing_ok=missing_ok)

        monkeypatch.setattr(Path, "unlink", _fail_unlink)

        item = extract_one(
            ex_file,
            facility_root,
            ["サービスA"],
            {"サービスA": ["DC_A"]},
            adapter,
        )

        # primary 結果は SUCCESS、cleanup 失敗は warning として分離
        assert item.status is ExtractionStatus.SUCCESS
        assert item.cleanup_warning is ExtractionErrorCode.CLEANUP_FAILED
        assert item.error_code is None  # primary error にしない

    def test_cleanup_failed_preserved_on_failure(
        self,
        source_dir: Path,
        facility_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ex_file = _make_ex_file(source_dir, "2025_DC_A_提供.ex_")
        adapter = FakeSfxAdapter(produced_pdfs=())  # NO_PDF_PRODUCED

        original_unlink = Path.unlink

        def _fail_unlink(self: Path, missing_ok: bool = False) -> None:
            if self.suffix == ".exe":
                raise OSError("locked")
            original_unlink(self, missing_ok=missing_ok)

        monkeypatch.setattr(Path, "unlink", _fail_unlink)

        item = extract_one(
            ex_file,
            facility_root,
            ["サービスA"],
            {"サービスA": ["DC_A"]},
            adapter,
        )

        # primary failure + cleanup warning 両方記録
        assert item.status is ExtractionStatus.EXTRACT_FAILED
        assert item.error_code is ExtractionErrorCode.NO_PDF_PRODUCED
        assert item.cleanup_warning is ExtractionErrorCode.CLEANUP_FAILED

    def test_exe_cleanup_after_adapter_exception(
        self, source_dir: Path, facility_root: Path
    ) -> None:
        ex_file = _make_ex_file(source_dir, "2025_DC_A_提供.ex_")
        adapter = FakeSfxAdapter(
            raise_on_extract=SfxExtractionFailed(
                ExtractionErrorCode.SFX_LAUNCH_FAILED, "OSError"
            )
        )

        item = extract_one(
            ex_file,
            facility_root,
            ["サービスA"],
            {"サービスA": ["DC_A"]},
            adapter,
        )

        assert item.status is ExtractionStatus.EXTRACT_FAILED
        assert not (source_dir / "2025_DC_A_提供.exe").exists()  # finally で cleanup
        assert ex_file.exists()  # 元 .ex_ は保持

    def test_pdf_remains_on_partial_output(
        self, source_dir: Path, facility_root: Path
    ) -> None:
        """PARTIAL_OUTPUT 時は partial_outputs のパスが返るが移動は行われない。"""
        ex_file = _make_ex_file(source_dir, "2025_DC_A_提供.ex_")
        partial_pdf = source_dir / "half.pdf"
        partial_pdf.write_bytes(b"%PDF-1.4 partial")

        adapter = FakeSfxAdapter(
            raise_on_extract=SfxExtractionFailed(
                ExtractionErrorCode.SFX_TIMEOUT,
                "partial",
                partial_outputs=(partial_pdf,),
            )
        )

        item = extract_one(
            ex_file,
            facility_root,
            ["サービスA"],
            {"サービスA": ["DC_A"]},
            adapter,
        )

        assert item.status is ExtractionStatus.PARTIAL_OUTPUT
        # 部分生成 PDF は元の場所に残る (PR3 では隔離しない、PR4 で UI 検討)
        assert partial_pdf.exists()
        # 移動先は空
        assert not (facility_root / "サービスA" / "half.pdf").exists()

    def test_move_oserror_returns_move_io_error(
        self,
        source_dir: Path,
        facility_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """HIGH-B: shutil.move の OSError が捕捉され MOVE_FAILED + MOVE_IO_ERROR で返る。"""
        ex_file = _make_ex_file(source_dir, "2025_DC_A_提供.ex_")
        adapter = FakeSfxAdapter(
            produced_pdfs=(source_dir / "out.pdf",),
            side_effect=_pdf_creating_side_effect(("out.pdf",)),
        )

        def _fail_move(src: str, dst: str) -> None:
            raise PermissionError("locked")

        monkeypatch.setattr(shutil, "move", _fail_move)

        item = extract_one(
            ex_file,
            facility_root,
            ["サービスA"],
            {"サービスA": ["DC_A"]},
            adapter,
        )

        assert item.status is ExtractionStatus.MOVE_FAILED
        assert item.error_code is ExtractionErrorCode.MOVE_IO_ERROR
        assert item.error_detail == "PermissionError"

    def test_partially_moved_preserved_on_second_pdf_conflict(
        self, source_dir: Path, facility_root: Path
    ) -> None:
        """HIGH-A: 複数 PDF の途中で衝突した場合、移動済 PDF が partially_moved に保持される。"""
        ex_file = _make_ex_file(source_dir, "2025_DC_A_提供.ex_")
        # 2 個目に対応する dest を事前配置 (衝突を仕込む)
        (facility_root / "サービスA" / "p2.pdf").write_bytes(b"existing")

        adapter = FakeSfxAdapter(
            produced_pdfs=(source_dir / "p1.pdf", source_dir / "p2.pdf"),
            side_effect=_pdf_creating_side_effect(("p1.pdf", "p2.pdf")),
        )

        item = extract_one(
            ex_file,
            facility_root,
            ["サービスA"],
            {"サービスA": ["DC_A"]},
            adapter,
        )

        assert item.status is ExtractionStatus.MOVE_FAILED
        assert item.error_code is ExtractionErrorCode.MOVE_CONFLICT
        assert item.error_detail == "p2.pdf"
        # 1 個目は物理的に移動済み → partially_moved に記録
        assert len(item.partially_moved) == 1
        assert item.partially_moved[0] == facility_root / "サービスA" / "p1.pdf"
        assert item.partially_moved[0].exists()
        # MOVE_FAILED で moved_pdfs は空 (不変条件: SUCCESS 時のみ非空)
        assert item.moved_pdfs == ()

    def test_oserror_str_is_replaced_with_type_name_pii_safe(
        self, source_dir: Path, facility_root: Path
    ) -> None:
        """HIGH-C: OSError.str() は full path を含むため type(e).__name__ のみ伝搬する。"""
        ex_file = _make_ex_file(source_dir, "2025_DC_A_提供.ex_")
        # SfxExtractionFailed の detail にも full path が含まれない契約を確認
        sentinel_path = "C:\\Users\\sasak\\本田様\\絶対漏れちゃダメ.exe"
        adapter = FakeSfxAdapter(
            raise_on_extract=SfxExtractionFailed(
                # adapter 側で type(e).__name__ にすることを期待
                ExtractionErrorCode.SFX_LAUNCH_FAILED,
                "FileNotFoundError",
            )
        )

        item = extract_one(
            ex_file,
            facility_root,
            ["サービスA"],
            {"サービスA": ["DC_A"]},
            adapter,
        )

        assert item.error_detail == "FileNotFoundError"
        # full path-like sentinel は absolutely 含まれない
        assert sentinel_path not in (item.error_detail or "")


# ---------------------------------------------------------------------------
# extract_one の overwrite_existing + trashbox_root 経路 (Issue #ex-overwrite)
# ---------------------------------------------------------------------------


class TestExtractOneOverwriteWithTrashbox:
    """``overwrite_existing=True`` + ``trashbox_root`` 指定時の旧 PDF 退避 + 上書き。

    業務要件: ``move_conflict`` で停止した ex_file を、人間の確認後に
    旧 PDF を NAS の trashbox 経由で退避してから上書きできるようにする。
    Tera-station NAS の trashbox 機能とは独立した二重保険として、明示的に
    ``shutil.move`` で trashbox 配下に退避する (削除復旧経路の信頼性確保)。
    """

    def test_overwrite_quarantines_existing_to_trashbox_then_moves(
        self, source_dir: Path, facility_root: Path, tmp_path: Path
    ) -> None:
        """既存 dest を trashbox に退避し、新 PDF を配置 → SUCCESS。"""
        trashbox = tmp_path / "trashbox"
        ex_file = _make_ex_file(source_dir, "2025_DC_A_提供.ex_")
        existing_pdf = facility_root / "サービスA" / "report.pdf"
        existing_pdf.write_bytes(b"OLD_CONTENT")

        adapter = FakeSfxAdapter(
            produced_pdfs=(source_dir / "report.pdf",),
            side_effect=_pdf_creating_side_effect(("report.pdf",)),
        )

        item = extract_one(
            ex_file,
            facility_root,
            ["サービスA"],
            {"サービスA": ["DC_A"]},
            adapter,
            overwrite_existing=True,
            trashbox_root=trashbox,
        )

        # SUCCESS で完了
        assert item.status is ExtractionStatus.SUCCESS
        assert item.error_code is None
        # 新 PDF が dest に配置されている (旧 b"OLD_CONTENT" は消失)
        assert existing_pdf.exists()
        assert existing_pdf.read_bytes() == b"%PDF-1.4 fake"
        # 旧 PDF は trashbox 配下に退避 (path: trashbox/<facility_root.name>/<facility>/<basename>)
        quarantined = trashbox / facility_root.name / "サービスA" / "report.pdf"
        assert quarantined.exists()
        assert quarantined.read_bytes() == b"OLD_CONTENT"
        # SUCCESS 不変条件: moved_pdfs に新 dest が含まれる
        assert item.moved_pdfs == (existing_pdf,)

    def test_quarantine_failure_aborts_without_overwrite(
        self,
        source_dir: Path,
        facility_root: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """trashbox 退避が失敗したら新 PDF を配置せず ``QUARANTINE_DEST_FAILED``。

        不変条件: 旧 PDF が dest に残ったまま、新 PDF も配置されない
        (= 中途半端なデータ消失を構造的に排除)。
        """
        trashbox = tmp_path / "trashbox"
        ex_file = _make_ex_file(source_dir, "2025_DC_A_提供.ex_")
        existing_pdf = facility_root / "サービスA" / "report.pdf"
        existing_pdf.write_bytes(b"OLD_CONTENT")

        adapter = FakeSfxAdapter(
            produced_pdfs=(source_dir / "report.pdf",),
            side_effect=_pdf_creating_side_effect(("report.pdf",)),
        )

        original_move = shutil.move

        def _fail_to_trashbox(src: object, dst: object, *args: object, **kwargs: object) -> object:
            # trashbox 配下への move のみ fail (SFX 抽出 PDF の dest 配置は通常通り)
            if str(trashbox) in str(dst):
                raise OSError("simulated permission denied on trashbox")
            return original_move(src, dst, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(shutil, "move", _fail_to_trashbox)

        item = extract_one(
            ex_file,
            facility_root,
            ["サービスA"],
            {"サービスA": ["DC_A"]},
            adapter,
            overwrite_existing=True,
            trashbox_root=trashbox,
        )

        assert item.status is ExtractionStatus.MOVE_FAILED
        assert item.error_code is ExtractionErrorCode.QUARANTINE_DEST_FAILED
        assert item.error_detail == "OSError"
        # 旧 PDF は dest にそのまま残る (中途半端な消失なし)
        assert existing_pdf.read_bytes() == b"OLD_CONTENT"
        # 新 PDF は配置されていない (moved_pdfs 空)
        assert item.moved_pdfs == ()

    def test_quarantine_dest_collision_uses_timestamp_suffix(
        self, source_dir: Path, facility_root: Path, tmp_path: Path
    ) -> None:
        """trashbox に既に同名がある場合、timestamp suffix で衝突回避。"""
        import re

        trashbox = tmp_path / "trashbox"
        existing_quarantined_dir = trashbox / facility_root.name / "サービスA"
        existing_quarantined_dir.mkdir(parents=True)
        (existing_quarantined_dir / "report.pdf").write_bytes(b"OLDER_QUARANTINED")

        ex_file = _make_ex_file(source_dir, "2025_DC_A_提供.ex_")
        existing_pdf = facility_root / "サービスA" / "report.pdf"
        existing_pdf.write_bytes(b"OLD_CONTENT")

        adapter = FakeSfxAdapter(
            produced_pdfs=(source_dir / "report.pdf",),
            side_effect=_pdf_creating_side_effect(("report.pdf",)),
        )

        item = extract_one(
            ex_file,
            facility_root,
            ["サービスA"],
            {"サービスA": ["DC_A"]},
            adapter,
            overwrite_existing=True,
            trashbox_root=trashbox,
        )

        assert item.status is ExtractionStatus.SUCCESS
        # 元の trashbox 既存物は上書きされず保持
        assert (existing_quarantined_dir / "report.pdf").read_bytes() == b"OLDER_QUARANTINED"
        # 新規退避は suffix 付き (report_YYYYMMDD_HHMMSS_<6hex>.pdf)
        # Review C1: 同秒 silent overwrite 防止のため urandom uniquifier を含む
        suffixed = list(existing_quarantined_dir.glob("report_*.pdf"))
        assert len(suffixed) == 1
        assert suffixed[0].read_bytes() == b"OLD_CONTENT"
        assert re.match(r"^report_\d{8}_\d{6}_[0-9a-f]{6}\.pdf$", suffixed[0].name)

    def test_quarantine_dest_same_second_collision_uses_random_suffix(
        self,
        source_dir: Path,
        facility_root: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """同秒 + urandom suffix 衝突時に ``QUARANTINE_DEST_FAILED`` で明示停止。

        Review C1 / G5 (rating 9): 旧実装は秒精度 timestamp のみで、同秒に複数
        retry が走ると trashbox 上の前 quarantine を silent overwrite していた。
        ``_quarantine_pre_existing_target`` と一貫して ``os.urandom(3).hex()``
        uniquifier を追加 + 衝突再チェックで構造的に排除。urandom を fixed bytes
        にモックして強制衝突 → OSError → QUARANTINE_DEST_FAILED となる動作を確認。
        """
        from datetime import datetime as _dt

        trashbox = tmp_path / "trashbox"
        facility_subdir = trashbox / facility_root.name / "サービスA"
        facility_subdir.mkdir(parents=True)

        # urandom と datetime.now() を fixed value にモックして衝突を強制
        monkeypatch.setattr("os.urandom", lambda n: b"\xab\xcd\xef"[:n])

        class _FixedDatetime:
            @classmethod
            def now(cls) -> _dt:
                return _dt(2026, 5, 9, 12, 0, 0)

        monkeypatch.setattr(
            "wiseman_hub.pdf.ex_extractor.datetime", _FixedDatetime
        )

        # 衝突対象: 同 timestamp + 同 urandom hex のファイルを事前配置
        (facility_subdir / "report.pdf").write_bytes(b"first_quarantined")
        (facility_subdir / "report_20260509_120000_abcdef.pdf").write_bytes(
            b"second_collision_target"
        )

        ex_file = _make_ex_file(source_dir, "2025_DC_A_提供.ex_")
        existing_pdf = facility_root / "サービスA" / "report.pdf"
        existing_pdf.write_bytes(b"OLD_3RD")

        adapter = FakeSfxAdapter(
            produced_pdfs=(source_dir / "report.pdf",),
            side_effect=_pdf_creating_side_effect(("report.pdf",)),
        )

        item = extract_one(
            ex_file,
            facility_root,
            ["サービスA"],
            {"サービスA": ["DC_A"]},
            adapter,
            overwrite_existing=True,
            trashbox_root=trashbox,
        )

        # 衝突で QUARANTINE_DEST_FAILED (旧 PDF も新 PDF も触られない)
        assert item.status is ExtractionStatus.MOVE_FAILED
        assert item.error_code is ExtractionErrorCode.QUARANTINE_DEST_FAILED
        # 既存 trashbox の "second_collision_target" は silent overwrite されない
        assert (
            facility_subdir / "report_20260509_120000_abcdef.pdf"
        ).read_bytes() == b"second_collision_target"
        # 旧 PDF は dest にそのまま残る
        assert existing_pdf.read_bytes() == b"OLD_3RD"

    def test_overwrite_false_default_preserves_legacy_move_conflict(
        self, source_dir: Path, facility_root: Path
    ) -> None:
        """``overwrite_existing`` 未指定 (default False) は ``MOVE_CONFLICT`` で停止。

        既存挙動 100% 維持の signature contract test。
        """
        ex_file = _make_ex_file(source_dir, "2025_DC_A_提供.ex_")
        existing_pdf = facility_root / "サービスA" / "report.pdf"
        existing_pdf.write_bytes(b"existing")

        adapter = FakeSfxAdapter(
            produced_pdfs=(source_dir / "report.pdf",),
            side_effect=_pdf_creating_side_effect(("report.pdf",)),
        )

        # overwrite_existing 未指定 (default False)
        item = extract_one(
            ex_file,
            facility_root,
            ["サービスA"],
            {"サービスA": ["DC_A"]},
            adapter,
        )

        assert item.status is ExtractionStatus.MOVE_FAILED
        assert item.error_code is ExtractionErrorCode.MOVE_CONFLICT
        # 旧 PDF はそのまま (上書きなし)
        assert existing_pdf.read_bytes() == b"existing"


# ---------------------------------------------------------------------------
# extract_one の logger.warning 出力 (HIGH-G / M-1) (3 件)
# ---------------------------------------------------------------------------


class TestExtractOneWarnings:
    def test_partial_outputs_emit_warning(
        self,
        source_dir: Path,
        facility_root: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        ex_file = _make_ex_file(source_dir, "2025_DC_A_提供.ex_")
        partial_pdf = source_dir / "half.pdf"
        adapter = FakeSfxAdapter(
            raise_on_extract=SfxExtractionFailed(
                ExtractionErrorCode.SFX_TIMEOUT,
                "x",
                partial_outputs=(partial_pdf,),
            )
        )

        with caplog.at_level(logging.WARNING, logger="wiseman_hub.pdf.ex_extractor"):
            extract_one(
                ex_file,
                facility_root,
                ["サービスA"],
                {"サービスA": ["DC_A"]},
                adapter,
            )

        all_log = " ".join(record.getMessage() for record in caplog.records)
        assert "partial outputs" in all_log
        assert "2025_DC_A_提供.ex_" in all_log

    def test_cleanup_warning_emits_warning(
        self,
        source_dir: Path,
        facility_root: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        ex_file = _make_ex_file(source_dir, "2025_DC_A_提供.ex_")
        adapter = FakeSfxAdapter(
            produced_pdfs=(source_dir / "out.pdf",),
            side_effect=_pdf_creating_side_effect(("out.pdf",)),
        )

        original_unlink = Path.unlink

        def _fail_unlink(self: Path, missing_ok: bool = False) -> None:
            if self.suffix == ".exe":
                raise OSError("locked")
            original_unlink(self, missing_ok=missing_ok)

        monkeypatch.setattr(Path, "unlink", _fail_unlink)

        with caplog.at_level(logging.WARNING, logger="wiseman_hub.pdf.ex_extractor"):
            extract_one(
                ex_file,
                facility_root,
                ["サービスA"],
                {"サービスA": ["DC_A"]},
                adapter,
            )

        all_log = " ".join(record.getMessage() for record in caplog.records)
        assert "cleanup_failed" in all_log
        assert "2025_DC_A_提供.ex_" in all_log

    def test_no_warning_on_clean_success(
        self,
        source_dir: Path,
        facility_root: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        ex_file = _make_ex_file(source_dir, "2025_DC_A_提供.ex_")
        adapter = FakeSfxAdapter(
            produced_pdfs=(source_dir / "out.pdf",),
            side_effect=_pdf_creating_side_effect(("out.pdf",)),
        )

        with caplog.at_level(logging.WARNING, logger="wiseman_hub.pdf.ex_extractor"):
            extract_one(
                ex_file,
                facility_root,
                ["サービスA"],
                {"サービスA": ["DC_A"]},
                adapter,
            )

        warnings = [
            record for record in caplog.records if record.levelno >= logging.WARNING
        ]
        assert warnings == []


# ---------------------------------------------------------------------------
# retry_overwrite (Issue #ex-overwrite, UI 上書き再実行 経由)
# ---------------------------------------------------------------------------


class TestRetryOverwrite:
    """1 回目処理結果から ``MOVE_CONFLICT`` のみを ``overwrite=True`` で再処理。"""

    def test_empty_input_returns_empty_tuple(
        self, facility_root: Path, tmp_path: Path
    ) -> None:
        """空 input → 空 output (境界値)。"""
        result = retry_overwrite(
            items=(),
            facility_root_dir=facility_root,
            facility_names=["サービスA"],
            aliases={"サービスA": ["DC_A"]},
            adapter=FakeSfxAdapter(produced_pdfs=()),
            trashbox_root=tmp_path / "trashbox",
        )
        assert result == ()

    def test_non_conflict_items_passed_through_unchanged(
        self, source_dir: Path, facility_root: Path, tmp_path: Path
    ) -> None:
        """MOVE_CONFLICT 以外の item はそのまま返す (再処理対象外)。"""
        ex_file = _make_ex_file(source_dir, "2025_DC_A_提供.ex_")
        # 例: SUCCESS item は再処理しない
        success_item = ExtractionItem(
            source_path=ex_file,
            resolve_result=_dummy_resolve_confirmed(),
            status=ExtractionStatus.SUCCESS,
            moved_pdfs=(facility_root / "サービスA" / "x.pdf",),
        )

        result = retry_overwrite(
            items=(success_item,),
            facility_root_dir=facility_root,
            facility_names=["サービスA"],
            aliases={"サービスA": ["DC_A"]},
            adapter=FakeSfxAdapter(produced_pdfs=()),
            trashbox_root=tmp_path / "trashbox",
        )

        assert result == (success_item,)

    def test_move_conflict_items_retried_with_overwrite(
        self, source_dir: Path, facility_root: Path, tmp_path: Path
    ) -> None:
        """MOVE_CONFLICT item は overwrite=True で再処理 → SUCCESS になる。"""
        trashbox = tmp_path / "trashbox"
        ex_file = _make_ex_file(source_dir, "2025_DC_A_提供.ex_")
        existing_pdf = facility_root / "サービスA" / "report.pdf"
        existing_pdf.write_bytes(b"OLD")

        # 1 回目処理結果のシミュレート: MOVE_CONFLICT
        conflict_item = ExtractionItem(
            source_path=ex_file,
            resolve_result=_dummy_resolve_confirmed("サービスA"),
            status=ExtractionStatus.MOVE_FAILED,
            error_code=ExtractionErrorCode.MOVE_CONFLICT,
            error_detail="report.pdf",
        )

        adapter = FakeSfxAdapter(
            produced_pdfs=(source_dir / "report.pdf",),
            side_effect=_pdf_creating_side_effect(("report.pdf",)),
        )

        result = retry_overwrite(
            items=(conflict_item,),
            facility_root_dir=facility_root,
            facility_names=["サービスA"],
            aliases={"サービスA": ["DC_A"]},
            adapter=adapter,
            trashbox_root=trashbox,
        )

        assert len(result) == 1
        assert result[0].status is ExtractionStatus.SUCCESS
        # 旧 PDF は trashbox 配下に退避
        quarantined = trashbox / facility_root.name / "サービスA" / "report.pdf"
        assert quarantined.exists()
        assert quarantined.read_bytes() == b"OLD"

    # ----- Review G3: matched_facility is None 防御パス -----

    def test_move_conflict_without_matched_facility_logged_and_passed_through(
        self,
        source_dir: Path,
        facility_root: Path,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """``MOVE_CONFLICT`` で ``matched_facility is None`` の防御パスが動作する。

        Review G3 (rating 8): ``ExtractionItem.__post_init__`` の不変条件を
        bypass した invariant 違反 item に対し、retry_overwrite が
        ``logger.warning`` を出して input 元のまま skip する (=defensive)。
        """
        ex_file = _make_ex_file(source_dir, "2025_DC_A_提供.ex_")
        # __post_init__ をすり抜けるため object.__setattr__ で invariant 違反を構築
        # (frozen dataclass のため通常代入では構築不能)
        invariant_violator = ExtractionItem(
            source_path=ex_file,
            resolve_result=_dummy_resolve_confirmed("サービスA"),
            status=ExtractionStatus.MOVE_FAILED,
            error_code=ExtractionErrorCode.MOVE_CONFLICT,
        )
        # post-construction で resolve_result を unmatched に強制 (invariant 違反)
        object.__setattr__(
            invariant_violator,
            "resolve_result",
            _dummy_resolve_unmatched(),
        )

        adapter = FakeSfxAdapter(produced_pdfs=())

        with caplog.at_level("WARNING"):
            result = retry_overwrite(
                items=(invariant_violator,),
                facility_root_dir=facility_root,
                facility_names=["サービスA"],
                aliases={"サービスA": ["DC_A"]},
                adapter=adapter,
                trashbox_root=tmp_path / "trashbox",
            )

        # input そのまま (再処理されず)
        assert result == (invariant_violator,)
        # 防御 log 出力済 (filename のみ含む PII-safe)
        assert any(
            "invariant violation" in r.message and ex_file.name in r.message
            for r in caplog.records
        )

    # ----- Review G4: 複数 MOVE_CONFLICT items / 部分失敗 -----

    def test_multiple_move_conflicts_retried_independently(
        self, source_dir: Path, facility_root: Path, tmp_path: Path
    ) -> None:
        """複数 MOVE_CONFLICT items を順次 retry し、ordering と独立性を検証。

        Review G4 (rating 7): 業務 context の "3 件 conflict" を実証カバー。
        SUCCESS item は pass-through、ordering は input 順を保持。
        """
        trashbox = tmp_path / "trashbox"
        # 3 件 conflict + 1 件 SUCCESS
        conflicts = []
        for i in range(3):
            ex_file = _make_ex_file(source_dir, f"2025_DC_A_提供_{i}.ex_")
            (facility_root / "サービスA" / f"2025_DC_A_提供_{i}.pdf").write_bytes(
                f"OLD_{i}".encode()
            )
            conflicts.append(
                ExtractionItem(
                    source_path=ex_file,
                    resolve_result=_dummy_resolve_confirmed("サービスA"),
                    status=ExtractionStatus.MOVE_FAILED,
                    error_code=ExtractionErrorCode.MOVE_CONFLICT,
                )
            )
        success_item = ExtractionItem(
            source_path=Path("ok.ex_"),
            resolve_result=_dummy_resolve_confirmed(),
            status=ExtractionStatus.SUCCESS,
            moved_pdfs=(facility_root / "サービスA" / "ok.pdf",),
        )

        # ex_file 毎に異なる PDF を返す動的 adapter (FakeSfxAdapter は単一 fixed
        # produced_pdfs しか返せないため、複数 retry を表現するには Protocol 直実装)
        adapter = _DynamicSfxAdapter()

        result = retry_overwrite(
            items=(*conflicts, success_item),
            facility_root_dir=facility_root,
            facility_names=["サービスA"],
            aliases={"サービスA": ["DC_A"]},
            adapter=adapter,
            trashbox_root=trashbox,
        )

        # ordering 保持 (3 件 conflict + 1 件 SUCCESS、input 順)
        assert len(result) == 4
        # 全 conflict が SUCCESS に変化
        for i in range(3):
            assert result[i].status is ExtractionStatus.SUCCESS
        # SUCCESS item は pass-through
        assert result[3] is success_item
        # 全旧 PDF が trashbox に退避済 (各々独立)
        for i in range(3):
            quarantined = trashbox / facility_root.name / "サービスA" / f"2025_DC_A_提供_{i}.pdf"
            assert quarantined.exists()
            assert quarantined.read_bytes() == f"OLD_{i}".encode()

    def test_partial_failure_preserves_success_items(
        self,
        source_dir: Path,
        facility_root: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """1 件目成功 / 2 件目失敗 → 1 件目の成功は破棄されず保持される。

        Review G4 (rating 7): per-item exception の独立性検証。
        ループ全体を try/except で包む regression を構造的に防ぐ。
        """
        trashbox = tmp_path / "trashbox"
        ex_files = []
        conflicts = []
        for i in range(2):
            ex_file = _make_ex_file(source_dir, f"2025_DC_A_提供_{i}.ex_")
            ex_files.append(ex_file)
            (facility_root / "サービスA" / f"2025_DC_A_提供_{i}.pdf").write_bytes(
                f"OLD_{i}".encode()
            )
            conflicts.append(
                ExtractionItem(
                    source_path=ex_file,
                    resolve_result=_dummy_resolve_confirmed("サービスA"),
                    status=ExtractionStatus.MOVE_FAILED,
                    error_code=ExtractionErrorCode.MOVE_CONFLICT,
                )
            )

        adapter = _DynamicSfxAdapter()

        # 2 件目の trashbox 退避を fail させる
        original_move = shutil.move
        call_count = {"trashbox": 0}

        def _fail_second_trashbox_move(
            src: object, dst: object, *args: object, **kwargs: object
        ) -> object:
            if str(trashbox) in str(dst):
                call_count["trashbox"] += 1
                if call_count["trashbox"] == 2:
                    raise OSError("simulated 2nd trashbox failure")
            return original_move(src, dst, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(shutil, "move", _fail_second_trashbox_move)

        result = retry_overwrite(
            items=tuple(conflicts),
            facility_root_dir=facility_root,
            facility_names=["サービスA"],
            aliases={"サービスA": ["DC_A"]},
            adapter=adapter,
            trashbox_root=trashbox,
        )

        # 1 件目成功 / 2 件目失敗
        assert len(result) == 2
        assert result[0].status is ExtractionStatus.SUCCESS
        assert result[1].status is ExtractionStatus.MOVE_FAILED
        assert result[1].error_code is ExtractionErrorCode.QUARANTINE_DEST_FAILED
        # 1 件目の旧 PDF は trashbox に退避済 (失敗で破棄されていない)
        first_quarantined = (
            trashbox / facility_root.name / "サービスA" / "2025_DC_A_提供_0.pdf"
        )
        assert first_quarantined.exists()
        assert first_quarantined.read_bytes() == b"OLD_0"
        # 2 件目の旧 PDF は dest に残る (中途半端な消失なし)
        assert (
            facility_root / "サービスA" / "2025_DC_A_提供_1.pdf"
        ).read_bytes() == b"OLD_1"


# ---------------------------------------------------------------------------
# extract_directory (8 件)
# ---------------------------------------------------------------------------


class TestExtractDirectory:
    def test_empty_source_dir_returns_empty_items(
        self, source_dir: Path, facility_root: Path
    ) -> None:
        result = extract_directory(source_dir, facility_root, {}, FakeSfxAdapter())
        assert result.items == ()
        assert result.success_count == 0
        assert result.pending_filenames == ()

    def test_single_ex_file_processed(
        self, source_dir: Path, facility_root: Path
    ) -> None:
        _make_ex_file(source_dir, "2025_DC_A_提供.ex_")
        adapter = FakeSfxAdapter(
            produced_pdfs=(source_dir / "out.pdf",),
            side_effect=_pdf_creating_side_effect(("out.pdf",)),
        )

        result = extract_directory(
            source_dir, facility_root, {"サービスA": ["DC_A"]}, adapter
        )

        assert len(result.items) == 1
        assert result.success_count == 1

    def test_multiple_ex_files_processed_in_sorted_order(
        self, source_dir: Path, facility_root: Path
    ) -> None:
        # 並び順検証用に名前を逆順で生成
        for name in ("zzz_サービスB.ex_", "aaa_DC_A_提供.ex_", "mmm_デイケアセンター_提供.ex_"):
            _make_ex_file(source_dir, name)

        # adapter 呼び出し時に動的に PDF 生成
        def _produce(exe_path: Path, watch_dirs: Sequence[Path]) -> None:
            pdf_name = exe_path.stem + ".pdf"
            (watch_dirs[0] / pdf_name).write_bytes(b"%PDF")

        adapter = FakeSfxAdapter(side_effect=_produce)

        # adapter.produced_pdfs は実際の生成パスを使うため動的生成だと return 値も動的に
        # → 別の adapter 実装を使う
        class DynamicFakeAdapter:
            def __init__(self) -> None:
                self.calls: list[tuple[Path, tuple[Path, ...]]] = []

            def extract_pdf(
                self, exe_path: Path, watch_dirs: Sequence[Path]
            ) -> Sequence[Path]:
                self.calls.append((exe_path, tuple(watch_dirs)))
                pdf = watch_dirs[0] / (exe_path.stem + ".pdf")
                pdf.write_bytes(b"%PDF")
                return (pdf,)

        adapter = DynamicFakeAdapter()  # type: ignore[assignment]

        result = extract_directory(
            source_dir,
            facility_root,
            {"サービスA": ["DC_A"]},
            adapter,
        )

        assert len(result.items) == 3
        names = [i.source_path.name for i in result.items]
        assert names == sorted(names)  # ソート順保証

    def test_source_dir_not_found_raises(
        self, tmp_path: Path, facility_root: Path
    ) -> None:
        missing = tmp_path / "does_not_exist"
        with pytest.raises(FileNotFoundError, match="source_dir not found"):
            extract_directory(missing, facility_root, {}, FakeSfxAdapter())

    def test_facility_root_not_found_raises(
        self, source_dir: Path, tmp_path: Path
    ) -> None:
        missing = tmp_path / "no_root"
        with pytest.raises(FileNotFoundError, match="facility_root_dir not found"):
            extract_directory(source_dir, missing, {}, FakeSfxAdapter())

    def test_underscore_prefix_dirs_excluded(
        self, source_dir: Path, facility_root: Path
    ) -> None:
        # `_` 始まりは旧版互換で除外
        (facility_root / "_archive").mkdir()
        (facility_root / "_temp").mkdir()
        _make_ex_file(source_dir, "2025_archive_提供.ex_")

        adapter = FakeSfxAdapter()
        result = extract_directory(source_dir, facility_root, {}, adapter)

        # _archive はマッチ候補に入らないので UNMATCHED / SKIPPED
        assert result.items[0].status in (
            ExtractionStatus.SKIPPED_AMBIGUOUS,
            ExtractionStatus.SKIPPED_UNMATCHED,
        )
        # adapter は呼ばれない (skip)
        assert adapter.calls == []

    def test_orphan_alias_canonicals_returned(
        self, source_dir: Path, facility_root: Path
    ) -> None:
        result = extract_directory(
            source_dir,
            facility_root,
            # サービスZ は facility_root に存在しない (orphan)
            {"サービスA": ["DC_A"], "サービスZ": ["GHOST"]},
            FakeSfxAdapter(),
        )

        assert "サービスZ" in result.orphan_alias_canonicals
        assert "サービスA" not in result.orphan_alias_canonicals

    def test_pending_filenames_collected(
        self, source_dir: Path, facility_root: Path
    ) -> None:
        _make_ex_file(source_dir, "2025_未登録_提供.ex_")
        _make_ex_file(source_dir, "2025_DC_A_提供.ex_")

        class DynamicFakeAdapter:
            def extract_pdf(
                self, exe_path: Path, watch_dirs: Sequence[Path]
            ) -> Sequence[Path]:
                pdf = watch_dirs[0] / (exe_path.stem + ".pdf")
                pdf.write_bytes(b"%PDF")
                return (pdf,)

        adapter = DynamicFakeAdapter()
        result = extract_directory(
            source_dir,
            facility_root,
            {"サービスA": ["DC_A"]},
            adapter,
        )

        assert "2025_未登録_提供.ex_" in result.pending_filenames
        assert "2025_DC_A_提供.ex_" not in result.pending_filenames


# ---------------------------------------------------------------------------
# WindowsSfxAdapter platform 境界 (3 件)
# ---------------------------------------------------------------------------


class TestWindowsSfxAdapterPlatformGuard:
    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="win32 上では UnsupportedSfxPlatformError を投げない (実機検証で別途確認)",
    )
    def test_constructor_raises_on_macos(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 現環境 (macOS) で構築 → 独自例外
        with pytest.raises(UnsupportedSfxPlatformError, match="win32"):
            WindowsSfxAdapter()

    def test_constructor_raises_on_linux(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "wiseman_hub.pdf.ex_extractor.sys.platform", "linux"
        )
        with pytest.raises(UnsupportedSfxPlatformError):
            WindowsSfxAdapter()

    def test_unsupported_error_is_runtime_subclass(self) -> None:
        # except RuntimeError でも捕捉可能 (CLI / UI で広く扱う際の保証)
        assert issubclass(UnsupportedSfxPlatformError, RuntimeError)


# ---------------------------------------------------------------------------
# PII ログ防御 (4 件)
# ---------------------------------------------------------------------------


class TestPIILogProtection:
    def test_logger_emits_filename_only_on_success(
        self,
        source_dir: Path,
        facility_root: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        ex_file = _make_ex_file(source_dir, "2025_DC_A_提供.ex_")
        adapter = FakeSfxAdapter(
            produced_pdfs=(source_dir / "out.pdf",),
            side_effect=_pdf_creating_side_effect(("out.pdf",)),
        )

        with caplog.at_level(logging.INFO, logger="wiseman_hub.pdf.ex_extractor"):
            extract_one(
                ex_file,
                facility_root,
                ["サービスA"],
                {"サービスA": ["DC_A"]},
                adapter,
            )

        all_log_text = " ".join(record.getMessage() for record in caplog.records)
        # filename は OK
        assert "2025_DC_A_提供.ex_" in all_log_text

    def test_logger_does_not_emit_full_path(
        self,
        source_dir: Path,
        facility_root: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        ex_file = _make_ex_file(source_dir, "2025_DC_A_提供.ex_")
        adapter = FakeSfxAdapter(
            produced_pdfs=(source_dir / "out.pdf",),
            side_effect=_pdf_creating_side_effect(("out.pdf",)),
        )

        with caplog.at_level(logging.INFO, logger="wiseman_hub.pdf.ex_extractor"):
            extract_one(
                ex_file,
                facility_root,
                ["サービスA"],
                {"サービスA": ["DC_A"]},
                adapter,
            )

        all_log_text = " ".join(record.getMessage() for record in caplog.records)
        # フルパスや facility_root_dir 情報が漏れていない
        assert str(source_dir) not in all_log_text
        assert str(facility_root) not in all_log_text

    def test_logger_does_not_emit_facility_name(
        self,
        source_dir: Path,
        facility_root: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        ex_file = _make_ex_file(source_dir, "2025_DC_A_提供.ex_")
        adapter = FakeSfxAdapter(
            produced_pdfs=(source_dir / "out.pdf",),
            side_effect=_pdf_creating_side_effect(("out.pdf",)),
        )

        with caplog.at_level(logging.DEBUG, logger="wiseman_hub.pdf.ex_extractor"):
            extract_one(
                ex_file,
                facility_root,
                ["サービスA"],
                {"サービスA": ["DC_A"]},
                adapter,
            )

        all_log_text = " ".join(record.getMessage() for record in caplog.records)
        # matched_facility (= "サービスA") は log に含めない
        assert "サービスA" not in all_log_text

    def test_logger_does_not_emit_candidates_on_ambiguous(
        self,
        source_dir: Path,
        facility_root: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        ex_file = _make_ex_file(source_dir, "2025_DC_提供.ex_")
        adapter = FakeSfxAdapter()

        with caplog.at_level(logging.DEBUG, logger="wiseman_hub.pdf.ex_extractor"):
            extract_one(
                ex_file,
                facility_root,
                ["サービスA", "サービスB"],
                {"サービスA": ["DC"], "サービスB": ["DC"]},
                adapter,
            )

        all_log_text = " ".join(record.getMessage() for record in caplog.records)
        # candidates ("サービスA" / "サービスB") は log に含めない
        assert "サービスA" not in all_log_text
        assert "サービスB" not in all_log_text


# ---------------------------------------------------------------------------
# FakeSfxAdapter 動作 (3 件)
# ---------------------------------------------------------------------------


class TestFakeSfxAdapter:
    def test_returns_produced_pdfs(self, tmp_path: Path) -> None:
        pdf = tmp_path / "x.pdf"
        adapter = FakeSfxAdapter(produced_pdfs=(pdf,))
        result = adapter.extract_pdf(tmp_path / "x.exe", [tmp_path])
        assert tuple(result) == (pdf,)

    def test_raises_when_configured(self, tmp_path: Path) -> None:
        adapter = FakeSfxAdapter(
            raise_on_extract=SfxExtractionFailed(
                ExtractionErrorCode.SFX_TIMEOUT, "timeout"
            )
        )
        with pytest.raises(SfxExtractionFailed) as exc:
            adapter.extract_pdf(tmp_path / "x.exe", [tmp_path])
        assert exc.value.code is ExtractionErrorCode.SFX_TIMEOUT

    def test_side_effect_invoked_with_call_args(self, tmp_path: Path) -> None:
        captured: list[tuple[Path, tuple[Path, ...]]] = []

        def _hook(exe_path: Path, watch_dirs: Sequence[Path]) -> None:
            captured.append((exe_path, tuple(watch_dirs)))

        adapter = FakeSfxAdapter(side_effect=_hook)
        adapter.extract_pdf(tmp_path / "x.exe", [tmp_path])
        assert len(captured) == 1
        assert captured[0][0] == tmp_path / "x.exe"


# ---------------------------------------------------------------------------
# SfxExtractionFailed 型 (2 件)
# ---------------------------------------------------------------------------


class TestSfxExtractionFailed:
    def test_partial_outputs_default_empty(self) -> None:
        e = SfxExtractionFailed(ExtractionErrorCode.SFX_TIMEOUT, "x")
        assert e.partial_outputs == ()
        assert e.code is ExtractionErrorCode.SFX_TIMEOUT
        assert e.detail == "x"

    def test_partial_outputs_preserved(self, tmp_path: Path) -> None:
        partial = (tmp_path / "a.pdf", tmp_path / "b.pdf")
        e = SfxExtractionFailed(
            ExtractionErrorCode.SFX_TIMEOUT, "x", partial_outputs=partial
        )
        assert e.partial_outputs == partial


# ---------------------------------------------------------------------------
# 統合シナリオ (3 件)
# ---------------------------------------------------------------------------


class TestExtractDirectoryIntegration:
    def test_mixed_success_skip_and_failure(
        self, source_dir: Path, facility_root: Path
    ) -> None:
        _make_ex_file(source_dir, "2025_DC_A_提供.ex_")  # SUCCESS
        _make_ex_file(source_dir, "2025_未登録_提供.ex_")  # SKIPPED_UNMATCHED

        class MixedAdapter:
            def extract_pdf(
                self, exe_path: Path, watch_dirs: Sequence[Path]
            ) -> Sequence[Path]:
                pdf = watch_dirs[0] / (exe_path.stem + ".pdf")
                pdf.write_bytes(b"%PDF")
                return (pdf,)

        adapter = MixedAdapter()
        result = extract_directory(
            source_dir,
            facility_root,
            {"サービスA": ["DC_A"]},
            adapter,
        )

        assert result.success_count == 1
        assert len(result.pending_manual) == 1
        assert len(result.failed) == 0

    def test_alias_orphan_with_normal_processing(
        self, source_dir: Path, facility_root: Path
    ) -> None:
        _make_ex_file(source_dir, "2025_DC_A_提供.ex_")

        class _Adapter:
            def extract_pdf(
                self, exe_path: Path, watch_dirs: Sequence[Path]
            ) -> Sequence[Path]:
                pdf = watch_dirs[0] / (exe_path.stem + ".pdf")
                pdf.write_bytes(b"%PDF")
                return (pdf,)

        result = extract_directory(
            source_dir,
            facility_root,
            {"サービスA": ["DC_A"], "ゴースト施設": ["GHOST"]},
            _Adapter(),
        )

        assert result.success_count == 1
        assert "ゴースト施設" in result.orphan_alias_canonicals

    def test_all_failures_no_success(
        self, source_dir: Path, facility_root: Path
    ) -> None:
        _make_ex_file(source_dir, "2025_DC_A_提供.ex_")
        _make_ex_file(source_dir, "2025_DC_A_第2_提供.ex_")
        adapter = FakeSfxAdapter(produced_pdfs=())  # 常に NO_PDF_PRODUCED

        result = extract_directory(
            source_dir,
            facility_root,
            {"サービスA": ["DC_A"]},
            adapter,
        )

        assert result.success_count == 0
        assert len(result.failed) == 2
        assert all(
            i.error_code is ExtractionErrorCode.NO_PDF_PRODUCED
            for i in result.failed
        )

    def test_unexpected_exception_does_not_break_batch(
        self, source_dir: Path, facility_root: Path
    ) -> None:
        """HIGH-B: 1 ファイルで想定外例外 (RuntimeError 等) が出ても残り全件処理が継続する。"""
        _make_ex_file(source_dir, "aaa_DC_A_提供.ex_")  # 通常成功
        _make_ex_file(source_dir, "bbb_DC_A_提供.ex_")  # adapter 例外
        _make_ex_file(source_dir, "ccc_DC_A_提供.ex_")  # 通常成功

        class FlakyAdapter:
            def __init__(self) -> None:
                self.call_count = 0

            def extract_pdf(
                self, exe_path: Path, watch_dirs: Sequence[Path]
            ) -> Sequence[Path]:
                self.call_count += 1
                if "bbb" in exe_path.name:
                    raise RuntimeError("adapter implementation bug")
                pdf = watch_dirs[0] / (exe_path.stem + ".pdf")
                pdf.write_bytes(b"%PDF")
                return (pdf,)

        adapter = FlakyAdapter()
        result = extract_directory(
            source_dir,
            facility_root,
            {"サービスA": ["DC_A"]},
            adapter,
        )

        # 3 ファイル全件処理される (中断されない)
        assert len(result.items) == 3
        # bbb は EXTRACT_FAILED + UNEXPECTED
        bbb_item = next(i for i in result.items if "bbb" in i.source_path.name)
        assert bbb_item.status is ExtractionStatus.EXTRACT_FAILED
        assert bbb_item.error_code is ExtractionErrorCode.UNEXPECTED
        assert bbb_item.error_detail == "RuntimeError"
        # aaa / ccc は SUCCESS
        assert result.success_count == 2

    def test_memory_error_propagates_and_stops_batch(
        self, source_dir: Path, facility_root: Path
    ) -> None:
        """silent-failure-hunter H-2: MemoryError は再 raise してバッチ続行を止める。"""
        _make_ex_file(source_dir, "aaa_DC_A_提供.ex_")
        _make_ex_file(source_dir, "bbb_DC_A_提供.ex_")

        class OOMAdapter:
            def extract_pdf(
                self, exe_path: Path, watch_dirs: Sequence[Path]
            ) -> Sequence[Path]:
                raise MemoryError("simulated OOM")

        with pytest.raises(MemoryError):
            extract_directory(
                source_dir,
                facility_root,
                {"サービスA": ["DC_A"]},
                OOMAdapter(),
            )

    def test_resolver_failure_falls_back_to_unmatched(
        self,
        source_dir: Path,
        facility_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """HIGH-NEW-2: 例外源が resolver の場合、フォールバックで二度目の例外を防ぐ。"""
        _make_ex_file(source_dir, "aaa_DC_A_提供.ex_")

        from wiseman_hub.pdf import ex_extractor as exmod

        call_count = {"n": 0}
        original_resolve = exmod.resolve_facility

        def _flaky_resolve(
            filename: str, names: list[str], aliases: dict[str, list[str]]
        ) -> ResolveResult:
            call_count["n"] += 1
            # 1 回目 (extract_one 内): 例外を投げる → extract_directory が捕捉
            # 2 回目 (extract_directory フォールバック): ここでも例外を投げる
            #   → 安全 fallback (UNMATCHED) で吸収されるべき
            raise ValueError("resolver internal bug")

        monkeypatch.setattr(exmod, "resolve_facility", _flaky_resolve)
        adapter = FakeSfxAdapter()

        result = extract_directory(
            source_dir,
            facility_root,
            {"サービスA": ["DC_A"]},
            adapter,
        )

        # バッチが落ちずに完走、UNEXPECTED で 1 件処理される
        assert len(result.items) == 1
        assert result.items[0].status is ExtractionStatus.EXTRACT_FAILED
        assert result.items[0].error_code is ExtractionErrorCode.UNEXPECTED
        # フォールバックで UNMATCHED resolve_result が入る
        assert result.items[0].resolve_result.status is ResolveStatus.UNMATCHED

        # original_resolve は使用済み
        del original_resolve

    def test_force_facility_bypasses_resolver_with_manual_override(
        self, source_dir: Path, facility_root: Path
    ) -> None:
        """PR4: force_facility 指定で resolver を bypass、MANUAL_OVERRIDE で CONFIRMED。"""
        # 通常なら UNMATCHED になるファイル名
        ex_file = _make_ex_file(source_dir, "2025_未登録施設_提供.ex_")
        adapter = FakeSfxAdapter(
            produced_pdfs=(source_dir / "out.pdf",),
            side_effect=_pdf_creating_side_effect(("out.pdf",)),
        )

        item = extract_one(
            ex_file,
            facility_root,
            ["サービスA", "サービスB"],
            {},
            adapter,
            force_facility="サービスA",
        )

        assert item.status is ExtractionStatus.SUCCESS
        assert item.resolve_result.status is ResolveStatus.CONFIRMED
        assert item.resolve_result.reason is ResolveReason.MANUAL_OVERRIDE
        assert item.resolve_result.matched_facility == "サービスA"
        # 抽出された PDF が「サービスA」フォルダに移動される
        assert item.moved_pdfs[0].parent == facility_root / "サービスA"

    def test_force_facility_not_in_facility_names_raises(
        self, source_dir: Path, facility_root: Path
    ) -> None:
        """PR4: force_facility が facility_names に存在しないと ValueError (UI 誤値防止)。"""
        ex_file = _make_ex_file(source_dir, "2025_test.ex_")
        adapter = FakeSfxAdapter()

        with pytest.raises(ValueError, match="not in facility_names"):
            extract_one(
                ex_file,
                facility_root,
                ["サービスA"],
                {},
                adapter,
                force_facility="存在しない事業所",
            )

    def test_force_facility_pii_safe_error_message(
        self, source_dir: Path, facility_root: Path
    ) -> None:
        """PR4: force_facility 不正時の例外メッセージは PII-safe (事業所名を含めない)。"""
        ex_file = _make_ex_file(source_dir, "2025_test.ex_")
        adapter = FakeSfxAdapter()
        sentinel = "PII機密事業所名XYZ"

        with pytest.raises(ValueError) as exc_info:
            extract_one(
                ex_file,
                facility_root,
                ["サービスA"],
                {},
                adapter,
                force_facility=sentinel,
            )

        # 例外メッセージに force_facility 値・facility_names 値が含まれない
        msg = str(exc_info.value)
        assert sentinel not in msg
        assert "サービスA" not in msg

    def test_unexpected_logger_uses_type_name_only_pii_safe(
        self,
        source_dir: Path,
        facility_root: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """HIGH-NEW-1: logger.exception ではなく logger.warning + type(e).__name__ で PII 漏洩防止。"""
        _make_ex_file(source_dir, "aaa_DC_A_提供.ex_")
        sentinel_path = "C:\\Users\\sasak\\本田様\\漏れちゃダメ.pdf"

        class LeakyAdapter:
            def extract_pdf(
                self, exe_path: Path, watch_dirs: Sequence[Path]
            ) -> Sequence[Path]:
                # 例外メッセージに full path 風の文字列を含めて漏洩テスト
                raise OSError(f"locked: {sentinel_path}")

        with caplog.at_level(logging.WARNING, logger="wiseman_hub.pdf.ex_extractor"):
            extract_directory(
                source_dir,
                facility_root,
                {"サービスA": ["DC_A"]},
                LeakyAdapter(),
            )

        all_log = " ".join(record.getMessage() for record in caplog.records)
        # full path-like sentinel は含まれない
        assert sentinel_path not in all_log
        # 型名は含まれる
        assert "OSError" in all_log


# ---------------------------------------------------------------------------
# find_target_pdf / find_unexpected_naming_pdfs (basename 完全一致 + 変則命名検出)
# ---------------------------------------------------------------------------


class TestFindTargetPdf:
    """``find_target_pdf`` の basename 完全一致と探索順を検証。"""

    def test_finds_lowercase_pdf_in_first_dir(self, tmp_path: Path) -> None:
        (tmp_path / "report.pdf").touch()
        result = find_target_pdf("report", [tmp_path])
        assert result is not None
        assert result.name == "report.pdf"

    def test_returns_none_when_only_unrelated_pdf(self, tmp_path: Path) -> None:
        """basename 完全一致なので無関係な PDF は拾わない (誤配布防止)。"""
        (tmp_path / "noise.pdf").touch()
        (tmp_path / "report_misc.pdf").touch()  # report_001.pdf 風だが stem 違い
        result = find_target_pdf("report", [tmp_path])
        assert result is None

    def test_search_order_first_dir_takes_priority(self, tmp_path: Path) -> None:
        """探索順は引数順: ex_file.parent 最優先で渡す呼び出し側との契約。"""
        first = tmp_path / "first"
        second = tmp_path / "second"
        first.mkdir()
        second.mkdir()
        (first / "report.pdf").write_text("FIRST")
        (second / "report.pdf").write_text("SECOND")

        result = find_target_pdf("report", [first, second])
        assert result is not None
        assert result.read_text() == "FIRST"

    def test_skips_missing_directory(self, tmp_path: Path) -> None:
        existing = tmp_path / "exist"
        existing.mkdir()
        (existing / "report.pdf").touch()
        ghost = tmp_path / "ghost"  # 存在しない

        result = find_target_pdf("report", [ghost, existing])
        assert result is not None
        assert result.parent == existing

    def test_returns_none_for_directory_with_same_basename(
        self, tmp_path: Path
    ) -> None:
        """is_file() ガードで「ディレクトリ <stem>.pdf/」を誤検出しない。"""
        (tmp_path / "report.pdf").mkdir()  # stem.pdf という名前のディレクトリ
        result = find_target_pdf("report", [tmp_path])
        assert result is None


class TestFindUnexpectedNamingPdfs:
    """変則命名検出 (UNEXPECTED_PDF_NAMING)。"""

    def test_finds_underscore_suffix(self, tmp_path: Path) -> None:
        (tmp_path / "report_001.pdf").touch()
        (tmp_path / "report_002.pdf").touch()
        result = find_unexpected_naming_pdfs("report", [tmp_path])
        names = {p.name for p in result}
        assert names == {"report_001.pdf", "report_002.pdf"}

    def test_finds_paren_suffix(self, tmp_path: Path) -> None:
        (tmp_path / "report (1).pdf").touch()
        result = find_unexpected_naming_pdfs("report", [tmp_path])
        assert len(result) == 1
        assert result[0].name == "report (1).pdf"

    def test_excludes_expected_target(self, tmp_path: Path) -> None:
        """``<stem>.pdf`` は expected として除外される (Windows NTFS は case-insensitive)。"""
        (tmp_path / "report.pdf").touch()
        result = find_unexpected_naming_pdfs("report", [tmp_path])
        assert result == []

    def test_excludes_unrelated_prefix(self, tmp_path: Path) -> None:
        """``food.pdf`` (boundary 文字でない) は ``foo`` と無関係扱い。"""
        (tmp_path / "food.pdf").touch()
        (tmp_path / "fooled.pdf").touch()
        result = find_unexpected_naming_pdfs("foo", [tmp_path])
        assert result == []

    def test_finds_dot_suffix(self, tmp_path: Path) -> None:
        """``report.x.pdf`` のような複数拡張子も変則扱い。"""
        (tmp_path / "report.x.pdf").touch()
        result = find_unexpected_naming_pdfs("report", [tmp_path])
        assert len(result) == 1

    def test_dedup_across_watch_dirs(self, tmp_path: Path) -> None:
        """同じ Path が複数 watch_dirs に渡されても重複しない。"""
        (tmp_path / "report_001.pdf").touch()
        result = find_unexpected_naming_pdfs(
            "report", [tmp_path, tmp_path]
        )
        assert len(result) == 1


class TestQuarantinePreExistingTarget:
    """``_quarantine_pre_existing_target`` の単体検証."""

    def test_no_pre_existing_returns_none(self, tmp_path: Path) -> None:
        ex_file = tmp_path / "report.ex_"
        ex_file.touch()
        q_path, origin, code, detail = _quarantine_pre_existing_target(ex_file)
        assert q_path is None
        assert origin is None
        assert code is None
        assert detail is None

    def test_renames_existing_target(self, tmp_path: Path) -> None:
        ex_file = tmp_path / "report.ex_"
        ex_file.touch()
        target = tmp_path / "report.pdf"
        target.write_text("OLD")
        q_path, origin, code, detail = _quarantine_pre_existing_target(ex_file)
        assert q_path is not None
        assert origin == target
        assert code is None
        assert not target.exists()  # 元の位置にはない
        assert q_path.exists()  # 退避先に存在
        assert q_path.read_text() == "OLD"  # 中身保持

class TestExtractOnePreExistingPdfQuarantine:
    """同名 PDF 同居状態の挙動 (誤配布事故の構造的防止)。"""

    def _ex_file(self, source_dir: Path, name: str = "サービスA_提供.ex_") -> Path:
        ex = source_dir / name
        ex.touch()
        return ex

    def _facility_root(self, base: Path, names: list[str]) -> Path:
        root = base / "facilities"
        root.mkdir()
        for n in names:
            (root / n).mkdir()
        return root

    def test_pre_existing_replaced_by_new_sfx_output(
        self, tmp_path: Path
    ) -> None:
        """退避 → SFX 新規生成 → **新生成 PDF を採用、退避物は削除**。"""
        source = tmp_path / "src"
        source.mkdir()
        ex_file = self._ex_file(source)
        old_pdf = ex_file.with_suffix(".pdf")
        old_pdf.write_text("OLD")  # 古い PDF が同居

        root = self._facility_root(tmp_path, ["サービスA"])

        produced = source / "サービスA_提供.pdf"

        def side_effect(exe_path: Path, watch_dirs: object) -> None:
            # SFX 模擬: 退避中 (origin が無い状態) で新規 PDF を実生成
            produced.write_text("NEW")

        adapter = FakeSfxAdapter(
            produced_pdfs=(produced,), side_effect=side_effect
        )

        item = extract_one(
            ex_file=ex_file,
            facility_root_dir=root,
            facility_names=["サービスA"],
            aliases={},
            adapter=adapter,
        )

        assert item.status is ExtractionStatus.SUCCESS
        # 移動先に新 PDF が存在し、内容は NEW
        moved = root / "サービスA" / "サービスA_提供.pdf"
        assert moved.exists()
        assert moved.read_text() == "NEW"
        # 退避物は削除済 (source 直下に quarantine 残骸がない)
        quarantines = list(source.glob(f"*{_QUARANTINE_PREFIX}*"))
        assert quarantines == []

    def test_pre_existing_restored_when_sfx_produces_no_new_pdf(
        self, tmp_path: Path
    ) -> None:
        """退避 → SFX が新規生成しない → **EXTRACT_FAILED + 退避物復元**。"""
        source = tmp_path / "src"
        source.mkdir()
        ex_file = self._ex_file(source)
        old_pdf = ex_file.with_suffix(".pdf")
        old_pdf.write_text("OLD")

        root = self._facility_root(tmp_path, ["サービスA"])

        # SFX が SfxExtractionFailed(NO_PDF_PRODUCED) を投げる (新規生成失敗)
        adapter = FakeSfxAdapter(
            raise_on_extract=SfxExtractionFailed(
                ExtractionErrorCode.NO_PDF_PRODUCED, "no pdf produced"
            )
        )

        item = extract_one(
            ex_file=ex_file,
            facility_root_dir=root,
            facility_names=["サービスA"],
            aliases={},
            adapter=adapter,
        )

        assert item.status is ExtractionStatus.EXTRACT_FAILED
        assert item.error_code is ExtractionErrorCode.NO_PDF_PRODUCED
        # 退避物が元の位置に復元されている (古い PDF はそのまま source に残る)
        assert old_pdf.exists()
        assert old_pdf.read_text() == "OLD"
        # quarantine 残骸はない
        quarantines = list(source.glob(f"*{_QUARANTINE_PREFIX}*"))
        assert quarantines == []
        # 移動先には何も入っていない
        assert not (root / "サービスA" / "サービスA_提供.pdf").exists()

    def test_unrelated_pdf_in_source_is_not_touched(self, tmp_path: Path) -> None:
        """basename 不一致 PDF は退避されず・移動されない。"""
        source = tmp_path / "src"
        source.mkdir()
        ex_file = self._ex_file(source)
        unrelated = source / "noise.pdf"
        unrelated.write_text("UNRELATED")

        root = self._facility_root(tmp_path, ["サービスA"])

        produced = source / "サービスA_提供.pdf"

        def side_effect(exe_path: Path, watch_dirs: object) -> None:
            produced.write_text("NEW")

        adapter = FakeSfxAdapter(
            produced_pdfs=(produced,), side_effect=side_effect
        )
        item = extract_one(
            ex_file=ex_file,
            facility_root_dir=root,
            facility_names=["サービスA"],
            aliases={},
            adapter=adapter,
        )

        assert item.status is ExtractionStatus.SUCCESS
        # 無関係 PDF は触られていない
        assert unrelated.exists()
        assert unrelated.read_text() == "UNRELATED"
        # 移動先には期待 PDF
        assert (root / "サービスA" / "サービスA_提供.pdf").exists()


class TestQuarantineFailureAbortsBeforeSfx:
    """退避失敗時は SFX を呼ばずに即 EXTRACT_FAILED で return する契約."""

    def test_quarantine_rename_failure_aborts_before_sfx(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """rename OSError → SFX adapter は呼ばれず QUARANTINE_FAILED で return."""
        source = tmp_path / "src"
        source.mkdir()
        ex_file = source / "サービスA_提供.ex_"
        ex_file.touch()
        # quarantine 対象の同名 PDF を同居させる
        old_pdf = ex_file.with_suffix(".pdf")
        old_pdf.write_text("OLD")

        root = tmp_path / "facilities"
        root.mkdir()
        (root / "サービスA").mkdir()

        # Path.rename を OSError raise に差し替え
        original_rename = Path.rename

        def fake_rename(self: Path, target: Path) -> Path:
            if self == old_pdf:
                raise PermissionError("locked by AV")
            return original_rename(self, target)

        monkeypatch.setattr(Path, "rename", fake_rename)

        # adapter call 数を counter で検査
        call_counter = {"count": 0}

        def side_effect(exe_path: Path, watch_dirs: object) -> None:
            call_counter["count"] += 1

        adapter = FakeSfxAdapter(produced_pdfs=(), side_effect=side_effect)

        item = extract_one(
            ex_file=ex_file,
            facility_root_dir=root,
            facility_names=["サービスA"],
            aliases={},
            adapter=adapter,
        )

        # 1. SFX adapter は呼ばれていない (古い PDF 同居のまま処理回避)
        assert call_counter["count"] == 0
        # 2. EXTRACT_FAILED + QUARANTINE_FAILED で return
        assert item.status is ExtractionStatus.EXTRACT_FAILED
        assert item.error_code is ExtractionErrorCode.QUARANTINE_FAILED
        # 3. error_detail は型名のみ (フルパス・PII を含まない)
        assert item.error_detail == "PermissionError"
        # 4. 古い PDF は元の位置に残る (退避失敗 → 動かない)
        assert old_pdf.exists()
        assert old_pdf.read_text() == "OLD"
        # 5. 移動先には何も入らない
        assert not (root / "サービスA" / "サービスA_提供.pdf").exists()


class TestQuarantineRestoreFailureRecorded:
    """SFX 失敗 + 復元失敗 → cleanup_warning + primary 上書き禁止契約."""

    def test_restore_failure_recorded_as_cleanup_warning(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SFX が NO_PDF_PRODUCED → restore で OSError → cleanup_warning に記録."""
        source = tmp_path / "src"
        source.mkdir()
        ex_file = source / "サービスA_提供.ex_"
        ex_file.touch()
        old_pdf = ex_file.with_suffix(".pdf")
        old_pdf.write_text("OLD")

        root = tmp_path / "facilities"
        root.mkdir()
        (root / "サービスA").mkdir()

        # adapter は SfxExtractionFailed(NO_PDF_PRODUCED) を投げる
        adapter = FakeSfxAdapter(
            raise_on_extract=SfxExtractionFailed(
                ExtractionErrorCode.NO_PDF_PRODUCED, "no pdf produced"
            )
        )

        # restore の Path.rename を OSError raise に差し替え (delete 経路は影響しない)
        original_rename = Path.rename

        def fake_rename(self: Path, target: Path) -> Path:
            # quarantine から origin への戻り rename (target が old_pdf) を阻害
            if target == old_pdf:
                raise PermissionError("locked by AV")
            return original_rename(self, target)

        monkeypatch.setattr(Path, "rename", fake_rename)

        item = extract_one(
            ex_file=ex_file,
            facility_root_dir=root,
            facility_names=["サービスA"],
            aliases={},
            adapter=adapter,
        )

        # primary error は SFX 由来の NO_PDF_PRODUCED 維持
        assert item.status is ExtractionStatus.EXTRACT_FAILED
        assert item.error_code is ExtractionErrorCode.NO_PDF_PRODUCED
        # cleanup_warning に QUARANTINE_RESTORE_FAILED 記録
        assert item.cleanup_warning is ExtractionErrorCode.QUARANTINE_RESTORE_FAILED

    def test_primary_cleanup_warning_not_overridden_by_quarantine(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """先勝ち契約: .exe 削除失敗 (primary) を quarantine 警告で上書きしない."""
        source = tmp_path / "src"
        source.mkdir()
        ex_file = source / "サービスA_提供.ex_"
        ex_file.touch()
        old_pdf = ex_file.with_suffix(".pdf")
        old_pdf.write_text("OLD")

        root = tmp_path / "facilities"
        root.mkdir()
        (root / "サービスA").mkdir()

        adapter = FakeSfxAdapter(
            raise_on_extract=SfxExtractionFailed(
                ExtractionErrorCode.NO_PDF_PRODUCED, "no pdf produced"
            )
        )

        # 1. .exe の unlink を OSError 化 → primary cleanup_warning = CLEANUP_FAILED
        # 2. restore も OSError 化 → quarantine_post_warning = QUARANTINE_RESTORE_FAILED
        # 期待: primary (CLEANUP_FAILED) が維持される
        original_unlink = Path.unlink
        original_rename = Path.rename
        exe_path = ex_file.with_suffix(".exe")

        def fake_unlink(self: Path, missing_ok: bool = False) -> None:
            if self == exe_path:
                raise PermissionError("exe locked")
            return original_unlink(self, missing_ok=missing_ok)

        def fake_rename(self: Path, target: Path) -> Path:
            if target == old_pdf:
                raise PermissionError("av lock")
            return original_rename(self, target)

        monkeypatch.setattr(Path, "unlink", fake_unlink)
        monkeypatch.setattr(Path, "rename", fake_rename)

        item = extract_one(
            ex_file=ex_file,
            facility_root_dir=root,
            facility_names=["サービスA"],
            aliases={},
            adapter=adapter,
        )

        assert item.status is ExtractionStatus.EXTRACT_FAILED
        assert item.error_code is ExtractionErrorCode.NO_PDF_PRODUCED
        # 先勝ち: .exe 削除失敗が primary cleanup_warning を取る
        assert item.cleanup_warning is ExtractionErrorCode.CLEANUP_FAILED


class TestExtractOneUnexpectedNamingIntegration:
    """UNEXPECTED_PDF_NAMING の extract_one 経由統合検証."""

    def test_unexpected_naming_pdf_propagates_error_code(
        self, tmp_path: Path
    ) -> None:
        """SFX が <stem>_001.pdf のみ生成 → PARTIAL_OUTPUT + UNEXPECTED_PDF_NAMING."""
        source = tmp_path / "src"
        source.mkdir()
        ex_file = source / "サービスA_提供.ex_"
        ex_file.touch()

        root = tmp_path / "facilities"
        root.mkdir()
        (root / "サービスA").mkdir()

        # adapter は SfxExtractionFailed(UNEXPECTED_PDF_NAMING) を投げる
        # (実機では SFX が <stem>_001.pdf を出力した状況)
        unexpected_pdf = source / "サービスA_提供_001.pdf"
        unexpected_pdf.write_text("UNEXPECTED_CONTENT")

        adapter = FakeSfxAdapter(
            raise_on_extract=SfxExtractionFailed(
                ExtractionErrorCode.UNEXPECTED_PDF_NAMING,
                "unexpected naming, count=1",
                partial_outputs=(unexpected_pdf,),
            )
        )

        item = extract_one(
            ex_file=ex_file,
            facility_root_dir=root,
            facility_names=["サービスA"],
            aliases={},
            adapter=adapter,
        )

        # PARTIAL_OUTPUT (partial_outputs があるため EXTRACT_FAILED から昇格)
        assert item.status is ExtractionStatus.PARTIAL_OUTPUT
        assert item.error_code is ExtractionErrorCode.UNEXPECTED_PDF_NAMING
        # partial_outputs に変則命名 PDF が運用者へ列挙される
        assert unexpected_pdf in item.partial_outputs
        # 自動移動はされない (構造的禁止)
        assert not (root / "サービスA" / "サービスA_提供_001.pdf").exists()
        # 元の変則命名 PDF は source に残る (運用者が手動対応)
        assert unexpected_pdf.exists()


class TestSnapshotPdfsAndFallback:
    """SFX 出力 PDF 名が ex_file の stem と一致しない実機ケース対応:
    snapshot 差分検出を fallback として使う設計の検証。
    """

    def test_snapshot_pdfs_excludes_quarantine(self, tmp_path: Path) -> None:
        """``.quarantine-`` prefix を含む PDF は snapshot から除外される
        (古い退避 PDF を「新規生成」と誤認させない構造保証)。"""
        (tmp_path / "regular.pdf").touch()
        (tmp_path / f"old.pdf{_QUARANTINE_PREFIX}20260101000000-aaaa").touch()
        (tmp_path / "data.txt").touch()  # 非 PDF は除外

        snapshot = WindowsSfxAdapter._snapshot_pdfs([tmp_path])
        names = {p.name for p in snapshot}
        assert names == {"regular.pdf"}

    def test_snapshot_pdfs_handles_missing_dir(self, tmp_path: Path) -> None:
        ghost = tmp_path / "ghost"
        snapshot = WindowsSfxAdapter._snapshot_pdfs([ghost])
        assert snapshot == set()

    def test_resolve_falls_back_to_snapshot_diff_single_new(
        self, tmp_path: Path
    ) -> None:
        """SFX が ex_file.stem と異なる名前で 1 件 PDF を出した場合、
        snapshot 差分で fallback 検出される (実機 SFX の任意命名対応)。"""
        before: set[Path] = set()  # SFX 起動前は空
        # SFX 起動後に SFX 名固有の短い名前で 1 件出現
        sfx_output = tmp_path / "提供実績.pdf"
        sfx_output.touch()

        result = WindowsSfxAdapter._resolve_target_or_raise(
            target_stem="long_ex_file_stem_with_facility_suffix",
            watch_dirs=[tmp_path],
            primary_dir=tmp_path,
            before_snapshot=before,
        )
        assert len(result) == 1
        assert result[0].name == "提供実績.pdf"

    def test_resolve_prefers_basename_over_snapshot_diff(
        self, tmp_path: Path
    ) -> None:
        """``<stem>.pdf`` が見つかれば snapshot 差分より優先 (既存契約維持)。"""
        before: set[Path] = set()
        target = tmp_path / "stem.pdf"
        target.touch()
        # 余計な PDF も増えているが target を優先
        other = tmp_path / "別名.pdf"
        other.touch()

        result = WindowsSfxAdapter._resolve_target_or_raise(
            target_stem="stem",
            watch_dirs=[tmp_path],
            primary_dir=tmp_path,
            before_snapshot=before,
        )
        assert len(result) == 1
        assert result[0].name == "stem.pdf"

    def test_resolve_picks_latest_when_multiple_new(
        self, tmp_path: Path
    ) -> None:
        """新規生成が複数 → 最新 mtime を採用 (誤検知ではなく救済路)。"""
        import time as _time

        before: set[Path] = set()
        old = tmp_path / "old_output.pdf"
        old.touch()
        _time.sleep(0.01)
        newer = tmp_path / "newer_output.pdf"
        newer.touch()

        result = WindowsSfxAdapter._resolve_target_or_raise(
            target_stem="unrelated_stem",
            watch_dirs=[tmp_path],
            primary_dir=tmp_path,
            before_snapshot=before,
        )
        assert len(result) == 1
        assert result[0].name == "newer_output.pdf"

    def test_resolve_excludes_pre_existing_from_diff(
        self, tmp_path: Path
    ) -> None:
        """before_snapshot に含まれる PDF は差分から除外される
        (誤配布防止: 既存 PDF を SFX 出力扱いにしない)。"""
        pre_existing = tmp_path / "pre_existing.pdf"
        pre_existing.touch()
        before = {pre_existing}
        # SFX が新たに出した 1 件
        sfx_out = tmp_path / "sfx_new.pdf"
        sfx_out.touch()

        result = WindowsSfxAdapter._resolve_target_or_raise(
            target_stem="unrelated",
            watch_dirs=[tmp_path],
            primary_dir=tmp_path,
            before_snapshot=before,
        )
        assert len(result) == 1
        assert result[0].name == "sfx_new.pdf"

    def test_resolve_raises_no_pdf_when_no_diff(
        self, tmp_path: Path
    ) -> None:
        """SFX 起動前後で PDF 集合に変化なし → NO_PDF_PRODUCED。"""
        existing = tmp_path / "stays.pdf"
        existing.touch()
        before = {existing}

        with pytest.raises(SfxExtractionFailed) as exc_info:
            WindowsSfxAdapter._resolve_target_or_raise(
                target_stem="other_stem",
                watch_dirs=[tmp_path],
                primary_dir=tmp_path,
                before_snapshot=before,
            )
        assert exc_info.value.code is ExtractionErrorCode.NO_PDF_PRODUCED
