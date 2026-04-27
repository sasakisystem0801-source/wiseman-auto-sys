# Handoff: ex_extractor 5 PR シリーズ着手 + PR1/PR2 完了（Session 27 終了時点）

**更新日**: 2026-04-27（Session 27 / PR #130 + #131 マージ後）
**ブランチ**: main（PR #130, #131 squash merge 済）
**main HEAD**: `eed2d47` feat(pdf): facility_resolver 実装（誤配布防止のための安全マッチング、PR2/5）(#131)

## セッション 27 の成果（ex_extractor 5 PR シリーズ着手 + PR1/PR2 完了）

### ユーザー要求

本田様要望（2026-04-27）:

> 結合する A の PDF ファイルが存在するフォルダ（サブフォルダ：BC のあるサブフォルダと
> 同じところ）が有るルートフォルダを設定して、ex_ファイルPDF変換移動の一連機能を
> ワンボタン化したい

ADR-013（PR #126）で実装済の「事業所フォルダ一括結合」の **前段階** として、
Wiseman からダウンロードされる `.ex_` ファイル（WinSFX32 LZH 自己解凍 EXE）を
PDF 抽出 + 事業所フォルダへ振り分けする機能をデスクトップアプリに統合。
既存スクリプト `scripts/process_ex_files.py`（263 行）を移植 + 拡張。

### 5 PR 分割計画（Codex セカンドオピニオン経由で確定）

| # | スコープ | 状態 |
|---|---------|------|
| **PR1** | 設定スキーマ拡張（`ex_source_dir` + `facility_aliases`） | ✅ Merged (#130) |
| **PR2** | `pdf/facility_resolver` 純粋ロジック（alias 優先 + 安全マッチング） | ✅ Merged (#131) |
| PR3 | `pdf/ex_extractor` core 移植 + SFX adapter 化 + macOS fake runner + scripts ラッパー | ⬜ 次セッション |
| PR4 | UI 統合（dialog + launcher 5ボタン化 + 手動振り分け UI） | ⬜ |
| PR5 | Windows 実機検証 + 修正 + settings.py タブ化（独立評価） | ⬜ |

### マージ済 ✅

- **PR #130** (squash merge `37f394d`): feat(config): ex_source_dir + facility_aliases 追加
  - 3 files (`config.py` / `default.toml` / `test_config.py`)、+650 / -31 LOC
  - テスト 21 件追加（既存 25 → 37 → さらにレビュー対応で +9 で 46）
  - **入力検証**: `_coerce_facility_aliases` + `_validate_facility_aliases` 6 条件
- **PR #131** (squash merge `eed2d47`): feat(pdf): facility_resolver 実装
  - 3 files 新規（`facility_resolver.py` / `test_facility_resolver.py` / `ADR-014`）、+1,369 LOC
  - テスト 63 件、全体 720 passed
  - **マッチング戦略**: alias 優先 → 完全一致 → 部分一致(語境界 + 一意/十分差)

### マッチング戦略（PR2 で確定、ADR-014 に明記）

| 順位 | 判定 | reason | 説明 |
|------|------|--------|------|
| 1 | alias 一致 | `ALIAS_MATCH` | alias が **語境界付き** で含まれ、canonical が **実在** |
| 1' | alias 複数 canonical hit | `AMBIGUOUS_ALIAS` | dict 順先勝ち回避 |
| 2 | 正規化完全一致 | `EXACT_MATCH` | NFKC + 空白保持後に一意 |
| 2' | 同 複数 hit | `AMBIGUOUS_EXACT` | 正規化重複検出 |
| 3 | 部分一致 (一意) | `PARTIAL_UNIQUE` | 語境界付き 1 件 |
| 4 | 部分一致 (最長優位) | `PARTIAL_DOMINANT` | 最長 - 次長 ≥ 2 文字 |
| 5 | AMBIGUOUS | `AMBIGUOUS_PARTIAL` | 候補複数 + 差不十分 → 手動 |
| 6 | UNMATCHED | `NO_CANDIDATE` / `EMPTY_FILENAME` / `EMPTY_FACILITY_LIST` | 細分 reason |

### 多重 Quality Gate の効果（HIGH 11 件発見・対応）

#### PR #130（4 agent + Codex MCP）
- code-reviewer / pr-test-analyzer / comment-analyzer / type-design-analyzer 4 並列
- **3 agents が独立に同一 HIGH を指摘**: alias value 文字列の silent 文字分解
- HIGH 3 件: 文字分解 / global 一意性違反 / 配列要素非文字列 → `_validate_facility_aliases` 6 条件で fail-fast

#### PR #131（5 agent + Codex MCP）
- 上記 4 + silent-failure-hunter
- **HIGH 8 件**: alias 複数 canonical hit / 正規化完全一致複数 / 空白扱い設計矛盾 / ResolveResult 不変条件未強制 / docstring 戦略一覧不備 / ADR 実名残置 / テスト docstring 数値ミス / テスト名と意図不一致
- すべて対応: `__post_init__` 不変条件強制、新 reason `AMBIGUOUS_ALIAS`/`AMBIGUOUS_EXACT`、空白除去廃止 + 境界文字化、factory メソッド、`is_auto_distributable` プロパティ、`find_orphan_alias_canonicals` ヘルパー

### 重要な設計判断（次セッション以降に影響）

1. **誤配布回避を最重要 KPI**: 介護現場での false positive は業務事故 → AMBIGUOUS への手動振り分けを積極採用
2. **空白の扱い**: NFKC 正規化はするが空白除去せず、半角・全角・タブ・改行を境界文字として活用（H-C 対応）
3. **入力契約**: filename / facility_names のみ防御、aliases は config 層検証済み前提（resolver は AttributeError 等を伝播）
4. **PII 防御**: facility_resolver はログ出力ゼロ、テストデータも全仮名化（「サービスA」「ユーザー001」）、ADR 内も仮名統一
5. **PR4 統合用フック**: `is_auto_distributable` / `needs_manual_*` プロパティで UI 分岐の単一判定ポイント、`find_orphan_alias_canonicals` で設定不整合警告

### ADR-014 (Proposed)

`docs/adr/014-ex-extractor-integration.md` 作成。PR3-5 完了 + Windows 実機検証後に Accepted 昇格予定。マッチング戦略、語境界要件、PII 防御方針、Windows 専用機能の検証戦略を明記。

### Issue Net 変化（本セッション）

- **Close**: 0 件
- **起票**: 0 件
- **Net: 0 件**

進捗評価: Net 0 だが **「進捗ゼロ」ではない**。理由:
- ユーザー明示指示「ex_ ファイル PDF 変換 + 振り分けワンボタン化」の実装着手（CLAUDE.md GitHub Issues #5 該当）
- 5 PR シリーズ計画策定（Codex セカンドオピニオンで承認）
- PR1 / PR2 マージ済（コア事故防止コア完成、+1,997 LOC、テスト +100 件、既存リグレッション 0）
- ADR-014 Proposed 作成
- 既存 P2 Issue 13 件は本機能と無関係、保留妥当

### 次セッション送り（PR3 着手前の確認事項）

**PR3 スコープ**: `scripts/process_ex_files.py` を `src/wiseman_hub/pdf/ex_extractor.py` に移植
- SFX 実行を adapter インターフェース化（Windows 実装 + macOS fake adapter）
- 構造化結果（成功/失敗/手動振り分け待ち）の戻り値型
- `find_orphan_alias_canonicals` 警告連携の準備
- `scripts/process_ex_files.py` を薄ラッパーに置換（CLI 互換維持）
- macOS 単体テストで fake runner による全フロー検証

**PR3 で参照すべき PR2 公開 API**:
- `resolve_facility(filename, facility_names, aliases) -> ResolveResult`
- `ResolveResult.is_auto_distributable` / `.needs_manual_selection` / `.needs_manual_input`
- `ResolveResult.confirmed/.ambiguous/.unmatched` factory
- `find_orphan_alias_canonicals(facility_names, aliases) -> list[str]`
- `normalize_name(s: str) -> str`

**Session 26 観察事項（要確認）**:
- 元 `a_missing` 状態事業所（`きなり(メール)※持参`）の初回判定タイミングと A.pdf 生成タイミングの競合可能性 → PR3-4 統合段階で再観察

---

## セッション 26 の成果（PR #126 Windows 実機検証完走 + ADR 昇格）

**Session 26 終了時点 main HEAD**: `1b3cfcf` docs(adr): ADR-013 + ADR-011 Accepted 昇格

### 主成果
- **PR #126 全 13 AC の Windows 実機検証完走**（本田様 Windows 11 + `\\Tera-station\share\03.FAX(事業所)\` 40 事業所）
- **ADR-013** Proposed → Accepted 昇格（`facility_root_dir` + 一括結合 UI）
- **ADR-011** Proposed → Accepted 昇格（タスク 14D 完走、4 ボタン構成実機稼働）
- **AC-12 / AC-13（最重要バグ予防）** が本番経路で機能することを実機確認

### 実機検証で確認できた最重要ポイント
- **AC-12 (再実行ループ防止)**: 出力 `{事業所名}.pdf` を A.pdf 候補から除外する核心ロジック実機確認
- **AC-13 (Acrobat ロック中の本番経路、致命バグ予防)**: review-pr で発見した致命バグ（`PdfMergeError(__cause__=PermissionError)` ラップ経路）の修正が本番経路で機能、`failed_locked` ステータス + 「結合 PDF を閉じてから再実行」文言を実機で確認

詳細: `docs/handoff/session26-pr126-windows-runbook.md`、ADR-013 / ADR-011

---

## セッション 25 の成果（PR #126 マージ）

**Session 25 終了時点 main HEAD**: `0f9abbb` feat(ui): 事業所ルートフォルダ管理 + 一括/選択 PDF 結合（デスクトップアプリ統合）

10 commits → squash merge `0f9abbb`、合計 +3239 / -151 行、新規テスト 97 件。

### 機能概要
**新ダイアログ `FacilityRootManagerDialog`** が「事業所フォルダ一括結合」ボタンから起動:
1. ルートフォルダ選択 → TOML 永続化（`pdf_merge.facility_root_dir`）
2. 配下事業所を自動検出（`運動機能向上計画書/` AND `経過報告書/` 両方ある）
3. チェックボックス + ステータス + 「フォルダを開く」「結合PDFを開く」
4. 「全選択 / 全解除」「停止」ボタン、サマリ表示
5. PermissionError → 「結合 PDF を閉じてから再実行」文言

詳細: ADR-013、`docs/handoff/archive/2026-04-history.md`

### 多重 Quality Gate の効果（Session 25）
- Codex plan モードで AC-12 / AC-13 追加（再実行ループ防止 + lock 文言変換）
- Generator-Evaluator 分離プロトコル → HIGH (X ボタン未バインド) 等を発見
- 6 並列レビュー → AC-13 前提崩壊リスク（致命）など発見・修正

---

## セッション 24 の成果（PR #124 マージ）

**Session 24 終了時点 main HEAD**: `4216828`（PR #124）

`merge_facility` 新仕様（A+B+C 全揃いのみ ABCABC 連結、1 事業所 1 ファイル）+ ADR-012。
詳細: `docs/handoff/archive/2026-04-history.md`

---

## 過去セッション履歴

- Session 11-21 詳細: `docs/handoff/archive/2026-04-history.md`
- Session 22-23: PR #115/#120/#122/#123（page_index invariant + 1-C ランブック同期）
- Session 24-26: 上記サマリ参照、詳細は git log と ADR-011/012/013 参照

---

## 積み残し Issue / 技術負債

### Session 27 で CLOSED
- なし（PR #130 + #131 は新機能、既存 Issue とは無関係）

### P2（open、優先順、本機能と無関係）
- **#117**: Session.candidates / UserCandidate.similar_candidates を tuple 化
- **#80**: Windows 実機 smoke build で Phase B / OCR import 検証
- **#63**: Linux CI Tk wiring skip
- **#45**: SourceKind StrEnum 統一
- **#27**: config dataclass 型設計強化
- **#40**, **#39**, **#29**, **#17**, **#16**, **#14**, **#11**

### P1（open、継続）
- **#6**: PoC E2E テスト

### 新規起票候補（次セッション以降で判断）
- なし（5 PR 計画は ADR-014 + 本ハンドオフで管理、Issue 化は Net KPI に反するため見送り）

---

## impl-plan 進捗（Session 27 終了時点）

| タスク | 状態 | PR |
|--------|------|-----|
| 12C 初回起動ウィザード | ⏳ 優先度低 | - |
| 13D ランチャー「事業所フォルダ結合」統合 | ✅ Session 19 / 25 / 26 | #108, #126 |
| 14A-D PyInstaller / アイコン / 配布 / ADR-011 | ✅ Session 26 | #79/#60/#82, #128 |
| 事業所単位 1 ファイル仕様 | ✅ Session 24 | #124 |
| 事業所ルートフォルダ管理 + 一括/選択結合 | ✅ Session 25 / 26 | #126, #128 |
| **ex_extractor PR1 設定スキーマ** | ✅ **Session 27** | #130 |
| **ex_extractor PR2 facility_resolver** | ✅ **Session 27** | #131 |
| **ex_extractor PR3 core 移植 + SFX adapter** | ⏳ **次セッション** | - |
| **ex_extractor PR4 UI 統合** | ⏳ | - |
| **ex_extractor PR5 Windows 実機 + settings タブ化** | ⏳ | - |
| 15 GitHub Actions + WIF | ⏳ GUI 安定後 | - |

---

## セッション再開手順（コピペ可）

### 次セッション開始時（Session 28）

```bash
cd /Users/yyyhhh/Projects/wiseman_auto_sys
git checkout main
git pull --ff-only
# main HEAD が eed2d47（PR #131）であることを確認
gh issue list --state open
```

### 次のアクション（PR3 着手）

PR3: `ex_extractor` core 移植 + SFX adapter 化（中規模、400-500 LOC 想定）

1. `scripts/process_ex_files.py` の現状ロジック把握（既読、263 行）
2. `src/wiseman_hub/pdf/ex_extractor.py` 新規作成
   - SFX 実行を adapter Protocol 化（Windows 実装 + macOS fake adapter）
   - 構造化結果型（成功/失敗/手動振り分け待ち）
   - PR2 公開 API（`resolve_facility` / `find_orphan_alias_canonicals`）と統合
3. `tests/unit/pdf/test_ex_extractor.py` で fake runner ベースの全フロー検証
4. `scripts/process_ex_files.py` を薄ラッパーに置換（CLI 互換維持）
5. ADR-014 更新（変更履歴）
6. Quality Gate（pytest + ruff + flake8 + mypy + 5 並列レビュー + Codex）

---

## 参照ファイル

### Session 27 成果物（最新）
- `src/wiseman_hub/config.py`: `PdfMergeConfig.ex_source_dir` + `facility_aliases` + `_validate_facility_aliases`
- `src/wiseman_hub/pdf/facility_resolver.py`: 純粋ロジック（240 行、`resolve_facility` + `ResolveResult` + `find_orphan_alias_canonicals`）
- `tests/unit/pdf/test_facility_resolver.py`: 63 テスト（仮名化済）
- `docs/adr/014-ex-extractor-integration.md`: 本機能の設計 ADR（Proposed）
- `config/default.toml`: ex_source_dir / facility_aliases コメント例

### Session 26 成果物
- `docs/handoff/session26-pr126-windows-runbook.md`: 30-45 分検証フロー
- ADR-011 / ADR-013 Accepted

### Session 25 成果物
- `src/wiseman_hub/pdf/facility_scanner.py`, `facility_bulk_runner.py`, `ui/facility_root_dialog.py`, `utils/os_open.py`

### Session 24 成果物
- `src/wiseman_hub/pdf/facility_merger.py`, ADR-012

### 履歴
- `docs/handoff/archive/2026-04-history.md`: Session 11-21 詳細
