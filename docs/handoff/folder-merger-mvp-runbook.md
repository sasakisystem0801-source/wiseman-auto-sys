# 事業所フォルダ PDF 結合 MVP 実機ランブック

**所要: 30 分で成功報告まで到達**することを目的に、手順の順番と判断ポイントを明示する。

**前提**: PR #108 (feat/folder-merger-mvp) マージ前の実機検証。Windows 11 + TeamViewer アクセス可能。

---

## 🎯 このランブックのゴール

1. 実 A.pdf + 実 B/C フォルダで **少なくとも 1 利用者分の結合 PDF が出力される**
2. サマリ出力で異常パターン（抽出失敗 / 同姓重複 / 欠損）が可視化される
3. 出力 PDF を開いて**氏名マッチが正しい**ことが目視確認できる

失敗した場合は「**問題の早期切り分け**」を優先し、実装修正 or 要件調整の判断に進む。

---

## 📋 Step 0: 環境セットアップ（5 分）

### 0-1. TeamViewer 再接続 + PowerShell 起動

管理者権限不要。通常 PowerShell で OK。

### 0-2. リポジトリ最新化

```powershell
cd $HOME\Projects\wiseman-auto-sys
git fetch origin
git checkout feat/folder-merger-mvp
git pull
git log --oneline -4
```

**期待コミット**（最新から4件）:
```
b66baa2 fix(pdf): Codex HIGH - 同姓重複時の B/C 誤添付を fail-safe で防止
7ce1965 feat(ui): Launcher に「事業所フォルダ結合」ボタン追加
d3e6aab refactor(pdf): review-pr フィードバック反映
8a09e49 feat(pdf): facility_merger - 事業所フォルダ PDF 結合 (MVP 暫定)
```

### 0-3. 依存同期 + ユニットテスト

```powershell
uv sync
uv run pytest tests/unit/pdf/test_facility_merger.py tests/unit/pdf/test_text_name_extractor.py -q
```

**期待**: 23+4 tests passed。1 件でも fail したら Step 1 に進まず、エラー内容を共有。

---

## 🔍 Step 1: 事前診断（5 分）— **書込なし、問題早期発見**

**最重要**: 本実行の前に必ず `--diag` で実データと実装の整合を確認する。これで「書込失敗」「氏名抽出失敗」「予想外のマッチ」を**PDF を一枚も書かずに検知できる**。

```powershell
$a_pdf = "C:\Users\sasak\OneDrive\デスクトップ\本田様\きなり\202603_提供実績_ささき整形外科デイケアセンター(2814101271)_居宅介護支援事業所　きなり(2874101146)_20260409.pdf"
$facility = "\\Tera-station\share\03.FAX(事業所)\きなり(メール)※持参"
$output = "C:\Users\sasak\OneDrive\デスクトップ\本田様\きなり"

uv run python scripts\merge_facility.py `
    --a "$a_pdf" `
    --facility "$facility" `
    --output "$output" `
    --diag
```

### 診断結果で確認すること

```
[B] 運動機能向上計画書: N files
  - 【藤野様】.pdf
  - asao.pdf
  - 塩津.pdf
  - 尾島.pdf

[C] 経過報告書: M files
  - 塩津.pdf
  - 日浦.pdf
  - 尾島.pdf

A.pdf ページ別氏名抽出 + マッチ予測
  p 1: 塩津 美貴子  B=塩津.pdf   C=塩津.pdf   → A+B+C
  p 2: 尾島 太郎   B=尾島.pdf   C=尾島.pdf   → A+B+C
  ...
```

| 観察 | 意味 | 次のアクション |
|-----|------|--------------|
| 全ページで氏名抽出成功 + 期待通りマッチ | ✅ **理想**、Step 2 へ進む | Step 2 本実行 |
| 氏名抽出失敗ページあり | A.pdf のテキスト層の構造違い、または正規表現と実データの揺らぎ | 失敗ページの「ページ番号」を共有 → 正規表現調整 |
| 全ページ抽出失敗 | A.pdf がスキャン画像（テキスト層なし） | OCR 必要、MVP スコープ外、要件再検討 |
| 同姓重複 (AMBIGUOUS) が想定外の姓で発生 | 別人の誤添付リスク回避中 | 該当姓の B/C は fail-safe でスキップ、意図通りならそのまま Step 2 |
| B/C に期待するファイル名が無い | ファイル名規則が違う | 運用で事前リネーム or マッチ規則を追加 |

**判断**: 診断結果が「期待と 7-8 割以上一致」なら Step 2 へ。そうでなければ Step 2 を**スキップ**して、診断結果のスクショを送って相談。

---

## 🚀 Step 2: 本実行（CLI、5 分）

診断で問題なければ `--diag` を外して実行。

```powershell
uv run python scripts\merge_facility.py `
    --a "$a_pdf" `
    --facility "$facility" `
    --output "$output"
