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

import ctypes

from pywinauto import Application
from pywinauto.findwindows import ElementNotFoundError
from pywinauto.timings import TimeoutError as PywinautoTimeoutError

logger = logging.getLogger(__name__)

# use_last_error=True を付けて user32 をロードしないと ctypes.get_last_error()
# は他の ctypes 呼び出しの残骸を返すため、失敗時のエラー情報が嘘になる。
_USER32 = ctypes.WinDLL("user32", use_last_error=True)


class PywinautoEngine(RPAEngine):
    """pywinauto (UIA backend) によるワイズマンGUI操作の実装。

    ワイズマンは .NET Framework 3.5 / WinForms / MDI 構成。
    UIA backendを使用し、アクセシビリティセレクタでコントロールを特定する。
    """

    def __init__(self, startup_wait_sec: int = 15, window_title_pattern: str = ".*管理システム SP.*") -> None:
        self._app: Application | None = None
        self._launcher_window: WindowSpecification | None = None
        self._main_window: WindowSpecification | None = None
        self._startup_wait_sec = startup_wait_sec
        self._window_title_pattern = window_title_pattern

    @staticmethod
    def _post_message(hwnd: int, msg: int, wparam: int, lparam: int) -> None:
        """PostMessageW を呼び、戻り値 0 (失敗) を RuntimeError に昇格させる。

        PostMessage は非同期キュー投入で、失敗時は 0 を返し GetLastError() を
        セットする (無効 HWND / 対象スレッド終了 / キュー満杯等)。戻り値を無視
        すると、後段の wait("visible") が "ウィンドウが見つからない" という
        誤ったエラーになり調査を誤誘導するため、ここで明示的に検出する。
        """
        ok = _USER32.PostMessageW(hwnd, msg, wparam, lparam)
        if not ok:
            err = ctypes.get_last_error()
            raise RuntimeError(
                f"PostMessageW failed: hwnd=0x{hwnd:x} msg=0x{msg:x} "
                f"GetLastError={err}"
            )

    @staticmethod
    def _send_message(hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        """SendMessageW を呼ぶ。SendMessage は同期のため戻り値はメッセージ依存。

        失敗時の 0 は他メッセージの正常値と衝突するため GetLastError() を参照
        しても確実ではない。HWND の生存確認のみ事前に行い、以降は呼び出し元が
        後段の状態遷移で検知する責務を持つ。
        """
        if not _USER32.IsWindow(hwnd):
            raise RuntimeError(f"SendMessageW: invalid hwnd=0x{hwnd:x}")
        return _USER32.SendMessageW(hwnd, msg, wparam, lparam)

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
        except Exception as exc:
            # comtypes.COMError / RuntimeError 等 pywinauto の UIA 呼び出しは
            # 環境によって様々な型を投げる。ここで黙殺はせず debug ログに残し、
            # 呼び出し元には "見つからなかった" と同等の None を返す（上位で
            # 明示的に欠落判定するため）。
            logger.debug(
                "_get_active_mdi_child: UIA 呼び出しで例外 (%s): %s",
                type(exc).__name__, exc,
            )

        return None

    def launch(self, exe_path: str) -> None:
        """ワイズマンを起動する（システム選択ランチャー frmStartUp まで）。

        ワイズマンはUSBドングル認証のみで動作し、アプリ内ログイン画面は存在しない（ADR-007）。
        起動直後に表示されるのはシステム選択ランチャー(frmStartUp)であり、
        目的のケア記録システムには続けて select_care_system() を呼ぶ必要がある。

        exe_path が .lnk ショートカットの場合、pywinauto の Application.start() は
        Windows Shell を介してショートカットを解決する。
        """
        logger.info("ワイズマン起動: %s", exe_path)
        is_shortcut = exe_path.lower().endswith(".lnk")
        if is_shortcut:
            # Application.start は .exe 前提で .lnk を扱えないため、Shell 経由で解決する。
            # 起動後、frmStartUp ウィンドウが見えたタイミングで connect() でアタッチする。
            import subprocess
            subprocess.Popen(["cmd", "/c", "start", "", exe_path], shell=False)
            self._app = Application(backend="uia")
        else:
            self._app = Application(backend="uia").start(exe_path)
        try:
            # ドングル認証とランチャー表示を待機
            logger.info("ドングル認証・ランチャー表示待機中 (%d秒)...", self._startup_wait_sec)
            time.sleep(self._startup_wait_sec)

            if is_shortcut:
                # ランチャーウィンドウ(frmStartUp)に直接アタッチする
                # class_name_re は .NET WinForms のバージョン差で揺れるため使わない
                logger.info("ランチャープロセスに接続中...")
                self._app.connect(title_re=r".*ワイズマンシステム.*", timeout=30)

            # システム選択ランチャー frmStartUp を待機
            logger.info("システム選択ランチャー待機中...")
            self._launcher_window = self._app.window(auto_id="frmStartUp")
            self._launcher_window.wait("visible", timeout=30)
            logger.info("起動成功: %s", self._launcher_window.window_text())
        except Exception:
            if self._app is not None:
                with contextlib.suppress(Exception):
                    self._app.kill()
                self._app = None
            raise

    def select_care_system(self) -> None:
        """システム選択ランチャーから「通所・訪問リハビリ管理システム SP(ケア記録)」を選択する。

        実機ではケア記録の選択項目は Button ではなく Pane（WinForms Panel）として
        実装されており、auto_id が動的なため title_re で検索する。
        Pane は UIA の InvokePattern を持たないことが多いため、座標クリックで対応する。
        """
        if self._launcher_window is None:
            raise RuntimeError("ランチャーが未接続です。先に launch() を実行してください")

        logger.info("ケア記録システムを選択中...")
        # 実機はPane(auto_id動的)、モックはPanel+Labelの構造で、UIA の Name プロパティを
        # 持つのが Pane なのか Text(Label) なのか Button なのかは環境により異なる。
        # 複数の control_type を順に試して最初にマッチしたもの（の HWND）にクリック
        # メッセージを直接 PostMessage する。PostMessage は画面座標やフォーカスに依存せず、
        # COM クロススレッド競合も起きない。
        title_pattern = r".*通所.*[ｹケ][ｱア]記録.*"
        target_hwnd: int | None = None
        found_ct: str | None = None
        last_err: Exception | None = None
        for ct in ("Button", "Pane", "Text", "Hyperlink"):
            try:
                candidate = self._launcher_window.child_window(
                    title_re=title_pattern,
                    control_type=ct,
                )
                wrapper = candidate.wait("visible", timeout=5)
                target_hwnd = wrapper.handle
                found_ct = ct
                logger.info(
                    "ケア記録要素発見: control_type=%s hwnd=0x%x", ct, target_hwnd or 0,
                )
                # UIA ラッパーと探索オブジェクトを即座に破棄する。
                # これらを抱えたまま後段の Win32 クリック送信に入ると、comtypes が
                # 管理する COM プロキシが別スレッドで解放されて再入/スレッド制約の
                # 違反を引き起こす場合があった。HWND だけを保持して参照を切るのが
                # 最も確実な回避策。
                del wrapper
                del candidate
                break
            except (ElementNotFoundError, PywinautoTimeoutError) as exc:
                last_err = exc
                continue
        if target_hwnd is None or target_hwnd == 0:
            # デバッグ用: launcher の descendants を列挙してログ出力
            try:
                descendants = self._launcher_window.descendants()
                logger.error("ケア記録要素が見つかりません。launcher の descendants (先頭50件):")
                for i, d in enumerate(descendants[:50]):
                    try:
                        ct_name = d.element_info.control_type
                        name = d.element_info.name or ''
                        aid = d.element_info.automation_id or ''
                        logger.error("  [%d] %s name=%r aid=%r", i, ct_name, name, aid)
                    except Exception:
                        continue
            except Exception as dump_err:
                logger.error("descendants 列挙も失敗: %s", dump_err)
            raise RuntimeError(
                f"ケア記録選択要素が見つかりません (pattern={title_pattern!r})"
            ) from last_err

        # HWND に直接クリックイベントを送る
        # （座標/フォーカス/DPI 非依存、COM も介さないため安全）
        import gc
        gc.collect()
        time.sleep(0.1)
        WM_LBUTTONDOWN = 0x0201
        WM_LBUTTONUP = 0x0202
        BM_CLICK = 0x00F5
        MK_LBUTTON = 0x0001

        if found_ct == "Button":
            # Button は BM_CLICK に確実に反応する（最も信頼できる）。
            # care system 選択はクリック後モーダルを開かないため Send で OK。
            logger.info("ケア記録 BM_CLICK: hwnd=0x%x", target_hwnd)
            self._send_message(target_hwnd, BM_CLICK, 0, 0)
        else:
            # Pane/Text: WM_LBUTTONDOWN/UP を Post
            logger.info("ケア記録 WM_LBUTTON: hwnd=0x%x", target_hwnd)
            self._post_message(target_hwnd, WM_LBUTTONDOWN, MK_LBUTTON, 0)
            time.sleep(0.05)
            self._post_message(target_hwnd, WM_LBUTTONUP, 0, 0)
        time.sleep(0.5)

        # ケア記録メインウィンドウ frmMenu200 を待機
        logger.info("ケア記録メインウィンドウ待機中...")
        self._main_window = self._app.window(auto_id="frmMenu200")
        self._main_window.wait("visible", timeout=30)
        # MDI 子ウィンドウ等の初期化が完了するまで少し待つ
        time.sleep(1)
        logger.info("ケア記録システム起動完了: %s", self._main_window.window_text())

    def click_new_registration(self) -> None:
        """ケア記録メインウィンドウの「新規登録」ボタンをクリックし、新規登録フォームを開く。

        実機の「新規登録」Button は auto_id が動的（例: 395888）なため title で検索する。
        クリック後、MDI子ウィンドウ frmKihon が開くのを待つ。
        """
        if self._main_window is None:
            raise RuntimeError("メインウィンドウが未接続です。先に select_care_system() を実行してください")

        logger.info("新規登録ボタンをクリック中...")
        btn = self._main_window.child_window(title="新規登録", control_type="Button")
        btn.wait("visible", timeout=10)
        # pywinauto の UIA backend で btn.click() を実行すると、クリック直後に
        # MDI 子ウィンドウ frmKihon が表示されて元のボタン要素が消失し、UIA 操作の
        # 完了確認フェーズで COMError (UIA_E_ELEMENTNOTAVAILABLE) を投げる。
        # care system 選択と同じく HWND + BM_CLICK で統一する。
        import gc
        target_hwnd = btn.wrapper_object().handle
        del btn
        gc.collect()
        BM_CLICK = 0x00F5
        # SendMessage は同期呼び出しのため、クリックで開く MDI 子フォームが
        # ShowDialog 相当の独自メッセージループに入ると返らなくなり全体がハング
        # する。PostMessage で非同期にキューへ投入し、frmKihon の出現を後段で
        # 検知する。
        logger.info("新規登録 BM_CLICK(Post): hwnd=0x%x", target_hwnd)
        self._post_message(target_hwnd, BM_CLICK, 0, 0)

        # 新規登録フォーム frmKihon を待機
        # frmKihon は MDI 子ウィンドウとして開くため、Application.window() (top-level only)
        # ではなく main_window の descendant として検索する
        logger.info("新規登録フォーム待機中...")
        reg_window = self._main_window.child_window(auto_id="frmKihon")
        reg_window.wait("visible", timeout=10)
        logger.info("新規登録フォーム表示完了")

    def navigate_menu(self, menu_path: list[str]) -> None:
        """MDIメニューを階層的に辿って指定画面に遷移する。"""
        if self._main_window is None:
            raise RuntimeError("メインウィンドウが未接続です。先にlaunchを実行してください")

        logger.info("メニュー遷移: %s", " → ".join(menu_path))

        # WinForms MenuStrip: menu_select("親メニュー->子メニュー") 形式
        menu_string = "->".join(menu_path)

        try:
            self._main_window.menu_select(menu_string)
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
            except (ElementNotFoundError, AttributeError, PywinautoTimeoutError) as fallback_err:
                # menu_select と個別クリックの両方が失敗した場合は silent failure
                # にせず呼び出し元に伝播させる（後段の export_csv 等が誤った MDI
                # 子ウィンドウに対して動作するのを防ぐ）。
                raise RuntimeError(
                    f"メニュー遷移失敗: {menu_string} "
                    f"(menu_select: {exc}; individual click: {fallback_err})"
                ) from fallback_err

        # MDI子ウィンドウが開くのを待機
        time.sleep(1)
        logger.info("メニュー遷移完了: %s", menu_string)

    def export_csv(self, output_dir: Path) -> Path | None:
        """現在の画面からCSVエクスポートを実行する。

        Mock app の印刷ボタンは exe ディレクトリに auto_export.csv を直接出力する。
        本番では SaveFileDialog が表示されるが、CI 環境では Windows 共通ダイアログの
        検出・操作が不安定なため、ダイアログレスのアプローチを採用。
        """
        if self._main_window is None:
            raise RuntimeError("メインウィンドウが未接続です")

        logger.info("CSVエクスポート開始")
        output_dir.mkdir(parents=True, exist_ok=True)

        # アクティブなMDI子ウィンドウの[印刷]ボタンをクリック
        active_child = self._get_active_mdi_child()
        if active_child is None:
            logger.error("MDI子ウィンドウが見つかりません")
            return None

        # BM_CLICK (PostMessage) で印刷ボタンをクリック。
        # click_input() は CI の active desktop 制約で不安定なため、
        # PostMessage 経由の BM_CLICK を使用する。
        import gc
        BM_CLICK = 0x00F5
        btn_print = active_child.child_window(auto_id="btnPrint").wrapper_object()
        btn_hwnd = btn_print.handle
        del btn_print
        gc.collect()
        time.sleep(0.1)
        logger.info("印刷ボタン BM_CLICK: hwnd=0x%x", btn_hwnd)
        _USER32.PostMessageW(btn_hwnd, BM_CLICK, 0, 0)
        time.sleep(3)

        # Mock app が直接出力した auto_export.csv を取得
        csv_filename = f"care_record_{int(time.time())}.csv"
        csv_path = output_dir / csv_filename

        auto_csv = self._find_auto_export_csv()
        if auto_csv is not None:
            import shutil
            shutil.copy2(str(auto_csv), str(csv_path))
            auto_csv.unlink()
            logger.info("CSVエクスポート成功: %s", csv_path)
            return csv_path

        # フォールバック: 保存ダイアログ経由（本番 Wiseman 向け）
        try:
            save_dlg = self._app.window(title_re=".*保存.*|.*名前.*|.*Save.*")
            save_dlg.wait("visible", timeout=10)
        except (ElementNotFoundError, PywinautoTimeoutError):
            logger.error("保存ダイアログが表示されません")
            return None

        for selector in [
            lambda d: d.child_window(auto_id="FileNameControlHost"),
            lambda d: d.child_window(auto_id="txtFileName"),
            lambda d: d.child_window(control_type="Edit"),
        ]:
            try:
                selector(save_dlg).set_edit_text(str(csv_path))
                break
            except (ElementNotFoundError, PywinautoTimeoutError, AttributeError):
                continue
        else:
            logger.warning("ファイル名入力欄が見つかりません")
            return None

        time.sleep(0.5)

        for selector in [
            lambda d: d.child_window(auto_id="btnSave"),
            lambda d: d.child_window(title_re=".*保存.*", control_type="Button"),
            lambda d: d.child_window(title="Save", control_type="Button"),
        ]:
            try:
                selector(save_dlg).click_input()
                break
            except (ElementNotFoundError, PywinautoTimeoutError):
                continue
        else:
            logger.warning("保存ボタンが見つかりません")
            return None

        time.sleep(1)

        if csv_path.exists():
            logger.info("CSVエクスポート成功: %s", csv_path)
            return csv_path

        logger.warning("CSVファイルが見つかりません: %s", csv_path)
        return None

    def _find_auto_export_csv(self) -> Path | None:
        """Mock app が直接出力した auto_export.csv を探す。"""
        search_roots = [Path(__file__).parents[3]]  # プロジェクトルート
        # CI 環境のパス
        ci_root = Path(r"D:\a\wiseman-auto-sys\wiseman-auto-sys")
        if ci_root.exists():
            search_roots.append(ci_root)

        for root in search_roots:
            csv = root / "mock_wiseman_app" / "WisemanMock" / "bin" / "Release" / "auto_export.csv"
            if csv.exists():
                return csv
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
        # WinForms DataGridView UIA構造:
        #   Table > Custom(ヘッダー行) > Header...
        #   Table > Custom(データ行1) > Edit...
        #   Table > Custom(データ行2) > Edit...
        try:
            # まずDataItem（標準的なUIA構造）を試行
            data_items = grid.children(control_type="DataItem")
            if data_items:
                for item in data_items:
                    cells = item.children()
                    row_data = [c.window_text() for c in cells]
                    rows.append(row_data)
                logger.debug("DataItem経由: %d行", len(data_items))
            else:
                # WinForms DataGridView: 行がCustom要素、セルがEdit子要素
                custom_items = grid.children(control_type="Custom")
                data_row_count = 0
                for item in custom_items:
                    edits = item.children(control_type="Edit")
                    if edits:
                        row_data = [e.window_text() for e in edits]
                        rows.append(row_data)
                        data_row_count += 1
                if data_row_count > 0:
                    logger.debug("Custom>Edit経由: %d行", data_row_count)
                elif col_count > 0:
                    # 最終フォールバック: 全子孫Editをフラットに取得し列数で分割
                    edits = grid.descendants(control_type="Edit")
                    if edits:
                        for i in range(0, len(edits), col_count):
                            row_data = [e.window_text() for e in edits[i:i + col_count]]
                            if len(row_data) == col_count:
                                rows.append(row_data)
                        logger.debug("descendants(Edit)経由: %d行", len(rows) - 1)
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

        # [終了] ボタン: ShowDialog()によるモーダルブロック回避
        btn_exit = self._main_window.child_window(auto_id="btnExit").wrapper_object()
        WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0201, 0x0202
        self._post_message(btn_exit.handle, WM_LBUTTONDOWN, 1, 0)
        time.sleep(0.05)
        self._post_message(btn_exit.handle, WM_LBUTTONUP, 0, 0)
        time.sleep(1)

        # 確認ダイアログで [はい] をクリック
        try:
            confirm = self._app.window(title_re=".*確認.*")
            confirm.wait("visible", timeout=10)
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
            except (ProcessLookupError, OSError, SystemError):
                break  # プロセス終了済み（Windows では OSError/SystemError になる場合がある）
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
