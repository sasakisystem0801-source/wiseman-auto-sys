# 居宅 → FAX 対照表 GCS 同期 実機検証 runbook

**目的**: Windows 実機で「対照表 → GCP へ送信」「GCP から対照表を取得」ボタンを **1 回でも成功** させるための前提条件・手順・失敗時 rollback を網羅。

**過去失敗対策の反映**:
- ❌ Session 39: SA キー実機未配置で GCP 機能が動かなかった → Phase 0-3 で必須化
- ❌ TOML 手貼りスペース混入 → 機械書き戻しで解消（本機能で対応）
- ❌ PR #169 過剰修正による回帰 → 既存 `_on_save` / `_on_scan_env` を変更しないことを保証
- ❌ PyInstaller hidden import 漏れ → spec に `wiseman_hub.cloud.mapping_sync` + `google.api_core.exceptions` 明示済
- ❌ 外部 API OK でも実態 NG → push 後の閉ループ pull 検証を実装

---

## Phase 0: 前提条件確認（一度切り、必須）

### 0-1. SA キー実機配置

```powershell
# Windows 実機 PowerShell
Test-Path "$HOME\wiseman-hub\config\sa-key.json"
# → True が返ること
```

未配置なら macOS から TeamViewer 経由でファイル転送 or USB 経由で配置。
配置後に **メタフィールドのみ**で確認（秘密鍵本体を画面・録画に出さない、codex review LOW 対応）:

```powershell
Get-Item "$HOME\wiseman-hub\config\sa-key.json" | Format-List Name, Length
$key = Get-Content "$HOME\wiseman-hub\config\sa-key.json" -Raw | ConvertFrom-Json
$key | Select-Object type, project_id, client_email
# 期待:
#   type        : service_account
#   project_id  : wiseman-hub-prod
#   client_email: <SA 名>@wiseman-hub-prod.iam.gserviceaccount.com
# private_key 本文・private_key_id・client_id は表示しない
```

### 0-2. config/default.toml の [gcp] 設定

```powershell
# 配布物の config/default.toml で確認
Get-Content "$HOME\wiseman-hub\config\default.toml" | Select-String -Pattern "project_id|bucket_name|service_account_key_path"
```

期待 3 行:
```
project_id = "wiseman-hub-prod"
bucket_name = "wiseman-hub-prod"
service_account_key_path = "config/sa-key.json"
```

未設定なら設定ダイアログから入力するか、手動で config/default.toml を編集。

### 0-3. SA に必要な GCS 権限を **SA キー本人で** 確認（codex review HIGH-2 対応）

**重要**: 個人アカウントで `gcloud storage ls` しても SA に同等権限あるとは限らない（false positive）。
**必ず SA キーを使った自己確認** を実施する。

#### 方式 A（推奨）: Windows 実機 Python smoke で end-to-end 確認

```powershell
cd $HOME\Projects\wiseman-auto-sys
uv run python scripts/check_gcp_access.py "$HOME\wiseman-hub\config\sa-key.json" wiseman-hub-prod
# 期待出力:
#   [OK] from_service_account_json: <client_email>
#   [OK] bucket exists: wiseman-hub-prod
#   [OK] write smoke: gs://wiseman-hub-prod/mappings/_health-check.json
#   [OK] read smoke: <bytes>
#   [OK] delete smoke: removed
#   ALL GREEN — SA can read/write/delete in mappings/ prefix
```

失敗時の主な原因:
- `[FAIL] from_service_account_json`: SA キー JSON が壊れている → 再配置
- `[FAIL] bucket exists`: bucket 名違い or SA に bucket access なし → IAM 確認
- `[FAIL] write smoke`: `roles/storage.objectCreator` 欠落
- `[FAIL] read smoke`: `roles/storage.objectViewer` 欠落

#### 方式 B（補助）: macOS 側で SA キーを一時 activate して確認

```bash
# 一時的に SA で gcloud を動かし、戻す（個人アカウントの設定は壊さない）
gcloud auth activate-service-account --key-file /tmp/sa-key.json
gcloud storage ls gs://wiseman-hub-prod/ --project=wiseman-hub-prod
echo '{"smoke":"ok"}' | gcloud storage cp - gs://wiseman-hub-prod/mappings/_health-check.json
gcloud storage rm gs://wiseman-hub-prod/mappings/_health-check.json
gcloud config set account YOUR_PERSONAL@gmail.com  # 元アカウントに戻す
```

