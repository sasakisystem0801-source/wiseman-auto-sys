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
import enum
import logging
import tkinter as tk
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Any, assert_never, cast

from wiseman_hub.config import (
    AppConfig,
    ConcatSourceLetter,
    ReportTarget,
    UserNameBBox,
    coerce_path,
    is_path_configured,
    save_config,
)
from wiseman_hub.ui.common import (
    MessageBoxLike,
    assert_main_thread,
    default_messagebox,
    install_tk_exception_guard,
)

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


class ValidationCode(enum.StrEnum):
    """``validate_form`` が返すエラー種別（Issue #68）。

    文字列メッセージ依存を解消し、i18n / テスト結合を enum 経由に集約する。
    表示文字列は ``format_validation_errors`` が UI 層で変換する。
    """

    INPUT_DIR_MISSING = "input_dir_missing"
    OUTPUT_DIR_MISSING = "output_dir_missing"
    SOURCE_A_FILENAME_MISSING = "source_a_filename_missing"
    OCR_ENDPOINT_MISSING = "ocr_endpoint_missing"
    OCR_API_KEY_MISSING = "ocr_api_key_missing"
    BBOX_NOT_NUMBER = "bbox_not_number"
    BBOX_DPI_NOT_POSITIVE_INT = "bbox_dpi_not_positive_int"
    BBOX_DPI_NOT_INTEGER = "bbox_dpi_not_integer"
    CONCAT_ORDER_EMPTY = "concat_order_empty"
    CONCAT_ORDER_INVALID_TOKEN = "concat_order_invalid_token"


@dataclass(frozen=True)
class ValidationError:
    """``validate_form`` が返す個別エラー。

    PII 防御: ``context`` に raw 入力値は入れない。field 名 / 不正 token 等の
    「構造的に安全な情報」のみ保持し、表示文字列は UI 層で構築する。
    """

    code: ValidationCode
    field_name: str
    context: dict[str, Any] = field(default_factory=dict)


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
    # Issue #27 続編 G Phase 2a: input_dir / output_dir は Path 型、Tk Entry は
    # str 保持のため未設定 sentinel は空 str に変換 (is_path_configured ベース)。
    return SettingsForm(
        input_dir=(
            str(config.pdf_merge.input_dir)
            if is_path_configured(config.pdf_merge.input_dir)
            else ""
        ),
        output_dir=(
            str(config.pdf_merge.output_dir)
            if is_path_configured(config.pdf_merge.output_dir)
            else ""
        ),
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
        # Issue #27 続編 G §4: exe_path は Path 型、Tk Entry は str 保持のため
        # 未設定 Path("") (= Path(".")) は空 str に変換する (str(Path("")) == "." なので
        # is_exe_configured で判定)。
        wiseman_exe_path=(
            str(config.wiseman.exe_path) if config.wiseman.is_exe_configured else ""
        ),
    )


