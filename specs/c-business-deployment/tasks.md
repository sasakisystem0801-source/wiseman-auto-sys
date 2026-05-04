# C 機能業務化 Tasks

**最終更新**: 2026-05-04（Session 42）
**spec**: `./spec.md`
**現在フェーズ**: Phase 1 - 実機反映（着手前）

---

## 完了済タスク

### 設計・実装フェーズ

- [x] **ADR-015** 採択（cache + suggest + 人間レビュー UI、LLM 不採用）/ Session 41
- [x] **PR #172** B/C MVP マージ（main 反映） / Session 42
  - ChecklistConfig + B/C 配置エンジン + Tk ダイアログ
  - 居宅 → FAX フォルダマッピング（mapping_sync.py）
  - 環境スキャン（env_scanner.py、B 処理パターン確立）
- [x] **PR #179** PR-α v3 マージ（main 反映） / Session 42
  - cache + suggest_patterns + 人間レビュー UI（XlsxPickerDialog）
  - PlacementConfirmDialog（全件 Treeview）
  - audit.py（JSON Lines + threading.Lock）
  - reviewer HIGH 6 件 + M 1 件全反映
- [x] **PR #176** Session 40 handoff マージ
- [x] **PR #178** Session 41 handoff マージ
- [x] Codex セカンドオピニオン取得（Session 42、Stage 0 構想に対する PII / 順序評価）

---

## 進行中タスク

なし（Phase 1 着手前）

---

## 残タスク

### Phase 1: 実機 exe 反映（runbook: `docs/handoff/1c-exe-redistribution-runbook.md`）

実行環境: 本田様 PC、TeamViewer 経由 PowerShell

- [ ] **1-1** リポジトリ最新化（`git checkout main && git pull --ff-only`）
- [ ] **1-2** 現行 exe バックアップ（`wiseman_hub.exe.bak-<timestamp>`）
- [ ] **1-3** 依存同期 + テスト（`uv sync --extra dev && uv run pytest -q -m "not integration"`）
- [ ] **1-4** Launcher 起動中なら停止
- [ ] **1-5** clean ビルド（`uv run pyinstaller wiseman_hub.spec --clean --noconfirm`）
- [ ] **1-6** build warning 検査（プロジェクト由来 warning がないこと）
- [ ] **1-7** 配布先に上書き（`Copy-Item -Force dist\wiseman_hub.exe "$dist\wiseman_hub.exe"`）
- [ ] **1-8** 起動確認（コンソール窓出ない、Launcher 起動、`ImportError` なし）

完了条件: Launcher が PR #179 ベースで起動し、C 機能ボタンから C ダイアログが開く

### Phase 2: 5 担当者の suggest_patterns 投入（runbook: `docs/handoff/staff-path-cache-runbook.md` Phase 0）

`$HOME\wiseman-hub\config\default.toml` に追記:

- [ ] **2-1** PT 宮下 entry 追加（`base_dir = "\\\\Tera-station\\share\\PT 宮下"`、suggest_patterns: `リハ経過報告書/令和{era}年/リハ経過報告書*{month}月*.xlsx`）
- [ ] **2-2** PT 小島 entry 追加（新旧 2 系統対応、suggest_patterns: `リハ経過報告書(新)/経過報告書*令和{era}年{month}月*.xlsx`）
- [ ] **2-3** PT 平瀬 entry 追加（担当者名なし、suggest_patterns: `リハ経過報告書/令和{era}年/新経過報告書 {month}月*.xlsx`）
- [ ] **2-4** PT 木塚 entry 追加（同フォルダ別人混在、suggest_patterns: `経過報告書/令和*{era}*年度*/経過報告書*木塚*{month}月*.xlsx`）
- [ ] **2-5** OT 小林 entry 追加（suggest_patterns: `経過報告書/R{era}/*{month}月*.xlsx`）

完了条件: TOML 構文エラーなし、アプリ再起動で `[checklist.report_staff."<staff>"]` が認識される

注意: pattern が NAS 実態と完全一致しない場合は cache populate（Phase 3）でフォルダツリーから直接選択 → 「記憶する」で吸収可能

### Phase 3: 5 担当者 × 26 年 3 月で cache populate（runbook Phase 1）

GUI 操作（PowerShell ではなく）:

