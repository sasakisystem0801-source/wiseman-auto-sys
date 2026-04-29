# ハンドオフ履歴アーカイブ: 2026-04

2026-04 の Session 12-14 のハンドオフ内容をアーカイブ。詳細な変更履歴・完了タスク・解決済みの技術的詳細を保持。
現行のハンドオフは `docs/handoff/LATEST.md` を参照。

---

## セッション 14 の成果

### マージ済み（1 PR）
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

### 事前検証（10-2 実機テスト前に全 PASS）
- **macOS smoke build**: `uv run pyinstaller --clean wiseman_hub.spec` → 67MB binary 生成、hidden imports 致命警告なし
- **frozen path 回帰テスト**: `tests/unit/test_main_entrypoint.py` に 3 件既存（Codex HIGH #14A 対応分）
- **lint / typecheck / test**: ruff all checks passed / mypy no issues (28 files) / pytest 421 passed, 62 skipped

### 総変更量
- 1 file changed, +43 / -1 lines（docs のみ）
- テスト件数: 421 passed 維持
- **本番 Cloud Run リビジョン更新**: 00002-* → 00003-98m

### Session 14 の学び（次セッションに引継ぐ運用ギャップ）
- **PR merged ≠ 本番反映**: Cloud Run は手動 `gcloud run deploy` 運用のため、PR マージ後にデプロイ実行者が手動トリガーしないと本番は旧コードのまま残る
- **対策候補**:
  1. タスク 15（GitHub Actions Windows runner + WIF）の範囲で、`main` への push 時に `backend/ocr_proxy/**` 変更があれば自動 Cloud Build + Cloud Run deploy を追加
  2. `backend/ocr_proxy/deploy.md` 冒頭に「**main merge 後は速やかに再デプロイ必須**」チェックリストを追記
  3. 10-2 実施前の受入基準に `curl /health` 疎通確認を含める

---

## セッション 13 の成果

### マージ済み（5 PR 連続）
- **PR #88**: Issue #51 #3-#6 - 残タスク 4 件のテストカバレッジ追加
  - 3 files, +209 lines（tests/unit/pdf/ 配下のみ、本体コード変更なし）
  - #3: `test_ocr_server_error_saves_interrupted_state`（非 KI Exception 経路で INTERRUPTED 保存）
  - #4: `test_zero_page_pdf_raises_corrupted_error`（fitz 0-page は save できないため monkeypatch で page_count=0 注入）
  - #5: `test_save_failure_during_interrupt_does_not_mask_original_exception`（INTERRUPTED 保存失敗で元例外が masked されない契約）
  - #6: `test_gc_coexists_with_interrupted_sessions`（gc_old_sessions が COMPLETED のみ削除、INTERRUPTED/NEEDS_REVIEW はロック不要で保全）
  - /review-pr 3 エージェント並列: Critical 0 / Important 3 → 全対応
  - **Issue #51 CLOSED**（#1-#6 全完了）

- **PR #89**: Issue #58 - /healthz を /health にリネーム（Cloud Run GFE 404 回避）
  - 4 files, +22/-7
  - Cloud Run GFE が `/healthz` を intercept して 404 HTML を返す問題の修正
  - **Issue #58 CLOSED**

- **PR #90**: Issue #71 - install_tk_exception_guard 契約テスト追加
  - 1 file, +62
  - exc_type=None で AttributeError 伝播、SystemExit / KeyboardInterrupt 伝播の defense-in-depth
  - **Issue #71 CLOSED**

- **PR #91**: Issue #50 - --list-sessions 集計行（healthy/corrupted 件数表示）
  - 2 files, +88
  - **Issue #50 CLOSED**

- **PR #92**: Issue #64 - --config 存在しないパス警告ログ
  - 2 files, +112
  - **Issue #64 CLOSED**

### 総変更量
- 12 files changed, +493 lines
- **5 Issue CLOSED**: #51, #58, #71, #50, #64
- 全 CI SUCCESS、全レビュー Critical 0
- 前セッション 400 passed → **421 passed**（+13 テスト）

