# ADR-016: Windows アプライアンス化 + Mac-from-GCP 開発フロー

## Status
Proposed (2026-05-06)

## Context

C 経過報告書自動配置（PR #172 ～ #194）の運用検証で、現状アーキテクチャの
スケーラビリティ限界が顕在化した:

1. **dev/test が Windows GUI に縛られる**: dry-run 機能が GUI のみ（PR #192）
   で、検証のたび TeamViewer 越しに業務責任者の PC を借りる必要があった。
   PR #195 で Mac CLI 化したが、これは局所対応にすぎない。

2. **保守・診断が PowerShell 依存**: audit log / xlsx_path_cache が Windows
   ローカルのみで、Mac から状態確認するたび PowerShell コマンドを業務責任者に
   実行してもらう必要があった（2026-05-06 セッション中も発生）。

3. **アップデートが手動 PowerShell runbook**: ADR-004（GCS manifest polling 自動更新）は
   2026-03-22 に Accepted されたが `src/wiseman_hub/updater/` は `__init__.py`
   のみの空スタブで実装ゼロ。実機反映は `docs/handoff/1c-exe-redistribution-runbook.md`
   の手動 PowerShell 5 コマンドに依存している。

4. **業務責任者は PowerShell リテラシー無し**: 現状は開発者の TeamViewer
   立ち会い前提で、属人性が高い。

ユーザー（本田様）からの明示要求（2026-05-06）:

> 現場の運用では、やはりWindowsのデスクトップアプリは使います。
> 開発とテストはMacからのGCP経由でしたいです。
> 理想は、Windows側でなるべくはPowerShellを使わなくても、開発や保守メンテナンス
> やアップデートやテストなどが出来ることです。

加えて codex セカンドオピニオン（threadId: `019dfb0a-d658-7c42-a957-ea2c6a26dd4f`）で
以下の Critical 指摘を受けた:

- C-1. release 用 GCS と業務データ用 GCS は IAM を分けるべき
- C-2. updater は「アプリ本体内蔵」より「小さな bootstrapper / updater 分離」が強い
- C-3. checksum だけでは supply-chain 保護として弱い（OIDC + provenance 必須）
- C-4. 個人情報を含む audit/cache の GCS 保持設計が ADR に必要

## Decision

Windows を「実行専用アプライアンス」として位置づけ、開発・テスト・保守・
アップデートのオペレーションを Mac + GCP + GitHub に分離する。
ADR-004 の高位決定（GCS manifest polling）は継承し、実装設計を本 ADR で置換する。

### 役割分担

| 層 | 役割 | 主な操作面 |
|----|------|-----------|
| **Windows 実機** | 業務本番実行（Wiseman GUI / Excel COM / NAS 書込） | `wiseman_hub.exe` GUI のみ |
| **Mac (開発者)** | 契約テスト、schema 検証、dry-run、audit 分析 | CLI + `gsutil` |
| **GitHub** | source-of-truth、build pipeline、release 発行 | PR / tag |
| **GCP (data hub)** | audit / cache の共有、release 配布、spreadsheet | GCS / Drive |

PowerShell は **disaster recovery 専用**となり、日常運用から外れる。

### コンポーネント

```
┌─ GCP wiseman-hub-prod ──────────────────────────────────┐
│                                                          │
│  ┌─ wiseman-hub-data-prod ─┐  ┌─ wiseman-hub-release-prod ─┐│
│  │ audit/{date}/*.jsonl    │  │ versions/X.Y.Z/             ││
│  │ cache/xlsx_path/*.json  │  │   wiseman_hub.exe           ││
│  │                         │  │   wiseman_hub.exe.sha256    ││
│  │ Windows: write          │  │ manifest.json               ││
│  │ Mac:     read-only      │  │ Windows: read-only          ││
│  │ GHA:     no-access      │  │ GHA(OIDC): write only       ││
│  └─────────────────────────┘  └─────────────────────────────┘│
│                                                              │
│  Drive: spreadsheet (既存、変更なし)                          │
└──────┬─────────────────────────────────┬─────────────────────┘
       │                                 │
       │ read-only                       │ read-only
       ↓                                 ↓
  ┌─Mac (契約テスト) ──┐    ┌─Windows 実機 (appliance) ──┐
  │ scripts/CLI         │    │ wiseman_launcher.exe        │
  │  - dry-run          │    │  ├ manifest poll            │
  │  - audit 分析       │    │  ├ checksum 検証            │
  │  - schema 検証      │    │  ├ provenance 検証          │
  │ gsutil              │    │  ├ versions/X.Y.Z/ ダウンロード│
  └─────────────────────┘    │  ├ current.json 切替        │
                              │  └ wiseman_hub.exe spawn    │
                              │                              │
                              │ wiseman_hub.exe (本体)       │
                              │  ├ 業務 GUI                 │
                              │  ├ audit → spool → GCS     │
                              │  └ cache → GCS mirror       │
                              └──────────────────────────────┘
```

### Critical 設計ポイント

#### 1. GCS bucket と IAM の分離（codex C-1）

