"""Issue #210 review C1 (type-design Critical) + Important 82 (code-reviewer) 反映。

PR #228 review で `test_phase_literal_typo_rejected_by_mypy` が CI で mypy 対象外
(``pyproject.toml`` ``mypy.exclude = ["^tests/"]``) のため lock-in 効果ゼロの
dead code 状態と指摘された。本 file を `.github/workflows/test-unit.yml` の
``Type check (assert_type lock-in tests)`` step に追加し、Phase Literal narrow を
**実 enforce** する。

本 file は意図的に小さく保ち、既存 ``test_updater.py`` の dict→ManifestData mismatch
11 errors (Issue #209 PR2 由来の既知 scope 外問題) を CI mypy 対象に巻き込まない。
将来 ``_good_manifest()`` を ``ManifestData`` 化した別 PR で全 ``test_updater.py`` を
CI mypy 対象に格上げする想定。

precedent: ``tests/unit/launcher/test_manifest.py`` の Sha256Hex assert_type 版
(Issue #209 PR1)。本 file はそれと同パターンで CI step を追加する。
"""

from __future__ import annotations

from typing import assert_type

from wiseman_hub_launcher.updater import Phase, _phase_log


def test_phase_literal_typo_rejected_by_mypy() -> None:
    """Phase Literal narrow が typo を mypy で reject する static contract。

    runtime no-op (Literal は runtime 効果なし)。CI で本 file が mypy 対象になることで
    typo 反例が compile-time で reject され、type と production callsite の整合が
    静的に保証される。
    """
    # production phase 名は Phase narrow 通過 (assert_type は runtime no-op)
    valid_phase: Phase = "read_current"
    assert_type(valid_phase, Phase)

    # 反例: typo 化した phase 名は Phase narrow を通らないため、mypy が
    # ``Incompatible types in assignment`` で reject する。
    # # type: ignore は「mypy がここで型エラーを出すこと」を期待値として明示する。
    # 万一 mypy が本行を reject しなくなった場合は ``unused-ignore`` で別の error
    # が出るため、CI が green のまま regression が通ることはない。
    typo_phase: Phase = "downlaod_start"  # type: ignore[assignment]
    _ = typo_phase  # 未使用警告抑止


def test_phase_log_signature_locked_to_phase() -> None:
    """type-design S3 反映: ``_phase_log`` の signature 自体を lock-in する。

    誰かが ``_phase_log(phase: str, ...)`` に regress させても、本 test の
    valid call が引き続き OK + 反例 typo が mypy reject されないと検知できない。
    """
    # 正常 call: production callsite と同じ shape
    _phase_log("read_current", version="1.2.3", error_count=3)

    # 反例: typo を直接 _phase_log に渡しても mypy が reject する。
    # signature が phase: str に regress すると本 type:ignore が unused-ignore に化けて CI 落ちる。
    _phase_log("downlaod_start", x=1)  # type: ignore[arg-type]
