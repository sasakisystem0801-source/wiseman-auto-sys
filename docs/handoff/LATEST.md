# Handoff: Session 31 完了（PR #141 merged + PR #142 close 保留）

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