- [ ] **3-1** C ダイアログを開く
- [ ] **3-2** 「シート一覧取得」→ 対象月「26年3月」選択 → 「対象行を読込」
- [ ] **3-3** PT 宮下の行をダブルクリック → XlsxPickerDialog で正しい xlsx を選択 → 「記憶する」ON → OK
- [ ] **3-4** PT 小島で同様（新旧 2 系統が候補に出る場合は最新の方を選択）
- [ ] **3-5** PT 平瀬で同様
- [ ] **3-6** PT 木塚で同様（同フォルダの「東浦」と混同しないよう注意）
- [ ] **3-7** OT 小林で同様
- [ ] **3-8** 全 5 担当者の行が「実行待ち」になることを確認
- [ ] **3-9** TOML を確認、`[checklist.xlsx_path_cache]` に 5 件の cache が保存されていること

完了条件: cache 5 件が TOML 永続化、5 担当者すべてで NEEDS_REVIEW → 実行待ち遷移成功

### Phase 4: 配置実行 + 動作確認

- [ ] **4-1** C ダイアログで「実行」ボタン押下
- [ ] **4-2** PlacementConfirmDialog で全件 Treeview を目視確認 → OK
- [ ] **4-3** 配置完了後、FAX 事業所フォルダ配下に PDF が生成されていることを確認（`Get-ChildItem` で件数チェック）
- [ ] **4-4** PDF を 1〜2 件開いて、対象シートの 1 ページ目が出ていることを目視確認
- [ ] **4-5** 監査ログ確認（`$HOME\wiseman-hub\logs\audit\c_placement_<today>.jsonl`、件数 = 配置成功数）
- [ ] **4-6** エラー行があれば status:error で記録されていること（誤配置していないこと）

完了条件: 26 年 3 月分の経過報告書 PDF が誤配置 0 で FAX 事業所フォルダに配置完了、監査ログ整合

### Phase 5: 業務継続性確認（再起動 + 翌月 cache populate）

- [ ] **5-1** アプリ再起動後、26 年 3 月の同じ行を読み込み → cache hit で全行 PENDING になること
- [ ] **5-2** 26 年 4 月（または対象次月）でロード → 5 担当者全員 NEEDS_REVIEW（月別 cache 設計の確認）
- [ ] **5-3** 4 月分 cache populate（Phase 3 と同じ手順、5 クリック × 1 月 = 5 分）

完了条件: 月次運用フローが確立、業務責任者が独立で運用継続可能

### Phase 6: 振り返り + Issue 棚卸し

- [ ] **6-1** Phase 1-5 実機実行で見つかったペインポイントを `LATEST.md` に記録
- [ ] **6-2** Codex 推奨の Stage 0（GCS スナップショット + AI agent 駆動 mapping 提案）が必要か再評価
  - 痛点が「設定初期化が辛い」→ 縮小版 Stage 0 検討（PII 配慮: フォルダ構造のみ、xlsx 名出さない）
  - 痛点が「毎月 cache miss が多い」→ suggest_patterns 改善
  - 痛点が「担当者追加・規則変更」→ 同期・承認機構追加
- [ ] **6-3** ADR-015 §B 「将来再検討トリガー」に該当するか判断
- [ ] **6-4** 軽微改善 follow-up（PR #179 reviewer の Phase 2 課題 7 件）の優先度付け
- [ ] **6-5** spec.md / tasks.md 更新（Phase 1-5 完了を反映、次フェーズへ）

完了条件: 業務継続フローが確立し、次の改善判断材料が揃う

---

## ブロッカー / リスク

| 項目 | リスク | 対策 |
|------|--------|------|
| Excel COM が VBA マクロ付き xlsx で固まる | 配置実行が止まる | reviewer Phase 2 課題（Excel COM 例外分類強化）を優先実装 |
| NAS 接続不安定 | scan / 配置失敗 | 監査ログ status:error で検知、再実行で復旧 |
| suggest_patterns が NAS 実態と乖離 | 候補ゼロで NEEDS_REVIEW 多発 | folder_tree fallback で人間が直接選択（既存設計） |
| 業務責任者の操作ミスで誤配置確定 | 介護記録誤配置 | 配置前 Treeview 全件確認 + trashbox 復旧経路 |
| cache 永続化失敗（権限/容量） | 次回起動で cache 喪失 | 「キャッシュ保存失敗」警告（実装済）+ runbook トラブルシュート参照 |

---

## 改訂履歴

| 日付 | 内容 |
|------|------|
| 2026-05-04 | 初版作成（Session 42、Phase 1 着手前） |
