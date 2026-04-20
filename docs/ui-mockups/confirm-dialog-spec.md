# 確認 UI 仕様書: ConfirmDialog

**対象**: `src/wiseman_hub/ui/confirm_dialog.py`（タスク 8C / PR #A）
**関連 ADR**: ADR-009（UI 技術選定・Tkinter）、ADR-010（状態遷移）
**ステータス**: 仕様確定、実装前レビュー用

本ドキュメントは Tkinter 確認 UI の期待動作を定義する。CLAUDE.md CRITICAL ルール「UI 変更 → スクリーンショットで期待結果を提示」に基づく仕様書であり、実装完了後に `macos-screenshots.md` へ実物スクリーンショットを追記する。

---

## 1. 起動前提

- 呼び出し側（PR #B `run_phase_b` / `scripts/review_ui.py`）が `with_session_lock` 取得済み
- 対象 session は `status == NEEDS_REVIEW`
- session.candidates に `NEEDS_CONFIRMATION` または `NO_MATCH` が 1 件以上存在
- **main thread から呼び出す**（tkinter filedialog / messagebox / mainloop は thread-safe でない。違反時 `ConfirmDialog.__init__` が `RuntimeError`）
- PyInstaller 追加依存なし（stdlib `tkinter` のみ。macOS 開発機での Tcl/Tk ランタイム制約は §10.1 参照）

## 2. UI レイアウト

```
┌──────────────────────────────────────────────────────────────────────┐
│ 利用者ペア確認 - Session 20260420T001523Z-a1b2...                    │
├──────────────────────────────────────────────────────────────────────┤
│ 進捗: 2/5 解決済  | 未解決 3 件（確認 2 / 不一致 1）                  │
├──────────────────────────────────────────────────────────────────────┤
│ ┌ページ ┬抽出氏名─────┬信頼度┬状態─────────┬候補 B──────┬候補 C──────┐ │
│ │  1   │塩津 美喜子   │ high │auto_matched │B_塩津美...  │C_塩津美... │ │   ← 非表示
│ │  2   │塩津 美貴子   │medium│needs_confirm│B_塩津美... │C_塩津美... │ │ ←
│ │  3   │山田 太郎     │ low  │needs_confirm│B_山田太... │(none)      │ │ ← 表示
│ │  4   │佐藤 花子     │ high │no_match     │(none)      │(none)      │ │ ←
│ └──────┴──────────────┴──────┴─────────────┴────────────┴────────────┘ │
│                                                                       │
│ 選択中の候補:                                                          │
│   page_index=2, ocr="塩津 美貴子", confidence=medium                  │
│   similar: [B:塩津美喜子 d=1] [C:塩津美喜子 d=1]                      │
├──────────────────────────────────────────────────────────────────────┤
│ [承認]  [却下]  [手動選択...]  [スキップ]                             │
│                                              [すべて解決後に閉じる]   │
└──────────────────────────────────────────────────────────────────────┘
```

- ウィンドウサイズ: 900x520（`geometry("900x520")`）、リサイズ可能（Treeview の列幅合計 + scrollbar + padding の実測から決定。列幅は実装の `_COLUMNS` が単一の真実）
- タイトル: `f"利用者ペア確認 - Session {session_id}"`
- 中央 Treeview は `NEEDS_CONFIRMATION` / `NO_MATCH` のみ表示（既に解決済みの行は隠す）

## 3. 操作仕様

### 3.1 ボタン 4 種

| ボタン | 有効条件 | 動作 | 遷移先 PairStatus |
|--------|--------|------|------------------|
| **承認** | 選択行 が `NEEDS_CONFIRMATION` **かつ** similar_candidates に B または C が 1 件以上 | similar_candidates の先頭 B を `matched_b_path` に、先頭 C を `matched_c_path` に確定。どちらも存在しない場合はボタン無効 | `CONFIRMED` |
| **却下** | 選択行が `NEEDS_CONFIRMATION` または `NO_MATCH` | `matched_b_path = matched_c_path = None`、similar_candidates クリア | `REJECTED` |
| **手動選択...** | 選択行が `NEEDS_CONFIRMATION` または `NO_MATCH` | `filedialog.askopenfilename` を 2 回（B 用・C 用）起動。キャンセル可、片方のみ選択可 | `MANUALLY_SELECTED` |
| **スキップ** | 選択行が `NEEDS_CONFIRMATION` または `NO_MATCH` | `matched_b_path = matched_c_path = None` | `SKIPPED` |

