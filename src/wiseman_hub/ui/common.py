"""UI モジュール共通ヘルパ。"""

from __future__ import annotations

import threading


def assert_main_thread(component_name: str) -> None:
    """Tk は main thread でしか安全に使えないため、worker thread からの生成を fail-fast で拒否する。

    Tkinter（filedialog / messagebox / mainloop）は非 main thread から呼び出すと
    Windows 本番でハング / TclError を起こしうる。
    """
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError(
            f"{component_name} must be instantiated on the main thread "
            "(tkinter is not thread-safe)"
        )
