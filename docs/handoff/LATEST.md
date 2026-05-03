# Handoff: Session 40 完了 - PR #172 居宅マッピング GCP 自動化 実機 1 回成功 + 誤削除事故からの完全復旧

**更新日**: 2026-05-03（Session 40 / Mac + Windows TeamViewer 経由）
**main HEAD**: `40b940d` docs(handoff): Session 39 中断 (#175)
**作業ブランチ**: `feature/checklist-bc-mvp` HEAD `1a9ca31`（push 済、PR #172 OPEN）

---

## 🎯 Session 40 の最大成果

### Windows 実機 1 回成功達成（Session 39 で 4 セッション越し未完了だった目標）

1. SA キー実機配置（TeamViewer 転送、`$HOME\wiseman-hub\config\sa-key.json`）
2. PyInstaller 再ビルド（warning 検査クリア、hidden import 漏れなし）
3. アプリ「**GCP から対照表を取得**」ボタン → **39 件取得成功** + Text widget 反映
4. 設定保存 → `ChecklistConfig.facility_routing` 反映
5. B ダイアログで対照表機能（53 行解析、対照表効きで「居宅マッピング未登録」は UNMATCHED 想定の 1 件のみ）
6. CLI ドライランから 1 件実コピー成功（井上 聰美.pdf、97805 bytes）

→ Session 39 の 3 案 (A/B/C) のうちユーザーが decision-maker として選んだ **A 案 (GCP 連動)** を実装完了。

### 重大事故と完全復旧

- 誤削除事故: PowerShell の `|` 改行繋ぎでコピペ時に Where-Object フィルタが切れて、`$targets` に 6 件全部マッチ → `$targets | Remove-Item` で `\\Tera-station\share\03.FAX(事業所)\姫路医療生活協同組合 あぼし(メール)\運動機能向上計画書\` の 6 PDF (4.pdf / さえき.pdf / 井上 聰美.pdf / 石原.pdf / 立花.pdf / 竹國.pdf) を誤削除
- 復旧経路: Windows VSS は無効だったが、**Buffalo NAS Tera-station の `\\Tera-station\share\trashbox\`** に元のパス構造を保持して全 6 件発見
- 業務ファイル 5 件 (4.pdf / さえき.pdf / 石原.pdf / 立花.pdf / 竹國.pdf) を `Move-Item` で完全復旧
- 井上 聰美.pdf（テストコピー痕跡）は trashbox に隔離 (業務影響なし)

教訓は global memory に永続化済（後述）。

---

## 次セッションの最優先候補

### 1. 残作業（A 案延長線、優先度高）

| # | 内容 | 推定工数 |
|---|------|---------|
| A | 残り 4 件の B 配置実コピー（廣岡 / 西阪 / 山田 / 冨岡）。CLI `--execute-one 1..4` 順次 or GUI「実行」ボタンで一括 | 5 分 |
| B | 対照表精査: MEDIUM 3 / LOW 5 / UNMATCHED 13 件 (`docs/handoff/facility-mapping-draft.md`)。確定後 `scripts/build_routing_json.py` 改修 + GCS 上書き | 30 分〜 |
| C | C 配置（経過報告書）の動作確認。B と同等のフロー | 20 分 |
| D | PR #172 マージ判断（CI 通過確認 + 残作業優先度） | - |

### 2. GUI 改善案（中期、別 PR）

- 選択行のみ実コピー（現状は GUI「実行」ボタンが PENDING 全件一括のみ）
- 「以前のバージョン」/「trashbox」復旧 UI（誤削除リカバリ）
- 設定ダイアログの「対照表」を Treeview で編集可能に（TOML テキスト編集の代替）

### 3. 既存 follow-up Issue（Session 38 から継続、未着手）

| # | 由来 | 概要 |
|---|-----|------|
| #170 | type-design-analyzer | `_quarantine_pre_existing_target` の戻り値を `Quarantine` dataclass で tagged union 化 |
| #164 | silent-failure-hunter | ExExtractorViewModel.source_dir setter 検証で TOCTOU / 不変条件 |
| #162 | silent-failure-hunter | Launcher 同期 callback フリーズ + 例外保護 |
| #161 | silent-failure-hunter | GUI 再統合時の messagebox マッピング再構築要件 |
| #158 | codex review | 起動後 callback の load_config 失敗 actionable 化 |
| #152 | (#27 PR-B 系) | UserNameBBox NaN/inf + OcrBackendConfig 空白 URL 検証 |
| #134 | OCR | Gemini 2.5 Flash retire (2026-10-16) 対応 |

---

## Session 40 の成果

### PR #172 へ 5 commit 追加 push（feature/checklist-bc-mvp、HEAD `1a9ca31`）

| commit | 内容 | 規模 |
|--------|------|------|
| `f8a9130` | feat(cloud): 対照表 GCS push/pull + Codex review 指摘 8 件反映（mapping_sync.py 新規 + settings_dialog.py + tests + spec） | 4 ファイル / +602 |
| `3eeea04` | feat(scripts): GCP アクセス smoke + 対照表 draft 生成（check_gcp_access.py + draft_facility_mapping.py） | 2 ファイル / +350 |
| `a44b066` | docs(handoff): 対照表 draft + GCS sync 実機検証 runbook | 2 ファイル / +414 |
| `d39ba80` | fix(scripts): GCP smoke の buckets.get 不要化 + delete 権限不足 warning（実機運用検証で発覚） | 2 ファイル / +94 |
| `1a9ca31` | feat(scripts): B 配置のドライラン + 1 件実行 CLI（実機検証用、GUI 全件一括の代替） | 1 ファイル / +155 |

CI: `Build Windows Smoke` ✅ success（直近 push 分）、test-unit (3.11/3.12) ✅、test-integration ⏳

### Codex review (medium) 指摘 8 件全反映

- HIGH-1: SA キー JSON 破損時の `ValueError`/`GoogleAuthError` を `MappingConfigError` に変換
- HIGH-2: SA 自己権限確認 smoke (`scripts/check_gcp_access.py`)
- MEDIUM-1: GCS upload/download に `timeout=30s`
- MEDIUM-2: `_routing_to_toml` で key/value 両側 `_escape_toml`
- MEDIUM-3: pull 前の parse 失敗時の確認 dialog
- MEDIUM-4: schema version 検証
- LOW-1: `MappingConfigError` で sa_path.name のみ表示
- LOW-2: runbook の SA キー先頭表示を `client_email` のみに

検証: 896 passed / 16 件追加、ruff/mypy clean。

### GCP IAM 修正（個人アカウント経由、bucket レベル最小権限）

```bash
gcloud storage buckets add-iam-policy-binding gs://wiseman-hub-prod-datalake \
  --member=serviceAccount:wiseman-hub-sa@wiseman-hub-prod.iam.gserviceaccount.com \
  --role=roles/storage.objectUser \
  --project=wiseman-hub-prod
```

効果: 取得 + 送信（新規 + 上書き）両方動作可能。次回以降 IAM 修正不要。

### GCS 初回データ投入

- `gs://wiseman-hub-prod-datalake/mappings/facility-routing-latest.json`（HIGH 39 件、version=1）
- `scripts/build_routing_json.py` で生成、個人アカウント `gcloud storage cp` で put

### 環境状態（次セッション開始時の前提）

| 項目 | 値 |
|------|-----|
| macOS gcloud | `wiseman-auto-sys` config = `sasaki.system0801@gmail.com` |
| Windows 実機 SA キー | `$HOME\wiseman-hub\config\sa-key.json` 配置済 |
| Windows 実機 exe | 79 MB / 2026/05/03 7:55:32 配布 (HEAD `1a9ca31` ベース) |
| GCS mappings/ | `facility-routing-latest.json` (HIGH 39 件) |
| 業務 share | 元の 5 件 (4.pdf 等) + Thumbs.db に復旧済 |
| trashbox | 井上 聰美.pdf がテスト痕跡として残置 |

---

## Session 40 で派生した教訓 / 永続化済 memory + ハーネス強化

### 教訓 memory（グローバル）

| 教訓 | 永続化先 |
|------|---------|
| PowerShell `\|` 改行繋ぎはコピペで切れて Where-Object 等が消える → 1 行詰めか件数アサーション必須 | `~/.claude/memory/feedback_powershell_pipe_continuation_risk.md` |
| 削除コマンド前の件数アサーション必須（`-WhatIf` 目視だけは見落とす） | `~/.claude/memory/feedback_destructive_command_safety.md` |
| Buffalo NAS の trashbox は SMB Remove-Item でも元パス保持で残る（VSS 無効でも別機構） | `~/.claude/memory/feedback_nas_trashbox_recovery.md` |
| MEMORY.md にも索引追加済 | `~/.claude/memory/MEMORY.md` |

### ハーネス強化（3 層構造、AI 自律性を阻害しない最小実装）

| 層 | 場所 | 役割 |
|----|------|------|
| L1: グローバル必読 | `~/.claude/CLAUDE.md` CRITICAL に 1 行ポインタ追加 | 全プロジェクトで毎セッション読まれる、destructive 操作の総則シグナル |
| L2: プロジェクト固有運用 | `wiseman_auto_sys/CLAUDE.md` に「Tera-station NAS の destructive 操作プロトコル」セクション + trashbox 場所表 | catchup 必読領域、4 項プロトコル + 復旧経路 |
| L3: 詳細参照 | 上記 memory 3 件 | AI が状況に応じて自律的に深掘り |

設計方針: hooks / rules 細分化は **採用せず**（AI 自律性阻害大、ROI 低）。memory 詳細 + CLAUDE.md ポインタで AI が状況に応じて自律判断できる構造を選択。

---

## Issue Net 変化

```
- Close 数: 0 件
- 起票数: 0 件
- Net: 0 件
```

triage 基準遵守: review 系・運用系の指摘は本 PR 内で消化、または PR コメント / TODO で対応。新規 Issue 化なし（rating 7 以上 / confidence 80 以上の指摘なし）。

誤削除事故は再発防止策を memory に永続化済のため、Issue 化対象外（運用ルールの整備で対応）。

---

## 次セッション開始時の意思決定

### 優先順序

1. **残り 4 件の B 配置実コピー** — `--execute-one 1..4` で確実に 1 件ずつ確認推奨（A 案最小スコープ完了）
2. **対照表精査 21 件** — MEDIUM 3 / LOW 5 / UNMATCHED 13 件、本田様の業務記憶必要
3. **C 配置動作確認** — B と同等のフロー
4. **PR #172 マージ判断** — CI 通過 + 残作業の優先度判断

### catchup 時の確認項目

#### Mac 側（macOS 開発機）

```bash
cd /Users/yyyhhh/Projects/wiseman_auto_sys
git checkout main && git pull --ff-only
git log --oneline -3
gh issue list --state open --limit 10
gh pr view 172 --json state,statusCheckRollup --jq '.state,.statusCheckRollup[].conclusion'
```

#### Windows 機側（TeamViewer 経由）

実機の exe は HEAD `1a9ca31` ベースで配布済なので、コード変更がなければ再ビルド不要。残り 4 件の実コピーは:

```powershell
cd $HOME\Projects\wiseman-auto-sys
git fetch origin
git checkout feature/checklist-bc-mvp
git pull --ff-only

$env:WISEMAN_HUB_CONFIG = "$HOME\wiseman-hub\config\default.toml"

# CLI で 1 件ずつ実コピー（confirm プロンプト付き）
uv run python scripts/checklist_b_dryrun.py 26年3月 --execute-one 1  # 廣岡 ときえ
uv run python scripts/checklist_b_dryrun.py 26年3月 --execute-one 2  # 西阪 修一
uv run python scripts/checklist_b_dryrun.py 26年3月 --execute-one 3  # 山田 タツ子
uv run python scripts/checklist_b_dryrun.py 26年3月 --execute-one 4  # 冨岡 美恵子
```

または GUI「実行」ボタンで残り 4 件一括（井上 聰美.pdf は GUI 起動時にカルテから plan 再計算されるが、配置済 / 不在に応じてスキップ判定される）。

---

## 参照ファイル

### Session 40 成果物

- `src/wiseman_hub/cloud/mapping_sync.py`: 新規、GCS 双方向同期 + バリデーション + version 検証 + auth 例外 → MappingConfigError 変換
- `src/wiseman_hub/ui/checklist_settings_dialog.py`: 「対照表 → GCP へ送信」「GCP から対照表を取得」ボタン 2 個追加 + 閉ループ検証
- `tests/unit/cloud/test_mapping_sync.py`: 新規 16 件
- `wiseman_hub.spec`: hiddenimports に `mapping_sync` + `google.api_core.exceptions` 追加
- `scripts/check_gcp_access.py`: SA 自己権限 smoke
- `scripts/build_routing_json.py`: HIGH 39 件 JSON 生成（draft_facility_mapping のロジック再利用）
- `scripts/draft_facility_mapping.py`: 60 居宅 × 40 FAX フォルダの rule-based マッチング → draft md
- `scripts/checklist_b_dryrun.py`: B 配置のドライラン + 1 件実行 CLI（GUI 全件一括の代替）
- `docs/handoff/facility-mapping-sync-runbook.md`: Phase 0-4 + 失敗パターン早見表
- `docs/handoff/facility-mapping-draft.md`: 対照表ドラフト出力 (HIGH 39 / MEDIUM 3 / LOW 5 / UNMATCHED 13)

### グローバル memory（Session 40 関連）

- `~/.claude/memory/feedback_powershell_pipe_continuation_risk.md`
- `~/.claude/memory/feedback_destructive_command_safety.md`
- `~/.claude/memory/feedback_nas_trashbox_recovery.md`
- `~/.claude/memory/MEMORY.md` 索引更新済

### 履歴

- `docs/handoff/archive/2026-04-history.md`: Session 11-34 詳細
- `docs/handoff/archive/session-38-pr-169.md`: Session 38
- `docs/handoff/archive/session-39-checklist-bc-mvp-blocker.md`: Session 39（中断、A 案決定）
- Session 40: 本 LATEST.md
