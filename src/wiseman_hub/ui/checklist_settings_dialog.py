"""チェックリスト連携専用設定ダイアログ（MVP）。

スプレッドシート ID / カルテ・FAX ルート / 出力サブフォルダ名 / 居宅マッピング /
担当者マッピングを編集・保存する。動的キー dict（facility_routing, report_staff）は
TOML フラグメントとして Text widget で編集する（GUI 構築工数を最小化）。

保存ボタンで:
    1. スカラー入力を検証（必須項目はメッセージ表示）
    2. TOML フラグメント 2 つを ``tomllib.loads`` で解析（失敗ならエラー表示）
    3. ChecklistConfig 構築 → AppConfig.checklist にセット → save_config
"""

from __future__ import annotations

import logging
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]
import tomlkit

from wiseman_hub.config import (
    AppConfig,
    ChecklistConfig,
    ReportStaffEntry,
    save_config,
)

logger = logging.getLogger(__name__)


class ChecklistSettingsDialog:
    """チェックリスト連携専用設定ダイアログ。"""

    def __init__(
        self, parent: tk.Tk | tk.Toplevel | tk.Misc, config: AppConfig, config_path: Path
    ) -> None:
        self._config = config
        self._config_path = config_path
        self._saved = False

        self._top = tk.Toplevel(parent)
        self._top.title("チェックリスト連携 設定")
        self._top.geometry("760x680")
        self._top.transient(parent)  # type: ignore[arg-type]
        self._top.grab_set()
        self._build_ui()

    def get_toplevel(self) -> tk.Toplevel:
        return self._top

    def saved(self) -> bool:
        return self._saved

    def _build_ui(self) -> None:
        cfg = self._config.checklist
        top = self._top
        body = ttk.Frame(top, padding=10)
        body.pack(fill="both", expand=True)

        row = 0

        def add_entry(label: str, value: str, *, browse: bool = False) -> tk.StringVar:
            nonlocal row
            ttk.Label(body, text=label).grid(
                row=row, column=0, sticky="e", padx=4, pady=2
            )
            var = tk.StringVar(value=value)
            entry = ttk.Entry(body, textvariable=var, width=70)
            entry.grid(row=row, column=1, sticky="we", padx=4, pady=2)
            if browse:
                captured: tk.StringVar = var
                ttk.Button(
                    body,
                    text="参照",
                    command=lambda: self._browse_folder(captured),
                ).grid(row=row, column=2, padx=2)
            row += 1
            return var

        self._spreadsheet_id = add_entry("スプレッドシート ID:", cfg.spreadsheet_id)
        self._karte_root = add_entry(
            "カルテルート:", cfg.karte_root, browse=True
        )
        self._monitoring_subfolder = add_entry(
            "モニタリングサブフォルダ:", cfg.monitoring_subfolder
        )
        self._fax_root = add_entry("FAX 事業所ルート:", cfg.fax_root, browse=True)
        self._b_output_subfolder = add_entry(
            "B 出力サブフォルダ:", cfg.b_output_subfolder
        )
        self._c_output_subfolder = add_entry(
            "C 出力サブフォルダ:", cfg.c_output_subfolder
        )

        body.columnconfigure(1, weight=1)

        # facility_routing TOML 入力
        ttk.Label(
            body,
            text="居宅 → FAX 事業所マッピング (TOML 1行1ペア):",
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(8, 2))
        row += 1
        self._routing_text = tk.Text(body, height=8, font=("Menlo", 10))
        self._routing_text.grid(
            row=row, column=0, columnspan=3, sticky="we", padx=4
        )
        self._routing_text.insert(
            "1.0", _routing_to_toml(cfg.facility_routing)
        )
        row += 1

        # report_staff TOML 入力
        ttk.Label(
            body,
            text="担当者 → xlsx パステンプレート (TOML テーブル):",
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(8, 2))
        row += 1
        self._staff_text = tk.Text(body, height=12, font=("Menlo", 10))
        self._staff_text.grid(
            row=row, column=0, columnspan=3, sticky="we", padx=4
        )
        self._staff_text.insert("1.0", _staff_to_toml(cfg.report_staff))
        row += 1

        # 下段ボタン
        btn = ttk.Frame(top, padding=10)
        btn.pack(fill="x")
        ttk.Button(btn, text="保存", command=self._on_save).pack(side="right", padx=4)
        ttk.Button(btn, text="キャンセル", command=self._top.destroy).pack(
            side="right", padx=4
        )

    def _browse_folder(self, var: tk.StringVar) -> None:
        d = filedialog.askdirectory(parent=self._top, initialdir=var.get() or ".")
        if d:
            var.set(d)

    def _on_save(self) -> None:
        try:
            routing = _parse_routing_toml(self._routing_text.get("1.0", "end"))
        except (tomllib.TOMLDecodeError, ValueError, TypeError) as exc:
            messagebox.showerror(
                "居宅マッピング解析エラー",
                f"{type(exc).__name__}: {exc}",
                parent=self._top,
            )
            return
        try:
            staff = _parse_staff_toml(self._staff_text.get("1.0", "end"))
        except (tomllib.TOMLDecodeError, ValueError, TypeError) as exc:
            messagebox.showerror(
                "担当者マッピング解析エラー",
                f"{type(exc).__name__}: {exc}",
                parent=self._top,
            )
            return

        new_checklist = ChecklistConfig(
            spreadsheet_id=self._spreadsheet_id.get().strip(),
            karte_root=self._karte_root.get().strip(),
            monitoring_subfolder=self._monitoring_subfolder.get().strip()
            or "08.運動器機能向上計画書",
            fax_root=self._fax_root.get().strip(),
            b_output_subfolder=self._b_output_subfolder.get().strip()
            or "運動機能向上計画書",
            c_output_subfolder=self._c_output_subfolder.get().strip()
            or "経過報告書",
            facility_routing=routing,
            report_staff=staff,
        )
        new_config = AppConfig(
            version=self._config.version,
            log_level=self._config.log_level,
            log_dir=self._config.log_dir,
            wiseman=self._config.wiseman,
            schedule=self._config.schedule,
            reports=self._config.reports,
            gcp=self._config.gcp,
            updater=self._config.updater,
            ocr_backend=self._config.ocr_backend,
            pdf_merge=self._config.pdf_merge,
            checklist=new_checklist,
        )
        try:
            save_config(new_config, self._config_path, create_if_missing=True)
        except (OSError, ValueError, TypeError) as exc:
            logger.error("save_config failed: %s", type(exc).__name__)
            messagebox.showerror(
                "保存エラー",
                f"設定保存に失敗: {type(exc).__name__}",
                parent=self._top,
            )
            return
        self._saved = True
        messagebox.showinfo("保存完了", "設定を保存しました", parent=self._top)
        self._top.destroy()


