# Handoff: ex_extractor 5 PR シリーズ PR3+PR4 完走（Session 28 終了時点）

**更新日**: 2026-04-27（Session 28 / PR #133 + #135 マージ後）
**ブランチ**: main
**main HEAD**: `6aa79c2` feat(ui): ex_extractor デスクトップ UI 統合（PR4/5）(#135)

## セッション 28 の成果（ex_extractor PR3 + PR4 完走）

### マージ済 ✅

#### PR #133 (PR3: ex_extractor core + SFX adapter)
- squash merge `e0c5207`、+2,545 / -371 LOC、テスト 66 件追加
- `scripts/process_ex_files.py`（旧 262 行）→ `src/wiseman_hub/pdf/ex_extractor.py` に移植 + 拡張
- SFX 実行を `SfxAdapter` Protocol で抽象化（Windows 実装 + macOS fake adapter）
- 結果型: `ExtractionStatus` (6 状態) / `ExtractionErrorCode` (9 種) / `ExtractionItem` / `ExtractionResult`
- 旧 CLI を薄ラッパー化、CLI インターフェース互換維持 + exit code 拡張 (0/2/1)
- **多重 Quality Gate**: 計画 Codex HIGH 4 + MEDIUM 3、実装後 6 並列レビュー HIGH 6 + MEDIUM 多数、review-pr 6 並列再レビュー HIGH 6 + MEDIUM 2、全件反映

#### PR #135 (PR4: デスクトップ UI 統合)
- squash merge `6aa79c2`、+2,275 / -44 LOC、テスト 90+ 件追加
- ランチャーに「ex_ ファイル変換 + 振り分け」**5 ボタン目** 追加
- `ExExtractorDialog` 新規（UiState 4 状態 / ViewModel / Tk widget）
- `ManualDistributionDialog` 新規（AMBIGUOUS/UNMATCHED の 1 件ずつ手動確定 + 確定前確認ステップ + 既定選択空）
- PR3 API 後方互換拡張: `extract_one(force_facility: str | None = None)` + `ResolveReason.MANUAL_OVERRIDE`
- **多重 Quality Gate**: 計画 Codex HIGH 4 + MEDIUM 3、実装後 review-pr 6 並列 HIGH 7 + MEDIUM 3 + 簡素化 1、全件反映

### Issue Net 変化（Session 28）

- **Close**: 0 件
- **起票**: 1 件（**#134** Gemini 2.5 Flash retire 2026-10-16 monitor）
- **Net: +1 件**

「進捗ゼロ」評価ではない理由（CLAUDE.md triage 基準 #5、ユーザー明示指示）:
- ユーザー指示「日本リージョンで使えるなら 3 Flash 移行 OK」に対する monitor 設計
- 再開条件機械化済（asia-northeast1 GA 記載 OR 2026-09-16 retire 30 日前）
- 能動的作業不要・open 維持で運用（postpone パターン、`feedback_issue_postpone_pattern.md` 準拠）

### Gemini 2.5 Flash retire 対応の判断（GCP PM/PL 視点）

**現状（2026-04-27）**:
- Gemini 2.5 Flash retire: 2026-10-16（公式リリースノート）
- 後継 Gemini 3 Flash: **Preview**（GA ではない）、`asia-northeast1` 提供は **公式未確認**、google.genai SDK で multimodal 劣化バグ報告あり

**判断**: 本日時点では移行見送り、Issue で monitor 継続。介護現場の本番投入で Preview モデル + 品質劣化バグ報告 + 日本リージョン未確認は推奨不可。retire まで 5.5 ヶ月の余裕あり。

**移行作業の概算**: `backend/ocr_proxy/app/config.py:37` の `GEMINI_MODEL` デフォルト + Cloud Run 環境変数のみで完結、ロールバック容易。Breaking changes（`total_reasoning_tokens` rename / PDF token 増 / image segmentation 非対応）は本リポジトリの利用範囲では影響なし（文字認識のみ）。

---

## 5 PR シリーズ進捗（ex_extractor 統合）

| # | スコープ | 状態 |
|---|---------|------|
| PR1 | 設定スキーマ拡張（`ex_source_dir` + `facility_aliases`） | ✅ Merged (#130) |
| PR2 | `pdf/facility_resolver` 純粋ロジック（alias 優先 + 安全マッチング） | ✅ Merged (#131) |
| PR3 | `pdf/ex_extractor` core 移植 + SFX adapter 化 + macOS fake runner + scripts ラッパー | ✅ Merged (#133) |
| **PR4** | **デスクトップ UI 統合（dialog + launcher 5 ボタン化 + 手動振り分け UI）** | ✅ **Merged (#135)** |
| PR5 | Windows 実機検証 + settings.py タブ化（独立評価） | ⬜ 次セッション |

---

## 次セッションへの送り（PR5 のスコープ判断保留）

ユーザー初期指示「Windows 実機テストを早くしたい」を踏まえ、次セッション開始時に A/B/C 選択肢から決定:

| 選択肢 | スコープ | 利点 | 欠点 |
|--------|---------|------|------|
| **A (推奨)** | PR5 を runbook 主体に絞る → settings タブ化は PR6 へ | **最速で実機テスト**へ。aliases 編集は TOML 直接編集（本田様は PR1 で経験済） | aliases 設定変更時の TOML 編集負担 |
| B | PR5 を本来計画通り（runbook + settings タブ化を 1 PR） | 本田様が GUI で完結 | 実機検証開始まで時間かかる |
| C | runbook を先に最小 PR → 実機検証 → 課題ベースで PR5 | 課題ベース設計で無駄なし | 並行 PR 管理コスト |

**GCP PM/PL 視点で A 推奨**: TTM 最短、実機検証で要件確定後の settings UI 設計の方が ROI 高、PR4 までで core 機能は完成済。

---

## 重要な設計判断（次セッション以降に影響）

### 誤配布回避が最重要 KPI
- false positive > false negative（介護現場で誤配布は業務事故）
- AMBIGUOUS / UNMATCHED は **抽出も skip** し手動確定経路へ（PR3）
- UNMATCHED の手動確定は確定前確認ステップ + 既定選択空で誤選択防御（PR4）

### PII 防御方針（ADR-014 §PII 保護方針 規定）
- `ex_extractor` モジュールの logger は filename + enum 値のみ
- フルパス / 事業所名 / matched_facility / candidates / 抽出 PDF 名 / OSError 生メッセージ → 禁止
- 事業所名・候補は `ManualDistributionDialog` 内のみ表示（運用者識別用）
- `orphan_alias_canonicals` は alias 設定不整合通知用に専用 banner 表示（外部送信なし、運用ドキュメントでログ取り扱い注意明記）
- caplog で直接検査（テスト 4+ 件）

### Windows 専用機能の隔離
- `pywinauto` import は `WindowsSfxAdapter._click_sfx_dialog` 内で **遅延 import**
- `WindowsSfxAdapter()` constructor で `sys.platform != "win32"` なら `UnsupportedSfxPlatformError`（独自例外）
- macOS の dry-run / `--help` 動作保証

### 手動 override の監査性
- `ResolveReason.MANUAL_OVERRIDE` で自動と手動を結果上区別
- UI サマリで「自動振り分け成功 N / 手動確定成功 M」を分離表示
- `extract_one(force_facility=...)` は後方互換（既存呼び出し元無変更）
- `force_facility not in facility_names` は ValueError で fail-fast（PII-safe メッセージ、`chars=/size=` で単位明示）

### 状態遷移の構造化
- `UiState` (IDLE / BUSY / SHOWING_RESULT / MANUAL_DISTRIBUTING) — `transition_to_*` で遷移元チェック
- `ManualUiState` (SELECTING / CONFIRMING / EXTRACTING / DONE) — `abort_remaining()` で中断時の穴埋め
- `ExtractionStatus` (SUCCESS / SKIPPED_AMBIGUOUS / SKIPPED_UNMATCHED / EXTRACT_FAILED / PARTIAL_OUTPUT / MOVE_FAILED) — `__post_init__` で不変条件強制
- close 後の after callback は `_top.winfo_exists()` ガードで TclError 抑止 + 運用情報消失防止

### 事故シナリオへの構造的防御
- adapter 例外時の部分生成 PDF → `SfxExtractionFailed.partial_outputs` で伝搬、自動移動禁止（`PARTIAL_OUTPUT` ステータス）
- 移動途中で衝突/IO エラー → `partially_moved` で運用者へ可視化（`MOVE_FAILED` ステータス）
- バッチ中の想定外例外 → ループ最外殻で `MemoryError`/`RecursionError` は再 raise、それ以外は `UNEXPECTED` で続行
- mtime フィルタ（`_MTIME_GRACE_SEC = 5.0`）で Desktop/Downloads の無関係 PDF 誤配布防止 + NTP 後方ステップ吸収

---

## ADR-014 状態
- **Proposed のまま**（PR5 完了 + 本田様実機検証完走後に Accepted 昇格予定）
- 変更履歴に PR1-4 の HIGH/MEDIUM 反映根拠を全て記録済（Codex セカンドオピニオン + Evaluator + 6 並列レビュー + review-pr 6 並列再レビュー）
- 公開 API 仕様（`extract_one` / `extract_directory` / 結果型 / CLI 終了コード 0/2/1）明記
- PII 保護方針セクションに `ex_extractor` モジュール + CLI レイヤ規定追加

---

## 積み残し Issue / 技術負債

### Session 28 で起票
- **#134**: OCR Gemini 2.5 Flash retire 対応（monitor、再開条件機械化済）

### Session 28 で CLOSED
- なし（PR #133 + #135 は新機能、既存 Issue と無関係）

### P1（open、継続）
- **#6**: PoC E2E テスト

### P2（open、優先順、本機能と無関係）
- **#117**: Session.candidates / UserCandidate.similar_candidates を tuple 化
- **#80**: Windows 実機 smoke build で Phase B / OCR import 検証
- **#63**: Linux CI Tk wiring skip
- **#45**: SourceKind StrEnum 統一
- **#27**: config dataclass 型設計強化
- **#40**, **#39**, **#29**, **#17**, **#16**, **#14**, **#11**, **#134**

---

## impl-plan 進捗（Session 28 終了時点）

| タスク | 状態 | PR |
|--------|------|-----|
| 12C 初回起動ウィザード | ⏳ 優先度低 | - |
| 13D ランチャー「事業所フォルダ結合」統合 | ✅ Session 19 / 25 / 26 | #108, #126 |
| 14A-D PyInstaller / アイコン / 配布 / ADR-011 | ✅ Session 26 | #79/#60/#82, #128 |
| 事業所単位 1 ファイル仕様 | ✅ Session 24 | #124 |
| 事業所ルートフォルダ管理 + 一括/選択結合 | ✅ Session 25 / 26 | #126, #128 |
| ex_extractor PR1 設定スキーマ | ✅ Session 27 | #130 |
| ex_extractor PR2 facility_resolver | ✅ Session 27 | #131 |
| **ex_extractor PR3 core 移植 + SFX adapter** | ✅ **Session 28** | **#133** |
| **ex_extractor PR4 UI 統合** | ✅ **Session 28** | **#135** |
| **ex_extractor PR5 Windows 実機 + settings タブ化** | ⏳ **次セッション (A/B/C 選択待ち)** | - |
| Gemini 2.5 Flash retire 対応 (monitor) | ⏳ 2026-09-01 再評価 | #134 |
| 15 GitHub Actions + WIF | ⏳ GUI 安定後 | - |

---

## セッション再開手順（コピペ可）

### 次セッション開始時（Session 29）

```bash
cd /Users/yyyhhh/Projects/wiseman_auto_sys
git checkout main
git pull --ff-only
# main HEAD が 6aa79c2（PR #135）であることを確認
gh issue list --state open
```

### 次のアクション（PR5 着手前のスコープ判断）

ユーザーに A/B/C を確認:

```
PR5 のスコープを A / B / C のどれにしますか？
- A (推奨): runbook 主体 (本田様向け実機検証手順) + ADR-014 Accepted 昇格条件のみ
- B: 本来計画通り (runbook + settings タブ化 1 PR)
- C: runbook 先に最小 PR → 実機検証 → 課題あれば PR5 で settings + 修正
```

### A 選択時の作業内容

1. `docs/handoff/pr5-ex-extractor-runbook.md` 作成
   - 本田様の Windows 11 環境で 30-45 分で完走できる検証フロー
   - AC-1〜AC-14 の実機検証チェックリスト
   - PII 防御の運用注意（ログ取り扱い）
   - 失敗時のロールバック手順
2. ADR-014 §未決事項 を更新（PR5 完了後の Accepted 昇格条件明記）
3. handoff コミット + PR
4. 本田様の実機検証完走を待つ → 結果を Session 29+ で反映

### B / C 選択時

`/impl-plan` で settings タブ化の計画を立てる（既存 settings.py 構造の確認 + ex_source_dir 入力 + facility_aliases CRUD UI + TOML 永続化）。

---

## 参照ファイル

### Session 28 成果物（最新）
- `src/wiseman_hub/pdf/ex_extractor.py`: PR3 core (~700 行)
- `src/wiseman_hub/ui/ex_extractor_dialog.py`: PR4 主ダイアログ (~590 行)
- `src/wiseman_hub/ui/manual_distribution_dialog.py`: PR4 手動振り分け (~580 行)
- `tests/unit/pdf/test_ex_extractor.py`: 70+ テスト
- `tests/unit/ui/test_ex_extractor_dialog.py`: 18 テスト
- `tests/unit/ui/test_manual_distribution_dialog.py`: 17 テスト
- `docs/adr/014-ex-extractor-integration.md`: 設計 ADR (Proposed)、PR1-4 変更履歴

### Session 27 成果物
- `src/wiseman_hub/config.py`: `PdfMergeConfig.ex_source_dir` + `facility_aliases` + `_validate_facility_aliases`
- `src/wiseman_hub/pdf/facility_resolver.py`: 純粋ロジック (`resolve_facility` + `ResolveResult` + `find_orphan_alias_canonicals` + `MANUAL_OVERRIDE` reason)
- `tests/unit/pdf/test_facility_resolver.py`: 65+ テスト

### Session 26 成果物
- `docs/handoff/session26-pr126-windows-runbook.md`: 30-45 分検証フロー
- ADR-011 / ADR-013 Accepted

### 履歴
- `docs/handoff/archive/2026-04-history.md`: Session 11-21 詳細
- Session 22-26 は git log + ADR-011/012/013 + 上記 runbook 参照

---

## 多重 Quality Gate の累積効果（5 PR シリーズ全体）

| PR | Codex 計画 | Evaluator | 6 並列実装後 | review-pr 6 並列再 | 簡素化 |
|----|----------|-----------|-------------|---------------------|--------|
| PR1 (#130) | - | ✅ | 4 並列 (HIGH 3) | - | - |
| PR2 (#131) | ✅ | ✅ | 5 並列 (HIGH 8) | - | - |
| PR3 (#133) | HIGH 4 + MED 3 | ✅ | 6 並列 (HIGH 6) | HIGH 6 + MED 2 | - |
| PR4 (#135) | HIGH 4 + MED 3 | ✅ | - | HIGH 7 + MED 3 | 1 件採用 |

合計: HIGH 38 件 + MEDIUM 多数を発見・反映、production の誤配布リスクを構造的に低減。
