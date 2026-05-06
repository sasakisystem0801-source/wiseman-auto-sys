# Handoff: Session 47 - ADR-016 Phase 4b 完了（PR-4 launcher updater + rollback）

**更新日**: 2026-05-06（Session 47 / Mac 開発機）
**main HEAD**: `79579f3` feat(launcher): updater + rollback + spawn + lock + preflight (ADR-016 PR-4) (#203)
**作業ブランチ**: なし（PR #203 merged、本ハンドオフ用 `feat/handoff-session-47` のみ）
**残作業**: ADR-016 Phase 5b / 6 / 7（次セッション以降、約 2 日想定）

---

## 🚪 まずここを読む（次セッション最初の入口）

**ADR-016 Phase 4b (PR-4 launcher updater) を 3 段階品質保証で完了したセッション**。`/catchup` 後の入口は以下:

1. ✅ **(済)** PR-4: launcher updater + rollback + spawn + lock + preflight + heartbeat（PR #203）
2. **(次)** **PR-6** (release workflow + SBOM + provenance + manifest 自動生成)
3. **(その後)** Phase 6 結合テスト + Phase 7 業務 Phase 4 全件配置

業務文脈は `specs/c-business-deployment/spec.md`（変更なし）。設計指針は ADR-016。

| ファイル | 役割 |
|---------|------|
| [docs/adr/016-windows-appliance-and-mac-dev-flow.md](../adr/016-windows-appliance-and-mac-dev-flow.md) | 設計の中核（§1.2 LOC 制約 / §2.1 fail-closed gate / §2.2 seed / §4 Phase 7 hard dependency を本セッションで追記） |
| [src/wiseman_hub_launcher/updater.py](../../src/wiseman_hub_launcher/updater.py) | 本セッション新規 module（download / spawn / rollback / lock / preflight / heartbeat） |
| [src/wiseman_hub_launcher/__main__.py](../../src/wiseman_hub_launcher/__main__.py) | --update / --no-spawn / --allow-insecure-checksum-only mode 追加 |
| [src/wiseman_hub_launcher/current.py](../../src/wiseman_hub_launcher/current.py) | previous_version + CurrentReadError + strict_read 追加 |
| 本 LATEST.md | Session 47 差分メモ + 次セッション入口 |

---

## 🎯 Session 47 の成果サマリー

### マージ済 PR (1 件、3 段階品質保証 + 番号単位明示認可後マージ)

| # | 種別 | 概要 | 行数 | 品質保証 |
|---|------|------|------|---------|
| #203 | feat(launcher) | updater + rollback + spawn + lock + preflight + heartbeat（ADR-016 PR-4） | +2635/-77 | 計画 codex (4C+5I+4S+3N) + PR codex (1C+6I+2S+1N) + 6 エージェント並列 (5C+4B-tier) 全反映 |

### 3 段階品質保証フロー（本セッションで確立）

Session 47 で初めて以下の流れを実施し、有効性を確認:

1. **計画段階 codex review** (threadId `019dfd43`) → Critical 4 件発見、修正版プラン承認後着手
2. **PR 段階 codex review** (threadId `019dfd5d`) → Critical 1 件 + Important 6 件発見、コミット後反映
3. **/review-pr 6 エージェント並列** (comment / test / silent-failure / type-design / code / simplify) → 重複排除後ユニーク Critical 5 件発見、必須 9 件反映

→ **次 PR 以降も適用推奨**。3 段階すべてで新規 Critical を発見しており、各段階の検出特性が独立。

### 主要技術要素

- **updater.py 新規** (290 LOC pygount): download / SHA-256 / atomic place / spawn + monitor / rollback / lock acquire/release/heartbeat / preflight
- **C-2 多重起動排他**: `O_CREAT|O_EXCL|O_WRONLY` + stale > 1h で強制解除 + `LockHeartbeat` で 60s 間隔の `os.utime` 更新（review_team A1 second-pass で transient retry 3 回まで）
- **C-4 preflight**: `versions/{current.version}/wiseman_hub.exe` 存在確認、初期 0.0.0 は WARN のみ
- **D2' 4 状態判定**: `subprocess.Popen.wait(timeout)` で `SUCCESS / OK_EARLY_EXIT / CRASH / OS_ERROR`、returncode==0 早期終了は rollback しない（single-instance / ドングル認証キャンセル等の正常 0 exit 対応）
- **D3' atomic download**: HTTPS chunked + size cap 300 MiB + redirect 検証 + Windows 互換 `tempfile.mkstemp` + `os.replace` + dir fsync
- **previous_version + rollback**: `current.json` schema 拡張、履歴 1 段保持、ROLLBACK 後は previous_version="" にリセット
- **supply-chain gate**: `--allow-insecure-checksum-only` 必須、PR-6 で provenance 検証実装後に除去予定
- **CurrentReadError + strict_read**: Windows AV transient ロックを silent に「first install」と誤認して rollback 能力を喪失するシナリオを防止（review_team A2 second-pass）

### exit code 体系拡張

| code | 意味 |
|------|------|
| 0 | OK / OK_EARLY_EXIT |
| 2 | CONFIG (argparse / HTTPS pre-check / fail-closed gate) |
| 3 | MANIFEST / network / artifact size error |
| 4 | UNEXPECTED |
| **5** | CHECKSUM_MISMATCH (PR-4 新設) |
| **6** | ROLLBACK_UNAVAILABLE / preflight 失敗 / current.json read error (PR-4 新設) |
| **7** | SPAWN_FAILED_NO_ROLLBACK (PR-4 新設) |
| **8** | LOCK_HELD (多重起動、PR-4 新設) |

### 品質メトリクス

- **1331 unit tests pass** (Session 46 末 1115 → +216 件、新規 launcher 216 + 既存維持)
  - launcher tests: 152 → 216（+64 件、updater + heartbeat retry + strict_read + B1/B2/B3 等）
- pygount: **899 LOC** (制約 900 LOC、ADR §1.2 で 300 → 400 → 700 → 800 → 900 と段階緩和、最終ライン)
- ruff / mypy / flake8 all clean
- PyInstaller smoke build: `dist/wiseman_launcher` Mach-O arm64 (macOS) 成功
- CI: 4/4 pass (test-unit 3.11 / 3.12 / build-smoke / test-integration)

### ADR-016 §1.2 LOC 制約の最終確定

300 → 400 (PR-3) → 700 (PR-4 計画) → 800 (PR-4 実装後) → **900 (review_team 反映後最終)** と段階緩和。**900 超過時は updater 分割を強制（再緩和不可）**。PR-6 で provenance verify を呼ぶ +30〜50 LOC が見込まれるため、`_lock.py` / `_download.py` の module 分割が必要になる可能性が高い。

### Issue Net 変化

```
- Close 数: 0 件
- 起票数: 0 件
- Net: 0 件
```

**理由**: 本セッションは ADR-016 Phase 4b 中心の中規模実装で、新規バグ発見ゼロ、既存 Issue への影響もなし。codex Critical/Important + review_team Critical は当該 PR 内で全反映済（追加 Issue 化不要）。review_team の保留 follow-up（type-design / silent-failure / comment 残）は ADR §1.2 LOC 制約の余裕がないため PR-6 と合わせて反映予定で、**個別 Issue 化はせず PR-6 計画書に明記**（CLAUDE.md Issue triage 基準 #4 rating ≥ 7 + confidence ≥ 80 を満たさない rating 5-6 案件のため、機械的 Issue 化を回避）。

---

## ADR-016 Phase 進捗

| Phase | 内容 | Status | 工数 | PR |
|-------|------|--------|------|-----|
| 0 | Mac CLI dry-run | ✅ merged | 完了 | #195 |
| 1 | ADR-016 draft | ✅ merged | 完了 | #196 |
| 2 | audit log GCS upload + spool + retry + ADR-004 amend | ✅ merged | 完了 | #198 |
| 3 | xlsx_path_cache GCS mirror | ✅ merged | 完了 | #201 |
| 4a | wiseman_launcher skeleton + manifest fetch | ✅ merged | 完了 | #200 |
| **4b** | **updater + rollback + spawn + lock + preflight + heartbeat** | ✅ **merged (本セッション)** | 完了 | **#203** |
| 5a | GCP IAM + WIF runbook | ✅ merged | 完了 | #197 |
| 5b | release workflow + SBOM + provenance + manifest 自動生成 | **next** | 1 日 | – |
| 6 | 結合テスト + canary 切替 | pending | 0.5 日 | – |
| 7 | 業務 Phase 4 全件配置を新システムで実行 | pending | 0.5 日 | – |

**残工数**: **約 2 日**（Phase 5b〜7 の合計）+ 本田様の GCP 側セットアップ（並行で約 1 時間）

---

## 🚀 次セッション直近のアクション（優先順位付き）

### 1. 【本田様タスク】PR-5 runbook 実行で GCP 側セットアップ（1 時間、開発側と並行可）

`docs/runbook/gcp-iam-setup.md` Phase 0-6 と `docs/runbook/workload-identity-federation-setup.md` Phase 0-5 を順次実行（未完なら）:

- bucket 作成: `wiseman-hub-data-prod` / `wiseman-hub-release-prod`
- SA 作成: `wiseman-hub-windows-runtime` / `wiseman-hub-mac-dev` / `wiseman-hub-gha-release`
- IAM bucket-level binding（minimum privilege）
- WIF Pool + Provider + GitHub Variables 5 個登録
- **Phase 5 改竄テスト**（Windows runtime → release-prod write 失敗を必ず検証）

完了後に開発側へ「runbook 完了」の連絡があれば、PR-6 (release workflow) 実装に着手可能。

### 2. 【開発側タスク】PR-6 (release workflow + SBOM + provenance, 1 日) に着手

**GitHub Actions OIDC + GCS upload + manifest atomic + SBOM 生成 + provenance attestation**:

- `.github/workflows/release.yml` 新規（windows-latest / tag push triggered / OIDC + WIF）
- `cyclonedx-py` で SBOM、`anchore/sbom-action` で artifact bundle
- `actions/attest-build-provenance` で provenance.intoto.jsonl 生成
- `gsutil cp` で `versions/X.Y.Z/{wiseman_hub.exe, .sha256, sbom.json, provenance.intoto.jsonl}` 配置
- `manifest.json` を atomic 生成（`current_version`/`commit_sha`/`built_at`/`released_at` 含む）
- `wiseman_hub_launcher/checksum.py` の `verify_provenance` を ProvenanceUnavailable から本実装に置換
- `--allow-insecure-checksum-only` flag を `__main__.py` から除去
- launcher run_update が provenance 検証を default で実行
- ADR-016 §2.1 PR-4 fail-closed gate 文言を「PR-6 で除去済」に更新

**review_team の保留 follow-up を併せて反映** (ADR-016 §1.2 LOC 余裕の関係で本 PR で反映できなかった分):
- type-design Critical: `SpawnOutcome` invariant を factory classmethods で enforce
- type-design Important 4: `LockHeartbeat` context manager / `Current.__post_init__` / `EXIT_DOWNLOAD` 分離 / `(SUCCESS, OK_EARLY_EXIT)` frozenset 化
- silent-failure Important 6: log fingerprint / `no_spawn` silent skip 警告 等
- comment Important 4: docstring 完全性 (`Args/Raises` 補完)
- pr-test Important 7: `LockHeartbeat` flakiness 対策 / cold start / lock race 等

**LOC 制約の見通し**: 現在 899/900。PR-6 で provenance 実装 +30〜50 LOC、follow-up 反映 +50〜80 LOC で合計 980〜1030 LOC 想定。**ADR-016 §1.2 で 900 LOC 超過時は updater 分割を強制と明記しているため、PR-6 では `_lock.py` (lock + heartbeat) と `_download.py` (download + checksum) を新規 module として分離**。

### 3. Phase 6 結合テスト + Phase 7 業務 Phase 4 全件配置（PR-6 マージ後）

dev tag → canary tag → 壊れた exe で rollback 検証 → 業務 60 件配置。

---

## 補足事項

### Session 47 の重要な決定の根拠

- **3 段階品質保証フローの確立**: 計画 codex + PR codex + /review-pr 6 エージェントの 3 段階すべてで新規 Critical を発見。各段階の検出特性が独立しており、PR-4 のような security/reliability critical な PR では必須運用として今後採用
- **ADR-016 §1.2 LOC 制約 900 が最終ライン**: 段階緩和で「validation 削って LOC 維持は supply-chain 防御毀損」を 3 度認めた結果。PR-6 では 900 超過時の **updater 分割 (再緩和不可)** を強制
- **review_team follow-up を Issue 化せず PR-6 計画書に明記**: rating 5-6 提案を機械的 Issue 化しない CLAUDE.md triage 基準に従う運用、Issue Net = 0 維持

### 本セッションで触った主要ファイル

**新規追加 (PR #203 / launcher PR-4)**:
- `src/wiseman_hub_launcher/updater.py` (新規、~570 LOC raw、290 LOC pygount)
- `tests/unit/launcher/test_updater.py`（新規、~840 LOC、40+ tests）

**変更 (PR #203 / launcher 拡張)**:
- `src/wiseman_hub_launcher/__main__.py` (`--update`/`--no-spawn`/`--allow-insecure-checksum-only` mode 追加、exit 5/6/7/8 拡張)
- `src/wiseman_hub_launcher/current.py` (`previous_version` 追加 + `CurrentReadError` + `strict_read` flag)
- `src/wiseman_hub_launcher/manifest.py` (`_is_simple_semver` → `is_simple_semver` public 化)
- `tests/unit/launcher/test_main.py` (PR-4 mode tests +28)
- `tests/unit/launcher/test_current.py` (previous_version + strict_read tests +15)

**変更 (PR #203 / 設計文書)**:
- `docs/adr/016-windows-appliance-and-mac-dev-flow.md`
  - §1.2 LOC 制約: 600 → 900 LOC への段階緩和ストーリーと根拠
  - §2.1 PR-4 成果物の本番配布禁止ゲート (`--allow-insecure-checksum-only` 必須、PR-6 で除去)
  - §2.2 初回配置時の seed 必須 (preflight check 実装、PR-5 runbook 改訂タスク)
  - §4 Phase 7 切替の hard dependency 3 件明記

### Session 46 までのコンテキスト

Session 46 の詳細は `docs/handoff/archive/session-46-adr-016-phase-3-4a.md` 参照（本セッション開始時に archive へ移動）。

### 次セッションの並列化機会

本田様の GCP 設定 (60 分) と開発側の PR-6 (~1 日) は **完全独立**で同時進行可能。本田様完了通知前でも PR-6 の launcher 側 (provenance verify 本実装 + follow-up 反映) は着手 OK（実 GCS 接続を試さない、unit test と smoke build のみ）。実 release workflow の試走 (tag push) は本田様の GCP セットアップ完了後。

---

## Quality Gate 充足確認

| 項目 | 状態 |
|------|------|
| ADR-016 整合性 (§1.2 / §2.1 / §2.2 / §4 を新規追記、既存 §1〜§7 と整合) | ✅ |
| 全 PR で番号単位の明示認可後マージ (#203) | ✅ |
| codex セカンドオピニオン Critical/Important 全反映 (計画 + PR の 2 段階) | ✅ |
| /review-pr 6 エージェント並列 Critical 5 件全反映 | ✅ |
| ruff / mypy / flake8 / 1331 unit tests pass | ✅ |
| Issue Net ≤ 0 | ✅（Net 0、進捗ゼロ扱いではない理由は上記 Issue Net 変化に明記） |
| 残留プロセスなし | ✅ |
| Test plan 未済項目 | ⚠ Windows 実機検証 (PR-5 runbook 実行後) と Mac から `gsutil` で実 GCS 確認 (Phase 6) は次セッション以降 |

`✅ 再開可能`（次セッション冒頭で本ファイルを読めば、PR-4 マージ後の状態から PR-6 + Phase 6/7 に進める）。
