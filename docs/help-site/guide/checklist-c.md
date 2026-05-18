# ③ C: 経過報告書 自動配置

スプレッドシートの担当者情報を元に、経過報告書（C 帳票）の xlsx を PDF 化して事業所フォルダに自動配置します。

## 何のための機能か

<div style="display:flex;gap:0.8em;align-items:center;margin:1em 0;flex-wrap:wrap;">
  <div style="background:#e3f2fd;border:2px solid #1565c0;border-radius:8px;padding:0.8em;text-align:center;flex:1;min-width:120px;">
    <div style="font-size:1.4em;">📊</div>
    <div style="font-size:0.85em;"><strong>スプレッドシート</strong><br>担当者付き利用者</div>
  </div>
  <div style="font-size:1.4em;color:#1565c0;">➜</div>
  <div style="background:#fff3e0;border:2px solid #f57c00;border-radius:8px;padding:0.8em;text-align:center;flex:1;min-width:120px;">
    <div style="font-size:1.4em;">📗</div>
    <div style="font-size:0.85em;"><strong>担当者の xlsx</strong><br>利用者シートを抽出</div>
  </div>
  <div style="font-size:1.4em;color:#f57c00;">➜</div>
  <div style="background:#f3e5f5;border:2px solid #7b1fa2;border-radius:8px;padding:0.8em;text-align:center;flex:1;min-width:120px;">
    <div style="font-size:1.4em;">📄</div>
    <div style="font-size:0.85em;"><strong>Excel PDF 化</strong><br>1 ページ目のみ</div>
  </div>
  <div style="font-size:1.4em;color:#7b1fa2;">➜</div>
  <div style="background:#e8f5e9;border:2px solid #2e7d32;border-radius:8px;padding:0.8em;text-align:center;flex:1;min-width:120px;">
    <div style="font-size:1.4em;">📂</div>
    <div style="font-size:0.85em;"><strong>FAX 事業所</strong><br>配下に配置</div>
  </div>
</div>

- 月ごとの **担当者付き利用者** を Google スプレッドシートで管理
- 担当者ごとに保存されている **経過報告書 xlsx ファイル** から、対象利用者のシートだけを PDF 化
- 生成された PDF を FAX 事業所フォルダ配下に自動配置

---

## 処理フロー

```mermaid
flowchart TD
    Start([開始]) --> Btn["① ボタンをクリック"]
    Btn --> Dlg["② C ダイアログ表示"]
    Dlg --> Sheet["③ シート一覧更新"]
    Sheet --> Month["④ 対象月のシート選択"]
    Month --> Load["⑤ 対象行を読込"]
    Load --> Show["⑥ 担当者付き利用者一覧"]
    Show --> Check{xlsx パス確認}
    Check -->|未設定の担当者| Pick["右クリック<br>→ xlsx パスを設定"]
    Pick --> Same{同名担当者複数?}
    Same -->|Yes| Picker["担当者ピッカー"]
    Same -->|No| Cache[キャッシュに保存]
    Picker --> Cache
    Cache --> Show
    Check -->|全て設定済| Run["⑦ 実行ボタン"]
    Run --> Confirm["⑧ 配置先確認<br>(PlacementConfirmDialog)"]
    Confirm -->|承認| Each[利用者ごとに処理]
    Confirm -->|キャンセル| End([中止])
    Each --> P1[Excel 起動 / xlsx 開く]
    P1 --> P2[利用者シートを 1 ページ PDF 化]
    P2 --> P3[FAX 事業所フォルダに配置]
    P3 --> Done([完了])

    style Start fill:#e3f2fd
    style Done fill:#e8f5e9
    style End fill:#ffcdd2
    style Confirm fill:#fff8e1
    style Run fill:#bbdefb
```

---

## 操作手順

<div class="step-card">
  <span class="step-card-num">1</span><strong>ボタンをクリック</strong><br>
  メイン画面の <strong>「③ C: 経過報告書 自動配置」</strong> ボタンをクリック。
</div>

<div class="step-card">
  <span class="step-card-num">2</span><strong>ダイアログが開く</strong><br>
  「C ダイアログ」が開きます。
</div>

<div class="step-card">
  <span class="step-card-num">3</span><strong>🔄 シート一覧を更新</strong><br>
  上部の <strong>「シート一覧更新」</strong> ボタンをクリック。
</div>

<div class="step-card">
  <span class="step-card-num">4</span><strong>対象月のシートを選択</strong><br>
  ドロップダウンから対象月を選択。
