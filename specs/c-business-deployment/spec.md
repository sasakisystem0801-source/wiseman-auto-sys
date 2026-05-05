# C 機能業務化 Spec

**最終更新**: 2026-05-05（Session 43）
**状態**: 業務化フェーズ Phase 1+2 完了（PR #172, #179, #181-#186）→ **Phase 3 cache populate 着手前**
**主担当**: 業務責任者（本田様 PC、Windows 実機）

---

## 業務目的

5 担当者（PT 宮下 / PT 小島 / PT 平瀬 / PT 木塚 / OT 小林）が毎月作成する **経過報告書 (xlsx)** から、**利用者ごとの該当シート 1 ページ目**を **PDF 化** し、利用者の居宅事業所に対応する **FAX 事業所フォルダ** に配置する作業を自動化する。

手作業の場合の規模感:
- 月次 60 件前後（5 担当者 × 利用者複数名）
- 命名規則がバラバラな NAS 上の xlsx を担当者ごとに探し、Excel で開いて利用者シートを特定し、1 ページ目を PDF 化、対応する FAX フォルダにドロップする
- **介護記録誤配置リスク**: 利用者・事業所間違いはコンプライアンス事故。誤配置 0 が必須

---

## 業務全体像（マッチングフロー）

```
[Google Sheets「対象シート」]
  各行: 氏名 / 担当者 / 居宅 / モニタリング ...
        ↓ download_xlsx + parse_sheet (cloud/sheets.py)
[ローカル ChecklistRow]
        ↓ plan_c_placement (pdf/checklist_c.py)
  ├ 居宅 → FAX フォルダ resolve
  │     mappings/facility-routing-latest.json （B 処理で確定済）
  ├ 担当者 → ReportStaffEntry resolve
  │     config/default.toml [checklist.report_staff."<staff>"]
  └ resolve_xlsx
       ├ cache hit (xlsx_path_cache) → PENDING（自動確定）
       ├ suggest_patterns ヒット → NEEDS_REVIEW（人間補正必須）
       └ 候補ゼロ → folder_tree fallback → NEEDS_REVIEW
        ↓ 人間レビュー UI（XlsxPickerDialog）+ 「記憶する」
[xlsx_path_cache 永続化（ローカル TOML）]
        ↓ PlacementConfirmDialog（全件 Treeview 目視確認）
[execute_c_placement]
  Excel COM で 1 ページ目のみ PDF 化（ExportAsFixedFormat From=1, To=1）
        ↓
[FAX 事業所フォルダに配置]
  \\Tera-station\share\03.FAX(事業所)\<事業所名>\<利用者名>.pdf
        ↓
[監査ログ JSON Lines]
  $HOME\wiseman-hub\logs\audit\c_placement_<YYYY-MM-DD>.jsonl
```

---

## 課題: 5 担当者の命名カオス

