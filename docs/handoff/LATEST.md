# Handoff: PDF 分割・条件付き再結合機能の実装（Session 3 終了時点）

**更新日**: 2026-04-20
**ブランチ**: main (clean, origin と同期済み)
**次セッションで `/catchup` を実行して再開可能**

## 機能概要

複数利用者がまとまった PDF (A) を1利用者=1ページで分割し、OCR で利用者名抽出、利用者ごとに別 PDF (B, C) を指定順で結合、末尾に共通 PDF (D) を追加して1つの PDF を生成する機能。

**本 Session で追加した要件**: 誤記/OCR 揺れで類似マッチした場合、Tkinter UI で人間が承認してから結合する（自動結合を回避）。

- **入力**: A（複数利用者PDF、固定矩形OCR）、B/C（利用者別PDF、ファイル名に利用者名）、D（共通PDF）
- **出力**: 全利用者分を連結した1つの PDF
- **環境**: Windows デスクトップアプリ（1施設1PC、ADR-002 の PyInstaller パッケージ）
- **規模**: 1〜20名/回

## アーキテクチャ

```
Windows Desktop App
  ↓ HTTPS (X-API-Key)
Cloud Run (asia-northeast1)  ← OCR プロキシ
  ↓ SA (roles/aiplatform.user)
Vertex AI Gemini 2.5 Flash (GA, asia-northeast1)

確認 UI: Tkinter（stdlib、PyInstaller 依存追加なし、ADR-009）
セッション管理: JSON + atomic write（schema_version v1、ADR-010）
```

## 実装計画（全 13 タスク）

| # | タスク | 状態 | PR / Issue |
|---|-------|------|-----------|
| 1 | ADR-008 起草 | ✅ | PR #26 |
| 2 | Cloud Run プロキシ実装 | ✅ | PR #28 |
| 3 | デプロイ手順書 | ✅ | PR #28（`backend/ocr_proxy/deploy.md`） |
| 4 | config.py 拡張 | ✅ | PR #26 |
| 5 | PDF splitter | ✅ | PR #31 |
| 6 | OCR HTTP クライアント | ✅ | PR #32 |
| 7 | PDF merger | ✅ | PR #33 |
| 8A | **ADR-009/010 + matcher + session 基盤** | ✅ | **PR #43** |
| 8B | Pipeline Phase A + CLI 骨格 | ⏳ **次セッション** | Issue #36 |
| 8C | 確認UI (Tkinter) + Phase B + Integration tests | ⏳ | Issue #37 |
| 10 | 実 Cloud Run デプロイ + AC2/AC7 実測 | ⏳ Session 4 予定 | - |
| 11 | README + sample TOML | ⏳ 最後 | - |

## Session 3 で完了した PR

### PR #42 - 既存 lint/type エラー修正 [merged, commit dec86f7]
- `tests/unit/test_process_ex_files.py` 日本語リテラル 3 行に `# noqa: E501`
- `pyproject.toml` mypy の exclude に `^backend/`, `^tests/`, `^scripts/` 追加
- CLAUDE.md の「Type check: mypy src/」方針と整合
- 契機: 後述の pre-push hook 強化で既存エラーが表面化

### PR #43 - タスク 8A [merged, commit 598ba10]
- ADR-009: UI 技術に Tkinter 採用（stdlib、配布サイズ増なし、macOS/Windows 両対応）
- ADR-010: 状態遷移図（Mermaid）+ JSON スキーマ v1 + GC ポリシ + ロック方針
- `src/wiseman_hub/pdf/matcher.py`:
  - `NameMatcher` Protocol（将来の FuriganaMatcher 拡張点）
  - `KanjiMatcher`（Levenshtein 距離ベース 3 層マッチング）
  - NFKC + 空白除去の `normalize_name`（表記揺れ吸収）
  - 類似候補は B/C 合算で距離昇順 top 3、`sorted(iterdir())` で決定論化
- `src/wiseman_hub/pdf/session.py`:
  - `Session` / `UserCandidate` / `CandidateState` dataclass
  - `SessionStatus`（7 値）/ `PairStatus`（7 値）StrEnum
  - JSON 永続化（atomic write、`os.fsync`、schema_version）
  - `SessionCorruptedError` で破損検知（全必須フィールド + kind + confidence + session_id 整合性）
  - `gc_old_sessions`（30 日経過 completed 削除、artifacts 配下 PDF も同時削除、sessions_dir 境界検証）
  - POSIX では `.sessions/` を `0o700` で作成（個人情報保護）
- `.gitignore` に `**/.sessions/` 追加
- テスト 71 件追加 PASS（全体 203 件 PASS）