---

## セッション 12 の成果

### マージ済み（3 PR 連続）
- **PR #84**: Issue #76 - merger 全 PdfMergeError message PII 除外
  - 2 files, +221/-18
  - 8 箇所の `PdfMergeError` 生成箇所を型名ベースに統一、`source_label` 呼出側で kind (A/B/C/D) のみに制限
  - 新規 PII 非漏洩回帰テスト +10 件（TestMergerPiiDefense）

- **PR #85**: タスク 11 - README 運用者セクション + default.toml.sample + §7.2 ログ取得手順
  - 3 files, +218/-9
  - 2 エージェント並列レビュー: Critical 2 / Important 3 / Suggestion 3 → **8/8 修正済**

- **PR #86**: Issue #51 #1/#2 - Windows msvcrt mock + 跨プロセスロックテスト
  - 1 file, +282
  - TestLockWindowsMsvcrt (5 件): `sys.modules` 経由の fake msvcrt 注入
  - TestCrossProcessLock (3 件): multiprocessing.spawn で親子プロセス間の lock 競合検証

### 総変更量
- 6 files changed, +721 / -27 lines
- 前セッション 400 passed → **408 passed**（+8 テスト）

### Session 12 での設計判断
- **Issue #76 PII 除外拡張**: `source_label` を呼出側で kind (A/B/C/D) のみに制限、関数シグネチャ非破壊で user_name 埋込を呼出規約レベルで排除
- **タスク 11 docs 整備**: `config/default.toml.sample` 新規作成、README 先頭に運用者セクション挿入
- **Issue #51 scope 絞込**: P1 #1 (Windows msvcrt) + #2 (跨プロセスロック) のみに絞り、#3-#6 は follow-up

---

## セッション 11 の成果（サマリー）

