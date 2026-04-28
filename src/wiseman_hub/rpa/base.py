"""RPA抽象インターフェース - Windows実装とmacOSモック実装の共通基盤"""

from __future__ import annotations

import abc
from pathlib import Path


class ExportCsvError(RuntimeError):
    """``export_csv`` 失敗の基底例外 (Issue #14)。

    呼び出し元はこの基底を catch することで全 export_csv 失敗を一括処理できる。
    具体的な失敗モードを区別したい場合はサブクラスで catch する。
    """


class MdiChildNotFoundError(ExportCsvError):
    """アクティブ MDI 子ウィンドウが見つからない。"""


class SaveDialogNotShownError(ExportCsvError):
    """保存ダイアログが期待時間内に表示されない。"""


class FileNameFieldNotFoundError(ExportCsvError):
    """保存ダイアログ内のファイル名入力欄を全 selector で発見できない。"""


class SaveButtonNotFoundError(ExportCsvError):
    """保存ダイアログ内の保存ボタンを全 selector で発見できない。"""


class CsvFileNotFoundError(ExportCsvError):
    """保存処理後に CSV ファイルが期待パスに作成されていない (待機タイムアウト
    または保存自体の失敗の両方を含む)。"""


class RPAEngine(abc.ABC):
    """ワイズマンGUI操作の抽象インターフェース。

    ワイズマンシステムSP（オンプレミス版）はMDI構成のネイティブWindowsアプリ。
    UI要素: ボタン、コンボボックス、チェックボックス、ラジオボタン、データグリッド。
    """

    @abc.abstractmethod
    def launch(self, exe_path: str) -> None:
        """ワイズマンを起動する（システム選択ランチャーまで）。

        ワイズマンはUSBドングル認証のみで動作し、アプリ内のログイン画面は存在しない。
        起動後、最初に表示されるのは「ワイズマンシステムSP」システム選択ランチャー
        （auto_id=frmStartUp）で、ここから目的のサブシステムを選択する必要がある。

        1. exe_path（.lnk または .exe）からアプリを起動
        2. USBドングル認証通過を待機（startup_wait_sec）
        3. システム選択ランチャーウィンドウ(frmStartUp)の表示を確認

        Args:
            exe_path: ワイズマン起動用のショートカット(.lnk)または実行ファイル(.exe)パス。
                Windows の場合、.lnk は Shell 経由で解決される。
        """

    @abc.abstractmethod
    def select_care_system(self) -> None:
        """システム選択ランチャーから「通所・訪問リハビリ管理システム SP(ケア記録)」を選択する。

        ランチャー画面の該当Pane（WinForms Panel）をクリックし、
        ケア記録メインウィンドウ(auto_id=frmMenu200)が開くのを待つ。
        """

    @abc.abstractmethod
    def click_new_registration(self) -> None:
        """ケア記録メインウィンドウの「新規登録」ボタンをクリックし、新規登録フォームを開く。

        クリック後、MDI子ウィンドウ(auto_id=frmKihon)が開くのを待つ。
        最小動作確認シナリオのためのメソッド。
        """

    @abc.abstractmethod
    def navigate_menu(self, menu_path: list[str]) -> None:
        """MDIメニューを階層的に辿って指定画面に遷移する。

        Args:
            menu_path: メニューの階層パス (例: ["ケア記録", "集計表"])
        """

    @abc.abstractmethod
    def export_csv(self, output_dir: Path) -> Path:
        """現在の画面からCSVエクスポートを実行する。

        操作フロー:
        1. [印刷] ボタンクリック
        2. 出力形式でCSVを選択
        3. 保存ダイアログでファイルパスを指定
        4. [保存] クリック

        Returns:
            保存されたCSVファイルのパス。

        Raises:
            ExportCsvError: 失敗時は本基底例外のサブクラスを raise する (Issue #14):

                - ``MdiChildNotFoundError``: アクティブ MDI 子ウィンドウ未取得
                - ``SaveDialogNotShownError``: 保存ダイアログ未出現
                - ``FileNameFieldNotFoundError``: ファイル名入力欄未発見
                - ``SaveButtonNotFoundError``: 保存ボタン未発見
                - ``CsvFileNotFoundError``: 保存後 CSV ファイル未存在
        """

    @abc.abstractmethod
    def read_grid_data(self) -> list[list[str]]:
        """現在の画面のデータグリッドからデータを直接読み取る。

        Returns:
            二次元リスト（行×列のテキストデータ）
        """

    @abc.abstractmethod
    def close_current_window(self) -> None:
        """現在のMDI子ウィンドウを閉じる（[閉じる]ボタン）。"""

    @abc.abstractmethod
    def close_wiseman(self) -> None:
        """ワイズマンを安全に終了する（[終了]ボタン → 確認ダイアログ）。"""

    @abc.abstractmethod
    def is_dongle_present(self) -> bool:
        """USBドングルが認識されているか確認する。

        ドングル未認識時はワイズマンがエラーダイアログを表示する想定。
        """

    @abc.abstractmethod
    def take_screenshot(self, name: str) -> Path:
        """現在の画面のスクリーンショットを保存する。"""
