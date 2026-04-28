# Handoff: Session 36 完了 - ユーザー要望 4 PR 完走 (#150/#151/#154/#155)

**更新日**: 2026-04-29（Session 36 / Mac 側で完結、Windows 検証は次セッション）
**ブランチ**: docs/handoff-session-36 (PR 予定)
**main HEAD**: `da6490f` docs(handoff): Session 35 完了 (#156) → 4 PR マージ後 main 同期済

## 次セッション主軸

**ユーザー要望（ex_ パス指定 + 不要ボタン除去）達成済**。次セッションは以下のいずれか：

### 次セッションの優先候補

1. **Windows 実機検証** — PR #160 (#154) / PR #163 (#155) で削除/追加した UI を **PyInstaller リビルド + 配備** で実機確認（受け入れ基準の最後の項目、各 PR で next session 持ち越し）
2. **業務フロー ② BC PDF 生成の指示受け** — Session 35 から継続。ユーザー明示「次セッションに指示」未消化
3. **#152 着手 (#27 PR-B 系)** — UserNameBBox NaN/inf + OcrBackendConfig 空白 URL 検証。型強化系の継続、Mac で完結可能

### Session 36 で派生した follow-up Issue

| # | 由来 | 概要 | 推奨 timing |
|---|-----|------|-----|
| #158 | codex review (Medium) | 起動後 callback の load_config 失敗 actionable 化 (`__main__.py:81/128/373/405`) | 既存設計修正、影響範囲中 |
| #161 | silent-failure-hunter HIGH | GUI 再統合時の messagebox マッピング再構築要件（将来 GUI 復活時の guard） | 復活前提なら都度実装 |
| #162 | silent-failure-hunter Medium ×2 | 同期 callback 重い処理時 UI フリーズ + `_invoke_or_show` 例外保護 | ADR 追記要件 |
| #164 | silent-failure-hunter HIGH | ExExtractorViewModel.source_dir setter 検証で TOCTOU / 不変条件 | 設計変更で範囲広い |
| #165 | silent-failure-hunter Medium | GUI 選択した取込元の「(セッション限定)」UX hint | UX 改善、軽微 |

## Session 36 の成果

### マージ済 4 PR (Issue 4 件 close)

| PR | Issue | 内容 | 規模 |
|----|-------|------|------|
| #157 | #150 ✅ P1/bug | `WisemanHub.__init__` / `__main__.main()` で `load_config` 例外を捕捉し actionable error + exit code 2 (config error)。**C1 (PII 漏洩)** + **HIGH-1 (OSError 識別)** + **HIGH-2 (RPA 経路 CLI context log)** + codex review HIGH (`reports = "bad"` AttributeError → exit code 1 漏れ) を統合 | 6 ファイル / +445 / -11 |
| #159 | #151 ✅ | `PdfMergeConfig.concat_order` を `tuple[ConcatSourceLetter, ...]` に変更。`__post_init__` で list → tuple 正規化 fail-safe。mutation bypass を型レベル阻止。codex Critical Gap (#1 TOML 経路の isinstance 検証 / #2 merger end-to-end / #3 `+=` contract test) を統合 | 6 ファイル / +105 / -26 |
| #160 | #154 ✅ | Launcher から旧ワークフロー UI 経路 (PDF マージ処理 / 確認待ちセッション) を除去。**`ui/launcher.py` 542 → 200 行**、`__main__.py` から `_make_phase_a/review/phase_b_callback` + `_review_outcome_to_callback_result` 削除、テスト 3 ファイル削除 | 9 ファイル / +111 / -1886 |
| #163 | #155 ✅ | `ExExtractorDialog` に「取込元選択...」ボタン追加（FacilityRootDialog の Browse パターン踏襲）。**HIGH-1 (OSError 捕捉)** + pr-test rating 4-7 (browse → run end-to-end / BUSY 双方向 / TOML 未設定 + browse / title 定数化) を統合 | 2 ファイル / +480 / -17 |

**累計差分**: 23 ファイル / +1141 / -1940 = **net -799 行** (Launcher リファクタの大量削除を含む)

### Issue Net 変化（Session 36）

```
## Issue Net 変化
- Close 数: 4 件 (#150, #151, #154, #155)
- 起票数: 5 件 (#158, #161, #162, #164, #165)
- Net: -1 件 ❌ KPI マイナス
```

#### Net マイナスの分析

5 件中 2 件は silent-failure-hunter HIGH 由来 (rating ≥ 7 確実、triage #4 該当):
- #161, #164 → 起票必須

3 件は Medium 由来 (rating 5-6 borderline、triage 厳密適用なら PR コメント / TODO で扱うべき):
- #158 (codex Medium、診断性低下) → 起票根拠: 別 PR で実装予定の独立スコープ
- #162 (silent-failure-hunter Medium ×2 統合) → 起票根拠: ADR 追記要件、本 PR スコープ外
- #165 (silent-failure-hunter Medium、UX) → 起票根拠: 将来 UX 改善 TODO

#### 反省点

triage 厳密適用なら起票は HIGH 2 件 (#161/#164) のみで `Net = Close 4 − 起票 2 = +2` (KPI ポジティブ) が想定値。実際は `Net = 4 − 5 = −1` で KPI マイナスに転じたため、Medium 3 件の起票判断は PR コメント・既存 Issue 追記で代替可能だった反省点が残る。

**Session 37 以降の方針**: rating ≥ 7 + confidence ≥ 80 を機械的に適用。ADR 追記要件等の「設計タスク」は別系統の TODO 管理を検討。

### 主要な技術的成果

#### 1. PII 防御の構造化 (PR #157 C1)

`_validate_facility_aliases` の 3 箇所の raise メッセージから `'{alias}'` プレースホルダを除去し、構造的なエラー種別のみ含む形に統一。
ADR-014 PII 防御に準拠し、actionable error 経路を介した logger.error への alias / 事業所名漏洩を防ぐ。

```python
# Before: raise ValueError(f"... duplicate alias '{alias}' within ...")
# After:  raise ValueError("... contains a duplicate alias within ...")
```

logger 出力では「facility_aliases contains a duplicate alias within the same facility」のような構造的メッセージのみで、具体的にどの alias かは config TOML を直接確認する運用とする。

#### 2. 型強化の構造的昇格 (PR #159、Issue #151)

`PdfMergeConfig.concat_order` を `list` → `tuple` に変更し、構築後 mutation を AttributeError / TypeError で **型レベル阻止**。
type-design-analyzer Enforcement 6/10 → **9/10** に昇格 (減点 1 は dataclass 自体が `frozen=False` のため `cfg.concat_order = [...]` 全置換は依然可能、`+=` 経路も同様)。

`__post_init__` 先頭で `if not isinstance(self.concat_order, tuple): self.concat_order = tuple(self.concat_order)` の fail-safe を追加し、TOML / settings.py / 既存テスト経由の list 入力を呼出側の漏れを fail-safe に吸収。

#### 3. exit code 規約の確立 (PR #157)

CLI の exit code を 1 (runtime error) と 2 (setup-time / config error) で区別。`reports = "bad"` のような TOML 形状エラーも `_coerce_facility_aliases` と同じく TypeError で fail-fast し exit code 2 側に寄せる。

#### 4. Launcher 簡素化 (PR #160、Issue #154)

`ui/launcher.py` 542 → 200 行 (-342)。executor / busy 状態管理を撤去し、同期 callback のみで成立する設計に。`pdf/pipeline.py:run_phase_a/run_phase_b` 等は ADR-013 方針でコード資産として残置 (Quality Gate 投資 19 件以上保護)。

業務フロー順 3 ボタン構成: ex_ 変換 (①) → 事業所結合 (③) → 設定。

#### 5. ExExtractorDialog の柔軟性向上 (PR #163、Issue #155)

毎回違う取込元から処理可能になり、業務上の不便を解消。FacilityRootDialog の Browse パターンを踏襲し UI 一貫性確保。

OSError 捕捉 (HIGH-1) で Windows UNC・ネットワーク切断・権限拒否時の silent failure を解消。logger に型名のみ + messagebox で actionable 通知。

### Quality Gate 実績

| PR | /review-pr エージェント数 | /codex review | 発見した重要指摘 |
|----|--------------------------|---------------|-----------------|
| #157 | 4 並列 | ✅ 実施 | C1 (rating 90+, PII 漏洩) → 本 PR 修正、HIGH (`reports = "bad"` exit code 漏れ) → 本 PR 修正 |
| #159 | 4 並列 | ⏭️ (中規模) | type-design 9/10 昇格、Critical Gap 3 件 (TOML isinstance / merger end-to-end / `+=` contract) → 本 PR 修正 |
| #160 | 4 並列 | ⏭️ (削除中心) | Important 2 件 (削除済シンボル参照 / 未使用 fixture) + HIGH-2 確認 (CLI 側に `assert_never` 残存) → 本 PR 修正 |
| #163 | 4 並列 | ⏭️ (中規模) | HIGH-1 (Path OSError) + pr-test rating 4-7 (4 件) → 本 PR 修正 |

**Codex セカンドオピニオン (PR #157)** は 4 エージェントが見落とした「`data.get("reports", {}).get(...)` の AttributeError → exit code 1 漏れ」を発見し、本 PR で修正。**memory `feedback_codex_review_value.md` の事例追加候補**。

### 次回再開コマンド

```bash
# Mac 側
cd /Users/yyyhhh/Projects/wiseman_auto_sys
git checkout main && git pull --ff-only
# main HEAD が da6490f であることを確認 (Session 36 マージ後 + handoff PR マージ後)
gh issue list --state open

# Windows 機側 (TeamViewer 経由) — PR #160/#163 の実機検証
cd $HOME\Projects\wiseman-auto-sys
git pull --ff-only
# PyInstaller リビルド + 配備
.\scripts\build-and-deploy.ps1  # (存在しないなら手順は archive 参照)
# Launcher が 3 ボタン構成 (ex_ 変換 / 事業所結合 / 設定) で起動することを確認
# ExExtractorDialog で「取込元選択...」ボタン押下 → folder browser → 選択 → 表示更新を確認
```

---

# 旧サマリ: Session 35 完了 - PR4 配備検証 (AC-1 (3) + ショートカット起動) 完走

**更新日**: 2026-04-29（Session 35 / Windows 実機検証 + Launcher 設計議論）
**main HEAD**: `1e1fbe8` (Session 35 はコード変更なし、検証 + Issue 起票 + handoff doc のみ)

## 検証完走（Windows 実機 + TeamViewer 経由）

| 項目 | 状態 | 根拠 |
|------|------|------|
| Phase 0 事前確認 | ✅ | exe LastWriteTime/Length が Session 32 終了時と一致 |
| AC-1 (1) Launcher 起動・コンソール非表示 | ✅ | スクショ① |
| AC-1 (2) 5 ボタン目「ex_ ファイル変換 + 振り分け」表示 | ✅ | スクショ① |
| **AC-1 (3) 5 ボタン目クリック → ExExtractorDialog 起動** | ✅ | スクショ② (PR4 #135 統合決定的確認) |
| Phase 2 ショートカット経由起動で新 exe 起動 | ✅ | Get-Process Path 確認 |

## 業務フロー整理（Session 35 確定）

```
[Wiseman ダウンロード] → .ex_ 群
       ↓
   ① ex_ ファイル変換 + 振り分け           ← Launcher ボタン (PR4 統合済)
       ↓
   ② BC PDF 生成 (B 計画書 + C 報告書)      ← 未実装、次セッション指示待ち
       ↓
   ③ 事業所フォルダ一括結合                ← Launcher ボタン (ADR-013 実装済)
```

ユーザー認識「現業務フロー (① → ② → ③) で **PDF マージ処理 (旧 ②b フロー) は使わない**」確定。Issue #154 で UI 経路除去 → Session 36 で実装完了。

## Issue Net (Session 35)

- Close: 0 / 起票: 2 (#154 / #155、ユーザー明示指示) / **Net: -2 件**

## 学び

1. ADR を業務フロー全体の根拠として活用する (ボタン削除候補は ADR + commit 時系列 + コード実態の 3 点セットで裏取り)
2. 業務フロー位置づけの確認は decision-maker の領分 (executor として推奨は出すが最終決定はユーザーに委ねる)
3. 観察事項は handoff doc に記録、安易に Issue 化しない

詳細: `docs/handoff/archive/2026-04-history.md` Session 35 セクション (Session 36 でアーカイブ移動予定)

---

## 5 PR シリーズ進捗（ex_extractor 統合）

| # | スコープ | 状態 |
|---|---------|------|
| PR1 | 設定スキーマ拡張（`ex_source_dir` + `facility_aliases`） | ✅ Merged (#130) |
| PR2 | `pdf/facility_resolver` 純粋ロジック | ✅ Merged (#131) |
| PR3 | `pdf/ex_extractor` core + SFX adapter + macOS fake runner | ✅ Merged (#133) |
| PR4 | デスクトップ UI 統合 | ✅ Merged (#135) |
| PR5 (A 選択) | Windows 実機検証 runbook + ADR-014 Accepted 昇格条件 | ✅ Merged (#137) |
| PR5 実機検証 AC-1 (3) + Phase 2 | ✅ Session 35 で完走 |
| PR5 実機検証 AC-2〜AC-14 | ⏳ Session 37+ | `pr5-ex-extractor-runbook.md` §2-2 |
| Session 36 派生 (Issue #154/#155) | ✅ Mac 側完了、Windows 実機検証 持ち越し |
| PR6（将来） | settings.py タブ化 | ⬜ |

---

## 積み残し Issue (Session 36 終了時点、open 15 件)

### P1（open、最優先）

- **#6**: PoC E2E テスト（ログイン→CSV抽出→GCSアップロード）

### P2（open、Session 36 派生）

- **#158**: 起動後 callback の load_config 失敗 actionable 化（codex 由来）
- **#161**: GUI 再統合時の messagebox マッピング再構築要件（HIGH 由来）
- **#162**: 同期 callback UI フリーズ + callback 例外保護（Medium ×2 統合）
- **#164**: ExExtractorViewModel.source_dir setter 検証（HIGH 由来）
- **#165**: GUI 選択した取込元の「(セッション限定)」UX hint（Medium）

### P2（open、継続）

- **#152**: UserNameBBox NaN/inf + OcrBackendConfig 空白 URL 検証
- **#27**: config dataclass 全体の型設計強化（PR-A/B 完了 / B-2 残存検討）
- **#11**: PywinautoEngine MEDIUM 5 件
- **#16**: test_new_registration_flow Pane/Text 経路カバー
- **#17**: smoke_real.py を pytest 統合
- **#29**: OCR proxy nice-to-have 改善
- **#39**: フリガナベース matching

### P2（monitor）

- **#134**: Gemini 2.5 Flash retire 2026-10-16 — 再開条件 `asia-northeast1` GA OR 2026-09-16
- **#63**: Linux Tk wiring tests skip — 再開条件は Issue 最新コメント参照

---

## 重要な設計判断（最新）

### Session 36 — exit code 規約 + PII フリー alias 検証

- exit code 1 (runtime) / 2 (setup-time / config error) を CLI で明示区別
- `_validate_facility_aliases` の raise メッセージから alias 文字列を除去 (PII 防御 ADR-014 準拠)
- `PdfMergeConfig.concat_order` を tuple 化 (mutation bypass を型レベル阻止)
- Launcher を 3 ボタン構成 (業務フロー順) に簡素化、`pdf/pipeline.py` 等は ADR-013 方針で資産残置

### Session 35 — 業務フロー 3 ステップ確定

- ① ex_ → 振り分け（実装済 PR4）
- ② BC PDF 生成（未実装、次セッション指示待ち）
- ③ 一括結合（実装済 ADR-013）
- 旧 ②b（PDF マージ + 確認待ちセッション）は **完全 deprecated** → Session 36 で UI 除去完了

### 過去セッションの設計判断（履歴）

- ADR-014 (Proposed): ex_extractor 統合の業務フロー位置づけ + 5 PR シリーズ + 誤配布防止 KPI
- ADR-013 (Accepted): 事業所ルート一括結合 + §既存単一事業所ダイアログの扱い (UI 経路除去既決)
- ADR-012 (Accepted): 事業所単位 1 ファイル ABCABC 連結
- ADR-011 (Accepted): 配布パッケージ仕様
- ADR-010: 人間確認 state machine（旧ワークフロー由来、Session 36 で UI 経路から除去完了）
- 詳細: `docs/handoff/archive/2026-04-history.md` Session 11-34

---

## ADR 状態

- 14 件すべて Status 確定
- 最新 ADR-014 は `Proposed` のまま、AC-2〜14 完走後に `Accepted` 昇格予定
- §PR5 Accepted 昇格条件 で機械的判定可能な昇格条件を明記
- Session 36 で新規 ADR 追加なし

---

## セッション再開手順 (Session 37)

### Mac 側

```bash
cd /Users/yyyhhh/Projects/wiseman_auto_sys
git checkout main && git pull --ff-only
# main HEAD が da6490f以降 (Session 36 マージ後) であることを確認
gh issue list --state open
```

### 次セッション開始時の意思決定

1. **業務フロー ② BC PDF 生成の指示受け** — ユーザー明示「次セッションに指示」継続
2. **PR #160/#163 の Windows 実機検証** — PyInstaller リビルド + 配備、Launcher 3 ボタン + ExExtractorDialog Browse 動作確認
3. **#152 着手判断** — Mac で完結可能 (UserNameBBox NaN/inf 検証等の型強化)
4. **AC-2〜14 残作業（Windows 機）** — runbook §2-2 推奨方式 B (.ps1 ラッパー) + 3 種 fixture

### Windows 機側 (TeamViewer 経由)

```powershell
cd $HOME\Projects\wiseman-auto-sys
git pull --ff-only
# PyInstaller リビルド + 配備して Launcher 3 ボタン構成 + ExExtractorDialog Browse を確認
notepad docs/handoff/pr5-ex-extractor-runbook.md
```

---

## 参照ファイル

### Session 36 成果物（最新）

- `src/wiseman_hub/app.py`: `WisemanHub.__init__` で load_config 例外捕捉 (PR #157)
- `src/wiseman_hub/__main__.py`: main() の exit code 1/2 区別 (PR #157)、Launcher 注入から旧 callback 除去 (PR #160)
- `src/wiseman_hub/config.py`: `_validate_facility_aliases` PII フリー化 (PR #157)、`concat_order` tuple 化 (PR #159)、`reports` 形状検証 (PR #157)
- `src/wiseman_hub/ui/launcher.py`: 542 → 200 行に簡素化 (PR #160)
- `src/wiseman_hub/ui/ex_extractor_dialog.py`: 取込元選択ボタン + OSError 捕捉 (PR #163)
- `src/wiseman_hub/pdf/review_flow.py`: GUI adapter 削除に伴う docstring 更新 (PR #160)

### 重要 doc

- `docs/handoff/pr5-ex-extractor-runbook.md`: AC-2〜14 実機検証 runbook
- `docs/handoff/ex-test-fixtures.md`: 3 種 fixture 仕様
- `docs/handoff/session32-pr5-ex-extractor-ac1-resume.md`: Session 32 中断 + AC-1 (3) チェックリスト（Session 35 で完走）
- `docs/adr/014-ex-extractor-integration.md`: §業務フロー上の位置づけ + §PR5 Accepted 昇格条件
- `docs/adr/013-facility-root-bulk-merge.md`: §既存単一事業所ダイアログの扱い (UI 経路除去既決、Session 36 で実装完了)
- `docs/adr/012-facility-merger-output-format.md`: §業務要件の背景 (A/B/C の業務的意味)

### 履歴

- `docs/handoff/archive/2026-04-history.md`: Session 11-34 詳細
- Session 35 は本 LATEST.md 旧サマリ参照
- Session 36 は本 LATEST.md トップサマリ
