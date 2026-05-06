# Workload Identity Federation 設定手順書（ADR-016 PR-5）

**目的**: GitHub Actions が長期 GCP サービスアカウントキーを GitHub Secrets に保存することなく `wiseman-hub-release-prod` に exe / manifest / SBOM を upload できるようにする。codex セカンドオピニオン Critical C-3（supply-chain 強化）の対応。

**前提条件**:
- `gcp-iam-setup.md` の Phase 1-5 が完了している（特に `wiseman-hub-gha-release` SA が作成済）
- GitHub repo: `sasakisystem0801-source/wiseman-auto-sys`
- 実行者: GCP 側で `Project Owner` または `Workload Identity Pool Admin` 権限、GitHub 側で repo の `admin` 権限
- 想定所要時間: 20-30 分

**このランブックの完走で達成されること**:
1. ✅ Workload Identity Pool + Provider が作成される
2. ✅ GitHub Actions OIDC トークンが GCP SA に impersonate できる
3. ✅ `release.yml` workflow が長期キーなしで GCS upload 可能になる
4. ✅ 設定値が GitHub Variables に登録される（PR-6 で参照）

---

## 🎯 Phase 0: 事前確認（3 分）

### 0-1. project number の取得

```bash
gcloud projects describe wiseman-hub-prod --format="value(projectNumber)"
# 出力例: 123456789012 (12 桁)
# → これを以降 PROJECT_NUMBER として使う
```

### 0-2. 必要 API の有効化（既に有効なら no-op）

```bash
gcloud services enable iamcredentials.googleapis.com
gcloud services enable sts.googleapis.com
```

---

## 🎯 Phase 1: Workload Identity Pool 作成（5 分）

### 1-1. Pool 作成

```bash
gcloud iam workload-identity-pools create wiseman-hub-github-pool \
  --project=wiseman-hub-prod \
  --location=global \
  --display-name="Wiseman Hub GitHub Pool" \
  --description="OIDC pool for GitHub Actions release pipeline"
```

検証:
```bash
gcloud iam workload-identity-pools describe wiseman-hub-github-pool \
  --project=wiseman-hub-prod \
  --location=global
# 期待: state = ACTIVE
```

---

## 🎯 Phase 2: OIDC Provider 作成（5 分）

### 2-1. GitHub OIDC Provider 設定

attribute mapping は以下を使う（公式推奨）:

```bash
gcloud iam workload-identity-pools providers create-oidc wiseman-hub-github-provider \
  --project=wiseman-hub-prod \
  --location=global \
  --workload-identity-pool=wiseman-hub-github-pool \
  --display-name="GitHub Actions OIDC" \
  --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner,attribute.ref=assertion.ref,attribute.event_name=assertion.event_name" \
  --attribute-condition="assertion.repository_owner == 'sasakisystem0801-source' && assertion.repository == 'sasakisystem0801-source/wiseman-auto-sys' && assertion.event_name == 'push' && assertion.ref.startsWith('refs/tags/v')" \
  --issuer-uri="https://token.actions.githubusercontent.com"
```

**重要**: `attribute-condition` で repo 縛り + **tag push 限定** を Provider レベルで設定し、他リポジトリ + feature branch からの impersonate を遮断する。
SA 側に conditional binding を追加する方式は無条件経路（後段の SA binding）を残すと bypass されるため不採用（codex security review 指摘）。

検証:
```bash
gcloud iam workload-identity-pools providers describe wiseman-hub-github-provider \
  --project=wiseman-hub-prod \
  --location=global \
  --workload-identity-pool=wiseman-hub-github-pool \
  --format="value(state,attributeCondition)"
# 期待: ACTIVE  assertion.repository_owner == ... && ... assertion.ref.startsWith('refs/tags/v')
```

---

## 🎯 Phase 3: Service Account に WIF binding（5 分）

### 3-1. PROJECT_NUMBER を環境変数に

```bash
PROJECT_NUMBER=$(gcloud projects describe wiseman-hub-prod --format="value(projectNumber)")
echo "PROJECT_NUMBER=$PROJECT_NUMBER"
```

### 3-2. GHA OIDC SA に対して WIF からの impersonate を許可

tag push 限定は Phase 2 の `attribute-condition` で完結するため、SA binding は無条件で OK:

```bash
gcloud iam service-accounts add-iam-policy-binding \
  wiseman-hub-gha-release@wiseman-hub-prod.iam.gserviceaccount.com \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/wiseman-hub-github-pool/attribute.repository/sasakisystem0801-source/wiseman-auto-sys"
```

