"""事業所フォルダ PDF 結合ダイアログ（MVP 暫定）。

Wiseman 系帳票の事業所単位結合機能の GUI フロント。既存 Phase A/B とは独立。

構成:
  - A.pdf 選択（filedialog.askopenfilename）
  - 事業所フォルダ選択（filedialog.askdirectory）
  - 出力ルート選択（filedialog.askdirectory）
  - [実行] ボタンで `merge_facility()` を呼び出し、結果サマリを表示

PII 防御:
  - サマリ表示は user_key（姓）のみ、full_name は出さない
  - エラー時は型名のみ表示

スコープ外（次 PR）:
  - 親フォルダから複数サブフォルダ選択
  - worker thread による非同期化（現状は同期実行、UI 一時ブロック）
  - 進捗バー
"""

from __future__ import annotations

import logging
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Final

from wiseman_hub.pdf.facility_merger import FacilityMergeReport, merge_facility
from wiseman_hub.ui.common import MessageBoxLike, default_messagebox

logger = logging.getLogger(__name__)

_TITLE: Final[str] = "事業所フォルダ PDF 結合"

_LABEL_A: Final[str] = "A: 提供実績 PDF"
_LABEL_FACILITY: Final[str] = "事業所フォルダ"
_LABEL_OUTPUT: Final[str] = "出力ルート"

_BTN_BROWSE: Final[str] = "参照..."
_BTN_RUN: Final[str] = "実行"
_BTN_CLOSE: Final[str] = "閉じる"

_MSG_SELECT_ALL: Final[str] = (
    "A.pdf / 事業所フォルダ / 出力ルート の全てを指定してください。"
)
_MSG_TITLE_ERROR: Final[str] = "実行エラー"
_MSG_TITLE_INVALID_INPUT: Final[str] = "入力不備"


@dataclass(frozen=True)
class FacilityMergerDialogResult:
    """ダイアログ終了時の戻り値（将来拡張用、現状は close されたかのみ記録）。"""

    executed: bool = False
    report: FacilityMergeReport | None = None


# DI フック: テストで `merge_facility` を差し替え可能にする
MergeFacilityFn = Callable[[Path, Path, Path], FacilityMergeReport]


