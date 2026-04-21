# タスク 14C: 施設 PC への配布・展開手順書

> **本手順書は検証用ドラフト**です。ADR-011（配布形式）は現時点 Proposed であり、
> タスク 10-2（Windows 実機 E2E）の結果を 14D で反映して ADR を Accepted 昇格した時点で
> 本手順書も正式版に切り替えます。MVP 第 1 施設への配布は 14D 完了後に実施してください。

介護施設 IT 担当者（または弊社展開担当者）向けに `wiseman_hub.exe` を
Windows 11 PC へ展開し、デスクトップショートカットを作成する手順。

対象読者: Windows PowerShell の基礎知識を持つ IT 担当者。
前提: 配布 ZIP（`wiseman-hub-vX.Y.Z-win-x64.zip`、`X.Y.Z` は配布時のバージョン）を USB で受領済み。

---

## 1. 配布 ZIP の構成

```
wiseman-hub-vX.Y.Z-win-x64.zip
├── wiseman_hub.exe                     ← PyInstaller onefile（未署名、65-70 MB）
├── config/
│   └── default.toml.sample             ← 設定サンプル（施設別に編集）
├── assets/
│   └── icon.ico                        ← Windows ショートカット用アイコン
├── scripts/
│   └── create_shortcut.ps1             ← デスクトップショートカット作成 PS
└── README.txt                          ← 起動・設定・よくあるエラー（タスク 11）
```

ファイルハッシュ（SHA256）は配布時に別途 IT 担当者へ連絡する（改竄検知、ADR-011 運用補強）。

---

## 2. 展開手順

### 2.1 配置場所の選定

| 選択肢 | 管理者権限 | 推奨度 |
|--------|-----------|--------|
| `%USERPROFILE%\wiseman-hub\`（= `C:\Users\<user>\wiseman-hub\`） | 不要 | ◎ MVP 既定 |
| `%LOCALAPPDATA%\wiseman-hub\`（= `C:\Users\<user>\AppData\Local\wiseman-hub\`） | 不要 | ○ エクスプローラに見せたくない場合 |
| `C:\wiseman-hub\` | **必要**（C:\ 直下への新規作成は標準ユーザーで拒否） | △ 施設内共有運用時のみ |
| `C:\Program Files\wiseman-hub\` | 必要 | △ 多ユーザー運用時のみ |

本 MVP は 1 施設 / 1 PC / 少人数運用のため `%USERPROFILE%\wiseman-hub\` を推奨。
以降のコマンド例は `%USERPROFILE%\wiseman-hub\` を前提に記述する（パス差異は読み替え可能）。

### 2.2 ZIP 展開

1. USB から配布 ZIP を `%USERPROFILE%\Downloads\wiseman-hub.zip` 等にコピー
2. **ハッシュ確認**（IT 担当の標準手順）:
   ```powershell
   Get-FileHash $env:USERPROFILE\Downloads\wiseman-hub.zip -Algorithm SHA256
   ```
   **ZIP とは別経路（電話 / 施設の既存チャット / 弊社担当への別メール等の out-of-band 経路）で事前連絡された
   SHA256 と一致することを確認**。ZIP と同じ USB / 同じメールに同梱したハッシュ値は改竄検知の意味を成さない。
   不一致なら展開を中止し弊社へ連絡。
3. エクスプローラで右クリック → 「すべて展開」→ 展開先 `%USERPROFILE%\` を指定
4. 展開後の構成:
   ```
   C:\Users\<user>\wiseman-hub\
   ├── wiseman_hub.exe
   ├── config\
   │   └── default.toml.sample
   ├── assets\
   │   └── icon.ico
   ├── scripts\
   │   └── create_shortcut.ps1
   └── README.txt
   ```

### 2.3 設定ファイルの準備

1. `config\default.toml.sample` を `config\default.toml` にコピー（**リネームではなくコピー**、サンプルは残しておく）
2. テキストエディタ（メモ帳可）で `config\default.toml` を開き、施設固有の設定に編集:
   - フォルダパス（`source_dir` / `user_dir` / `output_dir` 等）
   - `user_name_bbox` 等の施設別パラメータ
   - OCR の endpoint / api_key
3. 文字コードは UTF-8（BOM なし）で保存

本体起動後は「設定」ボタンから GUI で編集可能（タスク 12B で実装済）。
初期値の入力だけ手動で行う。

---

## 3. デスクトップショートカット作成

### 3.1 実行ポリシーの一時解除（PowerShell セッション限定）

標準の Windows 11 では PowerShell 実行ポリシーが `Restricted` のため、
スクリプト実行に**現在のセッション限定の暫定回避**が必要:

```powershell
Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process
```

- `Scope Process`: 現在の PS ウィンドウを閉じると元に戻る（永続化しない）
- レジストリ変更やシステム全体への影響なし
- 管理者権限不要

> **メモ**: 署名済みスクリプト + `RemoteSigned` への移行は、ADR-011 14D で
> コードサイニング購入判断と併せて再評価する（MVP 段階ではスクリプト署名なしのため `Bypass` で運用）。

### 3.2 ショートカット作成

```powershell
cd $env:USERPROFILE\wiseman-hub
.\scripts\create_shortcut.ps1
```

成功時の出力例（配置先によってパスは読み替え）:
```
=== Wiseman PDF ツール ショートカット作成 ===
配布ルート: C:\Users\<user>\wiseman-hub
exe パス : C:\Users\<user>\wiseman-hub\wiseman_hub.exe
アイコン : C:\Users\<user>\wiseman-hub\assets\icon.ico

