"""事業所ルートフォルダ scanner のユニットテスト（W2）。

scan_facility_root() が以下を満たすことを検証する:
- B（運動機能向上計画書/）AND C（経過報告書/）両方ある直下フォルダのみ事業所として認識
- 事業所直下の *.pdf 数で a_pdf_status を分岐（0/1/N+）
- 既存出力 PDF（{事業所名}.pdf）を A 候補から除外する（AC-12 最重要）
- 既存出力ファイルの有無を has_existing_output に記録
- 日本語・UNC・スペース・記号入り事業所名で失敗しない
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wiseman_hub.pdf.facility_scanner import (
    FacilityCandidate,
    FacilityStatus,
    scan_facility_root,
)


def _make_facility(
    root: Path,
    name: str,
    *,
    has_plan: bool = True,
    has_report: bool = True,
    a_pdfs: tuple[str, ...] = (),
    output_exists: bool = False,
    extra_subdirs: tuple[str, ...] = (),
) -> Path:
    """テスト用に事業所フォルダを作る helper。"""
    facility = root / name
    facility.mkdir(parents=True, exist_ok=True)
    if has_plan:
        (facility / "運動機能向上計画書").mkdir(exist_ok=True)
    if has_report:
        (facility / "経過報告書").mkdir(exist_ok=True)
    for pdf_name in a_pdfs:
        (facility / pdf_name).write_bytes(b"%PDF-1.4\n")
    if output_exists:
        (facility / f"{name}.pdf").write_bytes(b"%PDF-1.4\n")
    for sub in extra_subdirs:
        (facility / sub).mkdir(exist_ok=True)
    return facility


# -----------------------------------------------------------------------------
# AC-12: 出力ファイル除外（最重要、再実行ループ防止）
# -----------------------------------------------------------------------------


def test_output_pdf_excluded_from_a_candidates(tmp_path: Path) -> None:
    """既存出力 `{事業所名}.pdf` のみがある事業所 → A_MISSING。

    AC-12: A.pdf 候補から `{事業所名}.pdf` を除外する（再実行ループ防止）。
    出力ファイルを A 候補に含めると、再実行時に A_MULTIPLE 判定になり
    永続的に実行不可ループに陥る。
    """
    facility = _make_facility(tmp_path, "事業所X", a_pdfs=(), output_exists=True)
    assert (facility / "事業所X.pdf").exists()

    candidates = scan_facility_root(tmp_path)

    assert len(candidates) == 1
    cand = candidates[0]
    assert cand.facility_name == "事業所X"
    assert cand.status == FacilityStatus.A_MISSING
    assert cand.a_pdf_path is None
    assert cand.has_existing_output is True


def test_output_pdf_plus_one_input_pdf_yields_pending(tmp_path: Path) -> None:
    """`{事業所名}.pdf`（出力）+ `提供実績.pdf`（A）→ PENDING。出力は A 候補から除外される。"""
    facility = _make_facility(
        tmp_path,
        "事業所Y",
        a_pdfs=("提供実績.pdf",),
        output_exists=True,
    )

    candidates = scan_facility_root(tmp_path)

    assert len(candidates) == 1
    cand = candidates[0]
    assert cand.status == FacilityStatus.PENDING
    assert cand.a_pdf_path == facility / "提供実績.pdf"
    assert cand.has_existing_output is True


def test_output_pdf_plus_two_input_pdfs_yields_multiple(tmp_path: Path) -> None:
    """`{事業所名}.pdf`（出力）+ A 候補 2 件 → A_MULTIPLE。出力は候補に含めない。"""
    _make_facility(
        tmp_path,
        "事業所Z",
        a_pdfs=("提供実績.pdf", "別の.pdf"),
        output_exists=True,
    )

    candidates = scan_facility_root(tmp_path)

    assert len(candidates) == 1
    cand = candidates[0]
    assert cand.status == FacilityStatus.A_MULTIPLE
    assert cand.a_pdf_path is None
    assert len(cand.a_pdf_candidates) == 2
    # 候補に出力ファイルが含まれていないこと（AC-12 強い保証）
    candidate_names = {p.name for p in cand.a_pdf_candidates}
    assert "事業所Z.pdf" not in candidate_names
    assert candidate_names == {"提供実績.pdf", "別の.pdf"}


# -----------------------------------------------------------------------------
# 事業所判定（B AND C）
# -----------------------------------------------------------------------------


def test_b_and_c_both_required_for_facility(tmp_path: Path) -> None:
    """B/C 両方あるフォルダのみ事業所と認識（AC-2）。"""
    _make_facility(tmp_path, "両方あり", a_pdfs=("A.pdf",))
    _make_facility(tmp_path, "Bのみ", has_report=False, a_pdfs=("A.pdf",))
    _make_facility(tmp_path, "Cのみ", has_plan=False, a_pdfs=("A.pdf",))
    _make_facility(
        tmp_path, "両方なし", has_plan=False, has_report=False, a_pdfs=("A.pdf",)
    )
    # 関係ないファイル / 関係ない非事業所サブフォルダ も無視されるべき
    (tmp_path / "メモ.txt").write_text("ignored", encoding="utf-8")
    (tmp_path / "_archive").mkdir()

    candidates = scan_facility_root(tmp_path)

    names = {c.facility_name for c in candidates}
    assert names == {"両方あり"}


def test_extra_subdirs_dont_affect_facility_detection(tmp_path: Path) -> None:
    """B/C 以外のサブフォルダがあっても事業所判定に影響しない。"""
    _make_facility(
        tmp_path,
        "備考あり事業所",
        a_pdfs=("提供実績.pdf",),
        extra_subdirs=("backup", "古い書類"),
    )

    candidates = scan_facility_root(tmp_path)

    assert len(candidates) == 1
    assert candidates[0].status == FacilityStatus.PENDING


# -----------------------------------------------------------------------------
# A.pdf 件数による status 分岐
# -----------------------------------------------------------------------------


def test_a_pdf_zero_yields_missing(tmp_path: Path) -> None:
    """事業所直下に PDF が 0 件 → A_MISSING（AC-3）。"""
    _make_facility(tmp_path, "PDFなし", a_pdfs=())

    candidates = scan_facility_root(tmp_path)

    assert candidates[0].status == FacilityStatus.A_MISSING
    assert candidates[0].a_pdf_path is None
    assert candidates[0].a_pdf_candidates == ()


def test_a_pdf_one_yields_pending(tmp_path: Path) -> None:
    """事業所直下に PDF が 1 件 → PENDING（AC 主流）。"""
    facility = _make_facility(tmp_path, "1件", a_pdfs=("提供実績.pdf",))

    candidates = scan_facility_root(tmp_path)

    assert candidates[0].status == FacilityStatus.PENDING
    assert candidates[0].a_pdf_path == facility / "提供実績.pdf"
    assert candidates[0].a_pdf_candidates == (facility / "提供実績.pdf",)


def test_a_pdf_multiple_yields_multiple(tmp_path: Path) -> None:
    """事業所直下に PDF が 2 件以上 → A_MULTIPLE（AC-4）。"""
    _make_facility(tmp_path, "複数", a_pdfs=("提供実績.pdf", "old_提供実績.pdf"))

    candidates = scan_facility_root(tmp_path)

    cand = candidates[0]
    assert cand.status == FacilityStatus.A_MULTIPLE
    assert cand.a_pdf_path is None
    assert len(cand.a_pdf_candidates) == 2


# -----------------------------------------------------------------------------
# 命名・パスのエッジケース
# -----------------------------------------------------------------------------


def test_japanese_facility_name_with_special_chars(tmp_path: Path) -> None:
    """日本語・括弧・記号入りの事業所名でも例外なくスキャンできる（AC-11）。"""
    name = "きなり(メール)※持参"
    _make_facility(tmp_path, name, a_pdfs=("提供実績.pdf",))

    candidates = scan_facility_root(tmp_path)

    assert len(candidates) == 1
    assert candidates[0].facility_name == name
    assert candidates[0].status == FacilityStatus.PENDING


def test_pdf_extension_case_insensitive(tmp_path: Path) -> None:
    """`.PDF`（大文字）も A 候補として認識される（Windows で混在ありうる）。"""
    facility = _make_facility(tmp_path, "拡張子大文字", a_pdfs=("提供実績.PDF",))

    candidates = scan_facility_root(tmp_path)

    assert len(candidates) == 1
    cand = candidates[0]
    assert cand.status == FacilityStatus.PENDING
    assert cand.a_pdf_path == facility / "提供実績.PDF"


def test_non_pdf_files_ignored(tmp_path: Path) -> None:
    """直下に .txt / .docx / 拡張子なし がある場合も A 候補に含めない。"""
    facility = _make_facility(tmp_path, "雑多", a_pdfs=("提供実績.pdf",))
    (facility / "メモ.txt").write_text("note", encoding="utf-8")
    (facility / "資料.docx").write_bytes(b"\x00")
    (facility / "README").write_text("readme", encoding="utf-8")

    candidates = scan_facility_root(tmp_path)

    assert candidates[0].status == FacilityStatus.PENDING
    assert candidates[0].a_pdf_path == facility / "提供実績.pdf"


# -----------------------------------------------------------------------------
# ルートレベルのエラーハンドリング（AC-9）
# -----------------------------------------------------------------------------


def test_empty_root_returns_empty_list(tmp_path: Path) -> None:
    """空のルート → 空リスト（クラッシュしない）。"""
    candidates = scan_facility_root(tmp_path)
    assert candidates == []


def test_nonexistent_root_raises_file_not_found(tmp_path: Path) -> None:
    """存在しないルート → FileNotFoundError（AC-9 の一部、UI 側で文言変換）。"""
    missing = tmp_path / "does_not_exist"
    with pytest.raises(FileNotFoundError):
        scan_facility_root(missing)


def test_root_is_file_raises(tmp_path: Path) -> None:
    """ルートがファイル → NotADirectoryError（AC-9）。"""
    target = tmp_path / "file.txt"
    target.write_text("not a dir", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        scan_facility_root(target)


def test_multiple_facilities_returned_sorted_by_name(tmp_path: Path) -> None:
    """複数事業所は facility_name でソートされて返る（一覧表示の安定性）。"""
    _make_facility(tmp_path, "C事業所", a_pdfs=("A.pdf",))
    _make_facility(tmp_path, "A事業所", a_pdfs=("A.pdf",))
    _make_facility(tmp_path, "B事業所", a_pdfs=("A.pdf",))

    candidates = scan_facility_root(tmp_path)

    names = [c.facility_name for c in candidates]
    assert names == sorted(names)


def test_candidate_is_frozen_dataclass(tmp_path: Path) -> None:
    """FacilityCandidate は frozen で deep immutability。

    UI から状態変化（チェック ON/OFF や A_MULTIPLE 解決）は別構造で持つ。
    """
    _make_facility(tmp_path, "事業所", a_pdfs=("A.pdf",))

    candidates = scan_facility_root(tmp_path)

    assert isinstance(candidates[0], FacilityCandidate)
    with pytest.raises((AttributeError, TypeError)):
        candidates[0].facility_name = "改変"  # type: ignore[misc]


def test_output_path_is_computed_under_facility_dir(tmp_path: Path) -> None:
    """output_pdf_path は事業所サブフォルダ自身に作られる（要件 3）。"""
    facility = _make_facility(tmp_path, "出力先確認", a_pdfs=("A.pdf",))

    candidates = scan_facility_root(tmp_path)

    cand = candidates[0]
    assert cand.output_pdf_path == facility / "出力先確認.pdf"


def test_existing_output_flag_when_no_output(tmp_path: Path) -> None:
    """初回スキャン（出力なし）→ has_existing_output=False。"""
    _make_facility(tmp_path, "初回", a_pdfs=("A.pdf",))

    candidates = scan_facility_root(tmp_path)

    assert candidates[0].has_existing_output is False


def test_root_with_mixed_facility_and_non_facility_dirs(tmp_path: Path) -> None:
    """事業所と非事業所の混在 → 事業所のみ列挙されエラーは出ない。"""
    _make_facility(tmp_path, "事業所1", a_pdfs=("A.pdf",))
    (tmp_path / "ゴミ箱").mkdir()
    (tmp_path / "_template").mkdir()
    _make_facility(
        tmp_path, "_template_facility", has_plan=False, has_report=False
    )

    candidates = scan_facility_root(tmp_path)

    assert len(candidates) == 1
    assert candidates[0].facility_name == "事業所1"