</div>

<div class="step-card">
  <span class="step-card-num">5</span><strong>📥 対象行を読込</strong><br>
  <strong>「対象行を読込」</strong> ボタンをクリック。担当者が記入されている行が抽出されます。
</div>

<div class="step-card">
  <span class="step-card-num">6</span><strong>内容を確認</strong>
</div>

| 表示項目 | 意味 |
|---------|------|
| 利用者名 | 配置対象の利用者 |
| 担当者 | 経過報告書を作成した担当者 |
| xlsx パス | 担当者の経過報告書 xlsx ファイルパス |
| ステータス | 「実行待ち」「成功」等 |

---

## ✨ C 機能特有: xlsx パス設定

初回や担当者交代後、**担当者 → xlsx パス** が未登録の場合があります。  
該当行は <span class="badge badge-warn">⚠ xlsx パス未設定</span> と表示されます。

### xlsx パスの設定方法

<div class="step-card">
  <strong>1.</strong> 該当行を <strong>ダブルクリック</strong> または <strong>右クリック → 「xlsx パスを設定」</strong><br>
  <strong>2.</strong> <strong>xlsx ピッカー</strong> が開くので、担当者の経過報告書 xlsx ファイルを選択<br>
  <strong>3.</strong> 一度設定すれば、次回以降は <strong>キャッシュされて自動利用</strong> されます
</div>

### 同名担当者が複数いる場合

姓だけ一致する別人が複数いる場合、**担当者ピッカー** が開きます。

- 該当する担当者を一覧から選択してください
- 選択結果はキャッシュされ、次回以降は自動選択されます

---

## 実行と配置先確認

<div class="step-card">
  <span class="step-card-num">7</span><strong>▶️ 実行</strong><br>
  <strong>「実行」</strong> ボタンをクリック。
</div>

<div class="step-card">
  <span class="step-card-num">8</span><strong>配置先確認ダイアログ</strong><br>
  実行前に <strong>配置先確認ダイアログ（PlacementConfirmDialog）</strong> が表示されます。
  <ul>
    <li>配置先パス、ファイル名を確認</li>
    <li>問題なければ <strong>「承認」</strong> をクリック</li>
    <li>上書き等の懸念があれば <strong>「キャンセル」</strong></li>
  </ul>
</div>

<div class="step-card">
  <span class="step-card-num">9</span><strong>結果を確認</strong>
</div>

| ステータス | 意味 | 対応 |
|-----------|------|------|
| <span class="badge badge-ok">✓ 成功</span> | 配置完了 | OK |
| <span class="badge badge-warn">⚠ xlsx パス未設定</span> | 担当者の xlsx パスが未登録 | xlsx ピッカーで設定 |
| <span class="badge badge-warn">⚠ 利用者シート不在</span> | xlsx 内に利用者名のシートがない | xlsx 確認 |
| <span class="badge badge-warn">⚠ 事業所フォルダ不在</span> | FAX 事業所フォルダがない | フォルダ作成 |
| <span class="badge badge-error">✗ エラー</span> | システムエラー | 開発担当へ連絡 |

---

## C 機能特有の仕組み

### 🔄 xlsx パスキャッシュ

担当者 → xlsx パスの対応は **ローカルキャッシュ** + **GCS ミラー** で管理されています。

- 一度設定したパスは、ローカルにキャッシュされ高速利用
- GCS にも自動アップロードされるので、別 PC からも参照可能（マルチ端末対応）

### 📊 Excel COM による PDF 化

経過報告書 xlsx は **Microsoft Excel の COM 経由** で 1 シートずつ PDF 化されます。

> **注意**: 実行中は Excel が裏で起動します（自動制御、画面には出ません）。  
> Excel がインストールされていないと動作しません。

---

## よくある質問

> **Q. 担当者の xlsx パスを変更したい**  
> A. 該当行を右クリック → 「xlsx パスを設定」で再選択できます。

> **Q. xlsx ファイルが開かれている時に実行できる？**  
> A. 開かれていると **エラー** になります。実行前に閉じてください。

> **Q. Excel が複数起動して困る**  
> A. ツールが自動起動した Excel は実行完了後に終了します。手動で開いていた Excel には影響しません。

---

## 関連

- スプレッドシート ID、担当者マッピング等は **[⑤ 設定](settings.md)** から変更できます
- Excel が起動しない → [トラブルシューティング](../troubleshooting.md)
- 担当者ピッカーで該当者がいない → [FAQ](../faq.md)
