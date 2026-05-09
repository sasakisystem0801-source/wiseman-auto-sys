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
    find_monitoring_dir,
    plan_b_placement,
)


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
    """テスト用 ChecklistConfig (canonical name + facility_routing 1 件)。"""
    return ChecklistConfig(
        karte_root=str(karte_root),
        fax_root=str(fax_root),
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
