# ADR-009: UI技術の選定 - Tkinter（stdlib）を採用

## ステータス
**Accepted (2026-04-20)**

## コンテキスト

PDF分割・条件付き再結合機能（ADR-008）の実装において、OCR抽出した利用者名とB/Cファイル名との照合が曖昧（漢字誤記・OCR揺れ）な場合、自動結合せず**人間確認ステップ**を挟む仕様とした（PRD 要件追加、2026-04-20）。

運用例:
- Image 1: 氏名「塩津 美喜子」
- Image 2: 氏名「塩津 美貴子」（誤記の可能性）

→ 自動で同一人物とみなすと誤結合のリスクがある。運用者（介護職員）が「同一人物」「別人」を判断する UI が必要。

### 制約

- **クライアント環境**: 1施設・1 PC の Windows デスクトップアプリ（ADR-002 PyInstaller）
- **開発環境**: macOS（`rpa/` は Windows-only だが、UI は両環境で動作検証できることが望ましい）
- **配布形態**: 単一 exe バイナリ、追加ランタイムインストール不可
- **利用者**: 介護職員。IT 前提知識なし。複雑な操作は避ける
- **頻度**: 月 1 回〜数回、20名/回程度
- **依存追加の抑制**: PyInstaller パッケージサイズと依存ライセンス管理の負担を最小化

## 決定

**Tkinter（Python 標準ライブラリ）を採用する。**

### 実装方針

- エントリ: `src/wiseman_hub/ui/confirm_dialog.py`
- 起動タイミング: Phase A（split→OCR→match）完了後、`needs_confirmation` または `no_match` が 1件以上あるときのみ
- 画面構成: 単一ウィンドウ + Treeview による候補ペア一覧表示
- 操作: 各行に対して「承認 / 却下 / 手動選択 / スキップ」ボタン
- クローズ: 全件解決時 or ユーザーが中断（X ボタン）。中断時は session JSON に `interrupted_*` 状態を記録し次回再開可能（ADR-010）
- テスト: `tkinter.Event` の擬似発火 + `update_idletasks()` で非インタラクティブテスト可能

### 採用理由

| 観点 | Tkinter | 評価 |
|------|---------|------|
| 配布サイズ | Python 標準 → PyInstaller 追加コストほぼゼロ | ✅ 最適 |
| ライセンス | Python License（実質 public domain） | ✅ 配布自由 |
| macOS/Windows 互換性 | 両 OS で標準バンドル | ✅ 開発環境と一致 |
| 依存管理 | `uv sync` で追加依存不要 | ✅ 最小化 |
| 学習コスト | 単純なダイアログ UI には十分 | ✅ 十分 |
| 日本語入力 | IME 連携動作（macOS/Windows 共に実績） | ✅ 問題なし |
| アクセシビリティ | 標準 OS ウィジェット継承 | ✅ 介護現場で支障なし |

## 代替案と却下理由

| 案 | 却下理由 |
|----|---------|
| **PySide6 / PyQt6** | LGPL（PySide6）/ GPL or 商用（PyQt）でライセンス管理に配布時注意が必要。依存サイズが Tkinter 比で 30-50MB 増。今回のダイアログ規模では過剰 |
| **Flet（Flutter on Python）** | 2026-04 時点でまだ beta、PyInstaller 実績が薄い。Flutter ランタイム同梱で配布サイズ増。日本の介護現場 PC の Flutter 描画パフォーマンスに不安 |
| **Electron + Python バックエンド** | Node ランタイム同梱で配布サイズが 100MB+ 増。プロセス間通信の実装負担。ADR-002 PyInstaller 一本化方針と整合しない |
| **Web ローカル（Flask/FastAPI + ブラウザ）** | ブラウザ起動・ポート競合・Firewall 許可の運用負担。介護職員にブラウザ操作を強いる |
| **DearPyGui** | PyInstaller 対応はあるが IME 日本語入力で既知の不具合報告あり（GitHub Issue 多数）。業務で日本語氏名入力必須のため不適 |
| **CLI のみ（UI 無し）** | 候補提示と手動選択が現実的に困難。介護職員にコマンドライン操作を求めるのは非現実的 |

## 影響

- **新規ディレクトリ**: `src/wiseman_hub/ui/` は既にスタブ存在、本 ADR で実装開始
- **PyInstaller spec 更新不要**: Tkinter は stdlib のため hook 追加なし
- **テスト環境**: CI（GitHub Actions Linux）で Tkinter は `Xvfb` 仮想ディスプレイ経由で起動可能（必要時）。当面はテスト側で `TK_SILENCE_DEPRECATION=1` + ヘッドレス検証
- **macOS 開発機での動作確認**: スクリーンショットで UI 仕様書を作成（impl-plan の Definition of Done）

## スコープ外（将来対応）

- 多言語対応（日本語固定）
- テーマカスタマイズ（OS 標準外観継承）
- タブレット/タッチ操作最適化（マウス+キーボード前提）
- 高 DPI 対応（Tkinter 標準の `tk.call('tk', 'scaling', ...)` で必要時対処）

## 関連

- ADR-002: PyInstaller パッケージング（依存最小化方針と整合）
- ADR-008: OCR バックエンド（本 UI が OCR 結果の人間確認を担う）
- ADR-010: 人間確認ステップの状態遷移（本 UI が操作する状態の定義）
