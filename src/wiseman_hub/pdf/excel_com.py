"""Excel COM ラッパ: xlsx の指定シート 1 ページ目を PDF 化する（MVP）。

実装方針:
    - Protocol ``ExcelExporter`` で抽象化
    - Windows: pywin32 + Excel.Application（実機 Excel 必須）
    - macOS / Linux: MockExcelExporter（テスト/開発用、空 PDF を出力）

Excel COM の挙動:
    - ``Workbook.Worksheets("シート名").Select()`` → ``ActiveSheet.PageSetup.PrintArea``
    - ``ActiveSheet.ExportAsFixedFormat(0, "<path>", From=1, To=1)`` で 1 ページ目のみ出力
    - 0 = xlTypePDF
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class ExcelExporter(Protocol):
    """xlsx の指定シート 1 ページ目を PDF として書き出す抽象。"""

    def export_first_page(
        self, xlsx_path: Path, sheet_name: str, output_pdf: Path
    ) -> None:
        ...

    def close(self) -> None:
        ...


class Win32ExcelExporter:
    """pywin32 を使った Excel 実体経由の PDF 化（Windows 限定）。

    Workbook を逐次開閉する単純実装（MVP）。多数件処理時はパフォーマンスに難があるが、
    検証段階では問題視しない（必要なら後段でセッション保持に最適化）。
    """

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Win32ExcelExporter requires Windows")
        # Lazy import: macOS では win32com 自体が無い
        import win32com.client  # noqa: F401  # type: ignore[import-not-found,unused-ignore]

        self._win32com: Any = win32com.client
        self._app: Any = None

    def _ensure_app(self) -> Any:
        if self._app is None:
            self._app = self._win32com.DispatchEx("Excel.Application")
            self._app.Visible = False
            self._app.DisplayAlerts = False
        return self._app

    def export_first_page(
        self, xlsx_path: Path, sheet_name: str, output_pdf: Path
    ) -> None:
        app = self._ensure_app()
        wb = app.Workbooks.Open(str(xlsx_path), ReadOnly=True)
        try:
            try:
                ws = wb.Worksheets(sheet_name)
            except Exception as exc:
                raise ValueError(
                    f"Sheet not found in xlsx: {sheet_name}"
                ) from exc
            ws.Select()
            output_pdf.parent.mkdir(parents=True, exist_ok=True)
            # xlTypePDF = 0, From=1, To=1 で 1 ページ目のみ
            ws.ExportAsFixedFormat(0, str(output_pdf), From=1, To=1)
        finally:
            wb.Close(SaveChanges=False)

    def close(self) -> None:
        if self._app is not None:
            try:
                self._app.Quit()
            except Exception:
                logger.exception("Excel.Quit failed")
            self._app = None


class MockExcelExporter:
    """macOS / テスト環境用。export 呼び出しの記録と空 PDF 生成のみ。"""

    def __init__(self) -> None:
        self.calls: list[tuple[Path, str, Path]] = []

    def export_first_page(
        self, xlsx_path: Path, sheet_name: str, output_pdf: Path
    ) -> None:
        self.calls.append((xlsx_path, sheet_name, output_pdf))
        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        # 最小有効 PDF（pymupdf 等で開ける形は不問、shutil.copy2 と同じ扱いで十分）
        output_pdf.write_bytes(
            b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
        )

    def close(self) -> None:
        pass


def create_exporter() -> ExcelExporter:
    """OS に応じて適切な ExcelExporter を返す。"""
    if sys.platform == "win32":
        return Win32ExcelExporter()
    logger.warning("MockExcelExporter selected (non-Windows): xlsx → PDF will be a placeholder")
    return MockExcelExporter()
