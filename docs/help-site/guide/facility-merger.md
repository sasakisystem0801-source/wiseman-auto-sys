# ④ 事業所フォルダ一括結合

FAX 事業所フォルダ配下の PDF を、事業所ごとに 1 つの PDF に結合します。

## 何のための機能か

<div style="display:flex;gap:1em;align-items:center;margin:1em 0;">
  <div style="background:#fce4ec;border:2px solid #c2185b;border-radius:8px;padding:1em;text-align:center;flex:1;">
    <div style="font-size:1.4em;">📁📄📄📄</div>
    <div style="font-size:0.85em;color:#666;"><strong>事業所フォルダ</strong><br>複数 PDF が散在</div>
  </div>
  <div style="font-size:2em;color:#c2185b;">➜</div>
  <div style="background:#e8f5e9;border:2px solid #2e7d32;border-radius:8px;padding:1em;text-align:center;flex:1;">
    <div style="font-size:1.4em;">📑</div>
    <div style="font-size:0.85em;color:#666;"><strong>事業所別の結合 PDF</strong><br>FAX 送信用 1 ファイル</div>
  </div>
</div>

- ① ex_変換 / ② B 配置 / ③ C 配置 の結果、事業所フォルダには複数の PDF が散らばっています
- FAX 送信時は **事業所ごとに 1 つの PDF にまとめて送る** のが効率的
- このツールで **事業所単位の PDF 結合** を一括実行できます

---

## 処理フロー

```mermaid
flowchart TD
    Start([開始]) --> Btn["① ボタンをクリック"]
    Btn --> Dlg["② ダイアログ表示"]
    Dlg --> A["③ A.pdf カバーシート選択"]
    A --> Src["④ 事業所ルートフォルダ選択"]
    Src --> Dst["⑤ 出力ルートフォルダ選択"]
    Dst --> Run["⑥ 実行ボタン"]
    Run --> Loop[各事業所フォルダを処理]
    Loop --> Walk[サブフォルダ含めて PDF 再帰収集]
    Walk --> Sort[ファイル名順にソート]
    Sort --> Merge[A.pdf + 収集 PDF を結合]
    Merge --> Save["事業所名.pdf として出力"]
    Save --> Next{次の事業所}
    Next -->|あり| Loop
    Next -->|なし| Done([完了 + サマリ表示])

    style Start fill:#e3f2fd
    style Done fill:#e8f5e9
    style Run fill:#bbdefb
    style Merge fill:#f8bbd0
```

---

## 操作手順

<div class="step-card">
  <span class="step-card-num">1</span><strong>ボタンをクリック</strong><br>
  メイン画面の <strong>「④ 事業所フォルダ一括結合」</strong> ボタンをクリック。
</div>

<div class="step-card">
  <span class="step-card-num">2</span><strong>ダイアログが開く</strong><br>
  「事業所フォルダ結合」ダイアログが開きます。
</div>

<div class="step-card">
  <span class="step-card-num">3</span><strong>A.pdf（カバーシート）を選択</strong><br>
  各事業所の結合 PDF の <strong>1 ページ目</strong> に挟む「A.pdf」（送付状やカバーシート）を選択します。<br>
  全事業所で共通のカバーシートを使用します。
</div>

<div class="step-card">
  <span class="step-card-num">4</span><strong>事業所ルートフォルダを選択</strong><br>
  結合対象の事業所フォルダがまとまっている <strong>親フォルダ</strong> を選択します。<br>
  通常は <strong><code>\\Tera-station\share\03.FAX(事業所)</code></strong>。<br>
  このフォルダ直下の各事業所サブフォルダがすべて結合対象になります。
</div>

<div class="step-card">
  <span class="step-card-num">5</span><strong>出力ルートフォルダを選択</strong><br>
  結合後の PDF を出力する <strong>親フォルダ</strong> を選択します。<br>
  各事業所ごとに <code>&lt;事業所名&gt;.pdf</code> が出力されます。
</div>

<div class="step-card">
  <span class="step-card-num">6</span><strong>▶️ 実行</strong><br>
  実行が始まると、進捗が表示されます。
</div>

<div class="step-card">
  <span class="step-card-num">7</span><strong>結果を確認</strong><br>
  実行完了後、サマリが表示されます。
</div>

| 表示 | 意味 |
|------|------|
| <span class="badge badge-ok">成功 N 事業所</span> | 結合完了 |
| <span class="badge badge-error">失敗 N 事業所</span> | 結合できなかった事業所（理由表示あり） |

成功した事業所は、出力フォルダに `<事業所名>.pdf` として配置されます。

---

## 📦 結合される PDF の順序

```mermaid
flowchart LR
    A["📄 A.pdf<br>(カバー)"] --> B["📄 0001_xxx.pdf"]
    B --> C["📄 0002_xxx.pdf"]
    C --> D["📄 ..."]
    D --> Out["📑 事業所A.pdf"]

    style A fill:#fff3e0
    style Out fill:#e8f5e9
```

- **A.pdf が最初**（カバーシート）
- その後 **ファイル名のアルファベット順** で結合
- **サブフォルダ（利用者フォルダ）配下の PDF も再帰的に対象**

---

## よくある質問

> **Q. 事業所フォルダ内に PDF がない場合は？**  
> A. その事業所はスキップされます（エラーにはなりません）。

> **Q. PDF の順序を制御したい**  
> A. ファイル名の冒頭に番号を付けてください（例: `01_xxx.pdf`, `02_yyy.pdf`）。

> **Q. サブフォルダ（利用者フォルダ）内の PDF も対象？**  
> A. **対象です**。事業所フォルダ配下を再帰的に走査します。

> **Q. 既存の `<事業所名>.pdf` がある場合は？**  
> A. <span class="badge badge-warn">上書きされます</span>。実行前にバックアップを推奨します。

---

## 関連

- 結合結果のページ順が想定と違う → [FAQ](../faq.md)
- 一部の事業所だけ失敗する → [トラブルシューティング](../troubleshooting.md)
