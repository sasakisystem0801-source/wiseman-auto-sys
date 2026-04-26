# Handoff: facility_merger 新仕様完走（Session 24 終了時点）

**更新日**: 2026-04-27（merge 後の同期更新）
**ブランチ**: main（PR #124 squash merge 済）
**main HEAD**: `4216828` feat(facility-merger): 事業所単位 1 ファイル ABCABC 連結に仕様変更（明日納品）(#124)

## セッション 24 の成果（1 PR、4 commits → squash merge、合計 +906 / -738 行）

### マージ済 ✅
- **PR #124** (squash merge `4216828`): feat(facility-merger): 事業所単位 1 ファイル ABCABC 連結に仕様変更（明日納品）
  - 5 files (`facility_merger.py` / `test_facility_merger.py` / `facility_merger_dialog.py` / `merge_facility.py` / `LATEST.md`)
  - 4 commits（squash 前）:
    1. `e83228b` feat: 仕様変更コア（旧仕様 19 テスト削除 → 新 16 テスト）
    2. `d5ab50c` fix: Critical 5 件即修正（review 指摘）
    3. `295d791` fix: 除外表示重複バグ修正（実機で発覚）
    4. `eb147c9` docs: ハンドオフ更新
  - CI: 全 SUCCESS（test-integration 2m22s / test-unit 3.11 57s / 3.12 57s）
  - **ADR-012** 別 PR で作成（本 cleanup PR、`docs/adr/012-facility-merger-output-format.md`）

### 業務要件と仕様変更の本質

**ユーザー要望（明日納品）**: 「複数名分が 1 ファイルに ABCABC 連結された PDF が欲しい」

| 項目 | 旧仕様 | 新仕様 |
|------|--------|--------|
| 出力ファイル | `{output}/{facility}/{user_key}.pdf` × N 利用者 | `{output}/{facility}/{facility}.pdf` の **1 ファイル** |
| 連結対象 | A単独/A+B/A+C/A+B+C/B+C すべて出力 | **A+B+C 全揃いのみ** |
| 連結順序 | 利用者ごとに完結 | A1+B1+C1 + A2+B2+C2 + ... (A.pdf 出現順) |
| 除外利用者の扱い | 部分情報で出力 | 出力に含めず report にカテゴリ別記録 |
| 同姓重複 fail-safe | A のみ出力 | 完全除外 (`ambiguous_bc_skipped`) |

### 実機動作確認実績（きなり(メール)※持参 シナリオ）

- 入力: 提供実績.pdf + `//Tera-station/share/03.FAX(事業所)/きなり(メール)※持参`
- **結合 6 名**: 宇都宮・尾島・塩津・曽根・日浦・藤野（A→B→C 順）
- 除外 15 名: A のみ 6 / B 欠損 6 / a_missing 3
- 出力: `きなり(メール)※持参.pdf` 1 ファイル
- **目視確認: 別人混入なし** ✅

### Issue Net 変化（本セッション）
- **Close**: 0 件（merge 後に「優先 1-C 完走」の文脈で次セッションで実施）
- **起票**: 0 件（review 指摘は本ハンドオフで TODO 集約、起票は本田様の運用判断後）
- **Net: 0 件**

進捗評価: ユーザー明示指示「明日納品の業務要件」に基づくスコープ拡大 PR、CLAUDE.md GitHub Issues #5（ユーザー明示指示で個別タスク化）該当。1-C ランブックとは別ルートだが、結果として 1-C の核心目標「facility_merger 機能を実機エンドユーザーが使える」を達成。

### Quality Gate 履歴（PR #124）

| ゲート | 結果 |
|-------|------|
| `/impl-plan` Acceptance Criteria 8 項目 | ✅ |
| TDD（RED → GREEN → REFACTOR） | ✅ 新仕様 8 件 fail → 実装 → 全 PASS |
| pytest（macOS） | ✅ 559 passed / 68 skipped |
| ruff / mypy | ✅ All checks passed / 33 files no issues |
| `/simplify` 3 並列相当 + `/safe-refactor` | ✅ code-reviewer + evaluator agents |
| Evaluator 分離プロトコル | ✅ REQUEST_CHANGES（AC-5）→ 検証テスト追加で解消 |
| `/review-pr` 6 並列 | ✅ Critical 5 件 → 即修正済 |
| `/codex review` セカンドオピニオン | ⏭ ユーザー判断でスキップ（既に code-reviewer + evaluator + 6 並列で十分） |
| Windows 実機 ビルド + 配布 + 動作確認 | ✅ 6 名結合、別人混入なし、除外表示重複バグも解消 |

### Session 24 の学び

- **TDD の威力**: 「RED で 7/7 fail」→「GREEN で 7/7 PASS」の明確なシグナルが、4 ファイル横断の API 契約変更でも安全に進められた。AC-5 の output_path 検証も「fail を見て初めて気付く欠落」を埋められた
- **6 並列レビューの ROI**: code-reviewer + evaluator + 6 並列レビューの計 8 視点で **Critical 5 件 + Important 多数** を発見。特に silent-failure-hunter の「`_collect_pdfs_by_stem` の silent 全滅」と「`success.append` 順序による誤情報」は業務リスク級で、6 並列なしでは見落としていた可能性大
- **実機検証の不可逆価値**: テスト 19 件 + macOS smoke build PASS でも、実データで「除外表示の重複バグ」が発覚した。`_match_by_partial` のマッチ情報を `matched_bc_stems` に登録するタイミング問題は、テストではエッジケースとして発見されるまで気付けなかった。**実機検証は省略不可**
- **Codex セカンドオピニオン中断は許容**: 既に code-reviewer + evaluator + 6 並列で十分カバー。重複コストとリーク懸念から、Codex は次回（より深い設計判断時）に温存する判断が正しかった
- **明日納品の優先度判断**: ROI 低い指摘（DRY 集約、dataclass 化、Literal 化、`name_conflicts` 整理）は躊躇なく次セッション送り。**致命的のみ即対応 + 残りは構造化された TODO へ**

### 総変更量（Session 24）
- 1 PR, 4 files changed, +757 / -585 行
- 新規テスト: 19 件（新仕様 8 + Robustness 11）
- pytest: 559 passed / 68 skipped（前回 559 と同件数、内訳が刷新）
- 全ローカル検証 PASS / Windows 実機 PASS / CI 全 SUCCESS

## 次セッション送り（review 指摘の TODO 集約）

PR #124 merge 後、ROI 評価して必要に応じて Issue 化:

### 業務リスク系（silent-failure-hunter / 中優先）
- **CRIT-4 (例外型別メッセージ)**: `_on_run` の `except Exception` を `PdfMergeError` / `MemoryError` / `OSError` で型別 actionable メッセージに分離。介護施設職員にとっての可読性向上
- **IMP-1 (同姓重複 modal)**: ambiguous_bc_skipped が非ゼロなら UI に**赤字 modal** で強制告知。同姓 fail-safe による除外見落としを防ぐ
- **IMP-2 (stderr 複製)**: CLI 失敗時の summary を stderr にも複製。CI/cron 監視運用対応
- **IMP-3 (name_conflicts dead UI)**: 新仕様で意味縮退した `name_conflicts` を report から除去 or `ambiguous_bc_skipped` と統合

### コード品質系（code-reviewer + simplifier / 低優先）
- **I-1 (name_conflicts 汚染)**: ambiguous 経路で `_unique_key` を呼ばない構造に。Phase 0 の ambiguous 検出と Phase 1 の `_unique_key` の責務境界を明確化
- **C1 (DRY 集約)**: `_print_report` (CLI) と `_render_report` (Dialog) の重複ロジックを `format_report_lines` 等の pure 関数に切り出し。新除外カテゴリ追加時の二重メンテ解消
- **I1 (match-case)**: Phase 1 の連続 `if continue` を `match (b_match is None, c_match is None):` で明示
- **S1 (責務分割)**: `merge_facility` を `_detect_ambiguous_surnames` / `_classify_pages` / `_write_concatenated_pdf` に分割

### 型設計系（type-design-analyzer / 中優先）
- `UserMergeEntry.sources_used` を `Literal["A","B","C"]` の tuple に固定型化
- `__post_init__` で `sources_used == ("A","B","C")` 不変条件 runtime 強制
- 匿名 `tuple[str, bytes, Path, Path, str]` を `_FullSetEntry` dataclass 化（B/C 取り違え防止）

### テストカバレッジ系（pr-test-analyzer / 中優先）
- 出力ファイル既存時の上書き挙動テスト（atomic rename の二重実行）
- `PdfCorruptedError` テスト（空/破損 A.pdf）
- `OSError` / 出力先 read-only テスト
- 複数ページで extraction_failed 混在テスト（一部成功 + 一部失敗）
- `_match_by_partial` 逆方向マッチの境界テスト（異姓 B/C 誤マッチ防止）

### ドキュメント系（comment-analyzer / 低優先）
- `_unique_key` の docstring に「Phase 0 ambiguous 検出と独立して連番付与する WHY」明記
- 出力ファイル既存時の上書き挙動を docstring 明記
- `run_diagnostic` で first_name が stdout に出る件の PII 方針確認・コメント追加
- 事業所名にパス区切り文字含む場合のバリデーション追加（`_validate_user_name` 同等）

### 業務要件追加候補
- **真の五十音順**: 現状は A.pdf 出現順を継承（業務上 OK 想定）。もし真の五十音順が必要なら `text_name_extractor` 拡張でフリガナ取得 → ソート
- **事業所まとめ + 利用者別の両方出力**: ユーザーが「印刷用と個別配布用」両方欲しいと言えばオプション化検討

## セッション 23 の成果（直前のサマリ）

- **PR #122**: docs(runbook): 1-C exe 再配布ランブックを Session 22 終了時点に同期 + `uv sync --extra dev` 必須化
- **PR #123**: docs(handoff): Session 23 終了時点のハンドオフ更新 + Session 15-21 アーカイブ移動
- 副次成果: macOS smoke build 成功による事前検証パターンの確立

## 過去セッション詳細

Session 11-21 の詳細は `docs/handoff/archive/2026-04-history.md` を参照。
Session 22-23 の詳細は本ファイル下部 + 前回 LATEST.md（git log で参照可）。

## 次タスク優先順位

### 優先 1: 次セッション送り TODO の Issue 化判断

上記「次セッション送り」項目を本田様の運用フィードバックを見て個別 Issue 化。

CLAUDE.md Issue Triage 規範:
- **Issue 化対象**: 実害発生 / 再現可能なバグ / CI 破壊 / rating ≥ 7 & confidence ≥ 80 / ユーザー明示指示
- **PR コメント / TODO 留め**: rating 5-6 の任意改善

Critical 系（CRIT-4 / IMP-1 / IMP-2）は実害発生待ちで判断、コード品質系は本田様の継続運用次第。

### 優先 2: ADR-011 Accepted 昇格（旧 1-C のタスク 14D）

PR #124 で「facility_merger 機能を実機エンドユーザーが使える」状態を達成したので、ADR-011 を Proposed → Accepted に昇格させる別 PR を作成。**ADR-012 (本 cleanup で作成済) と同じ系統**。

### 優先 3: 過去から残る P2 Issue（変動なし）

- **#117**: Session.candidates / UserCandidate.similar_candidates を tuple 化
- **#80**: Windows 実機 smoke build で Phase B / OCR import 検証（タスク 15 で CI 自動化）
- **#63**: Linux CI Tk wiring skip
- **#45**: SourceKind StrEnum 統一
- **#27**: config dataclass 型設計強化

## 積み残し Issue / 技術負債

### Session 24 で CLOSED
- なし（PR #124 はユーザー明示指示由来、Issue ベースではない）

### Session 22-23 で CLOSED
- ~~**#49**~~ P1 bug `page_index 検証`（Session 22）

### P2（open、優先）
- **#117**: Session.candidates / UserCandidate.similar_candidates を tuple 化
- **#45**: SourceKind StrEnum 統一
- **#27**: config dataclass 型設計強化

### P2（open、継続）
- **#80**, **#63**, **#40**, **#39**, **#29**, **#17**, **#16**, **#14**, **#11**

### P1（open、継続）
- **#6**: PoC E2Eテスト

## impl-plan 進捗（Session 24 終了時点）

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
| **14D ADR-011 Accepted 昇格** | ⏳ **次セッション**（PR #124 merge 完了、ADR-012 と合わせて検討） | - |
| **新規: 事業所単位 1 ファイル仕様（明日納品）** | ✅ **完走** (squash merge `4216828`、ADR-012 作成済) | #124 |
| 15 GitHub Actions + WIF | ⏳ GUI 安定後 | - |

## セッション再開手順（コピペ可）

### 次セッション開始時（Session 25）

```bash
cd /Users/yyyhhh/Projects/wiseman_auto_sys
git checkout main
git pull --ff-only
# PR #124 が merge 済なら HEAD が新 commit に更新される
gh issue list --state open
```

### 本田様への運用フィードバック確認後

1. silent-failure-hunter Critical 系 (IMP-1/2/3) を Issue 化判断
2. ADR-011 Accepted 昇格 PR 作成（タスク 14D）
3. 真の五十音順 / 印刷用 PDF オプション 等の追加要件検討

## Quality Gate の実効性（Session 2-24 累積）

- **TDD**: Session 24 で「RED 7/7 fail → GREEN 7/7 PASS」の TDD 体験が新仕様の正確性を保証
- **6 並列レビュー**: Session 24 で **Critical 5 件**を即発見（silent-failure 3 + docstring 2）
- **実機検証**: Session 24 で「除外表示重複バグ」を実データで初発見（テスト + macOS smoke では未検出）
- **Codex セカンドオピニオン中断**: Session 24 で「既に code-reviewer + evaluator + 6 並列でカバー」と判断、重複コスト回避
- **`/impl-plan` Acceptance Criteria 8 項目**: Session 24 で 4 ファイル横断の API 契約変更を構造化、AC-5 の検証ギャップも evaluator が指摘

## 参照ファイル（次セッション用）

### Session 24 成果物（最新）
- `src/wiseman_hub/pdf/facility_merger.py` (PR #124): 事業所単位 1 ファイル ABCABC 連結実装
- `tests/unit/pdf/test_facility_merger.py` (PR #124): 新仕様 8 + Robustness 11 = 19 テスト
- `src/wiseman_hub/ui/facility_merger_dialog.py` (PR #124): 結合 N 名 + 除外内訳 + 重大警告表示
- `scripts/merge_facility.py` (PR #124): CLI + diag モード新仕様対応
- Windows 配布 exe: `C:\Users\sasak\wiseman-hub\wiseman_hub.exe` (78,541,735 bytes / 2026-04-26 22:45:51)

### Session 22-23 成果物
- `docs/handoff/1c-exe-redistribution-runbook.md` (PR #115/#122): 1-C ランブック
- `src/wiseman_hub/pdf/session.py` (PR #120): page_index invariant 検証

### 履歴
- `docs/handoff/archive/2026-04-history.md`: Session 11-21 詳細