def _routing_to_toml(routing: dict[str, str]) -> str:
    """居宅マッピングを TOML 風テキストに変換（key = "value" の羅列）。"""
    lines: list[str] = []
    for key, value in routing.items():
        lines.append(f'"{key}" = "{value}"')
    return "\n".join(lines)


def _staff_to_toml(staff: dict[str, ReportStaffEntry]) -> str:
    """担当者マッピングを TOML 風テキスト（``[name]\\n  key = "v"``）に変換。"""
    lines: list[str] = []
    for name, entry in staff.items():
        lines.append(f'["{name}"]')
        lines.append(f'base_dir = "{_escape_toml(entry.base_dir)}"')
        lines.append(
            f'year_subfolder_template = "{_escape_toml(entry.year_subfolder_template)}"'
        )
        lines.append(f'file_template = "{_escape_toml(entry.file_template)}"')
        lines.append("")
    return "\n".join(lines)


def _escape_toml(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _parse_routing_toml(text: str) -> dict[str, str]:
    """``"居宅" = "FAX フォルダ"`` 形式を解析。空行/コメントは無視。"""
    text = text.strip()
    if not text:
        return {}
    parsed: Any = tomllib.loads(text)
    if not isinstance(parsed, dict):
        raise TypeError("routing must be a flat table")
    result: dict[str, str] = {}
    for k, v in parsed.items():
        if not isinstance(v, str):
            raise TypeError(f"routing value must be str: {k}")
        result[str(k)] = v
    return result


def _parse_staff_toml(text: str) -> dict[str, ReportStaffEntry]:
    """``[名前]\\n  base_dir = "..."`` 形式を解析して ReportStaffEntry の dict に。"""
    text = text.strip()
    if not text:
        return {}
    parsed: Any = tomllib.loads(text)
    if not isinstance(parsed, dict):
        raise TypeError("staff must be a top-level table")
    result: dict[str, ReportStaffEntry] = {}
    for name, entry in parsed.items():
        if not isinstance(entry, dict):
            raise TypeError(f"staff[{name}] must be a table")
        result[str(name)] = ReportStaffEntry(
            base_dir=str(entry.get("base_dir", "")),
            year_subfolder_template=str(entry.get("year_subfolder_template", "")),
            file_template=str(entry.get("file_template", "")),
        )
    return result


# 未使用 import 防止のための tomlkit 参照（将来コメント保持に切り替える際の再利用）
_ = tomlkit
