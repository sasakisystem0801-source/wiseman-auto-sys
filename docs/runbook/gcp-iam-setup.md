# GCP IAM セットアップ手順書（ADR-016 PR-5）

**目的**: ADR-016 の Bucket 分離 + IAM 最小権限を実機の GCP 環境に反映する。本手順は本田様（運用責任者）または開発者が GCP コンソール / `gcloud` CLI で **1 度だけ** 実行する。

**前提条件**:
- GCP プロジェクト: `wiseman-hub-prod` が既存（ADR-003 で決定済）
- リージョン: `asia-northeast1`（東京、APPI / ismap 準拠）
- 実行者: `Project Owner` または `Storage Admin` + `Service Account Admin` ロールを持つアカウント
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

`/tmp/data-lifecycle.json` を作成:

```json
{
  "lifecycle": {
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
          "isLive": false
        }
      }
    ]
  }
}
```

適用:
```bash
gcloud storage buckets update gs://wiseman-hub-data-prod \
  --lifecycle-file=/tmp/data-lifecycle.json
```

### 2-3. Lifecycle 設定（release bucket = 直近 5 版以外を Archive class に移行）

`/tmp/release-lifecycle.json`:

```json
{
  "lifecycle": {
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
}
```

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

ADR-016 の権限マトリクスを正確に反映する:

| Bucket | Windows runtime | Mac dev | GHA OIDC |
|--------|----------------|---------|----------|
| `wiseman-hub-data-prod` | objectAdmin | objectViewer | （アクセスなし） |
| `wiseman-hub-release-prod` | objectViewer | objectViewer | objectAdmin |

### 4-1. data bucket 権限

```bash
# Windows runtime: objectAdmin（audit/cache write が必要）
gcloud storage buckets add-iam-policy-binding gs://wiseman-hub-data-prod \
  --member="serviceAccount:wiseman-hub-windows-runtime@wiseman-hub-prod.iam.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"

# Mac dev: objectViewer（read-only）
gcloud storage buckets add-iam-policy-binding gs://wiseman-hub-data-prod \
  --member="serviceAccount:wiseman-hub-mac-dev@wiseman-hub-prod.iam.gserviceaccount.com" \
  --role="roles/storage.objectViewer"

# GHA OIDC: アクセス禁止（バインドしない）
```

### 4-2. release bucket 権限

```bash
# Windows runtime: objectViewer（exe ダウンロードのみ、改竄不可）
gcloud storage buckets add-iam-policy-binding gs://wiseman-hub-release-prod \
  --member="serviceAccount:wiseman-hub-windows-runtime@wiseman-hub-prod.iam.gserviceaccount.com" \
  --role="roles/storage.objectViewer"

# Mac dev: objectViewer（検証用 read-only）
gcloud storage buckets add-iam-policy-binding gs://wiseman-hub-release-prod \
  --member="serviceAccount:wiseman-hub-mac-dev@wiseman-hub-prod.iam.gserviceaccount.com" \
  --role="roles/storage.objectViewer"

# GHA OIDC: objectAdmin（exe + manifest + SBOM upload）
gcloud storage buckets add-iam-policy-binding gs://wiseman-hub-release-prod \
  --member="serviceAccount:wiseman-hub-gha-release@wiseman-hub-prod.iam.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"
```

### 4-3. オプション: prefix 単位 IAM Conditions（強化セキュリティ）

「Windows runtime は data-prod の `audit/` と `cache/` だけに write 可」を厳密にする場合:

```bash
# 上記 4-1 のシンプルな objectAdmin の代わりに、condition 付きで bind:
gcloud storage buckets add-iam-policy-binding gs://wiseman-hub-data-prod \
  --member="serviceAccount:wiseman-hub-windows-runtime@wiseman-hub-prod.iam.gserviceaccount.com" \
  --role="roles/storage.objectAdmin" \
  --condition="expression=resource.name.startsWith('projects/_/buckets/wiseman-hub-data-prod/objects/audit/') || resource.name.startsWith('projects/_/buckets/wiseman-hub-data-prod/objects/cache/'),title=audit_cache_only"
```

注意: condition 付き IAM は学習コストが高いため、**初回は 4-1 のシンプル版で運用**し、運用が安定してから condition 化する 2 段階導入を推奨。

---

## 🎯 Phase 5: 権限検証（10 分）

### 5-1. Windows runtime SA の鍵を一時生成（検証専用）

```bash
gcloud iam service-accounts keys create /tmp/test-windows-runtime.json \
  --iam-account=wiseman-hub-windows-runtime@wiseman-hub-prod.iam.gserviceaccount.com
```

### 5-2. data bucket への write が成功すること

```bash
gcloud auth activate-service-account --key-file=/tmp/test-windows-runtime.json
echo "test" | gcloud storage cp - gs://wiseman-hub-data-prod/audit/test.txt
# 期待: 成功
```

### 5-3. release bucket への write が **失敗すること**（最重要）

```bash
echo "tampered" | gcloud storage cp - gs://wiseman-hub-release-prod/manifest.json
# 期待: 403 Permission Denied (Windows runtime は release-prod に objectViewer のみ)
```

**この検証が成功（403）しなかった場合、IAM 設定にミスがある。Phase 4 をやり直すこと。**

### 5-4. テスト鍵を削除（必須）

```bash
# キーローテーション: 検証で生成した鍵を即座に削除
KEY_ID=$(gcloud iam service-accounts keys list \
  --iam-account=wiseman-hub-windows-runtime@wiseman-hub-prod.iam.gserviceaccount.com \
  --filter="keyType:USER_MANAGED" \
  --format="value(name)" | head -1)
gcloud iam service-accounts keys delete $KEY_ID \
  --iam-account=wiseman-hub-windows-runtime@wiseman-hub-prod.iam.gserviceaccount.com \
  --quiet

rm /tmp/test-windows-runtime.json

# 元のアカウントに戻す
gcloud auth login
gcloud config set account sasaki.system0801@gmail.com
```

### 5-5. テストオブジェクト削除

```bash
gcloud storage rm gs://wiseman-hub-data-prod/audit/test.txt
```

---

## 🎯 Phase 6: 本番運用鍵の発行（オプション）

Windows runtime SA の鍵を実機に配置する場合:

```bash
gcloud iam service-accounts keys create ~/wiseman-hub-windows-runtime-key.json \
  --iam-account=wiseman-hub-windows-runtime@wiseman-hub-prod.iam.gserviceaccount.com
```

**重要**:
- この鍵ファイルを Windows 実機の `$HOME\wiseman-hub\config\sa-key.json` に **手渡し** で配置（メール / Slack 添付禁止）
- `default.toml` の `[gcp] service_account_key_path` を更新
- 旧 SA キー（既存 `sa-key.json`）はバックアップ後に削除
- キー漏洩リスクを避けるため、可能なら **WIF 経由 + 鍵ファイル不要** の構成を将来検討（ADR-016 Out of Scope）

Mac dev SA の鍵も同様に発行・配置。

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
gcloud storage rm --recursive gs://wiseman-hub-data-prod
gcloud storage rm --recursive gs://wiseman-hub-release-prod
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
