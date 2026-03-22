# Wiseman Auto System

介護ソフト「ワイズマンシステムSP」のデータを自動抽出し、GCPクラウドに連携するシステム。

## 概要

ワイズマンシステムSPはASP型の介護業務ソフトですが、クライアントは **.NETネイティブWindowsアプリ**（.NET Framework 3.5 / WinForms / MDI構成）です。USBキーまたはライセンスID認証が必要で、各PCにインストールして使用します。

本システムは **Python RPA（pywinauto）** でワイズマンのGUIを自動操作し、介護データをGCPクラウドに転送します。

## システム構成

```
┌────────────────────────────────────┐
│  ワイズマンASPサーバー              │
│  (*.wiseman.ne.jp)                 │
└──────────▲─────────────────────────┘
           │ インターネット
┌──────────┴─────────────────────────┐
│  Client PC (Windows 11)            │
│                                    │
│  Wiseman Hub (Python)              │
│   ├─ RPA Engine (pywinauto)        │
│   │   └─ ワイズマン .NETアプリを    │
│   │      GUI自動操作               │
│   ├─ Cloud Client (GCP SDK)        │
│   ├─ Scheduler (APScheduler)       │
│   └─ Auto Updater                  │
│                                    │
│  USB Key / License ID              │
└──────────┼─────────────────────────┘
           │ HTTPS
┌──────────▼─────────────────────────┐
│  GCP (asia-northeast1 / 東京)      │
│  Cloud Storage / BigQuery / Pub/Sub│
└────────────────────────────────────┘
```

## フェーズ計画

| Phase | 期間 | ゴール |
|-------|------|--------|
| **PoC** | 24時間（実働） | ログイン→CSV抽出→GCS転送の1本パイプライン |
| **MVP** | 2-4週間 | exe化、スケジューラ、BigQuery連携 |
| **Production** | 1-2ヶ月 | 自動更新、データ入力、Pub/Sub |
| **Scale** | 3-6ヶ月 | Webダッシュボード、複数クライアント |

## 技術スタック

| レイヤー | 技術 |
|---------|------|
| RPA（主） | pywinauto (UIA backend) |
| RPA（副） | PyAutoGUI（フォールバック） |
| クラウド | GCP (Cloud Storage, BigQuery, Pub/Sub, Cloud Functions) |
| パッケージング | PyInstaller |
| 設定 | TOML |
| 認証情報 | keyring (Windows DPAPI) |

## ディレクトリ構成

```
wiseman_auto_sys/
├── docs/
│   ├── prd.md                  # Product Requirements Document
│   ├── wiseman-system-spec.md  # ワイズマン技術仕様書
│   └── adr/                    # Architecture Decision Records (001-006)
├── src/wiseman_hub/
│   ├── app.py                  # オーケストレータ
│   ├── config.py               # TOML設定ローダー
│   ├── rpa/                    # pywinauto RPA操作
│   ├── cloud/                  # GCP連携
│   ├── updater/                # 自動更新
│   ├── scheduler/              # 定期実行
│   └── ui/                     # システムトレイ
├── config/default.toml         # デフォルト設定
├── tests/                      # テスト
└── pyproject.toml
```

## ドキュメント

- **[PRD](docs/prd.md)** — 製品要件定義（フェーズ計画、成功基準、リスク）
- **[ワイズマン技術仕様書](docs/wiseman-system-spec.md)** — ワイズマンのUI構造、インストール仕様、コントロール一覧
- **ADR（設計判断記録）**
  - [001: RPAライブラリ選定](docs/adr/001-rpa-library-selection.md) — pywinauto採用の理由
  - [002: パッケージングツール](docs/adr/002-packaging-tool.md) — PyInstaller→Nuitka段階移行
  - [003: GCPサービス選定](docs/adr/003-gcp-service-selection.md) — 月額$0-2のFree Tier活用
  - [004: 自動更新メカニズム](docs/adr/004-auto-update-mechanism.md) — GCSマニフェストポーリング
  - [005: 設定形式](docs/adr/005-config-format.md) — TOML + keyring暗号化
  - [006: ASP型自動化戦略](docs/adr/006-asp-automation-strategy.md) — Superseded（参考記録）

## 開発環境

- **開発**: macOS + Claude Code
- **実機テスト**: TeamViewer → Windows 11 クライアントPC
- **デプロイ**: GitHub Actions → PyInstaller exe → GCS → クライアントPC自動更新

## セットアップ

```bash
# 依存関係インストール
uv sync

# テスト実行
uv run pytest

# lint
uv run ruff check src/
```
