# ADR-014: .ex_ ファイル PDF 抽出・事業所フォルダ振り分け機能のデスクトップアプリ統合

## ステータス

**Proposed (2026-04-27)** — PR シリーズ進行中（PR1 マージ済 / PR2 進行中 / PR3-5 計画段階）。Windows 実機検証完了後に Accepted 昇格予定。

### 変更履歴

- 2026-04-27: 本 ADR 作成（PR2 で初版を追加）
- 2026-04-27: Evaluator 指摘 HIGH-1/HIGH-2 を反映（alias canonical 実在検証 + 語境界要求の追加）。テストデータを仮名化（PII 保護徹底、AC2-9 PARTIAL → PASS）
- 2026-04-27: 5 agents + Codex 並列レビュー指摘を反映（alias 複数 hit → AMBIGUOUS_ALIAS、正規化完全一致複数 → AMBIGUOUS_EXACT、ResolveResult `__post_init__` 不変条件強制、空白除去廃止で境界文字化、UNMATCHED reason 細分化、`is_auto_distributable` プロパティ、`find_orphan_alias_canonicals` ヘルパー追加、ADR 自身の実名残置を仮名化）
- 2026-04-27: PR3 実装着手。Codex セカンドオピニオン (HIGH 4 / MEDIUM 3 / LOW-MEDIUM 1) を反映:
  - **HIGH-1 移行期 false negative 対策**: CLI 薄ラッパーに pending filename の stderr 列挙 + 暫定運用手順表示 + exit code 2 (新規) で「振り分け止まり」を現場へ明示
  - **HIGH-3 CLI 互換境界の表現修正**: 「CLI 互換」ではなく「CLI **インターフェース** 互換、振り分けロジックは新 resolver により安全化により挙動変更」と明記
  - **HIGH-6 adapter 例外時の部分生成 PDF**: `SfxExtractionFailed.partial_outputs` フィールドで保持、`ExtractionStatus.PARTIAL_OUTPUT` で表現、自動移動を構造的に禁止。`cleanup_warning` を primary error と分離
  - **HIGH-8 AMBIGUOUS/UNMATCHED で SFX skip**: PR3 デフォルト維持。結果型は将来の `extract_for_review` モードに耐える形 (status enum + partial_outputs フィールド)
  - **MEDIUM-2 adapter 設計**: `NotImplementedError` ではなく `UnsupportedSfxPlatformError` (RuntimeError 派生) を採用、`pywinauto` import を `_click_sfx_dialog` 内で遅延化し macOS の dry-run / `--help` 動作を保証
  - **MEDIUM-4 結果型粒度**: `error: str` → `error_code: ExtractionErrorCode | None` + `error_detail: str | None` に分離、`ExtractionStatus` を新設して PR4 UI 分岐の単一判定ポイントを提供
  - **MEDIUM-5 PII ログ防御**: ポリシーを「フルパス禁止 / 事業所名禁止 / candidates 禁止 / 抽出 PDF 名禁止 / filename のみ許容」に厳格化、caplog で直接検査
