"""checklist_b の find_monitoring_dir ユニットテスト (Issue #monitoring-substring)。

業務要件: モニタリングサブフォルダの命名が利用者により揺らぐ
(``08.運動器機能向上計画書`` / ``10.運動器機能向上計画書`` / prefix なし /
``運動器機能向上計画書(過去分)`` 等)。設定値を canonical name のみ
(= ``運動器機能向上計画書``) にし、substring match で全パターン拾う。

PII 防御: テストデータには実在介護施設名・利用者名を含めない。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wiseman_hub.cloud.sheets import ChecklistRow
from wiseman_hub.config import ChecklistConfig
from wiseman_hub.pdf.checklist_b import (
    PlacementStatus,
    _parse_year_folder_name,
    find_monitoring_dir,
    find_month_pdf,
    plan_b_placement,
    resolve_facility,
)
from wiseman_hub.utils.text_norm import normalize_lookup_key


@pytest.fixture
def user_dir(tmp_path: Path) -> Path:
    """利用者フォルダの fixture (空)。"""
    user = tmp_path / "(さんわ)三和太郎"
    user.mkdir()
    return user


class TestFindMonitoringDir:
    """``canonical_name`` の substring match で揺らぎを吸収する。"""

    def test_numeric_prefix_matches(self, user_dir: Path) -> None:
        """``08.運動器機能向上計画書`` (数字 prefix 付き) が一意 HIT。"""
        target = user_dir / "08.運動器機能向上計画書"
        target.mkdir()

        matched, candidates = find_monitoring_dir(user_dir, "運動器機能向上計画書")
        assert matched == target
        assert candidates == [target]

    def test_different_numeric_prefix_matches(self, user_dir: Path) -> None:
        """``10.運動器機能向上計画書`` (= 業務で問題発生していたケース) も HIT。"""
        target = user_dir / "10.運動器機能向上計画書"
        target.mkdir()

        matched, candidates = find_monitoring_dir(user_dir, "運動器機能向上計画書")
        assert matched == target
        assert candidates == [target]

    def test_no_prefix_matches(self, user_dir: Path) -> None:
        """prefix なしの ``運動器機能向上計画書`` も HIT。"""
        target = user_dir / "運動器機能向上計画書"
        target.mkdir()

        matched, candidates = find_monitoring_dir(user_dir, "運動器機能向上計画書")
        assert matched == target
        assert candidates == [target]

    def test_suffix_variation_matches(self, user_dir: Path) -> None:
        """``運動器機能向上計画書(過去分)`` (suffix あり) も substring match で HIT。

        業務要件: 派生フォルダも当該利用者で実体 1 個なら受け入れる
        (= 同居なし前提、ユーザー確認済 2026-05-09)。
        """
        target = user_dir / "運動器機能向上計画書(過去分)"
        target.mkdir()

        matched, candidates = find_monitoring_dir(user_dir, "運動器機能向上計画書")
        assert matched == target
        assert candidates == [target]

    def test_old_prefix_variation_matches(self, user_dir: Path) -> None:
        """``_old_運動器機能向上計画書`` (任意 prefix) も HIT。"""
        target = user_dir / "_old_運動器機能向上計画書"
        target.mkdir()

        matched, candidates = find_monitoring_dir(user_dir, "運動器機能向上計画書")
        assert matched == target
        assert candidates == [target]

    def test_unrelated_folder_not_matched(self, user_dir: Path) -> None:
        """canonical name を含まない別系統フォルダは不一致。"""
        (user_dir / "01.基本情報").mkdir()
        (user_dir / "運動器カルテ").mkdir()  # 「運動器」は含むが canonical 全体ではない

        matched, candidates = find_monitoring_dir(user_dir, "運動器機能向上計画書")
        assert matched is None
        assert candidates == []

    def test_multiple_matches_returns_ambiguous(self, user_dir: Path) -> None:
        """複数 HIT 時は ``matched=None`` + 全候補返却 (= 人間判断に倒す)。

        業務上は同居なし前提だが、防御として AMBIGUOUS skip 経路を成立させる
        (誤配置 0 = ADR-013 / specs/c-business-deployment コンプライアンス要件)。
        """
        first = user_dir / "08.運動器機能向上計画書"
        second = user_dir / "運動器機能向上計画書(過去分)"
        first.mkdir()
        second.mkdir()

        matched, candidates = find_monitoring_dir(user_dir, "運動器機能向上計画書")
        assert matched is None
        # candidates は sort 順
        assert sorted(candidates) == sorted([first, second])
        assert len(candidates) == 2

    def test_nonexistent_user_dir_returns_empty(self, tmp_path: Path) -> None:
        """利用者フォルダが存在しない場合は ``(None, [])``。"""
        ghost = tmp_path / "ghost_user"
        matched, candidates = find_monitoring_dir(ghost, "運動器機能向上計画書")
        assert matched is None
        assert candidates == []

    def test_files_not_directories_are_ignored(self, user_dir: Path) -> None:
        """フォルダ名にマッチしてもファイルは候補に含めない (is_dir 判定)。"""
        (user_dir / "運動器機能向上計画書.txt").write_text("decoy")  # ファイル
        target = user_dir / "08.運動器機能向上計画書"
        target.mkdir()

        matched, candidates = find_monitoring_dir(user_dir, "運動器機能向上計画書")
        assert matched == target
        assert candidates == [target]

    # ----- Review SF6: canonical_name length guard -----

    def test_empty_canonical_name_rejected(
        self, user_dir: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """canonical_name が空文字列なら全 dir HIT を防止して ``(None, [])``。"""
        (user_dir / "08.運動器機能向上計画書").mkdir()
        (user_dir / "01.基本情報").mkdir()

        with caplog.at_level("ERROR"):
            matched, candidates = find_monitoring_dir(user_dir, "")
        assert matched is None
        assert candidates == []
        assert any("too short" in r.message for r in caplog.records)

    def test_short_canonical_name_rejected(
        self, user_dir: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """``運動`` (2 文字) は誤一致リスクのため reject (3 文字未満)。"""
        (user_dir / "運動器カルテ").mkdir()
        (user_dir / "運動療法").mkdir()

        with caplog.at_level("ERROR"):
            matched, candidates = find_monitoring_dir(user_dir, "運動")
        assert matched is None
        assert candidates == []

    def test_whitespace_only_canonical_name_rejected(
        self, user_dir: Path
    ) -> None:
        """全角/半角スペースのみの canonical_name も reject (_normalize_name 経由)。"""
        (user_dir / "08.運動器機能向上計画書").mkdir()

        matched, candidates = find_monitoring_dir(user_dir, "　 　")  # 全角+半角
        assert matched is None
        assert candidates == []

    # ----- Review CR2: _normalize_name 適用 (全角スペース揺らぎ) -----

    def test_fullwidth_space_in_folder_name_matches(self, user_dir: Path) -> None:
        """フォルダ名に全角スペースが混入していても _normalize_name 経由で HIT。"""
        target = user_dir / "08.運動器　機能向上計画書"  # 全角スペース混入
        target.mkdir()

        matched, candidates = find_monitoring_dir(user_dir, "運動器機能向上計画書")
        assert matched == target

    def test_fullwidth_space_in_canonical_name_matches(
        self, user_dir: Path
    ) -> None:
        """設定値に全角スペースが混入していても _normalize_name 経由で HIT。"""
        target = user_dir / "08.運動器機能向上計画書"
        target.mkdir()

        matched, _ = find_monitoring_dir(user_dir, "運動器　機能向上計画書")
        assert matched == target

    # ----- Review C1: iterdir OSError catch -----

    def test_iterdir_oserror_returns_empty_without_crash(
        self,
        user_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """iterdir で OSError が発生しても ``(None, [])`` で graceful 復帰。

        NAS 切断 / 権限 / TOCTOU 等のリアルなケースをシミュレート。
        バッチ全体クラッシュを防ぐ Review C1 の動作確認。
        """
        original_iterdir = Path.iterdir

        def _fail_iterdir(self: Path) -> object:
            if self == user_dir:
                raise PermissionError("simulated NAS permission denied")
            return original_iterdir(self)

        monkeypatch.setattr(Path, "iterdir", _fail_iterdir)

        with caplog.at_level("WARNING"):
            matched, candidates = find_monitoring_dir(
                user_dir, "運動器機能向上計画書"
            )
        assert matched is None
        assert candidates == []
        # PII 防御確認: log に user_dir の path が含まれない (型名のみ)
        assert any("PermissionError" in r.message for r in caplog.records)
        for r in caplog.records:
            assert str(user_dir) not in r.message  # PII safety


# ---------------------------------------------------------------------------
# plan_b_placement の monitoring 分岐 (Review G1: business KPI 直結)
# ---------------------------------------------------------------------------


def _make_row(name: str = "三和太郎") -> ChecklistRow:
    """テスト用 ChecklistRow を最小フィールドで構築。"""
    return ChecklistRow(
        name=name,
        monitoring_raw="3/15",
        staff="宮下",
        facility="きなり",
    )


def _make_config(karte_root: Path, fax_root: Path) -> ChecklistConfig:
    """テスト用 ChecklistConfig (canonical name + facility_routing 1 件)。

    Issue #27 続編 G Phase 3a: karte_root / fax_root は Path 型に移行済 (Path 直渡し)。
    """
    return ChecklistConfig(
        karte_root=karte_root,
        fax_root=fax_root,
        monitoring_subfolder="運動器機能向上計画書",
        facility_routing={"きなり": "きなり(メール)※持参"},
    )


class TestPlanBPlacementMonitoringBranches:
    """``plan_b_placement`` 内の monitoring 分岐 3 経路 (Review G1 rating 9)。"""

    def test_no_monitoring_dir_skipped_with_dedicated_status(
        self, tmp_path: Path
    ) -> None:
        """0 件 HIT → ``SKIPPED_NO_MONITORING_DIR`` で SKIPPED_NO_PDF と区別。"""
        karte_root = tmp_path / "karte"
        fax_root = tmp_path / "fax"
        # 利用者フォルダだけ作る (モニタリングフォルダなし)
        user_dir = karte_root / "さ" / "(さんわ)三和太郎"
        user_dir.mkdir(parents=True)
        (fax_root / "きなり(メール)※持参").mkdir(parents=True)

        cfg = _make_config(karte_root, fax_root)
        results = plan_b_placement([_make_row()], cfg, month=3)

        assert len(results) == 1
        assert results[0].status is PlacementStatus.SKIPPED_NO_MONITORING_DIR
        # 業務文脈で identification 可能なメッセージ
        assert "モニタリングフォルダ未発見" in results[0].message
        assert cfg.monitoring_subfolder in results[0].message

    def test_multiple_monitoring_dirs_skipped_ambiguous(
        self, tmp_path: Path
    ) -> None:
        """複数 HIT → ``SKIPPED_AMBIGUOUS`` + 候補返却 (誤配置 0 / 人間判断)。"""
        karte_root = tmp_path / "karte"
        fax_root = tmp_path / "fax"
        user_dir = karte_root / "さ" / "(さんわ)三和太郎"
        # メイン + 派生の同居 (= AMBIGUOUS)
        (user_dir / "08.運動器機能向上計画書").mkdir(parents=True)
        (user_dir / "運動器機能向上計画書(過去分)").mkdir(parents=True)
        (fax_root / "きなり(メール)※持参").mkdir(parents=True)

        cfg = _make_config(karte_root, fax_root)
        results = plan_b_placement([_make_row()], cfg, month=3)

        assert len(results) == 1
        assert results[0].status is PlacementStatus.SKIPPED_AMBIGUOUS
        assert len(results[0].candidates) == 2
        assert "候補 2 件" in results[0].message

    def test_single_monitoring_dir_with_month_pdf_pending(
        self, tmp_path: Path
    ) -> None:
        """1 件 HIT で月 PDF あり → ``PENDING`` (既存挙動 regression なし)。"""
        karte_root = tmp_path / "karte"
        fax_root = tmp_path / "fax"
        user_dir = karte_root / "さ" / "(さんわ)三和太郎"
        monitoring_dir = user_dir / "10.運動器機能向上計画書"  # 数字 prefix 揺らぎ
        monitoring_dir.mkdir(parents=True)
        (monitoring_dir / "3.pdf").write_bytes(b"%PDF-1.4")
        (fax_root / "きなり(メール)※持参").mkdir(parents=True)

        cfg = _make_config(karte_root, fax_root)
        results = plan_b_placement([_make_row()], cfg, month=3)

        assert len(results) == 1
        assert results[0].status is PlacementStatus.PENDING
        assert results[0].source_pdf == monitoring_dir / "3.pdf"

    def test_year_folder_r7_with_month_pdf_pending(self, tmp_path: Path) -> None:
        """Issue #282: ``R7/3.pdf`` (新構造) でも ``PENDING`` 配置成功。"""
        karte_root = tmp_path / "karte"
        fax_root = tmp_path / "fax"
        user_dir = karte_root / "さ" / "(さんわ)三和太郎"
        monitoring_dir = user_dir / "11.運動器機能向上計画書"
        year_dir = monitoring_dir / "R7"
        year_dir.mkdir(parents=True)
        (year_dir / "3.pdf").write_bytes(b"%PDF-1.4")
        (fax_root / "きなり(メール)※持参").mkdir(parents=True)

        cfg = _make_config(karte_root, fax_root)
        results = plan_b_placement([_make_row()], cfg, month=3)

        assert len(results) == 1
        assert results[0].status is PlacementStatus.PENDING
        assert results[0].source_pdf == year_dir / "3.pdf"


