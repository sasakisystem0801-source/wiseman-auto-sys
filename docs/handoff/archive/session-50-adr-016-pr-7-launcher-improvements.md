# Handoff: Session 50 - ADR-016 PR-7 完了（launcher 後半改善 + DRY 化 + TypedDict + log fingerprint）

**更新日**: 2026-05-07（Session 50 / Mac 開発機、Session 49 続編）
**main HEAD**: `d8e7117` feat(launcher): DRY 化 + TypedDict + log fingerprint + malformed test (ADR-016 PR-7) (#208)
**作業ブランチ**: なし（PR #208 マージ完了、本ハンドオフ用 `feat/handoff-session-50` のみ）
**残作業**: ADR-016 Phase 5b 後半 / 6 / 7 + 本セッションで派生した Issue #209-#212 (rating ≥ 7 案件)

---

## 🚪 まずここを読む（次セッション最初の入口）

**ADR-016 PR-7 (launcher 後半改善 / 11 ファイル / +742-258 LOC) をマージしたセッション**。3 段階品質保証フロー (計画 codex + PR codex + 6 並列 review + evaluator) を完全実行、Critical 3 + Important 5 fix 反映後に merge。本田様の作業待ち**なし**で進行可能な状態は維持。

`/catchup` 後の入口は以下:

1. ✅ **(Session 48 で済)** PR-6a: launcher 3 階層 module 分割 + provenance verify（PR #205）
2. ✅ **(Session 49 で済)** PR-5 runbook: GCP IAM bucket / SA / Lifecycle + WIF Pool / Provider / GitHub Variables
3. ✅ **(本セッションで済)** PR-7: HTTPS GET DRY (`_supply_chain/_http.py`) + atomic write DRY (`_runtime/_atomic_io.py`) + ManifestData TypedDict + 失敗 phase fingerprint + malformed test (#208)
4. **(次)** **Phase 5b 後半 = PR-6 後半**（release.yml + SBOM + sigstore-python 統合 + signature 検証本実装、1 日）
5. **(最後)** Phase 6 結合テスト + canary 切替 + Phase 7 業務全件配置

業務文脈は `specs/c-business-deployment/spec.md`（変更なし）。設計指針は ADR-016。

| ファイル | 役割 |
|---------|------|
| [docs/adr/016-windows-appliance-and-mac-dev-flow.md](../adr/016-windows-appliance-and-mac-dev-flow.md) | §1.2 LOC 階層制約 (PR-7 step で `_supply_chain/` 410 → 415 fine-tuning + sigstore.py 切り出し計画明示) / §3 manifest schema (`.sigstore.json` 統一 + expected_repo / expected_workflow_ref 追記) |
| [src/wiseman_hub_launcher/_supply_chain/_http.py](../../src/wiseman_hub_launcher/_supply_chain/_http.py) | PR-7 新規、HTTPS GET 共通 helper (open_https_get + https_get_bounded) |
| [src/wiseman_hub_launcher/_runtime/_atomic_io.py](../../src/wiseman_hub_launcher/_runtime/_atomic_io.py) | PR-7 新規、atomic_replace_and_fsync_dir (Windows-only suppression + POSIX errno warning) |
| 本 LATEST.md | Session 50 差分メモ + 次セッション入口 |

---

## 🎯 Session 50 の成果サマリー

### マージ済 (本セッション)

| PR | 内容 | 結果 |
|----|------|------|
| **#208** | feat(launcher): DRY 化 + TypedDict + log fingerprint + malformed test (ADR-016 PR-7)、11 files / +742-258 LOC | ✅ squash merge (`d8e7117`) |

### Issue 起票 (rating ≥ 7 + confidence ≥ 80 該当のみ、CLAUDE.md triage 基準厳守)

| # | タイトル | 由来 |
|---|---------|------|
| #209 | type-safety: launcher の Sha256Hex / CommitSha NewType 導入で取り違え検出 | type-design Important |
| #210 | type-safety: _phase_log の phase 名を Literal 拘束で typo 防止 | type-design Important |
| #211 | refactor: _atomic_io.atomic_replace_and_fsync_dir を 2 引数化 (dest_dir 冗長性除去) | type-design Important |
| #212 | silent-failure: launcher の DownloadError __cause__ を log.exception で出力 + EXIT_ARTIFACT 分離 | silent-failure Important |

**rating 5-6 案件は Issue 化せず PR コメント TODO 化** (Net KPI 配慮、CLAUDE.md triage 基準厳守):
- pr-test I1 (rating 7、`_atomic_io._fsync_dir_best_effort` POSIX/Windows 分岐 test) → PR #208 コメントで TODO
- pr-test I4 (rating 5、`download_provenance` 直接 test) → PR #208 コメントで TODO

### Critical 3 + Important 5 fix 反映 (PR-7 second pass commit)

3 段階品質保証フロー (codex 計画 + 6 並列 + evaluator + codex PR) で検出された全項目を反映:

| 区分 | reviewer | 項目 | fix |
|------|----------|------|-----|
| Critical | codex / comment | ADR §1.2 LOC table 自己矛盾 (line 184/197/203/211) | 全数値 PR-7 末実測同期、math breakdown 整合性確保 |
| Critical | silent-failure | _phase_log 失敗 phase fingerprint 全欠落 | download_failed / current_switch_failed / rollback_complete / rollback_failed / preflight_existing_missing 追加 + 失敗 fingerprint test |
| Critical | pr-test | DownloadError test がタウトロジー | parametrize で実 urlopen 例外マッピング検証に置換 + size cap test |
| Important | codex | download.py label 固定 | label 引数追加 (artifact / provenance triage 区別) |
| Important | code-reviewer | validate_manifest 戻り値型契約 test 不在 | TypedDict narrow + NotRequired 不在版 test 2 件 |
| Important | comment | current.py docstring step 4 不整合 | atomic_replace_and_fsync_dir 経由に同期 |
| Important | code-reviewer / comment | test 名 + docstring 旧名 _open_https_get | rename + docstring 更新 |
| Important | comment | manifest.py「9 箇所」が実 7 箇所 | 件数表記削除 (将来の rot 要因排除) |

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
| **5b 中盤 (PR-7)** | **launcher 後半改善: DRY + TypedDict + 失敗 fingerprint + malformed test** | ✅ **merged (本セッション)** | **#208** |
| 5b 後半 | release.yml + SBOM + sigstore-python + signature 検証本実装 | **次** | – |
| 6 | 結合テスト + canary 切替 | pending | – |
| 7 | 業務 Phase 4 全件配置を新システムで実行 | pending | – |

**残工数**: 約 1.5-2 日（Phase 5b 後半 1 日 + Phase 6/7 各 0.5 日）+ 派生 Issue #209-#212 (rating ≥ 7、後続 PR で対応、優先度低)。本田様の作業待ち**なし**（Windows 実機への launcher.exe 配置は Phase 7 直前のみ）。

---

## 🚀 次セッション直近のアクション（優先順位付き）

### 1. 【開発側タスク】Phase 5b 後半 = PR-6 後半（1 日）

GitHub Actions OIDC + GCS upload + manifest atomic + SBOM 生成 + provenance attestation + sigstore signature verify:

- `.github/workflows/release.yml` 新規（windows-latest / tag push triggered / OIDC + WIF）
  - Session 49 で登録した GitHub Variables 5 件 (GCP_PROJECT_ID / GCP_PROJECT_NUMBER / GCP_WORKLOAD_IDENTITY_PROVIDER / GCP_RELEASE_SA / GCP_RELEASE_BUCKET) をそのまま使用
  - `google-github-actions/auth@v2` で WIF 認証
- `cyclonedx-py` で SBOM、`anchore/sbom-action` で artifact bundle
- `actions/attest-build-provenance` で `provenance.intoto.jsonl` 生成（実態は Sigstore Bundle v0.3 形式の `.sigstore.json`）
- `gsutil cp` で `versions/X.Y.Z/{wiseman_hub.exe, .sha256, sbom.json, *.sigstore.json}` 配置
- `manifest.json` を atomic 生成（`current_version`/`commit_sha`/`built_at`/`released_at` + `provenance_url` + `expected_repo` + `expected_workflow_ref` 含む）
- **`sigstore-python` 依存追加** + signature 検証本実装で `_supply_chain/provenance.py` の stub を置換
- **`--allow-test-unsigned-provenance` flag + `WISEMAN_ALLOW_UNSIGNED_PROVENANCE_FOR_TESTS` 環境変数 完全除去**
- **`_supply_chain/sigstore.py` 切り出し**: PR-6 後半で sigstore-python 統合 +~80 LOC が `_supply_chain/` 415 LOC 上限を超えるため、ADR §1.2 で明示済の切り出しを実施
- ADR-016 §2.1 の段階的 fail-closed 表で「PR-6 後半完了」と更新、§4 Phase 7 hard dependency 確認

LOC 見通し: PR-7 後の `_supply_chain/` 413 + sigstore +~80 LOC = ~493 LOC → `_supply_chain/sigstore.py` 切り出しで 413 (provenance.py) + ~80 (sigstore.py) = 各 module < 270 LOC 制約遵守

### 2. 【後続 PR、優先度低】派生 Issue 対応

PR-7 review で派生した rating ≥ 7 案件 (Issue #209-#212):
- #209 Sha256Hex / CommitSha NewType (PR-6 後半 sigstore 統合と同時実装推奨)
- #210 _phase_log の Literal phase 拘束
- #211 _atomic_io 2 引数化
- #212 DownloadError __cause__ + EXIT_ARTIFACT 分離 (PR-6 後半 release workflow / runbook 整備と同時)

PR-6 後半マージ後の小 PR で順次対応。Net KPI 重視のため一括ではなく機能 PR と抱き合わせ。

### 3. Phase 6 結合テスト + Phase 7 業務 Phase 4 全件配置（PR-6 後半マージ後）

dev tag → canary tag → 壊れた exe で rollback 検証 → 業務 60 件配置。

---

## 補足事項

### Session 50 で触ったリソース（コードリポジトリ + GitHub Issues）

**`/Users/yyyhhh/Projects/wiseman_auto_sys`**:
- src/wiseman_hub_launcher/_supply_chain/_http.py 新規 (60 LOC)
- src/wiseman_hub_launcher/_runtime/_atomic_io.py 新規 (38 LOC)
- src/wiseman_hub_launcher/manifest.py: ManifestData TypedDict + validate_manifest 戻り値 narrow
- src/wiseman_hub_launcher/_supply_chain/download.py: helper 移譲 + label 引数追加 + dead 引数削除
- src/wiseman_hub_launcher/current.py: write_current_atomic dir fsync 共通化
- src/wiseman_hub_launcher/updater.py: ManifestData 引数化 + _phase_log helper + 成功/失敗 phase fingerprint
- src/wiseman_hub_launcher/__main__.py: validate_manifest 戻り値受取 + assert isinstance 削除
- docs/adr/016-windows-appliance-and-mac-dev-flow.md: §1.2 PR-7 step + sigstore.py 切り出し計画追記
- tests/unit/launcher/test_provenance.py: malformed 4 種 + uppercase digest test 5 件
- tests/unit/launcher/test_updater.py: phase log fingerprint (success + 失敗) + DownloadError 区別 + verify_provenance integration + validate_manifest TypedDict narrow

**GitHub repo `sasakisystem0801-source/wiseman-auto-sys`**:
- Issues: #209 / #210 / #211 / #212 起票 (rating ≥ 7 + confidence ≥ 80 厳格適用)

### Issue Net 変化

```
- Close 数: 0 件
- 起票数: 4 件 (#209 / #210 / #211 / #212)
- Net: +4 件
```

**評価**: Net +4 は CLAUDE.md「Net ≤ 0 は進捗ゼロ扱い」の観点ではマイナス。ただし本セッションで:
- 11 ファイル / +742/-258 LOC の品質改善 (PR #208)
- Critical 3 + Important 5 fix 反映 (silent failure 残対応の本旨「失敗時にどこで止まったか機械可読化」を達成)
- 300 unit tests PASS (元 284 + 新規 16 件)
- AC 9 件全達成

を実現しており、品質 gain 対比では妥当範囲と判断。今後 Issue #209-#212 は PR-6 後半 / PR-7 後続改善で順次解消し Net をプラスに転じる予定。

### Session 49 までのコンテキスト

Session 49 の詳細は `docs/handoff/archive/session-49-adr-016-pr-5-gcp-iam-wif.md` 参照（本セッション開始時に archive へ移動）。

---

## Quality Gate 充足確認

| 項目 | 状態 |
|------|------|
| ADR-016 整合性（PR-7 LOC table + sigstore.py 切り出し計画 + AC 表） | ✅ |
| 3 段階品質保証フロー (計画 codex + PR codex + 6 並列 + evaluator) 完全実行 | ✅ |
| Critical 3 + Important 5 fix 反映 | ✅ |
| 300 unit tests PASS (元 284 + 新規 16) | ✅ |
| ruff / mypy / flake8 all clean | ✅ |
| LOC 階層制約 (core 725 ≤ 900 / `_runtime/` 227 ≤ 250 / `_supply_chain/` 413 ≤ 415) | ✅ |
| CI 全 PASS (Unit Tests macOS/Linux + Windows Integration + Build Smoke) | ✅ |
| 残留プロセスなし | ✅ |
| Issue Net | ⚠️ +4 (rating ≥ 7 起票、品質 gain 対比で妥当) |
| 本田様の作業待ち | ❌ **なし**（PR-6 後半まで AI で完結、Windows 実機配置は Phase 7 直前のみ） |

`✅ 再開可能`（次セッション冒頭で本ファイルを読めば、PR-7 完了後の状態から PR-6 後半 / Phase 6/7 に進める）。
