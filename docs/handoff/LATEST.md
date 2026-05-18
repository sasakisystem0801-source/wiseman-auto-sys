# Session 91 完了 - Wiseman PDF ツール操作マニュアル Web 公開 (Firebase Hosting)

日時: 2026-05-18
HEAD (main): `acde649` (Session 90 完了時点) + 本 PR で更新予定
前セッション archive: [session-90-issue-27-closed.md](./archive/session-90-issue-27-closed.md)

## セッション概要

本日午後のクライアント（本田様）とのオンラインミーティングが「次に Windows 端末に接続可能なタイミング」かつ「失敗が許されない」状況下で発覚。当初目的は「現行デスクトップアプリの操作説明をクライアントに行う」ことだったが、UI/UX 改善は時間的に間に合わない判断。ユーザーから「マニュアルを Web ページ（Firebase Hosting）で作成して操作説明する」方針提示 → AI executor として **残り 4 時間で全工程完遂**。Firebase Hosting に docsify ベースのインタラクティブな操作マニュアルを公開し、バージョン管理機構と実機確認チェックリストまで整備した。

主要成果:

- **マニュアル公開**: <https://wiseman-hub-help.web.app>（HTTPS / Google CDN / モバイル対応 / 全機能網羅）
- **アプリ本体未変更**: TeamViewer 接続なし、本田様 PC への deploy なし → 本日のミーティングで現行アプリを安全に使ってもらえる状態維持
- **バージョン管理機構**: `_meta.json` ベース、全ページ自動フッター表示、changelog.md 履歴管理
- **実機確認チェックリスト**: `docs/help-site/REVIEW.md` で次回 TeamViewer 接続時の検証項目を整理
- **active Issue**: 2 (#6, #275) → **2** (変化なし、本セッションは別軸の成果)

## 本セッション完了内容

### Phase 1: 状況判断と方針確定

`/catchup` 結果 → 「Windows 接続できない期間中の積み残し対応」状態。ユーザーから ADR-016 Phase 7 切替の impl-plan 作成依頼 → 完成 → codex セカンドオピニオン (a) で **Critical 1 件 + Important 5 件** 検出 → 残り作業は TeamViewer + 並行監視 2 週間が必要と判明 → **本日着手は不可能** と確定。

クライアントミーティング想定タイミング判明 → UI/UX 改善は時間切れ → **「マニュアル Web ページ作成」に方針転換**。Firebase Hosting 案 (β: 既存 wiseman-hub-prod に追加) を採用。

### Phase 2: ヘルプサイト構築（残り 4 時間で完遂）

#### Phase 2.1: コンテンツ作成（10 Markdown）

- `README.md` (トップ)、`guide/overview.md` (画面全体)
- 機能 5 ページ: `ex-extractor.md` / `checklist-b.md` / `checklist-c.md` / `facility-merger.md` / `settings.md`
- 困った時 3 ページ: `faq.md` / `troubleshooting.md` / `glossary.md`

ソース: `src/wiseman_hub/ui/launcher.py` + 各 dialog の docstring + `_BTN_*` 定数 + `_STATUS_LABEL` から抽出。

#### Phase 2.2: docsify ベース静的サイト基盤

- `index.html` (docsify CDN 経由、ビルド不要)
- `_coverpage.md` / `_navbar.md` / `_sidebar.md`
- `firebase.json` (rewrites + Cache-Control 設定)
- `.firebaserc` (multi-site target `help` → `wiseman-hub-help`)

#### Phase 2.3: Firebase Hosting セットアップ

- ユーザー認可 (`firebase login` 切替: hy.unimail.11 → sasaki.system0801) 後に進行
- `firebase projects:addfirebase wiseman-hub-prod` → 409 ALREADY_EXISTS (既に登録済) 判明
- `firebase hosting:sites:create wiseman-hub-help` → 新規サイト作成成功
- `firebase target:apply hosting help wiseman-hub-help` → `.firebaserc` 自動更新
- `firebase deploy --only hosting:help` 成功

#### Phase 2.4: ユーザーフィードバック反映 (3 サイクル)

| 指摘 | 対応 |
|---|---|
| 「お粗末な状態」: 読み込み中残置 + ASCII アートのボタン | docsify `alias` で `_sidebar.md` 全パス解決 + HTML/CSS で実機風モックアップ + Mermaid 図 + ステップカード + バッジ |
| 各ボタンクリックで何も起きない | `<div>` → `<a>` リンク化 + hover で 2px 浮き上がり + 右矢印アニメ |
| バージョン表示でユーザビリティ向上 | `_meta.json` 一元管理 + フッター自動表示 + カバーバッジ + changelog.md + REVIEW.md |

### Phase 3: 実機確認準備

ヘルプ内容は実装コードから抽出したが UI 上の細部（C 機能の右クリックメニュー文言、設定ダイアログ項目構成、PlacementConfirmDialog の表示等）は推測含む。`docs/help-site/REVIEW.md` で次回 TeamViewer 接続時のチェック項目を整理 (5 機能 × 各 5〜7 項目 + スクショ取得推奨箇所)。

### Phase 4: クリーンアップとハンドオフ

- ローカルプレビュー (port 4567) 停止
- デバッグ画像 4 枚削除 (overview-after.png / overview-v2.png / ex-extractor.png / footer-check.png)
- `.gitignore` 更新 (`.firebase/` / `.playwright-mcp/` / `/*.png` / `firebase-debug.log`)

## Issue Net 変化

- **Close 数**: 0 件
- **起票数**: 0 件
- **Net**: 0 件

**Net = 0 だが、本セッションは Issue Tracker 外の epic 完遂**（クライアント向けマニュアル Web 公開）。本田様への業務継続性確保が最優先で、Issue Net KPI とは別軸の進捗。triage 基準⑤「ユーザー明示指示」に該当する単発成果のため、Issue 起票せず PR と handoff で記録する判断。

## 検証

### デプロイ動作確認

```bash
curl -sS -o /dev/null -w "%{http_code}\n" https://wiseman-hub-help.web.app/
# → 200
```

| URL | 確認内容 | 結果 |
|---|---|---|
| `/` | カバーページ + バージョンバッジ | ✅ Playwright 確認 |
| `/#/guide/overview` | サイドバー / Mermaid 図 / 5 ボタンモックアップ | ✅ |
| `/#/guide/ex-extractor` | ステップカード / バッジ / シーケンス図 | ✅ |
| `/#/changelog` | バージョン履歴 | ✅ |
| フッター | `マニュアル v1.0.0 · 最終更新 2026-05-18 · 対応アプリ 0.99.0+ · 変更履歴` | ✅ |
| ボタンクリック | 該当機能ページに遷移 | ✅ (ex-extractor で動作確認) |

### CI

- 直前 main (`acde649`) で Windows Integration + UI Tests 両 passing
- 本 PR はドキュメント + 設定ファイルのみ、コード変更なし → CI は test 系のみ check 想定

## 注意事項

### 既知の不確実箇所（REVIEW.md 参照）

ヘルプサイトの一部 UI 文言は実装コードから推測。実機との差分は次回 TeamViewer 接続時に検証 → Patch version (1.0.1) で修正:

- C ダイアログの「xlsx パスを設定」右クリックメニュー実在性と文言
- 設定ダイアログの項目構成（alias 設定 / 担当者マッピング の UI 表現）
- PlacementConfirmDialog の表示文言とキャンセル可否
- facility_merger の A.pdf 必須/オプション判定
- 各ステータスバッジの絵文字使用有無

→ **本日のクライアントミーティングでは、本田様が実機操作中に「マニュアルと実機が違う」と気づく可能性あり**。差分は想定内（業務操作は実機どおりで支障なし）として進行可能。

### Phase 7 切替 impl-plan (作成済、未着手)

ADR-016 Phase 7 切替の impl-plan を本セッション前半で作成 + codex セカンドオピニオン (a) 実施。**Critical 1 件 (`wiseman_launcher.exe --update` 引数必須)** + Important 5 件 (taskbar pin 経路 / multi-instance lock / tag push freeze / seed exe hash 照合 / AC7 observability) 検出済。次セッション以降の着手判断は decision-maker。本 PR には含めず、口頭/メモで継承。

### マニュアル更新運用

```bash
# 1. docs/help-site/*.md を編集
# 2. docs/help-site/_meta.json の manual_version + manual_updated を bump
# 3. docs/help-site/changelog.md に追記
# 4. firebase deploy --only hosting:help --project wiseman-hub-prod
```

## 次セッション最優先

| 優先度 | タスク | 補足 |
|---|---|---|
| **1** | **TeamViewer 接続できた時点で REVIEW.md チェックリスト潰し → スクショ撮影 → docs/help-site/assets/ 配置 → 該当 md 埋め込み → Patch deploy** | マニュアル 1.0.0 → 1.0.1 |
| 2 | **Issue #275 ヒアリング実施** (`docs/specs/issue-275-hearing.md` に整理済) | ミーティング時 or 別途 |
| 3 | Phase 7 切替判断 (impl-plan + codex review 完了済、必須条件 6 件あり) | decision-maker 判断 |
| 4 | Issue #6 PoC E2E (Windows 実機必須、長期) | 着手は decision-maker 判断 |

## 関連リンク

- **公開サイト**: <https://wiseman-hub-help.web.app>
- **配布用テキスト**: [docs/help-site/DISTRIBUTION.md](../help-site/DISTRIBUTION.md)
- **実機確認チェックリスト**: [docs/help-site/REVIEW.md](../help-site/REVIEW.md)
- **変更履歴**: <https://wiseman-hub-help.web.app/#/changelog>
- **Firebase Console**: <https://console.firebase.google.com/project/wiseman-hub-prod/hosting/sites/wiseman-hub-help>

## 残留事項

- ローカルプレビュー (port 4567) は停止確認済
- 本田様 PC へのデプロイは未実施 (アプリ本体は Session 90 完了時点のまま)
- ADR 新規作成は見送り (Hosting + docsify 採用は単発判断、将来必要なら起こす)