検証:
```bash
gcloud iam service-accounts get-iam-policy \
  wiseman-hub-gha-release@wiseman-hub-prod.iam.gserviceaccount.com \
  --format="json" | grep workloadIdentityUser
# 期待: principalSet://iam.googleapis.com/.../wiseman-hub-github-pool/...
```

**注意**: 旧版手順では SA binding に `condition=request.auth.claims.ref.startsWith('refs/tags/v')` を追加する案もあったが、
codex security review で以下が指摘されたため不採用とした:
- IAM Conditions の `request.auth.claims` は WIF impersonate 時の OIDC token claim を直接参照できない（用途違い）
- 無条件 binding を残したまま条件付き binding を追加しても、無条件経路が bypass 経路として残る
- tag 制限は Provider の `attribute-condition` に集約することで、認証段階で deny される設計が正解

---

## 🎯 Phase 4: 設定値を GitHub に登録（5 分）

### 4-1. GitHub Repository Variables（Secrets ではなく Variables）

**長期キーは保存しない**。Variables は public でも安全な値のみ。

なぜ Secrets ではなく Variables で OK か:
- 列挙する値（project ID / project number / WIF provider path / SA email / bucket 名）は **識別子であり認証材料ではない**
- 認証は WIF token（`id-token: write` 権限）+ Phase 2 の `attribute-condition`（repo + tag 縛り）+ Phase 3 の SA binding の 3 段階で行われる
- これらの識別子が漏洩しても、攻撃者は GitHub OIDC 経由かつ正しい repo + tag 条件でしか impersonate できない
- ログ出力時にマスクされなくても問題なし（Variables の典型用途）

| 名前 | 値 | 取得方法 |
|------|-----|---------|
| `GCP_PROJECT_ID` | `wiseman-hub-prod` | 固定 |
| `GCP_PROJECT_NUMBER` | `${PROJECT_NUMBER}` | Phase 3-1 で取得 |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | `projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/wiseman-hub-github-pool/providers/wiseman-hub-github-provider` | Phase 2 結果 |
| `GCP_RELEASE_SA` | `wiseman-hub-gha-release@wiseman-hub-prod.iam.gserviceaccount.com` | Phase 3-2 結果 |
| `GCP_RELEASE_BUCKET` | `wiseman-hub-release-prod` | 固定 |

GitHub web UI 操作:
1. https://github.com/sasakisystem0801-source/wiseman-auto-sys/settings/variables/actions
2. "New repository variable" で上記 5 個を登録
3. 値はすべて Variables（Secret ではない、ログ出力されても問題ない）

CLI 代替:
```bash
gh variable set GCP_PROJECT_ID --body "wiseman-hub-prod"
gh variable set GCP_PROJECT_NUMBER --body "${PROJECT_NUMBER}"
gh variable set GCP_WORKLOAD_IDENTITY_PROVIDER --body "projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/wiseman-hub-github-pool/providers/wiseman-hub-github-provider"
gh variable set GCP_RELEASE_SA --body "wiseman-hub-gha-release@wiseman-hub-prod.iam.gserviceaccount.com"
gh variable set GCP_RELEASE_BUCKET --body "wiseman-hub-release-prod"
```

検証:
```bash
gh variable list
# 期待: 上記 5 個が表示される
```

---

## 🎯 Phase 5: WIF 動作検証（5 分）

PR-6 の release.yml が完成する前に、**一時的な検証用 tag** で WIF impersonate を試す。
Phase 2 の `attribute-condition` で tag push 限定にしているため、`workflow_dispatch` では impersonate できない。
そのため検証も tag push で行う。

### 5-1. 検証用 workflow を一時的に作成

`.github/workflows/wif-test.yml` に以下を作成（検証完了後に削除する前提）:

```yaml
name: WIF Test (delete after verification)

on:
  push:
    tags:
      - 'v0.0.0-wif-test*'

permissions:
  id-token: write
  contents: read

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Authenticate to GCP via WIF
        uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{ vars.GCP_WORKLOAD_IDENTITY_PROVIDER }}
          service_account: ${{ vars.GCP_RELEASE_SA }}

      - name: Setup gcloud
        uses: google-github-actions/setup-gcloud@v2

      - name: Verify auth
        run: gcloud auth list

      - name: Test write to release bucket
        run: |
          echo "wif-test-$(date -u +%Y%m%dT%H%M%SZ)" | \
            gcloud storage cp - gs://${{ vars.GCP_RELEASE_BUCKET }}/wif-test/probe.txt
          gcloud storage cat gs://${{ vars.GCP_RELEASE_BUCKET }}/wif-test/probe.txt

      - name: Cleanup
        if: always()
        run: gcloud storage rm gs://${{ vars.GCP_RELEASE_BUCKET }}/wif-test/probe.txt || true
```

### 5-2. 検証用 tag を push して動作確認

