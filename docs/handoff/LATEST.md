# Handoff: Session 35 完了 - PR4 配備検証 (AC-1 (3) + ショートカット起動) 完走 + 業務フロー整理 + Issue 起票×2

**更新日**: 2026-04-29（Session 35 / Windows 実機検証 + Launcher 設計議論）
**ブランチ**: main
**main HEAD**: `1e1fbe8` refactor(config): 新規 3 型に Literal + __post_init__ 検証を追加 (Refs #27 PR-A) (#149)
（Session 35 はコード変更なし、検証 + Issue 起票 + handoff doc のみ）

## 次セッション主軸

**メイン = デスクトップアプリ実装（リファクタ系 Issue は引き続き touch しない）**

### 次セッションの最優先（ユーザー指示待ち）

1. **BC PDF 生成機能の入出力指示** — Session 35 でユーザー明示「次セッションに指示」
   - 入力: 何のファイル / どこから?
   - 出力: `{facility_name}/運動機能向上計画書/{利用者名}.pdf` 形式に直接振り分け?
2. **B/C PDF の元データソース** — 同上、次セッション指示待ち

### 次セッションで着手可能（明示認可済の作業）

3. **Issue #154 別 PR 実装** — Launcher 旧ワークフロー UI 経路除去（PDF マージ + 確認待ちセッション）
4. **Issue #155 別 PR 実装** — ExExtractorDialog 取込元フォルダ選択 UI 追加
5. **AC-2〜AC-14 残作業（Windows 機）** — `pr5-ex-extractor-runbook.md` §2-2 推奨方式（test.toml + WISEMAN_HUB_CONFIG）

## Session 35 の成果

### 検証完走（Windows 実機 + TeamViewer 経由）

| 項目 | 状態 | 根拠 |
|------|------|------|
| Phase 0 事前確認 | ✅ | exe LastWriteTime/Length が Session 32 終了時と一致 (78,632,876 bytes / 2026-04-28 8:00:08) |
| AC-1 (1) Launcher 起動・コンソール非表示 | ✅ | スクショ① |
| AC-1 (2) 5 ボタン目「ex_ ファイル変換 + 振り分け」表示 | ✅ | スクショ① |
| **AC-1 (3) 5 ボタン目クリック → ExExtractorDialog 起動** | ✅ | スクショ② (PR4 #135 統合決定的確認) |
| Phase 2 ショートカット経由起動で新 exe 起動 | ✅ | Get-Process Path = `C:\Users\sasak\wiseman-hub\wiseman_hub.exe`, StartTime 23:14:04-05 |

### 起票 Issue（triage #5 ユーザー明示指示）

| # | タイトル | ラベル |
|---|---------|--------|
| #154 | refactor(ui): Launcher から旧ワークフロー UI 経路を除去 (PDF マージ処理 / 確認待ちセッション) | P2, enhancement |
| #155 | feat(ui): ExExtractorDialog に取込元フォルダ選択 UI を追加 (TOML 固定 → GUI 都度選択) | P2, enhancement |

### 業務フロー整理（Session 35 確定）

```
[Wiseman ダウンロード] → .ex_ 群
       ↓
   ① ex_ ファイル変換 + 振り分け                            ← Launcher ボタン 4 (PR4 統合済)
       ↓
       事業所フォルダに A PDF が振り分けられる
       ↓
   ② BC PDF 生成 (B 運動機能向上計画書 + C 経過報告書)        ← 未実装、次セッション指示待ち
       ↓
       事業所フォルダに A/B/C 3 種が揃う
       ↓
   ③ 事業所フォルダ一括結合 (ABCABC 連結)                    ← Launcher ボタン 3 (ADR-013 実装済)
       ↓
       配布用 PDF 完成
```

ユーザー認識：「現業務フロー (① → ② → ③) で **PDF マージ処理 (旧 ②b フロー) は使わない**」確定。

### Launcher 削除後の構成（Issue #154 で実装予定）

```
削除前 (現状):                       削除後 (3 ボタン構成):
1. PDF マージ処理を実行              1. ex_ ファイル変換 + 振り分け    ← ① 業務フロー起点
2. 確認待ちセッション                2. 事業所フォルダ一括結合        ← ③ 一括再結合
3. 事業所フォルダ一括結合            3. 設定
4. ex_ ファイル変換 + 振り分け
5. 設定
```

### 観察事項（次セッション以降の追跡候補）

1. **ExExtractorDialog の「取込元 (.ex_): .」表示**
   - `ex_extractor_dialog.py:313` の `Path(config.pdf_merge.ex_source_dir or ".")` フォールバック挙動
   - `config.toml` 未編集状態（Session 32 から継続）でカレントディレクトリ "." を表示
   - Issue #155 で GUI 選択 UI 追加予定 → "." 表示問題は構造的に解消

2. **wiseman_hub プロセス 2 個起動**
   - ショートカット起動で 2 プロセス確認 (Id 7732, 11140 / StartTime 23:14:04-05)
   - PyInstaller onefile bundle の bootstrap loader + main process の典型挙動と推定
   - Issue #46 (セッションロック実装) との相互作用要追跡 — 2 重起動防止が想定通り効いているか実機確認候補

### Issue Net 変化（Session 35）

- **Close: 0 件**
- **起票: 2 件** (#154 / #155)
- **Net: -2 件** ❌ KPI マイナス

#### Net マイナスの分析

両起票ともユーザー明示指示（triage #5）で起票。**rating ベースの review エージェント起票ではなく、業務フロー再設計の意思決定に伴う UI 変更要件**。CLAUDE.md GitHub Issues 起票条件 #5「ユーザーから明示的に指示された個別タスク」に明確に該当。

triage 機械的判定:
- #154: ADR-013 §既存単一事業所ダイアログの扱い (2026-04-27) で「UI 経路除去」が既決方針 → Session 35 で実行決断
- #155: 既存 UX 不一致 (FacilityRootDialog はフォルダ GUI 選択あり、ExExtractorDialog はなし) を業務上の不便として明示

両 Issue とも「次セッションで別 PR で実装する」段取りで、長期滞留しない設計。

### 学び（次セッション以降の自衛策）

1. **ADR を業務フロー全体の根拠として活用する**
   - Session 35 で「ボタン 1, 2 はダミー」と最初に誤判定 → コード追跡で「実装は完成、ADR-013 で UI 経路除去既決」が判明 → 訂正
   - 削除候補を提示する前に、ADR 根拠 + commit 時系列 + コード実態の 3 点セットで裏取りする

2. **業務フロー位置づけの確認は decision-maker の領分**
   - 「現場で旧ワークフロー使っていますか？」の確認なしに削除推奨を AI で確定しない
   - executor として推奨は出すが、業務運用の最終決定は本田さんに委ねる

3. **観察事項は handoff doc に記録、安易に Issue 化しない**
   - wiseman_hub プロセス 2 個起動は「実機検証で観察した事象」止まりで、影響評価前に Issue 起票しない
   - 関連 Issue (#46) との相互作用を次回検証で確認してから判断

### 次回再開コマンド

```bash
# Mac 側（状況確認のみ、コード変更は Windows + 設計議論主体）
cd /Users/yyyhhh/Projects/wiseman_auto_sys
git checkout main && git pull --ff-only
# main HEAD が 1e1fbe8（PR #149）であることを確認 (Session 35 はコード変更なし)
gh issue list --state open

# Windows 機側（次セッションで継続）
# 1. AC-2〜AC-14 残作業: pr5-ex-extractor-runbook.md §2-2 推奨方式 B
cat docs/handoff/pr5-ex-extractor-runbook.md
# 2. Issue #154 / #155 別 PR 実装着手 (decision-maker 判断後)
gh issue view 154
gh issue view 155
# 3. BC PDF 生成機能の指示受け (ユーザー明示「次セッションに指示」)
```

### Open Issue 推移

- Session 35 開始時: 12 件
- Session 35 終了時: 14 件 (+2: #154/#155)

### Git 状態 (Session 35 終了時点)

- main HEAD: `1e1fbe8`（変更なし）
- handoff PR feature ブランチ: `docs/handoff-session-35`
- ブランチ: docs/handoff-session-35（このセッションでの作業ブランチ）
- CI: success (Session 34 時点、Session 35 でのコード変更なし)

---

# 旧サマリ: Session 34 完了 - PR #149 マージ + Mac 側打ち止め記録

**更新日**: 2026-04-28（Session 34 / Mac で進められる範囲で打ち止め）
**main HEAD**: `1e1fbe8` refactor(config): 新規 3 型に Literal + __post_init__ 検証を追加 (Refs #27 PR-A) (#149)

## マージ済 PR

| PR | Issue | 内容 | 規模 |
|----|-------|------|------|
| #149 (1e1fbe8) | #27 PR-A | 新規 3 型 (`OcrBackendConfig`, `UserNameBBox`, `PdfMergeConfig`) に Literal + `__post_init__` 検証 + `is_configured` + `merger._KNOWN_KINDS` を `VALID_CONCAT_LETTERS` に統合 (DRY) | 6 ファイル / +306 / -64 |

### Issue #27 段階実装の方針

- PR-A ✅ (Session 34): 新規 3 型
- PR-B: 既存 6 型横展開 — 次セッションで見送り、別途タイミングで
- PR-C: Path 型移行 → ROI 低い、Issue #151 (tuple 化) で型強化に振り替え

### Issue Net（Session 34）

- Close: 0 / 起票: 3 (#150 P1 / #151 P2 / #152 P2、すべて PR #149 レビュー由来) / **Net: -3 件 ❌**

### 学び

- **CRITICAL silent failure を即「スコープ外」と判定しない**: PR #149 の初判定で UI 層 cast を「別 Issue」としたが、最小修正で対応可と判明
- **`Issue #27` 等のタスク参照を docstring に書かない**: CLAUDE.md「Don't reference the current task」原則を 8 箇所違反、レビュー指摘で発覚
- **rating 6-7 borderline の Issue 起票判断**: PR スコープ追加で対処可能なら Issue 化しない (#151/#152 反省)

---

# 旧サマリ: Session 33 完了 - PR #146/#147 マージ + Issue Net -3 件

**更新日**: 2026-04-28（Session 33 / Issue #45 + #14 完了 + #40 検討 close）
**main HEAD**: `7de14ee` refactor(rpa): export_csv 失敗モードを ExportCsvError 階層で区別化 (Closes #14) (#147)

## マージ済 PR (Issue Net -3 件)

| PR | Issue | 内容 | 規模 |
|----|-------|------|------|
| #146 (607ad29) | #45 完了 ✅ | SourceKind を Literal から StrEnum に統一 (JSON 検証一元化) | 4 ファイル / +101 / -22 |
| #147 (7de14ee) | #14 完了 ✅ | export_csv 失敗モードを ExportCsvError 階層 (5 サブクラス) で区別化 | 6 ファイル / +280 / -35 |

### 検討して close した Issue

- **#40** (CLOSED not planned): B/C 異名 distance 0 マッチエッジケース
  - impl-plan 起動 → 数学的に「両方 distance 0 + 異名」は matcher の評価関数の対称性により発生不可能と判明
  - revert + Issue コメントに検討プロセス記録 (実装前に dead code 発見できた Generator-Evaluator 分離の成功例)

### 学び

1. **`patch.dict(sys.modules)` の落とし穴**: with 終了時に「with 内で追加された全キー」を削除する。新規 import は patch.dict ブロックの **前** に置く
2. **Issue 起票時の前提が誤りの場合の対応 (#40 教訓)**: impl-plan 段階で dead code 判明 → 即座に revert + Issue close (not planned) + 検討プロセス記録
3. **Codex review が 6 エージェント見落としを発見**: PR #147 で 6 並列が見落とした「印刷ボタン取得失敗が ExportCsvError 階層外」を Codex が発見 → **大規模 PR (3+ ファイル / 200+ 行) では `/codex review` セカンドオピニオンが価値あり**

---

# 旧サマリ: Session 32 中断 + macOS 側 A1-A5 検証準備整備完了

**更新日**: 2026-04-28（Session 32 / Windows 実機中断後、macOS 側で A1-A5 マージ済）
**main HEAD (当時)**: `cf9f8b1` docs(handoff): Session 32 中断記録 + PR5 検証準備整備 (A1-A5) (#144)

## 進捗

### 午前: Windows 11 実機（TeamViewer 経由）

- **Phase 0-1 完了**: exe バックアップ + `git pull --ff-only` (`f4a242e` 同期) + `uv sync --extra dev` + PyInstaller ビルド成功 (78,632,876 bytes / 2026-04-28 8:00:08)
- **Phase 2-1 完了**: 新 exe を `~/wiseman-hub/wiseman_hub.exe` に配備
- **AC-1 (1)(2) PASS**: Launcher 起動 + 5 ボタン目「ex_ ファイル変換 + 振り分け」表示確認
- **中断**: TeamViewer タイムリミットで AC-1 (3) 未実施 → Session 35 で完走

### 午後: macOS 側 A1-A5 検証準備整備（PR #144 マージ済）

- A1: runbook §2-2 config パス誤記修正
- A2: `config/test.toml.example` 新規 + `WISEMAN_HUB_CONFIG` 経路で本番 NAS 非汚染
- A3: `session32-...md` AC-1 (3) 実機チェックリスト精緻化
- A4: `docs/handoff/ex-test-fixtures.md` 新規（3 種 fixture 仕様）
- A5: ショートカット起動の env var 非継承落とし穴を runbook §2-2 に明文化

### Issue Net（Session 32）: 0 件（中断中、コード変更なし）

---

## 5 PR シリーズ進捗（ex_extractor 統合）

| # | スコープ | 状態 |
|---|---------|------|
| PR1 | 設定スキーマ拡張（`ex_source_dir` + `facility_aliases`） | ✅ Merged (#130) |
| PR2 | `pdf/facility_resolver` 純粋ロジック | ✅ Merged (#131) |
| PR3 | `pdf/ex_extractor` core + SFX adapter + macOS fake runner | ✅ Merged (#133) |
| PR4 | デスクトップ UI 統合 | ✅ Merged (#135) |
| PR5 (A 選択) | Windows 実機検証 runbook + ADR-014 Accepted 昇格条件 | ✅ Merged (#137) |
| **PR5 実機検証 AC-1 (3) + Phase 2** | **Session 35 で完走** ✅ | スクショ + Get-Process |
| PR5 実機検証 AC-2〜AC-14 | ⏳ Session 36+ | `pr5-ex-extractor-runbook.md` §2-2 |
| PR6（将来） | settings.py タブ化 | ⬜ |

---

## 積み残し Issue (Session 35 終了時点)

### P1（open、最優先）

- **#6**: PoC E2E テスト（ログイン→CSV抽出→GCSアップロード）
- **#150** (bug): load_config の例外未ハンドル: malformed TOML で startup crash

### P2（open、Session 35 起票）

- **#154**: Launcher 旧 UI 経路除去（次セッション別 PR）
- **#155**: ExExtractorDialog 取込元フォルダ選択 UI 追加（次セッション別 PR）

### P2（open、継続）

- **#151**: PdfMergeConfig.concat_order tuple 化
- **#152**: UserNameBBox NaN/inf + OcrBackendConfig 空白 URL 検証
- **#27**: config dataclass 全体の型設計強化（PR-A 完了 / PR-B 残存）
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

### Session 35 — 業務フロー 3 ステップ確定

ADR-014 §業務フロー上の位置づけ + コード時系列 + ユーザー明示で確定:
- ① ex_ → 振り分け（実装済 PR4）
- ② BC PDF 生成（未実装、次セッション指示待ち）
- ③ 一括結合（実装済 ADR-013）
- 旧 ②b（PDF マージ + 確認待ちセッション）は **完全 deprecated** → Issue #154 で UI 経路除去

### 過去セッションの設計判断（履歴）

- ADR-014 (Proposed): ex_extractor 統合の業務フロー位置づけ + 5 PR シリーズ + 誤配布防止 KPI
- ADR-013 (Accepted): 事業所ルート一括結合 + §既存単一事業所ダイアログの扱い (UI 経路除去既決)
- ADR-012 (Accepted): 事業所単位 1 ファイル ABCABC 連結
- ADR-011 (Accepted): 配布パッケージ仕様
- ADR-010: 人間確認 state machine（旧ワークフロー由来、Issue #154 で UI 経路から除去予定）
- 詳細: `docs/handoff/archive/2026-04-history.md` Session 21-31

---

## ADR 状態

- 14 件すべて Status 確定
- 最新 ADR-014 は `Proposed` のまま、AC-2〜14 完走後に `Accepted` 昇格予定
- §PR5 Accepted 昇格条件 で機械的判定可能な昇格条件を明記
- Session 35 で新規 ADR 追加なし

---

## セッション再開手順 (Session 36)

### Mac 側

```bash
cd /Users/yyyhhh/Projects/wiseman_auto_sys
git checkout main && git pull --ff-only
# main HEAD が 1e1fbe8（PR #149）であることを確認
gh issue list --state open
```

### 次セッション開始時の意思決定

1. **業務フロー ② BC PDF 生成の指示受け** — ユーザー明示「次セッションに指示」、入出力仕様確定後に impl-plan
2. **Issue #154/#155 別 PR 着手判断** — Mac で完結可能 (UI 変更 + テスト)、Windows 実機リビルド + 検証は完了後
3. **AC-2〜14 残作業（Windows 機）** — runbook §2-2 推奨方式 B (.ps1 ラッパー) + 3 種 fixture

### Windows 機側 (TeamViewer 経由)

```powershell
cd $HOME\Projects\wiseman-auto-sys
git pull --ff-only
# Issue #154/#155 PR がマージされていれば PyInstaller リビルド + 配備
# AC-2〜14 へ進む場合: docs/handoff/pr5-ex-extractor-runbook.md §2-2 方式 B
notepad docs/handoff/pr5-ex-extractor-runbook.md
notepad docs/handoff/ex-test-fixtures.md
```

---

## 参照ファイル

### Session 35 成果物（最新）

- なし（コード変更なし、handoff doc + Issue #154/#155 のみ）

### 重要 doc

- `docs/handoff/pr5-ex-extractor-runbook.md`: AC-2〜14 実機検証 runbook
- `docs/handoff/ex-test-fixtures.md`: 3 種 fixture 仕様
- `docs/handoff/session32-pr5-ex-extractor-ac1-resume.md`: Session 32 中断 + AC-1 (3) チェックリスト（Session 35 で完走）
- `docs/adr/014-ex-extractor-integration.md`: §業務フロー上の位置づけ + §PR5 Accepted 昇格条件
- `docs/adr/013-facility-root-bulk-merge.md`: §既存単一事業所ダイアログの扱い (UI 経路除去既決)
- `docs/adr/012-facility-merger-output-format.md`: §業務要件の背景 (A/B/C の業務的意味)

### 履歴

- `docs/handoff/archive/2026-04-history.md`: Session 11-31 詳細
- Session 32-34 は本 LATEST.md 旧サマリ参照
- Session 35 は本 LATEST.md トップサマリ