**Quality Gate 適用順**:
1. `/simplify` 3 並列レビュー（reuse/quality/efficiency）
2. `evaluator` 第三者評価（Acceptance Criteria 検証）
3. `/review-pr` 6 エージェント並列（code-reviewer / comment-analyzer / pr-test-analyzer / silent-failure-hunter / type-design-analyzer / code-simplifier）
4. `/codex review` セカンドオピニオン → High 2件 / Medium 3件 / Low 1件を受領、反映

**Codex 指摘反映（セカンドオピニオンの価値）**:
- High: GC の artifacts 削除漏れ（個人情報残留）→ `_remove_session_artifacts` 追加
- High: `.gitignore` に `.sessions/` 未追加 → 追加
- Medium: session_id 整合性検証不足 → `_from_dict` で検証追加
- Low: `.sessions/` 権限 → POSIX 0o700

これらは 6 エージェント並列レビューでは検出されず、セカンドオピニオンの価値を再確認。

## 副次的成果: pre-push hook の改善（別リポジトリ管理）

本 Session 中、`~/.claude/hooks/pre-push-quality-check.sh` の 2 つの問題を発見し、ローカルで修正適用済み:

1. **プロジェクト venv を無視してシステム Python でチェック**
   → プロジェクト `.venv/bin` を PATH 前置するよう修正
2. **別リポジトリへの push でチェック対象が誤判定**
   → COMMAND 文字列から `cd <dir>` を抽出し、push 対象 repo を特定するよう修正

ローカルファイルは修正済みで即反映されているが、`~/.claude` リポジトリは `yasushi-honda/claude-code-config` 管理で現セッションのトークンには push 権限なし。

**次セッション（yasushi-honda アカウント）での対応必要**:
- feature branch を作成（`feat/pre-push-hook-venv-detection` 推奨）
- 修正内容は `~/.claude/hooks/pre-push-quality-check.sh` に適用済みなのでそのまま commit
- PR 化してマージ

## 積み残し Issues

### Session 4 優先（PR #B / #C 実装時に必須）
- **#36 タスク 8B**: Pipeline Phase A + CLI 骨格（split→OCR→match のオーケストレータ）
- **#37 タスク 8C**: 確認 UI (Tkinter) + Phase B + Integration tests
- **#46 セッションロック実装**（Windows exe 二重起動・UI/GC 競合対策）: PR #B で統合実装
- **#47 transition_session API**（不正な状態遷移検出）: PR #B で統合実装

### タスク 8 関連の延期事項（PR #B or 後続で対応）
- **#38** atomic_io ユーティリティ抽出（merger + session 重複）
- **#39** フリガナベースのマッチング（B/C PDF 生成機能の仕様確定後）
- **#40** B と C で異名マッチの扱い
- **#44** Session/UserCandidate immutable 化（`updated_at` mutation 排除）
- **#45** SourceKind を StrEnum 化

### 別機能の積み残し（優先度低）
- #29 OCR プロキシ Nice-to-have
- #27 config dataclass 型設計強化
- #17 smoke_real.py pytest 統合
- #16 test_new_registration_flow カバレッジ
- #14 PywinautoEngine export_csv 失敗モード区別化
- #11 PywinautoEngine MEDIUM 5 件
- #6 PoC E2E テスト

## Acceptance Criteria 進捗（impl-plan Phase 2.7）

| AC | 内容 | 状態 | 検証箇所 |
|----|------|------|---------|
| AC1 | OCR プロキシ認証（APIキーなしで 401） | ✅ | `backend/ocr_proxy/tests/test_main.py` |
| AC2 | OCR 成功（既知 PDF ページ→利用者名） | 🔶 モックのみ、実 Cloud Run で未測定 | Session 4 タスク10 |
| AC3 | A 分割（5人分→5個の単ページ PDF） | ✅ | `tests/unit/pdf/test_splitter.py` |
| AC4 | ファイル名マッチング（欠損時 WARN） | ✅ | `test_merger.py` |
| AC5 | 順序設定反映（order=["A","C","B"]） | ✅ | `test_merger.py::test_concat_order_respected` |
| AC6 | D 末尾連結 | ✅ | `test_merger.py` |
| AC7 | 20名入力→1分以内 | ⏳ | Session 4 タスク10 |
| AC8 | OCR プロキシダウン時のリトライ3回 | ✅ | `test_ocr_client.py` |
| AC-P1 | run_phase_a(config) が A(3名) を split+OCR+match | ⏳ | PR #B 実装で検証 |
| AC-P2 | マッチング3層（漢字ベース、フリガナは #39） | ✅ | `test_matcher.py` |
| AC-P3 | B/C ファイル無し → no_match status | ✅ | `test_matcher.py::TestKanjiMatcherNoMatch` |
| AC-P4 | Phase A 中断 → interrupted_phase_a、再実行で続行/再開/破棄 | ⏳ | PR #B |
| AC-P5 | 確認 UI で needs_confirmation 解決 → ready_to_merge | ⏳ | PR #C |
| AC-P6 | run_phase_b は ready_to_merge のみ実行可 | ⏳ | PR #C |
| AC-P7 | 20名で Phase A < 60秒、Phase B < 5秒 | ⏳ | Session 4 タスク10 |
| AC-P8 | CLI `--resume` / `--list-sessions` | ⏳ | PR #B |
| AC-P10 | SessionStatus / PairStatus が ADR-010 と一致 | ✅ | `test_session.py::TestSessionStatusTransitions` |
| AC-P11 | schema_version 付き JSON、破損時 SessionCorruptedError | ✅ | `test_session.py::TestLoadErrors` |
| AC-P12 | 日本語氏名の表記揺れ正規化 | ✅ | `test_matcher.py::TestNormalizeName` |