| Bucket | 内容 | Windows SA | Mac dev SA | GHA OIDC |
|--------|------|-----------|------------|----------|
| `wiseman-hub-data-prod` | audit, cache, 利用者別状態 | objectAdmin | objectViewer | (no access) |
| `wiseman-hub-release-prod` | manifest, versions/, sha256, sbom | objectViewer | objectViewer | objectAdmin（OIDC短期） |

- Uniform bucket-level access、Object Versioning、Lifecycle、Retention を明示
- Windows SA キーが万一漏洩しても **release 改竄経路を遮断**
- prefix 単位 IAM Conditions も検討（audit/ への write のみ許可）

#### 1.1 release-prod bucket の auth 方式（PR-3 で確定、2026-05-06）

PR-3 (`wiseman_launcher` skeleton) 着手時の codex セカンドオピニオンを受けて、
release-prod bucket の auth 方式を以下のとおり確定する:

- `wiseman-hub-release-prod` は **public read** 前提とする
  （manifest.json + versions/ + sbom + provenance すべて公開可能なメタデータ）
- launcher は SA key を embed しない（後述の launcher 実装制約に直結）
- `wiseman-hub-data-prod` は **private 維持**（業務 PII / audit / cache）
- supply-chain 改竄防止は **SHA-256 + provenance** で担保（ADR-016 §3 参照）
- 公開 bucket だが書込権限は **GHA OIDC のみ**（Windows runtime / Mac dev / 一般 IAM 全て read-only）

launcher 側の実装制約（ADR-016 PR-3 で導入、PR-6 後半で §1.1.3 例外追加）:

- launcher 実コード行数 < 300 行（cloc 計測、空行/コメント/test 除外） →
  PR-3〜PR-6 で責務分割 + sigstore-python 統合、§1.2 で階層構造での上限管理に移行
- launcher runtime package は **stdlib only**（`urllib.request` + `hashlib` + `json` +
  `pathlib` + `datetime` + `argparse` + `logging` + `dataclasses` + `hmac` + `os` +
  `tempfile` のみ）→ **§1.1.3 で sigstore のみ例外として許可** (PR-6 後半)
- launcher は `wiseman_hub.*` を **import しない**（完全独立 package、import graph 最小）

trade-off:

- ✅ launcher が stdlib only で完結、依存が urllib.request のみ
- ✅ SA key 漏洩リスクゼロ（key 自体が存在しない）
- ✅ 配布 exe size を最小化（PyInstaller bundle が google-cloud-storage / requests 等を
  含まない）
- ⚠️ manifest URL を知れば誰でも参照可能（ただし内容は公開可能な exe メタデータのみ）
- ⚠️ download tracking ができない（access log は GCS audit log で代替可能）

別案（採用しない）:

- **SA key embed**: 配布 exe に key 同梱は漏洩リスクが高く、key rotation も困難
- **gsutil / google-cloud-storage embed**: launcher が肥大化し、stdlib only / 300 行制約と矛盾
- **GHA OIDC を runtime でも使う**: launcher は CI ではなく end-user 機で動くため OIDC 不可

参考: codex セカンドオピニオン threadId（PR-3 着手時）と本文書 §2 「launcher 自身の更新方針」

##### 1.1.1 真正性ベースの supply-chain 防御（PR-3 codex review 反映）

PR-3 のセカンドオピニオン（codex threadId 019dfce6）で追加判明した運用前提を明記する:

public read を採用するということは、**秘匿** ではなく **真正性** で改竄から守る方針となる:

- **SHA-256 単独では不十分**: manifest 改竄 + artifact 改竄を同時にされたら検知不能
- **provenance 検証で以下を必ず pin する**（PR-6 で本実装）:
  - `expected_repo` = "sasakisystem0801-source/wiseman-auto-sys"
  - `expected_workflow_ref` = ".github/workflows/release.yml@refs/heads/main"
  - `expected_commit_sha` = manifest.commit_sha と一致
  - `expected_issuer` = "https://token.actions.githubusercontent.com"
- これにより GitHub OIDC + provenance attestation で改竄経路を完全に封じる
- PR-3 では `verify_provenance` の signature を上記 pin 引数で固定（PR-6 への breaking change を回避）

##### 1.1.2 download tracking の制約

public bucket では individual end-user の download log が GCS access log で取得困難:

- 一般 public read の identity は粗い（IP / region のみ、user 識別不可）
- 個別端末の配布確認は **別系統** で実施:
  - `current.json` の version 情報 + 起動時の audit ping（PR-1 audit_uploader 経由）
  - 業務責任者 PC のみが対象なので、別系統 telemetry の精度は粗くて十分

##### 1.1.3 sigstore-python 例外 (PR-6 後半で追加)

§1.1 stdlib only 制約の **唯一の例外**として `sigstore-python` (>=3.0,<4.0) を許可する。
§1.1.1 で「秘匿でなく真正性で守る」方針とした以上、Sigstore Bundle 検証は真正性ベース
supply-chain 防御の本丸であり stdlib only では実装不可なため。

**配布サイズ影響**: PyInstaller bundle が +20-30 MB 程度増加。本田様 PC 1 台運用で
無視可能。

**TUF trusted root の運用**:
- `Verifier.production()` 内で Sigstore TUF repository から root metadata を online refresh
- offline 時 / refresh 失敗時は同梱 cache (sigstore-python 公式 root) で fallback
- cache 期限切れ + offline で fail-close (起動拒否)

