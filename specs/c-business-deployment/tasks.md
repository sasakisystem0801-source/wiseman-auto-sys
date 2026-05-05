# C 機能業務化 Tasks

**最終更新**: 2026-05-05（Session 43）
**spec**: `./spec.md`
**現在フェーズ**: Phase 3 - cache populate（着手前、Session 44 で実施予定）

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

### Session 43 強化フェーズ（業務化基盤の整備）

- [x] **PR #181** Windows pytest 11 fail 修正（test 側追従漏れ） / Session 43
- [x] **PR #182** TestManualSelectWiring を immutable session 契約に追従 / Session 43
- [x] **PR #183** ChecklistSettingsDialog 保存事故防止（suggest_patterns round-trip） / Session 43
- [x] **PR #184** PR-β v1: report_staff GCS 同期 + 「GCP から担当者を取得」UI ボタン / Session 43
  - 業務責任者の手動 TOML コピペ運用を「ワンクリック取得」に置換
  - 初回 GCS 投入スクリプト（`scripts/init_gcs_report_staff.py`）
- [x] **PR #185** Treeview ヘッダー sort + ステータスサマリー集計を共通化（DRY、C ダイアログ適用） / Session 43
- [x] **PR #186** PR-γ v1: lookup 表記揺れ吸収正規化レイヤー / Session 43
  - 全角/半角空白・英数・括弧・連続空白を `normalize_lookup_key` で吸収
  - 「介護相談支援センター　LEBEN」未マッチ問題を恒常解消

### Phase 1: 実機 exe 反映 ✅ 完了 (Session 43)

- [x] **1-1** リポジトリ最新化（PR #181-#186 順次取込）
- [x] **1-2** 現行 exe バックアップ（複数世代）
- [x] **1-3** 依存同期 + テスト（uv sync --extra dev、Mac 1000 PASS、Windows 1014 PASS + 環境 ERROR 1 件）
- [x] **1-4** Launcher 起動中なら停止
- [x] **1-5** clean ビルド（pyinstaller 6.19.0 / Python 3.11.9）
- [x] **1-6** build warning 検査（無害 3 件のみ: `pycparser.lextab` / `pycparser.yacctab` / `jinja2`）
- [x] **1-7** 配布先に上書き（`$HOME\wiseman-hub\wiseman_hub.exe` Length 79,240,050+α）
- [x] **1-8** 起動確認（コンソール窓出ない、Launcher 起動、5 ボタン構成、`ImportError` なし、Tk 同梱で環境問題回避を実証）

### Phase 2: 5 担当者の suggest_patterns 投入 ✅ 完了 (Session 43)

PR #184 (PR-β v1) で **設定ダイアログ「GCP から担当者を取得」ボタン** によるワンクリック投入に再設計。手動 TOML 編集は不要。

- [x] **2-1** Mac 側で `scripts/init_gcs_report_staff.py` で 5 担当者初期データ JSON 生成
- [x] **2-2** Mac 側で `gs://wiseman-hub-prod-datalake/mappings/report-staff-latest.json` に投入
- [x] **2-3** Windows 機側で C ダイアログ → 設定 → 「GCP から担当者を取得」 → 5 件取得
- [x] **2-4** 「保存」ボタンで `default.toml` 永続化
- [x] **2-5** 設定ダイアログ再オープンで 5 担当者の TOML が round-trip 保持されていることを確認 (PR #183 fix の実機実証)

実機 NAS 確認結果:
- PT 全員: 半角空白あり（`\\Tera-station\share\PT 宮下` 等）
- OT 小林のみ: 空白なし（`\\Tera-station\share\OT小林`）

### Phase 2 補完: 居宅マッピング不足の AI 自動補完 ✅ 完了 (Session 43)

「対象行を読込」で発覚した未登録 9 件 (4 種類) を Session 40 B 処理パターンで AI 自動マッチング:

- [x] **2-6** GCS スナップショット (`fax-folders-20260502-075905.json`) を pull
- [x] **2-7** AI で 4 種類 (あんサポートオフィス / 大津みやび野ホーム / まほろばの里 / 介護相談支援センター LEBEN) を FAX フォルダ実体と match
- [x] **2-8** Mac から push_routing で 4 件追加 (39 → 43 件)
- [x] **2-9** 全角空白版「介護相談支援センター　LEBEN」も追加で push (43 → 44 件)
- [x] **2-10** Windows 機側で「GCP から対照表を取得」 → 44 件取得 → 保存

Phase 2 補完後の状態:
- ⚠ 居宅未登録: 9 件 → **0 件** (PR #186 PR-γ v1 の正規化で全角空白問題も完全吸収)
- ⚠ 担当者未登録: 1 件 (藤井雅章 / 小島/木塚 併記、別問題で残存)

---

## 進行中タスク

なし（Phase 3 着手前、Session 44 で実施予定）

---

## 残タスク

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
| 2026-05-05 | Session 43 完了反映（Phase 1+2 完了マーク、Phase 2 補完追加、PR #181-186 記録、Phase 3 着手前） |
