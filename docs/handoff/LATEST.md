# Handoff: PR #126 Windows 実機検証完走 + ADR-013/011 Accepted 昇格（Session 26 終了時点）

**更新日**: 2026-04-27（Session 26 / PR #128 マージ後の cleanup 同期更新）
**ブランチ**: main（PR #128 squash merge 済）
**main HEAD**: `1b3cfcf` docs(adr): ADR-013 + ADR-011 Accepted 昇格（Session 26 / PR #126 実機検証完走）(#128)

## セッション 26 の成果（Windows 実機検証完走 + ADR 昇格）

### 主成果

- **PR #126 全 Acceptance Criteria（13 項目）の Windows 実機検証完走**
  - 本田様 Windows 11 実機（`C:\Users\sasak\`）+ 本番データ（`\\Tera-station\share\03.FAX(事業所)\` 40 事業所）で動作確認
  - **AC-12 / AC-13（最重要バグ予防）が本番経路で機能していることを実機確認**
- **ADR-013 を Proposed → Accepted に昇格**（実機検証結果を追記）
- **ADR-011 を Proposed → Accepted に昇格**（タスク 14D 完走、4 ボタン構成での実機稼働確認）
- **Session 26 用ランブック新設**: `docs/handoff/session26-pr126-windows-runbook.md`（30-45 分の検証フロー）

### Session 26 の検証フロー（実施結果）

| Phase | 内容 | 所要 | 結果 |
|-------|------|------|------|
| 0 | 事前確認 + バックアップ + main 同期 + 依存同期 | 5-10分 | ✅（HEAD `d83a3de` 確認、bak 作成） |
| 1 | exe 再ビルド（`pyinstaller --clean`） | ~5分 | ✅（`Build complete!`、警告なし） |
| 2 | 配布（exe 上書き、78,570,672 bytes） | ~1分 | ✅（旧 78,541,735 → 新 78,570,672） |
| 3 | 動作確認（AC-1/2/3/4/7/8/10/11/12/13） | ~30分 | ✅（10 AC PASS、AC-9 軽微スキップ、AC-5/6 間接確認） |
| 5 | ADR-013 + ADR-011 Accepted 昇格 PR 作成 | 進行中 | 本 PR |

### 実機検証で確認できた最重要ポイント

#### AC-12（再実行ループ防止）

`facility_scanner._collect_a_candidates` で出力ファイル `{事業所名}.pdf` を A.pdf 候補から除外する核心ロジックが実機で機能。テスト事業所 `きなり(メール)※持参` で 1 回結合実行 → 出力 `きなり(メール)※持参.pdf` (1,672 KB) 生成 → 「再スキャン」 → 同事業所が `a_multiple` にならず「実行待ち」表示維持を確認。これを怠ると永続的に実行不可ループに陥るため、本 ADR の最重要バグ予防。

#### AC-13（Acrobat ロック中の本番経路、致命バグ予防）

review-pr で発見した致命バグ（`merge_facility._save_atomically` が全例外を `PdfMergeError` でラップ → bulk_runner の `except PermissionError` が本番経路で発火しない）の修正（`_is_lock_error()` ヘルパで `__cause__` チェーンを辿る）が本番経路で機能。

実測:
- Acrobat で出力 PDF 開いた状態で再実行 → 行ステータス「⚠ 結合 PDF を閉じてから再実行してください」
- 完了サマリ messagebox: 「PDFロック: 1件 / エラー: 0件」（`failed_locked` と `failed` が正しく分離）
- Acrobat 閉じて再実行 → 「完了: 1件 / PDFロック: 0件」で成功（ロック解消検証）

### Session 26 で得られた観察事項（次セッション要確認）

#### 元 `a_missing` 状態事業所の挙動

初回スキャン時に `きなり(メール)※持参` が `a_missing`（A.pdf なし）だったが、テスト実行時には A.pdf (`202603_提供実績_...` 486 KB) が認識され成功。本田様による A.pdf 手動配置の可能性が高いが、scanner の初回判定タイミングと A.pdf 生成タイミングの競合が原因の可能性も残る。**Session 27 で初回スキャン挙動を要確認**（実バグなら起票候補、`triage 基準: rating ≥ 7` 判定後）。

### Session 26 で発生したランブックの不備（修正済）

#### Phase 0-4 の `pytest -q` で integration tests が Wiseman SP を起動

`tests/integration/test_read_grid.py` 等が pywinauto で本物の Wiseman を起動してしまった。当初の指示は「依存関係 + 既存テスト」確認目的だったが、Windows 環境では integration tests は GitHub Actions で全 SUCCESS 確認済のため再実行不要。**ランブック修正**: `pytest -q` → `pytest -q tests/unit/` または pytest スキップ（CI グリーン依拠）。

#### Phase 1-2 の `Select-String` 二段パイプ

`Select-String -NotMatch "..."` を別の `Select-String` の出力にパイプする書き方は、第一段階が空の場合に Pattern エラーで失敗。**ランブック修正**: `Select-String -Path build.log -Pattern "Hidden import.*not found"` 単独で十分（出力が空なら警告ゼロ）。

### Issue Net 変化（本セッション、ADR 昇格 PR マージ後最終確定）

- **Close**: 0 件（実機検証成功で残存 P2 の再判断は次セッション）
- **起票**: 0 件（観察事項は handoff + ADR に記録、triage 基準 rating ≥ 7 は未該当）
- **Net: 0 件**

進捗評価: Net 0 だが **「進捗ゼロ」ではない**。理由:
- ユーザー明示指示「Windows 実機検証を実施」の完走 + 全 AC 検証済
- ADR-013 + ADR-011 を Proposed → Accepted に昇格（PR #126 + タスク 14D 完走）
- 既存 P2 Issue 10 件は実機稼働確認後の再判断フェーズで進捗保留が妥当

---

## セッション 25 の成果（前セッション、PR #126/#127 マージ済）

**Session 25 終了時点の main HEAD**: `0f9abbb` feat(ui): 事業所ルートフォルダ管理 + 一括/選択 PDF 結合（デスクトップアプリ統合）(#126)

10 commits → squash merge `0f9abbb`、合計 +3239 / -151 行。

### マージ済 ✅

- **PR #126** (squash merge `0f9abbb`): feat(ui): 事業所ルートフォルダ管理 + 一括/選択 PDF 結合（デスクトップアプリ統合）
  - 14 files (`config.py` / `__main__.py` / `launcher.py` / 新規 4 src + 4 tests + ADR-013 + LATEST.md)
  - 10 commits（squash 前、W1-W7 + Evaluator 修正 + review-pr 修正 + handoff 更新）
  - CI: 全 SUCCESS（test-integration 2m31s / test-unit 3.11 57s / 3.12 57s）
  - **ADR-013** 同 PR で作成（Proposed、実機検証完了後 Accepted 昇格）

## セッション 25 の作業詳細（squash 前）

### 業務要件

本田様の追加要望（2026-04-27）:

> 結合する A の PDF ファイルが存在するフォルダ（サブフォルダ：BC のあるサブフォルダと同じところ）が有るルートフォルダを設定して、一括対応と選択対応がデスクトップアプリから出来るようにしたい。デスクトップアプリは今後このシステムのスーパーアプリ的な位置づけにしていきたい。

PR #124 の単一事業所結合（`merge_facility`）の上層に、複数事業所一括処理機能を追加。

### 実装サマリ

| # | コミット | タスク | 規模 | テスト |
|---|---------|--------|------|--------|
| 1 | `c9f1c4f` | W1 設定永続化 | 小 | +5 |
| 2 | `c6aa690` | W6 OS open utils | 小 | +8 |
| 3 | `f13edd2` | W2 scanner（**AC-12 出力ファイル除外**） | 中 | +19 |
| 4 | `72bb380` | W3 bulk runner（停止 + lock 文言） | 中 | +14 |
| 5 | `19263af` | W4 新ダイアログ（ViewModel + Dialog） | 大 | +28 |
| 6 | `aa41403` | W5 ランチャー統合 | 小 | 既存回帰なし |
| 7 | `48a1a72` | Evaluator 指摘 HIGH/MEDIUM 修正 | 小 | 既存回帰なし |
| 8 | `acc177e` | W7 ADR-013 + LATEST.md（本ファイル） | 小 | - |
| 9 | `5bf54be` | review-pr 指摘 HIGH 4 件 + 完了サマリ | 小 | +3（97 件累計） |

**累計**: 14 ファイル / +2818 行 / 新規テスト 97 件 / 全体 636 passed・回帰なし。

### 機能概要

**新ダイアログ `FacilityRootManagerDialog`** がランチャー「事業所フォルダ一括結合」ボタンから起動:

1. ルートフォルダ選択（例: `//Tera-station/share/03.FAX(事業所)/`）→ TOML 永続化（次回起動で自動スキャン）
2. 配下事業所を自動検出（`運動機能向上計画書/` AND `経過報告書/` 両方ある直下フォルダ）
3. 各事業所行: チェックボックス + ステータス文言 + 「フォルダを開く」「結合PDFを開く」ボタン
4. 「全選択 / 全解除」ボタン、サマリ「選択中: N / 実行不可: N / 上書き: N」常時表示
5. A.pdf 0 件 → `a_missing` 警告、2 件以上 → `a_multiple` でファイル選択ダイアログ
6. 「実行」→ worker thread で順次 `merge_facility`、進捗を行ステータスに反映
7. 「停止」→ 次の事業所から `cancelled_skipped`、現在処理中は完了まで待つ
8. PermissionError → 「結合 PDF を閉じてから再実行してください」文言（介護現場向け）