**system clock sanity check** (`_supply_chain/sigstore.py` の `_verify_system_clock`):
- launcher 起動時に system clock が UTC 基準で 2026-01-01〜2030-12-31 の範囲か検証
- 大幅ズレ時は `SigstoreVerifyError` raise

**他依存追加の禁止**: sigstore 以外の non-stdlib 依存追加は引き続き **禁止**。新規依存
追加が必要な場合は本 §1.1.3 を更新する PR を必ず分離する。

**例外を採らない別案 (採用しない)**:
- sigstore CLI subprocess 呼出: PyInstaller bundle に sigstore CLI binary 同梱が必要で逆に肥大化
- 純 Python verifier 自作: cert chain / Rekor / TUF を自作するのは現実的でない
- vendored sigstore: maintenance burden が大きい、security update を逃すリスク

参考: PR-6 後半 codex 計画レビュー threadId 019e010b (Critical 3 件のうち C3 反映)

#### 1.2 launcher 行数制約の運用定義（PR-3 codex review 反映、PR-6a で 3 階層化）

PR-3 着手時 codex review (threadId 019dfce6) で確定。300 LOC 制約は **runtime critical path** に
対するもの。validation や error message を削るのは supply-chain 防御の毀損となるため、
責務分割後は対称的 subpackage 構造で制約値を再設計する（codex Critical C-3 反映、threadId 019dfd9e）。

##### PR-6a 改訂後の 3 階層制約（codex C-3 反映）

PR-4 までは launcher 全体合算で 900 LOC を最終ラインとしていたが、provenance verify 本実装 +
review_team Important 反映で 1100+ LOC が見込まれたため、**単純再緩和ではなく責務分割後の
metric 再設計** で対応する。

| 区分 | 対象 | 上限 (実測 PR-7 末) |
|------|------|---------------------|
| **launcher core** | `__main__.py`, `manifest.py`, `checksum.py`, `current.py`, `updater.py` (orchestration only) | **900 LOC** (実測 701、PR-6a 末 711 → PR-7 で `assert isinstance` 撤廃 -10) |
| **`_runtime/` subpackage** | `lock.py` + `spawn.py` + `_atomic_io.py` + `__init__.py` (lock + heartbeat + spawn + SpawnOutcome + atomic IO helper) | **250 LOC** (実測 227、PR-6a 末 189 → PR-7 で `_atomic_io.py` 新規 +38) |
| **`_supply_chain/` subpackage** | `download.py` + `provenance.py` + `policy.py` + `_http.py` + `sigstore.py` + `__init__.py` (artifact download + claims verify + canonical URL policy + HTTPS GET helper + sigstore signature verify) | **530 LOC** (実測 514、計画 350 → 380 → 410 → 415 → 530、PR-6a 内で 2 段階 + PR-7 で 1 段階 + PR-6 後半で 1 段階 fine-tuning) |
| **各 module 単体** | 上記すべて | **270 LOC** (実測最大 262 = `__main__.py`、PR-6 後半末も維持) |
| **対象外** | `__init__.py` (version 文字列のみ)、test files、PyInstaller spec | 制約なし |

##### LOC 段階緩和の歴史（記録、再緩和不可）

| PR | 上限 (合算) | 実測 | 主要追加 |
|----|------------|------|---------|
| PR-3 | 400 | 389 | path traversal 防御 + HTTPS pin + DoS cap |
| PR-4 計画段階 | 700 | 782 | C-1/C-2/C-4/I-1/I-2/I-3/I-5 反映 |
| PR-4 PR 段階 | 800 | 842 | lock heartbeat + canary current_path + redirect 検証 + dir fsync |
| **PR-6a step 1** | 3 階層初期設計（合算 1530 LOC、core 900 + `_runtime/` 250 + `_supply_chain/` 380） | 1272 | provenance 本実装 + module 分割 + 二重 gate + LockHeartbeat ctx mgr |
| **PR-6a step 3** (PR review 反映後) | `_supply_chain/` 380 → **410 LOC** に fine-tuning（合算 1560） | **1321** | Critical 10 件反映 (urlparse 厳格化 + DSSE payloadType + bypass log + subject malformed fail-fast 等) |
| **PR-7** | `_supply_chain/` 410 → **415 LOC** に 1 段階 fine-tuning（合算 1565、`_runtime/` 250 / core 900 維持） | **1365** (core 725 / `_runtime/` 227 / `_supply_chain/` 413、PR codex review label 引数追加 + 失敗 phase log + validate_manifest 戻り値 test 反映後) | HTTPS GET helper (`_supply_chain/_http.py` +60) + atomic write helper (`_runtime/_atomic_io.py` +38) DRY 化、ManifestData TypedDict narrow (assert isinstance 撤廃)、predicate malformed/uppercase digest/integration test (+10 件)、phase log fingerprint (success+失敗両 path)、download label 引数 (artifact/provenance triage 区別)、`_supply_chain/sigstore.py` 切り出し計画明示 |
| **PR-6 後半** | `_supply_chain/` 415 → **530 LOC** に 1 段階 fine-tuning（合算 1680、`_runtime/` 250 / core 900 維持、各 module 単体 ≤ 270 厳守） | **1438** (core 697 / `_runtime/` 227 / `_supply_chain/` 514、sigstore-python 統合 + bypass 経路完全削除 + ProvenanceUnavailable 削除 + signature 検証本実装 反映後) | `_supply_chain/sigstore.py` 新規 (+92 LOC、`Verifier.verify_dsse` 委譲 + Identity 完全一致 `refs/tags/v{version}` + system clock sanity check)、`provenance.verify_provenance` 引数追加 (`expected_version`)、`policy.is_test_bypass_authorized` 削除、`__main__.py --allow-test-unsigned-provenance` flag 削除、`updater.allow_unsigned_provenance` 引数削除。各 module 単体は最大 200 LOC (provenance.py) で 270 上限内、container 上限のみ 415→530 fine-tuning |

