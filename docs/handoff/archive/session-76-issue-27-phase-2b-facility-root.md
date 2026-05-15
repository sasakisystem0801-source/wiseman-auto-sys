# Session 76 完了 — Issue #27 続編 G Phase 2b (PdfMergeConfig.facility_root_dir Path 化) 完遂

**Date**: 2026-05-15
**Main HEAD**: `98a0171` feat(config): Phase 2b Path 型移行 (PdfMergeConfig.facility_root_dir) — Issue #27 続編 G §4 (#301)
**Test count**: 1956 passed, 104 skipped (Phase 2a 1949 + Phase 2b 7 件新規)
**Active Issues**: 12 (実質 7、postpone 5) [変化なし、Net 0]
**Phase**: Phase 7 着手前 [変化なし]

---

## セッション経緯

Session 75 ハンドオフ (PR #299/#300) 完了状態から `/catchup` で再開。ユーザー指示
「次のアクション（優先度順）すすめて」で確定方針通り Phase 2b 着手。

実装フロー:
1. Phase 2a (PR #298) の patterns を踏襲: `PdfMergeConfig.facility_root_dir` を `str` → `Path` 化
2. consumer 整合 (`ui/facility_root_dialog.py` / `ui/ex_extractor_dialog.py`)
3. テスト追加・更新 (Phase 2b 新規クラス 7 件 + 既存 assertion を Path 比較化)
4. Quality Gate 4 段 (code-reviewer / evaluator / `/codex review`)
5. PR #301 作成 → CI 全 5 ジョブ PASS → ユーザー承認 → squash merge

ユーザー承認: 「このまま squash merge して」明示認可で merge 完了。

---

## 完了内容

### Issue #27 続編 G Phase 2b 完了 (PR #301 merged, main `98a0171`)

6 ファイル変更、+173/-55 行。

#### `config.py`: 残り 1 field を Path 化

| 旧 | 新 |
|---|---|
| `facility_root_dir: str = ""  # Phase 2b で Path 化予定` | `facility_root_dir: Path = field(default_factory=Path)` |
| `__post_init__` で `_check_path` 3 件 | 4 件 (input/output/ex_source/facility_root) |
| `load_config` の `coerce_path` for ループ 3 field | 4 field |

これで `PdfMergeConfig` の Path 性フィールド (input_dir / output_dir / ex_source_dir / facility_root_dir) は **全 4 件が Path 型に統一**。

#### consumer 整合性

| ファイル | 変更 |
|---|---|
| `ui/facility_root_dialog.py` | `is_path_configured` import、`set_root_and_rows` で `facility_root_dir=str(root)` → `facility_root_dir=root` (Path 直接)、初期化時 `tk.StringVar` を `is_path_configured` で gate、自動スキャン分岐の `Path(...)` 重複ラップ除去 |
| `ui/ex_extractor_dialog.py` | ViewModel 初期化を Phase 2a の ex_source_dir パターン踏襲 (`Path(config.pdf_merge.facility_root_dir or ".")` → `config.pdf_merge.facility_root_dir`) |

#### Quality Gate 履歴 (CLAUDE.md MUST 全実施)

| ステップ | 結果 |
|---------|------|
| 統合 review (8 観点) | Critical/High 0、Medium 2 (M-1 Phase 2a 設計判断踏襲で対応不要、M-2 frozen parametrize の path field 4 件を `Path` 化で意図明確化) |
| `evaluator` 分離 (5+ ファイル発動) | HIGH 1 件 (`_redraw` の `Path("").exists()` で `"."` Label 表示) は **Phase 2a で確立された既存挙動の継承**、Phase 2b 前 (`Path(config.pdf_merge.facility_root_dir or ".")`) と等価挙動 (`Path("") == Path(".")` で `.exists()` True、`str()` `"."`) のためスコープ外、handoff debt #2 として記録 |
| **`/codex review` セカンドオピニオン** ([thread 019e28b3-09b9-7ee2-9071-06c5c0f1a626]) | **APPROVE**、修正必須指摘なし |

#### Phase 2a 設計判断との一貫性

- **個別プロパティを追加しない**: `is_facility_root_configured` 等を作らず、consumer は `is_path_configured(cfg.pdf_merge.facility_root_dir)` 直呼び (Phase 2a の `is_input_configured` 等を作らなかった「helper 集約」原則踏襲)
- **`stringify_paths_recursive` は field 名非依存**: 新規 field 追加でカバー範囲は自動拡張、新規テスト不要

---

## ⚠️ 注意事項 / 次セッション着手前確認

### 1. 次セッション最優先: **exe 配布実行** (確定方針、Session 75 ハンドオフから継承)

Session 75 終了時にユーザーと合意した配布タイミングが Phase 2b merge で成立:

- ✅ Phase 2b 完了 (PR #301 merged)
- ⏭️ exe 配布 7 ステップ実行 (`docs/handoff/1c-exe-redistribution-runbook.md` Phase 0-5 準拠)

#### exe 配布 7 ステップ

| # | 操作 | コマンド |
|---|------|---------|
| 1 | リポジトリ最新化 | `cd $HOME\Projects\wiseman-auto-sys; git checkout main; git pull --ff-only` |
| 2 | 現行 exe を `.bak-<stamp>` でバックアップ | `Copy-Item "$dist\wiseman_hub.exe" "$dist\wiseman_hub.exe.bak-$stamp"` |
| 3 | 依存同期 + テスト (integration 除外) | `uv sync --extra dev; uv run pytest -q -m "not integration"` |
| 4 | clean ビルド | `uv run pyinstaller wiseman_hub.spec --clean --noconfirm 2>&1 \| Tee-Object -FilePath build.log` |
| 5 | build.log warning 検査 | `Select-String -Path build.log -Pattern "Hidden import.*not found"` (pycparser.lextab/yacctab / jinja2 / user32 / msvcrt のみなら無害) |
| 6 | 配布先に上書き | `Copy-Item -Force dist\wiseman_hub.exe "$dist\wiseman_hub.exe"` |
| 7 | Launcher 起動 + 実機検証 | `Start-Process "$dist\wiseman_hub.exe"` |

所要時間: 30-45 分。手順 1-6 は AI 伴走 (TeamViewer 経由 PowerShell)、手順 7 は本田様の確認も含む。

### 2. 実機検証 7 件 (Phase 2b 配布タイミング、本セッションで Path 移行 Phase 2b 追加)

| Issue / PR | 検証項目 |
|---|---|
| #274 Phase 1 | B/C ダイアログ詳細列 500px 表示 + 横スクロール動作 |
| #282 | `monitoring_subfolder/R7/<月>.pdf` 配置成功 / 旧構造 regression なし |
| Launcher 5 ボタン (PR #285) | 5 ボタン表示確認、業務フロー順 |
| #27 続編 F Phase 2/2-b の log_level 反映 | `[app] log_level = "DEBUG"` を書いて Launcher 起動 |
| PR #294 trust root WARNING | "sigstore trust root EXPIRED 268+ days ago" log |
| PR #296 Path 型移行 Phase 1 | 既存 `config/default.toml` を Path 化 load_config が正しく解釈 |
| PR #298 Phase 2a | `pdf_merge` セクション (`input_dir` / `output_dir` / `ex_source_dir`) の round-trip + ex_extractor 経路で `coerce_path` 動作 + PDF 結合機能で `cfg.input_dir` を Path 直接受取 |
| **NEW: PR #301 Phase 2b** | `pdf_merge.facility_root_dir` の round-trip + facility_root_dialog で `is_path_configured` gate 動作 (未設定時に StringVar が "" に、`"."` が出ないこと) + ex_extractor 経路で `config.pdf_merge.facility_root_dir` を Path 直接受取 |

### 3. 新規 handoff debt (本セッション発見 / 整理)

#### debt #1 (継承): Windows OS 差テストの事前検出
- Session 75 から継承、Phase 2b では `str(Path(...))` パターン徹底で対応、CI 全 PASS で gate 済
- Phase 3 で UNC パス (`\\Tera-station\share\...`) を扱う際は **より深刻**: UNC は OS 固有経路のため Mac runner では `PosixPath('//Tera-station/share/...')` に化けて意味的に違う
- 対策案 (Phase 3 着手時): `pytest.mark.windows_only` で gate / Mac セッションで実装後 push 前に `pytest tests/unit/ui/ -q` で全件 PASS 確認 + CI で OS 別検証

#### debt #2 (NEW): `_redraw` の `Path("").exists()` Label 表示問題 (Phase 2a 既存挙動)
- `ui/ex_extractor_dialog.py:559-563` で `_lbl_facility_root` / `_lbl_source` は `text=str(self._vm.X) if self._vm.X.exists() else _LBL_NOT_SET`
- `Path("") == Path(".")` で `.exists()` True (CWD 存在前提)、`str(Path(""))` `"."` → 未設定状態が `"."` として表示される silent UX 劣化
- **Phase 2a で確立済の挙動**、Phase 2b 前 (`Path(config.pdf_merge.facility_root_dir or ".")`) との挙動差ゼロのため Phase 2b スコープ外
- 修正案 (将来): `is_path_configured` で明示 gate して `_LBL_NOT_SET` 表示に切替え。`source_dir` (Phase 2a) と `facility_root_dir` (Phase 2b) の両方で同パターン
- triage 基準 (rating ≥ 7 / 実害 / CI 破壊 / 明示指示) 未達のため Issue 化せず handoff debt 記録、実機検証で本田様が気付いた場合に対応

#### debt #3 (継承): `Optional[Path]` 設計議論
- Phase 3 で `karte_root` / `fax_root` (UNC パス、`Path(".")` を意図する用例ゼロ) を扱う際は sentinel 問題が顕在化しにくい
- ただし umbrella §G の続編として **Phase 3 着手前に設計議論**: `Path | None` への移行か、現状の `Path("")` sentinel 維持か
- 判断材料: Phase 2a/2b で `is_path_configured` の strip 拡張 + `stringify_paths_recursive` で「`Path("")` ↔ `""` 双方向変換」が確立済。`Optional[Path]` に移行する技術的メリットは限定的、consumer の `is None` 判定置換コストが高い

### 4. 引き続き保留中の handoff debt

#### Windows Tcl init.tcl ランダム fail 問題 (Session 73 発見、rating 6 で Issue 化基準未達)
- 暫定対応: re-trigger で逃げる (本セッションでは発生せず)
- follow-up 候補: `TCL_LIBRARY` / `TK_LIBRARY` 環境変数明示設定

#### Issue #282 Codex 残指摘 4 件 (Session 71 で triage 済、rating 4-6)

### 5. Mac セッション着手不可項目 (前セッション継承、変化なし)

- #17 (smoke_real.py pytest 統合)
- #16 (test_new_registration_flow Pane/Text 経路)
- #11 (PywinautoEngine MEDIUM 5 件)
- #6 (PoC E2E)

### 6. PowerShell 廃止 epic 候補 (本セッション再確認)

本田様の明示要求 (2026-05-06): 「Windows側でなるべくは PowerShell を使わなくても、開発や保守メンテナンスやアップデートやテストなどが出来ること」

現状:
- `src/wiseman_hub/updater/` は `__init__.py` のみの空スタブ
- ADR-004 (GCS manifest polling auto-update) は 2026-03-22 Accepted だが **実装未着手**
- ADR-016 (Mac-from-GCP 開発フロー + bootstrapper/updater 分離) は 2026-05-06 **Proposed のまま**
- 配布は引き続き `docs/handoff/1c-exe-redistribution-runbook.md` の PowerShell 5 コマンド手動

着手するなら別 epic として: ADR-016 を Accepted に昇格 → `updater/` + bootstrapper 実装 → release バケット用意 → GitHub Actions OIDC 設定。Issue #27 続編 G とは独立。

---

## 次セッション優先順

### 次セッション実行手順 (確定)

1. **exe 配布 7 ステップ実行** (Phase 2b PR #301 merge 直後、`docs/handoff/1c-exe-redistribution-runbook.md` 準拠)
   - 手順 1-6 を AI 伴走 (TeamViewer 経由 PowerShell)
   - 手順 7 で実機検証 7 件 (#274 / #282 / Launcher 5 ボタン / log_level / trust root WARNING / Path Phase 1 / Path Phase 2a + 2b) を本田様と一緒に確認

2. **実機検証結果を LATEST.md に記録** (Session 77 終了時)
   - 残課題: Phase 3 (UNC パス、`Optional[Path]` 設計議論)、Issue #275、handoff debt #2 (Label 表示) の本田様反応

### 配布後の次々セッション以降

3. **Issue #275** — 本田様ヒアリング待ち (実機配布時に同時実施推奨)
4. **Phase 3 着手前の `Optional[Path]` 設計議論** — handoff debt #3、Phase 3 計画段階で扱う
5. **Issue #27 続編 G Phase 3** — Phase 2b 完了後、UNC パステスト追加必須 (debt #1)
6. **handoff debt #2** — 実機検証で本田様が `"."` 表示に気付いた場合に修正、未指摘なら継続観察
7. **Windows Tcl init.tcl 問題** — handoff debt 継続
8. **PowerShell 廃止 epic** — 別途独立して着手判断 (本セッション再確認、ADR-016 昇格 + updater 実装)

---

## 構造的整合性チェック

- ⏭️ `/impact-analysis`: PdfMergeConfig 1 field の型変更で 6 ファイル / 30 参照に波及。consumer 整合性確認は pytest 1956 件 PASS + mypy clean で gate 済、CI 全 5 ジョブ PASS で OS 横断検証済
- ⏭️ `/new-resource`: 新規 helper 追加なし (Phase 2a で確立した `coerce_path` / `_check_path` / `is_path_configured` / `stringify_paths_recursive` を流用)
- ⏭️ `/trace-dataflow`: TOML str → Path (load_config) → consumer Path API → str (save_config _stringify_path_values shallow) / JSON str (session._to_dict stringify_paths_recursive 任意深度) の双方向データフロー、Phase 2a で確立した規約を facility_root_dir にも適用、新たなデータパスなし

---

## Issue Net 変化

```
## Issue Net 変化
- Close 数: 0 件
- 起票数: 0 件
- Net: 0 件
```

**Net = 0 だが進捗実体あり**:

- **PR #301** で Issue #27 §4 Phase 2b (facility_root_dir Path 化 + consumer 整合) 完遂
- `PdfMergeConfig` の Path 性フィールド 4 件 (input/output/ex_source/facility_root) が全て Path 型統一達成
- Issue #27 umbrella は Phase 3 + `Optional[Path]` 設計議論が残るため close 不可
- 新規 Issue 起票はゼロ。本セッション発見の 1 件の懸念 (handoff debt #2: `_redraw` Label 表示) は Phase 2a 既存挙動継承 + triage 基準未達のため handoff debt 記録で吸収

triage 遵守: 機構化済み 3 層ゲートに従って Net ≤ 0 を維持。

Quality Gate 全 4 段を実施し、`/codex review` セカンドオピニオンで **APPROVE** 取得。本セッションの白眉:
1. **Phase 2a 設計判断との完全踏襲**: 新規 helper ゼロ、新規プロパティゼロ、既存 4 helper (`coerce_path` / `_check_path` / `is_path_configured` / `stringify_paths_recursive`) のみで Phase 2b を成立
2. **OS 中立性の徹底**: テスト assertion で `Path` 同士比較に統一 (Phase 2a debt #1 対策)、UNC パスは `Path("//Tera-station/share/...")` で表現し OS 差を回避
3. **evaluator の predictive 検出を Phase 2a 既存挙動継承と切り分け**: HIGH 指摘 1 件を実証 (`Path("") == Path(".")` の `.exists()` / `str()` 等価性) で Phase 2b 前後挙動差ゼロを確認、scope 厳守

---

## ✅ 残留プロセスなし

CI: ✅ Phase 2b PR #301 の全 5 ジョブ PASS (build-smoke 2m42s / test-integration 2m29s / test-unit 3.11 47s / test-unit 3.12 49s / test-windows-ui 56s)。main push 後の追加 Build Windows Smoke は本ハンドオフ作成時点で in_progress、結果未確定 (前 commit `6ba5b78` の同ジョブ PASS から大きな差なし見込み)。
