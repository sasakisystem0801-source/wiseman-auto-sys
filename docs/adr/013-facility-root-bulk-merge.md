# ADR-013: 事業所ルートフォルダ管理 + 一括/選択 PDF 結合（デスクトップアプリ統合）

## ステータス

**Accepted (2026-04-27)** — Session 26 で本田様の Windows 11 実機（`C:\Users\sasak\wiseman-hub\`）にて Acceptance Criteria 13 項目中 **11 項目を実機動作確認**（AC-1/2/3/4/7/8/10/11/12/13 + AC-6 完了サマリ messagebox 経由）、AC-5（チェック OFF は出力されない）はテスト 1 件実行で他事業所が未出力であることから間接確認、AC-9（ルート未設定/不在/アクセス不可）は次セッション送り（軽微・リスク低）。`\\Tera-station\share\03.FAX(事業所)` 配下の本番データ（40 事業所、実行可能 18 / 警告 22）スキャン + 1 事業所（`きなり(メール)※持参` 6 名結合、出力 1,672 KB）テスト実行で動作確認。**AC-13** は review-pr で発見した致命バグ（`PdfMergeError(__cause__=PermissionError)` ラップ経路）の修正が本番経路で機能していることを実機で確認（Acrobat ロック中に `failed_locked` ステータス + 「結合 PDF を閉じてから再実行してください」文言、サマリ「PDFロック: 1件」）。**AC-12** は再スキャン後に出力ファイル `{事業所名}.pdf` が `a_multiple` を引き起こさないことを実機で確認（再実行ループ防止）。

### 変更履歴

- 2026-04-27（Session 25）: 本 ADR 作成（Proposed）、PR #126 マージ
- 2026-04-27（Session 26）: Windows 実機検証完了 → Accepted 昇格

## コンテキスト

ADR-012（PR #124）で「事業所単位 1 ファイル ABCABC 連結」（`merge_facility`）が完成し、明日納品の業務要件を満たした。しかし運用形態として **1 回 1 事業所しか処理できない** 制約が残っており、ユーザーは A.pdf / 事業所フォルダ / 出力ルート を都度個別指定する必要があった。

本田様からの追加要望（2026-04-27）:

> 結合する A の PDF ファイルが存在するフォルダ（サブフォルダ：BC のあるサブフォルダと同じところ）が有るルートフォルダを設定して、一括対応と選択対応がデスクトップアプリから出来るようにしたい。デスクトップアプリは今後このシステムのスーパーアプリ的な位置づけにしていきたい。

実運用では複数事業所のフォルダが共通親ディレクトリ配下（例: `//Tera-station/share/03.FAX(事業所)/`）に並んでいるため、これを **ルートフォルダ** として 1 度設定すれば配下事業所を自動検出し、チェックボックス UI で一括 / 選択処理ができるようにすべき、という業務要求。

### 業務要件（ユーザー確定済）

1. **A.pdf 特定**: 事業所フォルダ直下の唯一の `*.pdf` を A とみなす（複数なら警告で実行不可）
2. **事業所判定**: `運動機能向上計画書/` AND `経過報告書/` 両方ある → 事業所
3. **出力先**: 各事業所サブフォルダ自身（`{root}/{事業所名}/{事業所名}.pdf`）
4. **UI**: チェックボックス複数選択 + 全選択/全解除 + 一覧から「フォルダを開く」「結合 PDF を開く」
5. **設定永続化**: TOML（`AppConfig.pdf_merge.facility_root_dir`）

### 制約

- **既存 `merge_facility` 互換維持**: PR #124 のテスト 19 件 + 実機検証投資を保護
- **介護施設職員（IT 非専門）**: UI は直感性最優先、エラー時は「PDFを閉じてから再実行」レベルの平易な日本語
- **クロスプラットフォーム**: macOS（dev）/ Windows（実機、UNC パス + 日本語事業所名）両対応
- **過剰実装禁止**: 「スーパーアプリ」化はビジョンとして共有するが、今回は基盤のみ実装

## 決定

### 機能構成（5 層）

| 層 | ファイル | 責務 |
|---|---------|------|
| 設定 | `config.py` | `PdfMergeConfig.facility_root_dir` で永続化 |
| スキャン | `pdf/facility_scanner.py` | ルート配下 → 事業所候補リスト（pure 関数） |
| 実行 | `pdf/facility_bulk_runner.py` | 候補 → 順次 `merge_facility` + status 管理 + 停止 |
| ViewModel | `ui/facility_root_dialog.py: FacilityRootViewModel` | UI 状態管理（pure Python、テスト容易） |
| Dialog | `ui/facility_root_dialog.py: FacilityRootManagerDialog` | Tk widget 薄ラッパー、ViewModel に依存 |
| OS 操作 | `utils/os_open.py` | macOS=open / Win=os.startfile / Linux=xdg-open |

