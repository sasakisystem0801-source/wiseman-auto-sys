# Windows 実機 E2E 手順書（タスク 10-2）

**作成日**: 2026-04-21
**前提**: タスク 10-1（Cloud Run デプロイ）完了、Service URL + API Key 確定済み

## 目的

Cloud Run にデプロイ済みの OCR プロキシと Windows 実機の CLI を連携させて、
実 PDF から利用者名抽出 → 確認 UI → PDF 結合までの E2E 動作を確認する。

## Cloud Run 接続情報

```
Service URL : https://wiseman-ocr-proxy-v45l5ocwma-an.a.run.app
Region      : asia-northeast1
Project     : wiseman-hub-prod
```

### API Key の取得と配布フロー

**原則**: 現場端末（Wiseman 実機）に GCP 認証情報や `gcloud` CLI を配置しない。
API Key は**運用者（管理者）が自分の端末で取得**し、以下のいずれかで現場端末に渡す:

1. 設定 GUI（タスク 12B 完成後）から運用者が入力 → TOML に保存
2. 現段階では運用者が `config\default.toml` を手動編集

**運用者端末（管理者のみ）で実行:**
```bash
gcloud secrets versions access latest \
    --secret=wiseman-ocr-api-keys \
    --project=wiseman-hub-prod
```

**キーローテーション時の現場再設定:**
- Secret Manager で新バージョン追加 → 旧バージョン disable（30 日グレース推奨）
- グレース期間中に運用者が全現場端末の `config\default.toml` を更新
- グレース期間終了前に全クライアント更新完了を確認
- 詳細: `backend/ocr_proxy/deploy.md` の「キーローテーション」節

## Windows 実機準備

### 1. リポジトリ取得（初回のみ）

```powershell
cd $HOME\Projects
git clone https://github.com/sasakisystem0801-source/wiseman-auto-sys.git
cd wiseman-auto-sys
```

### 2. Python 環境

```powershell
# uv が入っていない場合
pip install uv

uv sync
```

### 3. 設定ファイル編集

`config\default.toml` を開き、以下のセクションを有効化（`#` を外す）+ 値を設定:

```toml
[ocr_backend]
endpoint_url = "https://wiseman-ocr-proxy-v45l5ocwma-an.a.run.app"
api_key = "<上記コマンドで取得した API Key>"
timeout_sec = 30
max_retries = 3

[pdf_merge]
input_dir = "C:\\Users\\<USER>\\Documents\\wiseman_pdfs\\input"
output_dir = "C:\\Users\\<USER>\\Documents\\wiseman_pdfs\\output"
source_a_filename = "A.pdf"           # 複数利用者がまとまった PDF
source_d_filename = "D.pdf"           # 末尾連結する共通 PDF（任意）
source_b_pattern = "B_{name}.pdf"     # B 種別のテンプレート
source_c_pattern = "C_{name}.pdf"     # C 種別のテンプレート
concat_order = ["A", "B", "C"]

[pdf_merge.user_name_bbox]
# A.pdf の 1 ページ目で利用者氏名が印字されている領域（ポイント単位）
# 実 PDF を見て調整する。初回は PDF の左上から大まかな値を入れて試行錯誤
x0 = 50.0
y0 = 50.0
x1 = 300.0
y1 = 100.0
dpi = 200
```

### 4. テスト用 PDF 配置

`input_dir` に以下を配置:

- `A.pdf`: 複数利用者の帳票がまとまった PDF（1 ページ 1 利用者）
- `B_山田太郎.pdf`, `C_山田太郎.pdf` 等: 利用者別 PDF
- `D.pdf`: 全利用者共通で末尾に連結する PDF（任意、なければ `source_d_filename = ""` に変更）

**MVP 規模**: 1〜3 名のテストで十分（AC7 20 名は範囲外）。

## E2E テスト手順

### テスト 1: Phase A（PDF 分割 + OCR + マッチング）

```powershell
uv run python scripts\merge_user_pdfs.py
```

**期待結果**:
- A.pdf が 1 ページずつ分割される
- 各ページの user_name_bbox 領域を切り出し → Cloud Run で OCR
- 抽出された氏名で B/C の候補を検索
- 確度が高ければ自動マッチ、低ければ NEEDS_REVIEW 状態で session 保存
- コンソールに session_id と次に実行すべきコマンドが表示される