実機 NAS (`\\Tera-station\share\`) 上の経過報告書 xlsx の命名規則が担当者間で大きく異なり、template 展開（`{era}`/`{month}`）では吸収できない。

| 担当者 | フォルダ命名 | ファイル命名 |
|-------|------------|------------|
| OT 小林 | `経過報告書\R{era}\` | 未確認（cache populate で確定） |
| PT 宮下 | `リハ経過報告書\令和{era}年\` | `リハ経過報告書（宮下）{month}月{空白N個}.xlsx`（R7=空白1個、R8=空白4個） |
| PT 小島 | `リハ経過報告書(新)\` / `リハ経過報告書(旧)\令和{era}年度\`（**新旧 2 系統**） | `経過報告書 令和{era}年{month}月(最新).xlsx` 等、**同月複数候補** |
| PT 平瀬 | `リハ経過報告書\令和{era}年\` | `新経過報告書 {month}月{空白}.xlsx`（**担当者名なし**） |
| PT 木塚 | `経過報告書\令和{era}年度 経過報告書\`（年フォルダ内スペース揺れ） | `経過報告書 木塚R{era}.{month}月 .xlsx`（**同フォルダに別人「東浦」混在**） |

業務側の確認事項（2026-05-04）:
- 「規則は今後変更しない（収束済）」
- 「現状を吸収できれば OK（完璧な汎用性は不要）」
- 「担当者は当面 5 名固定」

---

## 既存決定事項（不変）

### 採用設計: ADR-015 - cache + サジェスト + 人間レビュー UI

ADR-015 §Decision で確定した 3 層構造:

1. **xlsx_path_cache（dict[str, str], キー `"{staff}:{year}:{month}"`）**
   - ユーザーがレビュー UI で確定した xlsx 絶対パスを永続化
   - **自動確定（PENDING）の唯一の根拠**

2. **suggest_patterns（list[str]）**
   - glob 風パターン（`*` のみ、`{era}`/`{month}` 埋め込み可）で候補絞り込み
   - 単独・複数とも自動確定せず、常に NEEDS_REVIEW

3. **scan_fallback + build_folder_tree（候補ゼロ時）**
   - base_dir を浅く walk してフォルダツリーを提示、UI で直接選択

### 不採用案（ADR-015 §Alternatives）

- **B 案 - 実行時 Vertex AI / LLM 自動マッチング**: 不採用
  - 理由: 非決定性によるデバッグ困難 + 介護記録誤配置リスク
  - **将来「規則変更頻発」「担当者大幅増加」が起きた場合に再検討**

### B 処理パターン継承（C への適用）

Session 40 の居宅マッピング自動化（PR #172 関連）で確立されたパターン:

```
[NAS 構造のスキャン]
  cloud/env_scanner.py scan_and_upload
        ↓
[GCS スナップショット保存]
  gs://<bucket>/nas-snapshots/fax-folders-<ts>.json
        ↓
[AI agent (Claude Code) が gcloud storage cat で読み取り]
  スプレッドシート居宅名と機械的マッチング
        ↓
[確定 mapping を GCS に保存]
  gs://<bucket>/mappings/facility-routing-latest.json
        ↓
[Windows 機が pull して TOML に取り込み]
  cloud/mapping_sync.py pull_routing
```

**現状 C 機能はこのパターンの NAS スナップショット部分を持たない**（Windows ローカルで `Path.iterdir()` で都度スキャン）。

将来 Stage 0 として C にも適用するか否かは、**実機での運用ペインポイントが顕在化してから判断**（Codex セカンドオピニオン推奨、Session 42）。先行実装は YAGNI + PII リスク（利用者氏名露出）で過剰。

---

## 業務安全性層（5 層防御）

ADR-015 §Decision §4-5 + CLAUDE.md 既記載で構造化:

1. **自動確定 = cache hit のみ**: 人間が UI で「記憶する」を選んだ path のみ自動使用される
2. **NEEDS_REVIEW での人間レビュー**: 候補単独でも自動確定しない
3. **配置前確認ダイアログ**: PlacementConfirmDialog で **全件 Treeview** 目視（5 件サンプルではない、PR-α v3 HIGH-3 対策）
4. **JSON Lines 監査ログ + threading.Lock**: 配置成功/失敗を append-only で記録
5. **NAS trashbox 復旧経路**: `\\Tera-station\share\trashbox\` で誤配置時の復旧（Session 40 実績）

---

## 出力仕様

### PDF 化

`src/wiseman_hub/pdf/excel_com.py:74` で実装済:
```python
ws.ExportAsFixedFormat(0, str(output_pdf), From=1, To=1)
# xlTypePDF = 0, From=1, To=1 で 1 ページ目のみ
```

### 配置先

`fax_root / fax_folder / cfg.c_output_subfolder / f"{row.name}.pdf"`
- `fax_root`: `\\Tera-station\share\03.FAX(事業所)`
- `fax_folder`: 居宅 → FAX フォルダ resolve（`mappings/facility-routing-latest.json`）
- `c_output_subfolder`: ChecklistConfig 既定（C 専用サブディレクトリ）
- `row.name`: 利用者氏名

### 監査ログ

`<log_dir>/audit/c_placement_<YYYY-MM-DD>.jsonl` に JSON Lines:
```json
{
  "user": "○○ ○○",
  "facility": "LEBEN(メール)",
  "staff": "宮下",
  "xlsx_path": "\\\\Tera-station\\share\\PT 宮下\\...",
  "sheet_name": "○○ ○○",
  "target_pdf": "\\\\Tera-station\\share\\03.FAX(事業所)\\LEBEN(メール)\\○○ ○○.pdf",
  "status": "success",
  "message": "",
  "timestamp": "2026-05-04T..."
}
```

PII 含むため **NAS や共有先にアップロードしない**（runbook 既記載）。

---

## 成功条件

| # | 条件 | 検証方法 |
|---|------|---------|
| 1 | 26 年 3 月分の 60 件前後を誤配置 0 件で配置完了 | 監査ログ + 配置先目視 |
| 2 | 5 担当者 × 各 1 件で cache populate が成立（NEEDS_REVIEW → 「記憶する」→ 実行待ち→ SUCCESS） | C ダイアログ操作 |
| 3 | アプリ再起動後も cache が永続（次月も継続使用可） | TOML 確認 + 同じ staff:year:month で cache hit |
| 4 | 配置前確認で全件 Treeview が表示される（5 件以上の場合） | 6 件以上のテストケース |
| 5 | エラー時に監査ログに status:error で記録され、誤配置されない | 失敗系テスト |

---

## 実装状態

### 完成済（main にマージ済）

#### コア実装

- **PR #172** (`feat(checklist): スプレッドシート連携 B/C PDF 自動配置機能 (MVP)`):
  - ChecklistConfig + B/C 配置エンジン + Tk ダイアログ + 専用設定ダイアログ
  - 居宅 → FAX フォルダマッピング (mapping_sync.py)
  - 環境スキャン (env_scanner.py) for B 処理
- **PR #179** (旧 PR #177, `feat(c): 担当者 xlsx パス cache + サジェスト UI（PR-α v3）`):
  - cache + suggest_patterns + 人間レビュー UI（XlsxPickerDialog）
  - PlacementConfirmDialog（全件 Treeview）
  - audit.py（JSON Lines + threading.Lock）
  - reviewer HIGH 6 件 + M 1 件全反映

#### Session 43 業務化基盤強化

- **PR #181/#182** Windows pytest test 側追従漏れ 11 件修正（Mac で skip 漏れ）
- **PR #183** ChecklistSettingsDialog 保存事故防止（`suggest_patterns` round-trip）
- **PR #184** PR-β v1: report_staff GCS 同期 + 「GCP から担当者を取得」UI ボタン
  - 業務責任者の手動 TOML コピペ運用を「ワンクリック取得」に置換
  - 初回投入: `scripts/init_gcs_report_staff.py`
- **PR #185** Treeview ヘッダー sort + ステータスサマリー集計を共通化（DRY、`ui/common.py`）
  - 業務責任者が毎月 80 件超を一目で把握 + 並び替え
- **PR #186** PR-γ v1: lookup 表記揺れ吸収正規化レイヤー（`utils/text_norm.py`）
  - 全角/半角空白・英数・括弧・連続空白を `normalize_lookup_key` で吸収
  - 「介護相談支援センター　LEBEN」未マッチ問題を恒常解消

### 業務化フェーズ（残作業）

Phase 1 (実機 exe 反映) + Phase 2 (5 担当者 suggest_patterns 投入 + 居宅マッピング補完) は Session 43 で完了。**Phase 3 cache populate 着手前**。詳細は `tasks.md` 参照。

---

## 関連ドキュメント

| 種別 | パス | 役割 |
|------|------|------|
| ADR | `docs/adr/015-staff-path-cache.md` | C マッチング設計判断 + LLM 不採用理由 |
| ADR | `docs/adr/013-facility-root-bulk-merge.md` | B 処理関連（事業所フォルダ集約） |
| ADR | `docs/adr/012-facility-merger-output-format.md` | facility_merger 出力形式 |
| Runbook | `docs/handoff/staff-path-cache-runbook.md` | 5 担当者 cache populate 運用手順 |
| Runbook | `docs/handoff/1c-exe-redistribution-runbook.md` | 実機 exe 反映正規手順 |
| Handoff | `docs/handoff/LATEST.md` | セッション間引き継ぎ（spec の差分メモに縮退予定） |
| Archive | `docs/handoff/archive/session-40-pr-172-mapping.md` | B 処理確立の経緯 |
| 実装 | `src/wiseman_hub/pdf/checklist_c.py` | plan_c_placement / resolve_xlsx / execute_c_placement |
| 実装 | `src/wiseman_hub/pdf/staff_path_scanner.py` | scan_candidates / scan_fallback / build_folder_tree |
| 実装 | `src/wiseman_hub/pdf/excel_com.py` | export_first_page (1 ページ目 PDF 化) |
| 実装 | `src/wiseman_hub/cloud/env_scanner.py` | NAS スナップショット → GCS（B 処理パターン） |
| 実装 | `src/wiseman_hub/cloud/mapping_sync.py` | mappings の GCS push/pull |
| 実装 | `src/wiseman_hub/audit.py` | 監査ログ JSON Lines |

---

## 進捗追跡

→ `tasks.md`

---

## 改訂履歴

| 日付 | 内容 |
|------|------|
| 2026-05-04 | 初版作成（Session 42、文脈分断対策の SDD 移行） |
| 2026-05-05 | Session 43 業務化基盤強化（PR #181-186）追記、Phase 1+2 完了反映、Phase 3 着手前 |
