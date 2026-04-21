"""設定 GUI（タスク 12B）。

TOML を「正」として維持し、本 GUI はそれを編集するツールに徹する。
エンドユーザー（介護施設運用者）がフォルダパス等を継続的に微調整する運用を想定。

設計方針:
- Pure logic（``SettingsForm`` ↔ ``AppConfig`` 変換、バリデーション）を Tk 非依存に分離
- UI 層は Entry / Button / filedialog の wiring と ``save_fn`` 呼出に徹する
- API Key 欄は ``show="*"`` でマスク（ショルダーハック防止）
- save 失敗時はログに型名のみ（PII 防御）、ユーザーには sanitized メッセージ
"""

from __future__ import annotations

import contextlib
import copy
import enum
import logging
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, ttk

from wiseman_hub.config import AppConfig, save_config
from wiseman_hub.ui.common import assert_main_thread
from wiseman_hub.ui.confirm_dialog import MessageBoxLike, default_messagebox

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


_VALID_SOURCES: tuple[str, ...] = ("A", "B", "C", "D")


@dataclass
class SettingsForm:
    """設定 GUI で編集するフィールドのみを保持する flat な入力モデル（全て文字列）。

    数値項目（bbox, dpi）は Tk Entry で保持するため文字列のまま扱い、
    ``validate_form`` と ``form_to_config`` で変換 + エラーチェックする。
    """

    input_dir: str = ""
    output_dir: str = ""
    source_a_filename: str = ""
    source_b_pattern: str = "B_{name}.pdf"
    source_c_pattern: str = "C_{name}.pdf"
    concat_order: str = "A,B,C"
    bbox_x0: str = "0.0"
    bbox_y0: str = "0.0"
    bbox_x1: str = "0.0"
    bbox_y1: str = "0.0"
    bbox_dpi: str = "200"
    ocr_endpoint_url: str = ""
    ocr_api_key: str = ""
    wiseman_exe_path: str = ""


@dataclass(frozen=True)
class SettingsDialogResult:
    """``SettingsDialog.run()`` の返却値。

    ``config is not None`` が成立する iff 保存が成功した。``saved`` property は
    単一真実源である ``config`` から派生させ、bool と optional を同期させる二重
    表現を避ける（呼出側が ``saved=True`` かつ ``config is None`` を誤って扱う
    ケースを構造的に排除）。
    """

    config: AppConfig | None = None

    @property
    def saved(self) -> bool:
        return self.config is not None


# ---------------------------------------------------------------------------
# Pure logic
# ---------------------------------------------------------------------------


def form_from_config(config: AppConfig) -> SettingsForm:
    """AppConfig から SettingsForm を生成（GUI 初期値用）。"""
    bbox = config.pdf_merge.user_name_bbox
    return SettingsForm(
        input_dir=config.pdf_merge.input_dir,
        output_dir=config.pdf_merge.output_dir,
        source_a_filename=config.pdf_merge.source_a_filename,
        source_b_pattern=config.pdf_merge.source_b_pattern,
        source_c_pattern=config.pdf_merge.source_c_pattern,
        concat_order=",".join(config.pdf_merge.concat_order),
        bbox_x0=str(bbox.x0),
        bbox_y0=str(bbox.y0),
        bbox_x1=str(bbox.x1),
        bbox_y1=str(bbox.y1),
        bbox_dpi=str(bbox.dpi),
        ocr_endpoint_url=config.ocr_backend.endpoint_url,
        ocr_api_key=config.ocr_backend.api_key,
        wiseman_exe_path=config.wiseman.exe_path,
    )


def form_to_config(form: SettingsForm, base: AppConfig) -> AppConfig:
    """SettingsForm を既存 AppConfig に重ねて新 AppConfig を返す。

    ``base`` の非フォーム項目（version / log_level / schedule / reports /
    source_d_filename 等）は変更しない。deepcopy で副作用を避ける。
    ``validate_form`` が空を返すことを前提とする（呼出側で保証）。
    """
    new_config = copy.deepcopy(base)
    new_config.pdf_merge.input_dir = form.input_dir.strip()
    new_config.pdf_merge.output_dir = form.output_dir.strip()
    new_config.pdf_merge.source_a_filename = form.source_a_filename.strip()
    new_config.pdf_merge.source_b_pattern = form.source_b_pattern.strip()
    new_config.pdf_merge.source_c_pattern = form.source_c_pattern.strip()
    new_config.pdf_merge.concat_order = [
        s.strip() for s in form.concat_order.split(",") if s.strip()
    ]
    new_config.pdf_merge.user_name_bbox.x0 = float(form.bbox_x0)
    new_config.pdf_merge.user_name_bbox.y0 = float(form.bbox_y0)
    new_config.pdf_merge.user_name_bbox.x1 = float(form.bbox_x1)
    new_config.pdf_merge.user_name_bbox.y1 = float(form.bbox_y1)
    new_config.pdf_merge.user_name_bbox.dpi = int(form.bbox_dpi)
    new_config.ocr_backend.endpoint_url = form.ocr_endpoint_url.strip()
    new_config.ocr_backend.api_key = form.ocr_api_key  # API Key は前後空白も有効値として尊重
    new_config.wiseman.exe_path = form.wiseman_exe_path.strip()
    return new_config