```bash
# main にコミットして push
git add .github/workflows/wif-test.yml
git commit -m "chore: add temporary WIF test workflow"
git push

# 検証用 tag を発行（attribute-condition の tag 縛りを通すため）
git tag v0.0.0-wif-test1
git push origin v0.0.0-wif-test1
```

GitHub Actions の Run UI で全 step が緑になることを確認。

失敗例:
- `Permission denied`: Phase 3 の SA binding が間違っている → `gcloud iam service-accounts get-iam-policy` で再確認
- `Unable to acquire impersonation credentials`: Phase 2 の `attribute-condition` が一致していない（repo 名 / tag prefix）
- `iam.serviceAccounts.getAccessToken denied`: Phase 0-2 の API 有効化忘れ

検証用 tag が `v0.0.0-wif-test*` 形式（`v` で始まる）なので Phase 2 の `assertion.ref.startsWith('refs/tags/v')` 条件を満たす。

### 5-3. 検証後、test workflow と tag を削除

```bash
# tag 削除（local + remote）
git tag -d v0.0.0-wif-test1
git push origin :refs/tags/v0.0.0-wif-test1

# workflow 削除
git rm .github/workflows/wif-test.yml
git commit -m "chore: remove WIF test workflow after verification"
git push

# release bucket の検証 object 削除（Cleanup step が失敗していた場合の保険）
gcloud storage rm gs://wiseman-hub-release-prod/wif-test/probe.txt 2>/dev/null || true
```

---

## ⚠️ セキュリティ確認チェックリスト

- [ ] WIF Pool の `attribute-condition` で repo owner + repo 名を絞っている（他リポジトリからの impersonate 不可）
- [ ] SA bindings に長期キーが残っていない（`gcloud iam service-accounts keys list` で USER_MANAGED 鍵がゼロまたは厳格管理されたもののみ）
- [ ] GitHub Secrets に GCP key が保存されていない（Variables のみ）
- [ ] `wif-test.yml` が削除済み

---

## ⚠️ rollback 手順

```bash
# SA binding 削除
gcloud iam service-accounts remove-iam-policy-binding \
  wiseman-hub-gha-release@wiseman-hub-prod.iam.gserviceaccount.com \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/wiseman-hub-github-pool/attribute.repository/sasakisystem0801-source/wiseman-auto-sys"

# Provider 削除
gcloud iam workload-identity-pools providers delete wiseman-hub-github-provider \
  --location=global \
  --workload-identity-pool=wiseman-hub-github-pool

# Pool 削除（30 日間 soft-delete されるので注意）
gcloud iam workload-identity-pools delete wiseman-hub-github-pool --location=global

# soft-delete 期間中の再作成衝突時:
# 1. soft-delete されている Pool を確認
gcloud iam workload-identity-pools list --location=global --show-deleted

# 2. undelete で復活させる（30 日以内なら可能）
gcloud iam workload-identity-pools undelete wiseman-hub-github-pool \
  --location=global --project=wiseman-hub-prod

# 3. provider も同様に soft-delete されているので必要なら undelete
gcloud iam workload-identity-pools providers list \
  --workload-identity-pool=wiseman-hub-github-pool \
  --location=global --show-deleted

gcloud iam workload-identity-pools providers undelete wiseman-hub-github-provider \
  --workload-identity-pool=wiseman-hub-github-pool \
  --location=global --project=wiseman-hub-prod

# GitHub Variables 削除
for v in GCP_PROJECT_ID GCP_PROJECT_NUMBER GCP_WORKLOAD_IDENTITY_PROVIDER GCP_RELEASE_SA GCP_RELEASE_BUCKET; do
  gh variable delete $v
done
```

---

## 完了確認チェックリスト

- [ ] WIF Pool `wiseman-hub-github-pool` が ACTIVE
- [ ] OIDC Provider `wiseman-hub-github-provider` が ACTIVE、attribute-condition で repo 縛り
- [ ] SA `wiseman-hub-gha-release` に `roles/iam.workloadIdentityUser` が WIF principalSet で binding
- [ ] GitHub Variables 5 個が登録済
- [ ] Phase 5 の `wif-test.yml` で write/read/cleanup が緑
- [ ] `wif-test.yml` 削除済

完了後、PR-6 の `release.yml` 実装に進める状態になる。

---

## References

- [Configuring OpenID Connect in Google Cloud Platform (GitHub Docs)](https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-google-cloud-platform)
- [google-github-actions/auth](https://github.com/google-github-actions/auth)
- [Workload Identity Federation overview (GCP Docs)](https://cloud.google.com/iam/docs/workload-identity-federation)
- ADR-016 Critical C-3: GHA OIDC + Provenance
