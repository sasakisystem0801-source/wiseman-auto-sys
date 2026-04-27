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
import shutil
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from wiseman_hub.pdf.facility_resolver import (
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
        # Codex HIGH-D 対応: mtime フィルタ用に SFX 起動前時刻を保持
        # Desktop/Downloads に同時並行で別 PDF が出現しても拾わない
        sfx_start = time.time()
        before = self._snapshot_pdfs(watch_dirs)

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
                    # SFX 正常終了 → 書き込み完了を待ってから差分検出
                    time.sleep(1)
                    return self._collect_new_pdfs(watch_dirs, before, sfx_start)
        finally:
            if proc.poll() is None:
                self._terminate_proc(proc)

        # タイムアウト後の最終チェック (旧版互換: 検出されれば成功扱い)
        time.sleep(1)
        final_pdfs = self._collect_new_pdfs(watch_dirs, before, sfx_start)
        if final_pdfs:
            return final_pdfs
        timeout_sec = int(self._MAX_WAIT_TICKS * self._TICK_INTERVAL_SEC)
        raise SfxExtractionFailed(
            ExtractionErrorCode.SFX_TIMEOUT,
            f"no pdf produced within {timeout_sec}s",
        )

    @classmethod
    def _collect_new_pdfs(
        cls,
        watch_dirs: Sequence[Path],
        before: set[Path],
        sfx_start: float,
    ) -> list[Path]:
        """SFX 起動後に出現した PDF のみを返す (Codex HIGH-D: 誤配布防止)。

        set 差分だけだと、SFX 実行中に別経路 (ユーザーの手動 DL 等) で生成された
        PDF まで拾い、無関係な PDF が事業所フォルダに移動される。``mtime >=
        sfx_start`` で実時間ベースに絞ることで、watch_dirs に Desktop/Downloads を
        含めたまま誤配布リスクを構造的に低減する。
        """
        candidates = cls._snapshot_pdfs(watch_dirs) - before
        new_pdfs: list[Path] = []
        for pdf in candidates:
            try:
                if pdf.stat().st_mtime >= sfx_start:
                    new_pdfs.append(pdf)
            except OSError:
                continue
        return new_pdfs

    @staticmethod
    def _snapshot_pdfs(directories: Sequence[Path]) -> set[Path]:
        pdfs: set[Path] = set()
        for d in directories:
            if d.exists():
                pdfs |= set(d.glob("*.pdf")) | set(d.glob("*.PDF"))
        return pdfs

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
    """
    return [
        ex_file.parent,
        Path.home() / "Desktop",
        Path.home() / "Downloads",
    ]


def extract_one(
    ex_file: Path,
    facility_root_dir: Path,
    facility_names: list[str],
    aliases: dict[str, list[str]],
    adapter: SfxAdapter,
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

    Returns:
        ``ExtractionItem`` (PII-safe な構造化結果)
    """
    # PII 保護: filename のみログ、フルパス・facility_root_dir は出さない
    logger.info("processing %s", ex_file.name)

    # Step 1: resolver で振り分け先決定 (Path.name 必須、resolver docstring で警告)
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

    # Step 2: .exe コピー
    exe_path = ex_file.with_suffix(".exe")
    try:
        shutil.copy2(ex_file, exe_path)
    except OSError as e:
        return ExtractionItem(
            source_path=ex_file,
            resolve_result=result,
            status=ExtractionStatus.EXTRACT_FAILED,
            error_code=ExtractionErrorCode.COPY_FAILED,
            error_detail=type(e).__name__,
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
            "%s: %s (.exe could not be removed)",
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
        except Exception as e:  # noqa: BLE001 (バッチ続行優先、PII 防御で型名のみ)
            logger.exception("unexpected error processing %s", ex_file.name)
            item = ExtractionItem(
                source_path=ex_file,
                resolve_result=resolve_facility(
                    ex_file.name, facility_names, aliases
                ),
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
