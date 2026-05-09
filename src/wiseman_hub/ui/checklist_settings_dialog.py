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
        ttk.Button(
            btn,
            text="環境スキャン → GCP 同期",
            command=self._on_scan_env,
        ).pack(side="left", padx=4)
        ttk.Button(
            btn,
            text="対照表 → GCP へ送信",
            command=self._on_push_routing,
        ).pack(side="left", padx=4)
        ttk.Button(
            btn,
            text="GCP から対照表を取得",
            command=self._on_pull_routing,
        ).pack(side="left", padx=4)
        ttk.Button(
            btn,
            text="GCP から担当者を取得",
            command=self._on_pull_staff,
        ).pack(side="left", padx=4)
        ttk.Button(btn, text="保存", command=self._on_save).pack(side="right", padx=4)
        ttk.Button(btn, text="キャンセル", command=self._top.destroy).pack(
            side="right", padx=4
        )

    def _browse_folder(self, var: tk.StringVar) -> None:
        d = filedialog.askdirectory(parent=self._top, initialdir=var.get() or ".")
        if d:
            var.set(d)

    def _on_scan_env(self) -> None:
        """FAX 事業所ルート配下のフォルダ名を GCS にアップロードする。

        AI による居宅マッピング自動生成のためのデータ提供。スキャン対象は
        現在の入力欄の `fax_root` 値 (保存前でも可)。
        """
        fax_root_str = self._fax_root.get().strip()
        if not fax_root_str:
            messagebox.showerror(
                "FAX ルート未設定",
                "FAX 事業所ルートを先に入力してください",
                parent=self._top,
            )
            return
        from pathlib import Path

        from wiseman_hub.cloud.env_scanner import scan_and_upload

        try:
            result = scan_and_upload(self._config.gcp, Path(fax_root_str))
        except (FileNotFoundError, NotADirectoryError) as exc:
            messagebox.showerror(
                "スキャン失敗",
                f"{type(exc).__name__}: {exc}",
                parent=self._top,
            )
            return
        except Exception as exc:
            logger.error("env scan upload failed: %s", type(exc).__name__)
            messagebox.showerror(
                "GCS アップロード失敗",
                f"{type(exc).__name__}: {exc}",
                parent=self._top,
            )
            return
        messagebox.showinfo(
            "GCP 同期完了",
            f"{result.folder_count} 件のフォルダを送信しました\n"
            f"GCS URI: {result.gcs_uri}",
            parent=self._top,
        )

    def _on_push_routing(self) -> None:
        """Text widget の対照表を JSON 化して GCS にアップロードする。

        過去失敗対策（feedback_external_api_ok_actual_ng.md）:
            push 直後に pull で読み戻し、内容が一致するまで「成功」と通知しない。
            push 200 OK でも実態 NG（書き込みが反映されない / 別ユーザーの上書き）
            のケースを構造的に検出する。
        """
        try:
            routing = _parse_routing_toml(self._routing_text.get("1.0", "end"))
        except (tomllib.TOMLDecodeError, ValueError, TypeError) as exc:
            messagebox.showerror(
                "対照表 解析エラー",
                f"{type(exc).__name__}: {exc}",
                parent=self._top,
            )
            return
        if not routing:
            messagebox.showwarning(
                "対照表 空",
                "対照表が空です。1 行以上入力してから送信してください。",
                parent=self._top,
            )
            return
        from wiseman_hub.cloud.mapping_sync import (
            MappingConfigError,
            MappingSyncError,
            pull_routing,
            push_routing,
        )

        try:
            uri = push_routing(self._config.gcp, routing)
        except MappingConfigError as exc:
            messagebox.showerror(
                "GCP 設定不足",
                f"{exc}\n\n設定ダイアログで [gcp] 項目を入力するか、"
                "config/default.toml を確認してください。",
                parent=self._top,
            )
            return
        except MappingSyncError as exc:
            messagebox.showerror(
                "GCP 送信失敗",
                f"{exc}",
                parent=self._top,
            )
            return

        # 閉ループ確認: push 直後に pull で読み戻して一致を確認
        try:
            verified = pull_routing(self._config.gcp)
        except MappingSyncError as exc:
            messagebox.showwarning(
                "送信検証失敗",
                f"送信は成功しましたが読み戻し検証に失敗:\n{exc}\n"
                "GCS 側の状態を確認してください。",
                parent=self._top,
            )
            return
        if verified != routing:
            messagebox.showwarning(
                "送信検証 不一致",
                f"送信内容 {len(routing)} 件と読み戻し {len(verified)} 件が一致しません。"
                "別ユーザーの並行更新かもしれません。",
                parent=self._top,
            )
            return
        messagebox.showinfo(
            "GCP 送信完了",
            f"{len(routing)} 件を送信し、読み戻し検証 OK\nGCS URI: {uri}",
            parent=self._top,
        )

    def _on_pull_routing(self) -> None:
        """GCS から最新対照表を取得し Text widget を上書きする。

        既存値が非空のときは上書き確認ダイアログを表示。保存ボタンは別途押下必須
        （取得 = 編集枠への反映、永続化は保存で確定）。
        """
        from wiseman_hub.cloud.mapping_sync import (
            MappingConfigError,
            MappingNotFoundError,
            MappingSyncError,
            pull_routing,
        )

        # 既存値が非空なら上書き確認
        # 過去失敗対策（codex review MEDIUM-3）: parse 失敗時は黙って空扱いにせず、
        # 「壊れた編集データを失う」ことを明示的に確認する。
        text = self._routing_text.get("1.0", "end")
        try:
            current = _parse_routing_toml(text)
            parse_failed = False
        except (tomllib.TOMLDecodeError, ValueError, TypeError):
            current = {}
            parse_failed = bool(text.strip())
        if parse_failed and not messagebox.askyesno(
            "編集中の対照表が解析不能",
            "現在の編集内容を解析できません。\n"
            "GCP からの取得結果で上書きしますか？\n"
            "（既存編集内容は失われます）",
            parent=self._top,
        ):
            return
        if current and not messagebox.askyesno(
            "上書き確認",
            f"現在 {len(current)} 件の対照表が編集中です。"
            "GCP からの取得結果で上書きしますか？",
            parent=self._top,
        ):
            return

        try:
            routing = pull_routing(self._config.gcp)
        except MappingConfigError as exc:
            messagebox.showerror(
                "GCP 設定不足",
                f"{exc}\n\n設定ダイアログで [gcp] 項目を入力するか、"
                "config/default.toml を確認してください。",
                parent=self._top,
            )
            return
        except MappingNotFoundError:
            messagebox.showinfo(
                "対照表 未登録",
                "GCP に対照表がまだ登録されていません。\n"
                "1) 編集枠に対照表を入力\n"
                "2) 「対照表 → GCP へ送信」ボタンで送信\n"
                "の順で初回登録してください。",
                parent=self._top,
            )
            return
        except MappingSyncError as exc:
            messagebox.showerror(
                "GCP 取得失敗",
                f"{exc}",
                parent=self._top,
            )
            return
        self._routing_text.delete("1.0", "end")
        self._routing_text.insert("1.0", _routing_to_toml(routing))
        messagebox.showinfo(
            "GCP 取得完了",
            f"{len(routing)} 件を取得しました\n保存ボタンで永続化してください",
            parent=self._top,
        )

    def _on_pull_staff(self) -> None:
        """GCS から最新担当者マッピングを取得し Text widget を上書きする（PR-β v1）。

        既存値が非空のときは上書き確認ダイアログを表示。保存ボタンは別途押下必須
        （取得 = 編集枠への反映、永続化は保存で確定）。pull_routing と同じ UX。
        """
        from wiseman_hub.cloud.mapping_sync import (
            MappingConfigError,
            MappingNotFoundError,
            MappingSyncError,
            pull_report_staff,
        )

        # 既存編集値が解析可能か検査して上書き確認の文言を分岐
        text = self._staff_text.get("1.0", "end")
        try:
            current = _parse_staff_toml(text)
            parse_failed = False
        except (tomllib.TOMLDecodeError, ValueError, TypeError):
            current = {}
            parse_failed = bool(text.strip())
        if parse_failed and not messagebox.askyesno(
            "編集中の担当者マッピングが解析不能",
            "現在の編集内容を解析できません。\n"
            "GCP からの取得結果で上書きしますか？\n"
            "（既存編集内容は失われます）",
            parent=self._top,
        ):
            return
        if current and not messagebox.askyesno(
            "上書き確認",
            f"現在 {len(current)} 件の担当者マッピングが編集中です。"
            "GCP からの取得結果で上書きしますか？",
            parent=self._top,
        ):
            return

        try:
            staff = pull_report_staff(self._config.gcp)
        except MappingConfigError as exc:
            messagebox.showerror(
                "GCP 設定不足",
                f"{exc}\n\n設定ダイアログで [gcp] 項目を入力するか、"
                "config/default.toml を確認してください。",
                parent=self._top,
            )
            return
        except MappingNotFoundError:
            messagebox.showinfo(
                "担当者マッピング 未登録",
                "GCP に担当者マッピングがまだ登録されていません。\n"
                "初回は管理者が `scripts/init_gcs_report_staff.py` 等で\n"
                "GCS に投入する必要があります。",
                parent=self._top,
            )
            return
        except MappingSyncError as exc:
            messagebox.showerror(
                "GCP 取得失敗",
                f"{exc}",
                parent=self._top,
            )
            return
        self._staff_text.delete("1.0", "end")
        self._staff_text.insert("1.0", _staff_to_toml(staff))
        messagebox.showinfo(
            "GCP 取得完了",
            f"{len(staff)} 件を取得しました\n保存ボタンで永続化してください",
            parent=self._top,
        )

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
            or "運動器機能向上計画書",
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
    """居宅マッピングを TOML 風テキストに変換（key = "value" の羅列）。

    過去失敗対策（codex review MEDIUM-2）: key/value に ``"`` や ``\\`` が混入した場合
    に TOML として再パース不能になるため、両側を ``_escape_toml`` で escape する。
    """
    lines: list[str] = []
    for key, value in routing.items():
        lines.append(f'"{_escape_toml(key)}" = "{_escape_toml(value)}"')
    return "\n".join(lines)


