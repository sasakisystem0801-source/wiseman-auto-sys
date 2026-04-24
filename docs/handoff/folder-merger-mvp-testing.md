# 事業所フォルダ PDF 結合 MVP 実機検証記録

**PR**: #108 (feat/folder-merger-mvp)
**対象**: tasks/Session 19 Windows 実機検証
**実施日**: _(実施後に記入)_
**実施者**: _(実施後に記入)_

---

## 検証前チェックリスト

### 環境
- [ ] Windows 11 PC で PowerShell 起動
- [ ] `git fetch origin && git checkout feat/folder-merger-mvp && git pull` 完了
- [ ] `uv sync` 完了（新規依存なしのため即完了のはず）
- [ ] `uv run pytest tests/unit/pdf/test_facility_merger.py -q` 通過（530 passed + 新規 4）

### データ
- [ ] A.pdf（提供実績チェックリスト）を OneDrive デスクトップに配置済み
- [ ] 事業所フォルダ（例: `\\Tera-station\share\03.FAX(事業所)\きなり(メール)※持参`）に Tera-station 経由でアクセス可能
- [ ] 配下に `運動機能向上計画書/` と `経過報告書/` が存在
- [ ] 出力先ディレクトリ（`OneDrive\デスクトップ\本田様\きなり` など）が書込可能

---

## 1. CLI 実機検証（AC-FM-7 最小）

### 実行コマンド

```powershell
cd $HOME\Projects\wiseman-auto-sys

uv run python scripts\merge_facility.py `
    -a "C:\Users\sasak\OneDrive\デスクトップ\本田様\きなり\202603_提供実績_ささき整形外科デイケアセンター(2814101271)_居宅介護支援事業所　きなり(2874101146)_20260409.pdf" `
    -f "\\Tera-station\share\03.FAX(事業所)\きなり(メール)※持参" `
    -o "C:\Users\sasak\OneDrive\デスクトップ\本田様\きなり"
