# Handoff: "使える Windows デスクトップアプリ" 完成化計画（Session 9 終了時点）

**更新日**: 2026-04-21
**ブランチ**: main（clean、全 PR マージ済）
**main**: 29cb3fa (PR #77 squash merged: Issue #75)

## セッション 9 の成果

### マージ済み
- **PR #70**: Issue #67（`install_tk_exception_guard` 共通化、P0）
- **PR #74**: タスク 13C（ランチャー ↔ 確認 UI / Phase B 統合）
  - 9 files, +1358/-61、ConfirmDialog Toplevel 化 + SessionPicker 新規 + Launcher Phase B worker thread
  - /simplify 3 並列 + Evaluator 分離 + 6 Agent + Codex 二段レビュー
  - Evaluator REQUEST_CHANGES 1 件（画面文言 PII）+ LOW 3 件、Codex HIGH 2 件（TOCTOU + grab_release）+ MEDIUM 2 件反映済
- **PR #77**: Issue #75（pipeline / merger ログ PII 漏洩、Codex HIGH）
  - 4 files, +374/-26、logger.exception 除去・output_path 非混入・__cause__ 保証範囲明示
  - 386 passed / 62 skipped、3 Agent + Codex レビュー HIGH 全解消

### 新規作成 Issue（Session 9）
- **#71**（P2）: `install_tk_exception_guard` の exc_type=None / BaseException テスト補強
- **#72**（P2）: `review_flow.py` で CLI `_cmd_review` と GUI `_make_review_callback` を共通化
- **#73**（P2）: `on_open_review` 戻り値を `ReviewCallbackResult` dataclass へ昇格
- **#75**（P1、PR #77 で close）: pipeline/merger ログ PII 漏洩
- **#76**（P2）: 他 `PdfMergeError` 生成箇所 8 箇所の path/user_name 除外（defense-in-depth）

## 次セッションの着手手順

```bash
cd /Users/yyyhhh/Projects/wiseman_auto_sys
# 1. catchup で状況把握
# 2. 優先タスク選択（14A or 10-2）
git checkout main
git pull --ff-only
```

## 次タスク優先順位

### 優先 1: タスク 14A（PyInstaller spec + icon 埋め込み）

**Issue #59 対応**: GUI 完成後のパッケージング。

**スコープ**:
- `wiseman_hub.spec` 作成（entry point: `src/wiseman_hub/__main__.py`）
- `--icon assets/icon.ico` で exe に resource 埋め込み（14B で生成済み）
- Tkinter / tomlkit / httpx / fitz の hidden imports 設定
- `pyinstaller --onefile --windowed wiseman_hub.spec` でビルド検証
- 生成 exe の起動確認（Windows 実機、10-2 と同時に）

**Acceptance Criteria**:
- AC-DIST-1: `dist/wiseman_hub.exe` がダブルクリックで Launcher GUI を起動
- AC-DIST-2: exe の taskbar / alt-tab アイコンが `assets/icon.ico` に差し替わる
- AC-DIST-3: config/default.toml が exe と同ディレクトリにあれば読み込める
- AC-DIST-4: Windows Defender / SmartScreen の挙動記録（署名なし配布の運用考慮）

**参照**: ADR-002 PyInstaller 選定、Issue #59

### 優先 2: タスク 10-2（Windows 実機 E2E、本田さん実施）

**スコープ**:
- TeamViewer 経由で Windows 11 PC にアクセス
- `docs/handoff/windows-e2e-task10.md` 手順に従い実施
- 13A/13B/13C 完成済みの Launcher GUI で以下を確認:
  - PDF マージ処理ボタン → Phase A 実行 → セッション生成
  - 確認待ちセッションボタン → SessionPicker → ConfirmDialog → Phase B → 出力 PDF 生成
  - 設定ボタン → SettingsDialog → TOML 書き戻し → 即反映
- AC2 (Cloud Run OCR 疎通), AC-UI-6~10 (Tkinter 実描画), AC-L-2/3/4 (Launcher 統合) 実測

**14A と同時実施可**: exe 化した後の実機確認も含めて 1 回のセッションで済ます方が効率的。

### 優先 3: Issue #76（P2、PdfMergeError 全般の PII 除外）

他 8 箇所の `PdfMergeError` message から path/user_name 除外（Issue #75 follow-up、defense-in-depth）。
30 分程度の小作業、PR #77 と同パターンで。

### 優先 4: タスク 14C / 14D / 15 / 11 / 12C

- 14C: ショートカット配布手順（14A 後）
- 14D: ADR-011 配布形式決定（14A 完了後）
- 15: GitHub Actions + WIF デプロイ CI
- 11: README + sample TOML（最後）
- 12C: 初回起動ウィザード（優先度低、12B でカバー済）

## 積み残し Issue / 技術負債

### P1
- **#51**: Windows msvcrt / 跨プロセスロック / 0 ページ PDF（単一 PC では発生せず）

### P2（Session 9 で新規）
- **#71**: guard の exc_type=None / BaseException 契約テスト
- **#72**: `review_flow.resolve_review_session` 共通化
- **#73**: `ReviewCallbackResult` dataclass
- **#76**: 他 PdfMergeError 生成箇所の PII 除外

### P2（継続）
- **#58**: `/healthz` Cloud Run GFE intercept（実害なし）
- **#59**: PyInstaller icon 埋め込み（14A スコープ）
- **#63**: Linux CI Tk wiring skip（別 PR）
- **#64**: `--config` 存在しないパス警告
- **#38**: `atomic_io` ユーティリティ抽出
- **#27 #29 #49 #50 #40 #39 #44 #45 #17 #16 #14 #11 #6**: 各種改善

## impl-plan 進捗（Session 9 終了時点）

| タスク | 状態 | PR |
|--------|------|-----|
| 10-1 Cloud Run デプロイ + 疎通確認 | ✅ merged | #60 |
| **10-2 Windows 実機 E2E** | ⏳ **本田さん実施待ち（14A と同時実施推奨）** | - |
| 12A TOML 書き戻し機能 | ✅ merged | #60 |
| 12B 設定 GUI | ✅ merged | #66 |
| 12C 初回起動ウィザード | ⏳ 優先度低 | - |
| 13A ランチャー GUI 骨格 | ✅ merged | #61 |
| 13B ランチャー ↔ Phase A 統合 | ✅ merged | #65 |
| 13C ランチャー ↔ 確認 UI / Phase B 統合 | ✅ merged | #74 |
| **14A PyInstaller spec** | ⏳ **次セッション最優先** | - |
| 14B アイコン生成 | ✅ merged | #60 |
| 14C ショートカット配布手順 | ⏳ 14A 後 | - |
| 14D ADR-011 執筆 | ⏳ 14A 完了時 | - |
| 15 GitHub Actions + WIF | ⏳ GUI 安定後 | - |
| 11 README + sample TOML | ⏳ 最後 | - |

## Session 9 で確定した設計判断

### タスク 13C

**Toplevel モーダル統一パターン（ConfirmDialog / SessionPicker / SettingsDialog 共通）**
- `tk.Toplevel(parent) + transient + grab_set + wait_window()` で race 構造排除
- `_close_dialog()` ヘルパーで Toplevel=destroy / standalone=quit を分岐
- **grab_release** を明示的に呼んでから destroy（Windows grab 残留防止、Codex MEDIUM 指摘反映）

**Launcher Phase A/B 統合パターン**
- `ThreadPoolExecutor(max_workers=1, thread_name_prefix="phase-worker")` で Phase A/B 直列化
- `on_open_review: Callable[[], str | None]`（main thread 同期）+ `on_run_phase_b: Callable[[str], None]`（worker thread）の 2 callback 設計
- `_handle_open_review` 内で `except Exception` は「コールバック本体の同期例外防御」として妥当（`install_tk_exception_guard` は Tk callback 例外のみ捕捉）

**TOCTOU 防御（Codex HIGH 指摘反映）**
- `_make_review_callback` の 2 回目ロック内で `load_session` 再実行
- 許可: (a) NEEDS_REVIEW && all_candidates_resolved、(b) 既に READY_TO_MERGE（冪等）
- それ以外は競合として停止（CLI `_cmd_review` 方針と統一）

### Issue #75

**PII 防御方針の完全化（pipeline / merger 層）**
- `logger.exception` 全廃、`logger.error("...: %s", type(exc).__name__)` に統一
- `source_a_path` / `output_path` ログ非混入（session_id + 型名 + 件数で追跡）
- `_save_atomically` 失敗時 `PdfMergeError.__str__` からも path 除外
  - 保証範囲: logger / GUI Launcher / CLI 経路は完全塞ぎ
  - 残リスク: `__cause__` chain 経由 threading.excepthook（実運用経路では発生せず、async/subprocess 化時に再評価）

### Quality Gate の実効性（Session 2-9 累積）
- **/simplify** 3 並列: 各 PR で IMPORTANT 3-6 件修正
- **Evaluator 分離**: 5+ files 発動、構造的契約の妥当性を別コンテキスト評価
- **6 Agent + Codex 二段レビュー**: Claude agents が見落とす HIGH を Codex が検出する非対称性を継続確認
  - 13C: Codex HIGH 2 件（TOCTOU + logger.exception PII）検出 → 14A 以降も継続運用

## セッション再開手順（コピペ可）

```bash
cd /Users/yyyhhh/Projects/wiseman_auto_sys
git checkout main
git pull --ff-only

# 14A 着手（PyInstaller spec）
git checkout -b feature/task-14a-pyinstaller-spec

# または 10-2 と同時進行の場合
# → 14A で exe ビルド → Windows 実機 E2E で 14A + 10-2 を同時検証
```

## 14A 設計メモ（詳細）

### スコープ

PyInstaller で `wiseman_hub.exe` を生成し、ダブルクリック起動できる Windows デスクトップアプリに仕立てる。

1. `wiseman_hub.spec` 新規作成:
   - Entry: `src/wiseman_hub/__main__.py`
   - Name: `wiseman_hub`
   - Icon: `assets/icon.ico`
   - Console: False（--windowed）
   - Hidden imports: tkinter / tomlkit / httpx / fitz / pymupdf
   - Data files: 必要なら （現状 TOML は exe 隣配置で十分）
2. ビルドコマンド: `pyinstaller wiseman_hub.spec`
3. Windows CI に「exe ビルド成功」の smoke test 追加（optional）
4. ADR-011 執筆（14D）に繋げる

### ファイル構成案

```
wiseman_hub.spec          # 新規、PyInstaller spec ファイル
docs/adr/ADR-011-distribution.md  # 14D で執筆
docs/handoff/14a-build.md # ビルド手順書（14C 配布手順と統合しても良い）
```

### 既存資産

- `assets/icon.ico`（14B で生成済、18KB、6 サイズマルチ ICO）
- `scripts/generate_icon.py`（再生成用）
- ADR-002: PyInstaller 選定
- `pyproject.toml`: 依存関係（PyInstaller 本体は開発依存として追加）

### 注意点

- PyInstaller 6.x を uv 経由でインストール（開発依存）
- `--onefile` vs `--onedir` の選択: 起動速度は `--onedir` が速いが配布は `--onefile` が単純
  → MVP は `--onefile` で進める（`--windowed` と組み合わせ）
- Cloud Run API Key は TOML 設定で運用、exe に埋め込まない（12A で確定済）
- Windows Defender SmartScreen 対策は別 Issue（署名購入の是非は運用判断、14D で記録）

## 参照ファイル（次セッション用）

### 14A 実装対象
- `wiseman_hub.spec`（新規）
- `pyproject.toml`（PyInstaller 開発依存追加）
- `docs/adr/ADR-011-distribution.md`（14D で執筆、14A では stub のみ）

### 既存資産
- `src/wiseman_hub/__main__.py`: main() エントリポイント
- `src/wiseman_hub/ui/launcher.py`: Launcher（3 ボタン + Phase A/B 非同期）
- `src/wiseman_hub/ui/confirm_dialog.py` / `session_picker.py` / `settings.py`: dialog 群
- `assets/icon.ico`: 14B で生成済
- `docs/adr/ADR-002-pyinstaller.md`: 選定理由