### 状態遷移（事業所単位）

実行前ステータス（scanner、`FacilityStatus`）:

```
[*] -> pending（B/C両方あり、A.pdf 1件、{事業所名}.pdf除外後）
[*] -> a_missing（A.pdf 0件）
[*] -> a_multiple（A.pdf 2件以上）
a_multiple -> pending（ユーザーが1件選択後、selected_a_pdf セット）
```

実行中・実行後ステータス（runner、`BulkExecutionStatus`）:

```
pending -> running（チェック ON で実行）
pending -> [*]（チェック OFF でスキップ）
running -> success（report.success > 0）
running -> partial（report.success = 0、除外のみ）
running -> failed（例外、PII 防御で型名のみ）
running -> failed_locked（PermissionError → 「PDFを閉じてから再実行」文言）
running -> cancelled_skipped（「次の事業所から停止」後）
```

### A.pdf 特定の核心ロジック（AC-12）

事業所直下の `*.pdf` から **既存出力 `{事業所名}.pdf` を除外** したうえで件数判定する（`facility_scanner.py:_collect_a_candidates`）。

これを怠ると、再実行時に `{事業所名}.pdf` が「もう 1 つの A 候補」として認識され `A_MULTIPLE` 判定 → **永続的に実行不可ループ**に陥る。本 ADR の最重要バグ予防。

### Windows PDF lock 文言変換（AC-13）

`PermissionError` を `BulkExecutionStatus.FAILED_LOCKED` + 「結合 PDF を閉じてから再実行してください」に変換（`facility_bulk_runner.py:_MSG_LOCKED`）。Windows で出力 PDF が Acrobat 等で開かれている典型ケースで、IT 非専門ユーザーに行動可能な指示を出す。

### 一括実行の停止（cancel_event）

`threading.Event` を `run_bulk_merge` に渡し、事業所間の境界でチェック（現在処理中の `merge_facility` は中断しない）。N=20 件処理中に誤ルート気付いた時の運用ストレスを回避。完全キャンセル（`merge_facility` 中断）は MVP 外。

### 既存出力の上書き仕様（AC-10）

**無条件上書き**（ユーザー判断）。UI のサマリ「上書き: N 件」表示で「明示」要件を満たす。確認ダイアログは挟まない（N=20 件運用での煩雑さを回避）。

### 既存単一事業所ダイアログの扱い

`ui/facility_merger_dialog.py:FacilityMergerDialog`（PR #124）は **コード資産として残置**。UI からのアクセス経路は除去するが、import 互換は保ち、テスト 19 件 + Quality Gate 投資を保護する。新ダイアログは事業所が 1 つしかないルートでも動作するため機能劣化なし。

## 検討した代替案

### 代替案 1: 既存単一事業所ダイアログを完全置換（削除）

- 長所: コードベースが小さくなる、認知負荷低減
- 短所: PR #124 の Quality Gate 投資（19 テスト + 実機検証）を破棄、回帰時の安全網なし
- 判断: 残置（Codex セカンドオピニオン + Evaluator 同意）

### 代替案 2: 完全キャンセル機能（merge_facility 中断）

- 長所: ユーザーの即時停止要求に応える
- 短所: `_save_atomically` の途中中断で破損ファイル残置リスク、実装コスト大、N=1 事業所処理時間は数秒〜十数秒で実用上問題小
- 判断: 「次の事業所から停止」（事業所間境界チェック）に縮退、MVP 範囲

### 代替案 3: 上書き確認ダイアログ

- 長所: 誤上書き事故を防ぐ
- 短所: N=20 件運用でクリック数増加、ユーザー要求は「無条件上書き」
- 判断: サマリ表示のみで明示、確認ダイアログなし。Evaluator は MEDIUM 懸念だが業務判断で受容

### 代替案 4: 進捗パーセント（merge_facility 中の途中進捗）

- 長所: ユーザー安心感
- 短所: `merge_facility` への callback 追加が破壊的変更、ROI 低
- 判断: 行ごとのステータス（処理中… → 完了）で十分、MVP 範囲外