- 2026-04-27: PR3 6 並列レビュー (evaluator + 5 agents) 指摘の HIGH を反映:
  - **PR3-HIGH-A**: `MOVE_FAILED` 時に複数 PDF の途中まで成功した移動先を `ExtractionItem.partially_moved` フィールドで運用者へ可視化 (運用情報の消失防止、4 reviewer 重複検出)
  - **PR3-HIGH-B**: `shutil.move` の `OSError` (クロスデバイス / 権限 / ネットワークドライブ切断) を捕捉し `MOVE_IO_ERROR` で構造化、`extract_directory` ループ最外殻でも想定外例外を `UNEXPECTED` として捕捉してバッチ続行を保証
  - **PR3-HIGH-C**: `WindowsSfxAdapter.extract_pdf` の `OSError.str()` は Windows で full path を含むため `type(e).__name__` のみを `SfxExtractionFailed.detail` に伝搬 (PII 防御)
  - **PR3-HIGH-D**: `_build_watch_dirs` の Desktop / Downloads 監視で SFX 実行中にユーザーが別途保存した無関係 PDF を誤配布するリスク → `_collect_new_pdfs` で `mtime >= sfx_start` フィルタを追加 (誤配布 KPI 直撃の構造的防御)
  - **PR3-HIGH-G/M-1**: `partial_outputs` / `cleanup_warning` 設定時の silent 化を `logger.warning` 出力で解消 (filename + enum 値のみ、PII-safe)
  - **PR3-HIGH-H**: `_click_sfx_dialog` の最外殻 `except Exception` に `logger.warning` で例外型名のみ出力 (UIA サービス停止 / 権限不足の根本原因切り分け用)
  - **PR3-HIGH-I**: `assert matched is not None` を `if matched is None: raise RuntimeError` に変更 (`python -O` 実行時の silent NoneType 伝播防止)
  - **PR3-HIGH-F**: CLI `_print_summary` に pending 件数の専用警告行 + cleanup_warning 別セクション + partially_moved 件数表示を追加 (現場運用での「振り分け止まり」即時検知)
  - **L-1**: `WindowsSfxAdapter._terminate_proc` の `proc.kill()` 後 `wait(timeout=10)` 追加 (driver hang 時の無限待機防止)
- 2026-04-27: **PR4 着手**（ex_extractor デスクトップ UI 統合）。Codex セカンドオピニオン HIGH 4 件 + MEDIUM 3 件を反映:
  - **PR4-HIGH-1 (force_facility 経路)**: PR3 `extract_one` は内部で `resolve_facility` を呼ぶため、UI で擬似 CONFIRMED を作っても再呼び出しで UNMATCHED に戻ってしまう設計欠陥を Codex 指摘。`extract_one(force_facility: str | None = None)` パラメータを追加（後方互換）し、指定時は resolver を bypass して `ResolveResult.confirmed(force_facility, ResolveReason.MANUAL_OVERRIDE)` を構築 + 抽出 + 移動。`force_facility not in facility_names` は ValueError で fail-fast（UI 誤値防止）
  - **PR4-HIGH-2 (監査性)**: `ResolveReason.MANUAL_OVERRIDE` を新設、`_REASON_TO_STATUS` で CONFIRMED にマップ。UI サマリで「自動振り分け成功」「手動確定成功」を分離表示（運用監査でどちらの経路で振り分けられたか識別可能）
  - **PR4-HIGH-3 (UNMATCHED 確認ステップ)**: 全 facility プルダウンの誤選択を構造的に防ぐため、確定前に「ファイル名 / 振り分け先事業所 / 出力先パス」を表示する確認ステップを追加。プルダウン既定選択は空（`(未選択)`）にして先頭 facility 誤選択を遮断
  - **PR4-HIGH-4 (PARTIAL_OUTPUT / partially_moved 可視化)**: PR5 持ち越しは事故温床のため PR4 で「要確認」セクションに件数 + filename を表示、partially_moved は「一部 PDF 移動済 N 件」と注記
  - **PR4-MEDIUM-5 (進捗)**: `_LBL_RUNNING = "処理中... (最大 数分かかる場合があります)"` で本田様 (IT 非専門) が「固まった」と誤認しないようにする。完全な per-file progress は PR5 で `extract_directory` に callback 追加検討
  - **PR4-MEDIUM-6 (モーダル制御)**: `Toplevel(parent)` + `transient` + `grab_set` + `protocol("WM_DELETE_WINDOW", _on_close)` + 実行中 close 抑止の facility_root_dialog パターン踏襲
  - **PR4-MEDIUM-7 (手動 SFX worker thread)**: ManualDistributionDialog 内で extract_one を独自 ThreadPoolExecutor で worker thread 化、UI 凍結防止