def _staff_to_toml(staff: dict[str, ReportStaffEntry]) -> str:
    """担当者マッピングを TOML 風テキスト（``[name]\\n  key = "v"``）に変換。

    PR #179 (PR-α v3) で追加された ``suggest_patterns`` (list[str]) も書き出す。
    deprecated フィールド (``year_subfolder_template`` / ``file_template``) は
    値が非空のときのみ書き出す（後方互換）。
    """
    lines: list[str] = []
    for name, entry in staff.items():
        lines.append(f'["{name}"]')
        lines.append(f'base_dir = "{_escape_toml(entry.base_dir)}"')
        if entry.suggest_patterns:
            inner = ", ".join(
                f'"{_escape_toml(p)}"' for p in entry.suggest_patterns
            )
            lines.append(f"suggest_patterns = [{inner}]")
        else:
            lines.append("suggest_patterns = []")
        # deprecated 後方互換: 値が空なら出力しない（新規入力では suggest_patterns を使う）
        if entry.year_subfolder_template:
            lines.append(
                f'year_subfolder_template = "{_escape_toml(entry.year_subfolder_template)}"'
            )
        if entry.file_template:
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
    """``[名前]\\n  base_dir = "..."`` 形式を解析して ReportStaffEntry の dict に。

    PR #179 (PR-α v3) で追加された ``suggest_patterns`` (list[str]) も読み取る。
    suggest_patterns 要素が文字列でない場合は TypeError を送出（保存前に GUI が検知）。
    """
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
        suggest_raw = entry.get("suggest_patterns", [])
        if not isinstance(suggest_raw, list):
            raise TypeError(
                f"staff[{name}].suggest_patterns must be a list of strings"
            )
        suggest_patterns: list[str] = []
        for element in suggest_raw:
            if not isinstance(element, str):
                raise TypeError(
                    f"staff[{name}].suggest_patterns elements must be strings"
                )
            suggest_patterns.append(element)
        result[str(name)] = ReportStaffEntry(
            base_dir=str(entry.get("base_dir", "")),
            suggest_patterns=suggest_patterns,
            year_subfolder_template=str(entry.get("year_subfolder_template", "")),
            file_template=str(entry.get("file_template", "")),
        )
    return result


# 未使用 import 防止のための tomlkit 参照（将来コメント保持に切り替える際の再利用）
_ = tomlkit