##### PR-6 後半 `_supply_chain/sigstore.py` 切り出し実装結果 (本 PR 反映)

PR-7 末で計画した sigstore.py 切り出しを実施したが、sigstore-python の cert chain /
Rekor inclusion proof / TUF trusted root refresh を委譲する glue + Identity policy 構築 +
system clock sanity check で **+92 LOC** が必要となり、`_supply_chain/` 全体は
411 → 514 LOC へ拡大した (計画 415 → 530 に fine-tuning)。

| 実装項目 | 実測 LOC | 配置先 |
|------------|---------|-------|
| `Bundle.from_json` + `Verifier.production()` + `verify_dsse` 委譲 + 例外正規化 | 92 | `_supply_chain/sigstore.py` (新規) |
| `provenance.verify_provenance` の sigstore.verify_dsse_bundle 呼出経路 | (既存 + 微増) | `provenance.py` 200 LOC |
| `policy.is_test_bypass_authorized` 削除 | -16 | `policy.py` 34 LOC |

**LOC 制約の追加 fine-tuning 根拠** (codex C3 反映):
- 当初計画 (PR-7 末) では sigstore.py を 80 LOC 程度に収める想定だったが、TUF 関連の
  例外 wrap + Identity policy 構築 + system clock 検証の glue で +12 LOC 増
- bypass 経路削除で `provenance.py` の縮小は限定的 (約 -20 LOC)、`policy.py` の縮小も
  約 -16 LOC で、container 全体では sigstore.py +92 が支配的
- 各 module 単体は 270 LOC 上限を維持 (provenance.py 200 / sigstore.py 92 / download.py 115 /
  _http.py 60 / policy.py 34)
- これ以降の `_supply_chain/` 拡張は **責務分割** (新 module 切り出し) でのみ許容、
  container 上限の単純再緩和は不可 (Session 47 末方針継承)

##### 制約再設計の根拠（codex C-3 反映、Session 47 末「再緩和不可」と整合）

- **単純再緩和の禁止**: 900 LOC 合算で再緩和は Session 47 末方針との正面衝突 → governance 破り
- **責務分割後の対称構造**: `_runtime/` (process 制御) と `_supply_chain/` (真正性検証) を
  独立 subpackage 化し、それぞれに独立した上限を設定。core は orchestration のみに専念
- **fine-tuning vs 再緩和の境界**: `_supply_chain/` 制約を 350 → 380 → 410 → 415 に 3 段階 fine-tuning。
  - **350 → 380** (step 1): provenance 検証本実装で 22 LOC 超過した実測値に応じた**責務分割後の初期 sizing 補正**
  - **380 → 410** (step 3): PR review 反映で Critical 10 件追加 (urlparse 厳格化 / DSSE payloadType 検証 /
    bypass log 強化 / subject malformed fail-fast 等)、いずれも **security gain** に対応した自然な増加であり
    「validation 削減サイン」ではない (codex C-3 への合意点)
  - **410 → 415** (PR-7 step): HTTPS GET DRY 化 helper (`_supply_chain/_http.py` +60 LOC) を新規追加し、
    `download._open_https_get` (-38 LOC) を helper 呼び出しに置換。
    `_atomic_place` (-50 LOC) は `_runtime/_atomic_io.py` (`_runtime/` subpackage) に集約され
    `_supply_chain/` から完全に転出した (= `_supply_chain/` 内の差分計算では二重計上不可)。
    `_supply_chain/` 内 net = +60 (`_http.py`) -38 (`_open_https_get`) -50 (`_atomic_place` 転出) = -28 LOC
    だが、PR-6a step 3 末の実測 408 → PR-7 末 411 = +3 LOC（差分は subdir 集計時の `__init__.py` 再 export と
    docstring 増加、policy.py の hash 検証コメント拡張等の累積で発生）。HTTPS pin + redirect downgrade 防御の
    **中央化による security 一貫性 gain** であり「validation 削減」ではなく「責務分離」の自然結果。
    PR-6 後半 sigstore-python 統合で `_supply_chain/sigstore.py` 内からも `_http.py` を再利用予定
    (重複再発を構造的に防止)
  - 今後 PR-6 後半で 415 LOC を超えそうなら **`_supply_chain/sigstore.py` 切り出しを強制** (Session 47 末
    「再緩和不可」精神の継承、責務分割を fine-tuning の上限とする)

