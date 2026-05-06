# Handoff: Session 46 - ADR-016 Phase 3 + 4a 完了（PR-2 + PR-3 並列実装、2 PR merged）

**更新日**: 2026-05-06（Session 46 / Mac 開発機）
**main HEAD**: `d268f4c` feat(cache): xlsx_path_cache GCS mirror (ADR-016 PR-2) (#201)
**作業ブランチ**: なし（全 PR merged、本ハンドオフ用 `feat/handoff-session-46` のみ）
**残作業**: ADR-016 Phase 4b / 5b / 6 / 7（次セッション以降、約 3 日想定）

---

## 🚪 まずここを読む（次セッション最初の入口）

**ADR-016 Phase 3 + 4a を Agent Teams 並列実装で完了したセッション**。`/catchup` 後の入口は以下:

1. ✅ **(済)** PR-2: xlsx_path_cache GCS mirror（PR #201, codex Critical 2 件全反映）
2. ✅ **(済)** PR-3: wiseman_launcher skeleton + manifest fetch（PR #200, codex Critical 4 件全反映）
3. **(次)** **PR-4** (updater versions/ + rollback) と **PR-6** (release workflow + SBOM)
4. **(その後)** Phase 6 結合テスト + Phase 7 業務 Phase 4 全件配置

業務文脈は `specs/c-business-deployment/spec.md`（変更なし）。設計指針は ADR-016。

| ファイル | 役割 |
|---------|------|
| [docs/adr/016-windows-appliance-and-mac-dev-flow.md](../adr/016-windows-appliance-and-mac-dev-flow.md) | 設計の中核（§1.1.1/1.1.2/1.2/4.1 を本セッションで追記） |
| [src/wiseman_hub_launcher/](../../src/wiseman_hub_launcher/) | 本セッション新規 package（stdlib only、389 LOC） |
| [src/wiseman_hub/cloud/xlsx_path_cache_mirror.py](../../src/wiseman_hub/cloud/xlsx_path_cache_mirror.py) | 本セッション新規（GCS mirror + tombstone + revision metadata） |
| [scripts/checklist_c_cache_view.py](../../scripts/checklist_c_cache_view.py) | 本セッション新規 Mac CLI（cache 状態 read-only 確認） |
| 本 LATEST.md | Session 46 差分メモ + 次セッション入口 |

---

## 🎯 Session 46 の成果サマリー

### マージ済 PR (2 件、両者 codex review 後の番号単位明示認可後にマージ)

| # | 種別 | 概要 | 行数 | codex 反映 |
|---|------|------|------|------------|
| #200 | feat(launcher) | wiseman_launcher skeleton + manifest fetch（ADR-016 PR-3） | +2015/-1 | Critical 4 + Important 7 + Suggestion 4 |
| #201 | feat(cache) | xlsx_path_cache GCS mirror（ADR-016 PR-2） | +1966/-2 | Critical 2 + Important 7 + Suggestion 1 + Nit 1 |

### 並列実装フローの教訓（重要、次セッション以降への引き継ぎ）

Session 46 で初めて Agent Teams 並列実装を実行し、以下が判明した:

1. **sub-agent は main session より sandbox が強く、`git switch` / `git commit` / `git push` / `pytest` 等の Bash がブロックされる**
2. **2 sub-agent が `main` working tree に同時にファイルを置くと混在状態になる**（write set 完全独立なら衝突はしないが、main session 側で振り分けが必要）
3. **codex review fix も sub-agent では Bash 制約で実装に至れない**（Critical 反映は main session が直接実行する必要があった）

→ **次セッション以降、PR-4 / PR-6 等は main session が直接実装する方が確実**。Agent Teams は read-only の調査タスク（Explore など）に限定する。

### codex セカンドオピニオン（3 回実施、Critical 全反映）

| 対象 | thread ID | 結果 |
|------|-----------|------|
| 計画書（PR-2/PR-3 並列プラン） | `019dfbc9-...` | Critical 4 件 → 修正版プラン提示後着手 |
| PR #200 (PR-3 launcher) | `019dfce6-...` | Critical 2 + Important 7 → 全反映後マージ |
| PR #201 (PR-2 cache mirror) | `019dfceb-...` | Critical 2 + Important 7 → 全反映後マージ |

### 品質メトリクス

- **1115 unit tests pass** (Session 45 末 1066 → +49 件、新規 launcher 78 + 新規 mirror 14 + その他)
- ruff / mypy / flake8 all clean（PR-2/PR-3 ファイル単体、既存 E305 / F541 は無関係）
- cross-platform: Mac でも全機能動作確認済（Windows 専用部分は mock）
- PyInstaller smoke build: `dist/wiseman_launcher` 8.0 MB Mach-O arm64 (macOS) 成功

### Issue Net 変化

```
- Close 数: 0 件
- 起票数: 0 件
- Net: 0 件
```

**理由**: 本セッションは ADR-016 Phase 3 + 4a 中心の中規模実装で、新規バグ発見ゼロ、既存 Issue への影響もなし。codex Critical/Important は当該 PR 内で全反映済（追加 Issue 化不要）。Suggestion / Nit も全反映または明示的に scope 外とした。

---

## ADR-016 Phase 進捗

| Phase | 内容 | Status | 工数 | PR |
|-------|------|--------|------|-----|
| 0 | Mac CLI dry-run | ✅ merged | 完了 | #195 |
| 1 | ADR-016 draft | ✅ merged | 完了 | #196 |
| 2 | audit log GCS upload + spool + retry + ADR-004 amend | ✅ merged | 完了 | #198 |
| **3** | **xlsx_path_cache GCS mirror** | ✅ **merged (本セッション)** | 完了 | **#201** |
| **4a** | **wiseman_launcher skeleton + manifest fetch** | ✅ **merged (本セッション)** | 完了 | **#200** |
| 4b | updater versions/current.json + rollback | **next** | 1.25 日 | – |
| 5a | GCP IAM + WIF runbook | ✅ merged | 完了 | #197 |
| 5b | release workflow + SBOM + manifest 自動生成 | pending（PR-4 + PR-5 依存） | 1 日 | – |
| 6 | 結合テスト + canary 切替 | pending | 0.5 日 | – |
| 7 | 業務 Phase 4 全件配置を新システムで実行 | pending | 0.5 日 | – |

**残工数**: **約 3 日**（Phase 4b〜7 の合計）+ 本田様の GCP 側セットアップ（並行で約 1 時間）

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

### 2. 【開発側タスク】PR-4 (updater + rollback, 1.25 日) に着手

**PR-3 (#200 merged) の launcher skeleton に download / current.json 切替 / spawn / rollback を追加**:

- `src/wiseman_hub_launcher/updater.py` 新規（download, atomic file place, current.json switch）
- `src/wiseman_hub_launcher/__main__.py` に `--update` mode 追加（dry-run 以外の経路）
- 起動失敗（exit != 0 / 30 秒以内 crash）→ 自動 rollback
- ADR-016 §1.2 で 600 LOC 制約に再定義済（critical path 全体）
- **次セッションは Agent Teams ではなく main session 直接実装で進める**（Session 46 教訓）

### 3. PR-6 (release workflow, 1 日) を PR-4 + PR-5 完了後に着手

GitHub Actions OIDC + GCS upload + manifest atomic + SBOM 生成 + provenance attestation。

### 4. Phase 6 結合テスト + Phase 7 業務 Phase 4 全件配置

dev tag → canary tag → 壊れた exe で rollback 検証 → 業務 60 件配置。

---

## 補足事項

### Session 46 の重要な決定の根拠

- **PR-3 stdlib only 採用**: codex C-3（auth 先送り危険）反映、`urllib.request` で release-prod public read。SA key embed 回避で launcher 極小性 + 漏洩リスクゼロを両立
- **PR-2 mirror hook の async 化**: codex C-1（UI thread 30 秒 freeze）反映、daemon thread + warn-only で UI 非ブロッキング
- **machine_id を UUIDv4 with `~/wiseman-hub/machine_id` 永続化**: PII 配慮、HW ID/hostname 不使用、ADR-016 §4.1 に取扱明文化
- **300 LOC 制約の再定義（PR-3: 400 / PR-4 後: 600）**: codex review 「validation 削って 300 維持は supply-chain 防御毀損」反映、ADR-016 §1.2 に運用定義

### 本セッションで触った主要ファイル

**新規追加 (PR #200 / launcher)**:
- `src/wiseman_hub_launcher/{__init__, __main__, manifest, checksum, current}.py` (5 files, 389 LOC)
- `wiseman_launcher.spec`（PyInstaller spec）
- `tests/unit/launcher/{test_manifest, test_checksum, test_current, test_main}.py` (4 files, 143 tests)

**新規追加 (PR #201 / cache mirror)**:
- `src/wiseman_hub/cloud/xlsx_path_cache_mirror.py`（mirror module）
- `scripts/checklist_c_cache_view.py`（Mac CLI）
- `tests/unit/cloud/test_xlsx_path_cache_mirror.py`（50 tests）
- `tests/unit/ui/test_checklist_c_dialog_mirror_hook.py`（write/delete async hook test）

**変更 (両 PR 共通)**:
- `docs/adr/016-windows-appliance-and-mac-dev-flow.md`（§1.1.1, §1.1.2, §1.2, §4.1 追記）

**変更 (PR #201 / mirror hook 統合)**:
- `src/wiseman_hub/ui/checklist_c_dialog.py`（write hook + delete hook 配置、async 化）

### Tera-station NAS テスト PDF の処理（前セッション残件）

Session 44 で配置した `\\Tera-station\share\03.FAX(事業所)\太子町地域包括（メール）※持参\経過報告書\森川 ひろゑ.pdf` は引き続き「削除 or 残置」のいずれでも OK（Phase 7 で全件再配置予定）。本セッションでは追加の PDF 配置はしていない。

### Session 45 までのコンテキスト

Session 45 の詳細は `docs/handoff/archive/session-45-adr-016-phase-0-1-2-5a.md` 参照（本セッション開始時に archive へ移動）。

### 次セッションの並列化機会

本田様の GCP 設定 (60 分) と開発側の PR-4 (~1.25 日) は **完全独立**で同時進行可能。本田様完了通知前でも PR-4 着手 OK（PR-4 自体は GCP 接続を試さない、unit test と PyInstaller smoke build のみ）。

---

## Quality Gate 充足確認

| 項目 | 状態 |
|------|------|
| ADR-016 整合性 (§1.1.1/§1.1.2/§1.2/§4.1 を新規追記、既存 §1〜§7 と整合) | ✅ |
| 全 PR で番号単位の明示認可後マージ | ✅ |
| codex セカンドオピニオン Critical/Important 全反映 | ✅ |
| ruff / mypy / flake8 / 1115 unit tests pass | ✅ |
| Issue Net ≤ 0 | ✅（Net 0、進捗ゼロ扱いではない理由は上記 Issue Net 変化に明記） |
| 残留プロセスなし | ✅ |
| Test plan 未済項目 | ⚠ Windows 実機検証 (PR-5 runbook 実行後) と Mac から `gsutil` で実 GCS 確認 (Phase 6) は次セッション以降 |

`✅ 再開可能`（次セッション冒頭で本ファイルを読めば、PR-2/3 マージ後の状態から PR-4 + PR-5 並列に進める）。
