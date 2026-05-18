# Issue #275 本田様ヒアリング項目 整理ノート

**作成日**: 2026-05-18 (Session 90)
**目的**: Issue #275 (ChecklistSettingsDialog の GCP 同期ボタン UI シンプル化) の impl-plan 確定に必要な業務ヒアリングを、本田様への質問が最短で完了するよう整理する
**Status**: 本田様ヒアリング待ち (Session 71 で投稿した [impl-plan たたき台](https://github.com/sasakisystem0801-source/wiseman-auto-sys/issues/275#issuecomment-4445806799) の質問項目を本ノートで具体化)

---

## 1. 現状の問題（要約）

- ChecklistSettingsDialog 下部に GCP 同期関連ボタンが 4 + 保存 + キャンセル = **6 個並列**
- 「環境スキャン」「対照表」「担当者」 × 「送信 / 取得 / 同期」の組み合わせで認知負荷が高い
- 担当者側に push ボタンがなく非対称（API `push_report_staff` は実装済、UI ボタン未公開）

## 2. 現状コード起点（実装事実）

`src/wiseman_hub/ui/checklist_settings_dialog.py:153-179`:

| ボタン | テキスト | handler | 内部 API | 認知上の難点 |
|---|---|---|---|---|
| 1 | 環境スキャン → GCP 同期 | `_on_scan_env` | `env_scanner.scan_and_upload` | 「環境」「スキャン」がドメイン用語 |
| 2 | 対照表 → GCP へ送信 | `_on_push_routing` | `mapping_sync.push_routing` | 「対照表」が専門的 |
| 3 | GCP から対照表を取得 | `_on_pull_routing` | `mapping_sync.pull_routing` | 「送信」と並列で誤操作リスク |
| 4 | GCP から担当者を取得 | `_on_pull_staff` | `mapping_sync.pull_report_staff` | 担当者側 push なし（非対称） |
| 5 | 保存 | `_on_save` | TOML 永続化 + sync_timestamp 記録 (PR #243 F4) | OK |
| 6 | キャンセル | `self._top.destroy` | — | OK |

`src/wiseman_hub/cloud/mapping_sync.py`:
- `push_routing` (L101) / `pull_routing` (L133) — 対照表
- `push_report_staff` (L180) / `pull_report_staff` (L223) — 担当者
- **`push_report_staff` 実装済、UI ボタンのみ未公開** → 候補 5 (対称化) は API 追加コストゼロ

## 3. 既存改善候補 5 案（Session 71 評価）

| # | 候補 | 実装コスト | UX 改善度 | 主リスク |
|---|---|---|---|---|
| 1 | 2 動作統合 (取得 1 / 送信 1) | M (dirty flag 拡張) | 高 | 片方だけ送信したい業務動線を潰す |
| 2 | Wizard 化 | H (状態判定 + 動的 UI) | 中 | 過剰実装 |
| 3 | 業務用語への言い換え | S (文字列のみ) | 中-高 | 業務語彙ヒアリング必須 |
| 4 | 送信/取得の上下グループ化 (LabelFrame) | S (Frame ネスト) | 中 | 縦幅増加 |
| 5 | 担当者側 push 追加 (UI のみ) | S (API 既存) | 中 | 既存業務に新動作 |

**組み合わせ A (保守的)**: 3 + 4 + 5 → ボタン 6→7、認知的に 2 グループ整理
**組み合わせ B (アグレッシブ)**: 1 + 3 → ボタン 6→5、大幅シンプル化（"常に同時取得・同時送信で困らない" の確認が前提）

---

## 4. ヒアリング項目（4 領域、優先順）

各質問に **目的 / expected answer template / 改善案との対応** を付け、本田様回答後に即 impl-plan を確定できる状態にする。

### 領域 1: 業務頻度・タイミング（最優先、組み合わせ A/B 選択の根拠）

| Q | 質問 | 目的 | expected answer template |
|---|---|---|---|
| 1-a | 対照表（居宅マッピング）を編集・同期する頻度は？ | 候補 1 (同時取得) 採用可否 | 毎日 / 週次 / 月次 / 事業所増減時のみ |
| 1-b | 担当者マッピングを編集する機会は？ | 同上、特に push 追加優先度 | 担当者異動時のみ / 月次 / 月複数回 |
| 1-c | 「環境スキャン → GCP 同期」を実際にいつ使うか？ | 環境スキャンを残すか・分離するか | 事業所増減時 / トラブル時 / 使ったことない |

**改善案との対応**:
- 「対照表と担当者の編集頻度が大きく違う」 → 候補 1 (2 動作統合) は同期動線潰しになる → A 採用
- 「両方とも月次でセットで触る」 → 候補 1 採用可 → B 採用候補
- 「環境スキャンほぼ使わない」 → ボタンを「詳細設定」サブメニューに退避可

### 領域 2: 操作パターン（候補 1 の採用可否の確定）

| Q | 質問 | 目的 | expected answer template |
|---|---|---|---|
| 2-a | 「対照表 → GCP へ送信」と「GCP から対照表を取得」、片方だけ使うことはあるか？ | 候補 1 の安全性 | 必ずセット (取得 → 編集 → 送信) / 片方だけ使う場面ある |
| 2-b | 担当者マッピングをローカルで編集する機会は？ | 候補 5 (push 追加) の必要性 | ある (push 必要) / 取得して使うだけ (push 不要) |
| 2-c | 「取得 → 編集 → 送信」サイクルで、編集途中で取得し直すことはあるか？ | 候補 1 の上書き確認動線設計 | あり (現状の上書き確認ダイアログ要維持) / なし |

**改善案との対応**:
- 2-a が「必ずセット」 → 候補 1 採用可 (常に取得 → 送信動線)
- 2-a が「片方だけ使う」 → 候補 1 は採用不可、A (グループ化のみ) に確定
- 2-b が「取得して使うだけ」 → 候補 5 は scope 外でも OK
- 2-c が「あり」 → 現状の上書き確認ダイアログ ([`_on_pull_routing`](../../src/wiseman_hub/ui/checklist_settings_dialog.py) L331-345 相当) を維持

### 領域 3: 業務用語（候補 3 の置換語確定）

スクリーンショットを見せながら本田様にとっての自然語を引き出す。

| 現状語 | 候補 | 質問 |
|---|---|---|
| 対照表 | 居宅マッピング / 事業所マッピング / FAX 送付先設定 / 事業所一覧 | 「これを口頭で同僚に説明するときどう呼ぶか？」 |
| 環境スキャン | 設置状況のチェック / 事業所フォルダ一覧の更新 / 配置確認 | 同上 |
| 送信 / 取得 | アップロード/ダウンロード / 保存先に反映/最新を取り込む / クラウドへ反映/クラウドから読み込み | 「どれが直感的？」 |
| GCP / GCS | クラウド / 共有 / サーバー | 「"GCP" は社内で通じる？」 |

**改善案との対応**:
- 置換語は impl-plan の Phase 0 で確定し、ボタンテキスト + ダイアログタイトル + エラーメッセージ全体に反映

### 領域 4: 同期方向の重要度（候補 4 のグルーピング配置確定）

| Q | 質問 | 目的 | expected answer template |
|---|---|---|---|
| 4-a | 「ローカル → GCS (送信)」と「GCS → ローカル (取得)」、どちらが頻度高いか？ | LabelFrame 配置順 | 取得側が多い / 送信側が多い / 同程度 |
| 4-b | 片方のみ重要なら、もう片方は「詳細設定」等に退避してよいか？ | UI 最小化方針 | 退避 OK / 両方常時表示が必要 |
| 4-c | 環境スキャンは「送信/取得」のどちらと同じグループに置きたいか？ それとも独立した方がよいか？ | 候補 4 のグループ設計 | 送信側グループ / 独立 / 別ダイアログ |

**改善案との対応**:
- 4-a の頻度差に応じて上下配置決定（頻度高い側を上）
- 4-b が「退避 OK」 → サブダイアログ化検討（候補 2 簡易版）
- 4-c が「独立」 → 環境スキャンは separator で分ける

---

## 5. ヒアリング当日の進行（推奨）

1. **準備**: 本田様 PC で wiseman-hub を起動 → B/C ダイアログから「設定」を開いた状態のスクリーンショットを撮影 (TeamViewer)
2. **領域 1 (頻度) を先に聞く** → 候補 1 採用可否を早期確定
3. **領域 2 (操作パターン) で候補 1 を再確認** → A / B 確定
4. **領域 3 (業務用語) を画面を見ながら確認** → 置換語確定
5. **領域 4 (同期方向) でグルーピング確認** → 配置確定
6. **その場で impl-plan たたき台を口頭で説明** → 違和感ヒアリング → 最終確定

> 重要: AskUserQuestion 3 択を出さない（[feedback_screen_based_review_no_multichoice.md](../../../.claude/memory/feedback_screen_based_review_no_multichoice.md)）。画面を見ながら本田様の自然な観察を引き出す。

---

## 6. ヒアリング後の意思決定マトリクス

| 領域 1 頻度 | 領域 2 操作 | 推奨組み合わせ | 主要改修 |
|---|---|---|---|
| 対照表/担当者で頻度差大 | 必ずセット | A + 環境スキャン退避 | グループ化 + 用語置換 + 担当者 push 追加 |
| 対照表/担当者で頻度差大 | 片方使う | A | 同上、ただし候補 1 採用なし |
| 月次セット運用 | 必ずセット | B | 取得 1 / 送信 1 に統合、用語置換 |
| 月次セット運用 | 片方使う | A 強化 | グループ化 + ダイアログ分割検討 |

---

## 7. Definition of Done（candidate、impl-plan 段階で確定）

- ChecklistSettingsDialog 下部ボタンが 5 個以下 (cancel/save 含む)（組み合わせ B 採用時）または 7 個以下（組み合わせ A 採用時、対称化により）
- 本田様が「次に何を押せばいいか」を UI 上の表示だけで判断できる
- 既存 pull-save closed-loop verify (F4 dirty flag, PR #243) の挙動を壊さない
- push 後の閉ループ検証 (`push_routing` の verified == routing チェック) を維持
- Launcher GCP 同期サマリー (Phase 2-α) との整合 (sync_timestamp 更新タイミングの一貫性)
- 担当者 push は既存 API (`push_report_staff`) で実装、新規 API 不要
- tk_required テスト追加 + Windows CI で PASS 確認
- 実機 1 業務サイクル完走確認

---

## 8. 影響範囲（impl-plan 段階で確定）

- `src/wiseman_hub/ui/checklist_settings_dialog.py` (UI 改修中心)
- `tests/unit/ui/test_checklist_settings_dialog.py` 等 tk_required テスト追加
- 既存 `mapping_sync.py` API 変更なし (`push_report_staff` 既実装を UI から呼ぶのみ)
- Launcher (`launcher.py`) 連動は `_record_sync_timestamp` 呼出位置のみ調整

## 9. 参考リンク

- 親 Issue: [#238](https://github.com/sasakisystem0801-source/wiseman-auto-sys/issues/238) (CLOSED, 表示シンプル化分の完了済)
- 本 Issue: [#275](https://github.com/sasakisystem0801-source/wiseman-auto-sys/issues/275)
- Session 71 impl-plan たたき台コメント: [#275 issuecomment-4445806799](https://github.com/sasakisystem0801-source/wiseman-auto-sys/issues/275#issuecomment-4445806799)
- 関連 PR (時系列): #184 (PR-β v1) / #239 (Phase 1) / #241 (Phase 2-α) / #243 (Phase 2-β) / #263 / #272
