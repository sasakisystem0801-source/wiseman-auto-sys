"""btnPrintクリック後のウィンドウ一覧を診断するスクリプト"""
import sys
import time

if sys.platform != "win32":
    print("Windows専用スクリプト")
    sys.exit(1)

from pywinauto import Application, Desktop  # noqa: E402

print("1. アプリに接続...")
app = Application(backend="uia").connect(title_re=".*管理システム SP.*")
main = app.window(title_re=".*管理システム SP.*")

print("2. MDI子ウィンドウ検索...")
child = main.child_window(control_type="Window")
print(f"   MDI child: {child.window_text()}")

print("3. btnPrintクリック...")
btn = child.child_window(auto_id="btnPrint")
print(f"   ボタン: name={btn.window_text()}, rect={btn.rectangle()}")
btn.click_input()

print("4. 2秒待機...")
time.sleep(2)

print("5. 全ウィンドウ一覧:")
for w in app.windows():
    try:
        print(f"   title={w.window_text()!r}  class={w.class_name()}")
    except Exception as e:
        print(f"   (error: {e})")

print("6. top_windows():")
desktop = Desktop(backend="uia")
for w in desktop.windows():
    try:
        t = w.window_text()
        if t and ("保存" in t or "名前" in t or "Save" in t or "ケア" in t or "管理" in t):
            print(f"   title={t!r}  class={w.class_name()}")
    except Exception:
        pass

print("完了")