### 代替案 5: ttkbootstrap / tksheet 等の追加 UI ライブラリ

- 長所: チェックボックス付きリストが標準提供される
- 短所: 追加依存が PyInstaller 配布バンドルサイズに影響、依存管理コスト
- 判断: 標準 `ttk.Frame` + 行ごと `Checkbutton` で実装（追加依存なし）

## 影響

### 肯定的

- **業務要件達成**: ルート設定 1 回で配下事業所の一括 / 選択処理が可能、N=20 事業所運用が現実的
- **設定永続化**: 次回起動時に自動スキャンで前回の作業に復帰
- **誤実行防止**: A_MISSING / A_MULTIPLE 状態の可視化と実行不可ガード
- **再実行ループ防止（AC-12）**: 既存出力ファイルを A 候補から除外する核心ロジック
- **Windows lock 対応（AC-13）**: 介護現場で頻発する「PDFを閉じて再実行」を文言で誘導
- **実行中断オプション**: N=20 件処理中の運用ストレス回避（次の事業所から停止）
- **PII 防御継承**: scanner / runner / Dialog すべてで「絶対パス・full_name 出さない」規律を維持
- **テスト容易性**: ViewModel を pure Python に分離、94 件の新規テストで AC 検証
- **後方互換**: `merge_facility` シグネチャ無変更、既存 19 テスト全 PASS 実測

### 否定的

- **コードベース肥大化**: 新規 4 ファイル（src）+ 4 ファイル（tests）+ 既存 4 修正、計 12 ファイル / +2620 行
- **既存単一事業所ダイアログの UI 経路除去**: コード資産は残るが、エンドユーザーは新ダイアログに統一される。慣れの再構築コスト
- **Tk Toplevel の smoke テスト未実装**: ViewModel ロジックは 28 テストでカバーするが、Tk Widget 統合は Windows 実機検証に依存
- **「スーパーアプリ」化はまだ着手せず**: ランチャーボタン構造は維持、機能タブ・サイドバー等の本格 UI 拡張は未来の判断
- **ユーザー名 / フリガナ抽出の余地**: 真の五十音順や PII 周りの拡張は ADR-012 の議論を継承

### 業務リスク（次セッション対応候補）

Evaluator 分離プロトコルの指摘から:

| 重要度 | 内容 | 対応方針 |
|--------|------|---------|
| MEDIUM | 上書き確認ダイアログなし | ユーザー判断「無条件上書き」確定済、UI サマリで明示。実機運用で問題が出たら追加検討 |
| LOW | A_MULTIPLE 解決後も「PDF選択...」ボタン残置 | 機能上問題なし、UI 細部は次回 |
| エッジ | UNC パスでの scanner / merge_facility 実ファイル検証なし | ✅ Session 26 で本番 UNC パス + 日本語事業所名で動作確認、解消 |

## Acceptance Criteria（13 項目、本 PR で macOS テスト全 PASS）

| # | 基準 | 検証 | 状況 |
|---|------|------|------|
| AC-1 | ルートフォルダ設定の永続化（再起動後復元） | テスト + 手動 | ✅ macOS PASS |
| AC-2 | B/C 両方あるフォルダのみ列挙 | scanner 単体 | ✅ |
| AC-3 | A.pdf 0 件 → A_MISSING 表示 | scanner + ViewModel | ✅ |
| AC-4 | A.pdf 2 件以上 → A_MULTIPLE、ファイル選択するまで実行不可 | scanner + ViewModel | ✅ |
| AC-5 | チェック OFF は出力されない | bulk runner 統合 | ✅ |
| AC-6 | 1 件失敗で残り続行 + サマリで件数明示 | bulk runner | ✅ |
| AC-7 | 「フォルダ/PDF を開く」が macOS/Windows 両対応 | os_open + 手動 | ✅ macOS / ✅ Windows 実機（Session 26、Explorer + Adobe Acrobat 両方起動確認） |
| AC-8 | 既存 merge_facility シグネチャ + 19 テストが PASS | pytest | ✅ 19/19 PASS 実測 |
| AC-9 | ルート未設定/不在/アクセス不可で明示表示 | UI + 異常系 | ✅ |
| AC-10 | 既存出力は無条件上書き + UI に明示 | bulk runner + サマリ | ✅ |
| AC-11 | 日本語/UNC パスで scan/open/merge が失敗しない | UNC モック + 手動 | ✅ macOS / ✅ Windows UNC 実機（Session 26、`\\Tera-station\share\03.FAX(事業所)` で日本語事業所名 + `(FAX)/(メール)` サフィックス含めて文字化けなし、scan/merge 成功） |
| AC-12 | A.pdf 候補から `{事業所名}.pdf` を除外 | scanner 単体 | ✅（最重要、3 パターン PASS） |
| AC-13 | Windows lock → 「PDFを閉じてから再実行」文言変換 | bulk runner + UI | ✅ Windows 実機（Session 26、Acrobat ロック中の `failed_locked` + 「結合 PDF を閉じてから再実行してください」文言、サマリ「PDFロック: 1件」、ロック解消後の再実行成功も確認） |

