"""Issue #227 type-design 反映: LauncherExitCode IntEnum 静的 narrow 検証 lock-in。

PR #226 の type-design-analyzer が rating 7 + confidence 90 で指摘した C2/C3
(EXIT_* int literal が narrow されず、docstring と二重管理) の解消後、本 file を
``.github/workflows/test-unit.yml`` の ``Type check (assert_type lock-in tests)`` step
に追加して lock-in を **実 enforce** する。

precedent:
    - ``tests/unit/launcher/test_manifest.py`` (Issue #209 PR1, Sha256Hex)
    - ``tests/unit/launcher/test_updater_phase_lockin.py`` (Issue #210, Phase Literal)

本 file は意図的に小さく保ち、既存 ``test_main.py`` (38 件) は CI mypy 対象外のままにする
(``pyproject.toml`` ``mypy.exclude = ["^tests/"]``)。本 file のみ workflow yaml で個別に
mypy 対象に格上げする。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, assert_type

from wiseman_hub_launcher.__main__ import LauncherExitCode


def test_launcher_exit_code_lock_in() -> None:
    """LauncherExitCode IntEnum の static narrow を assert_type で lock-in する。

    runtime: ``LauncherExitCode.OK`` に対する assert_type は no-op (typing.assert_type
    は runtime 上 `value` を素通しで返す)。
    static: 本 file を CI mypy 対象に入れることで以下が enforce される:

    - ``LauncherExitCode.OK`` は ``LauncherExitCode`` 型に narrow される
    - 存在しない member (例: ``LauncherExitCode.OOK``) は attr-defined error で reject
    """
    valid = LauncherExitCode.OK
    assert_type(valid, LauncherExitCode)


# typo 反例 + signature lock-in は runtime 実行すると AttributeError / 副作用が出るため、
# TYPE_CHECKING gate で static のみ評価する。runtime no-op、mypy 上は通常 module の如く解析。
# 本 block を CI mypy 対象に入れることで Phase Literal lock-in (Issue #210) と同等の
# 「regression が CI green のまま通らない」性質を実現する。
if TYPE_CHECKING:
    from wiseman_hub_launcher.__main__ import main, run_smoke_test

    def _typo_member_rejected_by_mypy() -> None:
        """存在しない member は mypy attr-defined error で reject。

        ``# type: ignore[attr-defined]`` は「ここで型エラーを出すこと」を期待値として
        明示する。万一 mypy が本行を reject しなくなったら ``unused-ignore`` で別 error
        が出るため、CI が green のまま regression が通ることはない。
        """
        typo_value: LauncherExitCode = LauncherExitCode.OOK  # type: ignore[attr-defined]
        _ = typo_value

    def _signature_returns_launcher_exit_code() -> None:
        """``main`` / ``run_smoke_test`` の戻り値が LauncherExitCode に narrow されている。

        誰かが戻り値を ``int`` に regress させたら assert_type が fail する。
        旧 ``int`` のままだと typo 検出機構ごと失われるため、signature 自体を lock-in する。
        """
        code = main([])
        assert_type(code, LauncherExitCode)

        smoke_code = run_smoke_test()
        assert_type(smoke_code, LauncherExitCode)