def validate_form(form: SettingsForm) -> list[str]:
    """フォーム値を検証し、エラーメッセージの list を返す（空 = OK）。"""
    errors: list[str] = []

    if not form.input_dir.strip():
        errors.append("入力フォルダを指定してください。")
    if not form.output_dir.strip():
        errors.append("出力フォルダを指定してください。")
    if not form.source_a_filename.strip():
        errors.append("A.pdf ファイル名を入力してください。")
    if not form.ocr_endpoint_url.strip():
        errors.append("OCR エンドポイント URL を入力してください。")
    if not form.ocr_api_key.strip():
        errors.append("OCR API キーを入力してください。")

    # エラーメッセージに入力値 (raw) を埋め込まない。フィールド間のコピペ誤入力
    # （例: API Key を URL 欄に貼付けて数値エラーになる）で PII が表示に露出する
    # のを防ぐ（PII 防御）。
    for label, raw in (
        ("bbox x0", form.bbox_x0),
        ("bbox y0", form.bbox_y0),
        ("bbox x1", form.bbox_x1),
        ("bbox y1", form.bbox_y1),
    ):
        try:
            float(raw)
        except ValueError:
            errors.append(f"{label} は数値で入力してください。")

    try:
        dpi = int(form.bbox_dpi)
        if dpi <= 0:
            errors.append("bbox dpi は正の整数で入力してください。")
    except ValueError:
        errors.append("bbox dpi は整数で入力してください。")

    order_tokens = [s.strip() for s in form.concat_order.split(",") if s.strip()]
    if not order_tokens:
        errors.append("結合順 concat_order を A,B,C のようなカンマ区切りで入力してください。")
    else:
        invalid = [t for t in order_tokens if t not in _VALID_SOURCES]
        if invalid:
            errors.append(
                "結合順 concat_order に不正な識別子があります: "
                + ",".join(invalid)
                + f"（使用可能: {','.join(_VALID_SOURCES)}）"
            )

    return errors


# ---------------------------------------------------------------------------
# UI text
# ---------------------------------------------------------------------------


class _FolderKey(enum.StrEnum):
    INPUT = "input_dir"
    OUTPUT = "output_dir"


_TITLE = "設定"
_TITLE_SAVE_ERROR = "設定保存エラー"
_MSG_SAVE_ERROR_FMT = (
    "設定の保存に失敗しました。詳細はログを確認してください。\n\n{type}"
)
_TITLE_VALIDATION_ERROR = "入力エラー"
_MSG_VALIDATION_HEADER = "以下の項目を修正してください:\n\n"


# ---------------------------------------------------------------------------
# SettingsDialog
# ---------------------------------------------------------------------------


SaveFn = Callable[..., object]
AskDirectoryFn = Callable[..., str]
AskOpenFileFn = Callable[..., str]


