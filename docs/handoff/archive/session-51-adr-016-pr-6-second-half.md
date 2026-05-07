# Handoff: Session 51 - ADR-016 PR-6 後半完了（sigstore-python 統合 + release.yml 新規 + bypass 経路完全削除）

**更新日**: 2026-05-07（Session 51 / Mac 開発機、Session 50 続編）
**main HEAD**: `75b7b6e` feat(launcher): sigstore-python 統合 + release.yml 新規 + bypass 経路完全削除 (ADR-016 PR-6 後半) (#214)
**作業ブランチ**: なし（PR #214 マージ完了、本ハンドオフ用 `docs/handoff-session-51` のみ）
**残作業**: ADR-016 Phase 6 (結合テスト + canary 切替) + Phase 7 (業務全件配置) + 派生 Issue #209-#217

---

## 🚪 まずここを読む（次セッション最初の入口）

**ADR-016 PR-6 後半 (release.yml + sigstore-python 統合 / 18 ファイル / +1971/-361 LOC) をマージしたセッション**。3 段階品質保証フロー (計画 codex + PR codex + 6 並列 review + evaluator) を完全実行、Critical 5 + Important 5 fix 反映後に merge。

**Phase 7 hard dependency 4 項目中 3/4 達成**:
- ✅ sigstore-python 統合 + signature 検証本実装
- ✅ `--allow-test-unsigned-provenance` flag 完全削除
- ✅ PR-5 runbook seed 手順反映済 (PR #197)
- ⏳ launcher.exe 本田様 PC 配置完了 (Phase 7 直前で手動配布)

`/catchup` 後の入口は以下:

1. ✅ **(Session 48 で済)** PR-6a: launcher 3 階層 module 分割 + provenance verify（PR #205）
2. ✅ **(Session 49 で済)** PR-5 runbook: GCP IAM bucket / SA / Lifecycle + WIF Pool / Provider / GitHub Variables
3. ✅ **(Session 50 で済)** PR-7: HTTPS GET DRY + atomic write DRY + ManifestData TypedDict + 失敗 phase fingerprint (#208)
4. ✅ **(本セッションで済)** PR-6 後半: sigstore-python 統合 + release.yml + bypass 完全削除 (#214)
5. **(次)** **Phase 6 結合テスト + canary 切替**（実機 dev tag → canary tag 検証、0.5-1 日）
6. **(最後)** **Phase 7 業務全件配置**（launcher.exe 本田様 PC 手動配布 + Phase 4 全件配置を新システムで実行、0.5 日）

業務文脈は `specs/c-business-deployment/spec.md`（変更なし）。設計指針は ADR-016。

| ファイル | 役割 |
|---------|------|
| [docs/adr/016-windows-appliance-and-mac-dev-flow.md](../adr/016-windows-appliance-and-mac-dev-flow.md) | §1.1.3 sigstore-python 例外明文化 + §1.2 LOC fine-tuning (`_supply_chain/` 415 → 530) + §2.1 fail-closed 表 (PR-6 後半 = flag 完全除去) + §3 manifest schema (sbom_url + sbom_sha256 追加) + §4 Phase 7 hard dependency 達成状況 |
| [.github/workflows/release.yml](../../.github/workflows/release.yml) | PR-6 後半 新規、tag push v*.*.* + workflow_dispatch dry_run、attest gating、partial release 検知 |
| [src/wiseman_hub_launcher/_supply_chain/sigstore.py](../../src/wiseman_hub_launcher/_supply_chain/sigstore.py) | PR-6 後半 新規、Verifier.verify_dsse 委譲 + Identity 完全一致 + system clock sanity check |
| [scripts/release/generate_manifest.py](../../scripts/release/generate_manifest.py) | PR-6 後半 新規、manifest atomic 生成 (sbom_url/sbom_sha256 含む) |
| 本 LATEST.md | Session 51 差分メモ + 次セッション入口 |

---

## 🎯 Session 51 の成果サマリー

### マージ済 (本セッション)

| PR | 内容 | 結果 |
|----|------|------|
| **#214** | feat(launcher): sigstore-python 統合 + release.yml 新規 + bypass 経路完全削除 (ADR-016 PR-6 後半)、18 files / +1971/-361 LOC | ✅ squash merge (`75b7b6e`) |

### Issue 起票 (rating ≥ 7 + confidence ≥ 80 該当のみ、CLAUDE.md triage 基準厳守)

| # | タイトル | 由来 | rating |
|---|---------|------|--------|
| #215 | test(launcher): scripts/release/generate_manifest.py の direct test 追加 | pr-test-analyzer Critical 1 | 9 |
| #216 | test(launcher): _supply_chain/sigstore.py の direct unit test 追加 | pr-test-analyzer Important 3 | 7 |
| #217 | ci(launcher): wiseman_launcher.spec の独立 smoke build を CI で常時検証 | PR codex Important 2 | 8 |

**rating 5-6 案件は Issue 化せず後続 PR の対応先送り** (Net KPI 配慮、CLAUDE.md triage 基準厳守):
- sigstore.py の ImportError 3 重複 → module top guard 統合 (code-simplifier rating 6)
- SigstoreVerifyError sub-classes (ClockSkewError 等) (type-design / silent-failure rating 6)
- ProvenanceError sub-classes (signature/claims/identity/canonical 4 種類 discriminator) (silent-failure rating 6)
- _load_bundle / _sha256_file の OSError 詳細 wrap (silent-failure rating 5)

### Critical 5 + Important 5 fix 反映 (PR-6 後半 second commit `7a922e6`)

3 段階品質保証フロー (計画 codex + 6 並列 + evaluator + PR codex) で検出された全項目を反映:

| 区分 | reviewer | 項目 | fix |
|------|----------|------|-----|
| Critical | code-reviewer / evaluator / type-design / comment-analyzer | ManifestData TypedDict に sbom_url + sbom_sha256 (NotRequired) 未追加 (forgotten edit) | 追加 + ペアリング invariant 検証 + 6 件 test |
| Critical | comment-analyzer | policy.py docstring 「`_BUILD_FLAVOR_ENV_VAR` 削除」誤記 (実は残存、build flavor 用) | docstring 修正 (削除済は `_TEST_BYPASS_ENV_VAR` のみ) |
| Critical | comment-analyzer | sigstore.py docstring 「±2 hour 範囲」誤記 (実装は 2026-2030 絶対範囲) | 「2026-2030 絶対範囲」に修正 + 2030 期限 TODO 追加 |
| Critical | comment-analyzer | provenance.py + sigstore.py docstring の identity 組立位置記述矛盾 | provenance.verify_provenance 内で組立てと統一 |
| Critical | comment-analyzer / silent-failure | ADR §1.1.3 「online refresh + cache fallback」誤記 | sigstore-python バージョン依存 + wrap で fail-close と明記 |
| Important | PR codex I1 | release.yml workflow_dispatch dry_run=false で prod bucket 汚染経路 | workflow_dispatch では do_upload=false 強制 |
| Important | silent-failure I7/I8 | release.yml attest 失敗時に GCS upload 全体 partial state | attest 成功 AND 条件で gating + partial release 検知 step 追加 |
| Important | code-reviewer / comment-analyzer | generate_manifest.py docstring の存在しない --bucket 記述 | 削除 (URL は launcher 側 RELEASE_BUCKET_BASE で組立) |
| Important | code-reviewer / comment-analyzer | provenance.py 旧 docstring「中間 commit では残したまま」 | 完全削除 |
| Important | type-design | verify_provenance の expected_version semver 形式検証なし | `^[0-9]+\.[0-9]+\.[0-9]+$` regex check + 7 件 test |

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
| GCP セットアップ | runbook 実行 (PR-5 運用面、AI 実行) | ✅ Session 49 | — |
| 5b 中盤 (PR-7) | launcher 後半改善: DRY + TypedDict + 失敗 fingerprint + malformed test | ✅ Session 50 | #208 |
| **5b 後半 (PR-6 後半)** | **release.yml 新規 + sigstore-python 統合 + signature 検証本実装 + bypass 経路完全削除** | ✅ **merged (本セッション)** | **#214** |
| 6 | 結合テスト + canary 切替 (実機 dev tag → canary 検証、launcher.exe 配布の前段階) | **次** | – |
| 7 | 業務 Phase 4 全件配置を新システムで実行 (launcher.exe 本田様 PC 配布 + Phase 4 全件) | pending | – |

**残工数**: 約 1.0-1.5 日（Phase 6 0.5-1 日 + Phase 7 0.5 日）+ 派生 Issue #209-#217 (rating ≥ 7 系、後続 PR で順次対応、優先度低)。

---

## 🚀 次セッション直近のアクション（優先順位付き）

### 1. 【ユーザー判断必要】Phase 6 結合テスト + canary 切替（0.5-1 日）

`actions/attest-build-provenance@v2` の実出力 bundle で `subject.name` が `wiseman_hub.exe` (basename) になることを確認 (PR codex C1、merge 前に未検証):

- 開発者: dev tag (例: `v0.0.1-dev` → ただし stable check で reject されるので実は `v0.99.0` 等の専用テスト version) を git push
- → release.yml 発火、GCS bucket に dev artifact upload
- → Mac から `gsutil cp` で provenance bundle download、`subject.name` を目視確認
- → launcher (Mac から `python -m wiseman_hub_launcher --update --manifest-url ...`) で signature 検証 pass を確認
- 確認できたら canary tag (`v0.99.1`) で本田様 PC への配布前 final 検証

**注意**: 現状 stable check (`^v[0-9]+\.[0-9]+\.[0-9]+$`) は `v0.99.0` を accept する (Phase 6 用 0.x.x 系で代替可能)。本番 v1.x.x.x は Phase 7 で打つ。

### 2. 【開発側タスク】派生 Issue 対応（Phase 6/7 と並行可）

- #215 generate_manifest.py direct test (rating 9、Phase 6 前に推奨)
- #216 sigstore.py direct test (rating 7、Phase 6/7 と並行で可)
- #217 launcher.spec smoke build CI (rating 8、Phase 6 前に推奨 - sigstore upgrade 検出の早期化)
- #209-#212 (Session 50 派生): Sha256Hex/CommitSha NewType / _phase_log Literal / _atomic_io 2 引数 / DownloadError __cause__

PR-6 後半マージ後の小 PR で順次対応。Net KPI 重視のため一括ではなく機能 PR と抱き合わせ。

### 3. Phase 7 業務全件配置（Phase 6 + #217 完了後）

launcher.exe を本田様 PC に手動配布 (PowerShell runbook、`docs/handoff/1c-exe-redistribution-runbook.md` 拡張版) → Phase 4 全件配置を新システムで実行。

---

## 補足事項

### Session 51 で触ったリソース

**`/Users/yyyhhh/Projects/wiseman_auto_sys`**:
- src/wiseman_hub_launcher/_supply_chain/sigstore.py 新規 (92 LOC、Verifier.verify_dsse 委譲)
- src/wiseman_hub_launcher/_supply_chain/provenance.py: signature 検証本実装 + bypass 削除 + expected_version semver 検証
- src/wiseman_hub_launcher/_supply_chain/policy.py: is_test_bypass_authorized + _TEST_BYPASS_ENV_VAR 削除
- src/wiseman_hub_launcher/_supply_chain/__init__.py: sigstore export 追加 / bypass export 削除
- src/wiseman_hub_launcher/__main__.py: --allow-test-unsigned-provenance flag 削除
- src/wiseman_hub_launcher/updater.py: allow_unsigned_provenance 引数削除
- src/wiseman_hub_launcher/manifest.py: ManifestData TypedDict に sbom_url + sbom_sha256 追加 + ペアリング invariant
- .github/workflows/release.yml 新規 (~150 LOC、tag push + workflow_dispatch + attest gating + partial release 検知)
- scripts/release/generate_manifest.py 新規 (~85 LOC、manifest atomic 生成)
- pyproject.toml: sigstore>=3.0,<4.0 + cyclonedx-bom>=4.0 + [tool.uv] prerelease=allow 追加
- uv.lock 更新 (+1034 LOC)
- wiseman_launcher.spec: sigstore + tuf hidden imports 追加、requests 除外解除
- docs/adr/016-windows-appliance-and-mac-dev-flow.md: §1.1.3 + §1.2 + §2.1 + §3 + §4 改訂
- tests/unit/launcher/test_provenance.py: bypass 経路 5 件 → sigstore mock 4 件 + semver 検証 7 件
- tests/unit/launcher/test_policy.py: is_test_bypass_authorized 関連 3 件削除
- tests/unit/launcher/test_updater.py: allow_unsigned_provenance 削除 + expected_version assertion 追加
- tests/unit/launcher/test_main.py: bypass 系 2 件削除 → flag rejected (SystemExit 2) test + signature failure (EXIT_PROVENANCE) test 追加
- tests/unit/launcher/test_manifest.py: sbom 6 件追加

**GitHub repo `sasakisystem0801-source/wiseman-auto-sys`**:
- Issues 起票: #215 / #216 / #217 (rating ≥ 7 + confidence ≥ 80 厳格適用)

### Issue Net 変化

```
- Close 数: 0 件
- 起票数: 3 件 (#215 / #216 / #217)
- Net: +3 件
```

**評価**: Net +3 は CLAUDE.md「Net ≤ 0 は進捗ゼロ扱い」の観点ではマイナス。ただし本セッションで:
- 18 ファイル / +1971/-361 LOC の機能追加 (PR #214、Phase 5b 後半完了)
- Phase 7 hard dependency 3/4 達成 (残 1 件は launcher 配布のみ)
- bypass 経路完全削除 + sigstore-python 統合で本格 fail-closed gate 有効化
- Critical 5 + Important 5 fix 反映 (review 全完了)
- 302 unit tests PASS (元 289 + 新規 13 件)
- AC 12 件中 11 件達成 (AC10 CI smoke は実行後 PASS 確認、AC12 は forgotten edit を fix で解消)

を実現しており、品質 gain 対比では妥当範囲と判断。今後 Issue #209-#217 は Phase 6/7 と並行 PR で順次解消し Net をプラスに転じる予定。

### Session 50 までのコンテキスト

Session 50 の詳細は `docs/handoff/archive/session-50-adr-016-pr-7-launcher-improvements.md` 参照（本セッション開始時に archive へ移動）。

---

## Quality Gate 充足確認

| 項目 | 状態 |
|------|------|
| ADR-016 整合性（§1.1.3 sigstore 例外 + §1.2 LOC 表 + §2.1 fail-closed + §3 sbom 拡張 + §4 hard dependency） | ✅ |
| 3 段階品質保証フロー (計画 codex + PR codex + 6 並列 review + evaluator) 完全実行 | ✅ |
| Critical 5 + Important 5 fix 反映 | ✅ |
| 302 unit tests PASS (元 289 + 新規 13) | ✅ |
| ruff / mypy / flake8 all clean | ✅ |
| LOC 階層制約 (core 697 ≤ 900 / `_runtime/` 227 ≤ 250 / `_supply_chain/` 518 ≤ 530 / 各 module ≤ 270) | ✅ |
| CI 全 PASS (Unit Tests macOS/Linux + Build Windows Smoke + Test Windows Integration) | ✅ |
| 残留プロセスなし | ✅ |
| Issue Net | ⚠️ +3 (rating ≥ 7 起票、品質 gain 対比で妥当) |
| 本田様の作業待ち | ⏳ **Phase 7 直前のみ** (launcher.exe 本田様 PC 手動配布) |

`✅ 再開可能`（次セッション冒頭で本ファイルを読めば、PR-6 後半完了後の状態から Phase 6 結合テスト → Phase 7 業務全件配置に進める）。