## 実装

PR `feat/facility-root-bulk-merge`（Session 25、本 ADR）:

| 変更ファイル | 内容 | テスト |
|------------|------|-------|
| `src/wiseman_hub/config.py` | `PdfMergeConfig.facility_root_dir` 追加 | +5（既存 20 → 25） |
| `src/wiseman_hub/utils/os_open.py` | クロスプラットフォーム open 新設 | +8 |
| `src/wiseman_hub/pdf/facility_scanner.py` | scan + 出力ファイル除外（AC-12） | +19 |
| `src/wiseman_hub/pdf/facility_bulk_runner.py` | 一括実行 + 停止 + lock 文言（AC-6/13） | +14 |
| `src/wiseman_hub/ui/facility_root_dialog.py` | ViewModel + Dialog（W4 + Evaluator HIGH/MEDIUM 反映） | +28 |
| `src/wiseman_hub/__main__.py` | 新ダイアログをランチャー導線に統合 | 既存回帰なし |
| `src/wiseman_hub/ui/launcher.py` | ボタンラベル「事業所フォルダ一括結合」 | 既存回帰なし |

**Quality Gate**:
- TDD（RED → GREEN）: 各 W で先にテスト作成 → 実装 → 全 PASS
- pytest 633 passed / 68 skipped / lint clean / mypy clean
- **Generator-Evaluator 分離**: Evaluator から HIGH (X ボタン未バインド) + MEDIUM (logger.exception パス漏洩) を指摘、修正コミット `48a1a72` で対応
- 6 commits + 1 修正コミット、+2620 行

### Evaluator 分離プロトコルの効果

`agents/evaluator.md` の AC 13 項目検証で以下を独立コンテキストで発見:

1. **HIGH (X ボタン未バインド)**: `WM_DELETE_WINDOW` を `_on_close` に bind 漏れ → 実行中の強制クローズで worker thread 宙吊り
2. **MEDIUM (logger.exception)**: scan エラーログでトレースバック経由のパス漏洩
3. **エッジ (busy 中の再スキャン)**: progress_callback サイレント失敗予防

これらは 6 並列レビュー（PR #124 で実施）では未検出だった盲点で、Evaluator の独立判定の価値を改めて確認した。

## Session 26 実機検証結果（Accepted 昇格根拠）

### 検証環境

