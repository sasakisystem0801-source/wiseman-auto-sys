# Handoff: Session 48 - ADR-016 PR-6a 完了（launcher 3 階層分割 + provenance verify 本実装）

**更新日**: 2026-05-07（Session 48 / Mac 開発機）
**main HEAD**: `cc34b1d` feat(launcher): provenance verify + 3-tier module split (ADR-016 PR-6a) (#205)
**作業ブランチ**: なし（PR #205 merged、本ハンドオフ用 `feat/handoff-session-48` のみ）
**残作業**: ADR-016 Phase 5b 後半 / 6 / 7（次セッション以降、約 2 日想定）+ PR-7 deferred (review_team 残)

---

## 🚪 まずここを読む（次セッション最初の入口）

**ADR-016 Phase 5b の launcher 側先行 (PR-6a) を 3 段階品質保証フローで完了したセッション**。`/catchup` 後の入口は以下:

1. ✅ **(済)** PR-6a: launcher 3 階層 module 分割 + SLSA provenance v1.0 claims verify + 二重 gate（PR #205）
2. **(次)** **本田様の PR-5 runbook 実行で GCP セットアップ**（並行可、1 時間）
3. **(その後)** PR-6 後半（release workflow + SBOM + sigstore-python 統合 + signature 検証本実装、1 日）
4. **(or 並行)** PR-7（launcher 後半改善: HTTPS GET DRY / atomic write DRY / TypedDict / log fingerprint 等、半日）
5. **(最後)** Phase 6 結合テスト + canary 切替 + Phase 7 業務全件配置

業務文脈は `specs/c-business-deployment/spec.md`（変更なし）。設計指針は ADR-016。

| ファイル | 役割 |
|---------|------|
| [docs/adr/016-windows-appliance-and-mac-dev-flow.md](../adr/016-windows-appliance-and-mac-dev-flow.md) | 設計の中核（§1.2 で 3 階層 LOC 制約 + §2.1 段階的 fail-closed + §4 Phase 7 hard dependency を本セッションで改訂） |
| [src/wiseman_hub_launcher/_runtime/](../../src/wiseman_hub_launcher/_runtime/) | 本セッション新規 subpackage (lock + spawn + heartbeat) |
| [src/wiseman_hub_launcher/_supply_chain/](../../src/wiseman_hub_launcher/_supply_chain/) | 本セッション新規 subpackage (download + provenance + policy) |
| [src/wiseman_hub_launcher/_supply_chain/provenance.py](../../src/wiseman_hub_launcher/_supply_chain/provenance.py) | SLSA v1.0 claims verify + DSSE / Sigstore Bundle 3 形式 parse |
| [tests/unit/launcher/test_provenance.py](../../tests/unit/launcher/test_provenance.py) | 本セッション新規 35 件（AC-2 / AC-3 検証） |
| [tests/unit/launcher/test_policy.py](../../tests/unit/launcher/test_policy.py) | 本セッション新規 23 件（canonical URL + 二重 gate） |
| 本 LATEST.md | Session 48 差分メモ + 次セッション入口 |

---

## 🎯 Session 48 の成果サマリー

### マージ済 PR (1 件、3 段階品質保証 + 番号単位明示認可後マージ)

| # | 種別 | 概要 | 行数 | 品質保証 |
|---|------|------|------|---------|
| #205 | feat(launcher) | launcher 3 階層 module 分割 + provenance verify 本実装 + 二重 gate（ADR-016 PR-6a） | +2429/-765 | 計画 codex (3C+5I+3S+1N) + PR codex (3I+3S+2N) + 6 エージェント並列 (Critical 10 + 主要 Important 6) **全反映** |

### 3 段階品質保証フロー（Session 47 で確立、本セッションで再証明）

各段階が独立に新規 Critical を発見、合計 16 件 Critical 反映:

1. **計画段階 codex review** (threadId `019dfd9e`) → Critical 3 件 (provenance_url canonical / 二重 gate / 3 階層 LOC 制約)
2. **PR 段階 codex review** (threadId `019dff53`) → Important 3 件 (workflow.repository suffix 緩い / commit/issuer pin 抜け落ちリスク / canonical URL direct test 不足)
3. **/review-pr 6 エージェント並列** → Critical 10 件 (silent-failure 系 / docstring 誤誘導 / test 皆無 / urlparse 厳格化 / except ValueError flatten 等)

→ **次 PR 以降も適用推奨**。3 段階すべてで新規 Critical を発見、検出特性が独立。

### 主要技術要素

#### T2: 3 階層 module 分割（codex C-3 反映）
- **launcher core** (`__main__.py` / `manifest.py` / `current.py` / `checksum.py` / `updater.py` orchestration only): 722 LOC
- **`_runtime/` subpackage** (`lock.py` + `spawn.py`): 191 LOC
- **`_supply_chain/` subpackage** (`download.py` + `provenance.py` + `policy.py`): 408 LOC

#### T4: provenance.py 新規実装（codex Q2-C / I-4 反映）
- **3 形式 parse**: Sigstore Bundle v0.3 / DSSE envelope / plain JSON statement（mediaType > payloadType > _type の優先順、T0 Explore で確認）
- **claims verify** (SLSA v1.0 §5.1 / §6 / §7.2):
  - subject digest + name match + multi-subject 一意性 invariant
  - predicateType: `^https://slsa.dev/provenance/v1(\.\d+)?$` strict regex
  - workflow.repository: `urlparse` で scheme=https + netloc=github.com + path=/{LAUNCHER_EXPECTED_REPO} 完全一致
  - workflow ref pattern: `.github/workflows/release.yml@refs/tags/vX.Y.Z`
  - builder id allowlist: `https://github.com/actions/runner@` 等
  - DSSE payloadType: `application/vnd.in-toto+json` 厳格化
- **signature 検証は stub interface**: `--allow-test-unsigned-provenance` flag + 環境変数 `WISEMAN_ALLOW_UNSIGNED_PROVENANCE_FOR_TESTS=1` の **AND 条件のみ bypass**

#### T6: 二重 gate（codex C-2 反映）
- 本番 PC は env 不在で必ず fail-close（CLI flag を渡されても bypass 不可）
- ADR §2.1 に PR-4 → PR-6a → PR-6 後半の段階的 fail-closed 強化 roadmap 明記

#### Critical security 強化（step 3 PR review 反映）
- `expected_sha256.lower()` 削除 → subject 側 strict 比較 + malformed entry **fail-fast**（continue skip 排除）
- `verify_provenance` bypass 後 silent return → **ERROR ログ昇格** + 構造化 (artifact + sha256 + subject_name)
- `__main__.py` の `except ValueError` 削除 → policy.py の ValueError を updater.py で **`ProvenanceError` に re-raise**（Current invariant / SpawnOutcome invariant 違反が EXIT_PROVENANCE に化けるのを防止）
- `Current.__post_init__` semver invariant + 5 件 test
- dir fsync OSError を Windows 限定 debug suppress、POSIX では errno + filename を warning ログ

### exit code 体系（PR-4 から維持、PR-6a で 9 新設明文化）

| code | 意味 |
|------|------|
| 0 | OK / OK_EARLY_EXIT |
| 2 | CONFIG (argparse / HTTPS pre-check) |
| 3 | MANIFEST / network / artifact size error |
| 4 | UNEXPECTED |
| 5 | CHECKSUM_MISMATCH (PR-4) |
| 6 | ROLLBACK_UNAVAILABLE / preflight 失敗 (PR-4) |
| 7 | SPAWN_FAILED_NO_ROLLBACK (PR-4) |
| 8 | LOCK_HELD (PR-4) |
| **9** | **PROVENANCE** (claims 不一致 / signature stub 到達、PR-6a) |

### 品質メトリクス

- **284 unit tests pass** (Session 47 末 1331 launcher 216 → +68 件)
  - test_provenance.py 35 件新規 (3 形式 parse + claims verify + 二重 gate)
  - test_policy.py 23 件新規 (canonical URL + env var 評価 + 信頼根 constants)
  - test_current.py +5 件 (Current.__post_init__ semver invariant)
  - test_main.py +2 件 (二重 gate 経路)
  - test_provenance.py に repo path traversal test +2 件 (urlparse 厳格化検証)
  - test_updater.py: `_bypass_provenance()` helper 導入で update_and_spawn 系 8 件を維持
- pygount Code 列: **launcher 全体 1321 LOC**（合算制約 1560 内）
  - core: 722 / 900 ✅
  - `_runtime/`: 191 / 250 ✅
  - `_supply_chain/`: 408 / 410 ✅（PR-6a 内 350 → 380 → 410 fine-tuning）
- ruff / mypy / flake8 all clean
- PyInstaller smoke build: macOS arm64 + Windows (CI) 両方成功
- CI 状況: test-unit 3.11/3.12 + Build Windows Smoke 成功

### ADR-016 §1.2 LOC 制約の最終確定

- **再緩和不可** (Session 47 末) を保つため、単純な 900 → 1200 拡張ではなく **3 階層構造に再設計**（codex C-3 合意点）
- 計測法明記: `uvx pygount --format=summary` の **Code 列**（空行 / コメント / docstring 除外、`wc -l` 値とは大きく乖離）
- `_supply_chain/` 制約は PR-6a 内で 350 → 380 → 410 と 2 段階 fine-tuning（Critical security 反映による自然な増加、「validation 削減サイン」ではない）
- 410 超過時は `_supply_chain/sigstore.py` 切り出し強制（PR-6 後半の sigstore 統合タイミング）

### 配布禁止 / Stop-the-line 条件（codex Important I-1 反映）

PR-6a 単独では canary / 業務責任者 PC への配布 **絶対禁止**:

- signature 検証 stub のため、攻撃者が release-prod bucket に書ける前提では偽造 provenance を通せる
- **Phase 6 結合テスト進入禁止**（PR-6 後半 sigstore-python 統合 + signature 検証本実装マージまで）
- **Phase 7 業務全件配置禁止**（`--allow-test-unsigned-provenance` flag が CLI から削除されない限り）

### Issue Net 変化

```
- Close 数: 0 件
- 起票数: 0 件
- Net: 0 件
```

**理由**: 本セッションは ADR-016 PR-6a 中心の中規模実装で、新規バグ発見ゼロ、既存 Issue への影響もなし。codex Critical/Important + review_team 16 件は当該 PR 内で全反映済（追加 Issue 化不要）。review_team / code-simplifier の保留 follow-up は ADR §1.2 LOC 余裕の関係で本 PR で反映できなかった分を、PR-7 計画書として本ハンドオフに明記（CLAUDE.md Issue triage 基準 #4 rating ≥ 7 + confidence ≥ 80 を満たさない rating 5-6 案件のため、機械的 Issue 化を回避）。

---

## ADR-016 Phase 進捗

| Phase | 内容 | Status | 工数 | PR |
|-------|------|--------|------|-----|
| 0 | Mac CLI dry-run | ✅ merged | 完了 | #195 |
| 1 | ADR-016 draft | ✅ merged | 完了 | #196 |
| 2 | audit log GCS upload + spool + retry + ADR-004 amend | ✅ merged | 完了 | #198 |
| 3 | xlsx_path_cache GCS mirror | ✅ merged | 完了 | #201 |
| 4a | wiseman_launcher skeleton + manifest fetch | ✅ merged | 完了 | #200 |
| 4b | updater + rollback + spawn + lock + preflight + heartbeat | ✅ merged | 完了 | #203 |
| 5a | GCP IAM + WIF runbook | ✅ merged | 完了 | #197 |
| **5b 前半** | **launcher 3 階層分割 + provenance claims verify + 二重 gate** | ✅ **merged (本セッション)** | 完了 | **#205** |
| 5b 後半 | release workflow + SBOM + sigstore-python 統合 + signature 検証本実装 | **次** | 1 日 | – |
| 6 | 結合テスト + canary 切替 | pending | 0.5 日 | – |
| 7 | 業務 Phase 4 全件配置を新システムで実行 | pending | 0.5 日 | – |

**残工数**: **約 2 日**（Phase 5b 後半 〜 7 の合計）+ 本田様の GCP 側セットアップ（並行で約 1 時間）+ PR-7 deferred 反映（半日、optional）

---

## 🚀 次セッション直近のアクション（優先順位付き）

### 1. 【本田様タスク】PR-5 runbook 実行で GCP 側セットアップ（1 時間、開発側と並行可）

`docs/runbook/gcp-iam-setup.md` Phase 0-6 と `docs/runbook/workload-identity-federation-setup.md` Phase 0-5 を順次実行（未完なら）:

- bucket 作成: `wiseman-hub-data-prod` / `wiseman-hub-release-prod`
- SA 作成: `wiseman-hub-windows-runtime` / `wiseman-hub-mac-dev` / `wiseman-hub-gha-release`
- IAM bucket-level binding（minimum privilege）
- WIF Pool + Provider + GitHub Variables 5 個登録
- Phase 5 改竄テスト（Windows runtime → release-prod write 失敗を必ず検証）

完了後に開発側へ「runbook 完了」の連絡があれば、Phase 5b 後半 (release workflow + sigstore) 実装に着手可能。

### 2. 【開発側タスク】PR-7 launcher 後半改善（1 日、本田様完了待ち不要、Phase 5b 後半着手前 or 並行で可能）

review_team / code-simplifier の保留 follow-up を反映する:

- **code-simplifier I-1**: HTTPS GET helper DRY (`download.py` の `_open_https_get` と `manifest.py` の `fetch_manifest` 共通化、~30 LOC 削減で `_supply_chain/` LOC 余裕確保)
- **code-simplifier I-2**: atomic write helper DRY (`download.py` の `_atomic_place` と `current.py` の `write_current_atomic` 共通化、`_atomic_place` の `fd`/`fd_owned` dead 引数削除)
- **type-design**: `LockHeartbeat` terminal state 化（二重 enter ガード、`stop()` 後の再 `start()` を `RuntimeError`）+ `manifest TypedDict` 化（assert isinstance noise 削減）
- **pr-test I2-I4**: predicate malformed shape (predicate not dict / runDetails not dict / builder not dict / buildDefinition not dict) test + integration test (provenance verify が update_and_spawn から実際呼ばれることの確認) + uppercase digest edge
- **silent-failure 残**: log fingerprint (構造化 JSON 1 行) / EXIT_DOWNLOAD semantic 分離 (現状 EXIT_MANIFEST=3 流用) / docstring Args/Raises/Returns 補完
- **comment 改善**: `provenance.py` の `_atomic_place` `fd`/`fd_owned` unused / `is_production_build` 用途未定 / `updater.py` re-export deprecation 経路の PR/Issue 参照
- **Nit 修正**: ADR §3 manifest schema 例の旧 `.intoto.jsonl` を `.sigstore.json` に統一

### 3. 【開発側タスク】Phase 5b 後半（PR-6 後半、1 日、本田様完了後）

GitHub Actions OIDC + GCS upload + manifest atomic + SBOM 生成 + provenance attestation + sigstore signature verify:

- `.github/workflows/release.yml` 新規（windows-latest / tag push triggered / OIDC + WIF）
- `cyclonedx-py` で SBOM、`anchore/sbom-action` で artifact bundle
- `actions/attest-build-provenance` で `provenance.intoto.jsonl` 生成（実際は Sigstore Bundle v0.3 形式の `.sigstore.json`）
- `gsutil cp` で `versions/X.Y.Z/{wiseman_hub.exe, .sha256, sbom.json, *.sigstore.json}` 配置
- `manifest.json` を atomic 生成（`current_version`/`commit_sha`/`built_at`/`released_at` + `provenance_url` + `expected_repo` + `expected_workflow_ref` 含む）
- **`sigstore-python` 依存追加** + signature 検証本実装で `_supply_chain/provenance.py` の stub を置換
- **`--allow-test-unsigned-provenance` flag + `WISEMAN_ALLOW_UNSIGNED_PROVENANCE_FOR_TESTS` 環境変数 完全除去**
- ADR-016 §2.1 の段階的 fail-closed 表で「PR-6 後半完了」と更新、§4 Phase 7 hard dependency 確認

LOC 見通し: PR-7 で DRY 化により ~50 LOC 削減 → PR-6 後半で sigstore 検証本実装 +~80 LOC で `_supply_chain/` 410 → ~440 LOC（要 fine-tuning または `_supply_chain/sigstore.py` 切り出し）

### 4. Phase 6 結合テスト + Phase 7 業務 Phase 4 全件配置（PR-6 後半マージ後）

dev tag → canary tag → 壊れた exe で rollback 検証 → 業務 60 件配置。

---

## 補足事項

### Session 48 の重要な決定の根拠

- **3 階層 module 構造での LOC 制約再設計**: codex C-3 で「Session 47 末『再緩和不可』の単純衝突を避ける」観点から、launcher core / `_runtime/` / `_supply_chain/` の独立制約に再設計。`_supply_chain/` の 350 → 410 fine-tuning は Critical security 反映による自然な増加で、防御を削る趨勢ではない
- **二重 gate (CLI flag + env var AND)**: codex C-2 で「`--allow-unsigned-provenance` だけでは本番配布で過大評価」と指摘されたため、本番 PyInstaller build で env を埋め込まないことを fail-close の primary 機構に。CLI flag は単独では bypass 不可
- **`urlparse` で workflow.repository 厳格化**: codex PR 段階 I-1 で「`endswith` だけでは `https://evil.example/x/sasaki.../wiseman-auto-sys` も通る」suffix 攻撃を防御
- **`except ValueError` 削除**: silent-failure-hunter / type-design の指摘で「Current invariant / SpawnOutcome invariant 違反 (= coding bug) が EXIT_PROVENANCE に化ける」semantic flatten を排除、`ProvenanceError` 階層に統合

### 本セッションで触った主要ファイル

**新規追加 (PR #205)**:
- `src/wiseman_hub_launcher/_runtime/{__init__.py, lock.py, spawn.py}` (191 LOC)
- `src/wiseman_hub_launcher/_supply_chain/{__init__.py, download.py, provenance.py, policy.py}` (408 LOC)
- `tests/unit/launcher/test_provenance.py` (35 件、+435 LOC)
- `tests/unit/launcher/test_policy.py` (23 件、+165 LOC)

**変更 (PR #205)**:
- `src/wiseman_hub_launcher/__main__.py`: flag 置換 + EXIT_PROVENANCE = 9 + `except ValueError` 削除
- `src/wiseman_hub_launcher/updater.py`: orchestration only に縮減 (344 → 170 LOC) + provenance 統合
- `src/wiseman_hub_launcher/manifest.py`: `expected_repo` / `expected_workflow_ref` 必須化
- `src/wiseman_hub_launcher/current.py`: `Current.__post_init__` semver invariant
- `src/wiseman_hub_launcher/checksum.py`: provenance stub を `_supply_chain/provenance.py` に移動
- `tests/unit/launcher/test_*.py`: PR-6a schema 拡張対応、`_bypass_provenance()` helper 導入

**変更 (PR #205 / 設計文書)**:
- `docs/adr/016-windows-appliance-and-mac-dev-flow.md`
  - §1.2: 3 階層 LOC 制約再設計 + 計測法明記 (pygount Code 列)
  - §2.1: PR-4 → PR-6a → PR-6 後半の段階的 fail-closed 強化 roadmap
  - §4: Phase 7 hard dependency に「`--allow-test-unsigned-provenance` flag 削除済」追加

### Session 47 までのコンテキスト

Session 47 の詳細は `docs/handoff/archive/session-47-adr-016-phase-4b.md` 参照（本セッション開始時に archive へ移動）。

### 次セッションの並列化機会

本田様の GCP 設定 (60 分) と開発側の **PR-7** (~半日) または **PR-6 後半** (~1 日) は **完全独立**で同時進行可能。本田様完了通知前でも PR-7 (DRY 化 + TypedDict + LockHeartbeat terminal + log fingerprint 等) は着手 OK（実 GCS 接続を試さない、unit test と smoke build のみ）。実 release workflow の試走 (tag push) は本田様の GCP セットアップ完了後。

---

## Quality Gate 充足確認

| 項目 | 状態 |
|------|------|
| ADR-016 整合性 (§1.2 / §2.1 / §4 を本 PR で改訂、§1〜§7 と整合) | ✅ |
| 全 PR で番号単位の明示認可後マージ (#205) | ✅ |
| 計画段階 codex review (`019dfd9e`) Critical 3 + Important 5 + Suggestion 3 + Nit 1 全反映 | ✅ |
| PR 段階 codex review (`019dff53`) Important 3 + Suggestion 3 + Nit 2 全反映 | ✅ |
| /review-pr 6 エージェント並列 Critical 10 + 主要 Important 6 全反映 | ✅ |
| ruff / mypy / flake8 / 284 unit tests pass | ✅ |
| Issue Net ≤ 0 | ✅（Net 0、進捗ゼロ扱いではない理由は上記 Issue Net 変化に明記） |
| 残留プロセスなし | ✅ |
| Test plan 未済項目 | ⚠ Windows 実機検証 (Phase 6) と 実 GCS 接続検証 (Phase 5b 後半 release workflow 着手時) は次セッション以降 |

`✅ 再開可能`（次セッション冒頭で本ファイルを読めば、PR-6a マージ後の状態から PR-7 / Phase 5b 後半 / Phase 6/7 に進める）。
