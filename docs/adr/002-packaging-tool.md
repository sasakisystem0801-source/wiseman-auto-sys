# ADR-002: パッケージングツールの選定

## ステータス
Accepted (2026-03-22)

## コンテキスト
クライアントPCにPythonがインストールされているか不明。Pythonランタイムを同梱した単体実行可能ファイル（exe）としてデスクトップアプリを配布する必要がある。

要件:
- Windows 11向けの単体exe生成
- pywinauto, google-cloud-storage等の依存ライブラリを同梱
- GitHub Actions (windows-latest) でのCI/CDビルド
- 起動速度は許容範囲内（10秒以内）

## 検討した選択肢

### A. PyInstaller（採用 - MVP）
- 最も広く使われるPython exe化ツール（月4.7Mダウンロード）
- `--onefile`で単体exe、`--onedir`でフォルダ配布
- ビルド速度: 高速

### B. Nuitka（検討 - Production）
- PythonコードをC言語にコンパイル
- 実行速度向上、リバースエンジニアリング耐性
- ビルド時間: 長い（C compiler必要）

### C. cx_Freeze
- PyInstallerと類似だがコミュニティ規模が小さい → **不採用**

## 決定
**MVP段階ではPyInstallerを採用。Production段階でNuitkaへの移行を検討する。**

## 理由
1. **開発速度**: PyInstallerはビルドが速く、PoC/MVPの高速イテレーションに適合
2. **実績**: pywinauto + PyInstaller の組み合わせは広く使われ、既知の問題と回避策が豊富
3. **CI/CD**: GitHub Actions windows-latestでのPyInstallerビルドは安定した実績がある
4. **段階移行**: NuitkaはIP保護が必要になるProduction段階で移行。ビルドスクリプトの変更のみで移行可能

## 結果
- `scripts/build_exe.py` にPyInstallerビルド設定を定義
- GitHub Actionsでタグpush時に自動ビルド
- exe署名（コード署名証明書）はMVP段階で導入し、Defender誤検知を防止
- Nuitka移行はADRを別途作成して判断