# ---------------------------------------------------------------------------
# Issue #282: R<年> フォルダ表記揺れ吸収 (_parse_year_folder_name)
# ---------------------------------------------------------------------------


class TestParseYearFolderName:
    """``_parse_year_folder_name`` が R<年> 表記揺れを吸収する (Issue #282)。"""

    @pytest.mark.parametrize(
        "folder_name,expected",
        [
            # 基本: 半角
            ("R7", 7),
            ("R10", 10),
            # 全角混在 (NFKC で半角化)
            ("R７", 7),
            ("Ｒ7", 7),
            ("Ｒ７", 7),
            # スペース挿入
            ("R 7", 7),
            ("R　7", 7),  # 全角スペース
            # 区切り文字挿入
            ("R.7", 7),
            ("R-7", 7),
            # 小文字
            ("r7", 7),
            # 複数桁
            ("Ｒ１０", 10),
        ],
    )
    def test_year_extracted_from_variations(
        self, folder_name: str, expected: int
    ) -> None:
        """表記揺れ 11 パターンから年数値が正しく抽出される。"""
        assert _parse_year_folder_name(folder_name) == expected

    @pytest.mark.parametrize(
        "folder_name",
        [
            "",
            "R",
            "R abc",
            "A7",  # 別アルファベット
            "H30",  # 平成 (本 Issue scope 外)
            "令和7",  # 漢字表記 (本 Issue scope 外)
            "2025",  # 西暦 (本 Issue scope 外)
            "R7年",  # 末尾に余分な文字
            "前R7",  # 先頭に余分な文字
        ],
    )
    def test_non_r_year_format_returns_none(self, folder_name: str) -> None:
        """R<年> 形式として解釈不能なら None を返す。"""
        assert _parse_year_folder_name(folder_name) is None


