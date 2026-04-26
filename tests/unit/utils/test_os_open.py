"""OS open utils のユニットテスト。

`open_with_default_app(path)` がプラットフォームごとに正しいコマンドを呼び出し、
セキュリティ上 shell=False を維持していることを検証する。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from wiseman_hub.utils.os_open import open_with_default_app


class _SpyRun:
    """subprocess.run のスパイ。args / kwargs を記録するだけで実行はしない。"""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.kwargs: list[dict[str, Any]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(args)
        self.kwargs.append(kwargs)

        class _Done:
            returncode = 0

        return _Done()


class _SpyStartfile:
    """os.startfile のスパイ（Windows 専用 API）。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, path: str) -> None:
        self.calls.append(path)


def test_macos_uses_open_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """macOS では `open <path>` が subprocess.run で呼ばれる。"""
    target = tmp_path / "dummy.pdf"
    target.write_bytes(b"%PDF-1.4\n")

    spy = _SpyRun()
    monkeypatch.setattr("wiseman_hub.utils.os_open.sys.platform", "darwin")
    monkeypatch.setattr("wiseman_hub.utils.os_open.subprocess.run", spy)

    open_with_default_app(target)

    assert len(spy.calls) == 1
    args = spy.calls[0]
    assert args[0] == ["open", str(target)]
    # セキュリティ: shell=False が明示的にセットされている（暗黙の True 化禁止）
    assert spy.kwargs[0].get("shell") is False
    assert spy.kwargs[0].get("check") is True


def test_windows_uses_startfile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows では os.startfile(str(path)) が呼ばれる。"""
    target = tmp_path / "dummy.pdf"
    target.write_bytes(b"%PDF-1.4\n")

    spy = _SpyStartfile()
    monkeypatch.setattr("wiseman_hub.utils.os_open.sys.platform", "win32")
    # os.startfile は Windows 以外では存在しないため raising=False で挿入
    monkeypatch.setattr(
        "wiseman_hub.utils.os_open._startfile", spy, raising=True
    )

    open_with_default_app(target)

    assert spy.calls == [str(target)]


def test_linux_uses_xdg_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Linux では `xdg-open <path>` が subprocess.run で呼ばれる。"""
    target = tmp_path / "dummy.pdf"
    target.write_bytes(b"%PDF-1.4\n")

    spy = _SpyRun()
    monkeypatch.setattr("wiseman_hub.utils.os_open.sys.platform", "linux")
    monkeypatch.setattr("wiseman_hub.utils.os_open.subprocess.run", spy)

    open_with_default_app(target)

    assert spy.calls[0][0] == ["xdg-open", str(target)]
    assert spy.kwargs[0].get("shell") is False


def test_directory_can_be_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ファイルだけでなくディレクトリも引数として受け付ける（事業所フォルダを開く用途）。"""
    spy = _SpyRun()
    monkeypatch.setattr("wiseman_hub.utils.os_open.sys.platform", "darwin")
    monkeypatch.setattr("wiseman_hub.utils.os_open.subprocess.run", spy)

    open_with_default_app(tmp_path)

    assert spy.calls[0][0] == ["open", str(tmp_path)]


def test_missing_path_raises_file_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """存在しないパス → FileNotFoundError（subprocess を呼ばない）。"""
    spy = _SpyRun()
    monkeypatch.setattr("wiseman_hub.utils.os_open.sys.platform", "darwin")
    monkeypatch.setattr("wiseman_hub.utils.os_open.subprocess.run", spy)

    missing = tmp_path / "does_not_exist.pdf"
    with pytest.raises(FileNotFoundError):
        open_with_default_app(missing)

    # 不在検出は subprocess に委ねず関数側で行う（OS 依存エラーメッセージを避ける）
    assert spy.calls == []


def test_unsupported_platform_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """未知プラットフォーム（aix, freebsd 等）→ NotImplementedError で明示。"""
    target = tmp_path / "dummy.pdf"
    target.write_bytes(b"%PDF-1.4\n")

    monkeypatch.setattr("wiseman_hub.utils.os_open.sys.platform", "aix")

    with pytest.raises(NotImplementedError, match="aix"):
        open_with_default_app(target)


def test_japanese_path_supported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """日本語パス（事業所名に日本語含む）でも例外なく実行される。

    AC-11: 日本語パスで scan/open が失敗しない の一部。
    """
    facility = tmp_path / "きなり(メール)※持参"
    facility.mkdir()

    spy = _SpyRun()
    monkeypatch.setattr("wiseman_hub.utils.os_open.sys.platform", "darwin")
    monkeypatch.setattr("wiseman_hub.utils.os_open.subprocess.run", spy)

    open_with_default_app(facility)

    assert spy.calls[0][0] == ["open", str(facility)]


def test_subprocess_failure_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """subprocess.run が例外を上げた場合、呼び出し元へそのまま伝播する。

    例: open コマンドが見つからない・xdg-open が未インストール等
    """
    target = tmp_path / "dummy.pdf"
    target.write_bytes(b"%PDF-1.4\n")

    def _raise(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError("simulated open failure")

    monkeypatch.setattr("wiseman_hub.utils.os_open.sys.platform", "darwin")
    monkeypatch.setattr("wiseman_hub.utils.os_open.subprocess.run", _raise)

    with pytest.raises(OSError, match="simulated open failure"):
        open_with_default_app(target)
