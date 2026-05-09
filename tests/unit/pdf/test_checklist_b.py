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

from wiseman_hub.pdf.checklist_b import find_monitoring_dir


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