- **PC**: 本田様 Windows 11 実機（`C:\Users\sasak\`）
- **本番データ**: `\\Tera-station\share\03.FAX(事業所)\`（40 事業所、`(FAX)` / `(メール)` サフィックス付き日本語名）
- **配布 exe**: `78,570,672 bytes` / `2026/04/27 7:13:10` ビルド（`d83a3de` HEAD で再ビルド + 配布）
- **テスト対象事業所**: `きなり(メール)※持参`（6 名分の運動機能向上計画書 + 経過報告書）

### 実測結果

| 検証項目 | 期待 | 実測 | 判定 |
|---------|------|------|------|
| ランチャーボタンラベル | 「事業所フォルダ一括結合」 | 「事業所フォルダ一括結合」 | ✅ |
| 配下事業所スキャン | 40 件列挙、B/C 両方ある事業所のみ実行可能 | 18 実行可能 / 22 警告 | ✅ |
| `a_missing` 表示 | 「⚠ 事業所直下にPDFがありません」 | 一致 | ✅ AC-3 |
| `a_multiple` 表示 + PDF選択ボタン | 「⚠ PDFが複数あります → 1つ選択してください」+ 「PDF選択...」 | 一致 | ✅ AC-4 |
| サマリ表示 | 選択中 / 実行不可 / 上書き | 「選択中: 18件 / 実行不可: 22件 / 上書き: 0件」 | ✅ |
| 1 事業所結合実行 | 6 名分 ABCABC 連結、`{事業所名}.pdf` 生成 | `きなり(メール)※持参.pdf` 1,672 KB 生成 | ✅ AC-8 |
| 完了サマリ messagebox | 5 status 別件数表示 | 「完了: 1件 / 結合対象なし: 0件 / PDFロック: 0件 / エラー: 0件 / 未処理(停止): 0件」 | ✅ AC-6 / review-pr LOW-1 |
| **AC-12 再スキャン後** | `{事業所名}.pdf` が A 候補から除外、`a_multiple` にならない | 再スキャン後「実行待ち」表示維持（`a_multiple` 不発火） | ✅ **最重要** |
| AC-7 フォルダ/PDF を開く | Explorer + デフォルト PDF ビューア起動 | Explorer + Adobe Acrobat 両方起動 | ✅ |
| **AC-13 Acrobat ロック中再実行** | `failed_locked` + 「PDFを閉じてから再実行」文言、サマリ「PDFロック: 1件」 | 「⚠ 結合 PDF を閉じてから再実行してください」+ サマリ「PDFロック: 1件 / 上書き: 1件」 | ✅ **最重要、本番経路バグ予防** |
| AC-13 補足（ロック解消後） | 再実行成功 | 「完了: 1件 / PDFロック: 0件」、出力ファイル更新 | ✅ |
| AC-1 永続化 | ランチャー再起動でルート復元 + 自動スキャン | UNC ルート欄表示維持 + 自動スキャン完走 | ✅ |
| AC-10 既存上書き明示 | サマリ「上書き: 1件」 | 一致 | ✅ |

### 未解決の観察事項（追跡中）

ADR の永続性を保つため、追跡課題の詳細は handoff ドキュメントで管理する（`docs/handoff/LATEST.md` 参照）:

- **元 `a_missing` 状態の事業所が結合実行で成功**: 初回スキャンと A.pdf 配置タイミングの競合可能性。本田様による A.pdf 手動配置が原因の可能性が高く、実装側のバグの根拠は未確認。
- **`a_missing` → 「実行待ち」遷移**: 「再スキャン」ボタンで正常に状態更新されることを実機で確認、scanner ロジック自体は正常動作。

## 次ステップ

### 短期（Session 26 で完了 ✅）

- **Windows 実機検証**: 本田様の `C:\Users\sasak\wiseman-hub\` で AC-7 / AC-11 / AC-12 / AC-13 を含む 11 項目を実機動作確認（上記「Session 26 実機検証結果」参照）
- **配布 exe 再ビルド**: PyInstaller onefile 78,570,672 bytes 生成 + 配布完了（`d83a3de` HEAD）
- **ADR-013 Accepted 昇格**: 本コミットで実施

### 中期

- **「次の事業所から停止」UI 改善**: 残り N 件 / 完了 M 件の進捗バー表示（業務リスク MEDIUM）
- **A_MULTIPLE 解決後 UI**: 「PDF選択...」ボタンの動的非表示（Evaluator LOW 指摘）
- **複数ルート切替（履歴）**: 複数の親ディレクトリを切り替えて使う運用が出てきた場合

### 長期（「スーパーアプリ」化の方向性）

ユーザービジョン「デスクトップアプリは今後このシステムのスーパーアプリ的な位置づけ」を実現するための方向:

- ランチャーをタブ / サイドバー UI に再構成（Phase A/B / 確認待ち / 事業所一括 / 設定 / 履歴）
- 機能横断のグローバル状態管理（settings / sessions / facility roots を統一）
- 配布 exe の自動更新メカニズム（ADR-004 の延長）

ただしこれらは過剰実装のリスクが高く、本田様の運用フィードバックを 1〜2 セッション蓄積してから着手判断する。

## 参考

- **ADR-012**: facility_merger 出力仕様（事業所単位 1 ファイル ABCABC 連結）— 本 ADR の前提
- **ADR-007**: USB ドングル認証 — 認証フローと独立
- **ADR-009**: UI 技術選定（tkinter）— 本 ADR の UI レイヤーが踏襲
- **ADR-011**: 配布形式（PyInstaller onefile）— 配布 exe 再生成は同手順
- **PR #124**: ADR-012 の実装、`merge_facility` 単一事業所版
- **rules/quality-gate.md**: Generator-Evaluator 分離プロトコル
- `docs/handoff/folder-merger-mvp-runbook.md`: 旧仕様の運用ランブック（本 ADR 反映で次セッション更新）
- `docs/handoff/1c-exe-redistribution-runbook.md`: exe 再配布手順
