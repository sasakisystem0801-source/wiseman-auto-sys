# タスク 14C: 施設 PC への配布・展開手順書

介護施設 IT 担当者（または弊社展開担当者）向けに `wiseman_hub.exe` を
Windows 11 PC へ展開し、デスクトップショートカットを作成する手順。

対象読者: Windows PowerShell の基礎知識を持つ IT 担当者。
前提: 配布 ZIP（`wiseman-hub-v0.1.0-win-x64.zip`）を USB で受領済み。

---

## 1. 配布 ZIP の構成

```
wiseman-hub-v0.1.0-win-x64.zip
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
| `C:\wiseman-hub\` | 不要 | ◎ MVP 推奨 |
| `%USERPROFILE%\wiseman-hub\` | 不要 | ○ 単一ユーザー運用時 |
| `C:\Program Files\wiseman-hub\` | 必要 | △ 多ユーザー運用時のみ |

本 MVP は 1 施設 / 1 PC / 少人数運用のため `C:\wiseman-hub\` を推奨。

### 2.2 ZIP 展開

1. USB から配布 ZIP を `C:\wiseman-hub.zip` 等にコピー
2. **ハッシュ確認**（IT 担当の標準手順）:
   ```powershell
   Get-FileHash C:\wiseman-hub.zip -Algorithm SHA256
   ```
   事前連絡された SHA256 と一致することを確認。不一致なら展開を中止し弊社へ連絡。
3. エクスプローラで右クリック → 「すべて展開」→ 展開先 `C:\` を指定
4. 展開後の構成:
   ```
   C:\wiseman-hub\
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
スクリプト実行に一時的な変更が必要。**現在のセッションのみに適用**される安全な設定を使う:

```powershell
Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process
```

- `Scope Process`: 現在の PS ウィンドウを閉じると元に戻る
- レジストリ変更やシステム全体への影響なし
- 管理者権限不要

### 3.2 ショートカット作成

```powershell
cd C:\wiseman-hub
.\scripts\create_shortcut.ps1
```

成功時の出力例:
```
=== Wiseman PDF ツール ショートカット作成 ===
配布ルート: C:\wiseman-hub
exe パス : C:\wiseman-hub\wiseman_hub.exe
アイコン : C:\wiseman-hub\assets\icon.ico

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

1. エクスプローラで `C:\wiseman-hub\wiseman_hub.exe` を右クリック
2. 「ショートカットの作成」を選択（同ディレクトリに `.lnk` が生成）
3. 生成された `.lnk` を Desktop に移動
4. 右クリック → プロパティ → 「アイコンの変更」→
   `C:\wiseman-hub\assets\icon.ico` を参照
5. 「全般」タブで名前を「Wiseman PDF ツール」に変更

---

## 5. SmartScreen / Windows Defender への対応

本 exe は未署名のため、初回起動時に「WindowsによってPCが保護されました」
ダイアログが出る可能性がある（ADR-011）。

### 5.1 個人 PC / 家庭用 Windows 11

1. ダイアログで「詳細情報」をクリック
2. 「実行」ボタンが表示されるのでクリック
3. 以降は同じ PC で警告なしで起動する

### 5.2 Enterprise 管理端末（Microsoft Defender for Endpoint / WDAC 有効）

ポリシー次第で「実行」ボタン自体が表示されない可能性がある。対応:

- **allowlist 登録**: 施設 IT 担当が `wiseman_hub.exe` の SHA256 ハッシュまたはファイルパスを
  MDE / WDAC の allowlist に事前登録（推奨）
- **Microsoft Security Intelligence への提出**: 弊社側で新ビルドごとに
  [Submit a file for malware analysis](https://www.microsoft.com/wdsi/filesubmission)
  へ提出し、Defender Cloud の誤検知解除を事前実施
- **上記でも解決しない場合**: 配布停止、弊社へ連絡

---

## 6. アンインストール

1. Desktop の「Wiseman PDF ツール.lnk」を削除
2. `C:\wiseman-hub\` ディレクトリを削除

レジストリ変更なし、Start Menu 登録なしのため上記のみで完全除去可能。

---

## 7. トラブルシューティング

### 7.1 `create_shortcut.ps1` 実行時のエラー

| エラー | 原因 | 対処 |
|--------|------|------|
| `このシステムではスクリプトの実行が無効になっている` | 実行ポリシー | §3.1 を実施 |
| `wiseman_hub.exe が見つかりません` | 配置ミス | ZIP 再展開、パスに日本語 / スペース混入確認 |
| `Desktop ディレクトリを特定できません` | 特殊な環境変数構成 | エクスプローラで Desktop を開けるか確認 |
| アクセスが拒否されました | Desktop 書込権限なし | OneDrive Desktop 同期無効化 or `-ExePath` `-IconPath` を絶対パスで指定 |

### 7.2 ダブルクリックでアプリが起動しない

- タスクマネージャで `wiseman_hub.exe` プロセスを確認
  - 起動後すぐ消える → ログ `%TEMP%\wiseman_hub_*.log` を確認（タスク 11 で READMEに記載予定）
- Tkinter ランタイムエラー → タスク 14A ビルド手順書 (`14a-build.md`) の「原因候補」参照
- `config\default.toml` が未配置 → §2.3 を再確認

### 7.3 「Wiseman PDF ツール」のアイコンが表示されない

- `.lnk` を右クリック → プロパティ → 「アイコンの変更」でアイコンキャッシュ再読込
- `ie4uinit.exe -ClearIconCache` で Windows アイコンキャッシュ強制更新（要再ログオン）

---

## 8. 弊社展開担当者向けチェックリスト

配布時に以下を施設 IT 担当者に事前連絡:

- [ ] 配布 ZIP の SHA256 ハッシュ
- [ ] 本手順書（14c-deploy.md）の PDF 版または URL
- [ ] `config\default.toml` の施設別初期値（事前ヒアリング結果）
- [ ] SmartScreen 初回警告についての想定挙動（個人 PC か Enterprise 管理端末か）
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