- 2026-04-27: PR #135 review-pr (6 並列再レビュー) で発見された新規 HIGH 7 件 + MEDIUM 3 件を反映:
  - **PR4-NEW-A (運用情報消失)**: 抽出中の close で SFX 完了 + PDF 移動済なのに UI 反映なし → `_on_extract_done` 冒頭で `_top.winfo_exists()` ガード + 親ダイアログ destroy 後の after callback 到達を logger.warning で可視化
  - **PR4-NEW-B (executor shutdown と worker thread)**: `shutdown(wait=False, cancel_futures=True)` は実行中 future を中断しないため、close 後の after callback で `_top.winfo_exists()` で safe ガード (HIGH-A と統合対応)
  - **PR4-NEW-C (永久 BUSY 固着)**: `_on_open_manual_click` の例外で MANUAL_DISTRIBUTING 固着 → try/except で `saved_result` 経由 SHOWING_RESULT 復帰 + messagebox 通知
  - **PR4-NEW-D (state 遷移チェック)**: `transition_to_idle_with_error` に遷移元チェック (`BUSY` または `MANUAL_DISTRIBUTING` のみ) を追加。docstring の状態遷移図にも `SHOWING_RESULT → BUSY (再実行)` / `MANUAL_DISTRIBUTING → IDLE` を明記
  - **PR4-NEW-E (部分実行 PDF 隠蔽)**: ManualDistributionDialog の `_on_extract_done` 例外パスで `dataclasses.replace` を使い `EXTRACT_FAILED + UNEXPECTED` で記録、original SKIPPED_* 状態のまま隠蔽されない
  - **PR4-NEW-F (ValueError メッセージ単位明示)**: `extract_one` の `force_facility not in facility_names` で `chars=` (文字数) と `size=` (要素数) を明示し誤誘導を解消
  - **PR4-NEW-G (統合テスト追加)**: 状態遷移の遷移元チェック失敗 / `MANUAL_DISTRIBUTING → IDLE` 復帰 / `abort_remaining` の DONE idempotent / 中断時の未処理 item 穴埋めを ViewModel テストでカバー (4 件追加、計 810 passed)
  - **PR4-NEW-MEDIUM-1**: `__main__._make_ex_extractor_callback` の `messagebox.showerror(parent=launcher.get_root())` で transient 化
  - **PR4-NEW-MEDIUM-4**: `select_facility` の候補外値 silent reject で `logger.warning` 出力 (運用者の「ボタン押したのに動かない」混乱を防ぐ)
  - **PR4-NEW-MEDIUM-5 (orphan banner 専用 frame)**: alias 設定不整合は次回以降も自動振り分け失敗を生む構造的問題のため、サマリ末尾ではなく専用 frame を上部に常時表示で見落とし防止
  - **簡素化 H2**: `_on_close` の while ループを `ManualDistributionViewModel.abort_remaining()` に責務移動、Tk 非依存テストで検証可能に
- 2026-04-27: PR #133 review-pr (6 並列再レビュー) で発見された新規 HIGH 6 件を反映:
  - **PR3-NEW-1 (PII)**: `extract_directory` 例外捕捉で `logger.exception` を使うと traceback 経由で `OSError.args` の full path が漏洩する → `logger.warning` + `type(e).__name__` のみに変更
  - **PR3-NEW-2 (resolver 二重呼び出し)**: 例外源が resolver の場合、フォールバックで再呼び出しすると同じ例外が二度目に発生しバッチ続行保護が破綻 → `try/except` で safe `UNMATCHED` フォールバック追加
  - **PR3-NEW-3 (mtime グレース)**: `time.time()` は非単調、SFX 実行中の NTP 後方ステップで本来の PDF が誤って除外される → `_MTIME_GRACE_SEC = 5.0` のマージンで吸収
  - **PR3-NEW-4 (silent skip 解消)**: `_collect_new_pdfs` の `stat()` 失敗を `logger.warning` + 型名で可視化 (network drive 切断 / 権限変化等の根本原因切り分け)
  - **PR3-NEW-5 (システム例外)**: `MemoryError` / `RecursionError` を `extract_directory` ループで握り潰すと派生 OOM が連鎖 → 先に re-raise してバッチ即時停止
  - **PR3-NEW-6 (不変条件)**: `partial_outputs` と `partially_moved` は status が排他なので同時非空にならないが、二重防御として `__post_init__` で排他検証を追加
  - **PR3-NEW-MEDIUM**: CLI `logging.basicConfig` を `main()` 内に移動 (import 時の root logger 上書きを防ぎ、PR4 UI からの import を阻害しない)
  - PII 保護方針セクションに `ex_extractor` モジュールおよび CLI レイヤの規定を追加 (orphan_alias_canonicals は alias 設定不整合通知用に canonical 名を例外的に出力する旨を明記、運用ドキュメントでの取り扱い注意を併記)