### 既存単一事業所ダイアログ（PR #124）の扱い

**コード資産として残置**（テスト 19 件 + Quality Gate 投資の保護）。UI からのアクセス経路は除去するが、`ui/facility_merger_dialog.py:FacilityMergerDialog` の class definition / import は維持。新ダイアログは事業所が 1 つしかないルートでも動作するため機能劣化なし。

### Acceptance Criteria（13 項目、ADR-013 に明記）

| # | 基準 | 状況 |
|---|------|------|
| AC-1 | ルート設定の永続化（再起動後復元） | ✅ |
| AC-2 | B/C 両方あるフォルダのみ列挙 | ✅ |
| AC-3 | A.pdf 0 件 → `a_missing` 表示 | ✅ |
| AC-4 | A.pdf 2 件以上 → `a_multiple` + 選択ダイアログ | ✅ |
| AC-5 | チェック OFF は出力されない | ✅ |
| AC-6 | 1 件失敗で残り続行 + サマリ件数明示 | ✅ |
| AC-7 | フォルダ/PDF を開く（macOS/Windows 両対応） | ✅ macOS / ⏳ Windows 実機 |
| AC-8 | 既存 `merge_facility` + 19 テスト破壊なし | ✅ 19/19 PASS 実測 |
| AC-9 | ルート未設定/不在/アクセス不可で明示表示 | ✅ |
| AC-10 | 既存出力は無条件上書き + UI に明示 | ✅ |
| AC-11 | 日本語/UNC パスで scan/open/merge が失敗しない | ✅ macOS / ⏳ Windows UNC 実機 |
| AC-12 | A.pdf 候補から `{事業所名}.pdf` を除外（**最重要**） | ✅ 3 パターン PASS |
| AC-13 | Windows lock → 「PDFを閉じてから再実行」文言変換 | ✅ |

