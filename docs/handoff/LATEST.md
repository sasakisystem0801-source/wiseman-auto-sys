# Handoff: "使える Windows デスクトップアプリ" 完成化計画（Session 18 終了時点）

**更新日**: 2026-04-23
**ブランチ**: main（clean、全 PR マージ済）
**main**: 23c3c95 (PR #106 squash merged: Issue #105 - session ディレクトリの stale tmp sweep 機構)

## セッション 18 の成果

### マージ済み（本セッション、2 PR 連続）
- **PR #104**: Issue #38 - `atomic_io` ユーティリティ抽出（refactor 本丸）
  - 7 files, +540/-72 lines（`src/wiseman_hub/utils/atomic_io.py` 新設 + merger / session / config 置換 + tests）
  - `write_bytes_atomically(target, payload, *, prefix)` と `save_atomically(target, writer, *, fsync, prefix)` の 2 関数で bytes 直接書込と writer callback 用途を API 分離
  - `try/finally` + success フラグで `BaseException`（KeyboardInterrupt 等）含む全例外時に tmp cleanup、元例外を上書きしない
  - merger `_save_atomically` は PdfMergeError ラップと PII ログ防御（型名のみ）を維持、置換後も既存 PII 契約テスト全通過
  - session `save_session` の旧 `except (OSError, ValueError)` 限定 catch による BaseException 時 tmp 残留リスクを atomic_io の finally で解消（堅牢化）
  - config の `_sweep_stale_tmp` の glob パターン `{path.name}.*.tmp` と整合する prefix 指定
  - **既存バグ修正**: merger の `os.replace` 失敗時に tmp が残留していた挙動を atomic_io の共通 finally で cleanup
  - **耐障害性向上**: merger / config に fsync 追加（session 相当の保証）
  - Codex plan review + Evaluator 分離プロトコル（18 AC 全 PASS）+ 6 並列レビュー（code / type / test / silent-failure / security / simplify）
  - 新規テスト 16 件（TestAtomicIO 全件）、既存テスト契約すべて維持
  - 2 commits（初版 + レビュー指摘対応: Evaluator MEDIUM 2 件 + fd lifetime 一貫性）
  - **Issue #38 CLOSED**

- **PR #106**: Issue #105 - session ディレクトリの stale tmp sweep 機構追加
  - 3 files, +329/-1 lines（`src/wiseman_hub/utils/atomic_io.py` に公開定数 `DEFAULT_TMP_GLOB` 追加 + `session.py` に `_sweep_stale_session_tmp` 追加 + tests）
  - PR #104 のセキュリティレビュー MEDIUM 指摘（プロセスクラッシュ時に PII 含む .*.tmp が session ディレクトリに平文残留する）への follow-up
  - `_sweep_stale_session_tmp(sessions_dir, *, threshold_seconds)`: mtime 60s 閾値で並行書込中 tmp を保護、`save_session` 冒頭で呼び出し
  - `atomic_io.DEFAULT_TMP_GLOB` を新規公開定数化して session 側からは参照経由に → 将来 atomic_io の prefix/suffix 変更に自動追従（Leaky abstraction 回避）
  - `except OSError` を分割:
    - `FileNotFoundError`（race で他プロセスが先に消した）は silent continue
    - 他の OSError は `Counter[type(e).__name__]` で型別集計 warning（atomic_io._cleanup_tmp の pattern と一貫）
  - `threshold_seconds: float = _STALE_TMP_THRESHOLD_SECONDS` デフォルト値化（テスト注入可能）
  - 新規テスト 11 件（TestStaleTmpSweep: sweep/保護/no-op/PII 防御/境界/race silent/型別集計/統合）
  - 2 commits（初版 + 5 並列レビュー指摘対応: Comment Critical 1 + Silent Failure MEDIUM 2 + ROI 2）
  - **Issue #105 CLOSED**

### 本セッションの Quality Gate 適用フロー

**PR #104 (atomic_io 抽出、6 files 変更)**:
1. `/impl-plan` で 5 タスク分解 + AC-1〜AC-7 定義
2. `/codex plan` セカンドオピニオン → HIGH 2 件（try/finally + PdfMergeError ラップ維持）反映
3. TDD: RED 14 tests → GREEN 実装 → Refactor（atomic_io 2 関数 + 3 置換）
4. `/simplify` 3 並列 → fsync "r+b" 修正、docstring 強化、prefix オプション追加
5. `/safe-refactor` → 型安全性・エラー処理 OK
6. **Evaluator 分離プロトコル（5+ files 発動）**: APPROVE (NEEDS_DISCUSSION) → MEDIUM 2 件対応（fd lifetime 一貫性 + session prefix コメント）
7. `/review-pr` 6 並列 → Critical 0 / Important 3 件対応（docstring 永続性 + BaseException 明記 + writer 契約）
8. Security MEDIUM 1 件（session sweep 機構なし）→ Issue #105 起票（スコープ分離）

**PR #106 (session sweep 機構、3 files 変更)**:
1. `/impl-plan` で 5 タスク分解 + 7 AC 定義
2. TDD: RED 7 tests → GREEN 実装 → Refactor
3. `/simplify` 3 並列 → Efficiency HIGH 3 件対応（`sessions_dir.exists()` 削除 + `DEFAULT_TMP_GLOB` 公開定数化 + 境界テスト追加）
4. `/review-pr` 5 並列 → Critical 1（docstring「race しない」誤り）+ MEDIUM 2（`except OSError` 分割 + 型名別集計）+ LOW 1（never-raise 契約明記）すべて対応
5. 追加テスト 4 件（getmtime race silent + unlink race silent + 型別集計）

### Issue Net 変化（本セッション）
- **Close**: 2 件（#38 = atomic_io 抽出 / #105 = session sweep）
- **起票**: 1 件（#105 = PR #104 security follow-up として Issue 化、同セッション内で close）
- **Net: -1** ✅ KPI 改善

### 総変更量（Session 18）
- 10 files changed, +869 / -73 lines
  - `src/wiseman_hub/utils/atomic_io.py`: 新規 132 行（write_bytes_atomically + save_atomically + `DEFAULT_TMP_GLOB` 公開定数）
  - `src/wiseman_hub/pdf/session.py`: atomic_io 委譲 + `_sweep_stale_session_tmp` 追加
  - `src/wiseman_hub/pdf/merger.py`: `_save_atomically` 内部置換（PdfMergeError ラップ維持）
  - `src/wiseman_hub/config.py`: `save_config` 置換
  - `tests/unit/utils/test_atomic_io.py`: 新規 358 行（16 tests）
  - `tests/unit/pdf/test_session.py`: TestStaleTmpSweep 追加 11 tests
  - `tests/unit/test_config.py`: monkeypatch 対象を atomic_io 経由に更新
- テスト件数: 475 passed → **502 passed**（+27: atomic_io 16 + session 11 + 既存置換吸収）
- skip: 63 維持
- 全ローカル検証 PASS（pytest 502 / ruff / mypy 30 source files）
- CI: 全 SUCCESS（PR #104: test-unit 3.11/3.12 各 1m / integration 2m40s、PR #106: 各 1m / integration 2m24s / 再実行 2m24s）

### Session 18 の学び
- **Evaluator 分離プロトコルが fd lifetime 非対称性を検出**: `write_bytes_atomically` は `os.fdopen(fd)` で mkstemp の fd を直接使い、`save_atomically` は `os.close(fd)` 先行で path 再オープン → 前者のみ `os.fdopen` 失敗時に fd リーク可能性（Python 3.11+ では実質解消だが、設計一貫性のため後者に揃えた）。第三者評価の価値
- **公開定数の導入で Leaky abstraction を解消**: session.py で `.*.tmp` を hard-code していたが、`atomic_io.DEFAULT_TMP_GLOB` を新設して参照経由に。将来 atomic_io の prefix/suffix 変更時に自動追従。小さな変更だが結合度を下げる
- **`except OSError` 分割パターンの運用価値**: `FileNotFoundError`（race で他プロセスが先に消した）を silent continue、その他は `Counter[type(e).__name__]` で型別集計。atomic_io._cleanup_tmp と一貫、運用者が「Permission エラー vs 消失 race」を区別可能
- **scope creep 回避**: PR #104 のセキュリティレビュー MEDIUM（session sweep なし）を当 PR に詰め込まず Issue #105 として起票 → 別 PR で対応。refactor PR は「重複除去」責務に専念

## セッション 17 の成果（サマリー）

- **PR #102**: Issue #68 - `validate_form` 戻り値 `ValidationError` enum 化
  - 2 files, +246/-52 lines
  - `ValidationCode` (StrEnum 10 種) + `ValidationError` (frozen dataclass) 導入
  - `_message_for` を `match/case` + `typing.assert_never` で mypy 網羅性静的検証
  - テスト 466 → 475 passed
  - **Issue #68 CLOSED**, Net: -1

## セッション 16 の成果（サマリー）

- **PR #100**: Issue #72 + #97 - review_flow 共通化 + 8 cancel path 直接テスト
  - 6 files, +1410/-129 lines
  - CLI / GUI 二重実装を `pdf/review_flow.resolve_review_session` に集約、`ReviewOutcome` + `ReviewReason` Literal で型付き
  - evaluator 2 round + 6 並列レビュー + codex セカンドオピニオン
  - テスト 425 → 466 passed（+41）
  - **Issue #72 + #97 CLOSED**, Net: -2

## セッション 15 の成果（サマリー）

- **PR #96**: Issue #73 - `on_open_review` 戻り値 `ReviewCallbackResult` dataclass 化
  - 4 files, +138/-46 lines
  - `_make_review_callback` の cancel/error 8 path を `CANCEL_RESULT` module-level sentinel に統一
  - テスト 421 → 425 passed
  - **Issue #73 CLOSED**, Net: -1

## 過去セッション詳細
Session 11-14 の詳細は `docs/handoff/archive/2026-04-history.md` を参照。

## 次タスク優先順位

### 優先 1: タスク 10-2（Windows 実機 E2E、本田さん実施）

**前提**: 14A / 14C / 11 完了により `wiseman_hub.spec` + ビルド手順書 + ショートカット配布手順書 + README 運用者セクション揃い済。

**スコープ**（`docs/handoff/14a-build.md` + `docs/handoff/14c-deploy.md` + `docs/handoff/windows-e2e-task10.md`）:
1. TeamViewer 経由で Windows 11 PC にアクセス
2. `uv sync --extra dev` → `uv run pyinstaller --clean wiseman_hub.spec` で exe 生成
3. 配布 ZIP をエミュレート: `dist/wiseman_hub.exe` + `config/default.toml.sample` + `assets/icon.ico` + `scripts/create_shortcut.ps1` を `%USERPROFILE%\wiseman-hub\` にコピー
4. `Set-ExecutionPolicy -Scope Process Bypass` + `.\scripts\create_shortcut.ps1` 実行
5. Launcher GUI で以下を実測:
   - PDF マージ処理ボタン → Phase A → セッション生成
   - 確認待ちセッション → SessionPicker → ConfirmDialog → Phase B → 出力 PDF
   - 設定 → SettingsDialog → TOML 書き戻し → 即反映
6. SmartScreen 初回警告の挙動記録
7. `create_shortcut.ps1` の exit code 1/2/3 の挙動確認

**Acceptance Criteria**: AC2（Cloud Run OCR）/ AC-UI-6〜10 / AC-L-2/3/4 / AC-DIST-1〜4 / AC-14C-1/2/4

### 優先 2: タスク 14D（ADR-011 Accepted 昇格）

**前提**: 10-2 実機検証結果が必須。ADR-011 Status を Proposed → Accepted に昇格、10-2 の SmartScreen 実画面記録を反映。

### 優先 3: P2 refactor 系 Issue（推奨着手順）

- **#44**: Session/UserCandidate を immutable 化（updated_at mutation 排除）
- **#45**: SourceKind を Literal から StrEnum に統一（#27 と連動可能）
- **#27**: config dataclass 全体の型設計強化（Literal + __post_init__ 検証）
- **#49**: resume 時の candidates 範囲外/重複 page_index 検証

### 優先 4: CI / 運用

- **#63**: Linux CI Tk wiring skip（CI 環境調整）
- **#29**: OCRプロキシ Nice-to-have 改善（非root/例外絞込/429テスト他）

### 優先 5: 将来対応

- **#39**: フリガナベースのマッチング（KanjiMatcher 以外の NameMatcher 実装）
- **#40**: B と C で異なる名前が距離0マッチした場合の扱い

## 積み残し Issue / 技術負債

### Session 18 で CLOSED
- ~~**#38**~~（`atomic_io` ユーティリティ抽出、PR #104）
- ~~**#105**~~（session sweep 機構、PR #106、同セッション内で起票 → close）

### Session 17 で CLOSED
- ~~**#68**~~（validate_form 戻り値 ValidationError enum 化、PR #102）

### Session 16 で CLOSED
- ~~**#72**~~（review_flow.py 共通化、PR #100）
- ~~**#97**~~（_make_review_callback cancel path 直接テスト、PR #100 で同時解消）

### Session 15 で CLOSED
- ~~**#73**~~（on_open_review dataclass 昇格、PR #96）

### Session 13 で CLOSED
- ~~**#51**~~, ~~**#58**~~, ~~**#71**~~, ~~**#50**~~, ~~**#64**~~

### P2（open、refactor 系、優先）
- **#44**: Session/UserCandidate immutable 化（updated_at mutation 排除）
- **#45**: SourceKind を Literal から StrEnum に統一
- **#27**: config dataclass 型設計強化
- **#49**: resume 時の candidates 検証

### P2（open、継続）
- **#80**（Session 10）: Windows 実機 smoke で Phase B / OCR import 検証
- **#63**: Linux CI Tk wiring skip
- **#40**: B と C で異なる名前が距離0マッチした場合の扱い
- **#39**: フリガナベースのマッチング
- **#29**: OCRプロキシ Nice-to-have 改善
- **#17**: smoke_real.py pytest 統合
- **#16**, **#14**, **#11**, **#6**: 各種改善

## impl-plan 進捗（Session 18 終了時点）

| タスク | 状態 | PR |
|--------|------|-----|
| 10-1 Cloud Run デプロイ + 疎通確認 | ✅ merged | #60, #89 |
| **10-2 Windows 実機 E2E** | ⏳ **本田さん実施待ち（14A / 14C / 11 完了）** | - |
| 11 README + sample TOML | ✅ merged | #85 |
| 12A TOML 書き戻し機能 | ✅ merged | #60 |
| 12B 設定 GUI | ✅ merged | #66 |
| 12C 初回起動ウィザード | ⏳ 優先度低 | - |
| 13A ランチャー GUI 骨格 | ✅ merged | #61 |
| 13B ランチャー ↔ Phase A 統合 | ✅ merged | #65 |
| 13C ランチャー ↔ 確認 UI / Phase B 統合 | ✅ merged | #74 |
| 14A PyInstaller spec | ✅ merged | #79 |
| 14B アイコン生成 | ✅ merged | #60 |
| 14C ショートカット配布手順 | ✅ merged | #82 |
| **14D ADR-011 Accepted 昇格** | ⏳ **10-2 結果反映後** | - |
| 15 GitHub Actions + WIF | ⏳ GUI 安定後 | - |

## セッション再開手順（コピペ可）

```bash
cd /Users/yyyhhh/Projects/wiseman_auto_sys
git checkout main
git pull --ff-only

# 優先1: 10-2 Windows 実機 E2E（本田さん実施、TeamViewer）
# → docs/handoff/14a-build.md + 14c-deploy.md + windows-e2e-task10.md に従う

# 優先2: 14D ADR-011 Accepted 昇格（10-2 結果反映）

# 優先3: P2 refactor 系 Issue（推奨着手順）
#   #44 Session/UserCandidate immutable 化（updated_at mutation 排除）
#   #45 SourceKind StrEnum 統一（#27 と連動可能）
#   #27 config dataclass 型設計強化（Literal + __post_init__ 検証）
#   #49 resume 時の candidates 検証

# 優先4: CI / 運用 (#63 Linux Tk skip)
# 優先5: OCRプロキシ改善 (#29 非root/例外絞込/429テスト)
# postponed: #80（Windows 実機必要）, #17（smoke_real.py pytest 統合）
```

## Quality Gate の実効性（Session 2-18 累積）

- **/simplify** 3 並列: 各 PR で IMPORTANT 3-6 件修正
- **Evaluator 分離**: 5+ files 発動、Session 16 で REQUEST_CHANGES 1 件、Session 18 で MEDIUM 2 件検出
- **6 Agent + Codex 二段レビュー**:
  - Session 9: 13C で Codex HIGH 2 件（TOCTOU + logger.exception PII）検出
  - Session 10: 14A で Codex HIGH 2 件（config CWD バグ + SmartScreen 過小評価）検出
  - Session 11: 14C で Codex HIGH 2 件（USERPROFILE 既定 + FilePublisher 不正確）検出
  - Session 15: 15 で Codex MEDIUM 2 件検出
  - **Session 18**: PR #104 で Codex plan review が HIGH 2 件（try/finally + PdfMergeError ラップ維持）を計画段階で検出
- **/review-pr 6 並列（PR #104 で実施）**: Critical 0 / Important 3 件採用（docstring 永続性 + BaseException 明記 + writer 契約）
- **`except OSError` 分割パターンの採用（Session 18）**: race silent continue + 型別集計 → atomic_io / session で一貫

## 参照ファイル（次セッション用）

### 10-2 実機検証対象
- `wiseman_hub.spec`
- `docs/handoff/14a-build.md`: macOS smoke / Windows 実機ビルド手順
- `docs/handoff/14c-deploy.md`: 施設 IT 担当者向け配布・展開手順書
- `docs/handoff/windows-e2e-task10.md`: E2E 検証手順
- `docs/adr/011-distribution-format.md`: 配布形式 ADR（Proposed、10-2 結果で Accepted 昇格）

### Session 18 成果物
- `src/wiseman_hub/utils/atomic_io.py`: `write_bytes_atomically` + `save_atomically` + `DEFAULT_TMP_GLOB` 公開定数
- `src/wiseman_hub/pdf/session.py::_sweep_stale_session_tmp`: stale tmp cleanup、mtime 60s threshold、Counter 型別集計
- `tests/unit/utils/test_atomic_io.py`: 16 tests
- `tests/unit/pdf/test_session.py::TestStaleTmpSweep`: 11 tests

### 履歴
- `docs/handoff/archive/2026-04-history.md`: Session 11-14 詳細
