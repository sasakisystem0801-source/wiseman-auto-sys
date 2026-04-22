"""atomic_io ユーティリティの単体テスト。

Issue #38: merger / session / config の tempfile+os.replace 重複を共通化。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import pytest


def test_write_bytes_atomically_creates_file(tmp_path: Path) -> None:
    """payload が target に正確に書き込まれる。"""
    from wiseman_hub.utils.atomic_io import write_bytes_atomically

    target = tmp_path / "out.bin"
    payload = b"hello atomic"

    write_bytes_atomically(target, payload)

    assert target.read_bytes() == payload


def test_write_bytes_atomically_overwrites_existing(tmp_path: Path) -> None:
    """既存 target が置換される。"""
    from wiseman_hub.utils.atomic_io import write_bytes_atomically

    target = tmp_path / "out.bin"
    target.write_bytes(b"old")

    write_bytes_atomically(target, b"new")

    assert target.read_bytes() == b"new"


def test_write_bytes_atomically_no_tmp_leftover_on_success(tmp_path: Path) -> None:
    """成功時に tmp ファイルが残らない。"""
    from wiseman_hub.utils.atomic_io import write_bytes_atomically

    target = tmp_path / "out.bin"
    write_bytes_atomically(target, b"payload")

    leftovers = [p for p in tmp_path.iterdir() if p.name != target.name]
    assert leftovers == []


def test_write_bytes_atomically_calls_fsync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """flush/fsync が呼ばれる（クラッシュ耐性）。"""
    from wiseman_hub.utils import atomic_io

    called: list[int] = []
    real_fsync = os.fsync

    def spy_fsync(fd: int) -> None:
        called.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(atomic_io.os, "fsync", spy_fsync)

    target = tmp_path / "out.bin"
    atomic_io.write_bytes_atomically(target, b"x")

    assert len(called) >= 1


def test_write_bytes_atomically_cleans_tmp_on_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """os.replace 失敗時に tmp が消え、既存 target が保たれる。"""
    from wiseman_hub.utils import atomic_io

    target = tmp_path / "out.bin"
    target.write_bytes(b"existing")

    def failing_replace(src: str, dst: str) -> None:
        raise OSError("simulated disk full")

    monkeypatch.setattr(atomic_io.os, "replace", failing_replace)

    with pytest.raises(OSError, match="disk full"):
        atomic_io.write_bytes_atomically(target, b"new")

    # 既存ファイル保護
    assert target.read_bytes() == b"existing"
    # tmp ファイル削除
    leftovers = [p for p in tmp_path.iterdir() if p.name != target.name]
    assert leftovers == []


def test_write_bytes_atomically_cleans_tmp_on_base_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """KeyboardInterrupt 注入時に tmp が消え、BaseException は伝播する。"""
    from wiseman_hub.utils import atomic_io

    target = tmp_path / "out.bin"

    def interrupting_replace(src: str, dst: str) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(atomic_io.os, "replace", interrupting_replace)

    with pytest.raises(KeyboardInterrupt):
        atomic_io.write_bytes_atomically(target, b"payload")

    leftovers = list(tmp_path.iterdir())
    assert leftovers == []


def test_write_bytes_atomically_sanitized_logs_on_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """cleanup 失敗時のログに path / 例外 message が出ない（PII 防御）。"""
    from wiseman_hub.utils import atomic_io

    # ユニークな PII 相当文字列
    pii_name = "user-taro-tanaka-secret"
    target = tmp_path / f"{pii_name}.bin"

    def failing_replace(src: str, dst: str) -> None:
        raise OSError("simulated-error-message-XYZ")

    def failing_unlink(self: Path, missing_ok: bool = False) -> None:
        raise OSError("cleanup-internal-XYZ")

    monkeypatch.setattr(atomic_io.os, "replace", failing_replace)
    monkeypatch.setattr(Path, "unlink", failing_unlink)

    with (
        caplog.at_level(logging.WARNING, logger="wiseman_hub.utils.atomic_io"),
        pytest.raises(OSError),
    ):
        atomic_io.write_bytes_atomically(target, b"x")

    log_text = caplog.text
    assert pii_name not in log_text
    assert "simulated-error-message-XYZ" not in log_text
    assert "cleanup-internal-XYZ" not in log_text


def test_save_atomically_invokes_writer_with_tmp_path(tmp_path: Path) -> None:
    """writer に tmp path（target とは別のファイル）が渡る。"""
    from wiseman_hub.utils.atomic_io import save_atomically

    target = tmp_path / "out.dat"
    captured: dict[str, Any] = {}

    def writer(tmp: Path) -> None:
        captured["path"] = tmp
        tmp.write_bytes(b"payload")

    save_atomically(target, writer)

    assert "path" in captured
    assert captured["path"] != target
    assert captured["path"].parent == target.parent
    assert target.read_bytes() == b"payload"


def test_save_atomically_no_tmp_leftover_on_success(tmp_path: Path) -> None:
    """成功時 tmp が残らない。"""
    from wiseman_hub.utils.atomic_io import save_atomically

    target = tmp_path / "out.dat"

    def writer(tmp: Path) -> None:
        tmp.write_bytes(b"x")

    save_atomically(target, writer)

    leftovers = [p for p in tmp_path.iterdir() if p.name != target.name]
    assert leftovers == []


def test_save_atomically_writer_failure_preserves_target(tmp_path: Path) -> None:
    """writer 例外時に既存 target が保たれ、tmp が消え、元例外が伝播する。"""
    from wiseman_hub.utils.atomic_io import save_atomically

    target = tmp_path / "out.dat"
    target.write_bytes(b"existing")

    def failing_writer(tmp: Path) -> None:
        tmp.write_bytes(b"partial")
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        save_atomically(target, failing_writer)

    assert target.read_bytes() == b"existing"
    leftovers = [p for p in tmp_path.iterdir() if p.name != target.name]
    assert leftovers == []


def test_save_atomically_replace_failure_cleans_tmp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """os.replace 失敗時に tmp が消える（merger の既存バグ修正）。"""
    from wiseman_hub.utils import atomic_io

    target = tmp_path / "out.dat"
    target.write_bytes(b"existing")

    def failing_replace(src: str, dst: str) -> None:
        raise OSError("simulated")

    monkeypatch.setattr(atomic_io.os, "replace", failing_replace)

    def writer(tmp: Path) -> None:
        tmp.write_bytes(b"new")

    with pytest.raises(OSError, match="simulated"):
        atomic_io.save_atomically(target, writer)

    assert target.read_bytes() == b"existing"
    leftovers = [p for p in tmp_path.iterdir() if p.name != target.name]
    assert leftovers == []


def test_save_atomically_calls_fsync_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """デフォルトで writer 後に fsync が呼ばれる。"""
    from wiseman_hub.utils import atomic_io

    called: list[int] = []
    real_fsync = os.fsync

    def spy_fsync(fd: int) -> None:
        called.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(atomic_io.os, "fsync", spy_fsync)

    target = tmp_path / "out.dat"

    def writer(tmp: Path) -> None:
        tmp.write_bytes(b"x")

    atomic_io.save_atomically(target, writer)

    assert len(called) >= 1


def test_save_atomically_skips_fsync_when_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """fsync=False で fsync がスキップされる。"""
    from wiseman_hub.utils import atomic_io

    called: list[int] = []

    def spy_fsync(fd: int) -> None:
        called.append(fd)

    monkeypatch.setattr(atomic_io.os, "fsync", spy_fsync)

    target = tmp_path / "out.dat"

    def writer(tmp: Path) -> None:
        tmp.write_bytes(b"x")

    atomic_io.save_atomically(target, writer, fsync=False)

    assert called == []


def test_save_atomically_base_exception_propagates_and_cleans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """KeyboardInterrupt 注入時に tmp が消え、BaseException は伝播する。"""
    from wiseman_hub.utils import atomic_io

    target = tmp_path / "out.dat"

    def interrupting_writer(tmp: Path) -> None:
        tmp.write_bytes(b"x")
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        atomic_io.save_atomically(target, interrupting_writer)

    leftovers = list(tmp_path.iterdir())
    assert leftovers == []


def test_write_bytes_atomically_honors_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """prefix 指定で tempfile 命名が変わる（呼び出し元 sweep 連携用）。

    意図的に ``os.replace`` を失敗させて tmp を残し、ファイル名 prefix を観測する。
    ``monkeypatch.setattr`` で module 属性（``atomic_io.tempfile`` /
    ``atomic_io.os``）を spy に差し替える。
    """
    from wiseman_hub.utils import atomic_io

    target = tmp_path / "config.toml"
    custom_prefix = "config.toml."

    captured: list[str] = []
    real_mkstemp = atomic_io.tempfile.mkstemp

    def spy_mkstemp(**kwargs: object) -> tuple[int, str]:
        fd, name = real_mkstemp(**kwargs)  # type: ignore[arg-type]
        captured.append(name)
        return fd, name

    def failing_replace(src: str, dst: str) -> None:
        raise OSError("simulated")

    # cleanup を抑制し、tmp 名を観測できるよう unlink を no-op 化する
    def noop_unlink(self: Path, missing_ok: bool = False) -> None:
        return None

    monkeypatch.setattr(atomic_io.tempfile, "mkstemp", spy_mkstemp)
    monkeypatch.setattr(atomic_io.os, "replace", failing_replace)
    monkeypatch.setattr(Path, "unlink", noop_unlink)

    with pytest.raises(OSError, match="simulated"):
        atomic_io.write_bytes_atomically(target, b"x", prefix=custom_prefix)

    assert len(captured) == 1
    assert Path(captured[0]).name.startswith(custom_prefix)


def test_save_atomically_honors_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """save_atomically も prefix 指定を反映する。"""
    from wiseman_hub.utils import atomic_io

    target = tmp_path / "out.pdf"
    custom_prefix = ".merge-"

    captured: list[str] = []
    real_mkstemp = atomic_io.tempfile.mkstemp

    def spy_mkstemp(**kwargs: object) -> tuple[int, str]:
        fd, name = real_mkstemp(**kwargs)  # type: ignore[arg-type]
        captured.append(name)
        return fd, name

    monkeypatch.setattr(atomic_io.tempfile, "mkstemp", spy_mkstemp)

    atomic_io.save_atomically(
        target, lambda p: p.write_bytes(b"ok"), prefix=custom_prefix
    )

    assert len(captured) == 1
    assert Path(captured[0]).name.startswith(custom_prefix)
