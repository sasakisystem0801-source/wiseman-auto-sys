"""`python -m wiseman_hub --smoke-test` のテスト（Issue #80）。

AC-1〜AC-6（impl-plan の Acceptance Criteria）を検証する:

- AC-1: smoke モードが exit 0 で完了する（macOS で）
- AC-2: smoke モードで Tkinter が import されない（GUI 副作用ゼロ）
- AC-3: smoke モードで HTTP リクエストが発火しない
- AC-4: smoke 内の fitz.open がダミー PDF を読める
- AC-5: smoke 内の split_pdf_with_bbox が ≥ 1 件返す
- AC-6: smoke 失敗時の出力に PII（PDF パス・氏名）が含まれない

Windows CI での AC-7〜AC-10 は build-windows-smoke.yml ワークフローで検証する。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest


def test_smoke_test_exits_zero(monkeypatch: Any) -> None:
    """AC-1: --smoke-test 指定で main() が SystemExit せず正常に return する。"""
    monkeypatch.setattr(sys, "argv", ["wiseman-hub", "--smoke-test"])

    from wiseman_hub.__main__ import main

    main()  # 例外なく完了することが AC-1（_run_smoke_test 内で sys.exit(1) も起きない）


def test_smoke_test_does_not_import_tkinter() -> None:
    """AC-2: smoke 経路で tkinter が import されない（GUI 副作用ゼロ）。

    既存テストで tkinter が既に import されているとフィルタしきれないため、
    subprocess で別プロセス起動して sys.modules を検証する（実測 < 0.3 秒）。
    """
    project_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "from wiseman_hub.__main__ import _run_smoke_test; "
                "_run_smoke_test(); "
                "print('TK_IN_MODULES' if 'tkinter' in sys.modules else 'NO_TK')"
            ),
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, (
        f"_run_smoke_test exited non-zero: stderr={result.stderr}"
    )
    assert "NO_TK" in result.stdout, (
        f"tkinter was imported in smoke path: stdout={result.stdout}"
    )


def test_smoke_test_does_not_send_http(monkeypatch: Any) -> None:
    """AC-3: smoke 内で OcrClient init は成功するが HTTP リクエストは発火しない。"""
    import httpx

    post_mock = MagicMock(side_effect=AssertionError("HTTP must not be sent in smoke"))
    monkeypatch.setattr(httpx.Client, "post", post_mock)

    from wiseman_hub.__main__ import _run_smoke_test

    _run_smoke_test()

    post_mock.assert_not_called()


def test_smoke_test_split_returns_one_page() -> None:
    """AC-4 + AC-5: ダミー PDF を fitz で生成 → split_pdf_with_bbox が 1 件返す。

    `_run_smoke_test()` 内部の split 結果検証で len != 1 だと RuntimeError raise →
    `sys.exit(1)` のため、本テストでは関数が例外なく完走することで間接的に検証する。
    """
    from wiseman_hub.__main__ import _run_smoke_test

    _run_smoke_test()  # raise されない = AC-4/AC-5 PASS


def test_smoke_test_failure_exits_one_and_writes_only_type_name(
    monkeypatch: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-6: smoke 失敗時に exit 1 + stderr に型名のみ（PII リーク防止）。

    OcrClient.__init__ をパスや氏名を含む例外を上げる差し替えで fail させ:
      1. SystemExit(1) で fail-fast すること
      2. stderr に書かれるのは ``smoke test failed: <TypeName>`` のみで、
         例外メッセージ内の PII（パス・氏名）が含まれないこと
    の両方を一度に検証する。
    """

    class _FakePIIError(Exception):
        pass

    def _raise(*_args: Any, **_kwargs: Any) -> None:
        raise _FakePIIError("/secret/path/to/患者太郎.pdf was rejected")

    monkeypatch.setattr(
        "wiseman_hub.pdf.ocr_client.OcrClient.__init__",
        _raise,
    )

    from wiseman_hub.__main__ import _run_smoke_test

    with pytest.raises(SystemExit) as excinfo:
        _run_smoke_test()
    assert excinfo.value.code == 1

    captured = capsys.readouterr()
    assert "_FakePIIError" in captured.err, (
        f"型名が stderr に含まれるべき: {captured.err!r}"
    )
    assert "/secret/path" not in captured.err, (
        f"PII（パス）が stderr に漏洩した: {captured.err!r}"
    )
    assert "患者太郎" not in captured.err, (
        f"PII（氏名）が stderr に漏洩した: {captured.err!r}"
    )
