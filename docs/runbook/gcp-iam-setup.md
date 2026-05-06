# GCP IAM セットアップ手順書（ADR-016 PR-5）

**目的**: ADR-016 の Bucket 分離 + IAM 最小権限を実機の GCP 環境に反映する。本手順は本田様（運用責任者）または開発者が GCP コンソール / `gcloud` CLI で **1 度だけ** 実行する。

**前提条件**:
- GCP プロジェクト: `wiseman-hub-prod` が既存（ADR-003 で決定済）
- リージョン: `asia-northeast1`（東京、APPI / ismap 準拠）
- 実行者ロール（**いずれかが必要、Project Owner ならすべて含む**）:
  - `roles/storage.admin`（bucket 作成 / IAM binding）
  - `roles/iam.serviceAccountAdmin`（SA 作成）
  - `roles/iam.serviceAccountKeyAdmin`（Phase 5 / 6 の key 発行・削除）
  - `roles/iam.serviceAccountTokenCreator`（Phase 5 検証で `--impersonate-service-account` を使う場合）
  - `roles/iam.workloadIdentityPoolAdmin`（WIF 手順書側で使用）
  - `roles/serviceusage.serviceUsageAdmin`（API 有効化）
- `gcloud` CLI が認証済（`gcloud auth list` で確認）
- 想定所要時間: 30-40 分（コマンド実行 15 分 + 検証 15 分）

**このランブックの完走で達成されること**:
1. ✅ `wiseman-hub-data-prod` / `wiseman-hub-release-prod` の 2 bucket が作成される
2. ✅ Uniform Bucket-Level Access、Object Versioning、Lifecycle が設定される
3. ✅ 3 つの Service Account（Windows runtime、Mac dev、GHA OIDC）が作成される
4. ✅ Bucket-level IAM で最小権限（write/read 分離）が適用される
5. ✅ Windows runtime SA が release-prod を改竄できないことを検証

**関連手順書**: Workload Identity Federation 設定は別ファイル `workload-identity-federation-setup.md` 参照。

---

## 🎯 Phase 0: 事前確認（3 分）

### 0-1. gcloud 認証と project 設定

```bash
gcloud auth list
gcloud config set project wiseman-hub-prod
gcloud config list
```

期待: `account = sasaki.system0801@gmail.com`、`project = wiseman-hub-prod`。

### 0-2. 必要 API の有効化（既に有効なら no-op）

```bash
gcloud services enable storage.googleapis.com
gcloud services enable iam.googleapis.com
gcloud services enable iamcredentials.googleapis.com
gcloud services enable sts.googleapis.com  # WIF 用
```

### 0-3. 既存リソースの確認（重複作成防止）

```bash
# bucket
gcloud storage buckets list --filter="name:wiseman-hub*"

# SA
gcloud iam service-accounts list --filter="email:wiseman-hub-*"
```

既に同名リソースがある場合は本手順を中断し、命名衝突の解決方針を協議する。

---

## 🎯 Phase 1: Bucket 作成（5 分）

### 1-1. data bucket（audit / cache 用）

```bash
gcloud storage buckets create gs://wiseman-hub-data-prod \
  --project=wiseman-hub-prod \
  --location=asia-northeast1 \
  --uniform-bucket-level-access \
  --public-access-prevention \
  --default-storage-class=STANDARD
```

検証:
```bash
gcloud storage buckets describe gs://wiseman-hub-data-prod \
  --format="value(iamConfiguration.uniformBucketLevelAccess.enabled,iamConfiguration.publicAccessPrevention)"
# 期待出力: True	enforced
```

### 1-2. release bucket（exe / manifest / SBOM 用）

```bash
gcloud storage buckets create gs://wiseman-hub-release-prod \
  --project=wiseman-hub-prod \
  --location=asia-northeast1 \
  --uniform-bucket-level-access \
  --public-access-prevention \
  --default-storage-class=STANDARD
```

---

## 🎯 Phase 2: Bucket 設定（Versioning / Lifecycle）（5 分）

### 2-1. Object Versioning 有効化（誤削除復旧用）

```bash
gcloud storage buckets update gs://wiseman-hub-data-prod --versioning
gcloud storage buckets update gs://wiseman-hub-release-prod --versioning
```

### 2-2. Lifecycle 設定（data bucket = audit 5 年保持 / cache 90 日）

