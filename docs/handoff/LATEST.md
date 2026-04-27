# Handoff: Issue #80 Windows smoke build CI 完了（Session 30 終了時点）

**更新日**: 2026-04-27（Session 30 / PR #139 マージ後）
**ブランチ**: main
**main HEAD**: `c63b65e` feat(ci): Windows smoke build for wiseman_hub.exe (Closes #80) (#139)

## セッション 30 の成果（Issue #80 Windows smoke build CI 化）

### マージ済 ✅

#### PR #139 (Issue #80 - Windows runner で wiseman_hub.exe smoke build)

- squash merge `c63b65e`、+338 LOC、3 ファイル（src/wiseman_hub/__main__.py / tests/unit/test_smoke_mode.py / .github/workflows/build-windows-smoke.yml）
- スコープ: PR #79 Codex MEDIUM 指摘「Windows smoke は GUI 起動だけでなく PDF split/merge と OCR client import まで実行すべき」への対応。macOS smoke + 実機 E2E では未検証だった Windows 固有の DLL 解決（runw bootloader、python311.dll、fitz/httpx）を CI 自動検証
- 成果物:
  - `_run_smoke_test()` 新設（fitz / splitter / ocr_client / fitz.open round-trip の最小経路）
    - GUI 副作用ゼロ: tkinter / UI モジュールは関数内 import を回避（AC-2 検証済）
    - PII 防御: 例外時 `type(e).__name__` のみ stderr 出力（本番経路と統一）
    - smoke 用 dummy credential は RFC 6761 .invalid TLD で外部到達ガード（二重防御）
    - OcrClient は `with` 構文で `_make_phase_a_callback` ExitStack パターンと整合
  - `tests/unit/test_smoke_mode.py` 新設（5 テスト、AC-1〜AC-6 機械的検証）
  - `.github/workflows/build-windows-smoke.yml` 新設
    - windows-latest で PyInstaller `--onefile` ビルド → exe 起動 → smoke
    - uv cache 有効化（CI 時間 30-90 秒短縮）
    - 成功時のみ exe artifact upload (retention 7 日)
    - exe 起動失敗時は dist/ listing + PyInstaller warn-files を必ず surface（CI デバッグ可能性）
- **多重 Quality Gate**: /impl-plan AC-1〜10 + /simplify 3 並列（4 件修正） + /safe-refactor（未使用引数 2 件） + /review-pr 6 並列（Critical 3 + Important 4 を反映）

### Issue Net 変化（Session 30）

- **Close**: 1 件（**#80**）
- **起票**: 0 件
- **Net: -1 件** ✅（KPI 進捗）

### CI 全ジョブ結果（PR #139、4 jobs / 3 workflows）

| ジョブ | 結果 |
|--------|------|
| build-smoke (新設、windows-latest) | ✅ pass |
| test-unit (3.11) | ✅ pass |
| test-unit (3.12) | ✅ pass |
| test-integration (既存、WinForms mock) | ✅ pass（挙動不変確認、AC-10 達成） |

### Acceptance Criteria 達成（AC-1〜AC-10）

| # | 基準 | 検証 |
|---|------|------|
| AC-1〜6 | macOS smoke + unit test 5 件 | ✅ pytest 815 passed |
| AC-7 | Windows ワークフロー起動 | ✅ build-smoke pass |
| AC-8 | Windows exe で smoke exit 0 | ✅ |
| AC-9 | exe artifact upload | ✅ `wiseman_hub-exe-{sha}` |
| AC-10 | 既存 workflow 挙動不変 | ✅ test-unit / test-integration pass |

---

## 5 PR シリーズ進捗（ex_extractor 統合）

| # | スコープ | 状態 |
|---|---------|------|
| PR1 | 設定スキーマ拡張（`ex_source_dir` + `facility_aliases`） | ✅ Merged (#130) |
| PR2 | `pdf/facility_resolver` 純粋ロジック | ✅ Merged (#131) |
| PR3 | `pdf/ex_extractor` core + SFX adapter + macOS fake runner | ✅ Merged (#133) |
| PR4 | デスクトップ UI 統合（dialog + launcher 5 ボタン化 + 手動振り分け UI） | ✅ Merged (#135) |
| PR5 (A 選択) | Windows 実機検証 runbook + ADR-014 Accepted 昇格条件 | ✅ Merged (#137) |
| PR6（将来） | settings.py タブ化（実機検証で要件確定後に独立評価） | ⬜ |

---

## 次セッション (Session 31) の作業

### 最優先: 本田様の Windows 11 実機検証（Session 30 から継続）

- runbook: `docs/handoff/pr5-ex-extractor-runbook.md`
- 所要時間: 30-45 分
- TeamViewer 経由で Windows 11 PC に接続
- AC-1〜AC-14 の PASS/FAIL を Phase 5-1 サマリテーブルに記録、PII 墨塗り済スクショ + AC-12 grep 結果取得
- Session 30 で本田様作業の機会がなければ Session 31 以降に持ち越し

### 実機検証完走後（同セッション or 翌セッション）

1. ADR-014 Status `Proposed` → `Accepted` 昇格 PR
2. 「### Session N 実機検証結果」サブセクションを §PR5 Accepted 昇格条件 内に新設（runbook Phase 5-1 サマリ + 観察事項 + PII grep 結果）
3. handoff/LATEST.md を Session N 化

### 一部 AC FAIL 時

- 誤配布リスク AC（AC-6/8/10）の FAIL → PR5.1 として最優先修正、Phase 4 rollback で旧 exe へ即時戻し
- PII 退化（AC-12）の FAIL → PR5.2 として最優先修正、墨塗り済 run.log 添付
- その他 AC FAIL → PR5.X として独立修正、修正後に再度本 runbook で再検証

### 並行可能なタスク（PR5 実機検証と独立）

- **#117**: Session.candidates / UserCandidate.similar_candidates の tuple 化（`/impact-analysis` で影響範囲確認後に着手可能）
- **#63**: Linux CI Tk wiring skip
- **#45**: SourceKind StrEnum 統一
- **#27**: config dataclass 型設計強化

### 能動作業不要（monitor）

- **#134**: Gemini 2.5 Flash retire 2026-10-16 — 再開条件 `asia-northeast1` GA 公式記載 OR 2026-09-16 retire 30 日前

---

## 重要な設計判断（PR3-5 で確立、Session 30 の Issue #80 で追加）

### Issue #80（Session 30）— Windows smoke build の設計原則

- **smoke モードと本番経路の分離**: `_run_smoke_test()` は CLI 引数 `--smoke-test` で分岐、main() 後段の Tk 経路には到達しない
- **GUI 副作用ゼロ要件**: tkinter / UI モジュールは関数内 import を回避（AC-2 で subprocess 検証）
- **PII 防御の規律統一**: smoke モードでも `type(e).__name__` のみ stderr 出力（CI 側で Process state / dist listing / PyInstaller warn-files を出してデバッグ可能性を担保）
- **dummy credential の二重防御**: RFC 6761 .invalid TLD + dummy api_key（万が一 HTTP 発火しても外部到達ガード）
- **OcrClient リソース管理の規律統一**: `with OcrClient(...) as client:` で `_make_phase_a_callback` の ExitStack パターンと整合
- **責務分離**: 既存 `test-windows-integration.yml`（WinForms mock + pytest）と新設 `build-windows-smoke.yml`（PyInstaller + smoke）を別ワークフロー化

### 誤配布回避が最重要 KPI（PR3-4、runbook 直撃 AC）
- false positive > false negative（介護現場で誤配布は業務事故）
- AMBIGUOUS / UNMATCHED は **抽出も skip** し手動確定経路へ（PR3）
- UNMATCHED の手動確定は確定前確認ステップ + 既定選択空（`(未選択)`）で誤選択防御（PR4 / AC-6）
- mtime フィルタ（`_MTIME_GRACE_SEC = 5.0`）で SFX 起動前の無関係 PDF 誤配布防止（PR3-HIGH-D / AC-8）
- MOVE_FAILED の `partially_moved` 件数は UI/CLI で可視化（運用情報消失防止、PR3-HIGH-A / AC-10）

### PII 防御方針（ADR-014 §PII 保護方針）
- `ex_extractor` モジュール logger は **filename + enum 値 + 例外型名のみ**
- フルパス / 事業所名 / matched_facility / candidates / 抽出 PDF 名 / OSError 生メッセージ → 禁止
- CLI レイヤの `orphan_alias_canonicals` 通知のみ canonical 名が例外的に出る（運用ローカル端末限定、SaaS log aggregator 送信禁止）
- AC-12 grep 検証で実機 run.log の漏洩有無を確認

### Windows 専用機能の隔離
- `pywinauto` import は `WindowsSfxAdapter._click_sfx_dialog` 内で **遅延 import**
- `WindowsSfxAdapter()` constructor で `sys.platform != "win32"` なら `UnsupportedSfxPlatformError`
- macOS の dry-run / `--help` 動作保証

### 手動 override の監査性
- `ResolveReason.MANUAL_OVERRIDE` で自動と手動を結果上区別、UI サマリで「自動振り分け成功 N / 手動確定成功 M」を分離表示
- `extract_one(force_facility=...)` は後方互換、`force_facility not in facility_names` は ValueError fail-fast

### 状態遷移の構造化
- `UiState` (IDLE / BUSY / SHOWING_RESULT / MANUAL_DISTRIBUTING) — `transition_to_*` で遷移元チェック
- `ManualUiState` (SELECTING / CONFIRMING / EXTRACTING / DONE) — `abort_remaining()` で中断時の穴埋め
- `ExtractionStatus` (SUCCESS / SKIPPED_AMBIGUOUS / SKIPPED_UNMATCHED / EXTRACT_FAILED / PARTIAL_OUTPUT / MOVE_FAILED) — `__post_init__` で不変条件強制

---

## ADR-014 状態
- **Proposed のまま**（実機検証完走後に Accepted 昇格予定）
- §PR5 Accepted 昇格条件 で機械的判定可能な昇格条件を明記（PR1-5 すべての変更履歴記録済）
- 公開 API 仕様（`extract_one` / `extract_directory` / 結果型 / CLI 終了コード 0/2/1）明記
- PII 保護方針セクションに `ex_extractor` モジュール + CLI レイヤ規定を含む

---

## 積み残し Issue

### Session 30 で起票
- なし

### Session 30 で CLOSED
- **#80**: Windows 実機 smoke build for Phase B / OCR import 検証 ✅（PR #139）

### P1（open、継続）
- **#6**: PoC E2E テスト

### P2（open、優先順）
- **#117**: Session.candidates / UserCandidate.similar_candidates を tuple 化（PR5 と独立、並行可）
- **#63**: Linux CI Tk wiring skip
- **#45**: SourceKind StrEnum 統一
- **#27**: config dataclass 型設計強化
- **#40**, **#39**, **#29**, **#17**, **#16**, **#14**, **#11**, **#134**

---

## impl-plan 進捗（Session 30 終了時点）

| タスク | 状態 | PR |
|--------|------|-----|
| 13D ランチャー「事業所フォルダ結合」統合 | ✅ Session 19 / 25 / 26 | #108, #126 |
| 14A-D PyInstaller / アイコン / 配布 / ADR-011 | ✅ Session 26 | #79/#60/#82, #128 |
| 事業所単位 1 ファイル仕様 | ✅ Session 24 | #124 |
| 事業所ルートフォルダ管理 + 一括/選択結合 | ✅ Session 25 / 26 | #126, #128 |
| ex_extractor PR1 設定スキーマ | ✅ Session 27 | #130 |
| ex_extractor PR2 facility_resolver | ✅ Session 27 | #131 |
| ex_extractor PR3 core 移植 + SFX adapter | ✅ Session 28 | #133 |
| ex_extractor PR4 UI 統合 | ✅ Session 28 | #135 |
| ex_extractor PR5 Windows 実機検証準備（A 選択） | ✅ Session 29 | #137 |
| **Issue #80 Windows smoke build CI** | ✅ **Session 30** | **#139** |
| ex_extractor PR5 実機検証実行 | ⏳ Session 31+（本田様作業） | - |
| ADR-014 Accepted 昇格 | ⏳ 実機検証後 | - |
| ex_extractor PR6 settings.py タブ化 | ⏳ 実機検証で要件確定後 | - |
| Gemini 2.5 Flash retire 対応 (monitor) | ⏳ 2026-09-16 retire 30 日前 / `asia-northeast1` GA 確認 | #134 |
| 15 GitHub Actions + WIF | ⏳ GUI 安定後 | - |

---

## セッション再開手順（コピペ可）

### Session 31 開始時

```bash
cd /Users/yyyhhh/Projects/wiseman_auto_sys
git checkout main
git pull --ff-only
# main HEAD が c63b65e（PR #139）であることを確認
gh issue list --state open
```

### 本田様の Windows 11 実機検証（TeamViewer 経由）

```powershell
cd $HOME\Projects\wiseman-auto-sys
git pull --ff-only
# docs/handoff/pr5-ex-extractor-runbook.md を notepad で開いて Phase 0 から実施
```

### 実機検証完走後の作業

1. ADR-014 Status `Proposed` → `Accepted` 昇格 PR（feature ブランチ + main 直 push 禁止 hook 経由）
2. 「### Session N 実機検証結果」サブセクションを §PR5 Accepted 昇格条件 内に新設
3. handoff/LATEST.md を Session N として更新

---

## 参照ファイル

### Session 30 成果物（最新）
- `src/wiseman_hub/__main__.py`: `_run_smoke_test()` 新設 + `--smoke-test` argparse
- `tests/unit/test_smoke_mode.py`: AC-1〜AC-6 検証 5 テスト
- `.github/workflows/build-windows-smoke.yml`: Windows runner で PyInstaller + smoke

### Session 29 成果物
- `docs/handoff/pr5-ex-extractor-runbook.md`: Windows 実機検証 runbook (615 行、Phase 0-5 + AC-1〜AC-14)
- `docs/adr/014-ex-extractor-integration.md`: §PR5 Accepted 昇格条件 セクション追加 + 変更履歴

### Session 27-28 成果物
- `src/wiseman_hub/pdf/ex_extractor.py`: PR3 core (804 行)
- `src/wiseman_hub/ui/ex_extractor_dialog.py`: PR4 主ダイアログ (660 行)
- `src/wiseman_hub/ui/manual_distribution_dialog.py`: PR4 手動振り分け (615 行)
- `src/wiseman_hub/pdf/facility_resolver.py`: PR2 純粋ロジック (418 行)
- `src/wiseman_hub/config.py`: PR1 設定スキーマ拡張 (430 行)
- `tests/unit/pdf/`, `tests/unit/ui/`: 200+ テスト

### Session 26 成果物（runbook 構造の参考元）
- `docs/handoff/session26-pr126-windows-runbook.md`: 30-45 分検証フロー（Phase 0-5 構造）
- ADR-011 / ADR-013 Accepted

### 履歴
- `docs/handoff/archive/2026-04-history.md`: Session 11-21 詳細
- Session 22-26 は git log + ADR-011/012/013 + session26-pr126 runbook 参照
- Session 27-29 は git log + PR #130/#131/#133/#135/#136/#137/#138 参照（前バージョンの LATEST.md）

---

## 多重 Quality Gate の累積効果（5 PR シリーズ + Issue #80）

| PR | Codex 計画 | Evaluator | 6 並列実装後 | review-pr 再 | 簡素化 |
|----|----------|-----------|-------------|--------------|--------|
| PR1 (#130) | - | ✅ | 4 並列 (HIGH 3) | - | - |
| PR2 (#131) | ✅ | ✅ | 5 並列 (HIGH 8) | - | - |
| PR3 (#133) | HIGH 4 + MED 3 | ✅ | 6 並列 (HIGH 6) | 6 並列 (HIGH 6 + MED 2) | - |
| PR4 (#135) | HIGH 4 + MED 3 | ✅ | - | 6 並列 (HIGH 7 + MED 3) | 1 件 |
| PR5 (#137) | impl-plan AC-PR5-1〜8 | - | - | 2 並列 (Crit 2 + Imp 5 + Sug 5) | 5 件 |
| **#80 (#139)** | **impl-plan AC-1〜10** | - | - | **6 並列 (Crit 3 + Imp 4)** | **/simplify 4 件 + /safe-refactor 2 件** |

合計: HIGH 38+ / Critical 5 / 多数の Suggestions を発見・反映、production の誤配布リスクを構造的に低減。