##### Stop-the-line 条件 (PR-6a で追加、codex Important I-1 反映)

PR-6a は signature 検証 stub のため、本番配布 artifact では `--allow-test-unsigned-provenance` flag
+ 環境変数 `WISEMAN_ALLOW_UNSIGNED_PROVENANCE_FOR_TESTS=1` の AND 条件で stub を bypass 可。
**本番 PC では env 不在で必ず fail-close** だが、この中継状態の半恒久化を防ぐため:

- **Phase 6 (結合テスト + canary 切替) 進入禁止**: PR-6 後半 (release workflow + sigstore-python
  統合 + signature 検証本実装) マージまで Phase 6 に進まない
- **業務全件配置 (Phase 7) 禁止**: `--allow-test-unsigned-provenance` flag が launcher CLI から
  削除されない限り Phase 7 着手禁止 (canary 検証で削除確認後のみ)

##### 計測法 (C9 反映、code-reviewer の rating 92 指摘)

LOC 値は **`uvx pygount` の `Code` 列**（空行 / コメント / docstring を **除外**した実コード行数）。
ファイル全体の `wc -l` 値とは大きく乖離する（PR-6a 末で `wc -l` 合算 ~2000 vs `Code` 合算 1281）。
PR body / ADR の数値は常に `Code` 列で記載し、混同を避けるため計測コマンドを併記する。

##### 行数監視

- 各 PR で以下 2 つを PR body に記載:
  - 合算: `uvx pygount src/wiseman_hub_launcher --format=summary` の `Code` 列
  - subpackage 個別: `uvx pygount src/wiseman_hub_launcher/{_runtime,_supply_chain} --format=summary` の `Code` 列
- いずれかの上限超過時は「責務分割後の構造から逸脱している signal」として module 再分割
  (例: `_supply_chain/sigstore.py` 切り出し) を強制 (再緩和不可)

#### 2. Bootstrapper / updater 分離（codex C-2）

```
$HOME\wiseman-hub\
├── wiseman_launcher.exe     # 固定（更新対象外、外側 1 回だけ配布）
├── current.json              # { "version": "1.2.3", "released_at": "..." }
├── versions\
│   ├── 1.2.2\
│   │   ├── wiseman_hub.exe
│   │   └── manifest.json
│   └── 1.2.3\
│       ├── wiseman_hub.exe
│       └── manifest.json
├── config\
│   └── default.toml
├── cache\
└── spool\
    └── audit\               # GCS 障害時の retry queue
```

起動フロー:
1. `wiseman_launcher.exe` が `current.json` を読み込み
2. GCS `manifest.json` を取得 → semver 比較
3. 新版あり → `versions/X.Y.Z/wiseman_hub.exe` を download
4. SHA256 + provenance 検証
5. 検証 OK → `current.json` を切替（atomic write）
6. `versions/{current}/wiseman_hub.exe` を spawn
7. **起動失敗（exit code != 0、または起動後 30 秒以内 crash）→ 自動 rollback**
   `current.json` を前版に戻し、再 spawn

特性:
- 実行中 exe ロック / SmartScreen / EDR 干渉を回避（exe 置換ではなく参照切替）
- rollback がファイル操作 1 つで完結
- launcher 本体のバグは自動更新できない（次節で扱う）

launcher 自身の更新方針:

- launcher は **極力小さく保つ**（manifest poll + checksum + spawn のみ、§1.2 の LOC 表参照）
- 更新は **年 1-2 回程度** を想定、PowerShell runbook で対応（disaster recovery 経路と共有）
- 「launcher の launcher」化は無限後退になるので採用しない
- launcher 更新が頻繁に必要になったら、それは **launcher が肥大化している signal** であり、
  アーキテクチャ見直しの契機とする

##### 2.1 PR-6a 成果物の本番配布禁止ゲート（PR-4 codex C-3 + PR-6a codex C-2 反映）

PR-4 codex review (threadId 019dfd43, C-3) と PR-6a codex review (threadId 019dfd9e, C-2) で確定。

**段階的 fail-closed 強化の歴史**:

| Phase | 検証範囲 | 配布許可条件 |
|-------|---------|-------------|
| **PR-4** | SHA-256 のみ (provenance 未実装) | `--allow-insecure-checksum-only` flag 単独で bypass、本番配布絶対禁止 |
| **PR-6a** | SHA-256 + SLSA v1.0 statement claims (subject digest + name + multi-subject 一意性 + predicateType + workflow ref + repo + builder id allowlist) | `--allow-test-unsigned-provenance` flag + 環境変数 `WISEMAN_ALLOW_UNSIGNED_PROVENANCE_FOR_TESTS=1` の **AND 二重 gate**、本番 PC では env 不在で必ず fail-close |
| **PR-6 後半 (本 PR)** | 上記 + **Sigstore Bundle v0.3 署名検証 (sigstore-python `Verifier.verify_dsse` 委譲)** + identity 完全一致 (`refs/tags/v{version}`) | **flag + env var 完全除去**、本格 fail-closed (本番 + test 環境共に同一 path で signature 検証必須、bypass 経路自体が存在しない) |

**PR-6a 実装上の安全装置 (codex Critical C-2 反映)**:

- `--update` / `--update --no-spawn` のいずれも provenance verify 経由（claims 不一致は `EXIT_PROVENANCE = 9`）
- signature 検証は stub interface (`ProvenanceUnavailable` raise)、bypass には CLI flag + env var の AND 必須
- `--dry-run` のみ provenance 検証経路を呼ばない (read-only、副作用ゼロ)
- 本番 PC (PyInstaller `wiseman_launcher.exe`) では環境変数を埋め込まないため、CLI flag を渡されても fail-close
- `--allow-test-unsigned-provenance` flag 名は migration audit で grep 容易（PR-6 後半で完全除去）

**PR-6a の制約条件 (codex Important I-1 反映)**:

- canary / 業務責任者 PC への **配布は依然禁止** (signature 未検証のため)
- Phase 6 結合テスト進入禁止 (PR-6 後半マージまで)
- Phase 7 業務全件配置禁止 (`--allow-test-unsigned-provenance` flag が CLI から削除されない限り)

**PR-6a で許可される操作**:

- Mac dev 環境 / smoke build / unit test では env var + flag を併用して動作確認可能
- canary build (artifact preview) の生成と検証は可能、ただし本番 PC への配置は不可

##### 2.2 初回配置時の seed 必須（PR-4 codex review 反映）

PR-4 codex review (threadId 019dfd43, C-4 反映) で確定:

`current.json` の `version="0.0.0"` は manifest 比較で常に小さくなる初期値だが、
spawn 時 rollback 不能（`versions/0.0.0/wiseman_hub.exe` が存在しないため）。

業務責任者 PC への初期配置 runbook (`docs/runbook/`) には、以下を必須として記載:

- `versions/{初期版}/wiseman_hub.exe` を seed として手動配置
- `current.json` を `{version: "{初期版}", previous_version: "", released_at: ...}` で初期化
- launcher 起動時の preflight が `versions/{current.version}/wiseman_hub.exe` の存在を検証
- preflight 失敗時は exit code 6 (ROLLBACK_UNAVAILABLE) + 業務責任者向け人間可読メッセージ

PR-4 では preflight check 実装のみ、runbook 改訂は PR-5 改訂タスクとして次セッション以降。

「PowerShell ゼロ」の運用解釈:

| 運用区分 | PowerShell 使用 | 想定頻度 |
|---------|----------------|---------|
| **日常運用**（業務責任者の毎日の操作） | **0 件**（達成目標） | – |
| 年次 launcher 更新 | 許容 | 1-2 回/年 |
| disaster recovery | 必須（フォールバック） | 障害時のみ |

#### 3. GitHub Actions OIDC + Provenance（codex C-3）

build pipeline:
```
push tag v* (例: v1.2.3)
  ↓
GitHub Actions (windows-latest)
  ├─ uv sync
  ├─ uv run pyinstaller wiseman_hub.spec --clean
  ├─ generate sha256
  ├─ generate SBOM (cyclonedx-py + anchore/sbom-action)
  ├─ google-github-actions/auth (workload identity federation)
  ├─ gsutil cp wiseman_hub.exe gs://wiseman-hub-release-prod/versions/1.2.3/
  ├─ gsutil cp wiseman_hub.exe.sha256 gs://wiseman-hub-release-prod/versions/1.2.3/
  ├─ gsutil cp sbom.json gs://wiseman-hub-release-prod/versions/1.2.3/
  └─ atomic-write manifest.json (current_version, sha256, commit_sha, built_at)
```

manifest schema（ADR-004 v2、PR-6a 拡張、PR-6 後半 SBOM 追加）:
```json
{
  "current_version": "1.2.3",
  "minimum_version": "1.0.0",
  "download_url": "versions/1.2.3/wiseman_hub.exe",
  "checksum_sha256": "abc123...",
  "commit_sha": "f976b44...",
  "built_at": "2026-05-06T12:00:00Z",
  "released_at": "2026-05-06T13:00:00Z",
  "provenance_url": "versions/1.2.3/wiseman_hub.exe.sigstore.json",
  "expected_repo": "sasakisystem0801-source/wiseman-auto-sys",
  "expected_workflow_ref": ".github/workflows/release.yml@refs/tags/v1.2.3",
  "sbom_url": "versions/1.2.3/sbom.json",
  "sbom_sha256": "def456...",
  "release_notes": "...",
  "force_update": false
}
```

PR-6 後半で追加 (codex Suggestion S1 反映):
- `sbom_url` / `sbom_sha256`: SBOM 改竄検出のため manifest に sha256 を含める。
  release.yml の `cyclonedx-py` で生成、`scripts/release/generate_manifest.py` が
  生成時に sha256 計算。本 PR では field 追加のみ、launcher 側の SBOM download +
  検証ロジックは後続 PR で追加。

- GitHub OIDC → GCP Workload Identity Federation で **長期 GCP key を GitHub secrets に置かない**
- PR ビルド: smoke test のみ（GCS upload なし）
- tag push: full build + GCS upload + manifest 更新
- PR と tag で workflow を分離（cost / 権限の最小化）

#### 4. PII 保持設計（codex C-4）

audit log は利用者氏名・施設名・NAS 絶対パス・PDF パス等を含む。
GCS 保持を ADR で明示:

| 種別 | 含むデータ | 保持期間 | 削除権限 |
|------|-----------|---------|---------|
| audit (c_placement) | 利用者名、staff、xlsx_path、target_pdf、status | **1825 日（5 年、介護記録関連法令の安全側）** | 開発者 (Mac SA via gsutil) |
| audit (b_placement) | 同上 | 1825 日（5 年） | 同上 |
| cache (xlsx_path) | staff、絶対パス（利用者名なし） | 90 日（stale 検出用） | 開発者 |
| release artifacts | exe + checksum + sbom | 直近 5 バージョン Standard、それ以前は Archive class へ自動移行 | GHA |

audit log の volume 試算: 配置 60 件/月 × 12 ヶ月 × 5 年 ≈ 3,600 record × 約 500 byte = 約 1.8 MB
（5 年保持してもストレージコスト無視可能）。

- Bucket lifecycle policy で自動削除
- Object Versioning で誤削除復旧
- ADR-007 で確認済の通り、audit 上の PII は介護現場運用で日常的に出現するため
  業務監査として GCS 保持は許容（ismap 内で完結する限り）

##### 4.1 machine_id の PII 取扱（PR-2 codex review 反映）

PR-2 (`xlsx_path_cache_mirror`) で導入した machine_id（`~/wiseman-hub/machine_id`
に永続化される UUIDv4）は、持続的識別子であり広義の個人データに該当する。
取扱は以下:

- **生成方針**: hostname / MAC アドレス / Windows machine GUID を使わず
  必ず UUIDv4 を新規生成（無関連識別子の原則）
- **保持期間**: audit / cache の payload に含まれる machine_id は、bucket
  lifecycle と同じ保持期間で自動削除（audit 5 年 / cache 90 日）
- **link 切れ性**: machine_id 自体は HW ID / hostname / username を含まないため、
  PC 入替で link が完全に切れる（new UUID 生成、旧 UUID は audit log のみに残る）
- **実質紐付け**: 業務責任者 PC は **1 台運用前提** のため、machine_id は実質的に
  「業務責任者本人」に紐づく。これは audit log の他フィールド（利用者名等）と
  同等の取扱となる
- **race 安全性**: ファイル作成は `open(path, "x")` atomic create + FileExistsError
  reread で並行起動 race を解決
- **format 検証**: 既存ファイルの内容を `uuid.UUID()` で parse 検証、不正なら
  `.invalid-{ts}` 退避 + 再生成

#### 5. spool + retry（codex Nice-to-have 1）

audit upload は GCP 障害時に業務を止めない:
```
1. wiseman_hub.exe が audit record を append_audit_record() で書き込む
   → ローカル $HOME\wiseman-hub\spool\audit\YYYY-MM-DD.jsonl に append
2. 起動時 + 5 分間隔で spool ディレクトリを scan
3. GCS object 名は content hash + sequence で冪等化
   → リトライで重複 upload しても安全
4. upload 成功 → spool エントリを削除（または .uploaded suffix）
```

#### 6. cache mirror に revision metadata（codex Nice-to-have 2）

```json
{
  "key": "宮下:2026:3",
  "xlsx_path": "\\\\Tera-station\\share\\PT 宮下\\...",
  "generated_at": "2026-05-06T08:00:00+09:00",
  "machine_id": "honda-pc-001",
  "config_revision": "v1.2.3",
  "base_config_sha256": "..."
}
```

PC 入替・config 巻き戻し時に「どのマシン / どのバージョンで生成された cache か」を
判定可能にする。

#### 7. Mac dry-run の位置付け = 「契約テスト」（codex Important 5）

Mac は本番同等を**謳わない**:

| レイヤー | Mac で検証可能 | Windows 実機で検証必須 |
|---------|--------------|---------------------|
| pure logic（plan_c_placement、resolve_xlsx 等） | ✅ | （任意） |
| GCS object schema、JSON contract | ✅ | （任意） |
| dry-run（PDF 書込なし、path 解決検証） | ✅ | （任意） |
| Excel COM PDF 生成 | ❌ | ✅ |
| WinForms / Wiseman GUI 操作 | ❌ | ✅ |
| Tera-station NAS SMB 書込 | ❌ | ✅ |
| USB ドングル認証 | ❌ | ✅ |

PR #195 の C-1 fix（macOS で `--execute-one` を block）はこの方針に沿った正しい実装。

## Consequences

### 良くなる点

1. **業務責任者の自律性向上**: 起動するだけで最新版になる。PowerShell 不要
2. **dev/test の効率向上**: TeamViewer 立ち会い不要、Mac で完結
3. **保守性向上**: audit / cache が GCS 集約で grep / 分析が容易
4. **supply-chain 強化**: OIDC + provenance + SBOM で改竄検知性能向上
5. **障害耐性向上**: spool + retry で GCP 障害時も業務継続
6. **rollback 容易性**: bootstrapper の参照切替で 1 操作完結
7. **PC 入替コスト低下**: launcher.exe + USB ドングルで現場セットアップ完了

### 悪くなる点・受容するリスク