# ---------------------------------------------------------------------------
# Issue #282: find_month_pdf の年フォルダ対応
# ---------------------------------------------------------------------------


class TestFindMonthPdfYearFolder:
    """``find_month_pdf`` が R<年> サブフォルダを走査する (Issue #282)。"""

    def test_direct_placement_preferred_over_year_folder(
        self, tmp_path: Path
    ) -> None:
        """旧/新構造混在時は直配置を優先 (旧運用との後方互換)。"""
        monitoring = tmp_path / "11.運動器機能向上計画書"
        (monitoring / "R7").mkdir(parents=True)
        (monitoring / "3.pdf").write_bytes(b"%PDF-1.4 direct")
        (monitoring / "R7" / "3.pdf").write_bytes(b"%PDF-1.4 year")

        found, _ = find_month_pdf(monitoring, 3)
        assert found == monitoring / "3.pdf"

    def test_year_folder_only_found(self, tmp_path: Path) -> None:
        """直配置なし + R7 のみ → R7/3.pdf を返す。"""
        monitoring = tmp_path / "11.運動器機能向上計画書"
        year_dir = monitoring / "R7"
        year_dir.mkdir(parents=True)
        (year_dir / "3.pdf").write_bytes(b"%PDF-1.4")

        found, _ = find_month_pdf(monitoring, 3)
        assert found == year_dir / "3.pdf"

    def test_latest_year_folder_preferred(self, tmp_path: Path) -> None:
        """複数年フォルダ存在時は R 数字最大 (最新年) を優先。"""
        monitoring = tmp_path / "11.運動器機能向上計画書"
        for year_name in ["R6", "R7", "R8"]:
            d = monitoring / year_name
            d.mkdir(parents=True)
            (d / "3.pdf").write_bytes(f"%PDF-1.4 {year_name}".encode())

        found, _ = find_month_pdf(monitoring, 3)
        assert found == monitoring / "R8" / "3.pdf"

    def test_falls_through_to_older_year_if_target_missing(
        self, tmp_path: Path
    ) -> None:
        """最新年 R8 に 3.pdf がなく R7 にあれば R7 を返す。"""
        monitoring = tmp_path / "11.運動器機能向上計画書"
        (monitoring / "R8").mkdir(parents=True)  # 空
        r7 = monitoring / "R7"
        r7.mkdir(parents=True)
        (r7 / "3.pdf").write_bytes(b"%PDF-1.4")

        found, _ = find_month_pdf(monitoring, 3)
        assert found == r7 / "3.pdf"

    @pytest.mark.parametrize(
        "year_folder_name",
        ["R7", "R７", "Ｒ7", "Ｒ７", "R 7", "R　7", "R.7", "R-7", "r7"],
    )
    def test_year_folder_notation_variations_matched(
        self, year_folder_name: str, tmp_path: Path
    ) -> None:
        """表記揺れ 9 パターンの年フォルダで PDF 発見可能。"""
        monitoring = tmp_path / "11.運動器機能向上計画書"
        year_dir = monitoring / year_folder_name
        year_dir.mkdir(parents=True)
        (year_dir / "3.pdf").write_bytes(b"%PDF-1.4")

        found, _ = find_month_pdf(monitoring, 3)
        assert found == year_dir / "3.pdf"

    def test_non_year_folder_ignored(self, tmp_path: Path) -> None:
        """R<年> 形式以外のサブフォルダは走査対象外。"""
        monitoring = tmp_path / "11.運動器機能向上計画書"
        (monitoring / "過去分").mkdir(parents=True)
        (monitoring / "過去分" / "3.pdf").write_bytes(b"%PDF-1.4")

        found, _ = find_month_pdf(monitoring, 3)
        assert found is None

    def test_empty_monitoring_dir_returns_none(self, tmp_path: Path) -> None:
        """空ディレクトリ → None。"""
        monitoring = tmp_path / "11.運動器機能向上計画書"
        monitoring.mkdir(parents=True)

        found, all_pdfs = find_month_pdf(monitoring, 3)
        assert found is None
        assert all_pdfs == []

    def test_nonexistent_monitoring_dir_returns_none(self, tmp_path: Path) -> None:
        """存在しないディレクトリ → None。"""
        monitoring = tmp_path / "does_not_exist"
        found, all_pdfs = find_month_pdf(monitoring, 3)
        assert found is None
        assert all_pdfs == []

    def test_year_folder_other_month_pdfs_do_not_interfere(
        self, tmp_path: Path
    ) -> None:
        """年フォルダ内に対象月以外の .pdf が混ざっていても一意確定。"""
        monitoring = tmp_path / "11.運動器機能向上計画書"
        year_dir = monitoring / "R7"
        year_dir.mkdir(parents=True)
        (year_dir / "3.pdf").write_bytes(b"%PDF-1.4")
        (year_dir / "4.pdf").write_bytes(b"%PDF-1.4")

        found, _ = find_month_pdf(monitoring, 3)
        assert found == year_dir / "3.pdf"

    # ----- codex review (#282) 反映: 誤確定リスクの早期 return -----

    def test_direct_ambiguous_does_not_fall_through_to_year_folder(
        self, tmp_path: Path
    ) -> None:
        """codex High-1: 直下に月マッチ複数 (3.pdf + 03.pdf) があれば、R7 フォルダ
        に確定 PDF があっても AMBIGUOUS で早期 return する (誤確定防止)。"""
        monitoring = tmp_path / "11.運動器機能向上計画書"
        monitoring.mkdir(parents=True)
        # 直下に AMBIGUOUS (stem=3 が 2 件: 3.pdf と 03.pdf)
        (monitoring / "3.pdf").write_bytes(b"%PDF-1.4 a")
        (monitoring / "03.pdf").write_bytes(b"%PDF-1.4 b")
        # R7 配下に「確定的な」3.pdf があっても、これに飛ばない
        year_dir = monitoring / "R7"
        year_dir.mkdir()
        (year_dir / "3.pdf").write_bytes(b"%PDF-1.4 year")

        found, all_pdfs = find_month_pdf(monitoring, 3)
        assert found is None
        # 直下の AMBIGUOUS のみ候補返却 (年フォルダ走査前に早期 return)
        assert set(all_pdfs) == {monitoring / "3.pdf", monitoring / "03.pdf"}

    def test_year_ambiguous_does_not_fall_through_to_older_year(
        self, tmp_path: Path
    ) -> None:
        """codex High-2: 最新年 R8 で月マッチ複数 → 古い年 R7 にフォールバックせず
        AMBIGUOUS で早期 return。"""
        monitoring = tmp_path / "11.運動器機能向上計画書"
        # R8 に AMBIGUOUS な月マッチ
        r8 = monitoring / "R8"
        r8.mkdir(parents=True)
        (r8 / "3.pdf").write_bytes(b"%PDF-1.4 a")
        (r8 / "03.pdf").write_bytes(b"%PDF-1.4 b")
        # R7 に「確定的な」3.pdf — これに誤って fall through しないこと
        r7 = monitoring / "R7"
        r7.mkdir()
        (r7 / "3.pdf").write_bytes(b"%PDF-1.4 r7")

        found, _ = find_month_pdf(monitoring, 3)
        assert found is None

    def test_same_logical_year_multiple_folders_ambiguous(
        self, tmp_path: Path
    ) -> None:
        """codex Medium-1: 同一論理年で複数物理フォルダ (R7 + Ｒ７ + 各 3.pdf) が
        あれば、iterdir 順依存の非決定性を避けるため AMBIGUOUS で人間判断に倒す。"""
        monitoring = tmp_path / "11.運動器機能向上計画書"
        r7_half = monitoring / "R7"
        r7_full = monitoring / "Ｒ７"  # NFKC で同じ R7
        r7_half.mkdir(parents=True)
        r7_full.mkdir(parents=True)
        (r7_half / "3.pdf").write_bytes(b"%PDF-1.4 half")
        (r7_full / "3.pdf").write_bytes(b"%PDF-1.4 full")

        found, _ = find_month_pdf(monitoring, 3)
        assert found is None

    # ----- codex High-3: iterdir OSError graceful 復帰 -----

    def test_iterdir_oserror_in_year_dir_graceful(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """年フォルダ ``iterdir`` の OSError (NAS 切断等) で例外伝播せず
        ``(None, [])`` で graceful 復帰 + PII フリー warn ログ。"""
        monitoring = tmp_path / "11.運動器機能向上計画書"
        year_dir = monitoring / "R7"
        year_dir.mkdir(parents=True)
        # year_dir の iterdir のみ失敗させる (monitoring_dir 自体は成功)
        original_iterdir = Path.iterdir

        def _fail_iterdir(self: Path) -> object:
            if self == year_dir:
                raise PermissionError("simulated NAS permission denied")
            return original_iterdir(self)

        monkeypatch.setattr(Path, "iterdir", _fail_iterdir)

        with caplog.at_level("WARNING"):
            found, all_pdfs = find_month_pdf(monitoring, 3)
        assert found is None
        assert all_pdfs == []
        # PII 防御: ログに path が含まれない
        for r in caplog.records:
            assert str(year_dir) not in r.message
        assert any("PermissionError" in r.message for r in caplog.records)

    def test_iterdir_oserror_in_monitoring_dir_returns_direct_pdfs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """``monitoring_dir`` 自体の 2 回目 iterdir (年フォルダ走査前) で OSError なら
        直配置 PDF のみ返して graceful 復帰。"""
        monitoring = tmp_path / "11.運動器機能向上計画書"
        monitoring.mkdir(parents=True)
        (monitoring / "5.pdf").write_bytes(b"%PDF-1.4")  # 月 3 ではないので fall through
        original_iterdir = Path.iterdir
        call_count = {"n": 0}

        def _fail_second_iterdir(self: Path) -> object:
            if self == monitoring:
                call_count["n"] += 1
                if call_count["n"] >= 2:
                    raise PermissionError("simulated NAS error")
            return original_iterdir(self)

        monkeypatch.setattr(Path, "iterdir", _fail_second_iterdir)

        with caplog.at_level("WARNING"):
            found, all_pdfs = find_month_pdf(monitoring, 3)
        assert found is None
        # 1 回目 iterdir (直配置探索) で取得した pdfs は返る
        assert all_pdfs == [monitoring / "5.pdf"]
        assert any("PermissionError" in r.message for r in caplog.records)


class TestResolveFacilityNormalization:
    """B の居宅名 lookup の表記揺れ吸収 (PR-γ v2、Session 78 実機デモ regression)。

    実機デモ (2026-05-15) で ``姫路医療生活協同組合 あぼし`` (半角空白) が
    routing 側 (``姫路医療生活協同組合あぼし``、normalize 後 key) と不一致で
    「居宅マッピング未登録」となった事案を regression 防止する。
    """

    def test_resolve_with_full_width_space_input(self) -> None:
        """スプレッドシート側が全角空白でも routing key (正規化済) と hit。"""
        routing = {
            normalize_lookup_key("姫路医療生活協同組合 あぼし"): "姫路医療生活協同組合 あぼし(メール)",
        }
        # スプレッドシート由来の生の facility_name (全角空白)
        result = resolve_facility("姫路医療生活協同組合　あぼし", routing)
        assert result == "姫路医療生活協同組合 あぼし(メール)"

    def test_resolve_with_no_space_input(self) -> None:
        """スプレッドシート側が空白なしでも routing key と hit (PR-γ v2 新規対応)。"""
        routing = {
            normalize_lookup_key("姫路医療生活協同組合 あぼし"): "姫路医療生活協同組合 あぼし(メール)",
        }
        result = resolve_facility("姫路医療生活協同組合あぼし", routing)
        assert result == "姫路医療生活協同組合 あぼし(メール)"

    def test_resolve_with_half_width_space_input(self) -> None:
        """スプレッドシート側が半角空白の通常パターン (旧仕様で動いていたケース)。"""
        routing = {
            normalize_lookup_key("姫路医療生活協同組合 あぼし"): "姫路医療生活協同組合 あぼし(メール)",
        }
        result = resolve_facility("姫路医療生活協同組合 あぼし", routing)
        assert result == "姫路医療生活協同組合 あぼし(メール)"

    def test_resolve_unknown_returns_none(self) -> None:
        """routing 未登録の facility 名は None。"""
        routing = {
            normalize_lookup_key("姫路医療生活協同組合 あぼし"): "姫路医療生活協同組合 あぼし(メール)",
        }
        assert resolve_facility("未登録居宅", routing) is None

    def test_resolve_three_patterns_match_same_key(self) -> None:
        """全角 / 半角 / 空白なし の 3 パターンが同一 routing key を引く (B/C 整合)。"""
        routing = {
            normalize_lookup_key("姫路医療生活協同組合 あぼし"): "FAX_NAME",
        }
        assert (
            resolve_facility("姫路医療生活協同組合　あぼし", routing)
            == resolve_facility("姫路医療生活協同組合 あぼし", routing)
            == resolve_facility("姫路医療生活協同組合あぼし", routing)
            == "FAX_NAME"
        )
