# Handoff: facility_merger 回帰テスト強化 + exe 配布準備 + 1-C runbook 完備（Session 20 終了時点）

**更新日**: 2026-04-24
**ブランチ**: main（clean、PR #110 + #111 + #112 + #113 マージ済）
**main**: cfb7128 (PR #113 squash merged: docs(runbook): 1-C exe 再配布専用ランブック新設)

## セッション 20 の成果（4 PR、合計 +492 / -25 行）

### マージ済み
- **PR #110**: test(facility_merger): 複数利用者 × 混在可用性シナリオで A→B→C 順序と非混入を検証
  - 1 file, +132 lines（docstring 改善含む 2 commits）
  - Session 19 の Windows 実機 19 件結合のうち**目視確認は 1 件のみ**だったギャップを自動回帰テストで担保
  - `[SRC:A|B|C][USER:xxx]` 合成タグで 5 利用者 × 混在可用性（A+B+C / A+B / A+C / A のみ）を内容レベル検証
  - `/review-pr` 4 エージェント並列 → Important 1 件（docstring 明文化）対応、triage 基準未満 nice-to-have 5 件は PR コメント記録のみ

- **PR #111**: feat(spec): PyInstaller spec に facility_merger hiddenimports 追加（タスク 1-C 準備）
  - 1 file, +3 lines
  - `wiseman_hub.ui.facility_merger_dialog` / `wiseman_hub.pdf.facility_merger` / `wiseman_hub.pdf.text_name_extractor` を hiddenimports に明示
  - macOS smoke build で 3 モジュールの `Hidden import not found` warning 無しを事前検証
  - `/review-pr` code-reviewer: blocker/important/nice-to-have 全 0 件 → approve 推奨

- **PR #112**: docs(handoff): Session 20 ハンドオフ更新（+110 / -19 行、本ドキュメントの初版）

- **PR #113**: docs(runbook): 1-C exe 再配布専用ランブック新設（Windows 実機単独完走支援）
  - 2 files, +247 / -6 lines
  - 新規 `docs/handoff/1c-exe-redistribution-runbook.md`（Phase 0-5、rollback 手順付き、20-30 分想定）
  - 既存 `folder-merger-mvp-runbook.md` は「ソース実行での MVP 検証」向けで exe 配布フロー未カバーだったギャップを解消
  - Claude 不在の Windows 実機作業で stuck 発生を最小化する目的

### 次スプリント方針（Codex セカンドオピニオンで確定）

**実行順: PR1（1-C 配布）→ 実運用 1 回 → PR2（1-B 内容抽出）→ 必要なら 1-A → 1-D/1-E**

Codex 回答の核心:
> 現状の最大リスクは品質不足より「配布されず業務価値が発生しない」こと。MVP は E2E 済で A のみ出力も業務上の最低線を満たすため、まず限定展開して実データを得る判断に納得感がある。マイグレーションコストは大きくない（内部マッチ方式の改善なので出力仕様は変わらず、後追い可能）。1-C と 1-B を同一 PR にすると配布トラブル時の切り分けが悪化する。1-E はフリーズ時間が実害化してから、1-A も観測頻度を見てからで十分。

この方針に基づき、本セッションでは 1-C の Claude 側準備（spec 更新 = PR #111）まで完了。Windows 実機作業は次セッションで TeamViewer 経由で実施する。

### 1-C 完走のための残作業（次セッション、Windows 実機）

```
# 1. TeamViewer で Windows 11 PC に接続
# 2. プロジェクト最新化
cd %USERPROFILE%\Projects\wiseman_auto_sys
git pull --ff-only
uv sync

# 3. exe ビルド（spec は #111 で更新済）
uv run pyinstaller wiseman_hub.spec --clean --noconfirm

# 4. ビルドログ確認
# `Hidden import "wiseman_hub.pdf.facility_merger" not found` 等の warning が
# 出ていないことを目視確認

# 5. 配布先上書き（既存 exe は事前に .bak 退避推奨）
copy dist\wiseman_hub.exe %USERPROFILE%\wiseman-hub\wiseman_hub.exe

# 6. 動作確認
%USERPROFILE%\wiseman-hub\wiseman_hub.exe
# → Launcher 起動、4 ボタン目「事業所フォルダ結合」表示確認
# → Session 19 と同じ A.pdf + 事業所フォルダでダイアログ実行
# → 19 件出力（2 件 A+B+C / 1 件 A+B / 4 件 A+C / 11 件 A のみ / 1 件 Phase 2）
#   の再現を確認

# 7. 問題なければ ADR-011 Status を Proposed → Accepted に昇格（タスク 14D 完了）
```

### 1-B 着手メモ（次々セッション以降、PR2）

- 対象: `src/wiseman_hub/pdf/facility_merger.py` の `_match_by_partial` を**ファイル名ベース → 内容ベース優先**に拡張
- API 追加案: `text_name_extractor.extract_name_from_pdf_first_page(path: Path) -> ExtractedName | None`（B/C の 1 ページ目から氏名抽出）
- マッチ戦略: Phase 1 で A 姓と B/C 内容抽出氏名を照合 → 内容一致優先、ファイル名部分一致はフォールバック
- TDD fixture: `[SRC:B][USER:xxx]` に加えて `氏名 XX YY 様` を B 側に仕込み、**ファイル名を誤らせても**内容マッチで結合される検証
- PII 配慮: 抽出した氏名を `FacilityMergeReport` の missing 系フィールドに漏らさない（既存 `test_pii_not_in_missing_lists` の拡張）

### Issue Net 変化（本セッション）
- **Close**: 0 件
- **起票**: 0 件
- **Net: 0 件**
- **進捗評価**: Issue 駆動ではなく、Session 19 完成機能の (a) 回帰テスト自動化 + (b) exe 配布準備という**ユーザー明示指示（"複数結合のテスト成功を狙いたい" + "どう進めますか? PM/PL として納得させて"）に基づく scope 作業**。CLAUDE.md GitHub Issues セクション #5 該当。`/review-pr` 検出の rating 5-6 提案 5 件は全て PR コメントで記録、triage 基準（rating ≥ 7 かつ confidence ≥ 80）未満のため Issue 化せず（feedback_issue_triage.md 厳守）

### 総変更量（Session 20）
- 2 PRs, 2 files changed, +135 / -0 lines
- テスト件数: 537 passed → **538 passed**（+1: facility_merger `test_multi_user_ordered_merge_verifies_page_content`）
- skip: 68（変化なし）
- 全ローカル検証 PASS（pytest 538 / ruff / mypy 33 source files）
- CI: 全 SUCCESS（test-unit 3.11/3.12 + test-integration Windows、両 PR）
- macOS smoke build: `uv run pyinstaller wiseman_hub.spec --clean --noconfirm` 成功

### Session 20 の学び
- **Codex の PM/PL 的判断で優先度確信**: 「配布されないと業務価値ゼロ」という視点を明言してもらうことで、1-A/1-B の誘惑（技術的に面白い match 率改善）より 1-C（退屈な配布作業）が先、という判断に納得感が出た。1 人開発では「技術的興味」と「業務価値」が乖離しやすい
- **spec 更新を独立 PR にする価値**: 1-C を「spec 更新（PR 化可能）」と「Windows 実機作業（物理作業）」に分離したことで、Claude 側の貢献部分を明確化でき、レビュー & 事前検証（macOS smoke build）を先行できた。1 人開発でも「PR 化できる部分」と「物理作業」を分離するのは有効
- **内容レベルテストは目視確認の代替として強力**: Windows 実機 19 件結合の目視確認は 1 件で限界だが、`[SRC:X][USER:xxx]` 合成タグ方式でユニットテスト内で 5 利用者 × 4 パターン × ページ順序 + 非混入を自動検証できた。「目視が追いつかないなら機械可読マーカーで」は良い設計パターン

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

### 優先 1: facility_merger MVP の実運用展開（Codex 方針に基づく順序）

**前提**: Session 19 で CLI + GUI 両経路の Windows 実機検証完了（19 件結合成功）。Session 20 で (a) 回帰テスト自動化 + (b) spec hiddenimports 更新（1-C 準備）完了。以下が残タスク。

#### 🔥 **優先 1-C** (次セッション直後): exe 再ビルド + 配布先差し替え
**前提が整った**: Session 20 の PR #111 で `wiseman_hub.spec` の hiddenimports に facility_merger 関連 3 モジュール追加済、macOS smoke build 事前検証済。残るは Windows 実機での exe ビルド + 配布。

**専用 runbook**: `docs/handoff/1c-exe-redistribution-runbook.md`（Phase 0-5 構成、rollback 手順付き、20-30 分想定）

ランブック概要:
- Phase 0: 事前確認（git 状態、現行 exe バックアップ、pytest）
- Phase 1: exe ビルド（`uv run pyinstaller --clean`、hidden import warning 検査）
- Phase 2: 配布（`$HOME\wiseman-hub\wiseman_hub.exe` に上書き）
- Phase 3: 動作確認（Launcher 4 ボタン目 + Session 19 シナリオ再現 + 目視確認）
- Phase 4: rollback（失敗時の `.bak-*` 復元）
- Phase 5: 完走処理（ADR-011 Accepted 昇格、タスク 14D 兼務、PR 作成）

**業務価値**: これを実施するまでエンドユーザーは facility_merger 新機能を一切使えない。Codex 判断「配布されないと業務価値ゼロ」の該当タスク。

#### 🟡 **優先 1-B** (1-C 完走 + 実運用 1 回後): B/C PDF 内容抽出による氏名マッチング
**設計方針（Session 20 メモ）**: `text_name_extractor` に `extract_name_from_pdf_first_page(path)` 追加 → Phase 1 の `_match_by_partial` を「B/C 内容抽出氏名優先、ファイル名部分一致はフォールバック」に拡張。TDD fixture はファイル名を意図的に誤らせて内容マッチで結合することを検証。実運用 1 回の observed failure を fixture 化すれば投資対効果が最大化。

#### 🟢 **優先 1-A** (1-B 実装時に観測頻度を見て判断): 表記揺れ吸収の強化
実運用で確認された不整合（「塩津 美喜子」/「美貴子」、ローマ字「asao」、【藤野様】等）。Codex 判断「観測頻度を見てから」で即着手せず。1-B で内容マッチ化すれば多くは自然解消する見込み。

#### 🔵 **優先 1-D** (1-B 安定後): 親フォルダ + 複数サブフォルダ選択 UI
`\\Tera-station\share\03.FAX(事業所)` 配下を列挙 → Listbox で複数選択 → 一括実行。

#### 🔵 **優先 1-E** (フリーズ実害化後): worker thread 非同期化（進捗バー）
現状 GUI は同期実行で一時フリーズ。Codex 判断「実害化してから」で即着手せず。

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

### Session 20 で CLOSED
- なし（ユーザー明示指示 scope、triage 基準 #5 該当、Issue 駆動ではない）

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

### Session 20 成果物（本セッション）
- `tests/unit/pdf/test_facility_merger.py`: `test_multi_user_ordered_merge_verifies_page_content`（5 利用者 × 混在可用性 × 内容レベル順序検証）追加
- `wiseman_hub.spec`: facility_merger 関連 3 モジュールを hiddenimports に明示
- `docs/handoff/1c-exe-redistribution-runbook.md`: 1-C Windows 実機作業専用ランブック（Phase 0-5 + rollback、238 行）新設

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
