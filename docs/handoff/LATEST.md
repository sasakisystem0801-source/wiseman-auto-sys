# Handoff: 事業所フォルダ PDF 結合 MVP + タスク 10-2 完走（Session 19 終了時点）

**更新日**: 2026-04-24
**ブランチ**: main（clean、PR #108 マージ済）
**main**: 39f9723 (PR #108 squash merged: feat(pdf): facility_merger - 事業所フォルダ PDF 結合 (MVP 暫定))

## セッション 19 の成果（最大コミット: +2,245 行）

### マージ済み
- **PR #108**: feat(pdf): facility_merger - 事業所フォルダ PDF 結合 (MVP 暫定)
  - 12 files, +2,245 lines / 5 commits（feat + refactor + ui + fix + docs）
  - **「A提供実績 + B運動機能向上計画書 + C経過報告書」を利用者単位で結合する新機能**
  - **Windows 実機で 18 ページ A から 19 名全員の氏名抽出成功、3 種全結合含め 19 件出力達成**
  - ユーザーゴール「OCR（テキスト認識）による A+B+C 正しい順序結合」完全達成

### 実装範囲
- **コア**: `src/wiseman_hub/pdf/facility_merger.py` (+358 行)
  - `merge_facility(source_a, facility_dir, output_root)` 本体
  - Phase 1: A.pdf 各ページを分割 → 氏名抽出 → B/C 姓マッチ → 3 者結合
  - Phase 2: A 未マッチの B/C 残余を相互マッチして結合
  - 9 フィールドの `FacilityMergeReport`（success / extraction_failed_pages / a_only / a_missing / b_missing / c_missing / name_conflicts / ambiguous_bc_skipped）
  - 既存 `splitter._extract_single_page_pdf` / `merger._append_pdf_file` / `merger._save_atomically` を private 再利用（将来 public 化予定）
- **氏名抽出**: `src/wiseman_hub/pdf/text_name_extractor.py` (+96 行)
  - Pattern 1（ラベル隣接型）: `氏名 姓 名 様` — 計画書・経過報告書向け
  - Pattern 2（フリガナ隣接型）: `半角カタカナ行 + 改行 + 漢字姓名` — 提供実績チェックリスト向け（実帳票で「氏名」ラベルと実名が別セルで離れているケース対応）
  - OCR 不要（全て `page.get_text()` によるテキスト層抽出）
- **CLI**: `scripts/merge_facility.py` (+274 行)
  - 本実行モード + `--diag` 事前診断モード（書込なしで氏名抽出 / B/C マッチプラン表示）
- **GUI**: `src/wiseman_hub/ui/facility_merger_dialog.py` (+275 行) + `launcher.py` 修正
  - Launcher 4 ボタン目「事業所フォルダ結合」追加
  - Toplevel ダイアログ（A.pdf / 事業所フォルダ / 出力ルート の 3 入力 + 実行 + 結果テキスト）
- **テスト**: 新規 30 tests（facility 17 + text_name 17 + dialog 5、dialog は Tk_required で skip 許容）
- **ドキュメント**: `docs/handoff/folder-merger-mvp-runbook.md`（30 分完走ランブック）+ `folder-merger-mvp-testing.md`（検証結果テンプレート）

### 本セッションの Quality Gate 適用フロー
1. `/impl-plan` で 11 タスク分解 + AC-FM-1〜7 + AC-UI-FM-1〜2 定義
2. TDD: RED → GREEN → Refactor（text_name_extractor → facility_merger → CLI → GUI）
3. `/simplify` 3 並列 → Important 3 件反映
4. `/safe-refactor` → UNC OSError / PermissionError / 同姓衝突 など HIGH 複数指摘
5. **Evaluator 分離プロトコル（新機能追加で発動）**: REQUEST_CHANGES → HIGH 2 件対応（Phase 2 対称化 + a_only 排他分岐）
6. `/review-pr` 6 並列 → Important 3 件（CLI PII / `_collect_pdfs_by_stem` silent drop / Raises docstring）対応
7. **`/codex review` セカンドオピニオン**: **HIGH 1 件検出（同姓重複時 B/C 誤添付）→ fail-safe で構造的防止**
   - `ambiguous_bc_skipped` フィールド追加、A.pdf pre-scan で姓カウント → 重複姓は B/C 添付スキップ
8. 合計 5 commits で指摘反映（feat 初版 → refactor review-pr 対応 → feat UI 追加 → fix Codex HIGH → feat diag + runbook）

### Windows 実機検証の実経過（AC-FM-7 完走）
1. TeamViewer 接続 → `git pull` → `uv sync` → `pytest` 通過
2. `--diag` 初回実行: **A.pdf 18 ページ全てで氏名抽出失敗**
3. 原因調査（`fitz.Page.get_text()` の生 repr 確認）: 提供実績チェックリストのテキスト層は「氏名」ラベルと実名が**別セル**で配置されており、既存 Pattern 1 がマッチせず
4. Pattern 2（フリガナ隣接型）を追加実装 + push
5. 再診断: **18 ページ全員の氏名抽出成功**（浅尾 和司 / 塩津 美喜子 / 尾島 亮子 他）
6. 本実行: **19 件出力**（A+B+C: 2 件 [塩津・尾島] / A+B: 1 件 [藤野] / A+C: 4 件 / A のみ: 11 件 / Phase 2: 1 件 [asao]）
7. 塩津.pdf 目視確認: **A（提供実績）→ B（運動器機能向上計画書）→ C（利用経過報告書）の順序で別人混入なく結合成功**
8. GUI 経由実行: 同じ 19 件結合成功、PII 防御（full_name 非表示）動作確認

### Session 19 の学び
- **Codex セカンドオピニオンが致命バグを事前検知**: 6 並列 review-pr が見逃していた「同姓 2 名 + B/C 1 ファイルで誤添付」を Codex が HIGH 指摘、Windows 実機検証前に fail-safe で構造防止完了。医療データ文脈で不可欠なレビュー構成
- **実データを見てから正規表現を書く**: 最初の「氏名 姓 名 様」パターンは Image #17（A.pdf 1 ページ目スクショ）のレイアウト先行イメージで書いてしまい、実際のテキスト層順序に合わなかった。Windows で `page.get_text()` の repr を見て初めて実データ構造が判明。テキスト層 PDF でも**「見た目」と「テキスト順序」は別物**
- **事前診断モード (`--diag`) の価値**: 書込なしで「実データ × 実装の整合」を早期検知できる設計が実機 1 発成功に直結。18 ページ抽出失敗の段階で本実行を止め、手戻りゼロで Pattern 2 追加に転換できた
- **ファイル名表記揺れの実運用確認**: A/B で「塩津 美喜子」、C で「塩津 美貴子」と漢字が違うケース（実運用の現実）でも、姓「塩津」の部分一致マッチで同一人物として正しく結合できた。表記揺れ対応の設計価値
- **`/clear` 後の過去画像アクセス**: `~/.claude/projects/{project}/` セッション JSONL に画像 base64 が残っており、`jq` + `base64 -d` で過去セッション画像を抽出可能。ユーザー記憶の「以前送った」B/C PDF 中身スクショを見つけ出し、実帳票構造の仮説立てに使えた

### Issue Net 変化（本セッション）
- **Close**: 0 件
- **起票**: 0 件
- **Net: 0 件**
- **進捗評価**: Issue 駆動ではなく**タスク 10-2（Windows 実機 E2E）完走 + 新機能 2,245 行追加**。ユーザー明示指示（本番 Windows PDF 結合検証）の達成 = CLAUDE.md GitHub Issues セクション #5 該当。本セッションでは rating 5-6 相当の改善提案は全て PR 内で吸収し、追加 Issue 起票なし（triage 基準厳守）

### 総変更量（Session 19）
- 12 files changed, +2,245 / -8 lines
- テスト件数: 502 passed → **537 passed**（+35: facility_merger 17 + text_name_extractor 17 + launcher 1 更新）
- skip: 68（dialog 5 件の Tk_required 追加）
- 全ローカル検証 PASS（pytest 537 / ruff / mypy 33 source files）
- CI: 全 SUCCESS（test-unit 3.11/3.12 + test-integration Windows）

## セッション 18 の成果（サマリー）
- **PR #104**: Issue #38 - `atomic_io` ユーティリティ抽出（7 files, +540/-72）。`write_bytes_atomically` + `save_atomically` 新設、merger/session/config 置換。**Issue #38 CLOSED**
- **PR #106**: Issue #105 - session `_sweep_stale_session_tmp` 追加（3 files, +329/-1）。mtime 60s 閾値、`except OSError` 分割（FileNotFoundError silent + Counter 型別集計）。**Issue #105 CLOSED**
- Net: **-1**

## セッション 17 の成果（サマリー）
- **PR #102**: Issue #68 - `validate_form` 戻り値 `ValidationError` enum 化（2 files, +246/-52）。`ValidationCode` (StrEnum 10 種) + `match/case` + `typing.assert_never`。**Issue #68 CLOSED**, Net: -1

## セッション 16 の成果（サマリー）
- **PR #100**: Issue #72 + #97 - review_flow 共通化（6 files, +1410/-129）。CLI/GUI 二重実装を `pdf/review_flow.resolve_review_session` に集約。**Issue #72 + #97 CLOSED**, Net: -2

## セッション 15 の成果（サマリー）
- **PR #96**: Issue #73 - `on_open_review` `ReviewCallbackResult` dataclass 化 + 8 cancel path → `CANCEL_RESULT` sentinel。**Issue #73 CLOSED**, Net: -1

## 過去セッション詳細
Session 11-14 の詳細は `docs/handoff/archive/2026-04-history.md` を参照。

## 次タスク優先順位

### 優先 1: facility_merger MVP の実運用展開（Session 19 継続）

**前提**: Session 19 で CLI + GUI 両経路の Windows 実機検証完了、19 件結合成功。以下は実運用に向けた改善タスク。

#### 1-A: 表記揺れ吸収の強化
実運用で確認された不整合:
- 「塩津 美喜子」（A/B）vs 「塩津 美貴子」（C）← 今回は姓一致で結合成功
- 「asao」（B、ローマ字）vs A.pdf 内氏名（漢字）← 今回は A マッチできず Phase 2
- 「【藤野様】」（B）vs A 抽出「藤野」← 部分一致で結合成功

**改善候補**: フリガナ正規化（半角↔全角カタカナ）、名前マッチ閾値調整、【様】除去の明示化。

#### 1-B: B/C PDF 内容抽出による氏名マッチング
現在は B/C ファイル名ベース。**B/C の PDF テキスト層からも氏名抽出**して内容ベースマッチ化すれば、ファイル名の揺らぎから完全に独立できる。`text_name_extractor.extract_name_from_page` の Pattern 1（氏名ラベル型）は既に運動機能向上計画書・経過報告書に適用可能。

#### 1-C: exe 再ビルド + 配布先差し替え
`wiseman_hub.spec` は facility_merger_dialog 分の hiddenimports 更新なしで動くはずだが、実機ビルド確認が必要。配布先 `%USERPROFILE%\wiseman-hub\wiseman_hub.exe` の上書き手順は `docs/handoff/folder-merger-mvp-runbook.md` に記載済。

#### 1-D: 親フォルダ + 複数サブフォルダ選択 UI
ユーザー要件の最終形。`\\Tera-station\share\03.FAX(事業所)` 配下を列挙 → Listbox で複数選択 → 一括実行。P2 以降実装候補。

#### 1-E: worker thread 非同期化（進捗バー）
現状 GUI は同期実行で一時フリーズ。`Launcher._schedule_phase_a_done` と同様のパターンで非同期化。

### 優先 2: タスク 14D（ADR-011 Accepted 昇格）
10-2 完了により ADR-011 Status を Proposed → Accepted に昇格。SmartScreen 実画面記録を反映（今回は警告なしで通過した実測結果）。

### 優先 3: P2 refactor 系 Issue（継続）
- **#44**: Session/UserCandidate immutable 化（updated_at mutation 排除）
- **#45**: SourceKind StrEnum 統一（#27 と連動可能）
- **#27**: config dataclass 型設計強化
- **#49**: resume 時の candidates 検証

### 優先 4: CI / 運用
- **#63**: Linux CI Tk wiring skip
- **#29**: OCRプロキシ Nice-to-have 改善

## 積み残し Issue / 技術負債

### Session 19 で CLOSED
- なし（新機能実装、既存 Issue は tasks/10-2 積み残し消化として扱い）

### Session 18 以前で CLOSED
- ~~**#38**~~（Session 18、atomic_io 抽出）
- ~~**#105**~~（Session 18、session sweep）
- ~~**#68**~~（Session 17、ValidationError enum）
- ~~**#72**~~ / ~~**#97**~~（Session 16、review_flow 共通化）
- ~~**#73**~~（Session 15、ReviewCallbackResult）
- ~~**#51**~~ / ~~**#58**~~ / ~~**#71**~~ / ~~**#50**~~ / ~~**#64**~~（Session 13）

### P2（open、refactor 系、優先）
- **#44**: Session/UserCandidate immutable 化
- **#45**: SourceKind StrEnum 統一
- **#27**: config dataclass 型設計強化
- **#49**: resume 時 candidates 検証

### P2（open、継続）
- **#80**: Windows 実機 smoke で Phase B / OCR import 検証
- **#63**: Linux CI Tk wiring skip
- **#40**: B と C で異なる名前が距離0マッチした場合の扱い
- **#39**: フリガナベースのマッチング
- **#29**: OCRプロキシ Nice-to-have 改善
- **#17**: smoke_real.py pytest 統合
- **#16**, **#14**, **#11**, **#6**: 各種改善

## impl-plan 進捗（Session 19 終了時点）

| タスク | 状態 | PR |
|--------|------|-----|
| 10-1 Cloud Run デプロイ + 疎通確認 | ✅ merged | #60, #89 |
| **10-2 Windows 実機 E2E** | ✅ **Session 19 完走（facility_merger 経由、19 件結合成功）** | #108 |
| 11 README + sample TOML | ✅ merged | #85 |
| 12A TOML 書き戻し機能 | ✅ merged | #60 |
| 12B 設定 GUI | ✅ merged | #66 |
| 12C 初回起動ウィザード | ⏳ 優先度低 | - |
| 13A ランチャー GUI 骨格 | ✅ merged | #61 |
| 13B ランチャー ↔ Phase A 統合 | ✅ merged | #65 |
| 13C ランチャー ↔ 確認 UI / Phase B 統合 | ✅ merged | #74 |
| **13D ランチャー「事業所フォルダ結合」統合** | ✅ **Session 19** | #108 |
| 14A PyInstaller spec | ✅ merged | #79 |
| 14B アイコン生成 | ✅ merged | #60 |
| 14C ショートカット配布手順 | ✅ merged | #82 |
| **14D ADR-011 Accepted 昇格** | ⏳ 10-2 結果反映後（次セッション） | - |
| 15 GitHub Actions + WIF | ⏳ GUI 安定後 | - |

## セッション再開手順（コピペ可）

```bash
cd /Users/yyyhhh/Projects/wiseman_auto_sys
git checkout main
git pull --ff-only

# 優先1-A: 表記揺れ吸収（facility_merger 改善）
# 優先1-B: B/C PDF 内容抽出によるマッチング（ファイル名非依存化）
# 優先1-C: exe 再ビルド + 配布先差し替え
# 優先1-D: 親フォルダ + 複数サブフォルダ選択 UI
# 優先1-E: GUI worker thread 非同期化

# 優先2: 14D ADR-011 Accepted 昇格

# 優先3: P2 refactor 系（#44, #45, #27, #49）

# 優先4: CI / 運用 (#63 Linux Tk skip)
```

## Quality Gate の実効性（Session 2-19 累積）

- **/simplify** 3 並列: 各 PR で Important 3-6 件修正
- **Evaluator 分離**: Session 16 で REQUEST_CHANGES 1 件 / 18 で MEDIUM 2 件 / **19 で HIGH 2 件**（Phase 2 対称化 + a_only 排他分岐）検出
- **6 Agent + Codex 二段レビュー**:
  - Session 9〜15: 各段で Codex HIGH / MEDIUM 指摘複数回検出
  - Session 18: PR #104 で Codex plan review が HIGH 2 件（try/finally + PdfMergeError ラップ維持）を計画段階で検出
  - **Session 19**: **Codex review が同姓重複時 B/C 誤添付 HIGH 指摘 → fail-safe で構造的防止**（医療データ誤配布の致命バグを実機検証前に回避）
- **`--diag` 事前診断モード**（Session 19 導入）: 書込なしで「実データ × 実装の整合」を早期検知、実機 1 発成功に直結
- **`except OSError` 分割パターン**（Session 18 確立）: race silent continue + 型別集計 → atomic_io / session / facility_merger で一貫

## 参照ファイル（次セッション用）

### Session 19 成果物
- `src/wiseman_hub/pdf/facility_merger.py`: merge_facility() 本体、9 フィールド報告 dataclass、Phase 1/2 両対称マッチ
- `src/wiseman_hub/pdf/text_name_extractor.py`: Pattern 1 (ラベル) + Pattern 2 (フリガナ) フォールバック
- `src/wiseman_hub/ui/facility_merger_dialog.py`: Toplevel ダイアログ（DI 対応）
- `src/wiseman_hub/ui/launcher.py`: 4 ボタン構成（OPEN_FACILITY_MERGER action 追加）
- `scripts/merge_facility.py`: CLI + `--diag` 診断モード
- `docs/handoff/folder-merger-mvp-runbook.md`: 30 分完走実機ランブック
- `docs/handoff/folder-merger-mvp-testing.md`: 検証結果テンプレート

### 履歴
- `docs/handoff/archive/2026-04-history.md`: Session 11-14 詳細
