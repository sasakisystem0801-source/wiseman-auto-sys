# Handoff: Windows 実機 1-C 作業前準備完了（Session 23 終了時点）

**更新日**: 2026-04-25
**ブランチ**: main（clean、PR #122 マージ済）
**main**: ae96054 (PR #122 squash merged: docs(runbook): 1-C exe 再配布ランブックを Session 22 終了時点に同期)

## セッション 23 の成果（1 PR、合計 +13 / -8 行）

### マージ済み
- **PR #122**: docs(runbook): 1-C exe 再配布ランブックを Session 22 終了時点に同期 + `uv sync --extra dev` 必須化
  - 1 file, +13 / -8 行
  - Phase 0-3 期待 commit を Session 20 (#112 まで) → Session 22 (#121 まで) に更新
  - Phase 0-4 を `uv sync --extra dev` 必須化（macOS 事前検証で `Failed to spawn pyinstaller` 実害確認）
  - Phase 0-4 期待テスト件数を 538 → 559 に更新
  - トラブル早見表に「`Failed to spawn pyinstaller`」エントリを追加（`--extra dev` 忘れの典型症状）

### 副次成果（Windows 実機作業前の事前検証）
- **macOS smoke build 成功**: `uv run pyinstaller wiseman_hub.spec --clean --noconfirm` で Hidden import warning なし、`dist/wiseman_hub` 66MB 生成。Windows 側でも同等期待
- **ローカル全検証 PASS**: pytest 559 passed / 68 skipped、ruff clean、mypy 33 source files clean
- **副次バグ発見**: `uv sync` のみだと dev extras (pyinstaller/ruff/mypy/pytest) が削除される実害を確認 → runbook に反映済（Windows 実機での 5-10 分手戻り回避）

### Issue Net 変化（本セッション）
- **Close**: 0 件
- **起票**: 0 件
- **Net: 0 件**

進捗評価: ユーザー明示指示「Windows 実機テスト前事前準備」に基づくドキュメント PR、CLAUDE.md GitHub Issues #5（ユーザー明示指示で個別タスク化）該当。Issue 駆動ではなく実機作業前準備が本質。

### Quality Gate 履歴（PR #122）

| ゲート | 結果 |
|-------|------|
| `/impl-plan` | ⏭ 軽微なドキュメント PR、skip |
| TDD | ⏭ docs only |
| pytest / ruff / mypy | ✅ 559 passed / ruff clean / mypy 33 source files |
| `/simplify` / `/safe-refactor` | ⏭ 1 ファイル/+13 行で 3 ファイル未満閾値、skip |
| Evaluator 分離 | ⏭ docs only で 5 ファイル未満閾値、skip |
| `/review-pr` | ⏭ rules/quality-gate.md「ドキュメントのみの変更」適用外、手動チェックリストで対応 |
| `/codex review` | ⏭ scope 小（21 行）、skip |
| CI | ✅ test-unit 3.11/3.12 + test-integration Windows 全 SUCCESS |

### Session 23 の学び

- **macOS 事前 smoke build の価値**: 実機作業前にローカルでビルド検証することで、Windows 実機作業中の手戻りを構造的に防げる。今回は `Failed to spawn pyinstaller` を事前に特定し runbook に反映できた。1-C のような物理作業セッションでは「事前にローカルで再現できる検証は全てやる」が原則
- **`uv sync` vs `uv sync --extra dev`**: `pyproject.toml` の `optional-dependencies` の dev グループは `uv sync` のデフォルトで除外される仕様。プロジェクト全体で他にも `uv sync` 単独記載が複数あり（CLAUDE.md / folder-merger-mvp-runbook.md / windows-e2e-task10.md / README.md）。1-C 完走後の別 PR で一括修正候補
- **ドキュメント PR の品質ゲート判断**: rules/quality-gate.md「ドキュメントのみの変更」適用外規則に従い、`/review-pr` 6 並列を skip。手動チェックリスト + CI で十分（PR #115 / #122 で確立）

### 総変更量（Session 23）
- 1 PR, 1 file changed, +13 / -8 行
- テスト件数: 559 passed（変化なし、docs PR）
- skip: 68（変化なし）
- 全ローカル検証 PASS
- CI: 全 SUCCESS

## セッション 22 の成果（サマリー）

- **PR #120**: fix(session): Issue #49 page_index invariant 検証を load 時に追加（P1 bug）
  - 2 files, +210 / -1 行（2 commits: 初版 + レビュー指摘 fix-up）
  - `_candidate_from_dict` で `page_index` が `int >= 0` を検証（bool は int サブクラスだが明示除外）
  - `_from_dict` で candidates 内 `page_index` 一意性検証 + `total_pages_a` 設定時は範囲検証
  - `total_pages_a` の bool gotcha 対称化（Codex LOW #1 反映）
  - `TestPageIndexInvariant` クラス追加（8 tests）
  - エラーメッセージは PII-safe（session_id + page_index + 型名のみ）
  - **Issue #49 CLOSED** (P1 bug、Codex セカンドオピニオン由来 P1 昇格を完全解決)
  - Net: -1

## 過去セッション詳細
Session 11-21 の詳細は `docs/handoff/archive/2026-04-history.md` を参照。

## 次タスク優先順位

### 優先 1: facility_merger MVP の実運用展開（Codex 方針に基づく順序）

**前提**: Session 19 で CLI + GUI 両経路の Windows 実機検証完了（19 件結合成功）。Session 20-23 で (a) 回帰テスト自動化 + (b) spec hiddenimports 更新 + (c) Phase 3-B regression smoke + (d) P1 bug 修正 + (e) runbook 同期完了。**Claude 側の準備は全て完了**。残るは Windows 実機での exe ビルド + 配布のみ。

#### 🔥 **優先 1-C** (次セッション最優先): exe 再ビルド + 配布先差し替え

**専用 runbook**: `docs/handoff/1c-exe-redistribution-runbook.md`（Phase 0-5 構成、rollback 手順付き、20-30 分想定）

ランブック概要:
- Phase 0: 事前確認（git 状態、現行 exe バックアップ、`uv sync --extra dev` + pytest 559）
- Phase 1: exe ビルド（`uv run pyinstaller --clean`、hidden import warning 検査）
- Phase 2: 配布（`$HOME\wiseman-hub\wiseman_hub.exe` に上書き）
- Phase 3: 動作確認（Launcher 4 ボタン目 + Session 19 シナリオ再現 19 件結合 + 目視確認）
  - **Phase 3-B**: 既存機能 regression smoke（Launcher 1/2 ボタンの ImportError 不発生確認 = Issue #80 手動部分カバー）
- Phase 4: rollback（失敗時の `.bak-*` 復元）
- Phase 5: 完走処理（ADR-011 Accepted 昇格、タスク 14D 完了、PR 作成）

**業務価値**: これを実施するまでエンドユーザーは facility_merger 新機能を一切使えない。Codex 判断「配布されないと業務価値ゼロ」の該当タスク。

#### 🟢 **優先 2: Issue #117 (type-design follow-up)** — Session 22 影響箇所事前調査済

- `Session.candidates: list` → `tuple[UserCandidate, ...]`
- `UserCandidate.similar_candidates: list` → `tuple[CandidateState, ...]`
- `Session.config_snapshot: dict[str, Any]` → `Mapping[str, Any]` or `MappingProxyType`
- 影響箇所事前調査済（Session 22）:
  - 構築箇所: `pipeline.py:180/206/358/390`、`confirm_dialog.py:623/626`、`session.py:171/643/714`
  - 既に tuple: `matcher.py:176/190/197`
  - テスト fixture 全箇所書き換え必要（数十箇所想定）
- 規模感: 5+ ファイル、Evaluator 分離プロトコル発動閾値、~150-250 行
- 投資対効果: 現状 violation なし（PR #116 で全 mutation を `replace` に書換済）だが、将来の追加コードで型レベル防御を提供

#### 🟡 **優先 1-B** (1-C 実運用 1 回後): B/C PDF 内容抽出による氏名マッチング
- 対象: `facility_merger._match_by_partial` をファイル名ベース → 内容ベース優先に拡張
- API 追加: `text_name_extractor.extract_name_from_pdf_first_page(path) -> ExtractedName | None`
- Codex 方針: 実運用 1 回の observed failure を fixture 化して投資対効果最大化

#### 🟢 **優先 3**: その他 P2 refactor 系
- **#45**: SourceKind StrEnum 統一
- **#27**: config dataclass 型設計強化

#### 🔵 **優先 1-D / 1-E**（フリーズ実害化後 / 観測頻度を見て）
- 1-D: 親フォルダ + 複数サブフォルダ選択 UI
- 1-E: GUI worker thread 非同期化（進捗バー）
- 1-A: 表記揺れ吸収の強化（1-B で内容マッチ化すれば自然解消見込み）

### 優先 4: タスク 14D（ADR-011 Accepted 昇格）
1-C 完走と同時実施。Status を Proposed → Accepted に昇格、SmartScreen 実画面記録を反映。

### 優先 5: CI / 運用
- **#80**: Windows 実機 smoke build で Phase B / OCR import 検証（Phase 3-B で手動部分カバー、CI 自動化はタスク 15）
- **#63**: Linux CI Tk wiring skip
- **#29**: OCRプロキシ Nice-to-have 改善

## 積み残し Issue / 技術負債

### Session 22-23 で CLOSED
- ~~**#49**~~ P1 bug `page_index 検証`（Session 22、Codex セカンドオピニオン由来 P1 昇格 → 完全解決）

### Session 21 で CLOSED
- ~~**#44**~~ Session/UserCandidate immutable 化
- ~~**#118**~~ #49 と重複のため統合 close

### P2（open、refactor 系、優先）
- **#117**: Session.candidates / UserCandidate.similar_candidates を tuple 化（type-design HIGH、Session 22 影響箇所事前調査済）
- **#45**: SourceKind StrEnum 統一
- **#27**: config dataclass 型設計強化

### P2（open、継続）
- **#80**: Windows 実機 smoke で Phase B / OCR import 検証
- **#63**: Linux CI Tk wiring skip
- **#40**: B と C で異なる名前が距離0マッチした場合の扱い
- **#39**: フリガナベースのマッチング
- **#29**: OCRプロキシ Nice-to-have 改善
- **#17**: smoke_real.py pytest 統合
- **#16**, **#14**, **#11**: 各種改善

### P1（open、継続）
- **#6**: PoC E2Eテスト: ログイン→CSV抽出→GCSアップロードの自動パイプライン

## impl-plan 進捗（Session 23 終了時点）

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
| **13D ランチャー「事業所フォルダ結合」統合** | ✅ Session 19 | #108 |
| 14A PyInstaller spec | ✅ merged | #79 |
| 14B アイコン生成 | ✅ merged | #60 |
| 14C ショートカット配布手順 | ✅ merged | #82 |
| **14D ADR-011 Accepted 昇格** | ⏳ **次セッション 1-C 完走と同時実施** | - |
| 15 GitHub Actions + WIF | ⏳ GUI 安定後 | - |

## セッション再開手順（コピペ可）

### Windows 実機 1-C 作業（次セッション最優先）

```powershell
# 1. TeamViewer で Windows 11 PC に接続、PowerShell 起動
# 2. 1-C runbook を Phase 0 から実施
cd $HOME\Projects\wiseman-auto-sys
git checkout main
git pull --ff-only
# git log --oneline -5 で ae96054 (PR #122) が最新を確認

# 3. docs/handoff/1c-exe-redistribution-runbook.md を Phase 0 から順に実施
# 重要: Phase 0-4 は uv sync --extra dev (--extra dev 必須)
# 期待: 559 passed, 68 skipped
```

### 1-C 完走後の次手

```bash
cd /Users/yyyhhh/Projects/wiseman_auto_sys
git checkout main
git pull --ff-only

# 優先2: Issue #117 (tuple 化、type-design follow-up、5+ ファイル想定)
# 優先1-B: B/C PDF 内容抽出によるマッチング（実運用 1 回後）
# 優先3: P2 refactor 系（#45, #27）
# 優先5: CI 改善（#63 Linux Tk skip）
```

## Quality Gate の実効性（Session 2-23 累積）

- **/simplify** 3 並列: 各 PR で Important 3-6 件修正
- **Evaluator 分離**: Session 16 で REQUEST_CHANGES 1 件 / 18 で MEDIUM 2 件 / **19 で HIGH 2 件**（Phase 2 対称化 + a_only 排他分岐）/ **21 で REQUEST_CHANGES 1 件**（save_session 戻り値統一）検出
- **6 Agent + Codex 二段レビュー**:
  - Session 18: PR #104 で Codex plan review が HIGH 2 件（try/finally + PdfMergeError ラップ維持）を計画段階で検出
  - **Session 19**: Codex review が同姓重複時 B/C 誤添付 HIGH 指摘 → fail-safe で構造的防止（医療データ誤配布の致命バグを実機検証前に回避）
  - **Session 21**: Codex のみが HIGH-1 (resume TOCTOU) 検出 + HIGH-2 (page_index) → #49 統合
  - **Session 22**: Codex のみが LOW #1 (`total_pages_a` bool gotcha 非対称) 検出
- **`--diag` 事前診断モード**（Session 19 導入）: 書込なしで「実データ × 実装の整合」を早期検知
- **`except OSError` 分割パターン**（Session 18 確立）: race silent continue + 型別集計 → atomic_io / session / facility_merger で一貫
- **macOS 事前 smoke build**（Session 23 確立）: 実機作業前に PyInstaller hidden import warning とコマンド成立性を検証

## 参照ファイル（次セッション用）

### Session 23 成果物（最新）
- `docs/handoff/1c-exe-redistribution-runbook.md` (PR #122): Phase 0-3 期待 commit / Phase 0-4 `uv sync --extra dev` 必須化 / 期待テスト件数 559 / トラブル早見表更新
- macOS smoke build artifact (ローカルのみ、コミット対象外): `dist/wiseman_hub` 66MB (動作確認済)

### Session 22 成果物
- `src/wiseman_hub/pdf/session.py` (PR #120): `_candidate_from_dict` / `_from_dict` に page_index invariant 検証追加
- `tests/unit/pdf/test_session.py`: `TestPageIndexInvariant` クラス（8 tests）

### Session 21 成果物
- `src/wiseman_hub/pdf/session.py` (PR #116): `Session` / `UserCandidate` を `@dataclass(frozen=True)` 化、`save_session` / `transition_session` 戻り値契約変更
- `docs/handoff/1c-exe-redistribution-runbook.md` (PR #115): 1-C Phase 3-B 既存機能 regression smoke 追加

### Session 19-20 成果物
- `src/wiseman_hub/pdf/facility_merger.py`: merge_facility() 本体、9 フィールド報告 dataclass、Phase 1/2 両対称マッチ
- `src/wiseman_hub/pdf/text_name_extractor.py`: Pattern 1 (ラベル) + Pattern 2 (フリガナ) フォールバック
- `src/wiseman_hub/ui/facility_merger_dialog.py`: Toplevel ダイアログ
- `src/wiseman_hub/ui/launcher.py`: 4 ボタン構成
- `scripts/merge_facility.py`: CLI + `--diag` 診断モード
- `wiseman_hub.spec` (PR #111): facility_merger 関連 3 モジュールを hiddenimports に明示
- `tests/unit/pdf/test_facility_merger.py` (PR #110): `test_multi_user_ordered_merge_verifies_page_content`
- `docs/handoff/folder-merger-mvp-runbook.md` / `folder-merger-mvp-testing.md`

### 履歴
- `docs/handoff/archive/2026-04-history.md`: Session 11-21 詳細