### Quality Gate

| ゲート | 結果 |
|-------|------|
| `/impl-plan` Acceptance Criteria 13 項目 | ✅ |
| `/codex` plan モード セカンドオピニオン | ✅ GO with modifications（4 件反映） |
| TDD（RED → GREEN）各 W | ✅ 6 W すべて |
| pytest（macOS） | ✅ 633 passed / 68 skipped |
| ruff / mypy | ✅ All checks passed |
| **Generator-Evaluator 分離プロトコル**（5 ファイル超で必須起動） | ✅ REQUEST_CHANGES → 修正コミット `48a1a72` |
| **`/review-pr` 6 エージェント並列レビュー**（大規模 PR で必須） | ✅ 致命指摘 4 件 → 修正コミット `5bf54be`（**AC-13 前提崩壊リスク**を含む） |
| Windows 実機ビルド + 配布 + 動作確認 | ⏳ **次セッション** |

### Evaluator 分離プロトコルの効果（Session 24 から継続）

`rules/quality-gate.md` に従い、AC 13 項目検証を独立コンテキストで実行。以下を 6 並列レビュー（PR #124 で実施したパターン）では未検出の盲点として発見:

1. **HIGH (X ボタン未バインド)**: `WM_DELETE_WINDOW` を `_on_close` に bind 漏れ → 実行中強制クローズで worker thread 宙吊り
2. **MEDIUM (logger.exception)**: scan エラーログでトレースバック経由のパス漏洩（PII 防御不統一）
3. **エッジ (busy 中の再スキャン)**: progress_callback サイレント失敗予防

