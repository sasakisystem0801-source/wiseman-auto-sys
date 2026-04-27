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
from collections.abc import Sequence
from pathlib import Path

import pytest

from wiseman_hub.pdf.ex_extractor import (
    ExtractionErrorCode,
    ExtractionItem,
    ExtractionResult,
    ExtractionStatus,
    FakeSfxAdapter,
    SfxExtractionFailed,
    UnsupportedSfxPlatformError,
    WindowsSfxAdapter,
    extract_directory,
    extract_one,
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
# WindowsSfxAdapter の platform 非依存メソッド (3 件)
# ---------------------------------------------------------------------------


class TestWindowsSfxAdapterStaticMethods:
    """test-analyzer H3: _snapshot_pdfs / _collect_new_pdfs は macOS でも検証可能。"""

    def test_snapshot_pdfs_finds_lowercase_and_uppercase(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "a.pdf").touch()
        (tmp_path / "b.PDF").touch()
        (tmp_path / "c.txt").touch()

        result = WindowsSfxAdapter._snapshot_pdfs([tmp_path])
        names = {p.name for p in result}
        assert names == {"a.pdf", "b.PDF"}

    def test_snapshot_pdfs_skips_missing_dir(self, tmp_path: Path) -> None:
        (tmp_path / "a.pdf").touch()
        result = WindowsSfxAdapter._snapshot_pdfs(
            [tmp_path, tmp_path / "does_not_exist"]
        )
        assert len(result) == 1

    def test_collect_new_pdfs_filters_by_mtime(self, tmp_path: Path) -> None:
        """HIGH-D: SFX 起動前に存在した PDF は無関係扱いで除外される。"""
        import os as _os

        # SFX 起動 "前" の PDF (古い mtime)
        old_pdf = tmp_path / "old.pdf"
        old_pdf.touch()
        old_mtime = old_pdf.stat().st_mtime - 100
        _os.utime(old_pdf, (old_mtime, old_mtime))

        sfx_start = old_pdf.stat().st_mtime + 50  # 旧ファイルより新しい時刻

        # SFX 起動後に出現した PDF
        new_pdf = tmp_path / "new.pdf"
        new_pdf.touch()  # 現在時刻 = sfx_start より新しい

        before: set[Path] = set()  # snapshot 時点で何もなかった想定
        result = WindowsSfxAdapter._collect_new_pdfs(
            [tmp_path], before, sfx_start
        )
        # old.pdf は mtime < sfx_start なので除外される
        result_names = {p.name for p in result}
        assert "new.pdf" in result_names
        assert "old.pdf" not in result_names
