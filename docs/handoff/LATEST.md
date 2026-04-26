# Handoff: 事業所ルートフォルダ管理 + 一括/選択結合（Session 25 終了時点）

**更新日**: 2026-04-27
**ブランチ**: `feat/facility-root-bulk-merge`（main から分岐、PR 作成予定）
**main HEAD**: `d086f46` docs(handoff,adr): Session 24 cleanup - LATEST.md merge 反映 + ADR-012 作成 (#125)

## セッション 25 の成果（7 commits、+2632 / -11 行）

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

**累計**: 12 ファイル / +2620 行 / 新規テスト 94 件 / 全体 633 passed・回帰なし。

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
| Windows 実機ビルド + 配布 + 動作確認 | ⏳ **次セッション** |

### Evaluator 分離プロトコルの効果（Session 24 から継続）

`rules/quality-gate.md` に従い、AC 13 項目検証を独立コンテキストで実行。以下を 6 並列レビュー（PR #124 で実施したパターン）では未検出の盲点として発見:

1. **HIGH (X ボタン未バインド)**: `WM_DELETE_WINDOW` を `_on_close` に bind 漏れ → 実行中強制クローズで worker thread 宙吊り
2. **MEDIUM (logger.exception)**: scan エラーログでトレースバック経由のパス漏洩（PII 防御不統一）
3. **エッジ (busy 中の再スキャン)**: progress_callback サイレント失敗予防

修正コミット `48a1a72` で対応。Evaluator の独立判定の価値を改めて確認。

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

### Issue Net 変化（本セッション）

- **Close**: 0 件（merge 後判断）
- **起票**: 0 件（review 指摘は ADR-013 と本ハンドオフで TODO 集約）
- **Net: 0 件**

進捗評価: ユーザー明示指示「ルートフォルダ管理 + 一括/選択結合」の実装、CLAUDE.md GitHub Issues #5 該当。

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
| 14D ADR-011 Accepted 昇格 | ⏳ 次セッション（PR #124 + 本 PR の実機検証完了後） | - |
| 事業所単位 1 ファイル仕様（明日納品） | ✅ Session 24 | #124 |
| **事業所ルートフォルダ管理 + 一括/選択結合** | ⏳ **本 PR 作成中** | TBD |
| 15 GitHub Actions + WIF | ⏳ GUI 安定後 | - |

## セッション再開手順（コピペ可）

### 次セッション開始時（Session 26）

```bash
cd /Users/yyyhhh/Projects/wiseman_auto_sys
git checkout main
git pull --ff-only
gh pr list --author "@me" --state open  # 本 PR の状態確認
gh issue list --state open
```

### 本田様の Windows 実機検証後

1. AC-7 / AC-11 / AC-13 の実機確認結果を踏まえて ADR-013 を Proposed → Accepted に昇格
2. ADR-011 Accepted 昇格 PR 作成（タスク 14D）
3. 配布 exe 再ビルド + 配布
4. 運用フィードバックで上書き確認ダイアログ等の追加判断

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
