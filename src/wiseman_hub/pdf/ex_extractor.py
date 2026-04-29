"""Wiseman ``.ex_`` ファイル PDF 抽出 + 事業所フォルダ振り分け core モジュール (PR3)。

`scripts/process_ex_files.py` (旧 CLI 専用、262 行) のロジックをデスクトップアプリ
統合可能な形に移植 + 拡張する。SFX (WinSFX32 LZH 自己解凍 EXE) 実行を ``SfxAdapter``
Protocol で抽象化し、Windows 実装と macOS テスト用 fake を分離することで全フローを
macOS 単体テストでカバー可能にする。

## 設計の核

### マッチング戦略
旧 ``find_subfolder_match`` (filename 単純包含のみ) を **PR2 ``resolve_facility``** へ
完全置換する。alias 優先 + 語境界要求 + AMBIGUOUS 細分により誤配布を構造的に低減。
AMBIGUOUS / UNMATCHED は SFX 抽出も skip し ``pending_manual`` として保持
(PR4 UI で手動振り分け)。

### adapter 設計
``SfxAdapter`` Protocol で Windows 固有処理 (pywinauto) を core から完全分離。
``WindowsSfxAdapter`` constructor で platform check、``pywinauto`` import は
extract_pdf 内で **遅延** することで macOS の ``--help`` / dry-run 動作を保証
(Codex セカンドオピニオン MEDIUM-2 対応)。

### 構造化結果型
``ExtractionItem.status`` (StrEnum) + ``error_code`` (StrEnum) + ``cleanup_warning``
で PR4 UI 分岐の単一判定ポイントを提供。adapter 例外時の部分生成 PDF は
``PARTIAL_OUTPUT`` ステータス + ``partial_outputs`` フィールドで表現し、
**自動移動を構造的に禁止** する (Codex HIGH-6 対応)。

### CLI 互換境界
``scripts/process_ex_files.py`` 薄ラッパーは **CLI インターフェース互換**
(argv パターン / デフォルトパス / stderr フォーマット) を維持しつつ、振り分け
ロジックは新 resolver に統一する。pending 発生時は exit code 2 で現場に明示的
通知 (Codex HIGH-1, HIGH-3 対応)。

## PII 保護方針

- 本モジュール内 ``logger`` 呼び出しは ``filename`` のみ渡す
- フルパス / 事業所名 / matched_facility / candidates / 抽出 PDF 名 を logger に渡さない
- ``ExtractionItem.error_detail`` は PII-safe な短い文字列 (filename 含むのみ可、
  事業所名・full path は禁止)
- 呼び出し元 (CLI / PR4 UI) が ``ExtractionItem`` 経由で表示する場合の PII 制御は
  呼び出し元の責務 (本モジュールは構造化情報を返すだけ)
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Final, Protocol

from wiseman_hub.pdf.facility_resolver import (
    ResolveReason,
    ResolveResult,
    find_orphan_alias_canonicals,
    resolve_facility,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Status / Error code 定義
# ---------------------------------------------------------------------------


class ExtractionStatus(StrEnum):
    """``extract_one`` の結果ステータス。

    PR4 UI が単一判定ポイントとして利用する。``ResolveResult.status`` とは
    独立 (resolver 結果に加えて抽出 / 移動の成否を表現)。
    """

    SUCCESS = "success"  # CONFIRMED + 抽出 + 移動すべて成功
    SKIPPED_AMBIGUOUS = "skipped_ambiguous"  # AMBIGUOUS で抽出スキップ
    SKIPPED_UNMATCHED = "skipped_unmatched"  # UNMATCHED で抽出スキップ
    EXTRACT_FAILED = "extract_failed"  # SFX 失敗 / PDF 検出失敗
    PARTIAL_OUTPUT = "partial_output"  # adapter 例外だが PDF 一部生成 (移動なし)
    MOVE_FAILED = "move_failed"  # 抽出成功だが移動失敗 (衝突等)


class ExtractionErrorCode(StrEnum):
    """``ExtractionItem.error_code`` / ``cleanup_warning`` の分類。

    PII-safe な enum 値で UI 分岐 / 統計集計を可能にする
    (詳細メッセージは ``error_detail`` を参照)。
    """

    SFX_LAUNCH_FAILED = "sfx_launch_failed"
    SFX_TIMEOUT = "sfx_timeout"
    NO_PDF_PRODUCED = "no_pdf_produced"
    UNEXPECTED_PDF_NAMING = "unexpected_pdf_naming"
    QUARANTINE_FAILED = "quarantine_failed"
    QUARANTINE_RESTORE_FAILED = "quarantine_restore_failed"
    MOVE_CONFLICT = "move_conflict"
    MOVE_IO_ERROR = "move_io_error"
    COPY_FAILED = "copy_failed"
    CLEANUP_FAILED = "cleanup_failed"
    UNSUPPORTED_PLATFORM = "unsupported_platform"
    UNEXPECTED = "unexpected"


# ---------------------------------------------------------------------------
# 例外
# ---------------------------------------------------------------------------


class UnsupportedSfxPlatformError(RuntimeError):
    """SFX 実行が当該プラットフォームで未サポートの場合に投げる業務例外。

    ``NotImplementedError`` ではなく独自例外を採用する理由
    (Codex MEDIUM-2 対応): NotImplementedError は Python 抽象メソッドの
    未実装シグナルとして広く使われており、業務エラーとの区別がつきにくい。
    独自例外なら CLI / UI 層で ``except UnsupportedSfxPlatformError`` で
    確実に捕捉でき、エンドユーザーへの平易な日本語メッセージ変換が容易。
    """


class SfxExtractionFailed(RuntimeError):
    """SFX 抽出失敗を type-safe に伝える内部例外。

    ``adapter.extract_pdf`` の実装側 (Windows / Fake) が失敗時に投げる。
    ``partial_outputs`` フィールドで「失敗したが PDF が一部生成された」
    ケースを表現できる (Codex HIGH-6 対応)。
    """

    def __init__(
        self,
        code: ExtractionErrorCode,
        detail: str = "",
        partial_outputs: Sequence[Path] = (),
    ) -> None:
        super().__init__(f"{code.value}: {detail}")
        self.code = code
        self.detail = detail
        self.partial_outputs: tuple[Path, ...] = tuple(partial_outputs)


# ---------------------------------------------------------------------------
# Adapter Protocol + 実装
# ---------------------------------------------------------------------------


class SfxAdapter(Protocol):
    """SFX 自己解凍 EXE 実行 adapter インターフェース。

    Windows 固有処理 (pywinauto / subprocess) を core から完全分離するための
    境界。実装は ``WindowsSfxAdapter`` (実機) と ``FakeSfxAdapter`` (テスト用)。
    Protocol を採用 (ABC ではない) することで fake 側で継承不要、テスト容易。
    """

    def extract_pdf(
        self, exe_path: Path, watch_dirs: Sequence[Path]
    ) -> Sequence[Path]:
        """SFX EXE を実行し、``watch_dirs`` に新規生成された PDF を返す。

        Raises:
            SfxExtractionFailed: 実行失敗 / タイムアウト / PDF 未生成等。
                ``partial_outputs`` に部分生成 PDF があれば含めて投げる
        """
        ...


class WindowsSfxAdapter:
    """Windows 実機での SFX 自己解凍 EXE 実行 adapter。

    旧 ``scripts/process_ex_files.py`` の ``_extract_with_exe`` /
    ``_click_sfx_dialog`` ロジックを移植。挙動互換のため timeout 後に PDF が
    検出された場合は成功扱い (旧版踏襲、現行運用維持)。

    macOS では構築時点で ``UnsupportedSfxPlatformError``。``pywinauto`` import
    は ``extract_pdf`` 内で **遅延** することで macOS の dry-run / ``--help``
    動作を保証 (Codex MEDIUM-2 対応)。
    """

    # SFX プロセスの最大待ち時間 (旧版互換: 60 ループ × 0.5s = 30s)
    _MAX_WAIT_TICKS: int = 60
    _TICK_INTERVAL_SEC: float = 0.5
    # ダイアログ操作を試みる tick 範囲 (旧版互換: 1-10s 相当)
    _DIALOG_TICK_START: int = 2
    _DIALOG_TICK_END: int = 20

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise UnsupportedSfxPlatformError(
                "WindowsSfxAdapter requires sys.platform == 'win32'"
            )

    def extract_pdf(
        self, exe_path: Path, watch_dirs: Sequence[Path]
    ) -> Sequence[Path]:
        """SFX 実行 + ``<exe_path.stem>.pdf`` (= ex_file の stem) の検出。

        誤配布防止 (quarantine 方式) の前提:
        - 呼び出し元 ``extract_one`` が SFX 実行前に ex_file.parent の同名 PDF を
          quarantine 退避済 (古い残骸を成功扱いで拾わない構造保証)
        - 本 adapter は「SFX 実行で得られた target」のみ返す責務に専念
        - basename 完全一致 (``<stem>.pdf`` / ``<stem>.PDF``) のみ採用、
          無関係 PDF は拾わない

        変則命名検出:
        - ``<stem>.pdf`` が見つからず ``<stem>_*.pdf`` のみ存在する場合、
          ``UNEXPECTED_PDF_NAMING`` で fail-fast (静かな ``NO_PDF_PRODUCED``
          より診断性 + 運用者通知性が高い)
        """
        target_stem = exe_path.stem  # ex_file.stem と同じ
        # SFX 起動前 snapshot: ex_file.parent のみ取る (誤配布リスクを最小化)。
        # quarantine で退避済の同名 PDF は snapshot に含まれない (`.quarantine-`
        # prefix を除外) ため、新規生成を確実に差分として検出できる。
        before_snapshot = self._snapshot_pdfs([exe_path.parent])

        try:
            proc = subprocess.Popen(  # noqa: S603 (信頼された .exe のみ)
                [str(exe_path)],
                cwd=str(exe_path.parent),
            )
        except OSError as e:
            # PII 防御 (Codex HIGH-C): OSError.str() は Windows で full path を含むため
            # 例外型名のみを伝搬する
            raise SfxExtractionFailed(
                ExtractionErrorCode.SFX_LAUNCH_FAILED, type(e).__name__
            ) from e

        dialog_clicked = False
        try:
            for i in range(self._MAX_WAIT_TICKS):
                time.sleep(self._TICK_INTERVAL_SEC)

                if (
                    not dialog_clicked
                    and self._DIALOG_TICK_START <= i <= self._DIALOG_TICK_END
                ):
                    dialog_clicked = self._click_sfx_dialog(proc.pid)

                if proc.poll() is not None:
                    # SFX 正常終了 → 書き込み完了を待ってから target 検出
                    time.sleep(1)
                    return self._resolve_target_or_raise(
                        target_stem, watch_dirs, exe_path.parent, before_snapshot
                    )
        finally:
            if proc.poll() is None:
                self._terminate_proc(proc)

        # タイムアウト後の最終チェック (旧版互換: 検出されれば成功扱い)
        time.sleep(1)
        try:
            return self._resolve_target_or_raise(
                target_stem, watch_dirs, exe_path.parent, before_snapshot
            )
        except SfxExtractionFailed as e:
            # target が無く変則命名も無いケースのみ SFX_TIMEOUT に格上げ
            # (UNEXPECTED_PDF_NAMING 等は元の error_code を維持)
            if e.code is ExtractionErrorCode.NO_PDF_PRODUCED:
                timeout_sec = int(
                    self._MAX_WAIT_TICKS * self._TICK_INTERVAL_SEC
                )
                raise SfxExtractionFailed(
                    ExtractionErrorCode.SFX_TIMEOUT,
                    f"no pdf produced within {timeout_sec}s",
                ) from e
            # SFX が遅延した上で変則命名 PDF を出した可能性: 後段の運用診断のために
            # タイムアウト経路を踏んだことをログに残す (PII safe: count のみ)。
            logger.warning(
                "%s: timeout-fallback found %s, count=%d",
                target_stem,
                e.code.value,
                len(e.partial_outputs),
            )
            raise

    @staticmethod
    def _snapshot_pdfs(dirs: Sequence[Path]) -> set[Path]:
        """指定ディレクトリ群の現在の *.pdf 集合を返す (`.quarantine-` は除外)。

        OSError は警告ログのみで握りつぶし、その dir は空集合扱い (ネットワーク
        ドライブの瞬断等で SFX 実行自体は止めない)。
        """
        snapshot: set[Path] = set()
        for d in dirs:
            try:
                if not d.exists():
                    continue
                for p in d.iterdir():
                    if not p.is_file():
                        continue
                    if p.suffix.lower() != ".pdf":
                        continue
                    if _QUARANTINE_PREFIX in p.name:
                        continue
                    snapshot.add(p)
            except OSError as exc:
                logger.warning(
                    "snapshot iterdir failed: %s", type(exc).__name__
                )
                continue
        return snapshot

    @classmethod
    def _resolve_target_or_raise(
        cls,
        target_stem: str,
        watch_dirs: Sequence[Path],
        primary_dir: Path,
        before_snapshot: set[Path],
    ) -> Sequence[Path]:
        """target stem に一致する PDF を返す。なければ snapshot 差分 → 変則命名 → raise。

        検出順序:
        1. ``<stem>.pdf`` が watch_dirs にあれば 1 件返す (basename 完全一致)
        2. ``primary_dir`` (= ex_file.parent) で SFX 起動後に **新規出現** した
           PDF を検出 (quarantine 退避済の古い PDF は差分から除外される)
           - 1 件 → 採用 (SFX が任意名で出すケース対応、実機 PDF 名 ≠ ex_file.stem)
           - 2 件以上 → 最新 mtime を採用 + 警告ログ (PII safe: count のみ)
        3. ``<stem>_*.pdf`` 等の変則命名 → UNEXPECTED_PDF_NAMING で raise
        4. 何も見つからなければ NO_PDF_PRODUCED で raise

        誤配布リスク評価:
        - quarantine 方式で同名 pre-existing は退避済 → snapshot 差分に古い残骸は混入しない
        - primary_dir は ``ex_file.parent`` のみ (Desktop / Downloads は基本対象外、
          ユーザーの手動 DL 等を巻き込まない)
        """
        target = find_target_pdf(target_stem, watch_dirs)
        if target is not None:
            return [target]

        after = cls._snapshot_pdfs([primary_dir])
        new_pdfs = sorted(after - before_snapshot)
        if len(new_pdfs) == 1:
            logger.info(
                "%s: snapshot-diff fallback matched 1 new pdf", target_stem
            )
            return [new_pdfs[0]]
        if len(new_pdfs) >= 2:
            try:
                latest = max(new_pdfs, key=lambda p: p.stat().st_mtime)
            except OSError:
                latest = new_pdfs[0]
            logger.warning(
                "%s: snapshot-diff found %d new pdfs, picked latest by mtime",
                target_stem,
                len(new_pdfs),
            )
            return [latest]

        unexpected = find_unexpected_naming_pdfs(target_stem, watch_dirs)
        if unexpected:
            raise SfxExtractionFailed(
                ExtractionErrorCode.UNEXPECTED_PDF_NAMING,
                f"unexpected naming, count={len(unexpected)}",
                partial_outputs=unexpected,
            )
        raise SfxExtractionFailed(
            ExtractionErrorCode.NO_PDF_PRODUCED, "no pdf produced"
        )

    @staticmethod
    def _terminate_proc(proc: subprocess.Popen[bytes]) -> None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                # driver hang 等で kill 不可なケース、メインフロー継続を優先
                logger.warning("SFX process kill timeout (pid=%d)", proc.pid)

    def _click_sfx_dialog(self, proc_pid: int) -> bool:
        """WinSFX32 ダイアログの OK ボタンを自動クリック。

        ``pywinauto`` は **遅延 import** (macOS で本 adapter は構築不可だが、
        将来 pyinstaller 等で import 解析が走るケースのため最小依存に留める)。
        """
        try:
            from pywinauto import Application
        except ImportError:
            logger.warning("pywinauto unavailable; SFX dialog auto-click skipped")
            return False

        try:
            app = Application(backend="uia").connect(process=proc_pid, timeout=3)
            dlg = app.top_window()

            for btn_title in ("OK", "OK(O)", "&OK"):
                try:
                    btn = dlg.child_window(title=btn_title, control_type="Button")
                    if btn.exists(timeout=1):
                        btn.click_input()
                        return True
                except Exception:  # noqa: BLE001 (pywinauto 内部例外を握り潰し次手段へ)
                    continue

            try:
                btn = dlg.child_window(title_re=r".*OK.*", control_type="Button")
                if btn.exists(timeout=1):
                    btn.click_input()
                    return True
            except Exception:  # noqa: BLE001
                pass

            try:
                dlg.type_keys("{ENTER}")
                return True
            except Exception:  # noqa: BLE001
                return False
        except Exception as e:  # noqa: BLE001 (Application connect 失敗も非致命)
            # Codex HIGH-H: 最外殻 except は logger.warning で型名のみ出力
            # (UIA サービス停止 / 権限 / ImportError 等の根本原因切り分け用)
            logger.warning(
                "SFX dialog auto-click failed (pid=%d): %s",
                proc_pid,
                type(e).__name__,
            )
            return False


class FakeSfxAdapter:
    """テスト用 fake adapter (macOS でも全フロー検証可能にする)。

    ``produced_pdfs`` で「抽出後に検出される PDF パス」を、``raise_on_extract``
    で「extract_pdf 内で投げる例外」を制御する。実際にファイルを作成するかは
    テスト側の責務 (本 adapter はパス情報を返すだけで I/O はしない)。

    ``side_effect`` は呼び出し時にファイル生成等のセットアップ動作を実行する
    フックで、実際に watch_dirs に PDF を作成するテストで利用する。
    """

    def __init__(
        self,
        produced_pdfs: Sequence[Path] = (),
        raise_on_extract: SfxExtractionFailed | None = None,
        side_effect: object = None,
    ) -> None:
        self._produced_pdfs: tuple[Path, ...] = tuple(produced_pdfs)
        self._raise = raise_on_extract
        self._side_effect = side_effect
        self.calls: list[tuple[Path, tuple[Path, ...]]] = []

    def extract_pdf(
        self, exe_path: Path, watch_dirs: Sequence[Path]
    ) -> Sequence[Path]:
        self.calls.append((exe_path, tuple(watch_dirs)))
        if callable(self._side_effect):
            self._side_effect(exe_path, watch_dirs)
        if self._raise is not None:
            raise self._raise
        return self._produced_pdfs


# ---------------------------------------------------------------------------
# 結果型
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExtractionItem:
    """1 つの ``.ex_`` ファイルの抽出 + 振り分け結果。

    Attributes:
        source_path: 元 .ex_ ファイルのパス
        resolve_result: PR2 resolver の判定結果 (PR4 UI で candidates 表示等に使用)
        status: 抽出 + 移動の総合ステータス (PR4 UI 分岐の単一判定ポイント)
        moved_pdfs: SUCCESS 時のみ非空、移動先 (facility サブフォルダ) のパス
        partially_moved: MOVE_FAILED 時に「途中まで成功した」移動先パス
            (HIGH-A 対応、運用情報の消失防止)。複数 PDF 抽出のうち N 件目で
            衝突/IO エラーが起きた際、N-1 件は既に物理的に dest に存在するが
            SUCCESS 不変条件は維持したまま運用者へ伝える経路
        partial_outputs: PARTIAL_OUTPUT 時のみ非空、adapter 例外で **抽出側** に
            残された PDF の元パス (Desktop/Downloads/source_dir 等、移動なし)
        error_code: 失敗時の分類 (PII-safe enum、UI 分岐用)
        error_detail: PII-safe な詳細メッセージ (filename のみ含む可、事業所名禁止)
        cleanup_warning: ``.exe`` 削除失敗等、primary 結果に影響しない warning。
            primary error を上書きしない設計 (Codex HIGH-6 対応)
    """

    source_path: Path
    resolve_result: ResolveResult
    status: ExtractionStatus
    moved_pdfs: tuple[Path, ...] = ()
    partially_moved: tuple[Path, ...] = ()
    partial_outputs: tuple[Path, ...] = ()
    error_code: ExtractionErrorCode | None = None
    error_detail: str | None = None
    cleanup_warning: ExtractionErrorCode | None = None

    def __post_init__(self) -> None:
        # 不変条件: SUCCESS 時のみ moved_pdfs 非空 / 失敗系で moved_pdfs 空
        if self.status is ExtractionStatus.SUCCESS:
            if not self.moved_pdfs:
                raise ValueError("SUCCESS requires non-empty moved_pdfs")
            if self.error_code is not None:
                raise ValueError("SUCCESS forbids error_code")
            if self.partially_moved:
                raise ValueError("SUCCESS forbids partially_moved")
        else:
            if self.moved_pdfs:
                raise ValueError(
                    f"{self.status} forbids moved_pdfs "
                    f"(adapter exception path)"
                )

        # partially_moved は MOVE_FAILED でのみ意味を持つ (HIGH-A)
        if (
            self.partially_moved
            and self.status is not ExtractionStatus.MOVE_FAILED
        ):
            raise ValueError(
                f"{self.status} forbids partially_moved "
                f"(only MOVE_FAILED retains partial moves)"
            )

        # partial_outputs と partially_moved は意味が直交し共存不可
        # (前者は adapter 例外時の検出元パス、後者は MOVE_FAILED 時の移動先パス)
        if self.partial_outputs and self.partially_moved:
            raise ValueError(
                "partial_outputs and partially_moved are mutually exclusive "
                "(distinct status semantics)"
            )

        # PARTIAL_OUTPUT は partial_outputs 非空が必須
        if self.status is ExtractionStatus.PARTIAL_OUTPUT and not self.partial_outputs:
            raise ValueError("PARTIAL_OUTPUT requires non-empty partial_outputs")

        # 失敗系は error_code 必須 (PR4 UI 分岐保証)
        failure_statuses = {
            ExtractionStatus.EXTRACT_FAILED,
            ExtractionStatus.PARTIAL_OUTPUT,
            ExtractionStatus.MOVE_FAILED,
        }
        if self.status in failure_statuses and self.error_code is None:
            raise ValueError(f"{self.status} requires error_code")


@dataclass(frozen=True)
class ExtractionResult:
    """``extract_directory`` の集計結果。

    Attributes:
        items: 各 .ex_ の処理結果 (入力順)
        orphan_alias_canonicals: alias 設定だけ残り実フォルダが消えた canonical 名群
            (PR4 UI で警告バナー、CLI で stderr 警告)
        pending_filenames: AMBIGUOUS / UNMATCHED となった filename の列
            (CLI で stderr に列挙して現場へ明示的通知)
    """

    items: tuple[ExtractionItem, ...]
    orphan_alias_canonicals: tuple[str, ...] = ()
    pending_filenames: tuple[str, ...] = field(default=())

    @property
    def success_count(self) -> int:
        return sum(1 for i in self.items if i.status is ExtractionStatus.SUCCESS)

    @property
    def pending_manual(self) -> tuple[ExtractionItem, ...]:
        """AMBIGUOUS / UNMATCHED で SFX 抽出を skip した item 群 (PR4 手動振り分け対象)。"""
        manual_statuses = {
            ExtractionStatus.SKIPPED_AMBIGUOUS,
            ExtractionStatus.SKIPPED_UNMATCHED,
        }
        return tuple(i for i in self.items if i.status in manual_statuses)

    @property
    def failed(self) -> tuple[ExtractionItem, ...]:
        """SFX 失敗 / 部分生成 / 移動失敗の item 群 (再試行 or 調査対象)。"""
        failure_statuses = {
            ExtractionStatus.EXTRACT_FAILED,
            ExtractionStatus.PARTIAL_OUTPUT,
            ExtractionStatus.MOVE_FAILED,
        }
        return tuple(i for i in self.items if i.status in failure_statuses)


# ---------------------------------------------------------------------------
# Core 関数
# ---------------------------------------------------------------------------


def _build_watch_dirs(ex_file: Path) -> list[Path]:
    """SFX 抽出後に PDF が生成され得るディレクトリ群 (旧版互換)。

    旧 ``scripts/process_ex_files.py`` の挙動踏襲。SFX 自己解凍 EXE は cwd
    依存で出力先が変わるため、ex_file 配下 + デスクトップ + ダウンロード
    を監視する。

    探索順: ``ex_file.parent`` を **最優先** に置く (quarantine 方式と整合:
    取込元配下が SFX 抽出の本筋経路。順序を変えると Desktop / Downloads 等の
    別フォルダで誤配布リスクが復活するため不変条件として固定)。
    Desktop / Downloads はフォールバック。
    """
    return [
        ex_file.parent,
        Path.home() / "Desktop",
        Path.home() / "Downloads",
    ]


# 変則命名検出時、target_stem の直後にあると「変則」と判定する文字。
# 例: ``foo`` に対して ``foo_001.pdf`` (`_`) / ``foo (1).pdf`` (空白) /
# ``foo.x.pdf`` (`.`) など。``food.pdf`` (`d`) は対象外 (boundary 文字でない)。
_VARIANT_NAMING_BOUNDARY: tuple[str, ...] = ("_", "(", " ", "-", ".", "　")


def find_target_pdf(
    target_stem: str, watch_dirs: Sequence[Path]
) -> Path | None:
    """``<target_stem>.pdf`` を ``watch_dirs`` 横断で探す。

    探索順は ``watch_dirs`` 引数の順序 (呼び出し元が ``ex_file.parent`` 最優先で
    渡す責務、``_build_watch_dirs`` 参照)。複数 watch_dir に同名 PDF が存在する
    場合、先頭ヒットを返す (quarantine 方式と整合)。

    実機 Windows NTFS は case-insensitive かつ case-preserving のため、SFX が
    ``.PDF`` で書き出しても ``.pdf`` のアクセスでヒットする。本プロジェクトは
    Windows 実機専用運用のため、大文字フォールバックは行わない。

    PII 防御: ``OSError`` 時は ``logger.warning`` に型名のみ出力。
    """
    target_name = f"{target_stem}.pdf"
    for d in watch_dirs:
        try:
            if not d.exists():
                continue
        except OSError as exc:
            logger.warning(
                "watch_dir exists() failed: %s", type(exc).__name__
            )
            continue
        candidate = d / target_name
        try:
            if candidate.is_file():
                return candidate
        except OSError as exc:
            logger.warning(
                "candidate is_file() failed for %s: %s",
                candidate.name,
                type(exc).__name__,
            )
            continue
    return None


# quarantine ファイル名の prefix。dot 始まりにすることで Windows / Unix 双方で
# 「隠しファイル / 一時ファイル」扱いになり、次回の glob("*.pdf") から自然に除外
# される (find_target_pdf / find_unexpected_naming_pdfs はこの prefix を見ない)。
_QUARANTINE_PREFIX: Final[str] = ".quarantine-"


def _quarantine_pre_existing_target(
    ex_file: Path,
) -> tuple[Path | None, Path | None, ExtractionErrorCode | None, str | None]:
    """SFX 実行前の同名 PDF を一時退避する。

    ``ex_file.parent / <stem>.pdf`` (大小文字両対応) が存在したら、同ディレクトリに
    ``<original>.quarantine-<ts>`` 形式でリネーム退避する。これにより SFX が新規
    PDF を生成しない / mtime 更新しない場合でも、古い PDF を成功扱いで移動する
    誤配布事故を構造的に防止する。

    Returns:
        (quarantine_path, quarantine_origin, error_code, error_detail)

        - 退避なし (pre-existing 不在): (None, None, None, None)
        - 退避成功: (quarantine_path, origin, None, None)
        - 退避失敗 (OSError): (None, origin_or_None, QUARANTINE_FAILED, type 名)
    """
    target_stem = ex_file.stem
    target = ex_file.parent / f"{target_stem}.pdf"
    origin: Path | None = None
    try:
        if target.is_file():
            origin = target
    except OSError:
        # stat 不能 → 退避対象外として続行 (SFX 後にも探索する経路がある)
        pass
    if origin is None:
        return (None, None, None, None)

    # 秒精度の strftime だけだと、同一 ex_file の連続再処理 / 同秒に複数 .ex_ を
    # 処理した場合に collision で rename が失敗する。urandom サフィックスで
    # 構造的に回避。
    ts = time.strftime("%Y%m%d-%H%M%S") + f"-{os.urandom(3).hex()}"
    quarantine_path = origin.with_name(f"{origin.name}{_QUARANTINE_PREFIX}{ts}")
    try:
        origin.rename(quarantine_path)
    except OSError as exc:
        # PII 防御: filename と enum 値のみ、フルパスは出さない
        logger.warning(
            "%s: quarantine pre-existing target failed: %s",
            ex_file.name,
            type(exc).__name__,
        )
        return (
            None,
            origin,
            ExtractionErrorCode.QUARANTINE_FAILED,
            type(exc).__name__,
        )
    return (quarantine_path, origin, None, None)


def _restore_quarantine(
    quarantine_path: Path | None,
    origin: Path | None,
    ex_file_name: str,
) -> ExtractionErrorCode | None:
    """退避物を元の位置に戻す。SFX が新規生成しなかった場合に呼ぶ。

    既に origin が存在する (想定外: 部分的に SFX が生成した等) 場合は
    quarantine を削除して新規分を優先 (origin 上書きを避ける)。

    Returns:
        - 復元成功 / 退避なし: None
        - 復元失敗: QUARANTINE_RESTORE_FAILED (cleanup_warning として記録される)
    """
    if quarantine_path is None or origin is None:
        return None
    try:
        if origin.exists():
            # SUCCESS 経路でない (extract_failed) のに origin が存在する想定外ケース。
            # 新規生成分を優先して quarantine は削除 (origin 上書き防止)。
            quarantine_path.unlink(missing_ok=True)
            return None
        quarantine_path.rename(origin)
        return None
    except OSError as exc:
        # 復元失敗は運用 critical: 元の PDF が quarantine 名で残ったまま
        logger.warning(
            "%s: quarantine restore failed: %s",
            ex_file_name,
            type(exc).__name__,
        )
        return ExtractionErrorCode.QUARANTINE_RESTORE_FAILED


def _delete_quarantine(
    quarantine_path: Path | None, ex_file_name: str
) -> ExtractionErrorCode | None:
    """SUCCESS / MOVE_FAILED 経路で退避物を削除する。

    Returns:
        - 削除成功 / 退避なし: None
        - 削除失敗: CLEANUP_FAILED (cleanup_warning 既存経路と同じ扱い)
    """
    if quarantine_path is None:
        return None
    try:
        quarantine_path.unlink(missing_ok=True)
        return None
    except OSError as exc:
        logger.warning(
            "%s: quarantine cleanup failed: %s",
            ex_file_name,
            type(exc).__name__,
        )
        return ExtractionErrorCode.CLEANUP_FAILED


def find_unexpected_naming_pdfs(
    target_stem: str, watch_dirs: Sequence[Path]
) -> list[Path]:
    """``<target_stem>`` を prefix とする変則命名 PDF を返す。

    SFX が ``<stem>_001.pdf`` / ``<stem> (1).pdf`` 等の変則命名で出力した場合の
    検出用。``UNEXPECTED_PDF_NAMING`` エラー化のため、``partial_outputs`` として
    運用者へ未対応パターンの存在を明示通知する目的。

    判定ルール:
    - ``<stem>.pdf`` は expected として除外
    - ``<stem>`` で始まり、直後の文字が ``_VARIANT_NAMING_BOUNDARY`` の場合のみ採用
      (``food.pdf`` のような無関係な前方一致を構造的に除外)

    Windows 実機専用運用のため大文字 ``.PDF`` 経路は持たない (NTFS は
    case-insensitive で ``*.pdf`` glob が ``foo.PDF`` も拾う)。

    PII 防御: ``OSError`` 時は ``logger.warning`` に型名のみ出力。
    """
    expected = f"{target_stem}.pdf"
    found: list[Path] = []
    seen: set[Path] = set()
    for d in watch_dirs:
        try:
            if not d.exists():
                continue
        except OSError:
            continue
        try:
            paths = list(d.glob("*.pdf"))
        except OSError as exc:
            logger.warning(
                "glob failed in %s: %s", d.name, type(exc).__name__
            )
            continue
        for p in paths:
            if p in seen:
                continue
            if p.name == expected:
                continue
            if not p.name.startswith(target_stem):
                continue
            suffix = p.name[len(target_stem):]
            if suffix and suffix[0] in _VARIANT_NAMING_BOUNDARY:
                found.append(p)
                seen.add(p)
    return found


def extract_one(
    ex_file: Path,
    facility_root_dir: Path,
    facility_names: list[str],
    aliases: dict[str, list[str]],
    adapter: SfxAdapter,
    *,
    force_facility: str | None = None,
) -> ExtractionItem:
    """1 つの ``.ex_`` を resolver で振り分け先を決定し、CONFIRMED なら抽出 + 移動。

    AMBIGUOUS / UNMATCHED は **抽出も skip** し ``pending_manual`` として保持
    (Codex HIGH-8: 安全側、PR4 UI で手動振り分け予定)。

    Args:
        ex_file: 処理対象の .ex_ ファイル (フルパス)
        facility_root_dir: 事業所サブフォルダの親ディレクトリ
        facility_names: 振り分け先候補 (facility_root_dir 配下のディレクトリ名群)
        aliases: PR1 検証済 alias 辞書
        adapter: SfxAdapter 実装 (Windows 実機 / Fake)
        force_facility: PR4 で追加。指定時は resolver を bypass し、
            ``ResolveReason.MANUAL_OVERRIDE`` で擬似 CONFIRMED を構築 + 抽出 + 移動。
            UI の手動振り分けダイアログから呼ばれる経路。``facility_names`` に
            存在しない値を渡した場合は ``ValueError`` (UI が誤った値を渡す事故防止)。

    Returns:
        ``ExtractionItem`` (PII-safe な構造化結果)
    """
    # PII 保護: filename のみログ、フルパス・facility_root_dir は出さない
    logger.info("processing %s", ex_file.name)

    # Step 1: resolver で振り分け先決定 (Path.name 必須、resolver docstring で警告)
    # PR4: force_facility 指定時は resolver bypass + MANUAL_OVERRIDE で CONFIRMED 構築
    if force_facility is not None:
        if force_facility not in facility_names:
            # PII 防御: 値そのものは出さず、文字数 (chars) と候補数 (size) で
            # 単位を明示。HIGH-F (comment-analyzer): len() の意味曖昧を解消
            raise ValueError(
                f"force_facility (chars={len(force_facility)}) "
                f"not in facility_names (size={len(facility_names)})"
            )
        result = ResolveResult.confirmed(
            force_facility, ResolveReason.MANUAL_OVERRIDE
        )
    else:
        result = resolve_facility(ex_file.name, facility_names, aliases)

    if result.needs_manual_selection:
        return ExtractionItem(
            source_path=ex_file,
            resolve_result=result,
            status=ExtractionStatus.SKIPPED_AMBIGUOUS,
        )
    if result.needs_manual_input:
        return ExtractionItem(
            source_path=ex_file,
            resolve_result=result,
            status=ExtractionStatus.SKIPPED_UNMATCHED,
        )

    # CONFIRMED: matched_facility は __post_init__ で非 None 保証済
    # 明示 raise (HIGH-I): ``python -O`` で assert が消えても契約を破らないように
    matched = result.matched_facility
    if matched is None:
        raise RuntimeError(
            "resolver returned CONFIRMED without matched_facility "
            "(ResolveResult invariant violation)"
        )

    # Step 1.5: pre-existing target quarantine
    # SFX 実行前に ex_file.parent の同名 PDF を一時退避し、SFX が新規生成しない
    # 場合に「古い PDF を成功扱いで移動」する誤配布事故を構造的に防ぐ。
    quarantine_path, quarantine_origin, q_error_code, q_error_detail = (
        _quarantine_pre_existing_target(ex_file)
    )
    if q_error_code is not None:
        # 退避失敗時は SFX 実行に進まない (古い PDF が同居したまま処理 → 誤配布リスク)
        return ExtractionItem(
            source_path=ex_file,
            resolve_result=result,
            status=ExtractionStatus.EXTRACT_FAILED,
            error_code=q_error_code,
            error_detail=q_error_detail,
        )

    # Step 2: .exe コピー
    exe_path = ex_file.with_suffix(".exe")
    try:
        shutil.copy2(ex_file, exe_path)
    except OSError as e:
        # quarantine を元に戻してから return (退避物が孤立しないように)
        restore_warning = _restore_quarantine(
            quarantine_path, quarantine_origin, ex_file.name
        )
        return ExtractionItem(
            source_path=ex_file,
            resolve_result=result,
            status=ExtractionStatus.EXTRACT_FAILED,
            error_code=ExtractionErrorCode.COPY_FAILED,
            error_detail=type(e).__name__,
            cleanup_warning=restore_warning,
        )

    # Step 3: SFX 抽出 + 移動 (cleanup を必ず実施)
    cleanup_warning: ExtractionErrorCode | None = None
    pdfs: list[Path] = []
    partial_outputs: tuple[Path, ...] = ()
    error_code: ExtractionErrorCode | None = None
    error_detail: str | None = None
    extract_failed = False
    moved_pdfs: list[Path] = []
    move_failed = False

    try:
        try:
            pdfs = list(adapter.extract_pdf(exe_path, _build_watch_dirs(ex_file)))
        except SfxExtractionFailed as e:
            error_code = e.code
            error_detail = e.detail
            partial_outputs = e.partial_outputs
            extract_failed = True

        if not extract_failed and not pdfs:
            error_code = ExtractionErrorCode.NO_PDF_PRODUCED
            extract_failed = True

        # Step 4: 移動 (CONFIRMED + 抽出成功時のみ)
        if not extract_failed:
            dest_dir = facility_root_dir / matched
            for pdf in pdfs:
                dest = dest_dir / pdf.name
                if dest.exists():
                    # HIGH-A: 既に moved_pdfs に積んだ分は partially_moved に保持
                    error_code = ExtractionErrorCode.MOVE_CONFLICT
                    error_detail = pdf.name
                    move_failed = True
                    break
                try:
                    shutil.move(str(pdf), str(dest))
                except OSError as e:
                    # HIGH-B: クロスデバイス / 権限 / ネットワーク drive 切断等を捕捉
                    error_code = ExtractionErrorCode.MOVE_IO_ERROR
                    error_detail = type(e).__name__
                    move_failed = True
                    break
                moved_pdfs.append(dest)
    finally:
        try:
            exe_path.unlink(missing_ok=True)
        except OSError:
            cleanup_warning = ExtractionErrorCode.CLEANUP_FAILED

    # Step 5: 結果集約 (status を分類確定)
    if extract_failed:
        status = (
            ExtractionStatus.PARTIAL_OUTPUT
            if partial_outputs
            else ExtractionStatus.EXTRACT_FAILED
        )
    elif move_failed:
        status = ExtractionStatus.MOVE_FAILED
    else:
        status = ExtractionStatus.SUCCESS

    # Step 6: quarantine 後処理
    # - SUCCESS / MOVE_FAILED → 退避物削除 (target_pdf は新規生成された)
    # - EXTRACT_FAILED / PARTIAL_OUTPUT → 退避物復元 (target_pdf は生成されず)
    quarantine_post_warning: ExtractionErrorCode | None
    if status in (ExtractionStatus.SUCCESS, ExtractionStatus.MOVE_FAILED):
        quarantine_post_warning = _delete_quarantine(
            quarantine_path, ex_file.name
        )
    else:
        quarantine_post_warning = _restore_quarantine(
            quarantine_path, quarantine_origin, ex_file.name
        )
    # 既存の cleanup_warning (.exe 削除失敗) を上書きしない: 先勝ち優先で primary を保持
    if cleanup_warning is None and quarantine_post_warning is not None:
        cleanup_warning = quarantine_post_warning

    # HIGH-G / M-1: silent な warning 状態を logger に出す
    # PII 防御: filename と enum 値のみ、フルパス / 事業所名は出さない
    if partial_outputs:
        logger.warning(
            "%s: partial outputs left in watch_dirs (count=%d)",
            ex_file.name,
            len(partial_outputs),
        )
    if cleanup_warning is not None:
        logger.warning(
            "%s: cleanup warning %s",
            ex_file.name,
            cleanup_warning.value,
        )

    return ExtractionItem(
        source_path=ex_file,
        resolve_result=result,
        status=status,
        moved_pdfs=tuple(moved_pdfs) if status is ExtractionStatus.SUCCESS else (),
        # HIGH-A: MOVE_FAILED でも途中まで成功した分を運用者へ可視化
        partially_moved=(
            tuple(moved_pdfs)
            if status is ExtractionStatus.MOVE_FAILED and moved_pdfs
            else ()
        ),
        partial_outputs=partial_outputs,
        error_code=error_code,
        error_detail=error_detail,
        cleanup_warning=cleanup_warning,
    )


def _scan_facility_names(facility_root_dir: Path) -> list[str]:
    """``facility_root_dir`` 配下の事業所サブフォルダ名を列挙 (旧版互換、``_`` 始まり除外)。"""
    return sorted(
        d.name
        for d in facility_root_dir.iterdir()
        if d.is_dir() and not d.name.startswith("_")
    )


def extract_directory(
    source_dir: Path,
    facility_root_dir: Path,
    aliases: dict[str, list[str]],
    adapter: SfxAdapter,
) -> ExtractionResult:
    """``source_dir`` 配下の全 ``.ex_`` を順次処理し、集計結果を返す。

    旧 ``process_directory`` を置換 + 拡張。``source_dir`` と ``facility_root_dir``
    を分離することで PR4 UI で別々のディレクトリを指定可能 (旧版は同一)。
    CLI 薄ラッパーは互換のため両者に同じパスを渡す。

    Args:
        source_dir: ``.ex_`` ファイルを列挙するディレクトリ
        facility_root_dir: 事業所サブフォルダの親ディレクトリ
        aliases: PR1 検証済 alias 辞書
        adapter: SfxAdapter 実装

    Returns:
        ``ExtractionResult`` (items + orphan + pending_filenames)

    Raises:
        FileNotFoundError: source_dir / facility_root_dir が存在しない
    """
    if not source_dir.exists():
        raise FileNotFoundError(f"source_dir not found: {source_dir}")
    if not facility_root_dir.exists():
        raise FileNotFoundError(f"facility_root_dir not found: {facility_root_dir}")

    facility_names = _scan_facility_names(facility_root_dir)
    orphans = tuple(find_orphan_alias_canonicals(facility_names, aliases))

    ex_files = sorted(source_dir.glob("*.ex_"))

    items: list[ExtractionItem] = []
    pending_filenames: list[str] = []
    pending_statuses = {
        ExtractionStatus.SKIPPED_AMBIGUOUS,
        ExtractionStatus.SKIPPED_UNMATCHED,
    }
    for ex_file in ex_files:
        # HIGH-B: 1 ファイルの想定外例外で残り全件処理が止まらないようループ最外殻保護
        try:
            item = extract_one(
                ex_file, facility_root_dir, facility_names, aliases, adapter
            )
        except (MemoryError, RecursionError):
            # silent-failure-hunter H-2: システム例外はバッチ続行不能、即時停止
            # (続行すると派生 OOM が連鎖する典型的アンチパターン)
            raise
        except Exception as e:  # noqa: BLE001 (バッチ続行優先、PII 防御で型名のみ)
            # PII 防御 (HIGH-NEW-1): logger.exception は traceback 経由で OSError.args
            # に含まれる full path を漏洩させるため使わない。型名のみログ
            logger.warning(
                "unexpected error processing %s: %s",
                ex_file.name,
                type(e).__name__,
            )
            # HIGH-NEW-2: 例外源が resolver の場合、再呼び出しで二度目の例外が
            # 投げられバッチ続行保護が破綻する → safe UNMATCHED にフォールバック
            # (UNEXPECTED 経路では resolve_result を信頼しない契約、PR4 UI で考慮)
            try:
                fallback_resolve = resolve_facility(
                    ex_file.name, facility_names, aliases
                )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "resolver also failed for %s; using UNMATCHED fallback",
                    ex_file.name,
                )
                fallback_resolve = ResolveResult.unmatched(
                    ResolveReason.NO_CANDIDATE
                )
            item = ExtractionItem(
                source_path=ex_file,
                resolve_result=fallback_resolve,
                status=ExtractionStatus.EXTRACT_FAILED,
                error_code=ExtractionErrorCode.UNEXPECTED,
                error_detail=type(e).__name__,
            )
        items.append(item)
        if item.status in pending_statuses:
            pending_filenames.append(ex_file.name)

    return ExtractionResult(
        items=tuple(items),
        orphan_alias_canonicals=orphans,
        pending_filenames=tuple(pending_filenames),
    )
