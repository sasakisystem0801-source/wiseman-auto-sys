# Handoff: ex_extractor 5 PR シリーズ完走（Session 29 終了時点）

**更新日**: 2026-04-27（Session 29 / PR #137 マージ後）
**ブランチ**: main
**main HEAD**: `17da370` docs(handoff,adr): PR5 ex_extractor Windows 実機検証 runbook + ADR-014 Accepted 昇格条件 (#137)

## セッション 29 の成果（PR5 runbook 主体に絞り、本田様の実機検証準備を完成）

### マージ済 ✅

#### PR #137 (PR5: A 選択 — Windows 実機検証 runbook + ADR-014 Accepted 昇格条件)

- squash merge `17da370`、+660/-2 LOC、ドキュメント 2 ファイル
- スコープ判断: **A 選択（runbook 主体に絞り、settings タブ化は PR6 へ後回し）**。GCP PM/PL 視点で TTM 最短、要件確定後に settings UI を設計するほうが ROI 高
- 成果物:
  - `docs/handoff/pr5-ex-extractor-runbook.md`（615 行、所要時間 30-45 分）
    - Phase 0-5 構造（session26-pr126 踏襲）
    - **AC-1〜AC-14** の実機検証チェックリスト（誤配布防止 KPI 直撃 AC を独立明記）
    - PII 取り扱い注意（運用ルール、検証開始前に必読）独立セクション
    - rollback 手順 + トラブル早見表 + 連絡ルール
  - ADR-014 §PR5 Accepted 昇格条件 セクション追加
    - AC-1〜AC-14 すべて PASS が必須、誤配布防止 KPI 直撃 AC（AC-6/8/10）は特に厳格
    - AC-12 PII 防御 grep 結果が必須エビデンス
    - 一部 AC FAIL 時の取り扱い（PR5.1 / PR5.2 として独立修正 PR、ADR-013/011 昇格慣習踏襲）
- **多重 Quality Gate**: /impl-plan AC-PR5-1〜8 + /review-pr 2 並列（comment-analyzer + code-reviewer）→ Critical 2 + Important 5 + Suggestions 5 をすべて反映

### Issue Net 変化（Session 29）

- **Close**: 0 件
- **起票**: 0 件
- **Net: 0 件**（ドキュメント整備セッション）

「進捗ゼロ」評価ではない理由（CLAUDE.md triage 基準準拠）:
- 本田様の Windows 11 実機検証（30-45 分完走可能）の準備を完成
- ADR-014 §PR5 Accepted 昇格条件 で機械的判定可能な昇格条件を明記
- review 指摘の I4-ca（launcher の `_btn_ex_extractor` disabled 漏れ）は rating 5-6 + 業務影響軽微で Issue 起票せず runbook 既知制限 note で対応（feedback_issue_triage.md 準拠）

---

## 5 PR シリーズ進捗（ex_extractor 統合）

| # | スコープ | 状態 |
|---|---------|------|
| PR1 | 設定スキーマ拡張（`ex_source_dir` + `facility_aliases`） | ✅ Merged (#130) |
| PR2 | `pdf/facility_resolver` 純粋ロジック | ✅ Merged (#131) |
| PR3 | `pdf/ex_extractor` core + SFX adapter + macOS fake runner | ✅ Merged (#133) |
| PR4 | デスクトップ UI 統合（dialog + launcher 5 ボタン化 + 手動振り分け UI） | ✅ Merged (#135) |
| **PR5 (A 選択)** | **Windows 実機検証 runbook + ADR-014 Accepted 昇格条件** | ✅ **Merged (#137)** |
| PR6（将来） | settings.py タブ化（実機検証で要件確定後に独立評価） | ⬜ |

---

## 次セッション (Session 30) の作業

### 最優先: 本田様の Windows 11 実機検証

- runbook: `docs/handoff/pr5-ex-extractor-runbook.md`
- 所要時間: 30-45 分
- TeamViewer 経由で Windows 11 PC に接続
- AC-1〜AC-14 の PASS/FAIL を Phase 5-1 サマリテーブルに記録、PII 墨塗り済スクショ + AC-12 grep 結果取得

### 実機検証完走後（同セッション or Session 31）

1. ADR-014 Status `Proposed` → `Accepted` 昇格 PR
2. 「### Session N 実機検証結果」サブセクションを §PR5 Accepted 昇格条件 内に新設（runbook Phase 5-1 サマリ + 観察事項 + PII grep 結果）
3. handoff/LATEST.md を Session N 化

### 一部 AC FAIL 時

- 誤配布リスク AC（AC-6/8/10）の FAIL → PR5.1 として最優先修正、Phase 4 rollback で旧 exe へ即時戻し
- PII 退化（AC-12）の FAIL → PR5.2 として最優先修正、墨塗り済 run.log 添付
- その他 AC FAIL → PR5.X として独立修正、修正後に再度本 runbook で再検証

### 並行可能なタスク（PR5 実機検証と独立）

- **#117**: Session.candidates / UserCandidate.similar_candidates の tuple 化（`/impact-analysis` で影響範囲確認後に着手可能）

### PR5 実機検証完走後の候補

- **#80**: Windows 実機 smoke build で Phase B / OCR import 検証（ex_extractor 安定動作確認後）
- **CLAUDE.md (project) ADR 数ドリフト**: 「001-006」記述を最新数に更新（本 handoff PR で同梱対応）

### 能動作業不要（monitor）

- **#134**: Gemini 2.5 Flash retire 2026-10-16 — 再開条件 `asia-northeast1` GA 公式記載 OR 2026-09-16 retire 30 日前

---

## 重要な設計判断（次セッション以降に影響、PR3-4 で確立）

### 誤配布回避が最重要 KPI（runbook 直撃 AC）
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

### Session 29 で起票 / CLOSED
- なし（ドキュメント整備セッション）

### P1（open、継続）
- **#6**: PoC E2E テスト

### P2（open、優先順）
- **#117**: Session.candidates / UserCandidate.similar_candidates を tuple 化（PR5 と独立、並行可）
- **#80**: Windows 実機 smoke build で Phase B / OCR import 検証（PR5 完走後）
- **#63**: Linux CI Tk wiring skip
- **#45**: SourceKind StrEnum 統一
- **#27**: config dataclass 型設計強化
- **#40**, **#39**, **#29**, **#17**, **#16**, **#14**, **#11**, **#134**

---

## impl-plan 進捗（Session 29 終了時点）

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
| **ex_extractor PR5 Windows 実機検証準備（A 選択）** | ✅ **Session 29** | **#137** |
| **ex_extractor PR5 実機検証実行** | ⏳ **Session 30**（本田様作業） | - |
| ADR-014 Accepted 昇格 | ⏳ Session 30+ | - |
| ex_extractor PR6 settings.py タブ化 | ⏳ 実機検証で要件確定後 | - |
| Gemini 2.5 Flash retire 対応 (monitor) | ⏳ 2026-09-01 再評価 | #134 |
| 15 GitHub Actions + WIF | ⏳ GUI 安定後 | - |

---

## セッション再開手順（コピペ可）

### Session 30 開始時

```bash
cd /Users/yyyhhh/Projects/wiseman_auto_sys
git checkout main
git pull --ff-only
# main HEAD が 17da370（PR #137）であることを確認
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
2. 「### Session 30 実機検証結果」サブセクションを §PR5 Accepted 昇格条件 内に新設
3. handoff/LATEST.md を Session 30 として更新

---

## 参照ファイル

### Session 29 成果物（最新）
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
- Session 27-28 は git log + PR #130/#131/#133/#135/#136 参照（前バージョンの LATEST.md）

---

## 多重 Quality Gate の累積効果（5 PR シリーズ全体）

| PR | Codex 計画 | Evaluator | 6 並列実装後 | review-pr 再 | 簡素化 |
|----|----------|-----------|-------------|--------------|--------|
| PR1 (#130) | - | ✅ | 4 並列 (HIGH 3) | - | - |
| PR2 (#131) | ✅ | ✅ | 5 並列 (HIGH 8) | - | - |
| PR3 (#133) | HIGH 4 + MED 3 | ✅ | 6 並列 (HIGH 6) | 6 並列 (HIGH 6 + MED 2) | - |
| PR4 (#135) | HIGH 4 + MED 3 | ✅ | - | 6 並列 (HIGH 7 + MED 3) | 1 件 |
| PR5 (#137) | impl-plan AC-PR5-1〜8 | - | - | 2 並列 (Crit 2 + Imp 5 + Sug 5) | 5 件 |

合計: HIGH 38+ / Critical 2 / 多数の Suggestions を発見・反映、production の誤配布リスクを構造的に低減。
