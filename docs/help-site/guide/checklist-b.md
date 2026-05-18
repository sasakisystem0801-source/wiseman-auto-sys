# ② B: 運動機能向上計画書 自動配置

スプレッドシートの月別データを元に、運動機能向上計画書（B 帳票）の PDF を利用者フォルダに自動配置します。

## 何のための機能か

<div style="display:flex;gap:0.8em;align-items:center;margin:1em 0;flex-wrap:wrap;">
  <div style="background:#e3f2fd;border:2px solid #1565c0;border-radius:8px;padding:0.8em;text-align:center;flex:1;min-width:140px;">
    <div style="font-size:1.4em;">📊</div>
    <div style="font-size:0.85em;"><strong>スプレッドシート</strong><br>月別モニタリング対象</div>
  </div>
  <div style="font-size:1.6em;color:#1565c0;">➜</div>
  <div style="background:#fff3e0;border:2px solid #f57c00;border-radius:8px;padding:0.8em;text-align:center;flex:1;min-width:140px;">
    <div style="font-size:1.4em;">📁</div>
    <div style="font-size:0.85em;"><strong>カルテ</strong><br>月別 PDF を取得</div>
  </div>
  <div style="font-size:1.6em;color:#f57c00;">➜</div>
  <div style="background:#e8f5e9;border:2px solid #2e7d32;border-radius:8px;padding:0.8em;text-align:center;flex:1;min-width:140px;">
    <div style="font-size:1.4em;">📂</div>
    <div style="font-size:0.85em;"><strong>FAX 事業所</strong><br>利用者フォルダに配置</div>
  </div>
</div>

- 月ごとの **モニタリング対象利用者** を Google スプレッドシートで管理
- 対象利用者ごとに、**カルテから月別 PDF をコピー** し、FAX 事業所フォルダ内の利用者フォルダに配置
- 手作業だと「該当月の対象者を探す → カルテで該当 PDF を探す → 利用者フォルダにコピー」を利用者数だけ繰り返す必要がある作業を自動化

---

## 処理フロー

```mermaid
flowchart TD
    Start([開始]) --> Btn["① ボタンをクリック"]
    Btn --> Dlg["② B ダイアログ表示"]
    Dlg --> Sheet["③ シート一覧更新"]
    Sheet --> Month["④ 対象月のシート選択"]
    Month --> Load["⑤ 対象行を読込"]
    Load --> Show["⑥ 対象利用者一覧を表示"]
    Show --> Check{ステータス確認}
    Check -->|⚠ 警告あり| Fix["スプレッドシート修正<br>または設定確認"]
    Check -->|問題なし| Run["⑦ 実行ボタン"]
    Fix --> Sheet
    Run --> Each[利用者ごとに処理]
    Each --> P1[カルテで月別 PDF を検索]
    P1 --> P2[FAX 事業所フォルダ確認]
    P2 --> P3[利用者フォルダにコピー]
    P3 --> Done([完了])

    style Start fill:#e3f2fd
    style Done fill:#e8f5e9
    style Fix fill:#fff8e1
    style Run fill:#bbdefb
```

---

## 操作手順

<div class="step-card">
  <span class="step-card-num">1</span><strong>ボタンをクリック</strong><br>
  メイン画面の <strong>「② B: 運動機能向上計画書 自動配置」</strong> ボタンをクリック。
</div>

<div class="step-card">
  <span class="step-card-num">2</span><strong>ダイアログが開く</strong><br>
  「B ダイアログ」が開きます。
</div>

<div class="step-card">
  <span class="step-card-num">3</span><strong>🔄 シート一覧を更新</strong>（初回または最新化したい時）<br>
  ダイアログ上部の <strong>「シート一覧更新」</strong> ボタンをクリック。スプレッドシートから最新の月別タブ一覧が取得されます。
</div>

<div class="step-card">
  <span class="step-card-num">4</span><strong>対象月のシートを選択</strong><br>
  ドロップダウンから対象月（例: <code>2026-05</code>）を選びます。
</div>

<div class="step-card">
  <span class="step-card-num">5</span><strong>📥 対象行を読込</strong><br>
  <strong>「対象行を読込」</strong> ボタンをクリック。<br>
  選択した月のシートから、<strong>モニタリング日付がある行</strong>（=配置対象の利用者）が抽出されます。
</div>

<div class="step-card">
  <span class="step-card-num">6</span><strong>内容を確認</strong><br>
  一覧テーブルで対象利用者と状態を確認します。
</div>

| 表示項目 | 意味 |
|---------|------|
| 利用者名 | 配置対象の利用者 |
| 居宅 | 紐付け先の居宅介護支援事業所 |
| 月別 PDF | カルテから探し出した該当月の PDF |
| ステータス | 「実行待ち」「成功」「⚠ ○○未登録」等 |

特に「⚠」マーク付きの行は **配置不能** または **要注意** の状態です。

<div class="step-card">
  <span class="step-card-num">7</span><strong>▶️ 実行</strong><br>
  問題なければ、右下の <strong>「実行」</strong> ボタンをクリック。<br>
  ステータスが「実行待ち」→「成功」に更新されていきます。
</div>

<div class="step-card">
  <span class="step-card-num">8</span><strong>結果を確認</strong>
</div>

| ステータス | 意味 | 対応 |
|-----------|------|------|
| <span class="badge badge-ok">✓ 成功</span> | 配置完了 | OK |
| <span class="badge badge-warn">⚠ 居宅マッピング未登録</span> | 利用者の居宅が判定できない | スプレッドシートに居宅を追記 |
| <span class="badge badge-warn">⚠ 利用者フォルダ未発見</span> | FAX 事業所フォルダ内に利用者フォルダがない | フォルダ作成 |
| <span class="badge badge-warn">⚠ 月別 PDF 不在</span> | カルテに該当月の PDF がない | カルテ側で出力確認 |
| <span class="badge badge-warn">⚠ 候補複数</span> | 同名の月別 PDF が複数あり判定不能 | カルテ整理 |
| <span class="badge badge-error">✗ エラー</span> | システムエラー | 開発担当へ連絡 |

<div class="step-card">
  <span class="step-card-num">9</span><strong>閉じる</strong><br>
  完了したら <strong>「閉じる」</strong> ボタンでダイアログを閉じます。
</div>

---

## 共通の操作ボタン

| ボタン | 役割 |
|--------|------|
| 🔄 シート一覧更新 | スプレッドシートから最新のシート一覧を再取得 |
| 📥 対象行を読込 | 選択中のシートから対象行を抽出 |
| ⚙️ 設定... | スプレッドシート ID 等の設定変更 |
| ▶️ 実行 | 表示中の全対象行に対して配置を実行 |
| 閉じる | ダイアログを閉じる |

---

## よくある質問

> **Q. 「シート一覧更新」と「対象行を読込」の違いは？**  
> A. 前者は **月のタブ一覧** を取りに行く（数か月に 1 度）。後者は **その月のシート内の利用者行** を取りに行く（実行ごと）。

> **Q. ⚠ マークの行を無視して実行できる？**  
> A. ⚠ の行は実行時に **自動的にスキップ** されます。エラーにはなりません。

> **Q. 設定変更後の挙動は？**  
> A. 「設定...」でスプレッドシート ID を変更した場合、自動的にシート一覧と対象行がクリアされます。「シート一覧更新」からやり直してください。

---

## 関連

- スプレッドシート ID、月別 PDF の取得元パス等は **[⑤ 設定](settings.md)** から変更できます
- ⚠ マークが大量に出る → [トラブルシューティング](../troubleshooting.md)
- スプレッドシートが見つからない → [FAQ](../faq.md)
