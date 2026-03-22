# Wiseman Auto System

## プロジェクト概要
介護ソフト「ワイズマンシステムSP」（オンプレミス版/ネイティブWindowsアプリ）のデータをPython RPA（pywinauto）でGCPクラウドに連携するシステム。

## アーキテクチャ
- **ワイズマン**: ASP型サービス（サーバーはワイズマン社がクラウドホスティング）だが、**クライアントは.NETネイティブWindowsアプリ**（MDI構成、.NET Framework 3.5）。USBキーまたはライセンスID認証が必要
- **RPA**: pywinauto (UIA backend) がワイズマンのGUIを自動操作。PyAutoGUIはフォールバック
- **Hub**: Pythonデスクトップアプリ（RPA操作・クラウド同期・スケジューリング統括）
- **クラウド**: GCP (Cloud Storage, BigQuery, Pub/Sub, Cloud Functions)

## ワイズマンUI特性（実環境スクリーンショットより確認済み）
- MDI親ウィンドウ内に子ウィンドウが開く
- タイトルバー: `通所・訪問リハビリ管理システム SP(ケア記録) [施設名]`
- 標準WinForms系コントロール: ボタン、コンボボックス、チェックボックス、ラジオボタン、データグリッド
- データグリッドに色付きセル（赤=異常値ハイライト）

## 開発環境
- **開発**: macOS + Claude Code（RPAコードはWindows専用、macOSではモック）
- **実機テスト**: TeamViewer経由でWindows 11クライアントPC（USBドングル必要）
- **セレクタ調査**: Windows上でInspect.exe / Spy++ を使用してコントロール構造を確認
- **デプロイ**: GitHub Actions → PyInstaller exe → GCS → クライアントPC自動更新

## 技術スタック
- Python 3.11+, uv (パッケージ管理)
- pywinauto (RPA主), PyAutoGUI (RPA副)
- google-cloud-storage, google-cloud-pubsub
- APScheduler, pystray, keyring
- PyInstaller (exe化), Terraform (インフラ)

## コーディング規約
- ruff (lint), mypy (型チェック)
- line-length: 120
- テストは `tests/` 配下に unit/integration/e2e で分類
- RPA操作は `src/wiseman_hub/rpa/base.py` の抽象インターフェースを実装

## 重要な設計判断
- ADRは `docs/adr/` に格納（001-006。006はSuperseded）
- 設定はTOML形式 (`config/default.toml`)
- 機密情報はkeyring (Windows DPAPI) で管理、設定ファイルに含めない
- CSV文字エンコーディング: Shift-JIS想定、設定で変更可能
- GCPリージョン: asia-northeast1 (東京) - データレジデンシー要件

## クロスプラットフォーム注意
- `rpa/` モジュールはWindows専用。macOSではモック実装でテスト
- `cloud/`, `config.py`, `updater/` はクロスプラットフォーム
- パス区切りは `pathlib.Path` を使用（`\\` ハードコード禁止）
- `sys.platform == "win32"` でプラットフォーム分岐

## 経緯メモ
- ワイズマン「ASP」は「サーバーのホスティング形態」であり、クライアントがブラウザベースという意味ではない
- クライアントは.NETネイティブアプリ（`C:\Users\{User}\AppData\Local\Programs\WISEMAN\WISEMANVSYSTEM\`にインストール）
- Web調査で「ASP=ブラウザ」と誤認→Playwright前提で設計→実環境スクリーンショット+公式インストール手順書で.NETネイティブアプリと確定→pywinautoに回帰