=== 完了 ===
ショートカット: C:\Users\<user>\Desktop\Wiseman PDF ツール.lnk
Desktop からダブルクリックで起動できます。
```

### 3.3 動作確認

1. Desktop の「Wiseman PDF ツール」アイコンをダブルクリック
2. Launcher GUI（3 ボタン画面）が表示されれば成功
3. 初回起動時の SmartScreen 挙動は後述（§5）

---

## 4. 手動でのショートカット作成（PS スクリプトが使えない場合）

PowerShell 実行が禁止されている環境での fallback:

1. エクスプローラで `%USERPROFILE%\wiseman-hub\wiseman_hub.exe` を右クリック
2. 「ショートカットの作成」を選択（同ディレクトリに `.lnk` が生成）
3. 生成された `.lnk` を Desktop に移動
4. 右クリック → プロパティ → 「アイコンの変更」→
   `%USERPROFILE%\wiseman-hub\assets\icon.ico` を参照
5. 「全般」タブで名前を「Wiseman PDF ツール」に変更

---

## 5. SmartScreen / Windows Defender への対応

本 exe は未署名のため、初回起動時に「WindowsによってPCが保護されました」
ダイアログが出る可能性がある（ADR-011）。

### 5.1 個人 PC / 家庭用 Windows 11

1. ダイアログで「詳細情報」をクリック
2. 「実行」ボタンが表示されるのでクリック
3. 以降は同じ PC で警告なしで起動する

> Windows 11 22H2 以降のダイアログ文言・ボタン名は軽微な差異がある。10-2（本田さん実機）で
> 実画面のボタン名を記録し、本節を正式版で更新する。

### 5.2 Enterprise 管理端末（Microsoft Defender for Endpoint / WDAC 有効）

ポリシー次第で「実行」ボタン自体が表示されない可能性がある。対応:

- **allowlist 登録**: 施設 IT 担当が `wiseman_hub.exe` の SHA256 ハッシュまたはファイルパスを
  事前登録（推奨）。本 MVP は**未署名 exe のため Publisher ルールは不可**、Hash / FilePath ルールのみ実効性あり:
  - **Microsoft Defender for Endpoint**: Security Center → Indicators から SHA256 Hash を追加
    （参考: MS Learn "Microsoft Defender for Endpoint indicators" を IT 担当で検索）
  - **WDAC (Windows Defender Application Control)**: PowerShell で `New-CIPolicyRule -Level Hash`
    または `-Level FilePath` → `.cip` にマージ配信
    （参考: MS Learn "Deploy WDAC policies" を IT 担当で検索）
  - いずれも弊社から**out-of-band 経路で連絡される** SHA256 ハッシュを起点に登録
  - `FilePublisher` / `Publisher` ルールはコードサイニング導入時（ADR-011 14D 以降）に追加検討
- **Microsoft Security Intelligence への提出**: 弊社側で新ビルドごとに
  Microsoft の malware analysis 提出フォーム（`microsoft.com/wdsi/filesubmission` で検索）
  へ提出し、Defender Cloud の誤検知解除を事前実施（URL はリダイレクトされやすいため検索経由を推奨）
- **上記でも解決しない場合**: 配布停止、弊社へ連絡

---

## 6. アンインストール

1. Desktop の「Wiseman PDF ツール.lnk」を削除
2. `%USERPROFILE%\wiseman-hub\`（§2.1 で別パスに配置した場合は当該ディレクトリ）を削除

レジストリ変更なし、Start Menu 登録なしのため上記のみで完全除去可能。

---

## 7. トラブルシューティング

### 7.1 `create_shortcut.ps1` 実行時のエラー

スクリプトは失敗パターンごとに異なる exit code と明示メッセージを返す。

| exit | メッセージ冒頭 | 原因 | 対処 |
|------|--------------|------|------|
| 1 | `wiseman_hub.exe が見つかりません` | 配置ミス | ZIP 再展開、`-ExePath` で絶対パス指定 |
| 1 | `配布ルートディレクトリ ... が解決できません` | ZIP 展開不完全 | ZIP を再取得して展開し直す |
| 1 | `Desktop ディレクトリを特定できません` | Known Folder 構成異常 | OneDrive 同期設定 / ユーザープロファイルを確認 |
| 2 | `WScript.Shell COM オブジェクトを作成できません` | WSH 無効 / ConstrainedLanguage | §4「手動でのショートカット作成」に切替 |
| 3 | `ショートカットの保存に失敗しました` | OneDrive 同期停止 / ASR ルール / ACL 不足 | OneDrive 再開、AV 一時停止（IT 担当判断）、または §4 手動作成 |
| - | `このシステムではスクリプトの実行が無効になっている` | 実行ポリシー | §3.1 を実施してから再実行 |

ASR（Attack Surface Reduction）ルールが `WScript.Shell` の `.lnk` 生成をブロックする既知事象あり
（ESET / Defender 各種）。その場合は §4 の手動作成 fallback を使う。

### 7.2 ダブルクリックでアプリが起動しない

- タスクマネージャで `wiseman_hub.exe` プロセスを確認
  - 起動後すぐ消える → タスク 11 の README 完成後にログ出力手順を追記予定（TBD）。
    暫定対応として、exe と同階層で `cmd` を開き `.\wiseman_hub.exe` を実行してエラー出力を目視確認
- Tkinter ランタイムエラー → タスク 14A ビルド手順書 (`14a-build.md`) の「原因候補」参照
- `config\default.toml` が未配置 → §2.3 を再確認

### 7.3 「Wiseman PDF ツール」のアイコンが表示されない

- `.lnk` を右クリック → プロパティ → 「アイコンの変更」で再指定してアイコンキャッシュ再読込
- Windows 10 / 11 共通: `ie4uinit.exe -ClearIconCache`（要再ログオン、Win11 22H2+ では挙動が不安定な報告あり）
- Windows 11 で上記が効かない場合:
  1. タスクマネージャで `エクスプローラー` を終了
  2. コマンドプロンプトで `del /f "%LocalAppData%\IconCache.db"` 実行
  3. サインアウト → サインインで再生成

---

## 8. 弊社展開担当者向けチェックリスト

> **前提**: ADR-011 が 14D で Accepted 昇格し、10-2 で Windows 実機動作確認が完了していること。
> 本手順書は現時点「検証用ドラフト」扱いのため、正式配布は 14D 完了後に実施する。

配布時に以下を施設 IT 担当者に事前連絡:

- [ ] 配布 ZIP の SHA256 ハッシュ（**ZIP とは別経路** — 電話 / 既存チャット / 別メール等の out-of-band で連絡）
- [ ] 本手順書（14c-deploy.md）の PDF 版または URL
- [ ] `config\default.toml` の施設別初期値（事前ヒアリング結果）
- [ ] SmartScreen 初回警告についての想定挙動（個人 PC か Enterprise 管理端末か、MDE / WDAC 有無）
- [ ] 緊急連絡先（展開時のトラブル対応）

展開後、施設側で以下を実測して弊社に報告:

- [ ] ショートカットからの起動成否
- [ ] SmartScreen ダイアログの有無・ボタン可否
- [ ] Launcher GUI の 3 ボタン動作（PDF 処理 / 確認待ち / 設定）
- [ ] Cloud Run OCR の疎通確認結果

---

## 参考

- ADR-011: 配布形式（PyInstaller onefile + 手動配布）
- タスク 14A: PyInstaller ビルド手順（`14a-build.md`）
- タスク 10-2: Windows 実機 E2E 検証（`windows-e2e-task10.md`）
- タスク 15: GitHub Actions + WIF CI（14A 完了後、ビルド自動化）