**セッション一覧確認**:
```powershell
uv run python scripts\merge_user_pdfs.py --list-sessions
```

### テスト 2: Phase B 確認 UI（Tkinter 実描画）— **AC-UI-6〜10 検証**

```powershell
uv run python scripts\merge_user_pdfs.py --review <session_id>
```

**確認項目（チェックリスト）**:
- [ ] **AC-UI-6**: Tkinter ダイアログが Windows 上で正しく描画される
- [ ] **AC-UI-7**: 候補リスト（B/C 別）が表示される、選択できる
- [ ] **AC-UI-8**: 「手動選択」ボタン → ファイル選択ダイアログ → 任意の PDF 指定可能
- [ ] **AC-UI-9**: 「却下」ボタン → その利用者が結合対象外になる
- [ ] **AC-UI-10**: 「スキップ」ボタン → 未決定で次の利用者へ
- [ ] 全員確認後、session が READY_TO_MERGE 状態になる

### テスト 3: Phase B 結合実行 — **AC-PB-1〜5 検証**

```powershell
uv run python scripts\merge_user_pdfs.py --merge <session_id>
```

**期待結果**:
- REJECTED/SKIPPED を除外した利用者分の PDF を結合
- `output_dir` に結合済み PDF が生成される
- concat_order 通りに A/B/C が並び、末尾に D が付く
- session が COMPLETED になる

**出力 PDF 目視確認**:
- [ ] ページ順序が設定通り
- [ ] 氏名マッチが正しい（別人の B が混入していない）
- [ ] D.pdf が末尾にある
- [ ] REJECTED した利用者が含まれていない

### テスト 4: 異常系 — 欠損 B/C の fail-hard

`B_山田太郎.pdf` だけ削除して `--merge` 再実行:

```powershell
uv run python scripts\merge_user_pdfs.py --merge <session_id>
```

**期待結果**:
- `PdfMergeError` で INTERRUPTED_PHASE_B 停止
- 不完全 output PDF は自動削除
- stderr に**氏名・パスが出ない**（PII 防御、Session 6 で対応済）

### テスト 5: resume / discard

```powershell
# 中断後の再開
uv run python scripts\merge_user_pdfs.py --resume <session_id>

# セッション破棄
uv run python scripts\merge_user_pdfs.py --discard <session_id>
```

## トラブル切り分けフロー

症状から原因候補を特定するためのマトリクス。まず該当行の「確認コマンド」を実行し、ログ採取は次節に記載。

### Phase A（テスト 1）でつまずいた場合

| 症状 | 原因候補 | 確認コマンド / 対応 |
|------|---------|---------------------|
| `OCRAuthError` / HTTP 401 | API Key 未設定 / 誤コピー | `default.toml` の `[ocr_backend] api_key` を再確認。Secret Manager から再取得: `gcloud secrets versions access latest --secret=wiseman-ocr-api-keys --project=wiseman-hub-prod` |
| `OCRAuthError` / HTTP 403 | API Key 失効（rotation） | 同上 + `backend/ocr_proxy/deploy.md` のキーローテーション節確認 |
| HTTP 503 のみ（例外トレース） | 1x1 PNG / 極小画像 / OCR 不能 | `user_name_bbox` の座標が狭すぎないか確認（x1-x0, y1-y0 ≥ 50pt 目安） |
| `FileNotFoundError: A.pdf` | `input_dir` にファイル未配置 | `dir <input_dir>` で実在確認。パス区切りは `\\`（TOML 内は 2 重バックスラッシュ） |
| セッション作成されるが氏名空 | `user_name_bbox` ずれ / PDF がスキャン画像で OCR 不能 | `python -c "import fitz; d=fitz.open(r'A.pdf'); print(d[0].get_pixmap(clip=(x0,y0,x1,y1), dpi=200).save('debug.png'))"` で bbox 画像を目視確認 |
| 全利用者が NEEDS_REVIEW 状態 | 氏名マッチ閾値未達（B/C ファイル名と一致しない） | B/C ファイル名のフリガナ/漢字表記揺れ確認。確認 UI（テスト 2）で手動選択できれば機能的には OK |

### Phase B 確認 UI（テスト 2）の描画問題

