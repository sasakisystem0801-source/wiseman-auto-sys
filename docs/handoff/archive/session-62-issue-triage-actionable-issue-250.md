# Session 62 完了 — Issue triage + #158 actionable error 化 + #250 起票

**Date**: 2026-05-10
**Main HEAD**: `30161bb` feat(diag): 起動後 callback の load_config 失敗を actionable error 化 (Closes #158) (#249)
**Test count**: 1580 → **1584** (+4)
**Active Issues**: 16 → **11 (実質)** [postpone 化 5 件で active カウント外]

---

## 完了内容

### A. Postpone 化 5 件 (active KPI 削減 -5)

CLAUDE.md `feedback_issue_postpone_pattern.md` に従い、observation 待ち / 外部条件待ち / 将来対応 Issue を機械化:

| # | タイトル | 再開条件 |
|---|---|---|
| **#245** | _record_sync_timestamp 失敗時の dirty flag 消失 | Phase 6 canary 後の production observation 待ち |
| **#170** | _quarantine_pre_existing_target tagged union 化 | quarantine ロジック拡張時 |
| **#161** | resolve_review_session 再統合 messagebox マッピング | 将来 GUI 再統合時 |
| **#134** | Gemini 2.5 Flash retire 対応 | Gemini 3 Flash GA + asia-northeast1 提供確認 (2026-09-16 monitor) |
| **#39** | フリガナベースのマッチング | B/C PDF 生成機能仕様確定 |

`postponed` ラベルを新規作成し、各 Issue の body 先頭に `[POSTPONED]` marker + 機械判定可能な再開条件を明記。

### B. Triage 評価 (close 候補 4 件、判断保留)

直近 review 由来の P2 enhancement Issues を評価。close 判断は decision-maker (人間) の領分のため番号単位確認待ち:

| # | タイトル | rating | 推奨 |
|---|---|---|---|
| **#164** | source_dir setter TOCTOU 検証 | rating 5-6 | close (UX 上問題なし、`_redraw` で都度 exists() チェック) |
| **#162** | Launcher callback フリーズ + 例外保護 | rating 5-6 | close (現 callback は dialog 起動のみで軽量) |
| **#152** | UserNameBBox NaN/inf + OcrBackendConfig 空白 URL | rating 6-7 境界 | close (OCR 設定 dialog 経路で UI バリデーション可能) |
| **#63** | Linux Tk wiring tests skip | rating 5-6 | close (Windows runner カバー済、配布先 Windows のみで副次的) |

### β. PR #249 完遂 (Issue #158 close)

**目的**: PR #157 で起動経路 + settings dialog を actionable error 化済の流れを、残り 4 起動後 callback (facility_root / ex_extractor / checklist_b / checklist_c) に展開し対称性を確保。

**変更内容**:
- `src/wiseman_hub/__main__.py` (+68/-4): 4 callback の `load_config` 呼び出しを `try/except (OSError, ValueError, TypeError)` で囲い、`logger.error` (PII-safe 型名のみ) + `messagebox.showerror("設定ファイル読込エラー")` + early return パターン適用
- `tests/unit/test_main_entrypoint.py` (+248): `TestPostStartupCallbackLoadConfigError` クラスで 4 callback × 各例外型を検証、PII 防御 assertion (messagebox body / log メッセージ) を lock-in

**4 並列 review 結果**:
- code-reviewer: Critical 0 / Important 0 / Suggestion 4 (rating 4-5)
- silent-failure-hunter: Critical 0 / Important 1 (rating 7 conf 90、本 PR スコープ外 → Issue #250 起票)
- comment-analyzer: Critical 1 (rating 8 conf 95) / Important 2 (rating 6-7)
- pr-test-analyzer: Critical 0 / Important 0 / Suggestion 3

**本 PR 内吸収** (commit `ed2d903`):
- ✅ C1: コメント内の `(line 222-235)` stale 削除 → `_make_settings_callback` 関数名参照 (grep-stable anchor)
- ✅ I1: test docstring 同様修正
- ✅ I2: 4 callback コメント重複圧縮 (facility_root に詳細集約、他 3 箇所は短縮参照 `Issue #158 (4 callback 共通): facility_root と同形 — 詳細はそちら参照。`)
- ✅ S-1: messagebox body PII 防御 assertion 追加 (4 test、`f"\n\n{exc}"` 退化を catch する規約 lock-in)

**マージ**: 番号認可受領 → PR #249 squash merge (main HEAD `30161bb`)、Issue #158 auto-close (2026-05-10T02:06:31Z)、feature ブランチ削除済。

### γ. follow-up Issue #250 起票

silent-failure-hunter Important rating 7 conf 90 (本 PR スコープ外) を Issue 化:

- **Issue #250**: post-action reload (checklist_b/c dialog 終了後) の `load_config` 失敗を warning ログ化
- 改善案: `_make_checklist_b_callback` / `_make_checklist_c_callback` の except 節 (line 217-221, 258-262) を `pass` から `logger.warning("load_config after checklist_<b|c> dialog failed: %s", type(exc).__name__)` に揃える (`facility_root` post-action と対称化)
- 軽量 PR で対応可能 (3 行 × 2 callback)、triage 基準④ 適合

---

## Issue Net 変化 (本セッション)

```
- Close 数: 1 件 (#158)
- 起票数: 1 件 (#250)
- Net: 0 件
- postpone 化: 5 件 (#245/#170/#161/#134/#39) — active カウント外で実質 -5
```

**Net = 0** だが、postpone 5 件で実質 active KPI が **16 → 11 (-5)** に削減。CLAUDE.md `feedback_issue_triage.md` 基準では Net 計算外。

連続 Net ≤ 0 記録: Session 50-57 で 8 連続 → Session 58 で +1 リセット → Session 59-61 で 3 連続 → **Session 62 で 4 連続再開** (+ postpone 5 件)。

---

## 次セッション優先順 (要番号認可)

| 順 | アクション | 前提条件 |
|---|---|---|
| **1** | **Issue #250 軽量 PR 着手** | 即着手可能、TDD で 30 分以内、checklist_b/c の except 節を 2 行 logger.warning に追加 |
| **2** | **close 候補 4 件の番号単位確認** (#164/#162/#152/#63) | 各 Issue について実害判断、番号認可で close (Net 削減) |
| **3** | **Phase 6 結合テスト + canary 切替** (Task #16) | TeamViewer 復旧 + 番号認可 (`v0.99.0` tag push) |
| **4** | **Phase 7 業務全件配置** (Task #17) | TeamViewer 復旧後、launcher 配布 + Phase 4 全件再実行 |

### 残 active Issue (11 件、judgment 必要)

直近 triage 候補 (close/着手判断保留): #164 / #162 / #152 / #63 / #250 (新)
古い未対応 (本セッション triage 対象外): #29 / #27 / #17 / #16 / #11 / #6

---

## ⚠️ 注意事項

1. **Phase 6 着手要件** (Task #16):
   - TeamViewer 復旧 + 本田様 PC `\\Tera-station\share\03.FAX(事業所)` 接続確認
   - `v0.99.0` tag push の番号認可 (CLAUDE.md 4 原則 §3)
   - 事前検証済 (release.yml 構文 OK / GitHub Variables 5 件 / GCS bucket clean state)

2. **Issue #245 観測待ち**:
   - silent-failure rating 7 conf 88 だが codex rating 8 conf 90 で反対あり
   - Phase 6 canary 後の production observation で sync_summary 不整合事例が観測されたら着手、それまで保留
   - postponed ラベル + body 先頭 `[POSTPONED]` marker 付与済

3. **Issue #134 Gemini 3 Flash 移行 monitor**:
   - 2026-09-01: 再評価
   - 2026-09-16: retire 30 日前、強制再評価
   - 2026-10-15: 移行完了デッドライン
   - postponed ラベル + body に moniter timeline 明記済

4. **postpone 化 Issue 着手プロトコル** (CLAUDE.md `feedback_issue_postpone_pattern.md`):
   - `/catchup` で見えても着手不可
   - ユーザーから該当 Issue 番号の明示指示があった場合のみ着手可
   - 着手前に Issue body の「再開条件」が満たされているかを必ず検証する

5. **本田様 PC TOML 更新**: TeamViewer 復旧時に `monitoring_subfolder` を `運動器機能向上計画書` canonical name に (PR #235 WARNING ログ保険ありで急がない)

6. **小規模 PR review 判断パターン** (本 PR で確立):
   - 軽量 PR (1-2 file / +200 行未満) でも Quality Gate 4 並列 review は最低限実施
   - codex セカンドオピニオンは 200 行超 + 構造的複雑度がある場合に追加検討
   - line 番号参照は grep-stable anchor (function name / class name) を使う (refactor で stale 化リスク回避)

---

## 状態スナップショット

| 項目 | 値 |
|------|-----|
| main HEAD | `30161bb` PR #249 merge |
| working tree | clean |
| 完了 PR | 1 件 (#249) |
| Test count | 1580 → 1584 (+4) |
| Issue 開件数 | 16 件 (実質 active 11 件) |
| 残留プロセス | 別プロジェクト (tadakayo/game-ai vite) のみ — 本プロジェクト無関係 |
| CI | success (Unit Tests + Integration + Build Smoke 全 PASS) |
| postpone 化 (新規) | 5 件 (#245/#170/#161/#134/#39) |
| follow-up Issue (新規) | 1 件 (#250) |