## セッション再開手順

```bash
# 1. 状況再確認
cd /Users/yyyhhh/Projects/wiseman_auto_sys
/catchup
/model   # Opus 4.7 xhigh であること確認

# 2. この handoff を読む
cat docs/handoff/LATEST.md

# 3. 次タスク着手（タスク 8B: Pipeline + CLI）
gh issue view 36   # タスク8B の詳細
/impl-plan         # 必須（OCR confidence 低時扱い、重複 user_name 扱い等の設計判断あり）
# または /tdd で直接実装
```

## 主要ファイル参照

- ADR-008: `docs/adr/008-ocr-backend.md`
- **ADR-009**: `docs/adr/009-ui-technology.md`（新規、Session 3）
- **ADR-010**: `docs/adr/010-human-confirmation-state.md`（新規、Session 3）
- Config 定義: `src/wiseman_hub/config.py`
- PDF モジュール:
  - `src/wiseman_hub/pdf/splitter.py`（タスク 5）
  - `src/wiseman_hub/pdf/ocr_client.py`（タスク 6）
  - `src/wiseman_hub/pdf/merger.py`（タスク 7）
  - **`src/wiseman_hub/pdf/matcher.py`**（タスク 8A、新規）
  - **`src/wiseman_hub/pdf/session.py`**（タスク 8A、新規）
- テスト: `tests/unit/pdf/test_{splitter,ocr_client,merger,matcher,session}.py`（136 件）
- OCR プロキシ: `backend/ocr_proxy/app/`
- デプロイ手順: `backend/ocr_proxy/deploy.md`
- sample TOML: `config/default.toml:42-75`

## Session 3 の学び（将来の参考）

### Quality Gate のエスカレーション価値
- `/simplify` 3 並列 → 表層の reuse/quality/efficiency
- `evaluator` → Acceptance Criteria ベースの第三者評価
- `/review-pr` 6 エージェント並列 → 多角的なコード品質
- `/codex review` → 前 4 者で見逃した運用/セキュリティ観点（個人情報残留、ファイル権限、境界検証）

**6 エージェント並列でも人間/AI のレビュアー組み合わせで層が違う**。セカンドオピニオンはコストに見合う価値があった（High 指摘 2 件含む）。

### pre-push hook の隠れた問題
- プロジェクトは `requires-python = ">=3.11"` 明示しつつ、既存コードは tomllib を try/except で fallback している「暗黙規約」
- 新規コード（StrEnum / datetime.UTC 直接 import）で規約違反が顕在化
- 根本対処は hook が venv を尊重すること（A 案「3.9 互換コード」は技術的負債）
- 判断基準: 「根本原因を直す > 個別回避」「グローバル改修の波及効果が正」

### セッションの階層設計（PR 分割）
- 11 タスクから 13 タスクに展開（タスク 8 を 8A/8B/8C に細分化）
- 1 セッションで 1 PR が適切な粒度（大規模すぎると品質ゲートが重い、小さすぎると review コスト対効果が悪い）
- 本 Session: タスク 8A（ADR + 基盤モジュール）→ 1 PR、レビュー 4 層で約 1 日

## Status Transitions 未実装の警告（次セッションで必ず実装）

ADR-010 で定義した状態遷移は enum と `all_candidates_resolved` のみ実装済み。**以下は Issue #47 で PR #B 時に追加必須**:

```
needs_review → ready_to_merge: all_candidates_resolved == True 必須
running_phase_a → needs_review or ready_to_merge: 完了条件ベース
running_phase_b → completed: output_path が存在することを検証
```

`session.status = ...` の直接代入は `transition_session()` API 経由に置き換える。