```

### 確認項目

| # | 項目 | 期待 | 結果 |
|---|------|------|------|
| 1 | exit code | `0`（success > 0 なら） | _(記入)_ |
| 2 | サマリ表示の `成功: N 件` | 1 以上 | _(記入)_ |
| 3 | `extraction_failed`（ページ番号） | 0 件 or 少数 | _(記入)_ |
| 4 | `a_only` / `a_missing` / `b_missing` / `c_missing` | 実データ構成と整合 | _(記入)_ |
| 5 | `name_conflicts`（同姓連番） | 発生する場合 `_2` suffix 確認 | _(記入)_ |
| 6 | `ambiguous_bc_skipped`（同姓 fail-safe） | 発生時は A のみ出力 | _(記入)_ |
| 7 | `$HOME\Documents\wiseman_output\...` ではなく**指定した OneDrive 配下**に出力されているか | 指定先に出力 | _(記入)_ |
| 8 | 出力 PDF を Adobe Reader で開けるか | 正常に開く | _(記入)_ |
| 9 | 結合順: A ページ → B → C | 正しい順序 | _(記入)_ |
| 10 | 氏名マッチの妥当性（目視） | 別人の B/C が入っていない | _(記入)_ |

### サマリ出力（貼り付け）

```
(CLI 実行結果をここに貼り付け)
```

### 生成ファイル（エクスプローラ）

```
(Get-ChildItem $out\きなり(メール)※持参\ の結果を貼り付け)
```

---

## 2. GUI 実機検証

### 実行

**方法 A: 開発環境直接起動**
```powershell
cd $HOME\Projects\wiseman-auto-sys
uv run python -m wiseman_hub
```

**方法 B: exe 再ビルド後（時間余れば）**
```powershell
uv run pyinstaller --clean wiseman_hub.spec
# → dist\wiseman_hub.exe → 配布先上書き
Copy-Item dist\wiseman_hub.exe $HOME\wiseman-hub\ -Force
# デスクトップショートカットから起動
```

### 確認項目

| # | 項目 | 期待 | 結果 |
|---|------|------|------|
| 1 | Launcher に **4 ボタン** 表示 | PDF マージ / 確認 / **事業所フォルダ結合** / 設定 | _(記入)_ |
| 2 | 「事業所フォルダ結合」クリック | Toplevel ダイアログ出現 | _(記入)_ |
| 3 | A.pdf の [参照...] ボタン | askopenfilename が開く、PDF を選択可 | _(記入)_ |
| 4 | 事業所フォルダの [参照...] | askdirectory が開く、UNC パスを選択可 | _(記入)_ |
| 5 | 出力ルートの [参照...] | askdirectory が開く | _(記入)_ |
| 6 | 未入力のまま [実行] | showerror（「全てを指定してください」） | _(記入)_ |
| 7 | 正常入力 → [実行] | サマリが Text widget に表示 | _(記入)_ |
| 8 | サマリに **user_key のみ**表示、フルネーム非表示 | PII 防御 OK | _(記入)_ |
| 9 | 存在しないパス指定 → [実行] | showerror（型名のみ、パス漏洩なし） | _(記入)_ |
| 10 | [閉じる] ボタン | ダイアログ閉じる、Launcher に戻る | _(記入)_ |

---

## 3. Windows 特有の確認（Codex 実機優先確認から）

| # | ケース | 確認方法 | 結果 |
|---|-------|---------|------|
| 1 | **同姓 2 名 + B/C 1 式で誤添付しない** | A に同姓 2 名を仕込み、B/C に 1 ファイルだけ用意 → 両者とも A のみ出力、`ambiguous_bc_skipped` に記録 | _(記入)_ |
| 2 | **UNC パス（`\\Tera-station\...`）が `askdirectory` / 手入力の両方で通る** | ダイアログで選択 + 手入力 Entry で直接ペースト | _(記入)_ |
| 3 | **B/C 片方を一時切断しても静かに A-only 量産しない** | ネットワーク一時断シミュレート（LAN ケーブル抜く / VPN 切断）→ warning ログが出るか | _(記入)_ |
| 4 | **Acrobat / Explorer プレビューで PDF を開いたまま**出力時に `os.replace` が失敗しないか | 出力予定の PDF を Adobe で開いた状態で再実行 → atomic_io の `os.replace` が Windows で PermissionError を投げる挙動を観察 | _(記入)_ |
| 5 | **日本語長パス（260 文字超）で `tmp` 作成と `os.replace` が失敗しないか** | 深いネスト + 長い事業所名でシミュレート | _(記入)_ |

---

## 4. 発見された問題

### Critical
_(あれば記入)_

### Important
_(あれば記入)_

### Minor / Future Improvement
_(あれば記入)_

---

## 5. AC 判定

| AC | 内容 | 判定 |
|----|------|------|
| AC-FM-1 | A+B+C 全揃い結合 | _(PASS/FAIL)_ |
| AC-FM-2 | 片側のみで欠損なし出力 | _(PASS/FAIL)_ |
| AC-FM-3 | 欠損利用者の report 記録 | _(PASS/FAIL)_ |
| AC-FM-4 | 出力パス規約 | _(PASS/FAIL)_ |
| **AC-FM-5** | **UNC パス動作** | _(PASS/FAIL)_ |
| AC-FM-6 | 両フォルダ無しで FileNotFoundError | _(PASS/FAIL)_ |
| **AC-FM-7** | **実機 CLI 実行成功** | _(PASS/FAIL)_ |
| AC-UI-FM-1 | GUI ダイアログ描画 | _(PASS/FAIL)_ |
| AC-UI-FM-2 | PII 防御（サマリに full_name 出さない） | _(PASS/FAIL)_ |

---

## 6. 次のアクション

- [ ] AC 全 PASS → PR #108 を ready for review に昇格、マージ
- [ ] 問題あれば本ファイルに追記 → fix コミットで対応
- [ ] マージ後: ハンドオフ `docs/handoff/LATEST.md` を Session 19 で更新
- [ ] 将来タスク起票候補:
  - B/C PDF テキスト層からの氏名抽出（内容ベースマッチ）
  - 親フォルダから複数サブフォルダ選択 UI
  - worker thread 非同期化（進捗バー）
  - exe 再ビルド + 配布先差し替え手順
