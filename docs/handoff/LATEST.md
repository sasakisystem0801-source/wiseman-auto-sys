# Session 64 完了 — Phase 6 結合テスト + canary 切替 完遂 (Task #16) + 3 連発 bug fix (#254/#255/#256)

**Date**: 2026-05-13
**Main HEAD**: `cd7eb23` fix(launcher): builder.id allowlist を実 GitHub attestation の workflow ref 形式に修正 (#256)
**Test count**: 1587 → **1587** (+0、本セッションは bug fix 中心で test 件数変化なし)
**Active Issues**: 12 (実質 7、postpone 5 を除く) [変化なし]
**Phase**: Phase 6 ✅ 完遂 → **Phase 7 着手前**

---

## 完了内容

### α. Phase 6 結合テスト + canary 切替 完遂 (Task #16 ✅ completed)

ADR-016 Windows アプライアンス化 epic の中核 milestone。本田様 PC 1 台で **launcher.exe → manifest fetch → Sigstore signature verify → wiseman_hub.exe download → spawn → Tk window 表示** の全フローを完遂。

**通過フロー** (本田様 PC 実機ログから確認):
1. ✅ manifest fetch (HTTP 200)
2. ✅ TUF offline mode (`Verifier.production(offline=True)`)
3. ✅ Sigstore signature verify (cert chain + Rekor SET + inclusion proof)
4. ✅ **provenance verified**: sha256=`6e492b167ca84eb6` + identity URL 一致
5. ✅ `wiseman_hub.exe` download (81 MB) → download_complete
6. ✅ current.json 切替 (`0.0.0 → 0.99.0`) → current_switched
7. ✅ wiseman_hub.exe spawn → spawn_complete success
8. ✅ Tk window「Wiseman PDF ツール」表示 (4 ボタン + 設定 全表示確認)

### β. v0.99.0 初回 release + GCS 配信開通

- **v0.99.0 tag push** → release.yml 発火 → PyInstaller build + SBOM + Sigstore attest + GCS upload
- **GCS public read 開通** (本セッションで判明した 4 つの IAM/設定問題を順次解消):
  - `manifests/` (s 付き subdirectory) → `manifest.json` (root 固定) 条件式修正 (release.yml が root に書き込む実装と整合)
  - `roles/storage.objectCreator` → `roles/storage.objectAdmin` (rerun 時の上書きで delete 権限要件、最小権限 conditional binding 維持)
  - `public_access_prevention=enforced` → `inherited` (PR-5 runbook の意図的設定だが ADR-016 §1 の public read 前提 / launcher の stdlib only / 300 LOC 制約と矛盾、設計判断で解除)
  - `allUsers` への `roles/storage.objectViewer` 付与 (manifest URL を知れば誰でも参照可能、ADR-016 line 113/134「公開可能なメタデータ」評価通り)

### γ. 3 連続バグ修正 PR (Phase 6 canary で発見)

Phase 6 実機検証で 3 連続の bug を発見 → 即修正 + main マージ。CI で検知できなかった根本原因は **canary 検証以前に実機 PC で sigstore 経路を実行する smoke test がなかった**こと。

| PR | タイトル | 修正内容 | review |
|---|---|---|---|
| **#254** | launcher.spec を collect_submodules で hidden import 網羅 | `collect_data_files('sigstore')` で TUF trust roots (`_store/prod/*.json`) を bundle 同梱 + `rekor_types` 名修正 + `_hidden()` で `on_error='raise'` (silent 漏れの構造的排除) + 推移依存 8 件追加 (OpenSSL/pyasn1/rfc3161_client/id/jwt/rfc8785/certifi/pyasn1_modules) | code-reviewer Critical 2 + Important 2 を本 PR 内吸収 |
| **#255** | Verifier.production(offline=True) で Windows symlink 権限要件を回避 | `WinError 1314` (symlink 作成権限不足) の根本対策。`Verifier.production()` (引数なし) → `(offline=True)` で TUF online refresh skip、bundle 同梱 trust roots のみで verify。代替案 (本田様 PC Developer Mode ON) は decision-maker 判断で却下 (業務 PC セキュリティ姿勢) | code-reviewer approve (Critical 0 / Important 0、Suggestion 2 件は別 Issue 推奨) |
| **#256** | builder.id allowlist を実 GitHub attestation の workflow ref 形式に修正 | launcher 初期実装の **SLSA Provenance v1.0 §7.2 解釈ミス** (`builder.id = actions/runner@`) を訂正。実 `actions/attest-build-provenance@v2` の builder.id は **workflow ref** (`https://github.com/{owner}/{repo}/.github/workflows/{file}.yml@{ref}`)。`LAUNCHER_EXPECTED_REPO` から動的構築、cross-repo attestation 防御 test 追加 (defense in depth) | 手動チェックリスト review (small tier、軽量 PR) |

**3 PR 共通の教訓**: 「実機 sigstore 経路を CI で検証していなかった」のが見落としの根本。これは Phase 6 canary の本質的価値で、design-implementation gap を発見できた。

---

## Issue Net 変化 (本セッション)

```
- Close 数: 0 件
- 起票数: 0 件
- Net: 0 件
```

**Net = 0、進捗ゼロ扱いだが epic 進捗 (Phase 6 完遂) で正当化**:

- 本セッションは **Phase 6 結合テスト完遂が主目的** (Task #16 completed = ADR-016 epic 中核 milestone)
- 発見した 3 つの bug は即 PR で吸収 (Issue 化せず本 PR 内 close)
- close 候補は前セッションで処理済 (#250/#164/#162/#63、Session 63 で Net -4)
- triage 基準④ (rating ≥ 7) を満たす **後追い debt 3 件は本 LATEST に記録**、別 Issue 化は次セッションで判断 (本セッション中の起票は Phase 6 unblock 集中のため見送り)

連続 Net ≤ 0 記録: Session 59-63 で **5 連続** → Session 64 で **6 連続再開 (Net 0)**。

active KPI 推移:
- Session 63 終了時: 12 件 (実質 active 7 件)
- Session 64 終了時: **12 件 (実質 active 7 件、変化なし)** — bug 発見は PR で吸収、新規 active なし

---

## 次セッション優先順 (要番号認可)

| 順 | アクション | 前提条件 |
|---|---|---|
| **1** | **Phase 7: 業務 Phase 4 全件配置を新システムで実行** (Task #17) | 本田様 PC で launcher 経由運用切替。デスクトップショートカット更新等、運用切替計画が必要 (impl-plan 推奨) |
| **2** | **後追い debt 3 件の判断** (本 LATEST 「⚠️ 注意事項」参照) | Issue 化するか、別 PR でまとめて消化するか、見送るか |
| **3** | Issue #152 軽量 PR or close 判断 | rating 6-7 境界、前セッションから保留中 |
| **4** | 古い P2 Issue 整理 (#29/#27/#17/#16/#11/#6) | triage 基準④ 再評価 |

### 残 active Issue (open 12 件、実質 active 7 件)

- 前セッションからの保留: #152 (rating 6-7 境界、`math.isfinite` + `.strip()` 検証)
- 古い未対応 (本セッション triage 対象外): #29 / #27 / #17 / #16 / #11 / #6
- postpone (active カウント外、明示指示なき限り着手不可): #245 / #170 / #161 / #134 / #39

---

## ⚠️ 注意事項

### 1. Phase 7 着手要件 (Task #17)

- **本田様 PC で launcher 経由運用に切替**: 既存 `wiseman_hub.exe` 直起動経路 → launcher → versioned subdir 経路
- **デスクトップショートカット更新**: 既存ショートカットは `$HOME\wiseman-hub\wiseman_hub.exe` を指す → launcher.exe を指すように変更
- **rollback 経路の確認**: 既存 `wiseman_hub.exe` は無傷で残るので、launcher 経由で問題が出ても即座に元経路に戻せる (CLAUDE.md `1c-exe-redistribution-runbook.md` の Phase 0-2 backup 流用可能)
- **業務影響評価**: 40 事業所データ処理を launcher 経由で実行 (`\\Tera-station\share\03.FAX(事業所)` への UNC アクセス確認)

### 2. 後追い debt 3 件 (本セッション発生分)

PR #254/#255 の review で指摘された Suggestion 系。rating 6-7 で triage 基準④ 境界、本セッションでは Phase 6 unblock 優先のため別 Issue 化見送り。次セッションで判断:

- **smoke-build 強化** (PR #254 handoff debt): `build-windows-smoke.yml` で `python -c "from sigstore.verify import Verifier; Verifier.production(offline=True)"` を smoke 実行 → 今回の `_store` 不在 / `rekor_types` 名前ミス / TUF symlink 要件などを CI で検知可能化。**本セッションで Phase 6 を突破した knowledge** を CI 化する value 高い。
- **trust root staleness 監視** (PR #255 S1): `offline=True` 採用で bundle 同梱 trust root の有効期限切れリスクあり。launcher 起動時に `_store/prod/root.json` の `expires` を warn-log する monitoring 追加検討。
- **sigstore-python 3.x 依存補足 docstring** (PR #255 S2): `pyproject.toml` で `sigstore>=3.0,<4.0` pin 済だが、module docstring に sigstore 3.x 依存の明示があると親切。

### 3. 本田様 PC の wiseman_hub.exe 配置状況 (Phase 6 完遂後)

```
$HOME\wiseman-hub\
├── wiseman_hub.exe              (79.3 MB, 既存直起動経路)
├── wiseman_hub.exe.bak-*        (rollback バックアップ多数)
├── wiseman_launcher.exe         (27.4 MB, PR #256 反映版、SHA-256: 81b5e2f8...)
├── current.json                 (0.99.0 切替済、launcher 管理)
├── versions/0.99.0/
│   └── wiseman_hub.exe          (launcher 経由 download 済、81 MB)
├── launcher-update-v3.log       (PR #255 後の WinError 1314 ログ)
├── launcher-update-v4.log       (Phase 6 完遂時のログ)
└── ... (assets / cache / config / logs / scripts、既存ディレクトリ)
```

### 4. ADR-016 design-implementation gap (本セッションで発覚)

Phase 6 canary 検証で 3 連続 bug 発見の構造的原因。今後の supply-chain 領域 implementation で同様の見落としを防ぐ仕組みが必要:

- **SLSA Provenance v1.0 §7.2 解釈ミス** (PR #256): 初期実装で `builder.id = actions/runner@` と思い込み、実 `actions/attest-build-provenance@v2` 出力で fail。**spec の prose 解釈だけでなく、CI run の生 attestation を取得して allowlist を経験的に確定する**プロセスが必要。
- **Windows symlink 権限要件** (PR #255): sigstore-python の TUF online refresh が `root_history/N.root.json → root.json` の symlink を作る → Windows 非管理者で fail。**Linux CI runner だけでテストすると見落とす**ので Windows runner で smoke 実行する design pattern が必要 (smoke 強化 debt と同じ理由)。
- **PyInstaller hidden imports の silent 漏れ** (PR #254): `collect_submodules` の default `on_error='warn once'` で誤字や未インストールも build 完走 → canary で初露見。**`on_error='raise'` を default 戦略**にすべき。

### 5. postpone 化 Issue 着手プロトコル (CLAUDE.md `feedback_issue_postpone_pattern.md`)

- `/catchup` で見えても着手不可 (#245 / #170 / #161 / #134 / #39)
- ユーザーから該当 Issue 番号の明示指示があった場合のみ着手可
- 着手前に Issue body の「再開条件」が満たされているかを必ず検証する

### 6. 本田様 PC TOML 更新 (前セッションからの繰越)

TeamViewer 復旧時 (本セッションで復旧確認済) に `monitoring_subfolder` を `運動器機能向上計画書` canonical name に更新するタスクは **依然未対応**。PR #235 WARNING ログ保険ありで急がないが、Phase 7 着手前 or 同時に処理することを推奨。

---

## 状態スナップショット

| 項目 | 値 |
|------|-----|
| main HEAD | `cd7eb23` PR #256 merge |
| working tree | clean |
| 完了 PR | 3 件 (#254 / #255 / #256) |
| Test count | 1587 passed (本セッション変化なし、bug fix 中心) |
| Issue 開件数 | 12 件 (実質 active 7 件、postpone 5 除く) |
| 残留プロセス | なし ✅ |
| Phase 6 (Task #16) | ✅ completed |
| Phase 7 (Task #17) | pending、次セッション着手予定 |
| 新規 release | v0.99.0 (初回)、GCS 配信稼働中 |
| GCS bucket `wiseman-hub-release-prod` | public read 開通済、`versions/0.99.0/` + root manifest.json 配置 |
| 本田様 PC launcher | PR #256 反映版稼働中 (`81b5e2f8...`)、current.json 0.99.0 |