1. **launcher.exe のバグは自動更新できない**: launcher は極小に保つことで影響範囲を限定
2. **オフライン耐性低下**: GCP 障害中は更新できない（ただし spool で audit は継続）
3. **GHA Windows runner コスト**: PR=smoke、tag=full build に分離して最小化
4. **bootstrapper 分離の実装コスト**: 元案の atomic replace より +1 日程度
5. **bucket 2 つ運用**: IAM 分離の運用ルール周知が必要

### 移行戦略

- 既存 PowerShell runbook（`docs/handoff/1c-exe-redistribution-runbook.md`）は
  「disaster recovery 用」として継続保守
- Phase 6 結合テスト後、Phase 7 で本番運用切替
- 切替後 2 週間は PowerShell runbook も並行で監視

#### Phase 7 切替の hard dependency（PR-4 / PR-6a codex review 反映）

PR-4 codex review (threadId 019dfd43, C-3) と PR-6a codex review (threadId 019dfd9e, I-1) で確定:

| dependency | 必要な理由 | 達成状況 (PR-6 後半末) |
|-----------|-----------|---------------------|
| **PR-6 後半マージ済 (sigstore-python 統合 + signature 検証本実装)** | claims verify (PR-6a) のみでは「攻撃者が release-prod bucket に書ける前提」で偽造 provenance を通せる。SLSA 元来の脅威モデル (sigstore で証明される build provenance) を満たすには signature 検証が必須 | ✅ 本 PR で達成 (sigstore.py + Verifier.verify_dsse 委譲) |
| **`--allow-test-unsigned-provenance` flag が launcher CLI から削除済** | PR-6 後半で完全 fail-closed (二重 gate も除去)、canary 検証で削除確認後のみ Phase 7 着手可 | ✅ 本 PR で削除 (argparse から削除、`is_test_bypass_authorized` 関数 + env var 参照も削除) |
| **PR-5 runbook の seed 手順反映済** | 初回配置時の `versions/{初期版}/wiseman_hub.exe` seed なしでは preflight 失敗で起動不能（§2.2） | ✅ PR #197 で達成 |
| **launcher の本番 PC 配置完了** | wiseman_launcher.exe は固定配布（§2 bootstrapper 構成）、初回のみ手動配布 | ⏳ Phase 7 直前で本田様 PC に手動配布 (PowerShell runbook) |

PR-4 / PR-6a は dev 検証 / smoke build / unit test 専用とし、本番 canary 切替は上記 4 件揃った時点で解禁。
PR-6 後半マージ完了で 3/4 達成、Phase 7 直前 launcher 配布のみ残る。

## Implementation

実装は 7 PR + ADR PR で構成（詳細は `/impl-plan` で再展開）:

| Phase | 内容 | 工数 | 関連 PR |
|-------|------|------|---------|
| 0 | PR #195 マージ（Mac CLI dry-run） | 完了次第 | #195 |
| 1 | 本 ADR-016 + ADR-004 amend | 0.75 日 | docs PR |
| 2 | audit log GCS spool + upload + retry | 0.75 日 | 1 PR |
| 3 | xlsx_path_cache GCS mirror（revision metadata 付き） | 0.5 日 | 1 PR |
| 4 | wiseman_launcher.exe + updater 実装（versions/, current.json, rollback） | 2 日 | 1-2 PR |
| 5 | GitHub Actions: tag → OIDC GCS upload + manifest + SBOM | 1 日 | 1 PR |
| 6 | 結合テスト + canary 切替確認 | 0.5 日 | – |
| 7 | Phase 4 全件配置を新システムで実行（C 業務化完遂） | 0.5 日 | – |

合計 **5.5-6 日**

## Relations

- **Supersedes (partial)**: ADR-004（高位決定は継承、実装設計を置換）
- **Extends**: ADR-011（distribution format → bootstrapper 構成に拡張）
- **Extends**: ADR-015（staff-path-cache → GCS mirror 化、revision metadata 追加）
- **Aligned with**: ADR-007（USB ドングル前提、認証経路は変更なし）

## Out of Scope

以下は本 ADR の範囲外（次フェーズ以降で再検討）:

- Cloud Run UI（業務責任者向け Web ダッシュボード）
- Pub/Sub push 通知（ADR-004 で不採用済 = ポーリング 1 時間で十分）
- GitHub Releases 直接配布（ADR-004 で不採用済 = ismap / rate limit）
- Windows code signing 証明書取得（自動更新開始時に再評価）
- Multi-PC 配布（現状 1 台運用、必要時に再設計）

## References

- ADR-004（GCS manifest polling、本 ADR で実装設計を置換）
- ADR-007（USB ドングル認証）
- ADR-011（distribution format）
- ADR-015（staff-path-cache）
- codex セカンドオピニオン threadId: `019dfb0a-d658-7c42-a957-ea2c6a26dd4f`
- GitHub Docs: [Workload Identity Federation](https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-google-cloud-platform)
- GitHub Docs: [Artifact Attestations](https://docs.github.com/actions/security-for-github-actions/using-artifact-attestations/using-artifact-attestations-to-establish-provenance-for-builds)
- Microsoft Learn: [SmartScreen Reputation](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation)
- Astral docs: [setup-uv](https://github.com/astral-sh/setup-uv)