`/tmp/data-lifecycle.json` を作成（**top-level は `rule` 配列、`lifecycle` wrapper は不要**）:

```json
{
  "rule": [
    {
      "action": {"type": "Delete"},
      "condition": {
        "age": 1825,
        "matchesPrefix": ["audit/"]
      }
    },
    {
      "action": {"type": "Delete"},
      "condition": {
        "age": 90,
        "matchesPrefix": ["cache/"]
      }
    },
    {
      "action": {"type": "Delete"},
      "condition": {
        "age": 30,
        "isLive": false,
        "matchesPrefix": ["cache/"]
      }
    }
  ]
}
```

注意（codex security review 反映）:
- `audit/` の **非現行世代を削除しない**: audit object が誤って上書き / 削除された場合の復旧経路（Versioning）を保つため、`isLive=false` ルールは `cache/` prefix に限定
- audit はファイル名に日付 + sequence を入れて immutable 運用（PR-1 の audit_uploader が冪等化）

適用:
```bash
gcloud storage buckets update gs://wiseman-hub-data-prod \
  --lifecycle-file=/tmp/data-lifecycle.json
```

### 2-3. Lifecycle 設定（release bucket = 古い版を Archive class に移行）

`/tmp/release-lifecycle.json`:

```json
{
  "rule": [
    {
      "action": {"type": "SetStorageClass", "storageClass": "ARCHIVE"},
      "condition": {
        "age": 90,
        "matchesPrefix": ["versions/"]
      }
    },
    {
      "action": {"type": "Delete"},
      "condition": {
        "age": 365,
        "isLive": false
      }
    }
  ]
}
```

注意（codex security review 反映）:
- 「直近 5 版以外を Archive」を **GCS Lifecycle 単独では表現できない**（`numNewerVersions` は Object Versioning の世代向け）
- 上記ルールは `versions/` prefix の object が **作成から 90 日経過したら Archive class に自動移行**するシンプルな時間ベース移行
- 「直近 5 版を Standard で残す」要件は PR-6 の release.yml 内で `gcloud storage objects list versions/` → 5 版より古いものを明示移行 / 削除する後段管理で実現する

適用:
```bash
gcloud storage buckets update gs://wiseman-hub-release-prod \
  --lifecycle-file=/tmp/release-lifecycle.json
```

検証:
```bash
gcloud storage buckets describe gs://wiseman-hub-data-prod --format="json(lifecycle)"
gcloud storage buckets describe gs://wiseman-hub-release-prod --format="json(lifecycle)"
```

---

## 🎯 Phase 3: Service Account 作成（5 分）

### 3-1. Windows runtime SA（実機 wiseman_hub.exe が使用）

```bash
gcloud iam service-accounts create wiseman-hub-windows-runtime \
  --display-name="Wiseman Hub Windows Runtime" \
  --description="Production Windows machine: writes audit/cache to data-prod, reads release-prod"
```

### 3-2. Mac dev SA（開発者の Mac CLI が使用）

```bash
gcloud iam service-accounts create wiseman-hub-mac-dev \
  --display-name="Wiseman Hub Mac Dev" \
  --description="Developer Mac CLI: read-only access to data-prod and release-prod for testing/audit"
```

### 3-3. GHA OIDC SA（GitHub Actions が WIF 経由で使用）

```bash
gcloud iam service-accounts create wiseman-hub-gha-release \
  --display-name="Wiseman Hub GHA Release" \
  --description="GitHub Actions release pipeline: writes to release-prod via Workload Identity Federation"
```

検証:
```bash
gcloud iam service-accounts list --filter="email:wiseman-hub-*"
# 期待: 上記 3 SA が表示される
```

---

## 🎯 Phase 4: Bucket-level IAM バインド（10 分）

ADR-016 の権限マトリクスを **prefix 限定の最小権限** で反映する（codex security review 指摘反映）:

| Bucket | Windows runtime | Mac dev | GHA OIDC |
|--------|----------------|---------|----------|
| `wiseman-hub-data-prod` | objectCreator + objectViewer (audit/, cache/ のみ) | objectViewer | （アクセスなし） |
| `wiseman-hub-release-prod` | objectViewer | objectViewer | objectCreator (versions/, manifests/) + objectViewer |

