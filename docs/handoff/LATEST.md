# Handoff: Session 53 - Issue #209 完結 (Sha256Hex NewType call-graph 全体 propagate)

**更新日**: 2026-05-08（Session 53 / Mac 開発機、Session 52 続編）
**main HEAD**: `e7d8dbb` type-safety(launcher): Sha256Hex 受けに caller 全面追従 + make_sha256hex 導入 (#209 PR2) (#224)
**作業ブランチ**: なし（PR #223 / #224 全マージ完了 + Issue #209 close）
**残作業**: ADR-016 Phase 6 (結合テスト + canary 切替) + Phase 7 (業務全件配置) + 派生 Issue #210-#212 / #161-#164 等

---

## 🚪 まずここを読む（次セッション最初の入口）

**Session 52 で完成した Phase 6 前 gate (build / runtime / manifest / signature) の上に、Issue #209 (Sha256Hex NewType 化) を 2 段階 PR で完結させたセッション**。codex セカンドオピニオンで scope 縮小 (4 種一括 → Sha256Hex 単独)、4 並列 review で各 PR の Critical 0 / Important 全反映を本 PR 内で吸収、Issue 起票ゼロで Net -1 達成。

**Phase 7 hard dependency 4 項目中 3/4 達成 (Session 52 から変化なし)**:
- ✅ sigstore-python 統合 + signature 検証本実装
- ✅ `--allow-test-unsigned-provenance` flag 完全削除
- ✅ PR-5 runbook seed 手順反映済
- ⏳ launcher.exe 本田様 PC 配置完了 (Phase 7 直前で手動配布)

**Issue #209 で達成した効果 (PR1 + PR2 合算)**:
- `Sha256Hex` NewType を `manifest.py` に導入、`ManifestData.checksum_sha256` / `sbom_sha256` を Sha256Hex 化
- caller 6 関数 (`verify_sha256` / `download_artifact` / `_download_with_atomic_place` / `_verify_subject` / `verify_statement_claims` / `verify_provenance`) を Sha256Hex 受け化
- `make_sha256hex(s: str) -> Sha256Hex` validating constructor で外部 source mint を gate (form / type 両方の不正を ManifestError 一本化)
- `commit_sha` (7-40 hex) や version 文字列との取り違えを mypy で **call-graph 全体に compile-time 検出**
- runtime ChecksumError / ProvenanceError 二重 fail-close 維持 (型 gate と runtime gate の冗長防御)
- CI mypy step に `mypy tests/unit/launcher/test_manifest.py` を追加し `assert_type` lock-in を CI で発現

`/catchup` 後の入口は以下:

1. ✅ **(Session 52 で済)** Phase 6 前 gate 4 経路完成 (PR #219 / #220 / #221)
2. ✅ **(本セッションで済)** Issue #209 PR1: Sha256Hex NewType 導入 (#223、Refs #209)
3. ✅ **(本セッションで済)** Issue #209 PR2: caller 全面追従 + make_sha256hex 導入 + review 反映 (#224、Closes #209)
4. **(次)** **Phase 6 結合テスト + canary 切替**（実 dev tag `v0.99.0` push → release.yml 発火 → GCS upload → bundle 検証 → canary tag）→ 番号認可必要
5. **(最後)** **Phase 7 業務全件配置**（launcher.exe 本田様 PC 手動配布 + Phase 4 全件配置を新システムで実行、TeamViewer 経由）

業務文脈は `specs/c-business-deployment/spec.md`（変更なし）。設計指針は ADR-016。

| ファイル | 役割 |
|---------|------|
| [src/wiseman_hub_launcher/manifest.py](../../src/wiseman_hub_launcher/manifest.py) | `Sha256Hex` NewType + `make_sha256hex` validating constructor + `ManifestData` field 型化 + `validate_manifest` 末尾の make_sha256hex narrow |
| [src/wiseman_hub_launcher/checksum.py](../../src/wiseman_hub_launcher/checksum.py) | `verify_sha256(expected_hex: Sha256Hex)` signature 化 + TYPE_CHECKING import |
| [src/wiseman_hub_launcher/_supply_chain/download.py](../../src/wiseman_hub_launcher/_supply_chain/download.py) | `download_artifact` / `_download_with_atomic_place` Sha256Hex 化 |
| [src/wiseman_hub_launcher/_supply_chain/provenance.py](../../src/wiseman_hub_launcher/_supply_chain/provenance.py) | `_verify_subject` / `verify_statement_claims` / `verify_provenance` Sha256Hex 化 |
| [tests/unit/launcher/test_manifest.py](../../tests/unit/launcher/test_manifest.py) | `assert_type` narrow lock-in (PR1) + `make_sha256hex` direct test 16 件 (PR2 review I-1 反映) |
| [.github/workflows/test-unit.yml](../../.github/workflows/test-unit.yml) | CI mypy step に `tests/unit/launcher/test_manifest.py` 追加 (PR1 review I-2 反映、assert_type lock-in を CI で発現) |
| 本 LATEST.md | Session 53 差分メモ + 次セッション入口 |

---

## 🎯 Session 53 の成果サマリー

### マージ済 (本セッション、2 段階 PR)

| PR | Issue | 内容 | 規模 | テスト | 結果 |
|----|-------|------|------|--------|------|
| **#223** | #209 (Refs) | type-safety(launcher): Sha256Hex NewType を manifest.py に導入 (PR1) | 4 files / +74/-9 | 110 | ✅ squash merge (`8ac36c8`) |
| **#224** | #209 (Closes) | type-safety(launcher): Sha256Hex 受けに caller 全面追従 + make_sha256hex (PR2) + review 反映 | 8 files / +172/-32 | 16 (新規 direct test) | ✅ squash merge (`e7d8dbb`) |

### Issue #209 完結プロセス (Generator-Evaluator + 2 段階 PR の good practice)

1. **計画段階**: codex セカンドオピニオン (`gpt-5.2`) を起動 → 当初案 (NewType 4 種一括 / 6 ファイル変更 1 PR / TypedDict constructor 構文) **NO-GO** 判定 → scope 縮小 (Sha256Hex 単独) + 2 段階 PR + dict literal 方式に修正
2. **PR1 実装**: manifest.py + updater.py + test_manifest.py + test-unit.yml (CI mypy 追加)
3. **PR1 review**: 4 並列 (type-design / code-reviewer / pr-test-analyzer / silent-failure-hunter) → Important 3 件 (`Closes → Refs` / CI mypy 不在 / overreach claim) すべて本 PR 内 fix
4. **PR2 実装**: checksum.py / _supply_chain/download / _supply_chain/provenance + tests + make_sha256hex
5. **PR2 review**: 4 並列 → Important 3 件 (make_sha256hex direct test 不在 (3 reviewer 同一指摘) / consistency / None TypeError) すべて本 PR 内 fix

### Issue Net 変化

```
## Issue Net 変化
- Close 数: 1 件 (#209 — PR1 + PR2 で完結)
- 起票数: 0 件
- Net: -1 件
```

CLAUDE.md「Net ≤ 0 が進捗 OK 基準」を満たす。本セッションは review agent から rating 5-6 の Suggestion を多数受けたが、**全て PR コメント / TODO レベルで処理し Issue 化せず**。rating 7 の Important 指摘は **本 PR 内で全反映** (PR2 で test_manifest.py に make_sha256hex direct test 16 件追加 + manifest.py に isinstance check 追加)、follow-up Issue 起票ゼロで完結。

### Test count 変化

338 (Session 52 末) → **354** (+16 件 in this session):
- PR #223: +2 (test_validate_manifest_narrows_*)
- PR #224: +16 (test_make_sha256hex_*) - 14 件は parametrize で展開、test 関数自体は 3 つ

(parametrize 展開後の合計 PASS 件数: 1471 passed, 94 skipped)

### 設計判断の record (codex + 4 並列 review)

| 当初案 | 修正後 | 経路 |
|--------|--------|------|
| NewType 4 種一括 (Sha256Hex / CommitSha / SemverTriple / Iso8601UtcZ) | Sha256Hex 単独 | codex セカンドオピニオン (churn が勝つ) |
| 6 ファイル変更 1 PR | 2 段階 PR (PR1: 入口 / PR2: 全面追従) | codex セカンドオピニオン (リスク分散) |
| `ManifestData(checksum_sha256=Sha256Hex(...), ...)` 構築 | `validated["checksum_sha256"] = make_sha256hex(...)` で個別 narrow | codex (TypedDict は runtime constructor ではない) + PR2 review I-2 (consistency) |
| Sha256Hex(...) 直接呼出 | `make_sha256hex(s)` validating constructor 経由必須 | PR1 review S-1 (silent-failure) + PR2 review I-2 (consistency) |
| - | `assert_type` で静的 type 契約 lock-in + CI mypy step 追加 | 4 並列 review pr-test-analyzer + type-design (重複指摘) |
| - | `make_sha256hex` 冒頭で `isinstance(value, str)` check + ManifestError 一本化 | PR2 review I-3 (docstring 契約厳守) |
| sigstore-python 境界の `str()` cast | 不要と判断 | 実装確認の結果、境界には str (statement.digest) のみ渡る |
| dict mutation 単一化 (review type-design Suggestion 2) | 見送り | cosmetic、scope inflation 防止 |

---

## 📌 次セッション直近のアクション

### 1. Phase 6 結合テスト + canary 切替 (0.5-1 日、要番号認可)

**目的**: Session 52 で CI 上の build / runtime / manifest / signature gate を完成 + Session 53 で Sha256Hex 取り違え検出が call-graph 全体に届いた状態を、実 dev tag を push して **release.yml の actual run + GCS upload + provenance bundle 生成** までを End-to-End で検証する。

```bash
# 1. dev tag push (release.yml 発火、do_upload=true で GCS bucket 経由)
git checkout main && git pull
git tag v0.99.0
git push origin v0.99.0  # ← 番号単位の明示認可必須 (destructive: GCS bucket 汚染 + tag history 残存)

# 2. release.yml の run 結果を gh で確認
gh run watch  # またはブラウザで Actions タブ
```

**確認項目** (PR #214 codex C1 で merge 前に未検証だった部分):
- `actions/attest-build-provenance@v2` の subject 名形式 (`subject.name` が `wiseman_hub.exe` か絶対 path か)
- GCS bucket `gs://wiseman-hub-release-prod/versions/0.99.0/` に exe + sha256 + sbom + sigstore.json + manifest.json が揃うか
- launcher 側で実 download → signature 検証が pass するか (Mac から `gsutil cp` で bundle 取得して unit test 経由)

問題なければ canary tag (`v0.99.1`) で Mac → 本田様 PC への Phase 7 直前 final 検証。

**AI / 人間の役割分担**:
- AI: release.yml run 監視 (Monitor) / GCS bucket 内容確認 (`gsutil ls`) / launcher Mac E2E (`gsutil cp` + unit test 経由 verify_provenance)
- ユーザー: tag push 認可、canary 切替判断、Phase 7 への go/no-go 評価

### 2. Phase 7 業務全件配置 (0.5 日、本田様 PC で実機作業、TeamViewer 経由)

**前提**: Phase 6 結合テスト pass + canary 切替成功

- launcher.exe を本田様 PC に手動配布 (`docs/handoff/1c-exe-redistribution-runbook.md` 準拠の PowerShell 手順)
- Phase 4 全件配置を新システムで実行 (新 launcher 経由 → wiseman_hub.exe 起動)

**AI ができるのは runbook 内容の事前レビュー + ユーザーが TeamViewer 中の質問にリアルタイム回答のみ。実機操作は 100% ユーザー作業。**

### 3. 派生 Issue 対応 (Session 50 派生 #209-#212、後回し可)

- ✅ **#209 (本セッションで close)** type-safety: launcher の Sha256Hex / CommitSha NewType 導入で取り違え検出
- **#210**: type-safety: `_phase_log` の phase 名を Literal 拘束で typo 防止
- **#211**: refactor: `_atomic_io.atomic_replace_and_fsync_dir` を 2 引数化 (dest_dir 冗長性除去)
- **#212**: silent-failure: launcher の `DownloadError __cause__` を `log.exception` で出力 + EXIT_ARTIFACT 分離

いずれも P2 enhancement、Phase 6 を block しない。

---

## 🗺️ 残 active Issue (P2 全て、ブロッカーなし)

| # | タイトル | 系統 |
|---|---------|------|
| #212 | silent-failure: launcher の DownloadError __cause__ を log.exception で出力 + EXIT_ARTIFACT 分離 | launcher (Session 50 派生) |
| #211 | refactor: _atomic_io.atomic_replace_and_fsync_dir を 2 引数化 | launcher (Session 50 派生) |
| #210 | type-safety: _phase_log の phase 名を Literal 拘束 | launcher (Session 50 派生) |
| #170, #164, #162, #161, #158, #152 | ex_extractor / config / ui 系 | 別ドメイン |
| #134 | OCR: Gemini 2.5 Flash retire (2026-10-16) 対応 | OCR |
| #63, #39, #29, #27, #17 | テスト / マッチング / OCR proxy / config | 別ドメイン |

---

## 🔧 状態スナップショット

| 項目 | 値 |
|------|-----|
| main HEAD | `e7d8dbb` type-safety(launcher): Sha256Hex 受けに caller 全面追従 + make_sha256hex 導入 (#209 PR2) (#224) |
| working tree | clean (全変更マージ済) |
| 残留 Node プロセス | なし ✅ |
| CI (main push 後) | success (Windows Integration Tests, 2m36s) |
| Test count | 1471 passed, 94 skipped (本セッションで +16 件 launcher direct test) |
| Issue 開件数 | 15 (Session 52 末 16 → -1 で 15、closed: #209) |

---

## ⚙️ 開発環境メモ (Session 51 から変化なし)

- Mac dev: `~/Projects/wiseman-auto-sys`、main で作業
- Windows 実機 (本田様 PC、TeamViewer 経由): `C:\Users\sasak\Projects\wiseman-auto-sys` (clone) + `C:\Users\sasak\wiseman-hub\` (配布物)
- 本番データ: `\\Tera-station\share\03.FAX(事業所)` (UNC、40 事業所、ADR-013)
- NAS trashbox: `\\Tera-station\share\trashbox\` (誤削除復旧経路)

---

## 🔁 セッション再開条件

- ✅ 再開可能: working tree clean、main 同期、CI 全 pass、handoff 更新済、Issue #209 close 確認済
- 次セッション最初: `/catchup` で Issue 一覧確認 → Phase 6 結合テスト直行 (実 dev tag push) または派生 Issue (#210-#212) 対応の選択
- Phase 6 で実 tag push する場合は番号単位の明示認可が必要 (destructive 操作: GCS bucket 汚染 + tag history 残存)