| 症状 | 原因候補 | 対応 |
|------|---------|------|
| ダイアログが表示されない / 一瞬出て消える | Python 未 frozen 実行で Tk ランタイム未解決（Windows の場合稀） | `python -c "import tkinter; tkinter.Tk().mainloop()"` で Tk 単体起動確認 |
| 文字化け（□ や ? 表示） | フォント解決失敗 | Windows 10/11 標準フォント（Meiryo UI）の存在確認、他 PC でも再現するか確認 |
| 高解像度でボタン/文字が極小 | DPI awareness 未有効（Windows 10+） | `windows-e2e-task10.md` 完了後に Issue 化、MVP では運用上 OK（ディスプレイ解像度を 100% に一時変更で回避可） |
| 「手動選択」でファイル選択ダイアログが出ない | `tkinter.filedialog` 未バンドル（exe 化後のみ） | spec の `hiddenimports` に `tkinter.filedialog` 含む（14A 確認済）。uv 経由実行では発生しない |

### Phase B 結合（テスト 3-4）の問題

| 症状 | 原因候補 | 対応 |
|------|---------|------|
| 出力 PDF が生成されない | 出力ディレクトリへの書込権限なし | `output_dir` を `%USERPROFILE%` 配下に変更（C:\ 直下は標準ユーザー書込不可） |
| `PdfMergeError: ...` が出るが氏名/パスが stderr に出ない | **正常**（PR #84 / Issue #76 で PII 防御済） | `client.log` 内の `__cause__` 経由で元例外を確認 |
| 出力順序が concat_order と異なる | `[pdf_merge] concat_order` 設定ミス | TOML のリスト順と利用者数 × セクション数が一致しているか確認 |

### exe 起動失敗（タスク 14C 以降で発生する場合）

→ `docs/handoff/14a-build.md` §トラブルシューティング参照（Tk ランタイム / hidden imports / config 配置）。10-2 範囲では exe ビルド後起動までをスコープ対象とする。

### SmartScreen 警告（初回起動）

想定内。「詳細情報 → 実行」で通過。2 回目以降は警告なし。詳細は `docs/handoff/14c-deploy.md` §5.1。

---

## 問題発生時のログ取得

### クライアント側
```powershell
uv run python scripts\merge_user_pdfs.py 2>&1 | Tee-Object -FilePath client.log
```

### Cloud Run 側
```bash
# macOS 開発機から確認
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="wiseman-ocr-proxy"' \
    --project=wiseman-hub-prod --limit=50 --format=json
```

## 完了条件（AC 対応）

| AC | 内容 | 検証 |
|----|------|------|
| AC2 | 実 PDF → 氏名抽出成功 | テスト 1 |
| AC-UI-6 | Tkinter 描画 | テスト 2 チェックリスト |
| AC-UI-7 | 候補選択 | テスト 2 |
| AC-UI-8 | 手動選択 | テスト 2 |
| AC-UI-9 | 却下 | テスト 2 |
| AC-UI-10 | スキップ | テスト 2 |
| AC-PB-1 | READY_TO_MERGE → COMPLETED + 出力 PDF 生成 | テスト 3 |
| AC-PB-2 | merger 失敗 → INTERRUPTED_PHASE_B | テスト 4 |
| AC-PB-3 | REJECTED/SKIPPED 除外 | テスト 3 |
| AC-Missing | 欠損 B/C で fail-hard + output 削除 + PII 漏洩なし | テスト 4 |

すべて PASS すれば タスク 10-2 完了 → タスク 13A（ランチャー GUI 骨格）着手へ。

## 発見された問題の記録先

- GitHub Issue を作成（`gh issue create`）
- タグ: `bug` + `P1` or `P2`
- 本セッションに戻って報告

## 既知の制約（本セッションで発見済み）

- **Cloud Run ヘルスチェックは `/health`**: `/healthz` は GFE 予約パス衝突で 404 を返していたため、PR #89（Issue #58）で `/health` にリネーム済
- **1x1 透明 PNG は 503**: Vertex AI が INVALID_ARGUMENT を返す（正常動作、極小画像は OCR 不能）
- **SmartScreen 警告**（.exe 化後）: 署名なしのため初回起動時「詳細情報 → 実行」手順が必要