## コンテキスト

Wiseman からダウンロードされる帳票は `.ex_` ファイル（WinSFX32 LZH 自己解凍 EXE）形式で、現状は `scripts/process_ex_files.py`（263 行）によりコマンドライン経由で PDF 抽出 + 事業所フォルダ振り分けを実行している。

ADR-013（PR #126）で `pdf_merge.facility_root_dir` 配下の事業所フォルダを一括結合するデスクトップアプリ機能が完成し、本田様の月次運用に投入された。次の業務改善として、**前段の `.ex_` 取込・振り分けもデスクトップアプリにワンボタン化** したいというユーザー要望が発生（2026-04-27）。

### 業務フロー上の位置づけ

```
[Wiseman ダウンロード] → .ex_ 群
       ↓
   ① ex_ → PDF 抽出 + 事業所フォルダ振り分け  ← 本 ADR の対象
       ↓
       事業所フォルダに B/C PDF が揃う
       ↓
   ②a 「事業所フォルダ一括結合」(ADR-013) または ②b 「PDF マージ処理」→「確認待ちセッション」
       ↓
       配布用 PDF 完成
```

### 制約

- **介護現場で誤配布が業務事故**: マッチング誤検知（false positive）は false negative より重大。事業所 A の介護記録が事業所 B に振り分けられると個人情報漏洩 + 業務信頼失墜
- **介護施設職員（IT 非専門）向け**: エラーは平易な日本語、手動振り分けは直感的な UI
- **Windows 専用機能**: pywinauto + subprocess 経由の SFX ダイアログ自動操作。macOS では fake runner で抽出フローのみテスト
- **既存 `scripts/process_ex_files.py` の挙動互換**: 本田様の現行運用を破壊しない
- **既存 ADR-013 / ADR-012 との整合**: facility_root_dir / 事業所フォルダ判定ロジックを共有

## 決定

### PR 分割（5 PR シリーズ）

Codex セカンドオピニオンによる「1 PR で 1,200+ LOC は事故率高い」指摘を受けて、機能を 5 PR に分割:

| # | スコープ | 状態 |
|---|---------|-----|
| PR1 | 設定スキーマ拡張（`ex_source_dir` + `facility_aliases`） | Merged (#130) |
| PR2 | `pdf/facility_resolver` 単体（alias 優先 + 安全マッチング） | Merged (#131) |
| PR3 | `pdf/ex_extractor` core 移植 + SFX adapter 化 + macOS fake runner + scripts ラッパー | Merged (#133) |
| PR4 | UI 統合（dialog + launcher 5 ボタン化 + 手動振り分け UI） | 本 PR |
| PR5 | Windows 実機検証 + 修正 + settings.py タブ化（独立評価） | 計画段階 |

### マッチング戦略（安全設計）

Codex 指摘「双方向部分一致 + 最長一致は false positive リスク」+ Evaluator 指摘
「短 alias の無境界マッチで誤配布」「alias canonical 不在で存在しないフォルダへの
書き込み」を受けて、以下の優先順序 + 安全制約で評価する:

| 順位 | 判定 | reason | 説明 |
|------|------|-------|------|
| 1 | alias 一致 | `ALIAS_MATCH` | `facility_aliases[canonical]` のいずれかが正規化ファイル名に **語境界付きで** 含まれる。**かつ canonical が facility_names に実在** する場合のみ |
| 2 | 正規化完全一致 | `EXACT_MATCH` | 正規化後のファイル名が事業所名そのものと等しい（レアケース） |
| 3 | 部分一致（一意） | `PARTIAL_UNIQUE` | 事業所名がファイル名に **語境界付き** 部分一致し、候補が 1 つだけ |
| 4 | 部分一致（最長優位） | `PARTIAL_DOMINANT` | 候補複数だが最長候補と次長候補の差が `_PARTIAL_MATCH_DOMINANCE_THRESHOLD = 2` 文字以上 |
| 5 | AMBIGUOUS | `AMBIGUOUS_PARTIAL` | 候補複数で差が閾値未満 → UI で手動選択 |
| 6 | UNMATCHED | `NO_CANDIDATE` | 候補ゼロ → UI でスキップ or 全事業所からのプルダウン選択 |

#### 部分一致の方向性

**事業所名 ⊂ ファイル名 の一方向のみ** を採用。逆方向（ファイル名 ⊂ 事業所名）は通常ファイル名が日付・記号付きで長いため起こらず、許容すると false positive を増やす。

#### 語境界要求（Evaluator HIGH-2 対応）

alias / canonical name のマッチには **「語境界」が必須**:
- 前後の文字が `_ALIAS_BOUNDARY_CHARS = "_-. ()/[]{}\,;:!?#@&%+=*~|<>'\"\`"` に含まれる
- または文字列の開始/終端

これにより以下の誤配布パスを遮断:
- alias `{"サービスA": ["デイ"]}` + ファイル名「夜間デイサービスB_提供.ex_」
  → "デイ" は前後「夜間」「サ」(日本語) で語境界なし → 誤ヒットせず UNMATCHED
- canonical「サービスA」+ ファイル名「夜間サービスA東_提供.ex_」
  → "サービスA" は前後「間」「東」(日本語) で語境界なし → 候補から除外

#### canonical 実在検証（Evaluator HIGH-1 対応）

alias 辞書の canonical が `facility_names` に存在しない場合、当該 alias 候補を skip する:
- 例: alias `{"消えた施設": ["短縮"]}` + facility_names ["訪問BX"]
  → canonical「消えた施設」が facility_names にないので skip
  → 部分一致 step に進み、訪問BX もマッチしないため UNMATCHED

これにより「alias 設定を残したまま実フォルダを削除した」運用ミスで存在しないパスへ
書き込もうとする経路を構造的に排除。

#### 「十分差」閾値（2 文字）の根拠

- 1 文字差: 「サービスA」と「サービスA東」のような僅差は人為的命名ミスとの区別が困難 → AMBIGUOUS
- 2 文字差以上: 「サービスA」と「サービスA（拡張）」(差 5 文字、半角化後) のような明確な追加修飾は別事業所と判定可能 → CONFIRMED

将来この閾値の調整が必要な場合は、設定ファイル化または ADR 改訂で対応。

（注: ADR 内で実在事業所名を使うと PR diff 経由の PII 漏洩経路を ADR 自身が破壊するため、テストデータと同じ仮名で記述する。レビュー H-F 対応）

### 正規化規則

- NFKC 正規化（半角カナ ⇔ 全角カナ、半角英数 ⇔ 全角英数、（）⇔ () 統一）
- 空白除去（半角・全角・タブ・改行・CR）

### facility_aliases の入力検証（PR1 で実装済）

`config._validate_facility_aliases` で以下を検証し、違反は `ValueError` / `TypeError` で fail-fast:

1. 正式名 key が空文字列でない
2. value が `list` 型である（文字列を直接書くと文字単位分解されるため `TypeError`）
3. value 要素がすべて非空 `str`
4. 同じ list 内で alias 重複なし
5. 異なる事業所間で同じ alias を共有しない（global 一意性）
6. alias が他事業所の正式名と一致しない（alias 一致と完全一致の衝突回避）

これにより `facility_resolver` は valid な alias 辞書を前提にできる契約。

### PII 保護方針

ファイル名・事業所名・別名は介護現場で機密扱いとなる場合があるため:

- `facility_resolver` モジュールは **ログ出力を一切行わない**
- 例外メッセージには「衝突した alias 文字列」のみ含めて運用者の修正を助けるが、正式事業所名・他別名は出さない
- 不正入力（空文字列、空白のみ）は例外を投げず `UNMATCHED` を返す（例外メッセージ経由の PII 漏洩防止）

#### `ex_extractor` モジュール (PR3)

- `logger` 出力は filename と enum 値（`ExtractionErrorCode` / `ExtractionStatus` の文字列値）のみ許容
- 禁止: フルパス / facility_root_dir / matched_facility / candidates / 抽出 PDF 名 / OSError 例外メッセージ生文字列
- `OSError.str()` 等の生例外メッセージは **必ず** `type(e).__name__` で型名のみ伝搬（Windows 環境では `OSError.args` に full path が含まれるため）
- caplog で直接検査（テスト 4 件、PR3 で網羅）

#### CLI レイヤ (`scripts/process_ex_files.py`)

`_print_summary` は以下の例外規定で stderr 出力する:
- 通常項目（成功 / pending / failed）: filename と enum 値のみ
- `orphan_alias_canonicals`: alias 設定不整合の通知用に **canonical 名を例外的に出力**（運用者が TOML を修正するために必要）

このため CLI ログは「事業所名を含む可能性がある PII データ」として扱う必要がある:
- ログファイル化禁止 / SaaS log aggregator (Sentry / Datadog 等) 送信禁止
- 運用者ローカル端末の stderr 出力に留める
- PR4 UI では本警告を専用ダイアログ（外部送信なし）で表示することで上記制約を構造的に保証する予定

### Windows 専用機能の検証戦略

`scripts/process_ex_files.py` の SFX ダイアログ自動操作（pywinauto）は Windows 実機でしか動作しない。PR3 で以下の構造に分離（実装確定）:

- **`SfxAdapter` Protocol**: `extract_pdf(exe_path, watch_dirs) -> Sequence[Path]` の最小契約。失敗時は `SfxExtractionFailed` を投げる（`partial_outputs` で部分生成 PDF を伝搬可能）
- **`WindowsSfxAdapter`**: 実機実装。constructor で `sys.platform != "win32"` なら `UnsupportedSfxPlatformError`。`pywinauto` は `_click_sfx_dialog` 内で **遅延 import**（macOS の dry-run / `--help` 動作保証）
- **`FakeSfxAdapter`**: テスト用。`produced_pdfs` / `raise_on_extract` / `side_effect` で全分岐を macOS で再現可能
- **macOS 単体テスト**（PR3 で実装、各 status 分岐網羅）: `.exe コピー → adapter 抽出 → PDF 移動 → cleanup` の SUCCESS / SKIPPED_AMBIGUOUS / SKIPPED_UNMATCHED / EXTRACT_FAILED / PARTIAL_OUTPUT / MOVE_FAILED 各分岐を fake adapter ベースで検証。`MOVE_IO_ERROR` / `partially_moved` / `UNEXPECTED` (ループ最外殻保護) / mtime フィルタ (Desktop 誤配布防止) も網羅
- **Windows 実機検証**: PR5 で実施、合格基準を ADR / TEST_PLAN に明記

### PR3 で確定した公開 API

`src/wiseman_hub/pdf/ex_extractor.py` (新規):

```python
def extract_one(
    ex_file: Path,
    facility_root_dir: Path,
    facility_names: list[str],
    aliases: dict[str, list[str]],
    adapter: SfxAdapter,
) -> ExtractionItem

def extract_directory(
    source_dir: Path,
    facility_root_dir: Path,
    aliases: dict[str, list[str]],
    adapter: SfxAdapter,
) -> ExtractionResult
```

結果型:
- `ExtractionStatus`: SUCCESS / SKIPPED_AMBIGUOUS / SKIPPED_UNMATCHED / EXTRACT_FAILED / PARTIAL_OUTPUT / MOVE_FAILED
- `ExtractionErrorCode`: SFX_LAUNCH_FAILED / SFX_TIMEOUT / NO_PDF_PRODUCED / MOVE_CONFLICT / **MOVE_IO_ERROR** / COPY_FAILED / CLEANUP_FAILED / UNSUPPORTED_PLATFORM / **UNEXPECTED**
- `ExtractionItem`: source_path / resolve_result / status / moved_pdfs / **partially_moved** / partial_outputs / error_code / error_detail / cleanup_warning（不変条件は `__post_init__` で強制、`partially_moved` は MOVE_FAILED 時のみ非空、`partial_outputs` と `partially_moved` は共存禁止）
- `ExtractionResult`: items / orphan_alias_canonicals / pending_filenames + プロパティ success_count / pending_manual / failed

### CLI 終了コード仕様（PR3 新規）

`scripts/process_ex_files.py` 薄ラッパーは旧版の 0/1 から拡張し、3 段階:

| code | 意味 | 旧版 |
|------|------|------|
| 0 | 全件 SUCCESS | 同（失敗 0 件） |
| 2 | 一部 pending（AMBIGUOUS / UNMATCHED が存在） | **新規**（旧版は 0 扱いだった） |
| 1 | 失敗あり（EXTRACT_FAILED / MOVE_FAILED / PARTIAL_OUTPUT）または致命的エラー | 同 |

優先順位: 1 > 2 > 0（失敗があれば 1、失敗なしで pending があれば 2）。これにより本田様の現行運用で「振り分けが止まったか」を CI / シェルスクリプト経由で機械的に判定可能。

## 結果

### Pros

- **誤配布リスクの構造的低減**: alias 優先 + AMBIGUOUS への手動回避で false positive を最小化
- **テスト容易性**: `facility_resolver` は純粋関数、UI / I/O から独立 → macOS で全網羅テスト可能
- **段階的レビュー可能性**: 5 PR 分割により各 PR のレビュー負荷が分散、設計判断ごとに承認取得
- **既存 ADR-013 と整合**: `facility_root_dir` を共有、事業所フォルダ判定ロジック流用

### Cons

- **PR 数増加**: 5 PR の段階的マージで全機能完成まで時間がかかる
- **手動振り分け UI の運用負荷**: AMBIGUOUS 判定が多いと UI 操作が増える → alias 登録で軽減を期待
- **Windows 実機検証の遅延**: PR3-5 完成まで実機統合動作が確認できない

### 中立

- 既存 `scripts/process_ex_files.py` は PR3 で薄いラッパーに置換し CLI 互換維持

## 関連

- ADR-012: facility_merger 出力仕様（事業所単位 1 ファイル ABCABC 連結）
- ADR-013: 事業所ルートフォルダ管理 + 一括/選択 PDF 結合（デスクトップアプリ統合）
- PR #130: PR1 設定スキーマ拡張（`ex_source_dir` + `facility_aliases`）
- Codex セカンドオピニオン（2026-04-27）: 1 PR 分割推奨 + マッチング戦略の安全設計
- 4 並列レビュー（PR #130, 2026-04-27）: code-reviewer / pr-test-analyzer / comment-analyzer / type-design-analyzer

## 未決事項

- AMBIGUOUS 判定の頻度実測（実機投入後にデータ収集）
- alias 自動学習（手動振り分け結果を alias に昇格する UX）の検討（PR4 で議論）
- `_PARTIAL_MATCH_DOMINANCE_THRESHOLD = 2` の妥当性検証（実例 50+ ファイル投入後）
