# ADR-011: 配布形式（PyInstaller onefile + 手動配布）

## ステータス
**Proposed (2026-04-21)** — 14A 完了時点。14D で Accepted に昇格予定。

## コンテキスト

ADR-002（PyInstaller 選定）で「Python アプリを PyInstaller で exe 化する」方針は確定済。
タスク 14A で `wiseman_hub.spec` を作成し、具体の配布形式を確定する必要がある。

制約:
- **対象規模**: 1 施設 / 1 PC / 1-3 名 per batch の MVP 運用（ADR-008 / PRD）
- **配布経路**: 弊社担当が USB で直接持参 → Windows 11 PC の `C:\Program Files\wiseman-hub\` 等に配置
- **認証**: USB ドングル（ADR-007）、クラウドアカウント不要
- **更新頻度**: 低（機能追加 or バグ修正時のみ、自動更新は不要、ADR-004 の自動更新方針は保留中）
- **ネットワーク**: Cloud Run OCR（ADR-008）へのアウトバウンドのみ、インバウンド不要
- **セキュリティ**: 医療介護 PII を扱うため署名・検疫体制が理想だが、コードサイニング証明書は購入コスト大

## 決定

### 配布形式

| 項目 | 値 | 理由 |
|------|----|------|
| ビルドモード | `--onefile` | 単一 exe で USB 配布運用に最適、ディレクトリ構造の不整合で起動失敗するリスクなし |
| ウィンドウモード | `--windowed`（`console=False`）| Launcher GUI がユーザー接点、コンソール窓不要 |
| アイコン | `assets/icon.ico` | 14B で生成済、Windows taskbar/alt-tab で識別可能 |
| UPX 圧縮 | 無効 | Windows Defender / SmartScreen の誤検知リスク、介護施設 PC で検疫フラグ立つと運用停止 |
| コードサイニング | 未実施（保留） | 証明書コスト vs 実害（SmartScreen の警告ダイアログ 1 回のみ）のトレードオフ、14D で再検討 |

### 配布レイアウト

```
wiseman-hub/                    # 配布 ZIP を展開した結果
├── wiseman_hub.exe             # PyInstaller onefile
├── config/
│   └── default.toml            # 設定ファイル（exe と同階層の相対パス、編集可能）
├── assets/
│   └── icon.ico                # ショートカット用（タスク 14C）
└── README.txt                  # 起動・設定・よくあるエラー（タスク 11）
```

`config/default.toml` は exe 外に配置（設定 GUI の書き戻しを可能にするため）。
`default` 命名は今後複数プロファイル（施設別等）への拡張余地を残すため。

### 配布パッケージ

- 形式: ZIP（`wiseman-hub-v0.1.0-win-x64.zip`）
- 配布物:
  - `wiseman_hub.exe`
  - `config/default.toml`（サンプル、施設別に編集）
  - `assets/icon.ico`
  - `README.txt`
- USB 配布時は施設側で任意ディレクトリに展開
- ショートカット作成スクリプト（タスク 14C）で Desktop にアイコン付きショートカットを配置

### ビルド環境

- Windows 実機ビルド（初回は本田さん、以降は GitHub Actions Windows runner、タスク 15）
- macOS 開発機は hidden imports 妥当性の smoke build のみ（`dist/wiseman_hub` 単一バイナリが生成されれば OK）
- クロスコンパイル不可（PyInstaller の制約）

## 検討した代替案

### `--onedir` モード
- 長所: 起動速度が速い（--onefile は毎回 tempdir に解凍）、デバッグ容易
- 短所: ディレクトリ構造で配布、ファイル欠損で silent failure、USB コピー時の不整合リスク
- 判断: MVP は `--onefile` 採用。起動速度は 1-2 秒程度の差で業務影響軽微。

### Windows MSI / Inno Setup インストーラ
- 長所: Program Files への配置、Start Menu 登録、アンインストール対応
- 短所: インストーラ作成の工数（WiX / Inno Setup の学習）、コードサイニングなしだと MSI も SmartScreen 対象
- 判断: 対象規模 1 施設のため過剰。14D で再評価。

### Python 環境 + バッチファイル起動
- 長所: ビルド不要、モジュール単位の更新可能
- 短所: Python ランタイム依存、施設 PC に Python インストール必要、PATH 設定トラブル
- 判断: 介護施設運用者に Python 前提は無理。却下。

### コードサイニング
- 長所: SmartScreen 警告回避、マルウェア誤検知リスク低減
- 短所: DigiCert / Sectigo の証明書 1 年 3-5 万円、更新手続きコスト、EV 証明書はさらに高額
- 判断: MVP スコープ外、14D で運用開始後の問題発生頻度を見て再検討。

## 影響

### 肯定的

- 単一 exe で USB 配布できる（介護施設運用者の操作負荷最小）
- exe 外の TOML で設定を変更可能（再ビルド不要）
- アイコン埋め込みで Windows UI 上の識別性確保
- UPX 無効で Windows Defender 誤検知リスク排除

### 否定的

- `--onefile` は毎回起動時に tempdir に解凍 → 起動 2-3 秒の遅延
- 未署名 exe → SmartScreen の「不明な発行元」警告（施設 IT 担当者に事前通知が必要）
- Cross-compile 不可 → macOS 開発機で本番 exe は作れず、Windows 実機 / CI が必須

## 14A 完了時点の実装

- `wiseman_hub.spec`: Entry / Icon / Hidden imports / UPX 無効 / --onefile + --windowed 定義
- `pyproject.toml`: `pyinstaller>=6.11.0` を dev 依存に追加済（14A で確認）
- macOS smoke build: `dist/wiseman_hub` 66 MB 生成成功、hidden imports 妥当性確認

## 次ステップ（14C / 14D / 10-2）

- **14C**: ショートカット作成スクリプト（PowerShell）、`README.txt` ドラフト
- **14D**: 本 ADR を Accepted に昇格、コードサイニング要否の運用判断を追記
- **10-2**: Windows 実機ビルド + E2E 検証（本田さん実施）、SmartScreen 挙動記録

## 参考

- ADR-002: PyInstaller 選定
- ADR-007: USB ドングル認証（認証状態を exe に埋め込まない設計）
- Issue #59: PyInstaller spec で assets/icon.ico を --icon で埋め込み