**承認の similar_candidates 採用ルール**（ADR-010 §「類似候補の提示ポリシー」と整合）:
- `similar_candidates` は距離昇順で既にソート済み（Phase A matcher）
- 先頭の `kind=="B"` を matched_b_path、先頭の `kind=="C"` を matched_c_path に採用
- B / C いずれかしか含まれなくても OK（欠損許容、merger 側で WARN）

### 3.2 行選択挙動

- Treeview で行クリック → 下部「選択中の候補」セクションに詳細表示
- 未選択時は全ボタン無効化
- 選択中の行が各操作で resolved 化されたら Treeview から消える（リフレッシュ）
- 全件解決（Treeview が空）→ 確認ダイアログ「すべて解決しました。閉じて結合へ進みます」→ OK で close

### 3.3 X ボタン (WM_DELETE_WINDOW)

- 未解決 candidate が残っている → 確認ダイアログ「未解決のまま閉じますか？ 後で再開できます」
  - はい → close、return `(resolved_all=False, session)`
  - いいえ → ダイアログ継続
- 全件解決済 → 直接 close、return `(resolved_all=True, session)`

### 3.4 操作ごとの永続化（fail-fast）

各操作（承認/却下/手動選択/スキップ）の直後に:
1. candidate.status と matched_b/c_path を更新
2. `session.updated_at` を現在時刻に更新
3. `save_session(sessions_dir, session)` 呼出
4. 失敗時は例外を呼出元に伝播（UI は中断、握り潰し禁止）

理由:
- UI 操作途中で強制終了しても操作済の解決状態は失われない
- 競合ロックは呼出側が `with_session_lock` で保持しているため衝突しない

## 4. API

```python
@dataclass(frozen=True)
class ConfirmDialogResult:
    session: Session  # UI 終了時点の session（所有は呼出側）
    aborted: bool = False  # Tk callback 例外で mainloop 異常終了時 True

    @property
    def resolved_all(self) -> bool:
        # aborted=True なら常に False（save 失敗後のメモリ全解決状態で READY_TO_MERGE に進むのを防ぐ）
        # それ以外は session.all_candidates_resolved の派生値（二重真実を避けるため property）
        ...

class ConfirmDialog:
    def __init__(
        self,
        session: Session,
        sessions_dir: Path,
        *,
        root: tk.Tk | None = None,  # テスト時に外から注入
        save_session_fn: Callable[..., Path] = save_session,  # テストスタブ
        askopenfilename_fn: Callable[..., str] = filedialog.askopenfilename,
        messagebox_fn: MessageBoxLike | None = None,  # None なら _DefaultMessageBox
    ) -> None: ...

    def run(self) -> ConfirmDialogResult: ...
```

- `root` は通常 `None`（内部で `tk.Tk()` 生成）、テスト時に外から渡す
- `save_session_fn` / `askopenfilename_fn` / `messagebox_fn` は依存性注入でテスト可能に
  - `save_session_fn` の実シグネチャは `save_session(session, *, sessions_dir: Path) -> Path`
  - `messagebox_fn` は `MessageBoxLike` Protocol 準拠（`askyesno` / `showinfo` / `showerror`）
- `run()` は `mainloop()` を呼び、閉じた時点で `ConfirmDialogResult` 返却

## 5. エラー処理

| 状況 | 挙動 |
|------|-----|
| session.status != NEEDS_REVIEW | `ValueError` 送出（呼出側契約違反） |
| candidates に未解決がない | `ValueError` 送出（起動する意味がない） |
| worker thread から呼出 | `RuntimeError` 送出（main thread 必須） |
| save_session が失敗 | Tk callback 経由の未捕捉例外は `_on_callback_exception` が受けて `logger.error`（PII 防御で型名のみ）+ `messagebox.showerror`（画面は PII 露出可）+ `root.quit()`。`ConfirmDialogResult.aborted=True` で返り、`resolved_all` は False 固定。**メモリ上の session は破棄** し on-disk から再ロードすること（resolve_candidate の in-place 更新分が反映されていないため） |
| filedialog が例外を送出（TclError/OSError） | `showerror` 表示後、そのファイル選択だけキャンセル扱い（ダイアログは継続）。業務データ破損なし |
| filedialog キャンセル | 該当フィールドは更新せず（B だけ選べば matched_b_path のみ更新）。片側のみ選択時は `messagebox.askyesno` で「片方のみで確定しますか？」確認 |
| 承認ボタン: similar_candidates が空 | ボタンは disabled。誤って呼ばれた場合は no-op（アサートせず静かに無視） |