def form_to_config(form: SettingsForm, base: AppConfig) -> AppConfig:
    """SettingsForm を既存 AppConfig に重ねて新 AppConfig を返す。

    ``base`` の非フォーム項目（version / log_level / schedule / reports /
    source_d_filename 等）は変更しない。
    ``validate_form`` が空を返すことを前提とする（呼出側で保証）。

    Issue #27 続編 E Phase 3b: ``AppConfig`` が ``frozen=True`` 化されたため、
    旧 ``copy.deepcopy(base)`` + 個別 attribute 代入パターンは attribute
    assignment が ``FrozenInstanceError`` で失敗する。``replace()`` の階層構造
    (``replace(base, pdf_merge=replace(base.pdf_merge, ...))``) に統一する。

    ``replace()`` は dataclass フィールドの shallow copy のため、上書きしない
    ``schedule`` / ``gcp`` / ``updater`` / ``checklist`` 等のフィールドは
    ``base`` と同一オブジェクトを共有する。``AppConfig`` は frozen のため呼出側から
    ``new_cfg.gcp = ...`` 等の参照差し替えは不可能で、各 nested dataclass も
    frozen=True (Phase 1-3a) のため属性代入も防がれる。
    Issue #27 続編 H1: ``AppConfig.reports`` は ``tuple[ReportTarget, ...]`` 化
    済みのため、tuple そのものの参照差し替えは ``replace()`` 経由で行い、要素
    追加・差し替えは tuple 再構築で行う (``cfg.reports.append`` は AttributeError
    で阻止される)。

    ただし mutable leaf (``ReportTarget.menu_path`` の list) は依然 frozen でも
    内容変更不可ではないため、``form_to_config`` の戻り値経由で
    ``new_cfg.reports[0].menu_path.append(...)`` 等を実行すると ``base`` 側にも
    漏れる。Codex review (PR #272) Medium 指摘の防御として ``reports`` は
    ``ReportTarget.menu_path`` まで含めて新 list で再構築し、mutable leaf の
    base/new_cfg alias を切る (umbrella 続編 H2 で menu_path の tuple 化により
    本暫定防御は不要になる予定)。
    """
    # bbox / concat_order は dataclass を再構築して __post_init__ で即時検証する
    # （個別属性代入では bypass されるため、不正値が次回起動まで silent になる問題を回避）。
    # 不正値（順序逆転 bbox / 未知 letter 等）は ValueError として呼出側に伝播し、
    # 既存の messagebox.showerror で UI 表示される。
    new_bbox = UserNameBBox(
        x0=float(form.bbox_x0),
        y0=float(form.bbox_y0),
        x1=float(form.bbox_x1),
        y1=float(form.bbox_y1),
        dpi=int(form.bbox_dpi),
    )
    # Issue #151: concat_order は tuple 化して mutation bypass を構造的に防ぐ。
    # __post_init__ 側にも fail-safe 変換があるが、settings 経由でも明示 tuple
    # で渡すことで呼出側の型契約と一致させる。
    parsed_concat = cast(
        tuple[ConcatSourceLetter, ...],
        tuple(s.strip() for s in form.concat_order.split(",") if s.strip()),
    )
    # PR #272 Codex Medium 指摘対応: mutable leaf list の base/new_cfg alias を切る。
    # Issue #27 続編 H1: AppConfig.reports は tuple 化済 (要素差し替え/追加は
    # tuple 再構築のみ可能、append/__setitem__ は AttributeError/TypeError)。
    # 残る mutable leaf は ReportTarget.menu_path (umbrella 続編 H2 対象)。
    # 続編 H2 完了までの暫定防御として、leaf list を浅くコピーする。
    decoupled_reports: tuple[ReportTarget, ...] = tuple(
        replace(r, menu_path=list(r.menu_path)) for r in base.reports
    )
    # API Key は前後空白も有効値として尊重（``form.ocr_api_key`` 生値を維持）。
    return replace(
        base,
        reports=decoupled_reports,
        pdf_merge=replace(
            base.pdf_merge,
            # Issue #27 続編 G Phase 2a: form (str) → Path 変換。coerce_path で
            # 空白 strip + Path("") sentinel 化を TOML 経路と一致させる (DRY)。
            input_dir=coerce_path("pdf_merge.input_dir", form.input_dir),
            output_dir=coerce_path("pdf_merge.output_dir", form.output_dir),
            source_a_filename=form.source_a_filename.strip(),
            source_b_pattern=form.source_b_pattern.strip(),
            source_c_pattern=form.source_c_pattern.strip(),
            concat_order=parsed_concat,
            user_name_bbox=new_bbox,
        ),
        ocr_backend=replace(
            base.ocr_backend,
            endpoint_url=form.ocr_endpoint_url.strip(),
            api_key=form.ocr_api_key,
        ),
        wiseman=replace(
            base.wiseman,
            # Issue #27 続編 G §4: form (str) → Path 変換。``coerce_path`` で TOML
            # 経路と同じ正規化 (空白 strip → Path("") sentinel) を再利用、UI と
            # 起動時で sentinel 規約を一元化する (DRY)。
            exe_path=coerce_path("wiseman.exe_path", form.wiseman_exe_path),
        ),
    )


_BBOX_FIELD_LABELS: dict[str, str] = {
    "bbox_x0": "bbox x0",
    "bbox_y0": "bbox y0",
    "bbox_x1": "bbox x1",
    "bbox_y1": "bbox y1",
}