設計方針:
- `objectAdmin` は bucket 全体の delete + overwrite が可能で、audit / release の改竄経路ができてしまう
- そこで **write 権限は `objectCreator` (PUT のみ、上書き不可)** に絞り、prefix で限定する
- read 権限は `objectViewer` を別途付与（読込は全体に対して許可、PII 影響は限定的）
- `objectCreator` は同じ object 名での再 PUT を 412 Precondition Failed で拒否する仕様も活用可能

### 4-1. data bucket 権限

```bash
# Windows runtime: audit/, cache/ への objectCreator (PUT のみ、上書き不可)
gcloud storage buckets add-iam-policy-binding gs://wiseman-hub-data-prod \
  --member="serviceAccount:wiseman-hub-windows-runtime@wiseman-hub-prod.iam.gserviceaccount.com" \
  --role="roles/storage.objectCreator" \
  --condition="expression=resource.name.startsWith('projects/_/buckets/wiseman-hub-data-prod/objects/audit/') || resource.name.startsWith('projects/_/buckets/wiseman-hub-data-prod/objects/cache/'),title=audit_cache_create_only,description=Limit Windows runtime to audit/ and cache/ creation"

# Windows runtime: 自身が書いた cache を読み戻すための objectViewer (bucket 全体読込)
gcloud storage buckets add-iam-policy-binding gs://wiseman-hub-data-prod \
  --member="serviceAccount:wiseman-hub-windows-runtime@wiseman-hub-prod.iam.gserviceaccount.com" \
  --role="roles/storage.objectViewer"

# Mac dev: bucket 全体 read-only
gcloud storage buckets add-iam-policy-binding gs://wiseman-hub-data-prod \
  --member="serviceAccount:wiseman-hub-mac-dev@wiseman-hub-prod.iam.gserviceaccount.com" \
  --role="roles/storage.objectViewer"

# GHA OIDC: アクセス禁止（バインドしない）
```

注意:
- prefix 限定 IAM Conditions は GCS UBLA 環境でサポートされる（公式 docs 参照）
- audit / cache 以外の prefix（例: 誤った root upload）は 403 で拒否される

### 4-2. release bucket 権限

```bash
# Windows runtime: bucket 全体 objectViewer（exe ダウンロードのみ、改竄不可 = release 改竄経路を遮断）
gcloud storage buckets add-iam-policy-binding gs://wiseman-hub-release-prod \
  --member="serviceAccount:wiseman-hub-windows-runtime@wiseman-hub-prod.iam.gserviceaccount.com" \
  --role="roles/storage.objectViewer"

# Mac dev: bucket 全体 objectViewer（検証用 read-only）
gcloud storage buckets add-iam-policy-binding gs://wiseman-hub-release-prod \
  --member="serviceAccount:wiseman-hub-mac-dev@wiseman-hub-prod.iam.gserviceaccount.com" \
  --role="roles/storage.objectViewer"

# GHA OIDC: versions/, manifest.json, sbom/ への objectCreator (PUT のみ、上書き不可)
gcloud storage buckets add-iam-policy-binding gs://wiseman-hub-release-prod \
  --member="serviceAccount:wiseman-hub-gha-release@wiseman-hub-prod.iam.gserviceaccount.com" \
  --role="roles/storage.objectCreator" \
  --condition="expression=resource.name.startsWith('projects/_/buckets/wiseman-hub-release-prod/objects/versions/') || resource.name.startsWith('projects/_/buckets/wiseman-hub-release-prod/objects/manifests/') || resource.name.startsWith('projects/_/buckets/wiseman-hub-release-prod/objects/sbom/'),title=release_artifacts_create_only,description=Limit GHA to release artifact creation"

# GHA OIDC: 自身が書いた release を読み戻すための objectViewer
gcloud storage buckets add-iam-policy-binding gs://wiseman-hub-release-prod \
  --member="serviceAccount:wiseman-hub-gha-release@wiseman-hub-prod.iam.gserviceaccount.com" \
  --role="roles/storage.objectViewer"
```

注意（manifest 上書き運用）:
- `objectCreator` は同名 object の再 PUT を拒否するため、**manifest.json は世代付きパスで運用**:
  - `manifests/manifest-v1.2.3.json` のように tag 名を含む immutable パス
  - 「現在の最新」を指す symbolic 機能は GCS にないため、release.yml で `manifests/manifest-vX.Y.Z.json` を生成し、launcher 側で「最新 tag をリスト → 一番新しいものを取得」ロジックを持つ
