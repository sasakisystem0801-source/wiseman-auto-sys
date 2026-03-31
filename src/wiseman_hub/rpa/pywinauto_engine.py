"""pywinautoベースのRPAエンジン実装（Windows専用）"""

from __future__ import annotations

import contextlib
import logging
import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from wiseman_hub.rpa.base import RPAEngine

if TYPE_CHECKING:
    from pywinauto.application import WindowSpecification

if sys.platform != "win32":
    raise ImportError("pywinauto_engine はWindows環境でのみ使用できます")

from pywinauto import Application
from pywinauto.findwindows import ElementNotFoundError
from pywinauto.timings import TimeoutError as PywinautoTimeoutError

logger = logging.getLogger(__name__)


class PywinautoEngine(RPAEngine):
    """pywinauto (UIA backend) によるワイズマンGUI操作の実装。

    ワイズマンは .NET Framework 3.5 / WinForms / MDI 構成。
    UIA backendを使用し、アクセシビリティセレクタでコントロールを特定する。
    """

    def __init__(self, startup_wait_sec: int = 15, window_title_pattern: str = ".*管理システム SP.*") -> None:
        self._app: Application | None = None
        self._main_window: WindowSpecification | None = None
        self._startup_wait_sec = startup_wait_sec
        self._window_title_pattern = window_title_pattern

    def _get_active_mdi_child(self) -> WindowSpecification | None:
        """アクティブなMDI子ウィンドウを取得する。

        WinForms MDI構造ではMDI子フォームはメインウィンドウ直下ではなく、
        MDIクライアント領域（Pane）の下にWindow として配置される:
            MainWindow > Pane (MDI Client) > Window (MDI Child)

        WindowSpecification を返すため、戻り値に対して child_window() 等が使用可能。
        """
        if self._main_window is None:
            return None

        # MDI子フォームは Pane (MDI Client) > Window の階層にある
        # child_window() は子孫を再帰検索するため、直接 Window を指定すれば
        # Pane を飛び越えて MDI 子フォームを見つけられる
        try:
            mdi_child = self._main_window.child_window(control_type="Window")
            if mdi_child.exists(timeout=2):
                return mdi_child
        except ElementNotFoundError:
            pass

        return None

    def launch_and_login(self, exe_path: str, username: str, password: str) -> None:
        """ワイズマンを起動してログインする。

        1. exe起動
        2. USBドングル認証待機（startup_wait_sec）
        3. ログイン画面でユーザー名/パスワード入力
        4. メインウィンドウ表示を確認
        """
        logger.info("ワイズマン起動: %s", exe_path)
        self._app = Application(backend="uia").start(exe_path)
        try:
            # ドングル認証通過を待機
            logger.info("ドングル認証待機中 (%d秒)...", self._startup_wait_sec)
            time.sleep(self._startup_wait_sec)

            # ログインウィンドウを検索
            # モックアプリのセレクタで動作確認済み。
            # 実機では Inspect.exe / dump_ui.py で正確なセレクタを特定し更新すること。
            logger.info("ログインウィンドウを検索中...")
            try:
                login_window = self._app.window(title_re=".*ログイン.*")
                login_window.wait("visible", timeout=30)

                # ユーザー名入力
                login_window.child_window(auto_id="txtUserId").set_edit_text(username)
                login_window.child_window(auto_id="txtPassword").set_edit_text(password)
                login_window.child_window(auto_id="btnLogin").click()
                logger.info("ログイン実行")
            except ElementNotFoundError:
                logger.error("ログインウィンドウが見つかりません")
                raise

            # メインウィンドウ表示を待機
            logger.info("メインウィンドウ待機中...")
            self._main_window = self._app.window(title_re=self._window_title_pattern)
            self._main_window.wait("visible", timeout=30)
            logger.info("ログイン成功: %s", self._main_window.window_text())
        except Exception:
            if self._app is not None:
                with contextlib.suppress(Exception):
                    self._app.kill()
                self._app = None
            raise

    def navigate_menu(self, menu_path: list[str]) -> None:
        """MDIメニューを階層的に辿って指定画面に遷移する。"""
        if self._main_window is None:
            raise RuntimeError("メインウィンドウが未接続です。先にlaunch_and_loginを実行してください")

        logger.info("メニュー遷移: %s", " → ".join(menu_path))

        # WinForms MenuStrip: menu_select("親メニュー->子メニュー") 形式
        menu_string = "->".join(menu_path)
        menu_success = False

        try:
            self._main_window.menu_select(menu_string)
            menu_success = True
            logger.debug("menu_select成功")
        except (ElementNotFoundError, AttributeError, PywinautoTimeoutError) as exc:
            # menu_selectがUIA backendで動作しない場合のフォールバック:
            # MenuItem を個別にクリック
            logger.warning("menu_select失敗 (%s): %s。個別クリックにフォールバック", type(exc).__name__, exc)
            try:
                for i, item in enumerate(menu_path):
                    self._main_window.child_window(
                        title=item, control_type="MenuItem",
                    ).click_input()
                    logger.debug("MenuItem clicked: %s (%d/%d)", item, i + 1, len(menu_path))
                    time.sleep(0.5)
                menu_success = True
            except (ElementNotFoundError, AttributeError, PywinautoTimeoutError) as e:
                logger.error("個別クリックフォールバック失敗: %s", e)

        # MDI子ウィンドウが開くのを待機
        if menu_success:
            time.sleep(1)
            logger.info("メニュー遷移完了: %s", menu_string)
        else:
            logger.warning("メニュー遷移失敗の可能性があります: %s", menu_string)

    def export_csv(self, output_dir: Path) -> Path | None:
        """現在の画面からCSVエクスポートを実行する。"""
        if self._main_window is None:
            raise RuntimeError("メインウィンドウが未接続です")

        logger.info("CSVエクスポート開始")
        output_dir.mkdir(parents=True, exist_ok=True)

        # アクティブなMDI子ウィンドウの[印刷]ボタンをクリック
        active_child = self._get_active_mdi_child()
        if active_child is None:
            logger.error("MDI子ウィンドウが見つかりません")
            return None

        # UIA Invokeパターンでボタンを直接呼び出し（click_inputより確実）
        try:
            btn_print = active_child.child_window(auto_id="btnPrint")
            btn_print.invoke()
        except (ElementNotFoundError, AttributeError):
            # invoke未対応の場合はclick_inputにフォールバック
            active_child.child_window(auto_id="btnPrint").click_input()
        time.sleep(1)

        # SaveFileDialog を処理
        try:
            save_dlg = self._app.window(title_re=".*保存.*|.*名前.*|.*Save.*")
            save_dlg.wait("visible", timeout=10)
        except (ElementNotFoundError, PywinautoTimeoutError):
            logger.error("保存ダイアログが表示されません")
            return None

        csv_filename = f"care_record_{int(time.time())}.csv"
        csv_path = output_dir / csv_filename

        # ファイル名入力欄にパスを設定
        filename_set = False
        for selector in [
            lambda d: d.child_window(auto_id="FileNameControlHost"),
            lambda d: d.child_window(control_type="Edit"),
        ]:
            try:
                selector(save_dlg).set_edit_text(str(csv_path))
                filename_set = True
                break
            except (ElementNotFoundError, PywinautoTimeoutError, AttributeError):
                continue

        if not filename_set:
            logger.warning("ファイル名入力欄が見つかりません")
            return None

        time.sleep(0.5)

        # [保存] ボタンをクリック
        save_clicked = False
        for selector in [
            lambda d: d.child_window(title_re=".*保存.*", control_type="Button"),
            lambda d: d.child_window(title="Save", control_type="Button"),
            lambda d: d.child_window(title="OK", control_type="Button"),
        ]:
            try:
                selector(save_dlg).click_input()
                save_clicked = True
                break
            except (ElementNotFoundError, PywinautoTimeoutError):
                continue

        if not save_clicked:
            logger.warning("保存ボタンが見つかりません")
            return None

        time.sleep(1)

        # 保存完了メッセージボックスを検出してOKをクリック
        try:
            msg_box = self._app.window(title_re=".*完了.*")
            msg_box.wait("visible", timeout=5)
            msg_box.child_window(title="OK", control_type="Button").click_input()
            logger.info("保存完了ダイアログを閉じました")
        except (ElementNotFoundError, PywinautoTimeoutError):
            logger.debug("保存完了ダイアログは表示されませんでした")

        if csv_path.exists():
            logger.info("CSVエクスポート成功: %s", csv_path)
            return csv_path

        logger.warning("CSVファイルが見つかりません: %s", csv_path)
        return None

    def read_grid_data(self) -> list[list[str]]:
        """現在の画面のデータグリッドからデータを直接読み取る。"""
        if self._main_window is None:
            raise RuntimeError("メインウィンドウが未接続です")

        # アクティブなMDI子ウィンドウのDataGridViewを検索
        active_child = self._get_active_mdi_child()
        if active_child is None:
            logger.warning("MDI子ウィンドウが見つかりません")
            return []

        # WinForms DataGridView は UIA では "Table" として公開される
        # wrapper() で実体化を試み、成功した候補を使う（TOCTOU回避）
        grid = None
        for selector in [
            lambda c: c.child_window(auto_id="dgvCareRecord", control_type="Table"),
            lambda c: c.child_window(control_type="Table"),
            lambda c: c.child_window(control_type="DataGrid"),
        ]:
            try:
                candidate = selector(active_child)
                candidate.wrapper_object()  # 実体化して存在を確認
                grid = candidate
                break
            except (ElementNotFoundError, PywinautoTimeoutError):
                continue

        if grid is None:
            logger.warning("DataGridViewが見つかりません")
            return []

        rows: list[list[str]] = []
        col_count = 0

        # ヘッダー行の取得
        # WinForms DataGridView: Table > Custom("トップの行") > Header の階層
        try:
            custom_rows = grid.children(control_type="Custom")
            if custom_rows:
                header_items = custom_rows[0].children(control_type="Header")
                header_texts = [h.window_text() for h in header_items]
                rows.append(header_texts)
                col_count = len(header_texts)
                logger.debug("ヘッダー行取得: %d列", col_count)
            else:
                # フォールバック: Header直下検索
                headers = grid.children(control_type="Header")
                if headers:
                    header_items = headers[0].children(control_type="HeaderItem")
                    header_texts = [h.window_text() for h in header_items]
                    rows.append(header_texts)
                    col_count = len(header_texts)
        except (ElementNotFoundError, IndexError) as e:
            logger.warning("ヘッダー行の読み取り失敗: %s", e)

        # データ行の取得
        # WinForms DataGridView: 各セルがEditとしてフラットに展開される
        try:
            # まずDataItem（標準的なUIA構造）を試行
            data_items = grid.children(control_type="DataItem")
            if data_items:
                for item in data_items:
                    cells = item.children()
                    row_data = [c.window_text() for c in cells]
                    rows.append(row_data)
                logger.debug("DataItem経由: %d行", len(data_items))
            elif col_count > 0:
                # フォールバック: Edit要素をフラットに取得し列数で分割
                edits = grid.children(control_type="Edit")
                if edits:
                    for i in range(0, len(edits), col_count):
                        row_data = [e.window_text() for e in edits[i:i + col_count]]
                        if len(row_data) == col_count:
                            rows.append(row_data)
                    logger.debug("Edit経由: %d行 (%dセル / %d列)",
                                 len(rows) - 1, len(edits), col_count)
        except ElementNotFoundError as e:
            logger.warning("データ行の読み取り失敗: %s", e)

        logger.info("グリッドデータ読み取り: %d行", len(rows))
        return rows

    def close_current_window(self) -> None:
        """現在のMDI子ウィンドウを閉じる。"""
        if self._main_window is None:
            raise RuntimeError("メインウィンドウが未接続です")

        active_child = self._get_active_mdi_child()
        if active_child is None:
            logger.warning("閉じるべきMDI子ウィンドウが見つかりません")
            return
        close_btn = active_child.child_window(auto_id="btnClose")
        if close_btn.exists(timeout=2):
            close_btn.click_input()
        else:
            # フォールバック: タイトルバーの閉じるボタン
            active_child.close()

        time.sleep(0.5)
        logger.info("MDI子ウィンドウを閉じました")

    def close_wiseman(self) -> None:
        """ワイズマンを安全に終了する。"""
        if self._main_window is None:
            logger.warning("メインウィンドウが未接続のため終了操作をスキップ")
            return

        logger.info("ワイズマン終了中...")

        # [終了] ボタンをクリック（UIA Invokeパターン優先）
        try:
            self._main_window.child_window(auto_id="btnExit").invoke()
        except (ElementNotFoundError, AttributeError):
            self._main_window.child_window(auto_id="btnExit").click_input()
        time.sleep(0.5)

        # 確認ダイアログで [はい] をクリック
        try:
            confirm = self._app.window(title_re=".*確認.*")
            confirm.wait("visible", timeout=5)
            try:
                confirm.child_window(title="はい").invoke()
            except AttributeError:
                confirm.child_window(title="はい").click_input()
        except (ElementNotFoundError, PywinautoTimeoutError):
            logger.warning("確認ダイアログが見つかりません。直接終了を試みます")
            self._main_window.close()

        # プロセス終了を待機（タイムアウト10秒）
        pid = self._app.process
        timeout_sec = 10
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break  # プロセス終了済み
            except PermissionError:
                pass  # プロセスは存在するがアクセス権なし → 存在として扱う
            time.sleep(0.5)
        else:
            logger.warning("ワイズマンプロセス(PID=%d)が%d秒以内に終了しませんでした", pid, timeout_sec)
            self._main_window = None
            self._app = None
            return

        self._main_window = None
        self._app = None
        logger.info("ワイズマン終了完了")

    def is_dongle_present(self) -> bool:
        """USBドングルが認識されているか確認する。"""
        # TODO: ドングル未検出時のエラーダイアログ検出
        # エラーウィンドウが存在しなければドングルは接続済みと判断
        try:
            Application(backend="uia").connect(title_re=".*エラー.*|.*ドングル.*")
            return False
        except ElementNotFoundError:
            return True

    def take_screenshot(self, name: str) -> Path:
        """現在の画面のスクリーンショットを保存する。"""
        output_dir = Path("data/screenshots")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{name}.png"

        if self._main_window is not None:
            self._main_window.capture_as_image().save(str(output_path))
            logger.info("スクリーンショット保存: %s", output_path)
        else:
            import pyautogui
            pyautogui.screenshot(str(output_path))
            logger.info("全画面スクリーンショット保存: %s", output_path)

        return output_path
