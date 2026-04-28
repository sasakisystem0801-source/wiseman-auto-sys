# Handoff: Session 33 完了 - PR #146/#147 マージ + Issue Net -3 件

**更新日**: 2026-04-28（Session 33 / Issue #45 + #14 完了 + #40 検討 close）
**ブランチ**: main
**main HEAD**: `7de14ee` refactor(rpa): export_csv 失敗モードを ExportCsvError 階層で区別化 (Closes #14) (#147)

## Session 33 進捗

### マージ済 PR (Issue Net -3 件)

| PR | Issue | 内容 | 規模 |
|----|-------|------|------|
| #146 (607ad29) | #45 完了 ✅ | SourceKind を Literal から StrEnum に統一 (JSON 検証一元化) | 4 ファイル / +101 / -22 |
| #147 (7de14ee) | #14 完了 ✅ | export_csv 失敗モードを ExportCsvError 階層 (5 サブクラス) で区別化 | 6 ファイル / +280 / -35 |

### 検討して close した Issue
- **#40** (CLOSED not planned): B/C 異名 distance 0 マッチエッジケース
  - impl-plan 起動 → 数学的に「両方 distance 0 + 異名」は matcher の評価関数の対称性により発生不可能と判明
    - distance = `_levenshtein(target_normalized, normalize_name(extracted))` なので、両方 distance 0 ⇒ `normalize_name(B_extracted) == normalize_name(C_extracted)` が必ず成立
  - revert + Issue コメントに検討プロセス記録 (実装前に dead code 発見できた Generator-Evaluator 分離の成功例)

### Issue Net 変化（Session 33 全体）
- **Close: 3 件** (#45 / #40 / #14)
- **起票: 0 件**
- **Net: -3 件** ✅ (KPI 大幅進捗)

### Quality Gate 適用実績
- impl-plan 全 PR で AC 定義 (PR #146: AC-1〜8、PR #147: AC-1〜11)
- safe-refactor: PR #146 (HIGH 0 / LOW 1 修正不要)、PR #147 (HIGH 1 selector DRY → 修正済)
- evaluator: PR #147 で REQUEST_CHANGES → AC-6 close_current_window スキップで対応
- review-pr 6 エージェント並列: 両 PR で実施
- Codex review (セカンドオピニオン): 両 PR で GO 判定。PR #147 で印刷ボタン取得失敗 (rating 7、6 エージェント見落とし) を発見、ユーザー判断で本 PR スコープ外

### 学び（次セッション以降の自衛策）

1. **`patch.dict(sys.modules)` の落とし穴**: `with patch.dict(sys.modules, _fake_mods):` は with 終了時に「with 内で追加された全キー」を削除する。新規例外クラスの `from wiseman_hub.rpa.base import (...)` を with **後**に置くと、with 内で base が初回 load → with 終了で削除 → テストの再 import で別クラス → `pytest.raises(...)` が isinstance チェックでマッチしない事象が発生。**新規 import は patch.dict ブロックの前に置く**こと。tests/unit/test_pywinauto_engine.py:57-69 にコメント記録済。

2. **Issue 起票時の前提が誤りの場合の対応 (#40 教訓)**: impl-plan 段階で「実装すべきガードが数学的に dead code になる」ことが判明したら、即座に revert + Issue close (not planned) + 検討プロセスを Issue コメントに記録。「コードを書いてから dead code merge」を防ぐ Generator-Evaluator 分離の価値が顕在化した事例。

3. **Codex review が 6 エージェントレビューで見落とした観点を発見**: PR #147 で 6 エージェント (code-reviewer / pr-test-analyzer / silent-failure-hunter / type-design-analyzer / comment-analyzer / code-simplifier) 全員が見落とした「印刷ボタン取得失敗が ExportCsvError 階層外で pipeline 全停止」を Codex が発見。**大規模 PR (3+ ファイル / 200+ 行) では `/codex review` セカンドオピニオンが価値あり** の根拠データ。

### Session 33 で発見した follow-up 候補 (本 PR では起票見送り)
- **印刷ボタン取得失敗の ExportCsvError 階層編入**: Codex 指摘 (PR #147)、Windows 実機で観測時に起票判断
- **メインウィンドウ未接続例外の階層編入**: type-design 指摘 (PR #147)、設計判断 ADR 化推奨
- **その他 rating 5-6 の review 指摘**: PR #146/#147 のレビューサマリコメント参照

### 次セッション候補

#### macOS 完結可能 (Codex Top 3 推奨順)
- **#27**: config dataclass 全体の型設計強化 (Literal + `__post_init__` 検証)
  - Codex 評価: 範囲を絞れば中-高。**AppConfig 全体に触ると PR5 検証範囲拡大リスク** あり
  - 推奨: 「Literal 追加のみ」にスコープ限定、path 必須化や空文字禁止は避ける
- **#29**: OCR proxy nice-to-have 改善 (非root/例外絞込/429テスト等)
- **#39**: フリガナベース matching (#40 は本セッションで close)

#### Windows 復帰時の最優先 (Session 32 から継続)
- PR5 ex_extractor 統合の AC-1 (3) 〜 AC-14 実機検証 (詳細は下記「Session 32 残未完作業」参照)

### 次回再開コマンド

```bash
cd /Users/yyyhhh/Projects/wiseman_auto_sys
git checkout main && git pull --ff-only
# main HEAD が 7de14ee（PR #147）であることを確認
gh issue list --state open
```

### Open Issue 推移
- Session 33 開始時: 10 件 (P2 enhancement のみ)
- Session 33 終了時: 7 件 (#45/#40/#14 close)
- 残り P2: #134 (monitor), #63 (monitor), #27, #39, #29, #17, #16

### Git 状態 (Session 33 終了時点)
- main HEAD: `7de14ee`
- ローカル clean / origin 同期済
- ブランチ: main
- CI: success (Windows Integration Tests / build-smoke / test-unit 3.11/3.12 / test-integration 全 PASS)

---

# 旧サマリ: Session 32 中断 + macOS 側 A1-A5 検証準備整備完了

**更新日**: 2026-04-28（Session 32 / Windows 実機中断後、macOS 側で A1-A5 マージ済）
**ブランチ**: main
**main HEAD (当時)**: `cf9f8b1` docs(handoff): Session 32 中断記録 + PR5 検証準備整備 (A1-A5) (#144)

## Session 32 進捗

### 午前: Windows 11 実機（TeamViewer 経由）

- **Phase 0 完了**: exe バックアップ（`wiseman_hub.exe.bak-20260428-075301`）+ `git pull --ff-only`（`f4a242e` 同期）+ `uv sync --extra dev`
- **Phase 1 完了**: PyInstaller ビルド成功（78,632,876 bytes / 2026-04-28 8:00:08、warning 既知の `pycparser` / `jinja2` のみ、`wiseman_hub.*` 由来 0 件）
- **Phase 2-1 完了**: 新 exe を `~/wiseman-hub/wiseman_hub.exe` に配備（旧版 78,570,672 → 新版 78,632,876、+62 KB は PR4 UI 統合分）
- **AC-1 (1)(2) PASS**: Launcher 起動（コンソール非表示）+ 5 ボタン目「ex_ ファイル変換 + 振り分け」表示確認（スクショ取得済）
- **中断**: TeamViewer タイムリミットで AC-1 (3) 未実施

### 午後: macOS 側 A1-A5 検証準備整備（PR #144 マージ済）

Codex セカンドオピニオン + /review-pr 3 並列レビュー（comment-analyzer / code-reviewer / code-simplifier）を経て:

- **A1**: runbook §2-2 config パス誤記修正（`config.toml` → `config\default.toml`、frozen exe の実解決パス）
- **A2**: `config/test.toml.example` 新規 + `WISEMAN_HUB_CONFIG` 経路で本番 NAS 非汚染（`__main__._default_config_path` 既実装を活かす）
- **A3**: `session32-...md` AC-1 (3) 実機チェックリスト精緻化（exe LastWriteTime 事前確認、「実行ボタン押下禁止」の理由明記、rollback コマンド）
- **A4**: `docs/handoff/ex-test-fixtures.md` 新規（SUCCESS / AMBIGUOUS / UNMATCHED の 3 種 fixture 発火条件・命名・調達手順）
- **A5**: ショートカット起動の env var 非継承落とし穴を runbook §2-2 に明文化、PowerShell `Start-Process` / `.ps1` ラッパー（方式 A/B）推奨化、ユーザー環境変数永続化（方式 C）を非推奨と明記

review-pr 指摘で発見した Critical（ADR-014 §PII 保護方針違反: 実顧客名「本田」直書き）と Important（`sasak` ハードコード、行番号ズレ、AMBIGUOUS 例の文字数説明矛盾、ショートカット起動説明 3 重複）も同 PR で修正反映済（commit `573da44`、+406 → +313 net）。

### 残未完作業（次回 Windows 実機セッション）

- **AC-1 (3)**: 5 ボタン目クリック → `ExExtractorDialog` 起動確認（[`session32-pr5-ex-extractor-ac1-resume.md`](./session32-pr5-ex-extractor-ac1-resume.md) §1 のチェックリストに沿う）
- **デスクトップショートカット経由起動確認**: 新 exe（78,632,876 bytes）が起動することを確認（resume note §2）
- **AC-2〜AC-14**: A1-A5 で整備した `test.toml` + `WISEMAN_HUB_CONFIG` 方式 B（`.ps1` ラッパー）+ 3 種 fixture を使って実施（[`pr5-ex-extractor-runbook.md`](./pr5-ex-extractor-runbook.md) §2-2 + [`ex-test-fixtures.md`](./ex-test-fixtures.md)）

### Issue Net 変化（Session 32 全体）

- **Close**: 0 件
- **起票**: 0 件
- **Net: 0 件**

中断中の準備フェーズで Net ≤ 0 だが、「進捗ゼロ扱い」基準の対象外（実機検証フェーズ途中で、コード変更や Issue 起票判断は AC-1 完走後にまとめて発生する設計）。AC-1 完走 + ADR-014 Accepted 昇格時に Issue Net 進捗を再計上する。

### 発見事項の対策状況

| # | 中断時の発見事項 | 状態 |
|---|----------------|------|
| 1 | runbook §2-2 config パス誤記 | ✅ A1 で修正、PR #144 マージ済 |
| 2 | Launcher 未使用ボタン削除提案 | ⏳ AC-1 完了後にユーザー確認 + 別 Issue + 別 PR |
| 3 | 本番 NAS 汚染防止 + 検証用 .ex_ fixture | ✅ A2 (test.toml.example) + A4 (ex-test-fixtures.md) + A5 (起動方式) で対策実装済、PR #144 マージ済 |

### 学び（次セッション以降の自衛策）

- **ADR-014 §PII 保護方針（実顧客名は仮名 `サービスA`/`サービスB` 等で記述）の確認漏れ**: 新規ドキュメント追加時は関連 ADR の命名規約を作業前に再確認する（review-pr で発見、過去 H-F の仮名化規約を再導入してしまった）
- **Codex セカンドオピニオンの「Released date」誤読**: 公式ドキュメント上の日付ラベルを必ず WebFetch で再検証（今回 Codex は 2026-06-17 を retire と誤読、実際は Released で retire は 2026-10-16）

### 次回再開コマンド

```bash
# Mac 側
cd /Users/yyyhhh/Projects/wiseman_auto_sys
git checkout main && git pull --ff-only
# main HEAD が cf9f8b1（PR #144）であることを確認
cat docs/handoff/session32-pr5-ex-extractor-ac1-resume.md  # AC-1 (3) 実機チェックリスト
cat docs/handoff/pr5-ex-extractor-runbook.md               # §2-2 推奨方式（test.toml + WISEMAN_HUB_CONFIG）
cat docs/handoff/ex-test-fixtures.md                       # 3 種 fixture 仕様

# Windows 機側（TeamViewer 経由、PowerShell）
# 1. AC-1 (3) 残作業: resume note §1 のチェックリスト
#    - exe LastWriteTime 確認 → 5 ボタン目クリック → Dialog 起動確認（実行ボタン押さない）
# 2. デスクトップショートカット経由起動確認: resume note §2
# 3. （AC-2〜14 へ進む場合）runbook §2-2 推奨方式 B で test.toml + WISEMAN_HUB_CONFIG 起動
```

---

# 旧サマリ: Session 31 完了（PR #141 merged + PR #142 close 保留）

**更新日**: 2026-04-27（Session 31 / PR #141 マージ後）
**ブランチ**: main
**main HEAD**: `7614635` refactor(session): tuple/Mapping 化で deep immutability 型保証 (Closes #117) (#141)

## セッション 31 の成果

### マージ済 ✅

#### PR #141 (Issue #117 — Session/UserCandidate を tuple/Mapping 化)

- squash merge `7614635`、+217 / -210 LOC、10 ファイル（src 3 + tests 7）
- スコープ: PR #116（Issue #44 完全 immutable 化）の続編。`frozen=True` 単体では防げない `.append()` 等の要素 mutation を**型レベルで禁止**する。
- 変更点:
  - `Session.candidates: list[UserCandidate]` → `tuple[UserCandidate, ...]`
  - `UserCandidate.similar_candidates: list[CandidateState]` → `tuple[...]`
  - `Session.config_snapshot: dict[str, Any]` → `Mapping[str, Any]`
  - `_to_dict` で `dict(session.config_snapshot)` 明示変換（asdict は MappingProxyType 等を再帰展開しないため）
  - `_from_dict` / `_candidate_from_dict` / `from_match_result` で `tuple(...)` 構築
  - `pipeline.py` 生成側（`(*session.candidates, candidate)`, `tuple(sorted(...))`）
  - `confirm_dialog.resolve_candidate` を tuple-based に、`_pick_first_by_kind` の引数型を `Sequence[CandidateState]` に緩和
  - tests/ 7 ファイルの fixture を `[...]` → `(...)` に置換、helper 戻り値型を tuple に統一
- JSON 後方互換性 100%（schema_version 不変、`_to_dict` で dict 化、tuple は json.dumps で array に正しく serialize）
- **多重 Quality Gate**: `/impl-plan` AC-1〜6 + evaluator (rules/quality-gate.md, MEDIUM/LOW 指摘 → 修正済) + `/simplify`（quality 軽微 2 件 → 修正済）+ `/safe-refactor`（0 件） + `/review-pr` 5 並列 + `/codex review` セカンドオピニオン（Critical 0 / Important 1 stale comment → 修正済）

### Close 保留 ⚠️

#### PR #142 (Issue #63 — Linux runner Tk wiring tests 全 skip 問題)

- 案 A（xvfb + python3-tk を test-unit.yml に追加）を試行
- Linux + xvfb 環境で `mainloop` を呼ぶ Tk async テスト（合計 11 件）が hang
- test-unit (3.11/3.12) ジョブが `Run unit tests` step で 16+ 分 in_progress 後、cancel 後 fail
- build-smoke / test-integration: PASS（影響なし）
- main は無影響（PR #142 未マージで close）
- **保留判断**: ローカル開発環境（macOS）で Linux 上の Tk 挙動を再現できず hang テストの個別特定にコスト大。本プロジェクトの配布先は Windows 実機のみで Windows runner の wiring tests でカバー範囲は MVP 許容。
- Issue #63 にコメントで保留理由・再開条件を追記、open のまま保留。

### Issue Net 変化（Session 31）

- **Close**: 1 件（**#117**）
- **起票**: 0 件
- **Net: -1 件** ✅（KPI 進捗）

### 次セッション (Session 32) の作業候補

#### 並行可能なタスク（PR5 実機検証と独立）

- **#45**: SourceKind StrEnum 統一（#117 と同系統の型 refactor、独立性高）
- **#27**: config dataclass 型設計強化（Literal + `__post_init__` 検証、#117 と関連）
- **#40**: B/C 異名距離 0 マッチのエッジケース
- **#39**: フリガナベース matching
- **#29**: OCR proxy nice-to-have 改善

#### 最優先（前セッションから継続）: Windows 11 実機検証

- runbook: `docs/handoff/pr5-ex-extractor-runbook.md`
- 所要時間: 30-45 分
- TeamViewer 経由で Windows 11 PC に接続
- AC-1〜AC-14 の PASS/FAIL を Phase 5-1 サマリテーブルに記録、PII 墨塗り済スクショ + AC-12 grep 結果取得

#### 能動作業不要（monitor）

- **#134**: Gemini 2.5 Flash retire 2026-10-16 — 再開条件 `asia-northeast1` GA 公式記載 OR 2026-09-16 retire 30 日前
- **#63**: Linux Tk wiring tests — 再開条件は Issue #63 の最新コメント参照（ローカル Linux 環境 OR pytest-timeout 知見確立 OR Windows runner 故障）

---

## 5 PR シリーズ進捗（ex_extractor 統合）

| # | スコープ | 状態 |
|---|---------|------|
| PR1 | 設定スキーマ拡張（`ex_source_dir` + `facility_aliases`） | ✅ Merged (#130) |
| PR2 | `pdf/facility_resolver` 純粋ロジック | ✅ Merged (#131) |
| PR3 | `pdf/ex_extractor` core + SFX adapter + macOS fake runner | ✅ Merged (#133) |
| PR4 | デスクトップ UI 統合（dialog + launcher 5 ボタン化 + 手動振り分け UI） | ✅ Merged (#135) |
| PR5 (A 選択) | Windows 実機検証 runbook + ADR-014 Accepted 昇格条件 | ✅ Merged (#137) |
| PR6（将来） | settings.py タブ化（実機検証で要件確定後に独立評価） | ⬜ |

---

## 重要な設計判断

### Issue #117（Session 31）— deep immutability tuple/Mapping 化の設計原則

- **frozen=True 単体では深い immutable にならない**: 属性代入は防げるが `list.append()` 等の要素 mutation は型レベルで防げない。tuple/Mapping 化で型レベル禁止に格上げ。
- **JSON シリアライズの後方互換性**: `_to_dict` で `dict(session.config_snapshot)` 明示変換（asdict は MappingProxyType を再帰展開しない）、tuple は json.dumps で array に変換 → 旧形式 (list で保存) JSON も `_from_dict` 内で `tuple(...)` で復元される。
- **テストフィクスチャも tuple 一貫性**: 個々のテストで list を渡しても Python ランタイム的には動くが、Issue #117 の「list 変更を型で防ぐ」設計意図がテスト層まで貫徹されない。evaluator 指摘で全 fixture を tuple 化。
- **mypy の `exclude = ["^tests/"]` 制約**: tests/ は型チェック対象外のため、テストの list→tuple 一貫性は機械的検証されない。round-trip テストの `isinstance(loaded.candidates, tuple)` assert で実行時保証を追加。

### Issue #63（Session 31）— Linux + xvfb で Tk async テスト hang の知見

- xvfb-run + python3-tk セットアップで Linux runner でも `tkinter.Tk()` は成功するが、`mainloop` を呼ぶ async / phase-A/B integration テスト（合計 11 件）が hang する。
- Windows runner では動作するが、Linux 環境では mainloop が escape できない可能性。
- 対応案 A は構造的に挫折。再着手時は `pytest-timeout` + 個別 `tk_mainloop` marker で hang テストを skip する戦略が候補。

### Issue #80（Session 30）— Windows smoke build の設計原則
（前セッションの記録、変更なし）

### 誤配布回避が最重要 KPI（PR3-4、runbook 直撃 AC）
（前セッションの記録、変更なし）

### PII 防御方針（ADR-014 §PII 保護方針）
（前セッションの記録、変更なし）

### Windows 専用機能の隔離
（前セッションの記録、変更なし）

### 手動 override の監査性
（前セッションの記録、変更なし）

### 状態遷移の構造化
（前セッションの記録、変更なし）

---

## ADR 状態
- 14 件すべて Status 確定（最新 ADR-014 は Proposed のまま、実機検証完走後に Accepted 昇格予定）
- §PR5 Accepted 昇格条件 で機械的判定可能な昇格条件を明記
- Session 31 で新規 ADR 追加なし（refactor のみ）

---

## 積み残し Issue

### Session 31 で起票
- なし

### Session 31 で CLOSED
- **#117**: Session.candidates / UserCandidate.similar_candidates を tuple 化 ✅（PR #141）

### Session 31 で保留判断（追加コメントのみ、open 維持）
- **#63**: Linux CI Tk wiring skip — PR #142 試行で hang 問題判明、保留

### P1（open、継続）
- **#6**: PoC E2E テスト

### P2（open、優先順）
- **#63**: Linux CI Tk wiring skip（保留）
- **#45**: SourceKind StrEnum 統一
- **#27**: config dataclass 型設計強化
- **#40**, **#39**, **#29**, **#17**, **#16**, **#14**, **#11**, **#134**

---

## impl-plan 進捗（Session 31 終了時点）

| タスク | 状態 | PR |
|--------|------|-----|
| 13D ランチャー「事業所フォルダ結合」統合 | ✅ Session 19 / 25 / 26 | #108, #126 |
| 14A-D PyInstaller / アイコン / 配布 / ADR-011 | ✅ Session 26 | #79/#60/#82, #128 |
| 事業所単位 1 ファイル仕様 | ✅ Session 24 | #124 |
| 事業所ルートフォルダ管理 + 一括/選択結合 | ✅ Session 25 / 26 | #126, #128 |
| ex_extractor PR1 設定スキーマ | ✅ Session 27 | #130 |
| ex_extractor PR2 facility_resolver | ✅ Session 27 | #131 |
| ex_extractor PR3 core 移植 + SFX adapter | ✅ Session 28 | #133 |
| ex_extractor PR4 UI 統合 | ✅ Session 28 | #135 |
| ex_extractor PR5 Windows 実機検証準備（A 選択） | ✅ Session 29 | #137 |
| Issue #80 Windows smoke build CI | ✅ Session 30 | #139 |
| **Issue #117 Session/UserCandidate tuple/Mapping 化** | ✅ **Session 31** | **#141** |
| ex_extractor PR5 実機検証実行 | ⏳ Session 32+（本田様作業） | - |
| ADR-014 Accepted 昇格 | ⏳ 実機検証後 | - |
| ex_extractor PR6 settings.py タブ化 | ⏳ 実機検証で要件確定後 | - |
| Gemini 2.5 Flash retire 対応 (monitor) | ⏳ 2026-09-16 retire 30 日前 / `asia-northeast1` GA 確認 | #134 |
| Linux CI Tk wiring tests 有効化 (保留) | ⏳ ローカル Linux 環境確保後 | #63 |
| 15 GitHub Actions + WIF | ⏳ GUI 安定後 | - |

---

## セッション再開手順（コピペ可）

### Session 32 開始時

```bash
cd /Users/yyyhhh/Projects/wiseman_auto_sys
git checkout main
git pull --ff-only
# main HEAD が 7614635（PR #141）であることを確認
gh issue list --state open
```

### 本田様の Windows 11 実機検証（TeamViewer 経由）

```powershell
cd $HOME\Projects\wiseman-auto-sys
git pull --ff-only
# docs/handoff/pr5-ex-extractor-runbook.md を notepad で開いて Phase 0 から実施
```

### 実機検証完走後の作業

1. ADR-014 Status `Proposed` → `Accepted` 昇格 PR（feature ブランチ + main 直 push 禁止 hook 経由）
2. 「### Session N 実機検証結果」サブセクションを §PR5 Accepted 昇格条件 内に新設
3. handoff/LATEST.md を Session N として更新

---

## 参照ファイル

### Session 31 成果物（最新）
- `src/wiseman_hub/pdf/session.py`: Session/UserCandidate を frozen=True + tuple/Mapping 化
- `src/wiseman_hub/pdf/pipeline.py`: 生成側を tuple 化
- `src/wiseman_hub/ui/confirm_dialog.py`: resolve_candidate を tuple-based に、`_pick_first_by_kind` を Sequence 引数化
- `tests/unit/pdf/test_session.py`, `tests/unit/test_merge_user_pdfs_cli.py`, `tests/unit/ui/test_confirm_dialog.py` 他: fixture を tuple 化、round-trip に isinstance(tuple) assert 追加

### Session 30 成果物
- `src/wiseman_hub/__main__.py`: `_run_smoke_test()` 新設 + `--smoke-test` argparse
- `tests/unit/test_smoke_mode.py`: AC-1〜AC-6 検証 5 テスト
- `.github/workflows/build-windows-smoke.yml`: Windows runner で PyInstaller + smoke

### Session 29 成果物
- `docs/handoff/pr5-ex-extractor-runbook.md`: Windows 実機検証 runbook (615 行、Phase 0-5 + AC-1〜AC-14)
- `docs/adr/014-ex-extractor-integration.md`: §PR5 Accepted 昇格条件 セクション追加 + 変更履歴

### Session 27-28 成果物
- `src/wiseman_hub/pdf/ex_extractor.py`: PR3 core (804 行)
- `src/wiseman_hub/ui/ex_extractor_dialog.py`: PR4 主ダイアログ (660 行)
- `src/wiseman_hub/ui/manual_distribution_dialog.py`: PR4 手動振り分け (615 行)
- `src/wiseman_hub/pdf/facility_resolver.py`: PR2 純粋ロジック (418 行)
- `src/wiseman_hub/config.py`: PR1 設定スキーマ拡張 (430 行)
- `tests/unit/pdf/`, `tests/unit/ui/`: 200+ テスト

### Session 26 成果物（runbook 構造の参考元）
- `docs/handoff/session26-pr126-windows-runbook.md`: 30-45 分検証フロー（Phase 0-5 構造）
- ADR-011 / ADR-013 Accepted

### 履歴
- `docs/handoff/archive/2026-04-history.md`: Session 11-21 詳細
- Session 22-26 は git log + ADR-011/012/013 + session26-pr126 runbook 参照
- Session 27-30 は git log + PR #130/#131/#133/#135/#136/#137/#138/#139/#140 参照（前バージョンの LATEST.md）

---

## 多重 Quality Gate の累積効果（5 PR シリーズ + Issue #80 + Issue #117）

| PR | Codex 計画 | Evaluator | 6 並列実装後 | review-pr 再 | 簡素化 |
|----|----------|-----------|-------------|--------------|--------|
| PR1 (#130) | - | ✅ | 4 並列 (HIGH 3) | - | - |
| PR2 (#131) | ✅ | ✅ | 5 並列 (HIGH 8) | - | - |
| PR3 (#133) | HIGH 4 + MED 3 | ✅ | 6 並列 (HIGH 6) | 6 並列 (HIGH 6 + MED 2) | - |
| PR4 (#135) | HIGH 4 + MED 3 | ✅ | - | 6 並列 (HIGH 7 + MED 3) | 1 件 |
| PR5 (#137) | impl-plan AC-PR5-1〜8 | - | - | 2 並列 (Crit 2 + Imp 5 + Sug 5) | 5 件 |
| #80 (#139) | impl-plan AC-1〜10 | - | - | 6 並列 (Crit 3 + Imp 4) | /simplify 4 件 + /safe-refactor 2 件 |
| **#117 (#141)** | **impl-plan AC-1〜6** | **MED/LOW 修正** | **-** | **5 並列 + codex (Crit 0 + Imp 1)** | **/simplify 2 件 + /safe-refactor 0 件** |

合計: HIGH 38+ / Critical 5 / 多数の Suggestions を発見・反映、production の誤配布リスクを構造的に低減し、deep immutability 型保証で誤実装リスクを構造的に低減。
