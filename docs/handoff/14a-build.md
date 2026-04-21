# タスク 14A: PyInstaller ビルド手順

`wiseman_hub.exe` を PyInstaller で生成するための手順。macOS 開発機での smoke build と Windows 実機ビルドの両方をカバーする。

## 前提

- Python 3.11+
- `uv` インストール済
- プロジェクトルートで `uv sync --extra dev` 実行済（PyInstaller 6.x が入る）

## macOS smoke build（hidden imports 妥当性検証用）

```bash
cd /path/to/wiseman_auto_sys
uv run pyinstaller --clean wiseman_hub.spec
# → dist/wiseman_hub （単一 binary、66 MB 前後）
```

**目的**: `wiseman_hub.spec` の `hiddenimports` に抜けがないか、import error で落ちないかを PyInstaller の Analysis 段階で検出する。起動確認は Windows 実機で行う（macOS の `runw` bootloader + Tk の組合せは MVP スコープ外）。

**失敗時**:
- `ModuleNotFoundError: No module named '...'` → `wiseman_hub.spec` の `hiddenimports` に追加
- warning `missing module` → 実行時 import でないなら無視可、実行時 import なら追加

## Windows 実機ビルド

本番配布用。初回は本田さん（Windows 11 実機）、以降は GitHub Actions Windows runner（タスク 15）。

```powershell
# Windows PowerShell / CMD
cd C:\Users\<user>\Projects\wiseman_auto_sys
uv sync --extra dev
uv run pyinstaller --clean wiseman_hub.spec
# → dist\wiseman_hub.exe （単一 exe、65-70 MB 前後）
```

### 起動確認（動作テスト）

```powershell
# ダブルクリック起動と同等
.\dist\wiseman_hub.exe
# → Launcher GUI（3 ボタン）が起動すれば OK
```

確認項目:
1. Launcher GUI が表示される
2. taskbar / alt-tab でアイコンが `assets/icon.ico` に差し替わっている
3. 「設定」ボタンで SettingsDialog が開く（config/default.toml が exe 隣にある前提）
4. 「PDF マージ処理」「確認待ちセッション」ボタンも反応する
5. 終了時に残留プロセスがない（Task Manager で `wiseman_hub.exe` が消える）

### config/default.toml の配置

exe と同階層の `config/` サブディレクトリに置く。exe 内部には TOML を埋め込まない方針（ADR-011）:

```
dist/
├── wiseman_hub.exe
└── config/
    └── default.toml
```

未配置時は Launcher の `--config` なし起動で `config/default.toml` を探し、存在しなければエラー表示（挙動は `__main__.py` 参照）。

## Windows Defender / SmartScreen 対応

未署名 exe のため、初回起動時に「WindowsによってPCが保護されました」ダイアログが出る可能性がある。運用手順:

1. ダイアログの「詳細情報」をクリック
2. 「実行」ボタンが表示されるのでクリック
3. 2 回目以降は警告なしで起動する（PC ごとに 1 回のみ）

施設 IT 担当者には事前通知が必要。将来的にコードサイニング証明書を購入すれば回避可能（ADR-011 / 14D で検討）。

## トラブルシューティング

### 起動しない / 一瞬画面が出て消える

- **原因候補 1**: Tk ランタイム未バンドル → `--windowed` の cold start 失敗
  - 対応: spec の `hiddenimports` に `tkinter.ttk`, `tkinter.filedialog`, `tkinter.messagebox` が入っているか確認
- **原因候補 2**: tomlkit / httpx / fitz の hidden import 不足
  - 対応: `--console` で一時ビルドして stderr traceback を確認（`console=True` に変更してリビルド）
- **原因候補 3**: `config/default.toml` 未配置
  - 対応: exe と同階層に `config/default.toml` を置く

### ビルドが遅い

macOS で 30 秒、Windows で 60-90 秒が目安。それ以上かかる場合:
- `--clean` を付けて前回の build cache を削除して再実行
- `build/` と `dist/` を手動削除して完全クリーンビルド

### UPX 警告

本 spec では `upx=False` で無効化済。UPX 圧縮は Windows Defender 誤検知リスクがあるため有効化しない（ADR-011）。

## CI 統合（タスク 15 向け）

GitHub Actions Windows runner で以下を実行する構想:

```yaml
- name: Build exe
  shell: pwsh
  run: |
    uv sync --extra dev
    uv run pyinstaller --clean wiseman_hub.spec
- name: Upload artifact
  uses: actions/upload-artifact@v4
  with:
    name: wiseman_hub-win-x64
    path: dist/wiseman_hub.exe
```

タスク 15 で詳細を詰める。

## 参考

- [PyInstaller 公式ドキュメント](https://pyinstaller.org/en/stable/)
- ADR-002: PyInstaller 選定
- ADR-011: 配布形式
- Issue #59: PyInstaller spec で assets/icon.ico を埋め込み
