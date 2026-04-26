# ADR-012: facility_merger 出力仕様（事業所単位 1 ファイル ABCABC 連結）

## ステータス

**Accepted (2026-04-26)** — PR #124 で実装 + Windows 実機動作確認済（Session 24）。

## コンテキスト

facility_merger（事業所フォルダ PDF 結合）の MVP 暫定仕様（PR #108、Session 19）は
「利用者ごとに別ファイル `{output_root}/{facility_name}/{user_key}.pdf` × N 利用者」を
出力する設計だった。

しかし業務運用での明示的要求（2026-04-26、明日納品）により、出力形態を
「事業所単位で 1 ファイルに ABCABC 連結」に変更する必要が発生した。

### 業務要件の背景

介護記録 PDF の業務フローでは:
- A: 提供実績チェックリスト（複数利用者 1 ページずつ）
- B: 運動機能向上計画書（利用者単位、1 ファイル/人）
- C: 経過報告書（利用者単位、1 ファイル/人）

を**事業所ごとに 1 つの PDF にまとめて配布・印刷したい**という要求がある。
旧仕様（利用者ごと別ファイル）では事業所単位での扱いに毎回 N ファイル分の
処理が必要で、運用負荷が高かった。

### 制約

- **明日納品**: 2026-04-27 に本田様から介護施設へ配布
- **医療データ取扱**: 別利用者の B/C が混入したら業務事故（誤配布リスク）
- **既存 PR #108 のテスト 19 件 + Session 22 の P1 修正（PR #120）の実装基盤を活用**
- **Windows 実機**: pywinauto / fitz / Tk の動作実機検証必須

## 決定

### 出力仕様

| 項目 | 値 | 理由 |
|------|----|------|
| 出力ファイル | `{output_root}/{facility_name}/{facility_name}.pdf` の **単一ファイル** | 事業所単位での配布・印刷に最適 |
| 連結対象 | A + B + C **全揃い**の利用者**のみ** | 不揃い PDF は業務上意味がなく、別途個別対応 |
| 連結順序 | A→B→C 順、利用者間は **A.pdf の出現順** | A.pdf が業務上既に五十音順で並んでいる前提を継承（最低コスト実装） |
| 不揃い利用者の扱い | **出力 PDF に含めず**、`FacilityMergeReport` のカテゴリ別フィールドに記録 | 業務上「ABC 全揃いのみ正式扱い」、誤配布防止 |
| 同姓重複 fail-safe | **完全除外**（旧仕様の「A のみ出力」を廃止） | 別利用者の B/C 混入リスクを構造的に排除 |

### FacilityMergeReport の意味論変化

| フィールド | 旧仕様の意味 | 新仕様の意味 |
|-----------|------------|------------|
| `success` | 各利用者の出力 entry × N | ABC 全揃いで連結された利用者リスト（全 entry が同一 `output_path` を共有） |
| `a_only` | A のみ出力された利用者 | **除外**（B/C 両方なし） |
| `b_missing` | A + C が出力された利用者（B 欠損） | **除外**（B 欠損で連結対象外） |
| `c_missing` | A + B が出力された利用者（C 欠損） | **除外**（C 欠損で連結対象外） |
| `a_missing` | B + C のみで出力された利用者 | **除外**（A にマッチなし） |
| `ambiguous_bc_skipped` | A のみ出力された同姓利用者 | **完全除外**（出力 PDF に含めない） |
| `bc_dirs_missing` | （新規） | B/C サブフォルダ自体が不在の場合の警告（運用上重大） |

## 検討した代替案

### 利用者ごと別ファイル維持（旧仕様）
- 長所: 既存テスト 19 件をそのまま流用可能、実装変更最小
- 短所: 業務運用要求と乖離、本田様の明日納品要件未達
- 判断: 業務要件優先、却下

### 利用者ごと別ファイル + 事業所まとめ両方出力
- 長所: 既存運用を壊さず新機能追加
- 短所: 出力ファイル数が倍増、ストレージ/印刷コストが二重、業務担当者の管理負荷増
- 判断: 本田様の要望は「1 ファイル化が業務効率」なので両立不要、却下

### 真の五十音順ソート（フリガナ取得拡張）
- 長所: A.pdf の並びに依存せず、純粋な五十音順を保証
- 短所: `text_name_extractor` 拡張でフリガナ抽出 + ソート実装が必要、明日納品に間に合わない
- 判断: 当面は A.pdf 出現順を継承（業務上既に五十音順想定）。本田様の運用フィードバックで真の五十音順が必要になれば次セッションで対応

### 印刷時のページ順を ABABAB → CCCCCC のような種類別グルーピング
- 長所: 印刷物の見やすさ（同種類が連続）
- 短所: 業務上は利用者単位（ABCABC）が自然、種類別は集計用途で別オペレーション
- 判断: 業務要件は ABCABC、却下

## 影響

### 肯定的

- **業務要件達成**: 1 事業所 1 ファイルの配布・印刷が即可能
- **誤配布リスク低減**: ABC 全揃い + 同姓 fail-safe で別利用者の混入を構造的に排除
- **除外利用者の可視化**: `FacilityMergeReport` の各カテゴリで「なぜ含まれなかったか」を運用者が判断可能
- **重大警告の明示**: `bc_dirs_missing` で NW 一時断・タイポ等による silent 全滅を UI/CLI 冒頭で告知
- **コード簡素化**: 旧 Phase 2（B+C のみ結合）を廃止、`merge_facility` の責務が明確化
- **PII 防御維持**: `user_key`（姓のみ）+ 例外型名のみ表示の規律は新仕様でも継承