def validate_form(form: SettingsForm) -> list[ValidationError]:
    """フォーム値を検証し、``ValidationError`` のリストを返す（空 = OK）。

    PII 防御: ``context`` に raw 入力値を入れない（API Key を URL 欄に貼付け
    などのコピペ誤入力で PII が表示層に露出しないよう構造的に分離する）。
    """
    errors: list[ValidationError] = []

    if not form.input_dir.strip():
        errors.append(
            ValidationError(code=ValidationCode.INPUT_DIR_MISSING, field_name="input_dir")
        )
    if not form.output_dir.strip():
        errors.append(
            ValidationError(code=ValidationCode.OUTPUT_DIR_MISSING, field_name="output_dir")
        )
    if not form.source_a_filename.strip():
        errors.append(
            ValidationError(
                code=ValidationCode.SOURCE_A_FILENAME_MISSING, field_name="source_a_filename"
            )
        )
    if not form.ocr_endpoint_url.strip():
        errors.append(
            ValidationError(
                code=ValidationCode.OCR_ENDPOINT_MISSING, field_name="ocr_endpoint_url"
            )
        )
    if not form.ocr_api_key.strip():
        errors.append(
            ValidationError(code=ValidationCode.OCR_API_KEY_MISSING, field_name="ocr_api_key")
        )

    for bbox_field in ("bbox_x0", "bbox_y0", "bbox_x1", "bbox_y1"):
        try:
            float(getattr(form, bbox_field))
        except ValueError:
            errors.append(
                ValidationError(code=ValidationCode.BBOX_NOT_NUMBER, field_name=bbox_field)
            )

    try:
        dpi = int(form.bbox_dpi)
        if dpi <= 0:
            errors.append(
                ValidationError(
                    code=ValidationCode.BBOX_DPI_NOT_POSITIVE_INT, field_name="bbox_dpi"
                )
            )
    except ValueError:
        errors.append(
            ValidationError(code=ValidationCode.BBOX_DPI_NOT_INTEGER, field_name="bbox_dpi")
        )

    order_tokens = [s.strip() for s in form.concat_order.split(",") if s.strip()]
    if not order_tokens:
        errors.append(
            ValidationError(code=ValidationCode.CONCAT_ORDER_EMPTY, field_name="concat_order")
        )
    else:
        invalid = [t for t in order_tokens if t not in _VALID_SOURCES]
        if invalid:
            errors.append(
                ValidationError(
                    code=ValidationCode.CONCAT_ORDER_INVALID_TOKEN,
                    field_name="concat_order",
                    context={"invalid_tokens": invalid},
                )
            )

    return errors


def _message_for(err: ValidationError) -> str:
    """ValidationError 単体の UI 表示文字列を構築。

    ``match`` + ``assert_never`` で mypy が網羅性を静的検証する。新しい
    ``ValidationCode`` を追加した際に対応メッセージを書き忘れると型エラー
    として検出されるため、実行時 ``AssertionError`` 防御より早い段階で気付ける。
    """
    match err.code:
        case ValidationCode.INPUT_DIR_MISSING:
            return "入力フォルダを指定してください。"
        case ValidationCode.OUTPUT_DIR_MISSING:
            return "出力フォルダを指定してください。"
        case ValidationCode.SOURCE_A_FILENAME_MISSING:
            return "A.pdf ファイル名を入力してください。"
        case ValidationCode.OCR_ENDPOINT_MISSING:
            return "OCR エンドポイント URL を入力してください。"
        case ValidationCode.OCR_API_KEY_MISSING:
            return "OCR API キーを入力してください。"
        case ValidationCode.BBOX_NOT_NUMBER:
            label = _BBOX_FIELD_LABELS.get(err.field_name, err.field_name)
            return f"{label} は数値で入力してください。"
        case ValidationCode.BBOX_DPI_NOT_POSITIVE_INT:
            return "bbox dpi は正の整数で入力してください。"
        case ValidationCode.BBOX_DPI_NOT_INTEGER:
            return "bbox dpi は整数で入力してください。"
        case ValidationCode.CONCAT_ORDER_EMPTY:
            return "結合順 concat_order を A,B,C のようなカンマ区切りで入力してください。"
        case ValidationCode.CONCAT_ORDER_INVALID_TOKEN:
            tokens = err.context.get("invalid_tokens", [])
            return (
                "結合順 concat_order に不正な識別子があります: "
                + ",".join(tokens)
                + f"（使用可能: {','.join(_VALID_SOURCES)}）"
            )
        case _:
            assert_never(err.code)


def format_validation_errors(errors: Iterable[ValidationError]) -> str:
    """ValidationError 列を messagebox body 用の bullet list 文字列に整形。"""
    return "\n".join(f"・{_message_for(e)}" for e in errors)


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
        install_tk_exception_guard(
            self._root, component="settings", messagebox=self._messagebox
        )

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
                _MSG_VALIDATION_HEADER + format_validation_errors(errors),
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

        - Toplevel: grab_release → ``destroy()`` で wait_window が return → 親 mainloop 継続
        - Standalone: ``quit()`` で自前 mainloop を終了

        Windows での grab 残留を防ぐため、Toplevel モード時は destroy 前に明示的に
        grab_release する（Codex MEDIUM 指摘、ConfirmDialog / SessionPicker と統一）。
        """
        if self._is_toplevel:
            with contextlib.suppress(tk.TclError):
                if self._root.grab_current() is self._root:  # type: ignore[no-untyped-call]
                    self._root.grab_release()
            with contextlib.suppress(tk.TclError):
                self._root.destroy()
        else:
            with contextlib.suppress(tk.TclError):
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