#### 必要な IAM ロール

GCP Console > IAM で SA `wiseman-hub-runtime@wiseman-hub-prod.iam.gserviceaccount.com`（または現運用の SA）に:
- `roles/storage.objectCreator`（push）
- `roles/storage.objectViewer`（pull）

不足なら `roles/storage.objectAdmin` を一時付与で代替可（本番運用時は最小権限に絞る）。

### 0-4. ネットワーク

```powershell
# Windows 実機からの GCS 疎通確認
Test-NetConnection storage.googleapis.com -Port 443
# → TcpTestSucceeded : True が必要
```

---

## Phase 1: 初回データ投入（macOS から、私が実施）

### 1-1. 対照表 JSON 作成

ユーザー精査済の対照表（HIGH 39 件 + 確定済 MEDIUM/LOW/UNMATCHED）を JSON 化:

```bash
# /tmp/facility-routing-latest.json に書く
cat > /tmp/facility-routing-latest.json <<'EOF'
{
  "version": "1",
  "generated_at": "2026-05-01T20:00:00+09:00",
  "mappings": {
    "ケアプラン太子": "ケアプラン太子（メール）※持参",
    "太子の郷": "太子の郷（FAX）※持参",
    ...
  }
}
EOF
```

### 1-2. GCS に put

```bash
gcloud storage cp /tmp/facility-routing-latest.json \
  gs://wiseman-hub-prod/mappings/facility-routing-latest.json
```

### 1-3. put 結果確認

```bash
gcloud storage cat gs://wiseman-hub-prod/mappings/facility-routing-latest.json | jq '.mappings | length'
# → 件数が想定通りか
```

---

## Phase 2: アプリ再ビルド（Windows 実機 PowerShell）

CLAUDE.md「Windows 実機環境」§最小フル手順 をベースに、warning 検査を強化:

```powershell
# Phase 2-0: リポジトリ最新化
cd $HOME\Projects\wiseman-auto-sys
git fetch origin
git checkout feature/checklist-bc-mvp
git pull --ff-only
git log --oneline -5

# Phase 2-1: 現行 exe バックアップ
$dist = "$HOME\wiseman-hub"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
Copy-Item "$dist\wiseman_hub.exe" "$dist\wiseman_hub.exe.bak-$stamp"

# Phase 2-2: 依存同期 + テスト
uv sync --extra dev
uv run pytest -q -m "not integration"
# → mapping_sync 関連 11 件含む全 PASS を確認

# Phase 2-3: clean ビルド
uv run pyinstaller wiseman_hub.spec --clean --noconfirm 2>&1 | Tee-Object -FilePath build.log

# Phase 2-4: warning 検査（過去 hidden import 漏れ事故防止）
Select-String -Path build.log -Pattern "Hidden import.*not found"
# → 出力された warning が pycparser.lextab / pycparser.yacctab / jinja2 / user32 / msvcrt のいずれかなら無害（無視）。
# wiseman_hub / google.api_core / mapping_sync が出たら進まず共有

# Phase 2-5: 配布
Copy-Item -Force dist\wiseman_hub.exe "$dist\wiseman_hub.exe"
Get-Item "$dist\wiseman_hub.exe" | Format-List Name, Length, LastWriteTime
```

---

## Phase 3: 実機動作確認

### 3-1. アプリ起動

```powershell
Start-Process "$dist\wiseman_hub.exe"
```

期待: コンソール窓が出ずに Launcher「Wiseman PDF ツール」が起動、5 ボタン構成。

### 3-2. 「GCP から対照表を取得」ボタン押下（読み込み確認）

1. Launcher → 設定 → チェックリスト連携設定
2. 設定ダイアログ下段「GCP から対照表を取得」ボタンクリック
3. **期待結果**: messagebox「N 件を取得しました 保存ボタンで永続化してください」
4. Text widget「居宅 → FAX 事業所マッピング」に対照表が反映される（目視確認）

#### 3-2 失敗パターン早見表

