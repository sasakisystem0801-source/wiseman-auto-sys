# Handoff: "使える Windows デスクトップアプリ" 完成化計画（Session 17 終了時点）

**更新日**: 2026-04-22
**ブランチ**: main（clean、全 PR マージ済）
**main**: a04fea0 (PR #102 squash merged: Issue #68 - validate_form 戻り値を ValidationError enum 化)

## セッション 17 の成果

### マージ済み（本セッション、1 PR）
- **PR #102**: Issue #68 - `validate_form` 戻り値を `list[str]` → `list[ValidationError]` 化
  - 2 files, +246/-52 lines（`src/wiseman_hub/ui/settings.py` + tests）
  - `ValidationCode` (StrEnum 10 種) + `ValidationError` (frozen dataclass) 導入
  - `format_validation_errors` が UI 層で enum → 日本語メッセージ変換、messagebox 表示は既存文言と完全一致
  - `_message_for` を `match/case` + `typing.assert_never` 化（type-design-analyzer rating 7 指摘反映）→ mypy で網羅性を静的検証、`# pragma: no cover` 削除
  - `test_multiple_missing_fields_accumulate_errors` 追加（pr-test-analyzer rating 7 指摘反映）→ early return / break 混入 regression 防御
  - PII 防御: `context` に raw 入力値を入れない契約を維持（API Key を URL 欄貼付け等の誤入力で PII 露出しない構造的分離）
  - `ValidationError.field_name` 命名: Issue 本文は `field: str` だが `dataclasses.field` と衝突して mypy "str not callable" → `field_name` に改名（simplify rating 7 confidence 95% 指摘反映）
  - 2 commits（初版 + /review-pr 指摘対応）
  - **Issue #68 CLOSED**

### 本セッションの Quality Gate 適用フロー
1. `/impl-plan` で 2 ファイル変更計画 + AC-1〜AC-7 定義（3 ステップ以上ルール）
2. TDD: RED（テスト error code assert 化）→ GREEN（enum 追加 + validate_form 改修）→ Refactor
3. `/simplify` 3 並列 → `field` → `field_name` 改名 + `dc_field` alias 解消
4. `/review-pr` 4 エージェント並列（code-reviewer rating 9/10 / type-design / silent-failure / test-analyzer）→ rating 7+ の 2 指摘採用
5. Issue triage 適用: rating 5-6 の指摘は PR コメント / TODO / 却下（CLAUDE.md triage 基準準拠）

### Issue Net 変化（本セッション）
- **Close**: 1 件（#68 = validate_form enum 化）
- **起票**: 0 件
- **Net: -1** ✅ KPI 改善（MEMORY.md `feedback_issue_triage.md` 基準達成）

### 総変更量（Session 17）
- 2 files changed, +246 / -52 lines
- テスト件数: 466 passed → **475 passed**（+9: TestValidateForm +4 / TestFormatValidationErrors +6 - 差分は既存テスト置換吸収）
- skip: 63 維持
- 全ローカル検証 PASS（pytest 475 / ruff / mypy 29 files）
- CI: 全 SUCCESS（test-unit 3.11 54s / 3.12 59s / test-integration 2m31s）

### Session 17 の学び
- **`/simplify` の rating 7 確実採用の効果**: `field` → `field_name` 改名は Issue 本文と異なる命名だが、mypy 衝突という実害のため採用。単なる「Issue 本文の忠実実装」より構造的正しさを優先する判断が機能した（`feedback_evaluate_as_system.md` 原則）
- **match/case + assert_never の mypy 静的網羅性**: 10 値 enum + UI 表示分岐で `if` チェーンと比較し、型安全性が大幅向上。新 code 追加時に runtime `AssertionError`（pragma: no cover で未検証）ではなく compile time で検出可能
- **review agent rating 閾値の厳格運用**: 4 エージェント並列で rating 7+ confidence 80+ は 2 件のみ。rating 5-6 を却下することで PR 肥大化を防ぎ、net -1 を維持

## セッション 16 の成果

### マージ済み（本セッション、1 PR）
- **PR #100**: Issue #72 + #97 統合 - review_flow に共通ロジック抽出 + 8 cancel path 直接テスト
  - 6 files, +1410/-129 lines（src 3 + tests 3）
  - CLI (`_cmd_review`) と GUI (`_make_review_callback.open_review`) で二重実装されていた
    確認 UI 起動 + NEEDS_REVIEW → READY_TO_MERGE 遷移フローを `pdf/review_flow.resolve_review_session` に集約
  - `ReviewOutcome` (frozen dataclass) + `ReviewReason` Literal (9 値) で分岐を型付き値オブジェクト化
  - `_review_outcome_to_callback_result` (GUI) / `_review_outcome_to_exit_code` (CLI) adapter を分離し、
    各 reason を直接ユニットテスト化（pr-test-analyzer rating 8 指摘対応）
  - CLI 側を single-lock → double-lock + fresh reload に強化（race safety 向上、correctness win）
  - `assert_never` で Literal 網羅性を mypy で compile-time 検証
  - race 対応: picker 選択後〜1st lock 取得前の `SessionNotFoundError` / `SessionCorruptedError` を
    両 adapter で catch → messagebox / stderr 通知 + CANCEL / EXIT_ERROR マッピング
  - 2 commits（初版 + /review-pr 指摘対応）
  - **Issue #72 CLOSED / Issue #97 CLOSED**

### 本セッションの Quality Gate 適用フロー（最多数の gate 通過）
1. `/impl-plan` で 5 ファイル変更計画 + AC-1〜AC-8 定義
2. `/simplify` 3 並列 → `assert_never` 追加 + `outcome: object` 削除
3. `/safe-refactor` → `dialog_factory` 型注釈追加（`type: ignore` 削除）
4. **evaluator 分離プロトコル (2 round)**:
   - 1st: REQUEST_CHANGES (HIGH 2 + MEDIUM 2) → 全対応（docstring 拡張 / race catch 追加 / test assertion 補強）
   - 2nd: APPROVE (LOW 2 件は merge blocker 外)
5. `/review-pr` 6 エージェント並列 → Important 1 (CLI unresolved count regression) + Suggestions 複数適用
6. `/codex review` セカンドオピニオン → HIGH 0 / MEDIUM 2（実質 skip）
7. レビュー指摘の triage 適用:
   - 本 PR で対応: CLI unresolved 残数復元（`ReviewOutcome.detail` 経由）/ `_make_factory` → `_RecordingFactory` class 化 / import 統合 / `SessionCorruptedError` テスト追加 / lock 呼出回数直接検証
   - Skip: discriminated union (rating 6 / 別 PR) / CLI per-reason parametrize / comment cleanup

### Issue Net 変化（本セッション）
- **Close**: 2 件（#72 = review_flow 共通化 / #97 = adapter 直接テスト追加）
- **起票**: 0 件（codex MEDIUM 指摘は triage 基準未達で skip、review agent suggestion は全て PR 内対応または skip）
- **Net: -2** ✅ KPI 改善

### 総変更量（Session 16）
- 6 files changed, +1410 / -129 lines
- テスト件数: 425 passed → **466 passed**（+41: review_flow 19 + adapter 19 + CLI race 3 = 41 新規）
- skip: 63 維持
- 全ローカル検証 PASS（pytest 466/466 / ruff / mypy 29 files）
- CI: 全 SUCCESS（test-unit 3.11 / 3.12 / test-integration、Windows Integration Tests in_progress）

### Session 16 の学び
- **evaluator 2 round の価値**: 1st round で HIGH 指摘（dialog.run() 中のロック保持期間が未文書化、race SessionNotFoundError 未処理）を検出し、docstring 拡張 + race catch 追加で対応。2nd round で APPROVE、適切な粒度で完了。
- **codex HIGH 0 の意義（5 セッション連続）**: Claude 6 エージェント + evaluator で HIGH レベル問題は網羅できており、codex は MEDIUM 2 件に留まった。品質ゲート多層化が機能している証左。
- **mypy `reason in (...)` Literal narrowing 非対応**: `or` chain（`reason == "a" or reason == "b"`）で記述する必要。`match/case` ならば narrow できるが assert_never との相性で if chain を維持。
- **既存 pre-existing 設計の踏襲判断**: CLI/GUI の message 露出非対称（CLI = exception message、GUI = type name only）は既存パターンであり、refactor で統一する判断はスコープ外と明示的に却下（`feedback_evaluate_as_system.md` 原則）。

## セッション 15 の成果

### マージ済み（本セッション、1 PR）
- **PR #96**: Issue #73 - on_open_review 戻り値を ReviewCallbackResult dataclass に昇格
  - 4 files, +138/-46 lines（src 2 + tests 2）
  - `Launcher.on_open_review` callback の戻り値を `str | None` → `ReviewCallbackResult` (frozen dataclass) へ昇格
  - 第三状態（確認完了したが Phase B スキップ / ドライラン等）に備えた API 拡張可能化
  - `_make_review_callback` の cancel/error 8 path を `CANCEL_RESULT` module-level sentinel に統一
  - 不変条件破綻時の明示 guard（python -O で assert 剥離されても安全停止）
  - 3 commits（初版 + レビュー対応 + codex セカンドオピニオン対応）
  - **Issue #73 CLOSED**

### 本セッションの Quality Gate 適用フロー
1. `/impl-plan` で 4 ファイル変更計画 + AC-1〜AC-7 定義
2. `/simplify` 3 並列 → CANCEL_RESULT sentinel 化 + 歴史的タグ除去
3. `/safe-refactor` → 8 error path 全件確認 + frozen 副作用検証
4. `/review-pr` 6 エージェント並列 → Critical 0 / Important 4 件
5. `/codex review` セカンドオピニオン → MEDIUM 2 / LOW 2 件追加検出
6. レビュー指摘の triage 適用:
   - 本 PR で対応: assert → guard / sentinel module-level / 第三状態テスト追加 / sentinel コメント整理
   - 別 Issue: #97 起票（テストギャップ rating 8）
   - PR コメント TODO: factory methods 推奨（severity rating ≥ 7 未満のため Issue 化見送り）

### Issue Net 変化（本セッション）
- **Close**: 2 件（#73 = 本実装 / #98 = triage 基準未達で取り下げ）
- **起票**: 1 件（#97 = pr-test-analyzer rating 8 テストギャップ）
- **Net: -1** ✅ KPI 改善

### 総変更量（Session 15）
- 4 files changed, +138 / -46 lines
- テスト件数: 421 passed → **425 passed**（+4: TestReviewCallbackResult 4 ケース）
- skip: 62 → 63（第三状態 Tk required test 追加、Linux CI では skip）
- 全ローカル検証 PASS（pytest 425/425 / ruff / mypy 28 files）

### Session 15 の学び
- **Issue triage 厳格運用の効果**: type-design REVISE は per-axis rating（Encapsulation 5/10 等）であり severity rating ≠ 7 のため Issue #98 を一度起票後に再評価で close、PR コメント TODO に変換
- **codex セカンドオピニオンの価値（4 セッション連続）**: Session 9-11 連続で HIGH 検出に続き、本 Session も MEDIUM 指摘 2 件採用（第三状態テスト + sentinel コメント整理）
- **module-level sentinel は Tk import deferring 設計と要トレードオフ**: closure scope 内 import を維持し、`launcher.py` 側のみ module-level 化することで両立

## セッション 14 の成果

### マージ済み（本セッション、1 PR）
- **PR #94**: 10-2 トラブル切り分けフロー追加 + Cloud Run /health 本番反映
  - 1 file, +43/-1 lines（`docs/handoff/windows-e2e-task10.md` のみ）
  - 症状×原因×対応マトリクス 5 節追加（Phase A / Phase B UI / Phase B 結合 / exe 起動 / SmartScreen）
  - `/healthz` 既知制約記述を「PR #89 で解消済」に更新
  - 軽量 docs 変更のため `/review-pr`（6 エージェント並列）は過剰としてセルフレビューで対応
  - CI 全 SUCCESS（test-unit 3.11 1m4s / 3.12 59s / test-integration 2m22s）

### 本セッションで発見・解消した本番ブロッカー
- **症状**: Cloud Run `/health` が HTTP 404 を返していた
- **原因**: PR #89（Issue #58、/healthz → /health リネーム）は main に merged 済だったが、**Cloud Run 本番リビジョンは旧コードのまま**（openapi.json の paths に `/healthz` が残存、`/health` は存在しない状態）
- **検出経路**: 10-2 実機テスト前の事前準備として macOS から `curl /health` で疎通確認 → HTTP 404 で異常検出
- **対応**: Cloud Run 再デプロイ実施
  - 新リビジョン: `wiseman-ocr-proxy-00003-98m`
  - 反映日時: 2026-04-22 13:31 JST
  - Cloud Build 52 秒 + Cloud Run deploy 約 40 秒
- **検証**:
  - 既存 URL `/health` → HTTP 200 `{"status":"ok"}` ✅
  - 既存 URL `/healthz` → HTTP 404 ✅（ルート削除済、期待通り）
  - openapi.json paths: `['/health', '/v1/ocr/extract-name']` ✅
- **影響範囲**: 10-2 実機テスト前に修正済のため、本田さんの Windows 実機テスト時には `/v1/ocr/extract-name` 経由で正常動作する見込み

### 事前検証（10-2 実機テスト前に全 PASS）
- **macOS smoke build**: `uv run pyinstaller --clean wiseman_hub.spec` → 67MB binary 生成、hidden imports 致命警告なし（user32/msvcrt 欠落は macOS なので想定内、jinja2/pycparser 未使用で実害なし）
- **frozen path 回帰テスト**: `tests/unit/test_main_entrypoint.py` に 3 件既存（Codex HIGH #14A 対応分）
- **lint / typecheck / test**: ruff all checks passed / mypy no issues (28 files) / pytest 421 passed, 62 skipped
- **Cloud Run 疎通**: 再デプロイ後 `/health` → 200 確認

### 総変更量（Session 14）
- 1 file changed, +43 / -1 lines（docs のみ、本体コード変更なし）
- テスト件数: 421 passed 維持（Session 13 と同数）
- **本番 Cloud Run リビジョン更新**: 00002-* → 00003-98m（PR #89 本番反映）

### Session 14 の学び（次セッションに引継ぐ運用ギャップ）
- **PR merged ≠ 本番反映**: Cloud Run は手動 `gcloud run deploy` 運用のため、PR マージ後にデプロイ実行者が手動トリガーしないと本番は旧コードのまま残る
  - 本セッション発見前、**Session 11-13 の間に少なくとも 1 リビジョン分の本番反映遅延**が発生していた（PR #89 merged が 2026-04-22 早朝、本番反映が同日 13:31）
- **対策候補**:
  1. タスク 15（GitHub Actions Windows runner + WIF）の範囲で、`main` への push 時に `backend/ocr_proxy/**` 変更があれば自動 Cloud Build + Cloud Run deploy を追加
  2. `backend/ocr_proxy/deploy.md` 冒頭に「**main merge 後は速やかに再デプロイ必須**」チェックリストを追記
  3. 10-2 実施前の受入基準に `curl /health` 疎通確認を含める（本セッションで実施済の経験を形式化）
- **短期対応**: 1 は工数重め（タスク 15 待ち）、2 は軽量で即対応可能 → **次セッション冒頭で deploy.md 補強 PR 化を推奨**

## セッション 13 の成果

### マージ済み（本セッション、5 PR 連続）
- **PR #88**: Issue #51 #3-#6 - 残タスク 4 件のテストカバレッジ追加
  - 3 files, +209 lines（tests/unit/pdf/ 配下のみ、本体コード変更なし）
  - #3: `test_ocr_server_error_saves_interrupted_state`（非 KI Exception 経路で INTERRUPTED 保存）
  - #4: `test_zero_page_pdf_raises_corrupted_error`（fitz 0-page は save できないため monkeypatch で page_count=0 注入）
  - #5: `test_save_failure_during_interrupt_does_not_mask_original_exception`（INTERRUPTED 保存失敗で元例外が masked されない契約）
  - #6: `test_gc_coexists_with_interrupted_sessions`（gc_old_sessions が COMPLETED のみ削除、INTERRUPTED/NEEDS_REVIEW はロック不要で保全）
  - /review-pr 3 エージェント並列: Critical 0 / Important 3 → 全対応（#4 docstring wording / #5 threshold magic number を KI flag 検出方式に変更 / #5 末尾コメント整理）
  - **Issue #51 CLOSED**（#1-#6 全完了）

- **PR #89**: Issue #58 - /healthz を /health にリネーム（Cloud Run GFE 404 回避）
  - 4 files, +22/-7（`backend/ocr_proxy/app/main.py` + tests + README + deploy.md）
  - Cloud Run GFE が `/healthz` を intercept して 404 HTML を返す問題の修正
  - /review-pr 2 エージェント: Critical 0 / Important 1 → 対応（regression test を `app.routes` ベースに強化し FastAPI 404 挙動依存を解消）
  - **Issue #58 CLOSED**

- **PR #90**: Issue #71 - install_tk_exception_guard 契約テスト追加
  - 1 file, +62（tests/unit/ui/test_common.py のみ）
  - exc_type=None で AttributeError 伝播（Tk main loop に委ねる defense-in-depth）を契約固定
  - SystemExit / KeyboardInterrupt は握り潰さず伝播（プロセス終了を阻害しない設計）を契約固定
  - /review-pr 2 エージェント: Critical 0 / Important 1 → 対応（docstring に「現行は副作用的、理想は defensive ガード」follow-up 注記追加）
  - **Issue #71 CLOSED**

- **PR #91**: Issue #50 - --list-sessions 集計行（healthy/corrupted 件数表示）
  - 2 files, +88（scripts/merge_user_pdfs.py + tests）
  - 出力末尾に「N sessions total: X healthy, Y corrupted」を追加、運用者が一目で破損件数を把握可能
  - /review-pr 2 エージェント: Critical 0 / Important 2 → 全対応（全 corrupted 境界値テスト追加、末尾位置を splitlines()[-1] で固定、例外型名 `<corrupted: SessionCorruptedError>` まで完全一致）
  - **Issue #50 CLOSED**

- **PR #92**: Issue #64 - --config 存在しないパス警告ログ
  - 2 files, +112（src/wiseman_hub/__main__.py + tests）
  - `args.config` 明示指定 + `.exists() == False` で logger.warning 事前通知（load_config 挙動は非破壊）
  - /review-pr 2 エージェント: Critical 0 / Important 1 → 対応（--rpa 経路での警告配置契約テスト追加）
  - **Issue #64 CLOSED**

### 総変更量（Session 13）
- 12 files changed, +493 lines（-7 lines only from #89 healthz rename）
- **5 Issue CLOSED**: #51, #58, #71, #50, #64
- 全 CI SUCCESS、全レビュー Critical 0
- 前セッション 408 passed → **現在 421 passed**（+13 テスト）

### Issue triage pattern 継続運用（memory 教訓）
- review agent rating 5-6 は Issue 化せず PR 中で対応（feedback_issue_triage.md）
- rating 7 は判断: PR #88 #5 threshold（対応）/ PR #90 exc_type=None（docstring 注記のみ）/ PR #91 末尾固定（対応）/ PR #92 --rpa 配置（対応）
- 5 PR 連続で Critical 0、Important 指摘は全て修正反映

## セッション 12 の成果

### マージ済み（本セッション、3 PR 連続）
- **PR #84**: Issue #76 - merger 全 PdfMergeError message PII 除外
  - 2 files, +221/-18（`src/wiseman_hub/pdf/merger.py` + `tests/unit/pdf/test_merger.py`）
  - 8 箇所の `PdfMergeError` 生成箇所を型名ベースに統一、`source_label` 呼出側で kind (A/B/C/D) のみに制限
  - 4 エージェント並列レビュー（code-reviewer / pr-test-analyzer / silent-failure-hunter / comment-analyzer）: Critical 0 / Important 8 件は defense-in-depth 強化系として PR #84 コメントに TODO 記録
  - 新規 PII 非漏洩回帰テスト +10 件（TestMergerPiiDefense）
  - CI 全 SUCCESS

- **PR #85**: タスク 11 - README 運用者セクション + default.toml.sample + §7.2 ログ取得手順
  - 3 files, +218/-9（`README.md` + `config/default.toml.sample` 新規 + `docs/handoff/14c-deploy.md`）
  - 2 エージェント並列レビュー（code-reviewer / comment-analyzer）: Critical 2 / Important 3 / Suggestion 3 → **8/8 修正済**
  - 主な修正: README「リネーム」→「コピー保存」整合、§2.3 フィールド名実装整合（source_dir 削除）、README リンクに GitHub anchor slug 付与、[gcp] project_id 直書き警告追加
  - CI 全 SUCCESS

- **PR #86**: Issue #51 #1/#2 - Windows msvcrt mock + 跨プロセスロックテスト
  - 1 file, +282（`tests/unit/pdf/test_session.py`、テストのみ）
  - TestLockWindowsMsvcrt (5 件): `sys.modules` 経由の fake msvcrt 注入で Windows 分岐を macOS/Linux でも検証
  - TestCrossProcessLock (3 件): multiprocessing.spawn で親子プロセス間の lock 競合検証
  - 2 エージェント並列レビュー（pr-test-analyzer / code-reviewer）: Critical 0 / Important 0 (blocking) → Merge as-is 推奨
  - Issue #51 は残項目 #3-#6 のため **open 維持**（feedback_issue_postpone_pattern.md 準拠）
  - CI 全 SUCCESS

### 総変更量（Session 12）
- 6 files changed, +721 / -27 lines
  - テスト: +~448（merger.py テスト追加 +~166 + Windows/multiprocessing テスト +282）
  - 設定テンプレート: +133（`config/default.toml.sample` 新規）
  - docs: +~85（README 運用者セクション + 14c-deploy.md §7.2）
  - code: +~55（`merger.py` の PII 防御リファクタ、実装コード変更は本質的にこれのみ）
- 全 CI SUCCESS、全レビュー blocking issue 0
- 前セッション 400 passed → **現在 408 passed**（+8 テスト）

## 前セッション（11）の成果

### マージ済み
- **PR #82**: タスク 14C（ショートカット配布手順、ADR-011 具体化）
  - 3 files, +449/-11（`scripts/create_shortcut.ps1` + `docs/handoff/14c-deploy.md` + ADR-011 更新）
  - Claude 3 並列レビュー（code-reviewer / silent-failure-hunter / comment-analyzer）: HIGH 3 件検出 + MEDIUM 多数
  - Codex セカンドオピニオン: Claude 見落としの HIGH 2 件 + MEDIUM 3 件検出
  - **計 HIGH 5 件 + MEDIUM 8 件すべて修正反映**
  - CI 全 SUCCESS（test-unit 3.11/3.12 各 56s、test-integration 3m13s）

### PR #82 で修正した主な指摘

**Claude HIGH**:
1. COM リソースリーク: `Save()` 失敗で `ReleaseComObject` 未到達 → `try/finally`
2. OneDrive Desktop リダイレクト: `Save()` 時 `0x80070005` が汎用 COMException → 個別 catch + 明示メッセージ
3. WSH 無効 / ConstrainedLanguage: `New-Object -ComObject` 失敗 → 個別 `try/catch` + §4 手動 fallback 誘導

**Codex HIGH（Claude 見落とし）**:
1. `C:\wiseman-hub\` が「管理者権限不要」は誤り（標準ユーザーは C:\ 直下書込不可）→ `%USERPROFILE%\wiseman-hub\` を MVP 既定化
2. 未署名 exe で `FilePublisher` allowlist は不正確 → Hash / FilePath ルールのみに限定、FilePublisher は 14D コードサイニング採用後

**MEDIUM 計 8 件**: PS 5.1 BOM 付与、ADR-011 ↔ 14c-deploy 整合、v0.1.0 → vX.Y.Z placeholder、Resolve-Path 非存在時の明示 check、検証用ドラフト注記、`Bypass -Scope Process` 表現、out-of-band SHA256 共有、Win11 22H2+ SmartScreen 文言注記

## 次タスク優先順位

### 優先 1: タスク 10-2（Windows 実機 E2E、本田さん実施）

**前提**: 14A / 14C 完了により `wiseman_hub.spec` + ビルド手順書 + ショートカット配布手順書が揃ったため、Windows 実機でパッケージング〜E2E〜配布リハーサルまで同時検証できる状態。

**スコープ**（`docs/handoff/14a-build.md` + `docs/handoff/14c-deploy.md` + `docs/handoff/windows-e2e-task10.md`）:
1. TeamViewer 経由で Windows 11 PC にアクセス
2. `uv sync --extra dev` → `uv run pyinstaller --clean wiseman_hub.spec` で exe 生成
3. 配布 ZIP をエミュレート: `dist/wiseman_hub.exe` + `config/default.toml.sample` + `assets/icon.ico` + `scripts/create_shortcut.ps1` を `%USERPROFILE%\wiseman-hub\` にコピー
4. `Set-ExecutionPolicy -Scope Process Bypass` + `.\scripts\create_shortcut.ps1` 実行
5. Desktop の「Wiseman PDF ツール」ショートカットからダブルクリック起動
6. Launcher GUI で以下を実測:
   - 3 ボタン表示、アイコン表示（taskbar / alt-tab / .lnk）
   - PDF マージ処理ボタン → Phase A → セッション生成
   - 確認待ちセッション → SessionPicker → ConfirmDialog → Phase B → 出力 PDF
   - 設定 → SettingsDialog → TOML 書き戻し → 即反映
7. SmartScreen 初回警告の挙動記録（ボタン文言 / Enterprise policy 有無）
8. `create_shortcut.ps1` の exit code 1/2/3 の挙動確認（exe 不在・WSH 無効・書込失敗）

**Acceptance Criteria**:
- AC2: 実 Cloud Run 経由 OCR 成功
- AC-UI-6〜10: Tkinter 実描画確認
- AC-L-2/3/4: Launcher 統合
- AC-DIST-1〜4: exe 起動 / アイコン / config 配置 / SmartScreen 挙動
- AC-14C-1/2/4: PS 実行成功 / Desktop ダブルクリック起動 / icon 埋め込み

### 優先 2: タスク 14D（ADR-011 Accepted 昇格）

**前提**: 10-2 実機検証結果が必須。

**スコープ**:
- ADR-011 Status を Proposed → Accepted に昇格
- 10-2 の SmartScreen 実画面記録を反映（`14c-deploy.md` §5.1 のボタン文言更新）
- コードサイニング要否の運用判断を追記:
  - 1 施設目: 未署名で運用、SmartScreen 警告を IT 担当で対応
  - 2 施設目以降: 証明書投資の合理性を 10-2 の実際の警告頻度 / Enterprise 環境遭遇率で判断
- `14c-deploy.md` 冒頭の「検証用ドラフト」注記を「正式版」に差し替え

### 優先 3: タスク 11（README + sample TOML）

**前提**: 14D 完了後が理想だが、並行可能。

**スコープ**:
- `README.md`: インストール / 起動 / 設定 / よくあるエラー（介護施設運用者向け、非技術者）
- `config/default.toml.sample`: 施設別に編集するテンプレート
- `14c-deploy.md` §7.2 の TBD（exe 起動失敗時のログ出力）を確定

### 優先 4: Issue #76（P2、PdfMergeError 全般 PII 除外）

他 8 箇所の `PdfMergeError` message から path/user_name 除外（Issue #75 follow-up）。30 分の小作業、PR #77 と同パターン。

### 優先 5: タスク 15 / 12C

- 15: GitHub Actions Windows runner + WIF デプロイ CI（Issue #80 の smoke test 統合含む）
- 12C: 初回起動ウィザード（優先度低、12B でカバー済）

## 積み残し Issue / 技術負債

### Session 17 で CLOSED
- ~~**#68**~~（validate_form 戻り値 ValidationError enum 化、PR #102）

### Session 16 で CLOSED
- ~~**#72**~~（review_flow.py 共通化、PR #100）
- ~~**#97**~~（_make_review_callback cancel path 直接テスト、PR #100 で同時解消）

### Session 15 で CLOSED
- ~~**#73**~~（on_open_review dataclass 昇格、PR #96）

### Session 13 で CLOSED
- ~~**#51**~~（P1 #1-#6 全完了、PR #86/#88）
- ~~**#58**~~（/healthz rename、PR #89）
- ~~**#71**~~（Tk guard 契約テスト、PR #90）
- ~~**#50**~~（list-sessions 集計行、PR #91）
- ~~**#64**~~（--config 警告、PR #92）

### P2（Session 8-12 で新規、継続）
- **#80**（Session 10）: Windows 実機 smoke で Phase B / OCR import 検証

### P2（継続）
- **#63**: Linux CI Tk wiring skip（CI 環境調整）
- **#38**: `atomic_io` ユーティリティ抽出
- **#49**: resume 時の candidates 範囲外/重複 page_index 検証
- **#45**: SourceKind を Literal から StrEnum に統一
- **#44**: Session/UserCandidate を immutable 化（updated_at mutation 排除）
- **#40**: B と C で異なる名前が距離0マッチした場合の扱い
- **#39**: フリガナベースのマッチング
- **#27 #29 #17 #16 #14 #11 #6**: 各種改善

## impl-plan 進捗（Session 14 終了時点）

| タスク | 状態 | PR |
|--------|------|-----|
| 10-1 Cloud Run デプロイ + 疎通確認 | ✅ merged（本番反映は Session 14 で PR #89 分を追加デプロイ） | #60, #89 |
| **10-2 Windows 実機 E2E** | ⏳ **本田さん実施待ち（14A / 14C / 11 完了、exe + 配布リハ + README 揃い済）** | - |
| **11 README + sample TOML** | ✅ merged | **#85** |
| 12A TOML 書き戻し機能 | ✅ merged | #60 |
| 12B 設定 GUI | ✅ merged | #66 |
| 12C 初回起動ウィザード | ⏳ 優先度低 | - |
| 13A ランチャー GUI 骨格 | ✅ merged | #61 |
| 13B ランチャー ↔ Phase A 統合 | ✅ merged | #65 |
| 13C ランチャー ↔ 確認 UI / Phase B 統合 | ✅ merged | #74 |
| 14A PyInstaller spec | ✅ merged | #79 |
| 14B アイコン生成 | ✅ merged | #60 |
| **14C ショートカット配布手順** | ✅ merged | #82 |
| **14D ADR-011 Accepted 昇格** | ⏳ **10-2 結果反映後** | - |
| 15 GitHub Actions + WIF | ⏳ GUI 安定後 | - |

## Session 11 で確定した設計判断

タスク 14C の詳細（ADR-011 配布レイアウト / `14c-deploy.md` MVP 配置先 / allowlist ルール /
`create_shortcut.ps1` exit code 構造化）は既にドキュメントに反映済（PR #82 merged）。
詳細は `docs/adr/011-distribution-format.md` と `docs/handoff/14c-deploy.md` を参照。

### Quality Gate の実効性（Session 2-11 累積）
- **/simplify** 3 並列: 各 PR で IMPORTANT 3-6 件修正
- **Evaluator 分離**: 5+ files 発動、13C で REQUEST_CHANGES 1 件検出
- **6 Agent + Codex 二段レビュー**:
  - Session 9: 13C で Codex HIGH 2 件（TOCTOU + logger.exception PII）検出
  - Session 10: 14A で Codex HIGH 2 件（config CWD バグ + SmartScreen 過小評価）検出
  - Session 11: 14C で Codex HIGH 2 件（USERPROFILE 既定 + FilePublisher 不正確）検出
  - **直近 3 セッション（9-11）連続で Codex が Claude 見落としの HIGH を検出 → 継続運用が合理的**

## セッション再開手順（コピペ可）

```bash
cd /Users/yyyhhh/Projects/wiseman_auto_sys
git checkout main
git pull --ff-only

# 優先1: 10-2 Windows 実機 E2E（本田さん実施、TeamViewer）
# → docs/handoff/14a-build.md + 14c-deploy.md + windows-e2e-task10.md に従う
# → README.md 運用者セクション + config/default.toml.sample で配布物最小セット揃い済

# 優先2: 14D ADR-011 Accepted 昇格（10-2 結果反映）

# 優先3: P2 refactor 系 Issue（Session 18 以降の候補、TODO 粒度）
#   #44 Session/UserCandidate immutable 化
#   #45 SourceKind StrEnum 統一
#   #49 resume 時の candidates 検証
#   #38 atomic_io ユーティリティ抽出（merger + session の tempfile+os.replace 重複）
#   #27 config dataclass 型設計強化（Literal + __post_init__ 検証）
# 優先4: CI / 運用 (#63 Linux Tk skip)
# 優先5: OCRプロキシ改善 (#29 非root/例外絞込/429テスト)
# postponed: #80（Windows 実機必要）, #17（smoke_real.py pytest 統合）
```

## Session 12 での設計判断

### Issue #76 の PII 除外拡張
- PR #77 で `_save_atomically` のみ型名ベースに統一済だったが、残り 8 箇所の `PdfMergeError` 生成箇所（`_validate_user_name` / `_open_pdf_file_or_raise` / `_append_pdf_bytes` / `_append_pdf_file`）にも適用
- `source_label` を呼出側で kind (A/B/C/D) のみに制限し、関数シグネチャ非破壊で user_name 埋込を呼出規約レベルで排除（型システム強制ではなく、テストが規約違反を検出する設計）
- `from e` は全箇所で維持 → `__cause__` 経由で元例外情報にアクセス可能

### タスク 11（docs 整備）
- `config/default.toml.sample` を新規作成、`config/default.toml`（dev 用）は残存
- README は先頭に運用者セクションを挿入、既存 dev 内容は維持（分離ファイル回避で GitHub プレビュー改善）
- `14c-deploy.md §7.2` に `startup.log` 取得コマンド（PowerShell `*>` / cmd `2>&1`）を具体化

### Issue #51 の scope 絞込
- P1 #1 (Windows msvcrt) + #2 (跨プロセスロック) のみに絞り、#3-#6 は follow-up
- Windows msvcrt は `sys.modules` 経由の fake 注入で macOS/Linux でも検証
- 跨プロセスロックは `multiprocessing.spawn` で fork の fd 継承を回避、Windows exe 二重起動と等価な挙動を再現

### Issue triage pattern の再適用（memory 教訓）
- review agent の rating 5-7 指摘は Issue 化せず PR コメント TODO で可視化（3 PR 連続で適用）
- Issue #51 は残項目 #3-#6 のため **open 維持**、再開条件を PR #86 本文で機械的に判定可能な形で記述

## 14D 着手メモ（10-2 結果反映）

10-2 完了後の 14D で更新すべき箇所:

### ADR-011
- Status: `Proposed (2026-04-21)` → `Accepted (10-2 完了日)`
- 実機検証結果の「14A 完了時点の実装」節に追記（SmartScreen 実画面 / 配布 PS 動作結果 / 起動時間実測）
- コードサイニング投資の判断記録（SmartScreen 警告頻度 / Enterprise 遭遇率で再評価）

### 14c-deploy.md
- 冒頭「検証用ドラフト」注記を削除
- §5.1 SmartScreen ボタン文言を実画面記録に差し替え
- §7.1 exit code 表を実機動作の追加ケースで補強
- §8 実測報告項目に 10-2 結果を反映

### 本 handoff
- Session 12 として 14D 成果 + 10-2 結果を別途まとめ直し

## 参照ファイル（次セッション用）

### 10-2 実機検証対象
- `wiseman_hub.spec`
- `docs/handoff/14a-build.md`: macOS smoke / Windows 実機ビルド手順
- `docs/handoff/14c-deploy.md`: 施設 IT 担当者向け配布・展開手順書
- `docs/handoff/windows-e2e-task10.md`: E2E 検証手順
- `docs/adr/011-distribution-format.md`: 配布形式 ADR（Proposed、10-2 結果で Accepted 昇格）

### 14D 更新対象
- `docs/adr/011-distribution-format.md`
- `docs/handoff/14c-deploy.md`

### 既存資産
- `assets/icon.ico`
- `scripts/create_shortcut.ps1`（14C）
- `src/wiseman_hub/__main__.py::_default_config_path`（14A、frozen 対応）
