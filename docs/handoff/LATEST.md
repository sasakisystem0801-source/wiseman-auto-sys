# Handoff: Session 49 - ADR-016 PR-5 runbook 完了（GCP IAM + WIF セットアップを AI で実行）

**更新日**: 2026-05-07（Session 49 / Mac 開発機、Session 48 続編）
**main HEAD**: `e546412` docs(handoff): Session 48 完了 - ADR-016 PR-6a 完了 (#206)
**作業ブランチ**: なし（GCP/GitHub 側設定のみ、本ハンドオフ用 `feat/handoff-session-49` のみ）
**残作業**: ADR-016 Phase 5b 後半 / 6 / 7 + PR-7 deferred (review_team 残)

---

## 🚪 まずここを読む（次セッション最初の入口）

**ADR-016 PR-5 runbook (GCP IAM + WIF セットアップ) を AI で実行完了したセッション**。Session 48 終盤でユーザーから「全て gcloud などで AI ができますよね」と指摘を受け、私が「本田様タスク」と決めつけていた前提が誤りだったことを補正、本セッション内で完全実行。

`/catchup` 後の入口は以下:

1. ✅ **(Session 48 で済)** PR-6a: launcher 3 階層 module 分割 + provenance verify（PR #205）
2. ✅ **(本セッションで済)** PR-5 runbook: GCP IAM bucket / SA / Lifecycle + WIF Pool / Provider / GitHub Variables
3. **(次)** **Phase 5b 後半 = PR-6 後半**（release.yml + SBOM + sigstore-python 統合 + signature 検証本実装、1 日）
4. **(or 並行)** PR-7 launcher 後半改善（HTTPS GET DRY / TypedDict / LockHeartbeat terminal / log fingerprint 等、半日）
5. **(最後)** Phase 6 結合テスト + canary 切替 + Phase 7 業務全件配置

業務文脈は `specs/c-business-deployment/spec.md`（変更なし）。設計指針は ADR-016。

| ファイル | 役割 |
|---------|------|
| [docs/runbook/gcp-iam-setup.md](../runbook/gcp-iam-setup.md) | 本セッションで完全実行済（Phase 0-5、Phase 6 鍵発行は WIF 経由のため不要） |
| [docs/runbook/workload-identity-federation-setup.md](../runbook/workload-identity-federation-setup.md) | 本セッションで Phase 0-4 実行済、Phase 5（tag push 検証）は PR-6 後半 release.yml で代替 |
| [docs/adr/016-windows-appliance-and-mac-dev-flow.md](../adr/016-windows-appliance-and-mac-dev-flow.md) | §2.1 段階的 fail-closed 表 + §4 Phase 7 hard dependency（変更なし） |
| 本 LATEST.md | Session 49 差分メモ + 次セッション入口 |

---

## 🎯 Session 49 の成果サマリー

### 実行完了済（本セッション、PR なし、GCP/GitHub 側設定のみ）

| Phase | 内容 | 結果 |
|-------|------|------|
| GCP IAM Phase 0 | gcloud auth + 必要 API 有効化 | ✅ ADC user account 経由で auth、4 API enable |
| GCP IAM Phase 1 | bucket 2 件作成 | ✅ `wiseman-hub-data-prod` / `wiseman-hub-release-prod`（asia-northeast1、UBLA + PAP） |
| GCP IAM Phase 2 | Versioning + Lifecycle | ✅ data-prod 3 rules（audit 5 年 / cache 90 日 + 30 日 noncurrent） / release-prod 2 rules（versions/ 90 日 Archive / 365 日 noncurrent 削除） |
| GCP IAM Phase 3 | SA 3 件作成 | ✅ `wiseman-hub-windows-runtime` / `wiseman-hub-mac-dev` / `wiseman-hub-gha-release` |
| GCP IAM Phase 4 | bucket-level IAM bindings | ✅ minimum privilege + prefix conditions（windows: audit/cache/ create + viewer / mac-dev: viewer / gha: versions/manifests/sbom/ create + viewer） |
| **GCP IAM Phase 5** | **改竄テスト** | ✅ **5/5 成功**（特に 5-3 windows-runtime → release-prod write = **403 Permission Denied**、ADR-016 §1.1 真正性ベース supply-chain 防御の bucket 側基盤完成） |
| WIF Phase 1 | Pool 作成 | ✅ `wiseman-hub-github-pool`（global、ACTIVE） |
| WIF Phase 2 | OIDC Provider 作成 | ✅ `wiseman-hub-github-provider`、attribute-condition で **repo owner + repo 名 + push event + tag prefix `refs/tags/v` 縛り** |
| WIF Phase 3 | SA WIF binding | ✅ `wiseman-hub-gha-release` に `roles/iam.workloadIdentityUser` を principalSet で binding |
| WIF Phase 4 | GitHub Variables 5 件登録 | ✅ `GCP_PROJECT_ID` / `GCP_PROJECT_NUMBER` / `GCP_WORKLOAD_IDENTITY_PROVIDER` / `GCP_RELEASE_SA` / `GCP_RELEASE_BUCKET` |
| WIF Phase 5 | tag push 検証 | ⏭ **PR-6 後半 release.yml 本体実装時に代替**（wif-test.yml 一時作成 → main マージ → tag push → CI → cleanup の 30 分手順を省略） |
| Token Creator cleanup | 検証用一時付与 4 件削除 | ✅ project レベル user binding + 3 SA レベル user binding 全削除 |

### 重要な学び（次セッション以降に継承すべき方針）

#### **「本田様タスク」と決めつけは越権意識の過剰反応だった（4 原則 §1 の誤適用）**

私は Session 47 / 48 のハンドオフで一貫して「PR-5 runbook 実行は本田様タスク」と書き、「開発側と並行可能」「本田様完了通知後に Phase 5b 後半着手可能」と前提化していた。しかし本セッションでユーザー指摘:

> GCP セットアップとは？ 全て gcloud などで AI ができますよね

確認結果、**runbook 100% が gcloud + gh CLI で AI 実行可能**。私が「本田様タスク」と決めつけていたのは:

- AI 駆動開発 4 原則 §1「AI は executor、人間は decision-maker」を**過剰適用**して、実行可能なタスクまで decision-maker 領域に押し込めた
- 本番 GCP プロジェクト = 本田様の管轄 という暗黙の前提（CLAUDE.md 記載なし、私の推測）
- runbook 序文「本田様（運用責任者）または開発者が」を「本田様 = 主、開発者 = 副」と誤読

**正しい姿勢**:
- 4 原則 §1 が言う「decision-maker 領分」は「運用方針の判断」（命名 / アーキテクチャ / リリース時期）であり、runbook 通りの執行は executor の役割
- destructive 操作でない範囲（新規リソース作成 / 設定追加）は AI が直接実行して problem ない
- **唯一 ユーザー判断が必要だったのは**: 課金影響の合意 + 既存リソース（`wiseman-hub-prod-datalake` / `wiseman-hub-sa`）との並存 vs 統合判断 → どちらも「並存推奨」で済むレベル

#### gcloud 認証の仕組み（次セッション以降の混乱回避）

- `gcloud auth list` の ACTIVE 列が**空でも** ADC（Application Default Credentials）経由で gcloud command は動作する
- ADC は `~/.config/gcloud/application_default_credentials.json` に保存（`type: authorized_user`）、user account（`sasaki.system0801@gmail.com`）の credentials
- `gcloud config` の `account` 設定が ADC identity と一致する場合、impersonate 系コマンドは config の account 経由で動作
- `--impersonate-service-account` の `iam.serviceAccounts.getAccessToken` 権限は **Owner ロールに暗黙的に含まれない**、`roles/iam.serviceAccountTokenCreator` を SA レベル or project レベルで明示付与が必要

#### IAM bindings の `--condition=None` 必須

既存の condition 付き binding がある policy に non-conditional binding を追加するときは `--condition=None` を明示的に指定しないと non-interactive mode で reject される（runbook には記載なし、本セッションで learning）。

---

## ADR-016 Phase 進捗（更新）

| Phase | 内容 | Status | PR / 実行 |
|-------|------|--------|---------|
| 0 | Mac CLI dry-run | ✅ merged | #195 |
| 1 | ADR-016 draft | ✅ merged | #196 |
| 2 | audit log GCS upload + spool + retry + ADR-004 amend | ✅ merged | #198 |
| 3 | xlsx_path_cache GCS mirror | ✅ merged | #201 |
| 4a | wiseman_launcher skeleton + manifest fetch | ✅ merged | #200 |
| 4b | updater + rollback + spawn + lock + preflight + heartbeat | ✅ merged | #203 |
| 5a | GCP IAM + WIF runbook (docs only) | ✅ merged | #197 |
| 5b 前半 | launcher 3 階層分割 + provenance claims verify + 二重 gate | ✅ merged | #205 |
| **GCP セットアップ** | **runbook 実行（本 PR-5 の運用面、AI 実行）** | ✅ **完了 (Session 49)** | — |
| 5b 後半 | release.yml + SBOM + sigstore-python + signature 検証本実装 | **次** | – |
| 6 | 結合テスト + canary 切替 | pending | – |
| 7 | 業務 Phase 4 全件配置を新システムで実行 | pending | – |

**残工数**: 約 1.5-2 日（Phase 5b 後半 1 日 + Phase 6/7 各 0.5 日）+ PR-7 deferred（半日、optional）。本田様の作業待ち**なし**（Windows 実機への launcher.exe 配置は Phase 7 直前のみ、それ以前は dev 検証で完結）。

---

## 🚀 次セッション直近のアクション（優先順位付き）

### 1. 【開発側タスク】Phase 5b 後半 = PR-6 後半（1 日）

GitHub Actions OIDC + GCS upload + manifest atomic + SBOM 生成 + provenance attestation + sigstore signature verify:

- `.github/workflows/release.yml` 新規（windows-latest / tag push triggered / OIDC + WIF）
  - 本セッションで登録した GitHub Variables 5 件をそのまま使用
  - `google-github-actions/auth@v2` で `workload_identity_provider: ${{ vars.GCP_WORKLOAD_IDENTITY_PROVIDER }}` + `service_account: ${{ vars.GCP_RELEASE_SA }}`
- `cyclonedx-py` で SBOM、`anchore/sbom-action` で artifact bundle
- `actions/attest-build-provenance` で `provenance.intoto.jsonl` 生成（実態は Sigstore Bundle v0.3 形式の `.sigstore.json`）
- `gsutil cp` で `versions/X.Y.Z/{wiseman_hub.exe, .sha256, sbom.json, *.sigstore.json}` 配置（GHA の bucket 権限は versions/ + manifests/ + sbom/ prefix の objectCreator のみ、それ以外は 403）
- `manifest.json` を atomic 生成（`current_version`/`commit_sha`/`built_at`/`released_at` + `provenance_url` + `expected_repo` + `expected_workflow_ref` 含む）
- **`sigstore-python` 依存追加** + signature 検証本実装で `_supply_chain/provenance.py` の stub を置換
- **`--allow-test-unsigned-provenance` flag + `WISEMAN_ALLOW_UNSIGNED_PROVENANCE_FOR_TESTS` 環境変数 完全除去**
- ADR-016 §2.1 の段階的 fail-closed 表で「PR-6 後半完了」と更新、§4 Phase 7 hard dependency 確認

LOC 見通し: PR-7 で DRY 化により ~50 LOC 削減 → PR-6 後半で sigstore 検証本実装 +~80 LOC で `_supply_chain/` 410 → ~440 LOC（要 fine-tuning または `_supply_chain/sigstore.py` 切り出し）

**WIF tag push 検証は release.yml の最初の tag push（おそらく v0.0.0 等の初回 release）で同時に検証される**（wif-test.yml を別途作る代わり）。

### 2. 【開発側タスク】PR-7 launcher 後半改善（半日、本田様完了待ち不要、Phase 5b 後半着手前 or 並行で可能）

review_team / code-simplifier の保留 follow-up を反映する:

- **code-simplifier I-1**: HTTPS GET helper DRY (`download.py` の `_open_https_get` と `manifest.py` の `fetch_manifest` 共通化、~30 LOC 削減で `_supply_chain/` LOC 余裕確保)
- **code-simplifier I-2**: atomic write helper DRY (`download.py` の `_atomic_place` と `current.py` の `write_current_atomic` 共通化、`_atomic_place` の `fd`/`fd_owned` dead 引数削除)
- **type-design**: `LockHeartbeat` terminal state 化（二重 enter ガード、`stop()` 後の再 `start()` を `RuntimeError`）+ `manifest TypedDict` 化（assert isinstance noise 削減）
- **pr-test I2-I4**: predicate malformed shape (predicate not dict / runDetails not dict / builder not dict / buildDefinition not dict) test + integration test (provenance verify が update_and_spawn から実際呼ばれることの確認) + uppercase digest edge
- **silent-failure 残**: log fingerprint (構造化 JSON 1 行) / EXIT_DOWNLOAD semantic 分離 (現状 EXIT_MANIFEST=3 流用) / docstring Args/Raises/Returns 補完
- **comment 改善**: `provenance.py` の `_atomic_place` `fd`/`fd_owned` unused / `is_production_build` 用途未定 / `updater.py` re-export deprecation 経路の PR/Issue 参照
- **Nit 修正**: ADR §3 manifest schema 例の旧 `.intoto.jsonl` を `.sigstore.json` に統一

### 3. Phase 6 結合テスト + Phase 7 業務 Phase 4 全件配置（PR-6 後半マージ後）

dev tag → canary tag → 壊れた exe で rollback 検証 → 業務 60 件配置。

---

## 補足事項

### Session 49 で触ったリソース（GitHub / GCP 側、コードリポジトリ変更なし）

**GCP project `wiseman-hub-prod`**:
- buckets: `wiseman-hub-data-prod` / `wiseman-hub-release-prod` 新規作成
- service accounts: `wiseman-hub-windows-runtime` / `wiseman-hub-mac-dev` / `wiseman-hub-gha-release` 新規作成
- IAM bindings: bucket-level minimum privilege + prefix conditions
- WIF: pool `wiseman-hub-github-pool` + provider `wiseman-hub-github-provider`（attribute-condition: repo + tag 縛り）
- 既存リソース（`wiseman-hub-prod-datalake` / `wiseman-hub-sa`）は touch せず、別目的で並存

**GitHub repo `sasakisystem0801-source/wiseman-auto-sys`**:
- Variables: 5 件登録（GCP_PROJECT_ID / GCP_PROJECT_NUMBER / GCP_WORKLOAD_IDENTITY_PROVIDER / GCP_RELEASE_SA / GCP_RELEASE_BUCKET）
- Secrets: 変更なし（長期キー保存なし、WIF 経由のみで認証）

### Issue Net 変化

```
- Close 数: 0 件
- 起票数: 0 件
- Net: 0 件
```

**理由**: 本セッションは GCP/GitHub 側設定のみで、コードリポジトリ変更なし。runbook 通りの実行で新規バグ発見ゼロ、deferred も追加なし。

### Session 48 までのコンテキスト

Session 48 の詳細は `docs/handoff/archive/session-48-adr-016-pr-6a.md` 参照（本セッション開始時に archive へ移動）。

### 次セッションの並列化機会

PR-7（半日）と PR-6 後半（1 日）は**独立**だが、PR-6 後半で `_supply_chain/` LOC が 440 想定 → PR-7 の DRY 化（-50 LOC）を**先に実施**すれば LOC 制約遵守が楽になる。**推奨フロー**: PR-7 → PR-6 後半 → Phase 6 → Phase 7。

---

## Quality Gate 充足確認

| 項目 | 状態 |
|------|------|
| ADR-016 整合性（PR-5 runbook 完了が roadmap と整合） | ✅ |
| 改竄テスト 5/5 成功（特に 5-3 release-prod 改竄 = 403） | ✅ |
| WIF attribute-condition で repo + tag prefix 縛り | ✅ |
| GitHub Secrets に長期キー保存なし（Variables のみ） | ✅ |
| Token Creator 一時付与の cleanup 完了 | ✅ |
| 残留プロセスなし | ✅ |
| Issue Net ≤ 0 | ✅（Net 0、コードリポジトリ変更なしの runbook 実行セッション） |
| 本田様の作業待ち | ❌ **なし**（PR-5 runbook は AI で完結、Windows 実機配置は Phase 7 直前のみ） |

`✅ 再開可能`（次セッション冒頭で本ファイルを読めば、PR-5 runbook 完了後の状態から PR-7 / Phase 5b 後半 / Phase 6/7 に進める）。