- **PR #82**: タスク 14C（ショートカット配布手順、ADR-011 具体化）
  - 3 files, +449/-11
  - Claude 3 並列レビュー + Codex セカンドオピニオンで HIGH 5 件 + MEDIUM 8 件修正
  - 主な指摘:
    - COM リソースリーク（`try/finally`）
    - OneDrive Desktop リダイレクト対応
    - WSH 無効 / ConstrainedLanguage fallback
    - `%USERPROFILE%\wiseman-hub\` を MVP 既定化（C:\ 直下は標準ユーザー書込不可）
    - FilePublisher allowlist は未署名 exe に不正確 → Hash / FilePath ルールのみ

---

## セッション 15 の成果（サマリー）
- **PR #96**: Issue #73 - `on_open_review` `ReviewCallbackResult` dataclass 化 + 8 cancel path → `CANCEL_RESULT` sentinel。**Issue #73 CLOSED**, Net: -1

## セッション 16 の成果（サマリー）
- **PR #100**: Issue #72 + #97 - review_flow 共通化（6 files, +1410/-129）。CLI/GUI 二重実装を `pdf/review_flow.resolve_review_session` に集約。**Issue #72 + #97 CLOSED**, Net: -2

## セッション 17 の成果（サマリー）
- **PR #102**: Issue #68 - `validate_form` 戻り値 `ValidationError` enum 化（2 files, +246/-52）。`ValidationCode` (StrEnum 10 種) + `match/case` + `typing.assert_never`。**Issue #68 CLOSED**, Net: -1

## セッション 18 の成果（サマリー）
- **PR #104**: Issue #38 - `atomic_io` ユーティリティ抽出（7 files, +540/-72）。`write_bytes_atomically` + `save_atomically` 新設、merger/session/config 置換。**Issue #38 CLOSED**
- **PR #106**: Issue #105 - session `_sweep_stale_session_tmp` 追加（3 files, +329/-1）。mtime 60s 閾値、`except OSError` 分割（FileNotFoundError silent + Counter 型別集計）。**Issue #105 CLOSED**
- Net: **-1**

---

## セッション 19 の成果（最大コミット: +2,245 行）

### マージ済み
- **PR #108**: feat(pdf): facility_merger - 事業所フォルダ PDF 結合 (MVP 暫定)
  - 12 files, +2,245 lines / 5 commits（feat + refactor + ui + fix + docs）
  - **「A提供実績 + B運動機能向上計画書 + C経過報告書」を利用者単位で結合する新機能**
  - **Windows 実機で 18 ページ A から 19 名全員の氏名抽出成功、3 種全結合含め 19 件出力達成**
  - ユーザーゴール「OCR（テキスト認識）による A+B+C 正しい順序結合」完全達成

### 実装範囲
- **コア**: `src/wiseman_hub/pdf/facility_merger.py` (+358 行)
  - `merge_facility(source_a, facility_dir, output_root)` 本体
  - Phase 1: A.pdf 各ページを分割 → 氏名抽出 → B/C 姓マッチ → 3 者結合
  - Phase 2: A 未マッチの B/C 残余を相互マッチして結合
  - 9 フィールドの `FacilityMergeReport`（success / extraction_failed_pages / a_only / a_missing / b_missing / c_missing / name_conflicts / ambiguous_bc_skipped）
  - 既存 `splitter._extract_single_page_pdf` / `merger._append_pdf_file` / `merger._save_atomically` を private 再利用（将来 public 化予定）
- **氏名抽出**: `src/wiseman_hub/pdf/text_name_extractor.py` (+96 行)
  - Pattern 1（ラベル隣接型）: `氏名 姓 名 様` — 計画書・経過報告書向け
  - Pattern 2（フリガナ隣接型）: `半角カタカナ行 + 改行 + 漢字姓名` — 提供実績チェックリスト向け（実帳票で「氏名」ラベルと実名が別セルで離れているケース対応）
  - OCR 不要（全て `page.get_text()` によるテキスト層抽出）
- **CLI**: `scripts/merge_facility.py` (+274 行)
  - 本実行モード + `--diag` 事前診断モード（書込なしで氏名抽出 / B/C マッチプラン表示）
- **GUI**: `src/wiseman_hub/ui/facility_merger_dialog.py` (+275 行) + `launcher.py` 修正
  - Launcher 4 ボタン目「事業所フォルダ結合」追加
  - Toplevel ダイアログ（A.pdf / 事業所フォルダ / 出力ルート の 3 入力 + 実行 + 結果テキスト）
- **テスト**: 新規 30 tests（facility 17 + text_name 17 + dialog 5、dialog は Tk_required で skip 許容）
- **ドキュメント**: `docs/handoff/folder-merger-mvp-runbook.md`（30 分完走ランブック）+ `folder-merger-mvp-testing.md`（検証結果テンプレート）

### Windows 実機検証の実経過（AC-FM-7 完走）
1. TeamViewer 接続 → `git pull` → `uv sync` → `pytest` 通過
2. `--diag` 初回実行: **A.pdf 18 ページ全てで氏名抽出失敗**
3. 原因調査（`fitz.Page.get_text()` の生 repr 確認）: 提供実績チェックリストのテキスト層は「氏名」ラベルと実名が**別セル**で配置されており、既存 Pattern 1 がマッチせず
4. Pattern 2（フリガナ隣接型）を追加実装 + push
5. 再診断: **18 ページ全員の氏名抽出成功**（浅尾 和司 / 塩津 美喜子 / 尾島 亮子 他）
6. 本実行: **19 件出力**（A+B+C: 2 件 [塩津・尾島] / A+B: 1 件 [藤野] / A+C: 4 件 / A のみ: 11 件 / Phase 2: 1 件 [asao]）
7. 塩津.pdf 目視確認: **A（提供実績）→ B（運動器機能向上計画書）→ C（利用経過報告書）の順序で別人混入なく結合成功**
8. GUI 経由実行: 同じ 19 件結合成功、PII 防御（full_name 非表示）動作確認

### Session 19 の学び
- **Codex セカンドオピニオンが致命バグを事前検知**: 6 並列 review-pr が見逃していた「同姓 2 名 + B/C 1 ファイルで誤添付」を Codex が HIGH 指摘、Windows 実機検証前に fail-safe で構造防止完了。医療データ文脈で不可欠なレビュー構成
- **実データを見てから正規表現を書く**: 最初の「氏名 姓 名 様」パターンは Image #17（A.pdf 1 ページ目スクショ）のレイアウト先行イメージで書いてしまい、実際のテキスト層順序に合わなかった。Windows で `page.get_text()` の repr を見て初めて実データ構造が判明。テキスト層 PDF でも**「見た目」と「テキスト順序」は別物**
- **事前診断モード (`--diag`) の価値**: 書込なしで「実データ × 実装の整合」を早期検知できる設計が実機 1 発成功に直結。18 ページ抽出失敗の段階で本実行を止め、手戻りゼロで Pattern 2 追加に転換できた
- **ファイル名表記揺れの実運用確認**: A/B で「塩津 美喜子」、C で「塩津 美貴子」と漢字が違うケース（実運用の現実）でも、姓「塩津」の部分一致マッチで同一人物として正しく結合できた。表記揺れ対応の設計価値

### 総変更量（Session 19）
- 12 files changed, +2,245 / -8 lines
- テスト件数: 502 passed → **537 passed**（+35: facility_merger 17 + text_name_extractor 17 + launcher 1 更新）

---

## セッション 20 の成果（4 PR、合計 +492 / -25 行）

### マージ済み
- **PR #110**: test(facility_merger): 複数利用者 × 混在可用性シナリオで A→B→C 順序と非混入を検証
  - 1 file, +132 lines（docstring 改善含む 2 commits）
  - Session 19 の Windows 実機 19 件結合のうち**目視確認は 1 件のみ**だったギャップを自動回帰テストで担保
  - `[SRC:A|B|C][USER:xxx]` 合成タグで 5 利用者 × 混在可用性（A+B+C / A+B / A+C / A のみ）を内容レベル検証
  - `/review-pr` 4 エージェント並列 → Important 1 件（docstring 明文化）対応、triage 基準未満 nice-to-have 5 件は PR コメント記録のみ

- **PR #111**: feat(spec): PyInstaller spec に facility_merger hiddenimports 追加（タスク 1-C 準備）
  - 1 file, +3 lines
  - `wiseman_hub.ui.facility_merger_dialog` / `wiseman_hub.pdf.facility_merger` / `wiseman_hub.pdf.text_name_extractor` を hiddenimports に明示
  - macOS smoke build で 3 モジュールの `Hidden import not found` warning 無しを事前検証

- **PR #112**: docs(handoff): Session 20 ハンドオフ更新

- **PR #113**: docs(runbook): 1-C exe 再配布専用ランブック新設（Windows 実機単独完走支援）
  - 2 files, +247 / -6 lines
  - 新規 `docs/handoff/1c-exe-redistribution-runbook.md`（Phase 0-5、rollback 手順付き、20-30 分想定）

### 次スプリント方針（Codex セカンドオピニオンで確定）

**実行順: PR1（1-C 配布）→ 実運用 1 回 → PR2（1-B 内容抽出）→ 必要なら 1-A → 1-D/1-E**

Codex 回答の核心:
> 現状の最大リスクは品質不足より「配布されず業務価値が発生しない」こと。MVP は E2E 済で A のみ出力も業務上の最低線を満たすため、まず限定展開して実データを得る判断に納得感がある。1-C と 1-B を同一 PR にすると配布トラブル時の切り分けが悪化する。

### Session 20 の学び
- **Codex の PM/PL 的判断で優先度確信**: 「配布されないと業務価値ゼロ」という視点を明言してもらうことで、1-A/1-B の誘惑（技術的に面白い match 率改善）より 1-C（退屈な配布作業）が先、という判断に納得感が出た
- **spec 更新を独立 PR にする価値**: 1-C を「spec 更新（PR 化可能）」と「Windows 実機作業（物理作業）」に分離したことで、Claude 側の貢献部分を明確化
- **内容レベルテストは目視確認の代替として強力**: `[SRC:X][USER:xxx]` 合成タグ方式でユニットテスト内で 5 利用者 × 4 パターン × ページ順序 + 非混入を自動検証

### 総変更量（Session 20）
- 2 PRs, 2 files changed, +135 / -0 lines
- テスト件数: 537 passed → **538 passed**（+1）

---

## セッション 21 の成果（2 PR、合計 +687 / -143 行）

### マージ済み
- **PR #115**: docs(runbook): 1-C に Phase 3-B（既存機能 regression smoke）追加（Issue #80 手動部分カバー）
  - 1 file, +48 / -1 行
  - 1-C Windows 実機セッションで `facility_merger` 以外の既存機能（Phase A マージ / Phase B 確認）起動を確認する任意 section 追加
  - 1-C 完走判定に影響しない fail-safe 設計

- **PR #116**: refactor(session): Issue #44 Session/UserCandidate 完全 immutable 化
  - 9 files, +639 / -142 行（2 commits: 初版 + Codex HIGH fix-up）
  - `Session` / `UserCandidate` を `@dataclass(frozen=True)` 化、7 箇所の mutation を `dataclasses.replace` に置換
  - `save_session(session) -> Session` / `transition_session(session, ns) -> Session` 戻り値契約変更
  - AC-IM-1〜9 テスト群追加（9 テスト）+ Partial Update CRITICAL 契約の全フィールド列挙検証
  - **Codex HIGH-1 (resume TOCTOU)**: `run_phase_a` が lock 取得後に `load_session` 戻り値を捨てて stale session を使い続けていたバグを構造的修正。同一 session_id への二重 resume で別利用者 PDF 混入のリスクを排除

### Issue Net 変化（Session 21）
- Close: 2 件（#44 / #118 — #49 と重複統合）
- 起票: 2 件（#117 tuple 化 follow-up / #118 page_index 検証 → #49 統合）
- Priority 昇格: 1 件（#49 P2 LOW → P1 bug、Codex HIGH rating 9+ 評価）
- Net: 0 件

### Session 21 の学び
- **Codex セカンドオピニオンの投資対効果**: 6 エージェント (5 /review-pr + Codex) のうち Codex のみが HIGH-1 (resume TOCTOU) を検出。medical PII 文脈では Codex レベルの批判的レビューが不可欠
- **既存 Issue との重複防止**: #118 起票直後に #49 との重複を発見。新 Issue 起票前に `gh issue list` で既存検索を徹底すべき
- **under-triage の再評価**: #49 が LOW (2026-04-20) だったが、Codex HIGH 評価により P1 bug 昇格。古い triage は鮮度を失うため、関連 PR レビュー時に既存 Issue の priority 再評価を検討すべき
- **frozen + replace パターンの徹底**: 7 mutation 箇所の網羅的書き換えに加え、呼出側で `session = save_session(...)` / `session = transition_session(...)` の戻り値受取を全箇所で統一

### 総変更量（Session 21）
- 2 PRs, 10 files changed, +687 / -143 行
- テスト件数: 538 passed → **551 passed**（+13: AC-IM テスト 9 + Codex HIGH regression 1 + mutation 検証 3）

---

# Session 31 完了 (2026-04-27): PR #141 merged + PR #142 close 保留

**main HEAD**: `7614635` refactor(session): tuple/Mapping 化で deep immutability 型保証 (Closes #117) (#141)

## マージ済 ✅

### PR #141 (Issue #117 — Session/UserCandidate を tuple/Mapping 化)

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

## Close 保留 ⚠️

### PR #142 (Issue #63 — Linux runner Tk wiring tests 全 skip 問題)

- 案 A（xvfb + python3-tk を test-unit.yml に追加）を試行
- Linux + xvfb 環境で `mainloop` を呼ぶ Tk async テスト（合計 11 件）が hang
- test-unit (3.11/3.12) ジョブが `Run unit tests` step で 16+ 分 in_progress 後、cancel 後 fail
- build-smoke / test-integration: PASS（影響なし）
- main は無影響（PR #142 未マージで close）
- **保留判断**: ローカル開発環境（macOS）で Linux 上の Tk 挙動を再現できず hang テストの個別特定にコスト大。本プロジェクトの配布先は Windows 実機のみで Windows runner の wiring tests でカバー範囲は MVP 許容。
- Issue #63 にコメントで保留理由・再開条件を追記、open のまま保留。

## Issue Net 変化（Session 31）

- **Close**: 1 件（**#117**）
- **起票**: 0 件
- **Net: -1 件** ✅（KPI 進捗）

## 重要な設計判断

### Issue #117 — deep immutability tuple/Mapping 化の設計原則

- **frozen=True 単体では深い immutable にならない**: 属性代入は防げるが `list.append()` 等の要素 mutation は型レベルで防げない。tuple/Mapping 化で型レベル禁止に格上げ。
- **JSON シリアライズの後方互換性**: `_to_dict` で `dict(session.config_snapshot)` 明示変換（asdict は MappingProxyType を再帰展開しない）、tuple は json.dumps で array に変換 → 旧形式 (list で保存) JSON も `_from_dict` 内で `tuple(...)` で復元される。
- **テストフィクスチャも tuple 一貫性**: 個々のテストで list を渡しても Python ランタイム的には動くが、Issue #117 の「list 変更を型で防ぐ」設計意図がテスト層まで貫徹されない。evaluator 指摘で全 fixture を tuple 化。
- **mypy の `exclude = ["^tests/"]` 制約**: tests/ は型チェック対象外のため、テストの list→tuple 一貫性は機械的検証されない。round-trip テストの `isinstance(loaded.candidates, tuple)` assert で実行時保証を追加。

### Issue #63 — Linux + xvfb で Tk async テスト hang の知見

- xvfb-run + python3-tk セットアップで Linux runner でも `tkinter.Tk()` は成功するが、`mainloop` を呼ぶ async / phase-A/B integration テスト（合計 11 件）が hang する。
- Windows runner では動作するが、Linux 環境では mainloop が escape できない可能性。
- 対応案 A は構造的に挫折。再着手時は `pytest-timeout` + 個別 `tk_mainloop` marker で hang テストを skip する戦略が候補。

## Session 31 終了時点の状態

- main HEAD: `7614635`
- ローカル clean / origin 同期済
- CI: success (Windows Integration Tests / build-smoke / test-unit 3.11/3.12 / test-integration 全 PASS)
- ADR 14 件すべて Status 確定（最新 ADR-014 は Proposed のまま、実機検証完走後に Accepted 昇格予定）


---

# 旧サマリ: Session 34 完了 - PR #149 マージ + Mac 側打ち止め記録

**更新日**: 2026-04-28（Session 34 / Mac で進められる範囲で打ち止め）
**main HEAD**: `1e1fbe8` refactor(config): 新規 3 型に Literal + __post_init__ 検証を追加 (Refs #27 PR-A) (#149)

## マージ済 PR

| PR | Issue | 内容 | 規模 |
|----|-------|------|------|
| #149 (1e1fbe8) | #27 PR-A | 新規 3 型 (`OcrBackendConfig`, `UserNameBBox`, `PdfMergeConfig`) に Literal + `__post_init__` 検証 + `is_configured` + `merger._KNOWN_KINDS` を `VALID_CONCAT_LETTERS` に統合 (DRY) | 6 ファイル / +306 / -64 |

### Issue #27 段階実装の方針

- PR-A ✅ (Session 34): 新規 3 型
- PR-B: 既存 6 型横展開 — 次セッションで見送り、別途タイミングで
- PR-C: Path 型移行 → ROI 低い、Issue #151 (tuple 化) で型強化に振り替え

### Issue Net（Session 34）

- Close: 0 / 起票: 3 (#150 P1 / #151 P2 / #152 P2、すべて PR #149 レビュー由来) / **Net: -3 件 ❌**

### 学び

- **CRITICAL silent failure を即「スコープ外」と判定しない**: PR #149 の初判定で UI 層 cast を「別 Issue」としたが、最小修正で対応可と判明
- **`Issue #27` 等のタスク参照を docstring に書かない**: CLAUDE.md「Don't reference the current task」原則を 8 箇所違反、レビュー指摘で発覚
- **rating 6-7 borderline の Issue 起票判断**: PR スコープ追加で対処可能なら Issue 化しない (#151/#152 反省)

---

# 旧サマリ: Session 33 完了 - PR #146/#147 マージ + Issue Net -3 件

**更新日**: 2026-04-28（Session 33 / Issue #45 + #14 完了 + #40 検討 close）
**main HEAD**: `7de14ee` refactor(rpa): export_csv 失敗モードを ExportCsvError 階層で区別化 (Closes #14) (#147)

## マージ済 PR (Issue Net -3 件)

| PR | Issue | 内容 | 規模 |
|----|-------|------|------|
| #146 (607ad29) | #45 完了 ✅ | SourceKind を Literal から StrEnum に統一 (JSON 検証一元化) | 4 ファイル / +101 / -22 |
| #147 (7de14ee) | #14 完了 ✅ | export_csv 失敗モードを ExportCsvError 階層 (5 サブクラス) で区別化 | 6 ファイル / +280 / -35 |

### 検討して close した Issue

- **#40** (CLOSED not planned): B/C 異名 distance 0 マッチエッジケース
  - impl-plan 起動 → 数学的に「両方 distance 0 + 異名」は matcher の評価関数の対称性により発生不可能と判明
  - revert + Issue コメントに検討プロセス記録 (実装前に dead code 発見できた Generator-Evaluator 分離の成功例)

### 学び

1. **`patch.dict(sys.modules)` の落とし穴**: with 終了時に「with 内で追加された全キー」を削除する。新規 import は patch.dict ブロックの **前** に置く
2. **Issue 起票時の前提が誤りの場合の対応 (#40 教訓)**: impl-plan 段階で dead code 判明 → 即座に revert + Issue close (not planned) + 検討プロセス記録
3. **Codex review が 6 エージェント見落としを発見**: PR #147 で 6 並列が見落とした「印刷ボタン取得失敗が ExportCsvError 階層外」を Codex が発見 → **大規模 PR (3+ ファイル / 200+ 行) では `/codex review` セカンドオピニオンが価値あり**

---

# 旧サマリ: Session 32 中断 + macOS 側 A1-A5 検証準備整備完了

**更新日**: 2026-04-28（Session 32 / Windows 実機中断後、macOS 側で A1-A5 マージ済）
**main HEAD (当時)**: `cf9f8b1` docs(handoff): Session 32 中断記録 + PR5 検証準備整備 (A1-A5) (#144)

## 進捗

### 午前: Windows 11 実機（TeamViewer 経由）

- **Phase 0-1 完了**: exe バックアップ + `git pull --ff-only` (`f4a242e` 同期) + `uv sync --extra dev` + PyInstaller ビルド成功 (78,632,876 bytes / 2026-04-28 8:00:08)
- **Phase 2-1 完了**: 新 exe を `~/wiseman-hub/wiseman_hub.exe` に配備
- **AC-1 (1)(2) PASS**: Launcher 起動 + 5 ボタン目「ex_ ファイル変換 + 振り分け」表示確認
- **中断**: TeamViewer タイムリミットで AC-1 (3) 未実施 → Session 35 で完走

### 午後: macOS 側 A1-A5 検証準備整備（PR #144 マージ済）

- A1: runbook §2-2 config パス誤記修正
- A2: `config/test.toml.example` 新規 + `WISEMAN_HUB_CONFIG` 経路で本番 NAS 非汚染
- A3: `session32-...md` AC-1 (3) 実機チェックリスト精緻化
- A4: `docs/handoff/ex-test-fixtures.md` 新規（3 種 fixture 仕様）
- A5: ショートカット起動の env var 非継承落とし穴を runbook §2-2 に明文化

### Issue Net（Session 32）: 0 件（中断中、コード変更なし）
