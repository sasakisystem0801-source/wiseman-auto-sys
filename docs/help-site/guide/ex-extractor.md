# ① ex_ファイル変換 + 振り分け

Wiseman から出力した `.ex_` ファイルを PDF に変換し、事業所フォルダに自動で振り分けます。

## 何のための機能か

<div style="display:flex;gap:1em;align-items:center;margin:1em 0;">
  <div style="background:#fff3e0;border:2px solid #f57c00;border-radius:8px;padding:1em;text-align:center;flex:1;">
    <div style="font-size:1.5em;">📁 .ex_ ファイル</div>
    <div style="font-size:0.85em;color:#666;">Wiseman 出力<br>そのままでは開けない</div>
  </div>
  <div style="font-size:2em;color:#f57c00;">➜</div>
  <div style="background:#e8f5e9;border:2px solid #2e7d32;border-radius:8px;padding:1em;text-align:center;flex:1;">
    <div style="font-size:1.5em;">📄 PDF + 事業所別振り分け</div>
    <div style="font-size:0.85em;color:#666;">事業所フォルダ配下に配置</div>
  </div>
</div>

- Wiseman の `.ex_` ファイルは **そのままではブラウザや PDF ビューアで開けません**
- このツールで **PDF に変換** + **事業所別のフォルダに振り分け** を一度に行います
- 振り分けが自動でできなかったファイル（事業所判定が曖昧/不明）は、後で **手動振り分けダイアログ** で処理します

---

## 処理フロー

```mermaid
flowchart TD
    Start([開始]) --> Btn["① ボタンをクリック"]
    Btn --> Dlg["② ダイアログが開く"]
    Dlg --> Src["③ 変換元フォルダを選択<br>(.ex_ ファイルがある場所)"]
    Src --> Dst["④ 振り分け先フォルダを選択<br>(\\Tera-station\\share\\03.FAX(事業所))"]
    Dst --> Run["⑤ 「実行」ボタンをクリック"]
    Run --> Judge{事業所判定}
    Judge -->|判定成功| OK["✅ 事業所フォルダに配置"]
    Judge -->|候補複数| AMBI["⚠ AMBIGUOUS<br>手動振り分けへ"]
    Judge -->|該当なし| UNM["❓ UNMATCHED<br>手動振り分けへ"]
    AMBI --> Manual["⑥ 手動振り分けダイアログ"]
    UNM --> Manual
    Manual --> End([完了])
    OK --> End

    style Start fill:#e3f2fd
    style End fill:#e8f5e9
    style OK fill:#c8e6c9
    style AMBI fill:#fff8e1
    style UNM fill:#ffe0b2
    style Manual fill:#f3e5f5
```

---

## 操作手順

<div class="step-card">
  <span class="step-card-num">1</span><strong>ボタンをクリック</strong><br>
  メイン画面の <strong>「① ex_ ファイル変換 + 振り分け」</strong> ボタンをクリックします。
</div>

<div class="step-card">
  <span class="step-card-num">2</span><strong>ダイアログが開く</strong><br>
  「ex_ ファイル変換」ダイアログが開きます。
</div>

<div class="step-card">
  <span class="step-card-num">3</span><strong>変換元フォルダを選択</strong><br>
  <code>.ex_</code> ファイルが入っているフォルダ（通常は Wiseman の出力先フォルダ）を選択します。
</div>

<div class="step-card">
  <span class="step-card-num">4</span><strong>振り分け先フォルダを選択</strong><br>
  PDF 振り分け先のルートフォルダを選択します。<br>
  通常は <strong><code>\\Tera-station\share\03.FAX(事業所)</code></strong> を選びます。
</div>

<div class="step-card">
  <span class="step-card-num">5</span><strong>「実行」ボタンをクリック</strong><br>
  実行が始まると、進捗バーが表示されます。
</div>

<div class="step-card">
  <span class="step-card-num">6</span><strong>結果を確認</strong><br>
  実行が終わると、以下のサマリが表示されます。
</div>

| ステータス | 意味 |
|---|------|
| <span class="badge badge-ok">成功 N 件</span> | 事業所が判定でき、振り分け完了 |
| <span class="badge badge-warn">AMBIGUOUS N 件</span> | 複数の事業所候補があり、判定不能（手動振り分けが必要） |
| <span class="badge badge-error">UNMATCHED N 件</span> | 該当する事業所がなく、振り分け不能（手動振り分けが必要） |

<div class="step-card">
  <span class="step-card-num">7</span><strong>手動振り分け（必要に応じて）</strong><br>
  AMBIGUOUS / UNMATCHED があった場合、<strong>「手動振り分け」ダイアログ</strong> が自動で開きます。<br>
  ファイル名と内容を確認しながら、正しい事業所を選択してください。
</div>

---

## よくある質問

> **Q. `.ex_` ファイルの拡張子は何？**  
> A. Wiseman 独自の拡張子です。中身は PDF データなので、このツールで `.pdf` に変換できます。

> **Q. 同じファイルを 2 回処理してしまったら？**  
> A. 既に振り分け済みのファイルは **重複チェック** で検出され、上書きは抑制されます。

> **Q. 振り分け先フォルダは固定？**  
> A. 振り分け先は実行のたびに選び直せます。ただし通常は **FAX 事業所フォルダ** を使います。

---

## 関連

- 事業所の判定ルール（alias 設定）は **[⑤ 設定](settings.md)** から変更できます
- 振り分け結果が想定と違う → [トラブルシューティング](../troubleshooting.md)
- 手動振り分け中に困った → [FAQ](../faq.md)
