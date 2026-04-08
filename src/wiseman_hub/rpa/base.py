"""RPA抽象インターフェース - Windows実装とmacOSモック実装の共通基盤"""

from __future__ import annotations

import abc
from pathlib import Path


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
    def export_csv(self, output_dir: Path) -> Path | None:
        """現在の画面からCSVエクスポートを実行する。

        操作フロー:
        1. [印刷] ボタンクリック
        2. 出力形式でCSVを選択
        3. 保存ダイアログでファイルパスを指定
        4. [保存] クリック

        Returns:
            保存されたCSVファイルのパス。失敗時はNone。
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