## 6. PII 保護

- `logger.info` / `logger.warning` / `logger.error` / `logger.debug` 全てで `user_name_ocr`, `matched_b_path`, `matched_c_path` を含めない
- 例外オブジェクトの **文字列表現（`str(e)`）はファイルパスを含みうる** ため、ログには `type(e).__name__` のみを出す（`logger.exception` は traceback に path を含むので不可）
- ログに出せるのは `session_id`, `page_index`, `confidence`, 操作名（`approved` / `approved_attempt` / `rejected` / `rejected_attempt` / `manually_selected` / `manually_selected_attempt` / `skipped` / `skipped_attempt`）, PairStatus 名, 例外型名
- Tkinter ウィンドウ内（messagebox / Label / Treeview）は PII 表示可（本来の目的、ローカルウィンドウ）

## 7. テスト戦略

- すべてヘッドレスで実行（macOS `TK_SILENCE_DEPRECATION=1`）
- `ConfirmDialog(..., root=tk.Tk())` で外から root 注入 → `withdraw()` で非表示
- 操作は `button.invoke()` で直接発火（イベントループ待機不要）
- `filedialog.askopenfilename` / `messagebox.*` は DI で差し替え
- `mainloop()` は呼ばず、`_apply_operation` 等の内部 API を直接テスト可能にする

## 8. Acceptance Criteria（再掲）

impl-plan Phase 2.7 定義の AC-UI-1〜11 を全て検証する。詳細は PR 本文と `tests/unit/ui/test_confirm_dialog.py` の docstring を参照。

## 9. 非スコープ（PR #B / #C / 将来）

- CLI エントリ (`scripts/review_ui.py`) → PR #B
- `run_phase_b()` との統合 → PR #B
- session.status の `needs_review → ready_to_merge` 遷移 → PR #B
- E2E 統合テスト → PR #C
- 誤記ペア学習辞書（2 回目以降自動承認）→ 将来（ADR-010 §スコープ外）
- タッチ/高 DPI 最適化 → 将来（ADR-009 §スコープ外）

## 10. スクリーンショット（実機確認状況）

### 10.1 現況

PR #A の macOS 開発環境では uv python-build-standalone と Homebrew Python いずれも
`_tkinter` モジュール非同梱（Tcl/Tk ランタイム欠落）で、確認 UI を macOS で起動
することができない。したがって本 PR では **§2 の ASCII ワイヤフレームを期待結果の
仕様定義** として扱う。

CLAUDE.md CRITICAL「UI 変更 → スクリーンショットで期待結果を提示」は、本機能の
本番環境（Windows 11 + 標準バンドル Tk）で実機スクリーンショットを取得することで
最終充足する（**Session 5 タスク 10**: 実 Cloud Run デプロイ + Windows 実機 AC 実測と同時）。

### 10.2 実機確認で撮影予定のカット

- `01-initial.png`: 初期表示（needs_confirmation 2 + no_match 1）
- `02-after-approve.png`: 1 件承認後（Treeview から消える）
- `03-manual-filedialog.png`: 手動選択の filedialog（B 選択）
- `04-all-resolved.png`: 全件解決時の確認ダイアログ
- `05-close-with-unresolved.png`: X ボタン押下時の確認ダイアログ

撮影後、本ドキュメントの本セクションを更新しスクリーンショットをリンクする。

### 10.3 macOS で Tk を有効化したい場合（参考）

今後 macOS 側でも実機確認を行うなら以下のいずれか:

- `brew install python-tk@3.12` + system Python で `.venv` を再作成（依存追加）
- `uv python install 3.11-tk`（公式サポートがあれば。2026-04 時点では未調査）
- Docker + Xvfb + screenshot ツール（CI 併用可）

本 PR 時点ではいずれも実施せず、Windows 実機確認に一元化する判断。
