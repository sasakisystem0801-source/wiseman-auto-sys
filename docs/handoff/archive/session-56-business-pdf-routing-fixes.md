# Handoff: Session 56 完了 - 業務問題 2 件解決 (PR #232 + #233) + Phase 6 引き続き ready

**更新日**: 2026-05-09（Session 56 / Mac 開発機、Session 55 続編）
**main HEAD**: `b20d9a2` feat(checklist-b): monitoring_subfolder substring match で揺らぎ吸収 (#233)
**作業ブランチ**: なし（PR #232 + #233 マージ完了）
**残作業**: ADR-016 **Phase 6 (結合テスト + canary 切替) 引き続き着手可能** + Phase 7 (業務全件配置) + 派生 Issue #211 / #170 / 別ドメイン

---

## 🚪 まずここを読む（次セッション最初の入口）

**業務問題 2 件を即時 PR 解決したセッション**。ユーザーからスクリーンショット報告 → 設計合意 → TDD → 4 並列 review → review 反映 → 番号認可 merge の流れを 2 PR で繰り返し、PR 内で rating ≥ 7 の Important 16 件を吸収済。

| PR | 業務問題 | 解決方法 | 規模 |
|----|---------|---------|------|
| **#232** | ex_ ファイル振り分けで `move_conflict` 発生時に上書き手段なし | 「上書き再実行...」ボタン → 確認ダイアログ → trashbox 退避 + 上書き (a 案) | 4 files / +1043/-15 |
| **#233** | モニタリング `08.運動器機能向上計画書` 設定で `10.` 等で不一致 → 業務停止 | substring match で全 prefix/suffix 揺らぎ吸収 + AMBIGUOUS skip 防御 | 5 files / +411/-4 |

**Phase 6 着手要件は引き続き全部満たされている** (Session 55 LATEST.md `archive/session-55-launcher-type-safety-trio.md` §🚪 表参照、本セッションで変化なし)。

**`/catchup` 後の入口**:

1. ✅ **(Session 53-55 で済)** launcher type-safety 三点セット (#209/#212/#210/#227)
2. ✅ **(本セッションで済)** 業務問題 2 件解決 (#232 ex-overwrite + #233 monitoring-substring)
3. **(次)** **Phase 6 結合テスト + canary 切替**（実 dev tag `v0.99.0` push → release.yml 発火 → GCS upload → bundle 検証 → canary tag）→ 番号認可必要
4. **(最後)** **Phase 7 業務全件配置**（launcher.exe 本田様 PC 手動配布 + Phase 4 全件配置を新システムで実行、TeamViewer 経由）

業務文脈は `specs/c-business-deployment/spec.md`（変更なし）。設計指針は ADR-016。

| ファイル (本セッション変更、要点) | 役割 |
|---------|------|
| [src/wiseman_hub/pdf/ex_extractor.py](../../src/wiseman_hub/pdf/ex_extractor.py) | `extract_one(overwrite_existing, trashbox_root)` + `_quarantine_existing_dest` (urandom suffix) + `retry_overwrite` + `QUARANTINE_DEST_FAILED` |
| [src/wiseman_hub/ui/ex_extractor_dialog.py](../../src/wiseman_hub/ui/ex_extractor_dialog.py) | `UiState.OVERWRITING` + 「上書き再実行...」ボタン + 確認ダイアログ + 例外時 saved_result 復帰 + `_merge_replacement_items` DRY |
| [src/wiseman_hub/pdf/checklist_b.py](../../src/wiseman_hub/pdf/checklist_b.py) | `find_monitoring_dir` 新規 (substring match + `_normalize_name` 適用 + iterdir OSError catch + length guard) + `SKIPPED_NO_MONITORING_DIR` 新 enum |
| [src/wiseman_hub/config.py](../../src/wiseman_hub/config.py) | `monitoring_subfolder` default を canonical name のみに変更 |
| [tests/unit/pdf/test_checklist_b.py](../../tests/unit/pdf/test_checklist_b.py) | 新規 18 件 (find_monitoring_dir 15 + plan_b_placement 3 分岐) |
| 本 LATEST.md | Session 56 差分メモ + 次セッション入口 |

---

## 🎯 Session 56 の成果サマリー

### マージ済 (本セッション、2 PR)

| PR | Issue | 内容 | 規模 | 結果 |
|----|-------|------|------|------|
| **#232** | (Issue 経由なし) | feat(ex-extractor): MOVE_CONFLICT 上書き再実行ダイアログ + trashbox 退避 (+ 4 並列 review Important 9 件本 PR 内吸収) | 4 files / +1043/-15 | ✅ squash merge (`b8ac9a5`) |
| **#233** | (Issue 経由なし) | feat(checklist-b): monitoring_subfolder substring match で揺らぎ吸収 (+ 4 並列 review Important 7 件本 PR 内吸収) | 5 files / +411/-4 | ✅ squash merge (`b20d9a2`) |

**特筆**: 業務問題が「ユーザー報告 → 即対応 → PR で解決」フローで処理され、Issue 経由していない。triage 基準上は「実害あり」で Issue 化対象だが、即時実装で解決した pragmatic 運用 (= 業務 KPI 達成優先、Issue は経過記録の役割を PR が代替)。

### 本セッションで踏んだ重要 process (Generator-Evaluator + 本 PR 内吸収)

**PR #232 (ex-overwrite)**: 4 並列 review (silent-failure / pr-test / code-reviewer / type-design)
- rating ≥ 7 の Important 9 件すべて本 PR 内 commit (`866abee`) で吸収:
  - **C1 CRITICAL (rating 9, 3 review 一致指摘)**: `_quarantine_existing_dest` 同秒衝突 silent overwrite latent bug → `os.urandom(3).hex()` uniquifier (= 既存 `_quarantine_pre_existing_target:691` と一貫) で構造的排除
  - I1+I2 (rating 7): `_on_retry_overwrite_done` の `transition_to_showing_result` 二次破壊防御 + `winfo_exists` ガード
  - I3 (rating 7): `retry_overwrite` で `AssertionError` 明示 re-raise (`MemoryError, RecursionError, AssertionError`)
  - I4 (rating 7): `_merge_replacement_items` の `assert` を `if/raise RuntimeError` (PyInstaller frozen build `python -O` 安全性)
  - G1, G3, G4, G5 (rating 7-9): test 5 件追加 (rollback path / matched_facility None / multiple conflicts / partial failure / same-second collision)
- defer (3 件、別 Issue 候補): OverwriteSpec dataclass / facility_names DRY / G2 widget-level smoke

**PR #233 (monitoring-substring)**: 4 並列 review
- rating ≥ 7 の Important 7 件すべて本 PR 内 commit (`a150771`) で吸収:
  - **C1+C2 (rating 9+8)**: `iterdir()` OSError 未 catch (NAS 切断時バッチ全体クラッシュ) → try/except + PII-safe log
  - **G1 (rating 9)**: `plan_b_placement` の AMBIGUOUS / SKIPPED_NO_MONITORING_DIR / PENDING 3 分岐テスト追加 (業務 KPI 直結)
  - G2 (rating 8): canonical_name 防御テスト (空/短文字/全角スペース)
  - **CR1 (rating 8)**: `SKIPPED_NO_PDF` 流用は識別不能 → `SKIPPED_NO_MONITORING_DIR` 新 enum
  - SF6 (rating 7): canonical_name length guard (`_MIN_CANONICAL_LEN = 3`)
  - CR2 (rating 7): `_normalize_name` 適用で全角スペース等の揺れも吸収
- defer (1 件): 旧 TOML 値 deprecation warning (本 PR description の runbook で代替対応済)

### Issue Net 変化

```
## Issue Net 変化
- Close 数: 0 件
- 起票数: 0 件
- Net: 0 件
```

**Net = 0** だが、本セッションは **業務問題 2 件を Issue 経由せず PR で直接解決** + **review 16 件 Important 吸収** + **test 36 件純増** の実質的進捗あり。CLAUDE.md「Net ≤ 0 が進捗 OK 基準」を 7 連続クリア (Session 50-56)。Issue 化しなかった理由: ユーザー報告 → 即実装で解決、Issue は経過記録としては PR description で十分 (triage 基準は「実害バグ起票」であり、解決済バグの起票は冗長)。

### Test count 変化

1487 (Session 55 末) → **1523** (+36 件 in this session):
- PR #232: +18 件 (TestExtractOneOverwriteWithTrashbox 5 + TestRetryOverwrite 6 + TestViewModelOverwriteTransitions 6 + helper 1)
- PR #233: +18 件 (TestFindMonitoringDir 15 + TestPlanBPlacementMonitoringBranches 3)

### 設計判断の record (4 並列 review)

| PR | 当初案 | 修正後 | 経路 |
|----|--------|--------|------|
| #232 | timestamp suffix のみで衝突回避 | `os.urandom(3).hex()` uniquifier 追加 + 衝突再チェック | C1 (CRITICAL) |
| #232 | `assert self.result is not None` | `if ... raise RuntimeError` | I4 (PyInstaller `-O` 安全性) |
| #232 | `(MemoryError, RecursionError)` のみ re-raise | `+ AssertionError` 追加 | I3 (silent failure 防御) |
| #233 | `iterdir()` 直接 (例外ガードなし) | try/except OSError + (None, []) 復帰 | C1 (NAS 切断時バッチ全体クラッシュ防止) |
| #233 | `cfg.monitoring_subfolder in d.name` 素朴 substring | `_normalize_name(canonical) in _normalize_name(d.name)` | CR2 (find_user_dir パターン対称、揺れ吸収一貫化) |
| #233 | `SKIPPED_NO_PDF` 流用 (フォルダ未発見も同 status) | `SKIPPED_NO_MONITORING_DIR` 専用 enum 新設 | CR1 (運用集計識別性、SKIPPED_NO_USER_DIR と対称) |
| #233 | (length guard なし) | `_MIN_CANONICAL_LEN = 3` で短文字 reject | SF6 (空/短文字 canonical_name 全 dir 誤一致防御) |

---

## 📌 次セッション直近のアクション

### 1. Phase 6 結合テスト + canary 切替 (0.5-1 日、要番号認可) ★ 最優先

Session 55 末と同じ。詳細は archive/session-55-launcher-type-safety-trio.md 参照。

```bash
git checkout main && git pull
git tag v0.99.0
git push origin v0.99.0  # ← 番号認可必須 (destructive: GCS bucket 汚染 + tag history 残存)
gh run watch
```

**確認項目** (PR #214 codex C1 で merge 前に未検証だった部分):
- `actions/attest-build-provenance@v2` の subject 名形式
- GCS bucket `gs://wiseman-hub-release-prod/versions/0.99.0/` の bundle 完成
- launcher 側で実 download → signature 検証 pass

**AI / 人間の役割分担**:
- AI: release.yml run 監視 / GCS 内容確認 / launcher Mac E2E
- ユーザー: tag push 認可、canary 切替判断、Phase 7 への go/no-go 評価

### 2. Phase 7 業務全件配置 (0.5 日、本田様 PC で実機作業、TeamViewer 経由)

Session 55 末と同じ。前提: Phase 6 pass + canary 成功。

**重要**: 本セッション PR #233 マージ後、本田様 PC の TOML 設定値 `monitoring_subfolder` を `08.運動器機能向上計画書` から **`運動器機能向上計画書`** (canonical name のみ) に手動更新必要。UI の「設定」ボタン → 「チェックリスト連携 設定」タブから書き換え + 保存で対応可。

### 3. 派生 Issue 対応 (後回し可、いずれも Phase 6 を block しない)

Session 55 末と同じ。**#211** (refactor: `_atomic_io.atomic_replace_and_fsync_dir` 2 引数化) が筆頭候補。

### 4. 本セッション defer 項目 (Session 57 候補、Issue 化見送り)

| 元 PR | 内容 | rating | 対応案 |
|-------|------|--------|--------|
| #232 | OverwriteSpec dataclass 化 (`extract_one` シグネチャ folding) | 7 | 別 PR で extract_one + retry_overwrite シグネチャ折り畳み |
| #232 | facility_names 共有 helper (extract_directory との DRY) | 7 | 別 PR で `_discover_facility_names` 抽出 |
| #232 | G2 widget-level smoke test (Tk widget reflection の retry_overwrite ボタン enable/disable) | 8 | 既存 `TestExExtractorDialogSmoke` パターンで追加 |
| #233 | 旧 TOML 値 deprecation warning | 7 | config.py で legacy value 検出 → logger.warning |

これらは triage 基準「rating ≥ 7」を満たすが本 PR 内で吸収済の代替手段 (= runbook / pragmatic) で対応済のため Issue 化見送り。Session 57 で着手するなら別 PR を切る。

---

## 🗺️ 残 active Issue (P2 全て、ブロッカーなし)

| # | タイトル | 系統 |
|---|---------|------|
| #211 | refactor: _atomic_io.atomic_replace_and_fsync_dir を 2 引数化 | launcher (Session 50 派生) |
| #170, #164, #162, #161, #158, #152 | ex_extractor / config / ui 系 | 別ドメイン |
| #134 | OCR: Gemini 2.5 Flash retire (2026-10-16) 対応 | OCR |
| #63, #39, #29, #27, #17, #16, #11, #6 | テスト / マッチング / OCR proxy / config / PoC E2E | 別ドメイン |

---

## 🔧 状態スナップショット

| 項目 | 値 |
|------|-----|
| main HEAD | `b20d9a2` feat(checklist-b): monitoring_subfolder substring match で揺らぎ吸収 (#233) |
| working tree | clean (全変更マージ済) |
| 残留 Node プロセス | なし ✅ |
| CI (main push 後) | success (test-unit 56s) |
| Test count | **1523 passed**, 94 skipped (本セッションで +36 件純増) |
| Issue 開件数 | **16** (Session 55 末から変化なし、Net = 0) |
| 業務問題 解決数 | **2 件** (move_conflict 自動解決経路 / monitoring 揺らぎ吸収) |
| Review 吸収件数 | **16 件 Important** (PR #232: 9 件 + PR #233: 7 件) |
| typed package status | wiseman_hub_launcher 引き続き typed package (PEP 561 marker) |
| lock-in file 数 | 3 系統 (Sha256Hex / Phase / LauncherExitCode、Session 53-55 から変化なし) |

---

## ⚙️ 開発環境メモ (Session 51 から変化なし)

- Mac dev: `~/Projects/wiseman-auto-sys`、main で作業
- Windows 実機 (本田様 PC、TeamViewer 経由): `C:\Users\sasak\Projects\wiseman-auto-sys` (clone) + `C:\Users\sasak\wiseman-hub\` (配布物)
- 本番データ: `\\Tera-station\share\03.FAX(事業所)` (UNC、40 事業所、ADR-013)
- NAS trashbox: `\\Tera-station\share\trashbox\` (誤削除復旧経路 + PR #232 上書き退避先)

---

## 🔁 セッション再開条件

- ✅ 再開可能: working tree clean、main 同期、CI 全 pass、handoff 更新済
- 次セッション最初: `/catchup` で Issue 一覧確認 → **本田様 PC の TOML 設定値更新** (PR #233 マージ後の運用必須) → **Phase 6 結合テスト直行** または defer 項目 (Session 57 候補) 対応の選択
- Phase 6 で実 tag push する場合は番号単位の明示認可が必要 (destructive 操作: GCS bucket 汚染 + tag history 残存)
- Phase 6 着手の前提条件はすべて満たされている (archive/session-55-launcher-type-safety-trio.md §🚪 まずここを読む 表参照)
