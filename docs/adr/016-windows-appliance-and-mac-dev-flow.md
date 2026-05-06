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

launcher 側の実装制約（ADR-016 PR-3 で導入）:

- launcher 実コード行数 < 300 行（cloc 計測、空行/コメント/test 除外）
- launcher runtime package は **stdlib only**（`urllib.request` + `hashlib` + `json` +
  `pathlib` + `datetime` + `argparse` + `logging` + `dataclasses` + `hmac` + `os` +
  `tempfile` のみ）
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

#### 1.2 launcher 行数制約の運用定義（PR-3 codex review 反映）

PR-3 着手時 codex review (threadId 019dfce6) で確定:

300 LOC 制約は **runtime critical path** に対するもの。盲目的な行数維持で
validation や error message を削るのは supply-chain 防御の毀損となるため、
以下の運用定義に従う:

| 区分 | 対象 | 上限 |
|------|------|------|
| **runtime critical path** (PR-3) | `__main__.py`, `manifest.py`, `checksum.py`, `current.py` の実コード | 400 LOC（pygount 計測、空行/コメント/docstring 除外） |
| **runtime critical path** (PR-4 後) | 上記 + `updater.py`（download/spawn/rollback） | 600 LOC |
| **対象外** | `__init__.py`（version 文字列のみ）、test files、PyInstaller spec | 制約なし |

PR-3 codex review (threadId 019dfce6) 反映後の実測値: **389 LOC**（path traversal 防御強化、HTTPS pin、DoS cap、provenance signature 拡張等で +103 LOC）。当初目標 300 LOC は「validation を削れば達成可能」だが supply-chain 防御の毀損となるため、現実的上限を 400/600 に再定義した。

緩和の根拠:

- launcher 極小性の本質は「**stdlib only** + **`wiseman_hub.*` import 禁止** +
  **依存ライブラリ重量ゼロ**」であり、行数自体ではない
- 行数を盲目的に維持するために validation を削るのは supply-chain 防御の毀損
- PR-4 後も runtime path package は **<500 LOC** 厳守、それを超えたらアーキテクチャ見直し

行数監視:

- 各 PR で `pygount src/wiseman_hub_launcher --format=summary` の値を PR body に記載
- 500 LOC 超過時は「launcher が肥大化している signal」として ADR 化アラート

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

- launcher は **極力小さく保つ**（manifest poll + checksum + spawn のみ、300 行未満目安）
- 更新は **年 1-2 回程度** を想定、PowerShell runbook で対応（disaster recovery 経路と共有）
- 「launcher の launcher」化は無限後退になるので採用しない
- launcher 更新が頻繁に必要になったら、それは **launcher が肥大化している signal** であり、
  アーキテクチャ見直しの契機とする

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

manifest schema（ADR-004 v2）:
```json
{
  "current_version": "1.2.3",
  "minimum_version": "1.0.0",
  "download_url": "versions/1.2.3/wiseman_hub.exe",
  "checksum_sha256": "abc123...",
  "commit_sha": "f976b44...",
  "built_at": "2026-05-06T12:00:00Z",
  "released_at": "2026-05-06T13:00:00Z",
  "provenance_url": "versions/1.2.3/provenance.intoto.jsonl",
  "release_notes": "...",
  "force_update": false
}
```

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
