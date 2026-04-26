# ADR-011: 配布形式（PyInstaller onefile + 手動配布）

## ステータス
**Accepted (2026-04-27)** — Session 26 で本田様の Windows 11 実機にて 14D 昇格条件 1-4 を達成。`wiseman_hub.exe` (78,570,672 bytes) を `d83a3de` HEAD で再ビルド + 配布、Launcher GUI 4 ボタン（PDFマージ処理 / 確認待ちセッション / 事業所フォルダ一括結合 / 設定）動作確認、UNC パス + 日本語事業所名（`\\Tera-station\share\03.FAX(事業所)`）での実環境動作確認、Phase A regression smoke 完走。SmartScreen は既存 hash reputation 確立済のため新規警告なし。コードサイニング要否は 1 施設運用継続のため当面なしを継続（運用補強で対応）。

### 変更履歴

- 2026-04-21: 14A 完了、Proposed として作成
- 2026-04-22: 14C 実装に伴い配布レイアウトを更新（`default.toml.sample` 命名に変更、
  `scripts/create_shortcut.ps1` を配布物に追加）。14C の施設 IT 担当者向け手順書
  `docs/handoff/14c-deploy.md` と整合。
- 2026-04-27（Session 26）: PR #124 + #126 の本番稼働確認完了 → Accepted 昇格

## コンテキスト

ADR-002（PyInstaller 選定）で「Python アプリを PyInstaller で exe 化する」方針は確定済。
タスク 14A で `wiseman_hub.spec` を作成し、具体の配布形式を確定する必要がある。

制約:
- **対象規模**: 1 施設 / 1 PC / 1-3 名 per batch の MVP 運用（ADR-008 / PRD）
- **配布経路**: 弊社担当が USB で直接持参 → Windows 11 PC の `C:\Program Files\wiseman-hub\` 等に配置
- **認証**: USB ドングル（ADR-007）、クラウドアカウント不要
- **更新頻度**: 低（機能追加 or バグ修正時のみ）。ADR-004（GCS manifest ポーリング）は Accepted だが MVP 段階では未実装のため、当面は手動配布（USB 持参）で運用する。
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
| コードサイニング | 未実施（保留、条件付き） | 証明書コストのトレードオフ、14D で再検討。**重要**: SmartScreen の「警告 1 回のみ」は個人 PC + 既知 publisher reputation 前提の理想論。現実には (1) 新ビルドごとに file hash reputation がリセット、(2) Enterprise policy（Microsoft Defender for Endpoint / WDAC）適用端末で「実行」導線が消えて配布停止の可能性、(3) Mark-of-the-Web 付き ZIP 配布で SmartScreen のチェックが強化される。下記「運用補強」で緩和する。 |

### 配布レイアウト

```
wiseman-hub/                         # 配布 ZIP を展開した結果
├── wiseman_hub.exe                  # PyInstaller onefile
├── config/
│   └── default.toml.sample          # 設定サンプル（施設側で default.toml にコピーして編集）
├── assets/
│   └── icon.ico                     # ショートカット用（タスク 14C）
├── scripts/
│   └── create_shortcut.ps1          # Desktop ショートカット作成（タスク 14C）
└── README.txt                       # 起動・設定・よくあるエラー（タスク 11）
```

`config/default.toml` は exe 外に配置（設定 GUI の書き戻しを可能にするため）。
`.sample` 命名で配布し、施設側でコピー → 編集する運用（上書き事故防止、`14c-deploy.md` §2.3）。
`default` 命名は今後複数プロファイル（施設別等）への拡張余地を残すため。

### 配布パッケージ

- 形式: ZIP（`wiseman-hub-vX.Y.Z-win-x64.zip`、`X.Y.Z` はビルドバージョン）
- 配布物:
  - `wiseman_hub.exe`
  - `config/default.toml.sample`（サンプル、施設側で `default.toml` にコピーして編集）
  - `assets/icon.ico`
  - `scripts/create_shortcut.ps1`（14C、Desktop ショートカット作成）
  - `README.txt`（14C 手順書の要点抜粋、タスク 11 で作成予定）
- USB 配布時は施設側で任意ディレクトリに展開
- ショートカット作成スクリプトで Desktop にアイコン付きショートカットを配置
  （詳細手順: `docs/handoff/14c-deploy.md`）

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

### 運用補強（サイニングなしで配布する場合の必須手順）

- **事前 hash 共有**: 配布 ZIP / exe の SHA256 を施設 IT 担当に事前連絡（改竄検知）
- **Microsoft Security Intelligence 提出**: 新ビルドごとに [Submit a file for malware analysis](https://www.microsoft.com/wdsi/filesubmission) から提出 → Defender Cloud の誤検知をプロアクティブに解除
- **施設 IT allowlist**: 施設の MDE / EDR で `wiseman_hub.exe` のハッシュまたはパスを allowlist 登録（事前相談ベース）
- **配布形式**: Mark-of-the-Web 付加を避けるため、インターネット経由ではなく USB 直接配布を優先
- **SmartScreen 警告手順**: 施設 IT 担当が「実行」押下できない端末（Enterprise policy で導線消失）では配布停止、署名購入を検討

MVP 1 施設運用ではこの補強で十分。2 施設目以降はコードサイニング投資が合理的になる閾値として 14D で再評価する。

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

- **14C**: ✅ ショートカット作成スクリプト (`scripts/create_shortcut.ps1`) +
  施設 IT 担当者向け手順書 (`docs/handoff/14c-deploy.md`) 実装済（2026-04-22、PR #82）。
  `README.txt` ドラフトはタスク 11 で作成予定
- **14D**: 本 ADR を Accepted に昇格、コードサイニング要否の運用判断を追記
- **10-2**: Windows 実機ビルド + E2E 検証（本田さん実施）、SmartScreen 挙動記録、
  14C の PS スクリプトの実機動作確認

## 14D Accepted 昇格条件（達成記録）

以下を全て満たした時点で本 ADR を Accepted に昇格する:

1. ✅ **Session 26 達成**: 本田様 Windows 11 実機で `wiseman_hub.exe` (78,570,672 bytes / `d83a3de` HEAD) ビルド + Launcher GUI 起動成功。`uv run pyinstaller wiseman_hub.spec --clean --noconfirm` で Hidden import 警告なしの clean build。
2. ✅ **Session 26 達成（4 ボタン構成に拡張）**: Launcher の **4 ボタン**（PDFマージ処理 / 確認待ちセッション / **事業所フォルダ一括結合** / 設定）が実機で動作。3 ボタン目は ADR-013（PR #126）で追加された新ダイアログ。
3. ✅ **Session 26 記録**: 既存 exe 上書き配布のため hash reputation 既確立、新 exe でも SmartScreen 警告は発生せず。Enterprise 環境（MDE / WDAC）での挙動は本配布先 PC ではポリシー未適用、別 PC での運用展開時に再評価。
4. ✅ **Session 26 判断**: 1 施設運用継続のためコードサイニングは引き続き非導入。運用補強（事前 hash 共有 + USB 直接配布）で当面対応。2 施設目展開時に再評価する閾値を維持。

## 参考

- ADR-002: PyInstaller 選定
- ADR-004: 自動更新機構（GCS manifest ポーリング、Accepted / 未実装）
- ADR-007: USB ドングル認証（認証状態を exe に埋め込まない設計）
- ADR-008: OCR バックエンド（Cloud Run、介護施設 PC からアウトバウンドのみ）
- Issue #59: PyInstaller spec で assets/icon.ico を --icon で埋め込み