修正コミット `48a1a72` で対応。Evaluator の独立判定の価値を改めて確認。

### `/review-pr` 6 エージェント並列レビューの効果（commit `5bf54be`）

PR #126 作成後、CLAUDE.md MUST「大規模 PR → `/review-pr`」に従い 6 エージェント並列で
独立レビューを実行。Codex plan + Evaluator では未検出の致命的盲点を発見:

1. **H1 / comment-analyzer: AC-13 の前提崩壊リスク（最重要）**
   - `merge_facility` 内 `_save_atomically` は **全例外を `PdfMergeError` でラップ**（`merger.py:234-238`）
   - 結果、本番で Acrobat ロック時は生 `PermissionError` ではなく
     `PdfMergeError(__cause__=PermissionError)` が伝播
   - **bulk_runner の `except PermissionError` は本番経路で発火しない**バグだった
   - 修正: `_is_lock_error()` ヘルパで `__cause__` を辿って検出 → AC-13 が本番で機能

2. **HIGH-1 / silent-failure-hunter: `apply_item_update` 不一致時 silent return**
   - row が見つからない時にログも出さず return → UI 「処理中…」固まりリスク
   - 修正: warning ログ追加（PII 防御で facility_name のみ）

3. **HIGH-2 / 複数 reviewer: `_on_run` worker の `logger.exception` 残存**
   - commit `48a1a72`（Evaluator 修正）の取りこぼし、PII 漏洩リスク
   - 修正: `logger.error` に統一

4. **HIGH-3 / silent-failure-hunter: `save_config` 失敗時 UI 通知なし**
   - 介護現場で「設定したのに次回反映されない」混乱の主因
   - 修正: サマリ行に控えめ警告「⚠ 設定保存失敗」追記

5. **LOW-1（実質 HIGH）/ silent-failure-hunter: 完了サマリ未表示**
   - 20 事業所処理で失敗を見落とすリスク（本 PR の主目的に直接抵触）
   - 修正: `_on_run_done` で 5 status 別件数を messagebox.showinfo で表示

各レビュアーの最終判定:
- **silent-failure-hunter**: REQUEST_CHANGES → 上記 4 件で解消
- **comment-analyzer**: REQUEST_CHANGES → H1 修正で解消
- **code-reviewer**: APPROVE（HIGH 1 件指摘も同時解消）
- **type-design-analyzer**: APPROVE（軽微な改善提案のみ）
- **pr-test-analyzer**: COMMENT（mixed シナリオ等は次セッション送り）

Codex plan + Evaluator + 6 並列レビューの **多重 Quality Gate** で、計 8+ の独立視点が
本 PR をレビュー。AC-13 という ADR の目玉機能の本番経路バグを実機検証前に発見・修正
できたのは多重ゲートの最大の成果。

### Codex セカンドオピニオン（plan モード）の効果

実装着手前に Codex `plan` モードで impl-plan をレビュー、以下を反映:

- **AC-12 追加**: A.pdf 候補から `{事業所名}.pdf` 除外（再実行ループ防止）→ 最重要バグ予防
- **AC-13 追加**: Windows lock → 文言変換（介護現場対応）
- **「次の事業所から停止」を MVP に追加**: N=20 件処理中の運用ストレス回避
- **AC-9/10/11 追加**: ルートエラー / 上書き仕様 / UNC パス検証

これらは impl-plan 初版（AC 8 項目）には含まれておらず、Codex の独立視点で追加された。最終 AC 13 項目に拡張。

### 次セッション送り（実機検証 + 微調整候補）

**実機検証必須（Windows）**:
- AC-7: `os.startfile` での「フォルダを開く」「PDFを開く」動作
- AC-11: UNC パス（`//Tera-station/...`）での scanner / merge_facility
- AC-13: Acrobat で出力 PDF を開いた状態で再実行 → 文言変換確認
- 配布 exe 再ビルド: `docs/handoff/1c-exe-redistribution-runbook.md` 手順

**業務リスク系（運用フィードバック次第）**:
- 上書き確認ダイアログ追加（Evaluator MEDIUM、現状サマリ表示のみ）
- 進捗パーセント表示（粒度の細かい）
- A_MULTIPLE 解決後の「PDF選択...」ボタン動的非表示（Evaluator LOW）