### 否定的

- **既存 PR #108 のテスト 19 件は再構築**（→ 新 19 件 = NewSpec 8 + Robustness 11、内容レベル検証もカバー。初版 PR #124-1 で 16 件、Critical 修正 +2 と実機バグ修正 +1 で計 19）
- **API 契約の破壊的変更**: `success` の意味が「各利用者出力」→「連結された利用者リスト」に変わる。dialog/CLI の対向側更新が必要（本 PR で対応済）
- **「五十音順」が A.pdf 出現順依存**: 業務上 A.pdf が五十音順で並んでいることが前提。崩れた場合は次セッションで真のソート実装が必要
- **出力ファイル既存時の上書き**: `_save_atomically` の `os.replace` で silent 上書き。同事業所 2 回連続実行で前回ファイルが消える（次セッションでドキュメント明記 or 確認 modal 検討）

### 業務リスク（次セッション対応候補）

review 指摘から:
- **CRIT-4**: `_on_run` の `except Exception` を型別に分離（介護施設職員向けの actionable メッセージ）
- **IMP-1**: ambiguous_bc_skipped 非ゼロ時の UI 赤字 modal 強制告知（同姓 fail-safe による除外見落とし防止）
- **IMP-2**: CLI 失敗時の summary を stderr 複製（CI/cron 監視運用対応）

## Acceptance Criteria（PR #124 で全クリア）

- [x] AC-1: 出力は `{output_root}/{facility_name}/{facility_name}.pdf` の 1 ファイルのみ
- [x] AC-2: ページ順 = `A1+B1+C1 + A2+B2+C2 + ...`（A.pdf 出現順）
- [x] AC-3: A単独/A+B/A+C/B+C は出力に含まれない
- [x] AC-4: 除外利用者を `a_only` / `b_missing` / `c_missing` / `a_missing` にカテゴリ別記録
- [x] AC-5: `report.success` 各 entry の `output_path` = `{facility_name}.pdf`、`sources_used` = `("A","B","C")`
- [x] AC-6: 同姓重複 fail-safe 維持、`ambiguous_bc_skipped` に記録
- [x] AC-7: macOS で pytest 559 passed / ruff clean / mypy 33 files no issues
- [x] AC-8: Windows 実機動作確認（きなり(メール)※持参 で 6 名結合、別人混入なし、除外 15 名カテゴリ別表示）

## 実装

PR #124（squash merge: `4216828`、Session 24）:

| 変更ファイル | 内容 |
|------------|------|
| `src/wiseman_hub/pdf/facility_merger.py` | `merge_facility()` 新仕様で再実装、`FacilityMergeReport.bc_dirs_missing` 追加 |
| `tests/unit/pdf/test_facility_merger.py` | 旧 19 テスト削除 → 新 19 テスト追加（NewSpec 8 + Robustness 11） |
| `src/wiseman_hub/ui/facility_merger_dialog.py` | 結合 N 名 + 除外内訳 + 重大警告表示に更新 |
| `scripts/merge_facility.py` | CLI + `--diag` モード新仕様対応 |

### 副次成果（Session 24 の review 経由）

- 実機検証で「除外表示の重複バグ」発覚 → 同 PR で修正（Phase 1 の `matched_bc_stems` 登録タイミング）
- 6 並列レビュー + Evaluator 分離で Critical 5 件即修正（silent failure 3 + docstring 2）
- silent-failure-hunter 指摘で `bc_dirs_missing` フィールド追加（NW 一時断対策）

## 次ステップ

### 短期（Session 25 候補）

- **本田様の運用フィードバック確認** → review 指摘 TODO の Issue 化判断
- **ADR-011 Accepted 昇格**（タスク 14D）— 14D の Acceptance 条件は ADR-011 に記載
- **CRIT-4 / IMP-1〜3** — 業務リスク系の即対応判断

### 中期

- **真の五十音順**: 本田様運用で「A.pdf の並びが五十音順でない」が判明した場合、`text_name_extractor` 拡張でフリガナ取得 → ソート
- **印刷オプション**: 「事業所単位 + 利用者ごと両方出力」の業務要望が出た場合のオプション機能化

### 長期

- B/C の PDF テキスト層から氏名抽出による内容ベースマッチ（Issue #117 系の発展）
- OCR フォールバック（B/C がスキャン画像の場合）

## 参考

- PR #108: facility_merger MVP 実装（旧仕様、Session 19）
- PR #120: Issue #49 page_index invariant 検証（Session 22）
- PR #124: 本 ADR の実装（Session 24、squash merge `4216828`）
- ADR-007: USB ドングル認証
- ADR-008: OCR バックエンド
- ADR-011: 配布形式（PyInstaller onefile）
- `docs/handoff/folder-merger-mvp-runbook.md`: 旧仕様の運用ランブック（仕様変更に伴い次セッションで更新検討）
- `docs/handoff/1c-exe-redistribution-runbook.md`: 1-C 配布手順（Session 22 同期、PR #122）
