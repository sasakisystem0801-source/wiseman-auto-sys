# Staff Path Cache 運用 Runbook

ADR-015 で導入した「担当者 xlsx パス cache + サジェスト + レビュー UI」の運用手順。
PR-α（feature/staff-path-sync）マージ後に本 runbook で初回 cache populate を行う。

## 前提

- 本 runbook は実機 Windows PC + TeamViewer 経由で実行する
- Tera-station NAS が SMB マウントされていること（`\\Tera-station\share`）
- `wiseman_hub.exe` が PR-α マージ後の HEAD でビルド配布済（`docs/handoff/1c-exe-redistribution-runbook.md`）

## Phase 0: 5 担当者の suggest_patterns を default.toml に投入

`config/default.toml` の `[checklist.report_staff."<staff>"]` に以下を追加する
（実機実態に基づく初期値、必要に応じて微調整）。

```toml
[checklist.report_staff."宮下"]
base_dir = "\\\\Tera-station\\share\\PT 宮下"
suggest_patterns = [
    "リハ経過報告書/令和{era}年/リハ経過報告書*{month}月*.xlsx",
]

[checklist.report_staff."小島"]
base_dir = "\\\\Tera-station\\share\\PT 小島"
suggest_patterns = [
    "リハ経過報告書(新)/経過報告書*令和{era}年{month}月*.xlsx",
]

[checklist.report_staff."平瀬"]
base_dir = "\\\\Tera-station\\share\\PT 平瀬"
suggest_patterns = [
    "リハ経過報告書/令和{era}年/新経過報告書 {month}月*.xlsx",
]

[checklist.report_staff."木塚"]
base_dir = "\\\\Tera-station\\share\\PT 木塚"
suggest_patterns = [
    "経過報告書/令和*{era}*年度*/経過報告書*木塚*{month}月*.xlsx",
]

[checklist.report_staff."小林"]
base_dir = "\\\\Tera-station\\share\\OT小林"
suggest_patterns = [
    "経過報告書/R{era}/*{month}月*.xlsx",
]
```

設定ダイアログ（C ダイアログ →「設定...」）から TOML フラグメントを直接編集して
保存することもできる。

## Phase 1: 各担当者の対象月 1 件で cache populate

1. C ダイアログで「シート一覧取得」→ 対象月（例: `26年3月`）→ 「対象行を読込」
2. 担当者ごとの行は `▶ 要レビュー` ステータスで表示される
3. 1 行をダブルクリック → xlsx 選択モーダル
4. 候補 Listbox から正しい xlsx を選択 → 「**この選択を記憶**」チェック ON →
   `OK`
5. 該当行が `実行待ち` に変わることを確認
6. 5 担当者分繰り返し（5 担当者 × 1 件 = 5 クリック）

cache が `default.toml` の `[checklist.xlsx_path_cache]` に保存される:

```toml
[checklist.xlsx_path_cache]
"宮下:2026:3" = "\\\\Tera-station\\share\\PT 宮下\\..."
"小島:2026:3" = "\\\\Tera-station\\share\\PT 小島\\..."
...
```

## Phase 2: 翌月以降は cache hit で自動

翌月の C 配置時は対象月を変えるだけで、ほとんどの担当者で「実行待ち」が
即決する（cache hit）。

cache miss が出るのは:
- **新月分のファイルがまだ無い**（業務の進捗待ち）
- **命名規則が変わった**（→ 業務責任者へ確認、ADR-015 前提崩壊）
- **担当者が増えた**（→ TOML に新 entry 追加）

## Phase 3: 監査ログの確認

配置成功/失敗は `<log_dir>/audit/c_placement_<YYYY-MM-DD>.jsonl` に
JSON Lines 形式で蓄積される。

```bash
# 当日の配置数
wc -l "$HOME/wiseman-hub/logs/audit/c_placement_$(date +%Y-%m-%d).jsonl"

# エラー行のみ
grep '"status":"error"' "$HOME/wiseman-hub/logs/audit/c_placement_*.jsonl"
```

PII（利用者氏名・絶対パス）が含まれるため、本ファイルは **NAS や共有先に
アップロードしない**。トラブルシュート目的で本田様の手元のみで参照する。

## Phase 4: 誤配置発生時のロールバック

1. 監査ログで誤配置 record を特定（`target_pdf` 値）
2. Tera-station NAS の `\\Tera-station\share\trashbox\` 経路で復旧経路を確認
3. 直近で配置した PDF が誤りなら、出力 PDF を `Move-Item` で trashbox にいったん
   退避（NAS の元パス構造保持）
4. `xlsx_path_cache` の該当キーを削除（次回は再 scan + 人間レビュー）

```powershell
# 例: 宮下 2026年3月の cache を削除して再選択を強制
# config/default.toml の [checklist.xlsx_path_cache] から "宮下:2026:3" 行を削除
```

## トラブルシュート

| 症状 | 原因候補 | 対処 |
|-----|---------|------|
| 全行 `担当者マッピング未登録` | report_staff 未登録 | Phase 0 を実施 |
| 全行 `▶ 要レビュー` | suggest_patterns 不一致 | Phase 1 でフォルダ選択 → cache 蓄積 |
| 候補 0 件 + 「フォルダから選択」も空 | base_dir パス誤り or NAS 切断 | UNC パスを Explorer で開けるか確認 |
| ダブルクリックしても何も起きない | NEEDS_REVIEW 以外の行を選択している | ステータスが `▶ 要レビュー` の行を選ぶ |
| 「キャッシュ保存失敗」警告 | config_path が読み取り専用、空き容量等 | logs/ ディスクとパス権限を確認 |

## 関連

- ADR-015: 設計判断
- PR #172: C MVP（前提）
- PR-α (feature/staff-path-sync): 本機能本体
- PR-β（予定）: cache + report_staff の GCS 同期（複数 PC 共有）
- グローバル memory: `feedback_nas_trashbox_recovery.md`