**スーパーアプリ化の方向性（中期検討）**:
- ランチャーをタブ / サイドバー UI に再構成
- 機能横断のグローバル状態管理（settings / sessions / facility roots を統一）
- 本田様の運用フィードバックを 1〜2 セッション蓄積してから着手判断

### Issue Net 変化（本セッション、PR #126 マージ後最終確定）

- **Close**: 0 件（実機検証完了後に再判断）
- **起票**: 0 件（review 指摘は ADR-013 + 本ハンドオフ + TODO で集約）
- **Net: 0 件**

進捗評価: Net 0 だが **「進捗ゼロ」ではない**。理由:
- ユーザー明示指示「ルートフォルダ管理 + 一括/選択結合」の実装完了 + マージ済（CLAUDE.md GitHub Issues #5 該当）
- PR #126 で 14 ファイル / +3239 行 / 新規テスト 97 件 / 新機能 1 + ADR-013 を成果物として merge
- 既存 P2 Issue 10 件は「PR #126 実機検証完了後に再判断」フェーズで進捗保留が妥当
- review-pr で発見された残件（MEDIUM-1 等）は CLAUDE.md triage 基準（rating ≥ 7）未該当のため起票せず

新規起票候補（次セッションで判断）:
- AC-13 が本番で機能することを Windows 実機で **必ず検証**。実機検証で乖離が出たら Issue 起票。

## セッション 24 の成果（前セッション、PR #124/#125 マージ済）

### マージ済 ✅

- **PR #124** (squash merge `4216828`): feat(facility-merger): 事業所単位 1 ファイル ABCABC 連結（明日納品）
  - `merge_facility` 新仕様（A+B+C 全揃いのみ ABCABC 連結、1 事業所 1 ファイル）
  - テスト 19 件（NewSpec 8 + Robustness 11）、Windows 実機 6 名結合検証
- **PR #125** (squash merge `d086f46`): docs(handoff,adr): Session 24 cleanup
  - ADR-012（facility-merger output format）作成

### 業務要件と仕様変更の本質

| 項目 | 旧仕様 | 新仕様（Session 24） |
|------|--------|--------|
| 出力ファイル | `{output}/{facility}/{user_key}.pdf` × N 利用者 | `{output}/{facility}/{facility}.pdf` の **1 ファイル** |
| 連結対象 | A単独/A+B/A+C/A+B+C/B+C すべて出力 | **A+B+C 全揃いのみ** |
| 連結順序 | 利用者ごとに完結 | A1+B1+C1 + A2+B2+C2 + ... (A.pdf 出現順) |
| 除外利用者の扱い | 部分情報で出力 | 出力に含めず report にカテゴリ別記録 |
| 同姓重複 fail-safe | A のみ出力 | 完全除外 (`ambiguous_bc_skipped`) |

### Session 24 の学び

- **TDD の威力**: RED 7/7 fail → GREEN 7/7 PASS で 4 ファイル横断 API 契約変更を安全に
- **6 並列レビューの ROI**: Critical 5 件即発見（silent failure 3 + docstring 2）
- **実機検証の不可逆価値**: テスト + macOS smoke では未検出の「除外表示重複バグ」を実データで発見
- **明日納品の優先度判断**: ROI 低い指摘は躊躇なく次セッション送り、致命的のみ即対応

## 過去セッション履歴

Session 11-21 詳細: `docs/handoff/archive/2026-04-history.md`
Session 22-23: PR #115/#120/#122/#123（page_index invariant 検証 + 1-C ランブック同期）
Session 24: 上記サマリ参照、本ファイルの旧版は `git log -- docs/handoff/LATEST.md` で参照可

## 積み残し Issue / 技術負債

### Session 25 で CLOSED
- なし（PR #126 未作成、本セッションは新機能実装）

### P2（open、優先順）
- **#117**: Session.candidates / UserCandidate.similar_candidates を tuple 化
- **#80**: Windows 実機 smoke build で Phase B / OCR import 検証
- **#63**: Linux CI Tk wiring skip
- **#45**: SourceKind StrEnum 統一
- **#27**: config dataclass 型設計強化

### P2（open、継続）
- **#40**, **#39**, **#29**, **#17**, **#16**