- もし `manifest.json` を単一 path で上書き運用したい場合は、上記 condition から `manifests/` を外し、別途 `manifests/` 専用の `objectAdmin` を bind する 2 段階構成にする。判断は PR-6 設計時に確定する

---

## 🎯 Phase 5: 権限検証（10 分）

**重要（codex security review 反映）**: SA key を一切作らずに `--impersonate-service-account` で検証する。鍵ファイル発行・削除手順のミスで権限ローテーションが壊れるリスクを排除する。

### 5-0. 前提: 運用者ロールに Token Creator が付与されていること

```bash
# 運用者の現在の identity を確認
gcloud auth list --filter=status:ACTIVE --format="value(account)"
# 出力例: sasaki.system0801@gmail.com
```

`Service Account Token Creator` ロールが必要。Phase 0 の前提ロール一覧を参照。

### 5-1. data bucket: Windows runtime として audit/ への write が成功すること

```bash
echo "test-audit-$(date -u +%Y%m%dT%H%M%SZ)" | \
  gcloud storage cp - gs://wiseman-hub-data-prod/audit/test-permcheck.txt \
  --impersonate-service-account=wiseman-hub-windows-runtime@wiseman-hub-prod.iam.gserviceaccount.com
# 期待: 成功（audit/ prefix なので objectCreator condition が通る）
```

### 5-2. data bucket: Windows runtime として **prefix 外（root）への write が失敗すること**

```bash
echo "should-fail" | \
  gcloud storage cp - gs://wiseman-hub-data-prod/forbidden.txt \
  --impersonate-service-account=wiseman-hub-windows-runtime@wiseman-hub-prod.iam.gserviceaccount.com
# 期待: 403 Permission Denied (prefix condition で audit/ と cache/ 以外は拒否)
```

### 5-3. release bucket: Windows runtime として write が **失敗すること**（最重要）

```bash
echo "tampered" | \
  gcloud storage cp - gs://wiseman-hub-release-prod/versions/9.9.9/wiseman_hub.exe \
  --impersonate-service-account=wiseman-hub-windows-runtime@wiseman-hub-prod.iam.gserviceaccount.com
# 期待: 403 Permission Denied (Windows runtime は release-prod に objectViewer のみ)
```

**この検証が成功（403）しなかった場合、IAM 設定にミスがある。Phase 4 をやり直すこと。**

### 5-4. release bucket: GHA OIDC SA として versions/ への write が成功すること

```bash
echo "fake-exe-content" | \
  gcloud storage cp - gs://wiseman-hub-release-prod/versions/0.0.0-test/wiseman_hub.exe \
  --impersonate-service-account=wiseman-hub-gha-release@wiseman-hub-prod.iam.gserviceaccount.com
# 期待: 成功
```

### 5-5. release bucket: GHA OIDC SA として root への write が **失敗すること**

```bash
echo "tampered" | \
  gcloud storage cp - gs://wiseman-hub-release-prod/random.txt \
  --impersonate-service-account=wiseman-hub-gha-release@wiseman-hub-prod.iam.gserviceaccount.com
# 期待: 403 Permission Denied (versions/, manifests/, sbom/ 以外は拒否)
```

### 5-6. テストオブジェクト削除

```bash
gcloud storage rm gs://wiseman-hub-data-prod/audit/test-permcheck.txt
gcloud storage rm gs://wiseman-hub-release-prod/versions/0.0.0-test/wiseman_hub.exe
```

### 5-7. impersonate アクセスログの確認（オプション）

Cloud Audit Logs で `--impersonate-service-account` の使用が記録されている:

```bash
gcloud logging read 'protoPayload.serviceName="iamcredentials.googleapis.com"
  AND protoPayload.methodName="GenerateAccessToken"
  AND protoPayload.request.name=~"wiseman-hub-windows-runtime"' \
  --limit=5 --format="value(timestamp,protoPayload.authenticationInfo.principalEmail)"
```

各検証ステップが運用者 identity 経由で実行されたことが確認できる。

---

## 🎯 Phase 6: 本番運用鍵の発行（オプション）

Windows runtime SA の鍵を実機に配置する場合:

```bash
gcloud iam service-accounts keys create ~/wiseman-hub-windows-runtime-key.json \
  --iam-account=wiseman-hub-windows-runtime@wiseman-hub-prod.iam.gserviceaccount.com
```

**重要（ismap 個人情報運用での必須要件）**:

| 項目 | 要件 |
|------|------|
| **配布経路** | Windows 実機の `$HOME\wiseman-hub\config\sa-key.json` に **手渡し** または対面 USB 経由（メール / Slack / DM 添付禁止） |
| **OS ACL** | NTFS で当該 Windows ユーザー以外は read 不可に設定（PowerShell `icacls` で確認） |
| **保管場所** | `$HOME\wiseman-hub\config\sa-key.json` 1 箇所のみ（コピー禁止） |
| **設定参照** | `default.toml` の `[gcp] service_account_key_path` を更新 |
| **旧鍵処理** | 既存 `sa-key.json` はバックアップ後 24 時間以内に元場所から削除、`gcloud iam service-accounts keys delete` で GCP 側からも失効 |
| **ローテーション** | 90 日に 1 回（最低でも年 1 回）、定期スケジュールで本 Phase 6 を再実行 |
| **棚卸し** | 四半期毎に `gcloud iam service-accounts keys list --filter='keyType:USER_MANAGED'` で発行中の鍵を確認、不要鍵があれば削除 |
| **失効監視** | 鍵漏洩疑いがある場合、GCP コンソールから即時無効化 |
| **組織ポリシー** | 可能なら `constraints/iam.disableServiceAccountKeyCreation` の組織ポリシーを設定して鍵作成を最後の手段化（ただし設定すると Phase 6 が失敗するため、必要時のみ一時解除する運用） |

将来的には WIF 経由（鍵ファイル不要）の構成への移行を検討（ADR-016 Out of Scope）。
Windows 機の WIF impersonation は GitHub Actions 経由ではなく Service Account Identity Token / Federated Credentials の活用が必要で、設計が別 ADR 級の判断になるため次フェーズで扱う。

Mac dev SA の鍵も同様の管理基準に従う（手渡し / OS ACL / 90 日ローテーション）。

---

## ⚠️ rollback 手順

万一の場合、以下のコマンドで完全に元に戻せる:

```bash
# IAM bindings 削除
gcloud storage buckets remove-iam-policy-binding gs://wiseman-hub-data-prod \
  --member="serviceAccount:wiseman-hub-windows-runtime@wiseman-hub-prod.iam.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"
# ... (他の binding も同様)

# SA 削除
gcloud iam service-accounts delete wiseman-hub-windows-runtime@wiseman-hub-prod.iam.gserviceaccount.com --quiet
gcloud iam service-accounts delete wiseman-hub-mac-dev@wiseman-hub-prod.iam.gserviceaccount.com --quiet
gcloud iam service-accounts delete wiseman-hub-gha-release@wiseman-hub-prod.iam.gserviceaccount.com --quiet

# Bucket 削除（中身ごと）
# 注意: gcloud storage rm --recursive gs://bucket は object のみ削除する（bucket 自体は残る）
# gcloud storage rm --recursive --all-versions で全 version を削除
gcloud storage rm --recursive --all-versions gs://wiseman-hub-data-prod
gcloud storage rm --recursive --all-versions gs://wiseman-hub-release-prod

# bucket 削除（空になっていないと失敗するので上記 object 削除を先に実行）
gcloud storage buckets delete gs://wiseman-hub-data-prod
gcloud storage buckets delete gs://wiseman-hub-release-prod
```

---

## 完了確認チェックリスト

- [ ] `wiseman-hub-data-prod` bucket が作成され、UBLA + Versioning + Lifecycle 適用済
- [ ] `wiseman-hub-release-prod` bucket が作成され、UBLA + Versioning + Lifecycle 適用済
- [ ] 3 つの SA が作成済（Windows runtime / Mac dev / GHA OIDC）
- [ ] data bucket: Windows=objectAdmin, Mac=objectViewer, GHA=（なし）
- [ ] release bucket: Windows=objectViewer, Mac=objectViewer, GHA=objectAdmin
- [ ] **Phase 5-3 の改竄テスト（403 拒否）が成功**
- [ ] 検証用 SA キーは削除済

完了後、`workload-identity-federation-setup.md` に進む。