class FacilityMergerDialog:
    """事業所フォルダ結合 Toplevel ダイアログ。"""

    def __init__(
        self,
        parent: tk.Tk | tk.Toplevel | tk.Misc,
        *,
        merge_fn: MergeFacilityFn | None = None,
        messagebox_fn: MessageBoxLike | None = None,
        filedialog_askopenfilename: Callable[..., str] | None = None,
        filedialog_askdirectory: Callable[..., str] | None = None,
    ) -> None:
        self._parent = parent
        self._merge_fn: MergeFacilityFn = merge_fn or merge_facility
        self._messagebox = messagebox_fn or default_messagebox()
        self._askopenfilename = (
            filedialog_askopenfilename or filedialog.askopenfilename
        )
        self._askdirectory = filedialog_askdirectory or filedialog.askdirectory
        self._result = FacilityMergerDialogResult()

        self._top = tk.Toplevel(parent)
        self._top.title(_TITLE)
        self._top.geometry("560x420")
        self._top.transient(parent)  # type: ignore[arg-type]
        self._top.grab_set()

        self._a_var = tk.StringVar()
        self._facility_var = tk.StringVar()
        self._output_var = tk.StringVar()

        self._build_ui()

    def _build_ui(self) -> None:
        frame = ttk.Frame(self._top, padding=12)
        frame.pack(fill="both", expand=True)

        self._add_path_row(frame, 0, _LABEL_A, self._a_var, self._browse_a)
        self._add_path_row(
            frame, 1, _LABEL_FACILITY, self._facility_var, self._browse_facility
        )
        self._add_path_row(
            frame, 2, _LABEL_OUTPUT, self._output_var, self._browse_output
        )

        # 結果表示エリア
        ttk.Label(frame, text="結果:").grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(12, 2)
        )
        self._result_text = tk.Text(frame, height=10, width=60, wrap="word")
        self._result_text.grid(row=4, column=0, columnspan=3, sticky="nsew")
        self._result_text.configure(state="disabled")

        # ボタン行
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=5, column=0, columnspan=3, sticky="e", pady=(12, 0))
        self._btn_run = ttk.Button(
            btn_frame, text=_BTN_RUN, command=self._on_run
        )
        self._btn_close = ttk.Button(
            btn_frame, text=_BTN_CLOSE, command=self._on_close
        )
        self._btn_run.pack(side="left", padx=(0, 8))
        self._btn_close.pack(side="left")

        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(4, weight=1)

    def _add_path_row(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        var: tk.StringVar,
        browse_command: Callable[[], None],
    ) -> None:
        ttk.Label(parent, text=label).grid(
            row=row, column=0, sticky="w", padx=(0, 8), pady=4
        )
        entry = ttk.Entry(parent, textvariable=var, width=50)
        entry.grid(row=row, column=1, sticky="ew", pady=4)
        ttk.Button(parent, text=_BTN_BROWSE, command=browse_command).grid(
            row=row, column=2, padx=(8, 0), pady=4
        )

    def _browse_a(self) -> None:
        path = self._askopenfilename(
            parent=self._top,
            title=_LABEL_A,
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if path:
            self._a_var.set(path)

    def _browse_facility(self) -> None:
        path = self._askdirectory(
            parent=self._top, title=_LABEL_FACILITY, mustexist=True
        )
        if path:
            self._facility_var.set(path)

    def _browse_output(self) -> None:
        path = self._askdirectory(parent=self._top, title=_LABEL_OUTPUT)
        if path:
            self._output_var.set(path)

    def _on_run(self) -> None:
        a = self._a_var.get().strip()
        facility = self._facility_var.get().strip()
        output = self._output_var.get().strip()

        if not a or not facility or not output:
            self._messagebox.showerror(_MSG_TITLE_INVALID_INPUT, _MSG_SELECT_ALL)
            return

        # 実行中はボタン disable
        self._btn_run.state(["disabled"])  # type: ignore[no-untyped-call]
        self._append_result("処理を開始します...\n")
        self._top.update()

        try:
            report = self._merge_fn(Path(a), Path(facility), Path(output))
        except FileNotFoundError as e:
            # PII 防御: FileNotFoundError.filename は UNC / 絶対パスを含みうるため
            # 画面には型名 + 汎用メッセージのみ、詳細は logger.exception で取得。
            logger.exception(
                "merge_facility FileNotFoundError: %s", type(e).__name__
            )
            self._append_result(
                "ERROR: ファイル/フォルダが見つかりません（詳細はログ参照）\n"
            )
            self._messagebox.showerror(
                _MSG_TITLE_ERROR,
                "指定したファイル / フォルダが見つかりませんでした。\n"
                "A.pdf のパス、事業所フォルダ、出力ルートを再確認してください。\n"
                f"\n{type(e).__name__}",
            )
            self._btn_run.state(["!disabled"])  # type: ignore[no-untyped-call]
            return
        except Exception as e:
            # 第三者例外は型名のみ、詳細は logger.exception 経路
            logger.exception("merge_facility failed: %s", type(e).__name__)
            self._append_result(f"ERROR ({type(e).__name__})\n")
            self._messagebox.showerror(
                _MSG_TITLE_ERROR,
                f"処理中にエラーが発生しました。\n詳細はログを確認してください。\n\n"
                f"{type(e).__name__}",
            )
            self._btn_run.state(["!disabled"])  # type: ignore[no-untyped-call]
            return

        self._render_report(report)
        self._result = FacilityMergerDialogResult(executed=True, report=report)
        self._btn_run.state(["!disabled"])  # type: ignore[no-untyped-call]

    def _render_report(self, report: FacilityMergeReport) -> None:
        """結果サマリを表示エリアに描画する（PII 防御: user_key のみ）。

        新仕様: 出力は事業所単位 1 ファイル `{facility_name}.pdf`。
        """
        lines: list[str] = []
        lines.append("=" * 50)
        lines.append(f"事業所: {report.facility_name}")
        lines.append(f"出力先: {report.output_dir}")
        lines.append("=" * 50)

        if report.success:
            output_file = f"{report.facility_name}.pdf"
            lines.append(
                f"結合 {len(report.success)} 名 → {output_file} "
                "(A→B→C 順で連結)"
            )
            for entry in report.success:
                lines.append(f"  ✓ {entry.user_key}")
        else:
            lines.append("結合対象なし（ABC 全揃いの利用者がいません）")

        if report.extraction_failed_pages:
            pages = ", ".join(str(p + 1) for p in report.extraction_failed_pages)
            lines.append(f"\n氏名抽出失敗（A.pdf ページ番号）: {pages}")

        excluded_total = (
            len(report.a_only)
            + len(report.b_missing)
            + len(report.c_missing)
            + len(report.a_missing)
            + len(report.ambiguous_bc_skipped)
        )
        if excluded_total > 0:
            lines.append(f"\n除外: {excluded_total} 名（出力 PDF に含まれません）")
        if report.a_only:
            lines.append(
                f"  ・A のみ（B/C 両方なし）: {', '.join(report.a_only)}"
            )
        if report.b_missing:
            lines.append(
                f"  ・B（計画書）なし: {', '.join(report.b_missing)}"
            )
        if report.c_missing:
            lines.append(
                f"  ・C（経過報告書）なし: {', '.join(report.c_missing)}"
            )
        if report.a_missing:
            lines.append(
                f"  ・A にマッチなし（B/C のみ存在）: {', '.join(report.a_missing)}"
            )
        if report.ambiguous_bc_skipped:
            lines.append(
                "  ・同姓重複 fail-safe（誤添付防止）: "
                f"{', '.join(report.ambiguous_bc_skipped)}"
            )
        if report.name_conflicts:
            lines.append(
                f"\n同姓コンフリクト（連番付与）: {', '.join(report.name_conflicts)}"
            )

        self._set_result_text("\n".join(lines) + "\n")

    def _append_result(self, text: str) -> None:
        self._result_text.configure(state="normal")
        self._result_text.insert("end", text)
        self._result_text.configure(state="disabled")
        self._result_text.see("end")

    def _set_result_text(self, text: str) -> None:
        self._result_text.configure(state="normal")
        self._result_text.delete("1.0", "end")
        self._result_text.insert("1.0", text)
        self._result_text.configure(state="disabled")

    def _on_close(self) -> None:
        self._top.destroy()

    def get_result(self) -> FacilityMergerDialogResult:
        return self._result

    def get_toplevel(self) -> tk.Toplevel:
        """テスト用: 内部 Toplevel を返す。"""
        return self._top