| 表示メッセージ | 原因 | 対処 |
|--------------|------|------|
| 「GCP 設定不足」 | bucket_name / project_id / SA キーパス が未入力 | Phase 0-2 を再確認 |
| 「対照表 未登録」（messagebox info） | GCS にまだ JSON がない | Phase 1 (macOS から put) を実施 |
| 「GCP 取得失敗: pull failed: Forbidden」 | SA に `objects.get` 権限なし | Phase 0-3 IAM 確認、不足ロール付与 |
| 「GCP 取得失敗: pull failed: SSLError」 | ネットワーク（プロキシ等） | Phase 0-4 疎通確認 |
| 「GCP 取得失敗: invalid JSON」 | GCS 上の JSON が壊れている | Phase 1 で put し直す |

### 3-3. 「対照表 → GCP へ送信」ボタン押下（書き込み + 閉ループ検証）

1. Text widget で 1 行追加 or 修正（例: 末尾に `"テスト" = "テストFAX"` 追加）
2. 「対照表 → GCP へ送信」ボタンクリック
3. **期待結果**: messagebox「N 件を送信し、読み戻し検証 OK GCS URI: gs://...」
   - 「読み戻し検証 OK」が表示されることが核心（push 200 OK だけでは信用しない）
4. macOS から確認:

```bash
gcloud storage cat gs://wiseman-hub-prod/mappings/facility-routing-latest.json | jq '.mappings | keys'
# → 追加した「テスト」キーが含まれること
```

#### 3-3 失敗パターン早見表

| 表示メッセージ | 原因 | 対処 |
|--------------|------|------|
| 「対照表 解析エラー」 | Text widget の TOML フォーマット不正 | スペース・引用符を確認、`"key" = "value"` 形式厳守 |
| 「対照表 空」 | Text widget が空 | 1 行以上入力 |
| 「GCP 送信失敗: push failed: Forbidden」 | SA に `objects.create` 権限なし | Phase 0-3 IAM 確認 |
| 「送信検証失敗」 | push 後に pull で読めない（権限非対称 / ネットワーク瞬断） | 再試行、永続するなら IAM 確認 |
| 「送信検証 不一致」 | 別ユーザーが並行して上書きしている | 一旦取得してから再送信 |

### 3-4. 「保存」ボタンで TOML 永続化

1. 「保存」ボタンクリック
2. 「設定を保存しました」messagebox
3. config/default.toml の `[checklist.facility_routing]` セクションが更新されたことを確認:

```powershell
Get-Content "$dist\config\default.toml" | Select-String -Pattern "facility_routing" -Context 0, 5
```

### 3-5. B/C ダイアログで対照表が効くか確認

1. Launcher → 「B: 運動機能向上計画書 自動配置」
2. 月選択（例: 26 年 4 月）
3. 「計画」ボタンで row 一覧を表示
4. 対照表に登録されている居宅は `SKIPPED_NO_FACILITY` ではなく `PENDING` 等になることを確認

---

## Phase 4: 失敗時の rollback

### 4-1. exe を前バックアップに戻す

```powershell
$dist = "$HOME\wiseman-hub"
$latest_bak = Get-ChildItem "$dist\wiseman_hub.exe.bak-*" |
  Sort-Object LastWriteTime -Descending | Select-Object -First 1
Copy-Item -Force $latest_bak.FullName "$dist\wiseman_hub.exe"
Write-Host "Restored from: $($latest_bak.Name)"
```

### 4-2. config/default.toml の `facility_routing` を空に戻す

設定ダイアログで Text widget をクリア → 保存。または config/default.toml の `[checklist.facility_routing]` セクションを直接編集して空 dict に。

### 4-3. GCS 上の JSON を削除（誤データを残さない）

```bash
gcloud storage rm gs://wiseman-hub-prod/mappings/facility-routing-latest.json
```

---

## Acceptance Criteria（Phase 3 で全て PASS が条件）

1. ✅ Phase 3-1: アプリ起動成功（ImportError ダイアログが出ない）
2. ✅ Phase 3-2: 「GCP から対照表を取得」で N 件反映、Text widget に居宅 → FAX 対照表が表示
3. ✅ Phase 3-3: 「対照表 → GCP へ送信」で「読み戻し検証 OK」表示
4. ✅ Phase 3-4: 「保存」で config/default.toml が更新
5. ✅ Phase 3-5: B ダイアログで対照表が反映され、`SKIPPED_NO_FACILITY` が減少

5 つ全て満たせば **「Windows 実機で 1 回成功」**。