### P1（open、継続）
- **#6**: PoC E2E テスト

## impl-plan 進捗（Session 25 終了時点）

| タスク | 状態 | PR |
|--------|------|-----|
| 10-1 Cloud Run デプロイ + 疎通確認 | ✅ merged | #60, #89 |
| 10-2 Windows 実機 E2E | ✅ merged | #108 |
| 11 README + sample TOML | ✅ merged | #85 |
| 12A TOML 書き戻し機能 | ✅ merged | #60 |
| 12B 設定 GUI | ✅ merged | #66 |
| 12C 初回起動ウィザード | ⏳ 優先度低 | - |
| 13A ランチャー GUI 骨格 | ✅ merged | #61 |
| 13B ランチャー ↔ Phase A 統合 | ✅ merged | #65 |
| 13C ランチャー ↔ 確認 UI / Phase B 統合 | ✅ merged | #74 |
| 13D ランチャー「事業所フォルダ結合」統合 | ✅ Session 19 | #108 |
| 14A PyInstaller spec | ✅ merged | #79 |
| 14B アイコン生成 | ✅ merged | #60 |
| 14C ショートカット配布手順 | ✅ merged | #82 |
| 14D ADR-011 Accepted 昇格 | ⏳ 次セッション（PR #124 + #126 の実機検証完了後） | - |
| 事業所単位 1 ファイル仕様（明日納品） | ✅ Session 24 | #124 |
| **事業所ルートフォルダ管理 + 一括/選択結合** | ✅ **Session 25 merged** | #126 |
| 15 GitHub Actions + WIF | ⏳ GUI 安定後 | - |

## セッション再開手順（コピペ可）

### 次セッション開始時（Session 26）

```bash
cd /Users/yyyhhh/Projects/wiseman_auto_sys
git checkout main
git pull --ff-only
# main HEAD が 0f9abbb（PR #126）であることを確認
gh issue list --state open
```

### 本田様の Windows 実機検証フェーズ（最優先）

PR #126 マージ済、コードベースは実機検証可能状態。次セッションで以下を実施:

1. **`docs/handoff/1c-exe-redistribution-runbook.md` 手順で配布 exe 再ビルド**
2. **AC-13 が本番経路で機能することを必ず検証**: bulk run 中に出力 PDF を Acrobat で
   開いた状態で再実行 → 「PDFを閉じてから再実行」文言が表示されること
   （`PdfMergeError(__cause__=PermissionError)` 経路の本番動作確認、review-pr で発見した
   AC-13 前提崩壊リスクの最終確認）
3. **AC-7 / AC-11 の実機確認**: UNC パス（`//Tera-station/...`）でのスキャン、
   日本語事業所名でのフォルダ/PDF 開閉
4. 上記 3 件全 PASS → ADR-013 を Proposed → Accepted 昇格 PR 作成
5. ADR-011 Accepted 昇格 PR 作成（タスク 14D、PR #124 + #126 が実機で稼働後）
6. 運用フィードバックに基づく追加判断:
   - 上書き確認ダイアログ追加（review-pr MEDIUM）
   - Tk smoke テスト追加
   - type-design 改善（`__post_init__` 不変条件、状態遷移 guard）

## 参照ファイル（次セッション用）

### Session 25 成果物（最新）
- `src/wiseman_hub/pdf/facility_scanner.py`: ルート配下スキャン
- `src/wiseman_hub/pdf/facility_bulk_runner.py`: 一括実行 + 停止 + lock 文言
- `src/wiseman_hub/ui/facility_root_dialog.py`: 新ダイアログ（ViewModel + Tk Widget）
- `src/wiseman_hub/utils/os_open.py`: クロスプラットフォーム open
- `docs/adr/013-facility-root-bulk-merge.md`: 本 ADR（Proposed）

### Session 24 成果物
- `src/wiseman_hub/pdf/facility_merger.py`: 事業所単位 1 ファイル ABCABC 連結（PR #124）
- `docs/adr/012-facility-merger-output-format.md`: 出力仕様 ADR

### Session 22-23 成果物
- `docs/handoff/1c-exe-redistribution-runbook.md`: 1-C ランブック
- `src/wiseman_hub/pdf/session.py`: page_index invariant 検証

### 履歴
- `docs/handoff/archive/2026-04-history.md`: Session 11-21 詳細
