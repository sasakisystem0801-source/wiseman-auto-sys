# 配布用テキスト

## 概要

- **公開 URL**: <https://wiseman-hub-help.web.app>
- **対応デバイス**: PC ブラウザ / スマートフォン / タブレット
- **QR コード**: `/tmp/wiseman-help-qr.png`（印刷物・PDF 貼付用）
- **配信基盤**: Firebase Hosting（Google CDN、HTTPS、グローバル配信）
- **更新方法**: `firebase deploy --only hosting:help`（即時反映、30 秒）

---

## クライアント送付用メッセージ（メール / Slack 用テンプレート）

```
本田様

お世話になっております。
本日のミーティングでご説明する Wiseman PDF ツールの操作マニュアルを
Web ページとしてご用意しましたのでお送りします。

🔗 操作マニュアル
https://wiseman-hub-help.web.app

【特徴】
・PC のブラウザ、スマートフォンどちらからでもご覧いただけます
・サイドバーから機能ごとの操作手順を確認できます
・右上の検索ボックスでマニュアル全体を検索可能です
・困ったときの FAQ・トラブルシューティングも掲載しています

【主な内容】
・5 つの機能の操作手順（業務フロー順）
   ① ex_ ファイル変換 + 振り分け
   ② B: 運動機能向上計画書 自動配置
   ③ C: 経過報告書 自動配置
   ④ 事業所フォルダ一括結合
   ⑤ 設定
・よくある質問（FAQ）
・トラブルシューティング
・用語集

ミーティング中、画面共有で実機を見ながらマニュアルもご参照いただけると
スムーズかと思います。

不明点・改善要望などございましたらお気軽にお知らせください。

よろしくお願いいたします。
```

---

## ミーティング中の使い方（提案）

1. **画面共有で実機 Wiseman PDF ツールを起動**
2. **クライアントのブラウザで `https://wiseman-hub-help.web.app` を開いてもらう**
3. **業務フロー順に各機能を操作 + マニュアル該当ページを並べて参照**

クライアントの手元（スマートフォンや別画面）でマニュアルを見ながら、共有画面で実機操作を見る形が理想。

---

## 今後のアップデート手順

### コンテンツ更新

```bash
# 1. docs/help-site/ 配下の .md ファイルを編集
# 2. ローカルプレビュー（任意）
cd docs/help-site && python3 -m http.server 4567
# → http://localhost:4567/ で確認

# 3. デプロイ
cd /Users/yyyhhh/Projects/wiseman_auto_sys
firebase deploy --only hosting:help --project wiseman-hub-prod
# 30 秒で反映、ブラウザでリロードして確認
```

### スクリーンショット追加（後日 TeamViewer 接続時）

1. 本田様 PC で各機能のスクリーンショット撮影
2. `docs/help-site/assets/` に配置
3. 該当 Markdown に `![説明](../assets/xxx.png)` で挿入
4. デプロイ

### デスクトップアプリからのヘルプリンク追加（次の exe 配布時）

`src/wiseman_hub/ui/launcher.py` または各ダイアログにヘルプボタンを追加して `webbrowser.open("https://wiseman-hub-help.web.app")` を呼ぶ実装。

---

## 運用情報

- **Firebase プロジェクト**: wiseman-hub-prod
- **Hosting site**: wiseman-hub-help
- **コンテンツ場所**: `docs/help-site/` (リポジトリ内)
- **デプロイ設定**: `firebase.json` (target: `help`)
- **無料枠**: 10GB ストレージ / 360MB 日次転送（マニュアル用途なら十分）

---

## 後日対応推奨タスク

| 優先度 | タスク | 補足 |
|---|---|---|
| High | 各機能のスクリーンショット追加 | TeamViewer 接続時に撮影 |
| Med | デスクトップアプリからヘルプリンク追加 | 次の exe 配布時 |
| Med | `.envrc` に `FIREBASE_PROJECT="wiseman-hub-prod"` 追加 | env-isolation ルール準拠 |
| Low | カスタムドメイン化（例: `help.wiseman-hub.example.com`）| 必要時 |
| Low | アクセス解析（Firebase Analytics 等）| 利用状況把握用 |
