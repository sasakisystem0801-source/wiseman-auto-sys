# 画面全体の説明

## メイン画面の構成

アプリを起動すると、業務フロー順に **5 つのボタン** が並んだメイン画面が表示されます。

<div class="app-mockup">
  <div class="app-mockup-title">Wiseman PDF ツール</div>
  <div class="app-mockup-body">
    <a class="app-btn" href="#/guide/ex-extractor"><span class="app-btn-num">1</span>ex_ ファイル変換 + 振り分け</a>
    <a class="app-btn" href="#/guide/checklist-b"><span class="app-btn-num">2</span>B: 運動機能向上計画書 自動配置</a>
    <a class="app-btn" href="#/guide/checklist-c"><span class="app-btn-num">3</span>C: 経過報告書 自動配置</a>
    <a class="app-btn" href="#/guide/facility-merger"><span class="app-btn-num">4</span>事業所フォルダ一括結合</a>
    <a class="app-btn app-btn-settings" href="#/guide/settings"><span class="app-btn-num">5</span>設定</a>
  </div>
</div>

> 💡 **このマニュアル上では**、上記の各ボタンをクリックすると **対応する機能の説明ページに飛びます**（マウスを乗せるとボタンが浮き上がります）。  
> **実機アプリでは**、ボタンをクリックすると専用のダイアログ（小さな別ウィンドウ）が開いて、その機能の操作画面が表示されます。

---

## 業務フロー全体像

毎月の業務は、おおよそ次の流れで実施します。各ボタンはこのフローに沿って並んでいます。

```mermaid
flowchart LR
    Start([🗓️ 月初業務開始]) --> B1["① ex_ファイル変換<br>+ 振り分け"]
    B1 --> B2["② B: 運動機能向上計画書<br>自動配置"]
    B2 --> B3["③ C: 経過報告書<br>自動配置"]
    B3 --> B4["④ 事業所フォルダ<br>一括結合"]
    B4 --> End([📠 FAX 送信])

    style Start fill:#e3f2fd,stroke:#1565c0,stroke-width:2px
    style End fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px
    style B1 fill:#fff3e0,stroke:#f57c00
    style B2 fill:#f3e5f5,stroke:#7b1fa2
    style B3 fill:#e1f5fe,stroke:#0277bd
    style B4 fill:#fce4ec,stroke:#c2185b
```

| 順序 | ボタン | やること |
|:---:|:------|:--------|
| 1 | **① ex_ファイル変換 + 振り分け** | Wiseman から出力したファイルを PDF にし、事業所別に振り分ける |
| 2 | **② B: 運動機能向上計画書 自動配置** | 該当月のモニタリング対象利用者の計画書を配置 |
| 3 | **③ C: 経過報告書 自動配置** | 該当月の担当者ごとの経過報告書を配置 |
| 4 | **④ 事業所フォルダ一括結合** | 事業所ごとに PDF を 1 つに結合（FAX 送信用） |

**⑤ 設定** は事前準備や設定変更時のみ使用します（普段は触りません）。

---

## ダイアログの共通レイアウト

B と C のダイアログは共通の操作パターンです。

<div class="dialog-mockup">
  <div class="dialog-mockup-title">B / C ダイアログ（例）</div>
  <div class="dialog-mockup-body">
    <div class="dialog-toolbar">
      <div class="dialog-toolbar-btn">🔄 シート一覧更新</div>
      <div class="dialog-toolbar-btn">📥 対象行を読込</div>
      <div class="dialog-toolbar-btn">⚙️ 設定...</div>
    </div>
    <div class="dialog-table">📊 対象行の一覧表示エリア（利用者名 / ステータス 等）</div>
    <div class="dialog-footer">
      <div class="dialog-toolbar-btn" style="background:#2c8cf0;color:white;border-color:#1976d2;">▶️ 実行</div>
      <div class="dialog-toolbar-btn">閉じる</div>
    </div>
  </div>
</div>

| 操作ボタン | 役割 |
|-----------|------|
| **🔄 シート一覧更新** | スプレッドシートから最新のシート一覧（=月別タブ）を取得 |
| **📥 対象行を読込** | 選択中のシートから対象となる行を抽出して表示 |
| **⚙️ 設定...** | スプレッドシート ID 等の設定変更 |
| **▶️ 実行** | 抽出された全行に対して PDF 配置を実行 |
| **閉じる** | ダイアログを閉じてメイン画面に戻る |

---

## 操作の基本パターン

各機能は次の 3 ステップで完結します。

```mermaid
sequenceDiagram
    actor U as ユーザー
    participant M as メイン画面
    participant D as ダイアログ
    participant S as スプレッドシート / フォルダ

    U->>M: 機能ボタンをクリック
    M->>D: ダイアログ表示
    U->>D: 対象月を選択
    D->>S: シート一覧 / 対象行を取得
    S-->>D: データ返却
    D-->>U: 一覧表示
    U->>D: ▶️ 実行ボタンをクリック
    D->>S: PDF 配置 / 結合 を実行
    S-->>D: 結果返却
    D-->>U: 結果サマリ表示
    U->>D: 閉じる
```

---

## 次のステップ

最初は **[① ex_ファイル変換 + 振り分け](ex-extractor.md)** から始めるのがおすすめです。

サイドバーから各機能のページに移動できます。

<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1em; margin: 1.5em 0;">
  <a href="#/guide/ex-extractor" style="text-decoration:none;">
    <div style="border:2px solid #f57c00;border-radius:8px;padding:1em;background:#fff3e0;text-align:center;">
      <div style="font-size:2em;">📄</div>
      <div><strong>① ex_ファイル変換</strong></div>
    </div>
  </a>
  <a href="#/guide/checklist-b" style="text-decoration:none;">
    <div style="border:2px solid #7b1fa2;border-radius:8px;padding:1em;background:#f3e5f5;text-align:center;">
      <div style="font-size:2em;">🏃</div>
      <div><strong>② B 自動配置</strong></div>
    </div>
  </a>
  <a href="#/guide/checklist-c" style="text-decoration:none;">
    <div style="border:2px solid #0277bd;border-radius:8px;padding:1em;background:#e1f5fe;text-align:center;">
      <div style="font-size:2em;">📋</div>
      <div><strong>③ C 自動配置</strong></div>
    </div>
  </a>
  <a href="#/guide/facility-merger" style="text-decoration:none;">
    <div style="border:2px solid #c2185b;border-radius:8px;padding:1em;background:#fce4ec;text-align:center;">
      <div style="font-size:2em;">📚</div>
      <div><strong>④ 事業所フォルダ結合</strong></div>
    </div>
  </a>
  <a href="#/guide/settings" style="text-decoration:none;">
    <div style="border:2px solid #757575;border-radius:8px;padding:1em;background:#f5f5f5;text-align:center;">
      <div style="font-size:2em;">⚙️</div>
      <div><strong>⑤ 設定</strong></div>
    </div>
  </a>
</div>