class SettingsDialog:
    """TOML 設定を編集する Tkinter フォーム。"""

    def __init__(
        self,
        config: AppConfig,
        config_path: Path,
        *,
        root: tk.Tk | None = None,
        parent: tk.Misc | None = None,
        save_fn: SaveFn = save_config,
        askdirectory_fn: AskDirectoryFn = filedialog.askdirectory,
        askopenfilename_fn: AskOpenFileFn = filedialog.askopenfilename,
        messagebox_fn: MessageBoxLike | None = None,
    ) -> None:
        """Args:
            root: 既存 Tk root をテストから渡すとき（parent 排他）。
            parent: Launcher など親ウィンドウが既にある場合に渡す。指定時は
                `Toplevel` + `grab_set` + `wait_window` で**モーダル**化し、
                設定編集中に Launcher の他ボタンが押されて旧 config で Phase A が
                走る race を構造的に防ぐ（医療 PII の誤配置対策）。
        """
        assert_main_thread("SettingsDialog")

        self._config = config
        self._config_path = config_path
        self._save_fn = save_fn
        self._askdirectory_fn = askdirectory_fn
        self._askopenfilename_fn = askopenfilename_fn
        self._messagebox = messagebox_fn or default_messagebox()

        if root is not None and parent is not None:
            raise ValueError("pass either root or parent, not both")
        if parent is not None:
            self._owns_root = True
            self._is_toplevel = True
            toplevel = tk.Toplevel(parent)
            # transient は Wm / Tcl_Obj を期待するが、Tk は Wm 派生のため実際には安全。
            # typeshed の overload 差で mypy が誤検知するため型無視する。
            toplevel.transient(parent)  # type: ignore[call-overload]
            toplevel.grab_set()
            self._root: tk.Tk | tk.Toplevel = toplevel
        elif root is not None:
            self._owns_root = False
            self._is_toplevel = False
            self._root = root
        else:
            self._owns_root = True
            self._is_toplevel = False
            self._root = tk.Tk()
        # Tk 既定は callback 例外を stderr へ traceback 出力するため PII が漏れる。
        # Toplevel でも root 経由で共有される property を上書きする。
        self._root.report_callback_exception = self._on_callback_exception  # type: ignore[union-attr]

        self._result: SettingsDialogResult = SettingsDialogResult()
        self._vars: dict[str, tk.StringVar] = {}

        self._build_ui()

    # -- UI construction ----------------------------------------------------

    def _build_ui(self) -> None:
        root = self._root
        root.title(_TITLE)
        root.geometry("560x560")

        container = ttk.Frame(root, padding=12)
        container.pack(fill="both", expand=True)

        initial = form_from_config(self._config)

        # ゲループ 1: フォルダパス
        self._add_folder_row(container, 0, "入力フォルダ", "input_dir",
                             initial.input_dir, _FolderKey.INPUT)
        self._add_folder_row(container, 1, "出力フォルダ", "output_dir",
                             initial.output_dir, _FolderKey.OUTPUT)

        # ゲループ 2: ファイル名 / パターン
        self._add_entry_row(container, 2, "A.pdf ファイル名",
                            "source_a_filename", initial.source_a_filename)
        self._add_entry_row(container, 3, "B パターン（{name}=氏名）",
                            "source_b_pattern", initial.source_b_pattern)
        self._add_entry_row(container, 4, "C パターン（{name}=氏名）",
                            "source_c_pattern", initial.source_c_pattern)
        self._add_entry_row(container, 5, "結合順（カンマ区切り）",
                            "concat_order", initial.concat_order)

        # グループ 3: bbox
        self._add_entry_row(container, 6, "bbox x0", "bbox_x0", initial.bbox_x0)
        self._add_entry_row(container, 7, "bbox y0", "bbox_y0", initial.bbox_y0)
        self._add_entry_row(container, 8, "bbox x1", "bbox_x1", initial.bbox_x1)
        self._add_entry_row(container, 9, "bbox y1", "bbox_y1", initial.bbox_y1)
        self._add_entry_row(container, 10, "bbox dpi", "bbox_dpi", initial.bbox_dpi)

        # グループ 4: OCR
        self._add_entry_row(container, 11, "OCR エンドポイント URL",
                            "ocr_endpoint_url", initial.ocr_endpoint_url)
        self.api_key_entry = self._add_entry_row(
            container, 12, "OCR API キー", "ocr_api_key",
            initial.ocr_api_key, show="*",
        )

        # グループ 5: Wiseman（optional）
        self._add_file_row(container, 13, "Wiseman exe パス（任意）",
                           "wiseman_exe_path", initial.wiseman_exe_path)

        # ボタン行
        btn_frame = ttk.Frame(container, padding=(0, 12, 0, 0))
        btn_frame.grid(row=14, column=0, columnspan=3, sticky="ew")
        ttk.Button(btn_frame, text="保存", command=self.attempt_save).pack(
            side="right", padx=(6, 0)
        )
        ttk.Button(btn_frame, text="キャンセル", command=self.cancel).pack(
            side="right"
        )

        # 列の伸縮
        container.columnconfigure(1, weight=1)

    def _add_entry_row(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        field_name: str,
        initial: str,
        *,
        show: str | None = None,
        columnspan: int = 2,
    ) -> ttk.Entry:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        var = tk.StringVar(value=initial)
        self._vars[field_name] = var
        entry = ttk.Entry(parent, textvariable=var)
        if show is not None:
            entry.configure(show=show)
        entry.grid(
            row=row, column=1, columnspan=columnspan, sticky="ew", padx=(6, 0), pady=3
        )
        return entry

    def _add_folder_row(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        field_name: str,
        initial: str,
        folder_key: _FolderKey,
    ) -> None:
        self._add_entry_row(parent, row, label, field_name, initial, columnspan=1)
        target = folder_key.value
        ttk.Button(
            parent,
            text="選択...",
            command=lambda: self.pick_folder(target),
        ).grid(row=row, column=2, padx=(6, 0), pady=3)

    def _add_file_row(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        field_name: str,
        initial: str,
    ) -> None:
        self._add_entry_row(parent, row, label, field_name, initial, columnspan=1)
        ttk.Button(
            parent,
            text="選択...",
            command=lambda: self.pick_file(field_name),
        ).grid(row=row, column=2, padx=(6, 0), pady=3)

    # -- Public entry -------------------------------------------------------

    def run(self) -> SettingsDialogResult:
        try:
            if self._is_toplevel:
                # Toplevel モードは親 mainloop が既に走っているので wait_window で
                # このダイアログが閉じるまで block（他ボタンは grab_set で抑止済み）。
                self._root.wait_window()
            else:
                # Standalone モード（テスト / parent なし起動）では自前 mainloop。
                self._root.mainloop()
        finally:
            if self._owns_root:
                with contextlib.suppress(tk.TclError):
                    self._root.destroy()
        return self._result

    def current_form(self) -> SettingsForm:
        """各 Entry の現在値を SettingsForm として返す（テスト / save 用）。"""
        kwargs = {name: var.get() for name, var in self._vars.items()}
        return SettingsForm(**kwargs)

    def attempt_save(self) -> SettingsDialogResult:
        form = self.current_form()
        errors = validate_form(form)
        if errors:
            self._messagebox.showerror(
                _TITLE_VALIDATION_ERROR,
                _MSG_VALIDATION_HEADER + "\n".join(f"・{e}" for e in errors),
            )
            return SettingsDialogResult()

        try:
            new_config = form_to_config(form, self._config)
            # save_config は create_if_missing=False が既定だが、設定 GUI から
            # 保存する以上「設定ファイルを作ってよい」状況なので明示的に True。
            self._save_fn(new_config, self._config_path, create_if_missing=True)
        except (OSError, ValueError, TypeError) as exc:
            # 想定される失敗型のみ捕捉（ファイル I/O / 数値 parse / TOML 型違反）。
            # 想定外は _on_callback_exception に落として fail-fast。
            # PII 防御: 例外 message はパスを含みうるため型名のみログに残す。
            logger.error("save_config failed: %s", type(exc).__name__)
            self._messagebox.showerror(
                _TITLE_SAVE_ERROR,
                _MSG_SAVE_ERROR_FMT.format(type=type(exc).__name__),
            )
            return SettingsDialogResult()

        self._result = SettingsDialogResult(config=new_config)
        self._close_dialog()
        return self._result

    def cancel(self) -> SettingsDialogResult:
        self._result = SettingsDialogResult()
        self._close_dialog()
        return self._result

    def _close_dialog(self) -> None:
        """Toplevel / standalone 両モードで dialog を閉じる共通処理。

        - Toplevel: ``destroy()`` で wait_window が return → 親の mainloop 継続
        - Standalone: ``quit()`` で自前 mainloop を終了
        """
        with contextlib.suppress(tk.TclError):
            if self._is_toplevel:
                self._root.destroy()
            else:
                self._root.quit()

    def pick_folder(self, field_name: str) -> None:
        if field_name not in self._vars:
            raise ValueError(f"unknown folder field: {field_name}")
        picked = self._askdirectory_fn(title="フォルダを選択")
        if picked:
            self._vars[field_name].set(picked)

    def pick_file(self, field_name: str) -> None:
        if field_name not in self._vars:
            raise ValueError(f"unknown file field: {field_name}")
        picked = self._askopenfilename_fn(title="ファイルを選択")
        if picked:
            self._vars[field_name].set(picked)

    # -- Tk callback exception ---------------------------------------------

    def _on_callback_exception(
        self,
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_tb: object,
    ) -> None:
        # PII 防御: logger には型名のみ。
        logger.error("settings callback exception: %s", exc_type.__name__)
        try:
            self._messagebox.showerror(
                "内部エラー",
                "処理中にエラーが発生しました。詳細はログを確認してください。\n\n"
                f"{exc_type.__name__}",
            )
        except Exception as e:  # noqa: BLE001 — 二次 showerror 失敗は握り潰し可
            # ConfirmDialog と同じ PII 防御パターン: 型名のみ。
            logger.warning(
                "showerror failed during settings callback exception: %s",
                type(e).__name__,
            )
