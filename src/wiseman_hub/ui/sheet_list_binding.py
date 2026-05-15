"""B/C ダイアログ + launcher 同期サマリーで共通利用するシート一覧 cache binding。

Issue #190 (PR-δ v1) で C ダイアログに導入した sheet_list_cache の起動時
populate + 永続化 + sync info label 表示を helper として外出しし、
B ダイアログ / launcher / 将来追加される dialog から再利用できるようにする。

設計判断:
    - 軽量クラス (state holding) で ``config_path`` + ``get_spreadsheet_id`` を束ね、
      cache 場所 / cache key の組立を 1 箇所に集約 (caller の重複コード削減)。
    - Tk widget は caller が引数で渡す (helper は widget を保持しない)。
      テスト時の widget mock 容易性と、caller 側の lifecycle 管理を尊重するため。
    - すべての失敗経路 (config_path=None / spreadsheet_id 空 / cache miss / I/O 失敗)
      は False / 空文字 / no-op で完了し、UI 進行を阻害しない。
    - sheet_list_cache モジュールへの薄いラッパで、cache schema は変更しない
      (既存 cache ファイルとの後方互換維持)。
"""

from __future__ import annotations

import datetime as _dt
import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from wiseman_hub.cloud.sheet_list_cache import (
    cache_dir_for as _sheet_cache_dir_for,
)
from wiseman_hub.cloud.sheet_list_cache import (
    load as _load_sheet_cache,
)
from wiseman_hub.cloud.sheet_list_cache import (
    save as _save_sheet_cache,
)
from wiseman_hub.cloud.sync_label import format_synced_at_label

if TYPE_CHECKING:
    from tkinter import ttk

logger = logging.getLogger(__name__)


SpreadsheetIdProvider = Callable[[], str | None]
NowProvider = Callable[[], _dt.datetime]


_DEFAULT_LABEL_PREFIX = "シート一覧 最終更新"


class SheetListBinding:
    """シート一覧 cache の load / save / sync-label を束ねる stateless wrapper。

    各 dialog が直接 ``sheet_list_cache.load/save`` を呼ぶと、cache_dir 算出 /
    spreadsheet_id None ガード / fetched_at の format ロジックが各所で重複する。
    本クラスはこれらを 1 箇所に集約し、caller は短い 1 行呼出で利用可能。

    **状態保持しない**: cache 内容も fetched_at も内部にキャッシュせず、各メソッド
    呼出のたびに ``sheet_list_cache.load`` で disk から読み直す。これは config
    再読込で spreadsheet_id が変わったケースでも常に最新を返すため (state を持つと
    invalidate のタイミングを各 caller が考慮しなければならず DRY 化の目的に反する)。
    disk I/O コストは 1 回の JSON read のため UI thread でも許容範囲。

    Attributes:
        _config_path: 設定ファイルパス。``None`` の場合は全 API が no-op で完了する
            (test 環境や config 未確定状態での安全な fallback)。
        _get_spreadsheet_id: 現在の spreadsheet_id を返す callable。
            config 再読込で値が変わる可能性があるため、毎呼出で問合せる。
        _now_fn: 現在時刻 (tz-aware) を返す provider。テスト時の time freeze 用。
    """

    def __init__(
        self,
        config_path: Path | None,
        get_spreadsheet_id: SpreadsheetIdProvider,
        *,
        now_fn: NowProvider | None = None,
    ) -> None:
        self._config_path = config_path
        self._get_spreadsheet_id = get_spreadsheet_id
        self._now_fn: NowProvider = now_fn or (
            lambda: _dt.datetime.now(tz=_dt.UTC)
        )

    def populate_combo_on_open(
        self,
        combo: ttk.Combobox,
    ) -> int:
        """起動時 cache hit 時に combo の values を populate し選択 index を末尾にする。

        Args:
            combo: 月選択 Combobox。caller の責務で生存している widget を渡すこと。

        Returns:
            populate した sheet 件数。cache miss / config_path=None / spreadsheet_id
            未設定 / cache 空のいずれかなら ``0`` を返し combo は変更しない。
            caller は戻り値で「cache hit したか」を判定して status_var の文言を
            分岐できる (例: "シート一覧 (キャッシュ N 件) - 最新化は..." vs 既定文言)。
        """
        if self._config_path is None:
            return 0
        spreadsheet_id = self._get_spreadsheet_id()
        if not spreadsheet_id:
            return 0
        cache_dir = _sheet_cache_dir_for(self._config_path)
        cached = _load_sheet_cache(cache_dir, spreadsheet_id)
        if cached is None or not cached.names:
            return 0
        combo["values"] = cached.names
        combo.current(len(cached.names) - 1)
        return len(cached.names)

    def save_after_fetch(self, sheet_names: list[str]) -> None:
        """Drive API fetch 完了後に cache を永続化する。

        config_path=None / spreadsheet_id 未設定なら no-op。
        I/O 失敗時は sheet_list_cache.save 内部で warn-only に処理され例外は伝播しない。
        """
        if self._config_path is None:
            return
        spreadsheet_id = self._get_spreadsheet_id()
        if not spreadsheet_id:
            return
        cache_dir = _sheet_cache_dir_for(self._config_path)
        _save_sheet_cache(cache_dir, spreadsheet_id, sheet_names)

    def read_fetched_at(self) -> _dt.datetime | None:
        """sync_label 用に現在 cache の fetched_at を返す。

        Returns:
            tz-aware datetime: cache 存在 + 有効な fetched_at が読めた場合。
            ``None``: config_path=None / spreadsheet_id 未設定 / cache miss /
            parse 失敗 / 旧 schema (fetched_at 欠落) のいずれか。
        """
        if self._config_path is None:
            return None
        spreadsheet_id = self._get_spreadsheet_id()
        if not spreadsheet_id:
            return None
        cache_dir = _sheet_cache_dir_for(self._config_path)
        cached = _load_sheet_cache(cache_dir, spreadsheet_id)
        return cached.fetched_at if cached is not None else None

    def format_sync_label(self, *, prefix: str = _DEFAULT_LABEL_PREFIX) -> str:
        """sync info label 用の表示文字列を組み立てる。

        例: ``"シート一覧 最終更新: 5/15 14:30 (3 分前)"``
            ``"シート一覧 最終更新: 不明"`` (cache 不在時)
        """
        fetched_at = self.read_fetched_at()
        return f"{prefix}: {format_synced_at_label(fetched_at, self._now_fn())}"

    def format_sync_label_with_error(
        self,
        err_type: str,
        *,
        prefix: str = _DEFAULT_LABEL_PREFIX,
    ) -> str:
        """更新失敗時の sync info label (既存 cache + 失敗マーカー併記)。

        Issue #238 Phase 1 review HIGH-1 の対応で C ダイアログに導入した文言と
        統一する。background 更新失敗時に sync_info が古いまま据え置かれて
        ユーザーが「最新化されている」と誤認するのを防ぐ。
        """
        fetched_at = self.read_fetched_at()
        label = format_synced_at_label(fetched_at, self._now_fn())
        return f"{prefix}: {label} ※更新失敗 ({err_type})"