```

### 成功判定

**exit code 0** + サマリに `成功: N 件` (N >= 1) で**今日のゴール達成**。

出力ディレクトリを確認:

```powershell
Get-ChildItem "$output\きなり(メール)※持参\" | Format-List Name, Length
```

---

## ✅ Step 3: 生成 PDF の目視確認（5 分）

```powershell
# 最初の 1 件を開く（Adobe Reader）
$first = Get-ChildItem "$output\きなり(メール)※持参\" -Filter *.pdf | Select-Object -First 1
Start-Process $first.FullName
```

### チェック項目

| # | 項目 | 期待 |
|---|------|------|
| 1 | 1 ページ目に **「令和 08 年 03 月分 提供実績チェックリスト」** + 対象利用者氏名 | ✅ |
| 2 | 2 ページ目に **「運動器機能向上計画書」** + 同じ利用者氏名 | ✅（マッチ成功の決定的証拠） |
| 3 | 3 ページ目以降に **「利用経過報告書」** + 同じ利用者氏名 | ✅ |
| 4 | **別人の書類が紛れ込んでいない** | 絶対！ |
| 5 | ファイル名の姓と中身の利用者が一致 | ✅ |

**1 件 OK** なら今日の「PDF 再結合処理のテスト成功」達成 🎉 残り時間で GUI 確認・他利用者確認に進む。

---

## 🖥️ Step 4: GUI 実機確認（10 分、時間があれば）

```powershell
uv run python -m wiseman_hub
```

### 確認項目

| # | 項目 | 期待 |
|---|------|------|
| 1 | Launcher に **4 ボタン** 表示（PDFマージ / 確認 / **事業所フォルダ結合** / 設定） | ✅ |
| 2 | 「事業所フォルダ結合」クリック → ダイアログ表示 | ✅ |
| 3 | [参照...] で A.pdf 選択、事業所フォルダ選択、出力先選択 | ✅ |
| 4 | [実行] → 結果 Text に CLI と同じサマリ表示 | ✅ |
| 5 | サマリに**フルネーム（`美貴子`等）が含まれていない**（user_key のみ） | PII 防御 OK |
| 6 | [閉じる] で Launcher に戻る | ✅ |

---

## 🚨 問題発生時の切り分け早見表

| 症状 | 原因候補 | 対応 |
|------|---------|------|
| `uv sync` で失敗 | 仮想環境破損 | `Remove-Item .venv -Recurse -Force; uv sync` |
| 診断で全ページ抽出失敗 | A.pdf がスキャン画像 | **Step 2 中止**、要件再検討 |
| 診断で UNC パスが「存在しません」 | Tera-station 未マウント or 認証失効 | エクスプローラで `\\Tera-station\share` を開く、認証再入力 |
| `os.replace` が PermissionError | 出力先 PDF を Acrobat で開いたまま | Adobe Reader を閉じて再実行 |
| 出力 PDF が「田中」のみ、中身が「田中 太郎」と「田中 花子」混在 | 同姓 fail-safe が効いていない | **即中止**、実装バグとして報告（Codex 対応済のはず） |
| `[WinError 3]` システムはパスを見つけられません | MAX_PATH 260 超え | 出力パスを `C:\wm_out\` 等の短いパスに変更 |
| 「ERROR (FileNotFoundError)」で止まる | 引数パスのスペル違い | 引数を `"` で囲む、`--diag` で先に確認 |

### 最悪シナリオ: 何も動かない

```powershell
# 最小単位のフォールバック: 1 利用者手動結合テスト
uv run python -c "
import fitz
from pathlib import Path
a = Path(r'$a_pdf')
b = Path(r'$facility\運動機能向上計画書\塩津.pdf')
c = Path(r'$facility\経過報告書\塩津.pdf')
doc = fitz.open()
with fitz.open(a) as s: doc.insert_pdf(s, from_page=0, to_page=0)
if b.exists():
    with fitz.open(b) as s: doc.insert_pdf(s)
if c.exists():
    with fitz.open(c) as s: doc.insert_pdf(s)
out = Path(r'$output\\fallback_塩津.pdf')
out.parent.mkdir(parents=True, exist_ok=True)
doc.save(str(out))
doc.close()
print(f'saved: {out}')
"
```

これで PDF が生成できれば、**pymupdf は動く = 実装のどこかが原因**と切り分けられる。

---

## 📝 成功後のアクション

1. **`docs/handoff/folder-merger-mvp-testing.md`** に検証結果を記入
2. PR #108 を **draft → ready for review → マージ**
3. ハンドオフ `docs/handoff/LATEST.md` を Session 19 として更新
4. 次 PR 候補を Issue 化（B/C PDF 内容抽出、複数フォルダ選択 UI、exe 再ビルド）

---

## 📞 連絡ルール

- **ステップ毎に出力 or スクショを共有**（問題なく進んでも「Step 1 診断 OK」の一言でペースが分かる）
- **期待と違う結果はすぐ共有**（勝手に進めない）
- **PII 含む可能性がある場合**（氏名・利用者コード）は共有前に墨塗りするか、最小情報（「荒木」だけ）に絞る
