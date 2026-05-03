# ADR-015: 担当者 xlsx パス解決の cache + サジェスト + 人間レビュー設計

## Status
Accepted (2026-05-04)

## Context

C 経過報告書自動配置（PR #172 で MVP 実装）の xlsx パス解決は、当初
`ReportStaffEntry.year_subfolder_template` / `file_template` の単純文字列
展開（`{era}`/`{month}`）で行っていた。実機検証で 5 担当者の NAS 上の
命名規則が大きく異なることが判明し、template 展開では吸収できないと結論。

判明した命名カオス（2026-05-04 実機確認）:

| 担当者 | フォルダ命名 | ファイル命名 |
|-------|------------|------------|
| OT 小林 | `経過報告書\R{era}\` | 未確認（PR-α 後の cache populate で確定） |
| PT 宮下 | `リハ経過報告書\令和{era}年\` | `リハ経過報告書（宮下）{month}月{空白N個}.xlsx`（R7=空白1個、R8=空白4個） |
| PT 小島 | `リハ経過報告書(新)\` / `リハ経過報告書(旧)\令和{era}年度\`（新旧 2 系統） | `経過報告書 令和{era}年{month}月(最新).xlsx` 等、同月複数候補 |
| PT 平瀬 | `リハ経過報告書\令和{era}年\` | `新経過報告書 {month}月{空白}.xlsx`（担当者名なし） |
| PT 木塚 | `経過報告書\令和{era}年度 経過報告書\`（年フォルダ内スペース揺れ） | `経過報告書 木塚R{era}.{month}月 .xlsx`（同フォルダに別人「東浦R7.3月」混在） |

ユーザー（業務責任者）から「規則は今後変更しない（収束済）」「現状を吸収できれば
OK（完璧な汎用性は不要）」と明言された。

## Decision

担当者 xlsx パス解決を以下の 3 層構造で再設計する:

1. **xlsx_path_cache（dict[str, str], キー形式 `"{staff}:{year}:{month}"`）**
   ユーザーがレビュー UI で確定した xlsx 絶対パスを永続化する。
   **自動確定（PENDING）の唯一の根拠**。次回以降の cache hit で deterministic
   に解決される（cache stale 時は再 scan）。

2. **suggest_patterns（list[str]）**
   ReportStaffEntry の新フィールド。glob 風パターン（`*` のみ、`{era}`/`{month}`
   埋め込み可）で xlsx 候補を絞り込む。複数候補・候補単独とも自動確定せず、
   常に NEEDS_REVIEW で人間レビューを要求する。
   実装は `Path.glob()` ではなく `Path.iterdir()` + Unicode-aware 正規表現で
   行い、SMB/UNC パス上の NFC/NFD 揺れと `~$*.xlsx` Office 一時ファイルを吸収。

3. **scan_fallback + build_folder_tree（候補ゼロ時）**
   suggest_patterns でヒットしなかった場合、base_dir を浅く walk してフォルダ
   ツリー dict + xlsx 一覧を作り、レビュー UI で直接ファイル選択できる経路を
   提供する。

これに加えて業務安全性層として:

4. **配置前確認ダイアログ**: PENDING 件数 + 対象 xlsx + 出力 path をユーザー
   目視確認させる。
5. **監査ログ JSON Lines**: 配置成功/失敗を `<log_dir>/audit/c_placement_<date>.jsonl`
   に append-only で記録、誤配置発生時の遡行可能性を確保。

## Consequences

### Positive

- **5 担当者の命名カオスを設定変更で吸収可能**（コード変更不要）
- **介護記録誤配置リスクを構造的に低減**: 自動確定するのは cache hit のみ。
  cache は人間が UI で「記憶する」を選んだもののみ蓄積される
- **規則変更時の運用は cache クリア + 再選択で済む**（少コスト）
- **PR #172 互換**: 旧 `*_template` フィールド残置 + `suggest_patterns` 空時に
  fallback で動作するため、既存設定はそのまま機能する
- **ismap GCP 内完結方針との整合性**: cache は ChecklistConfig.xlsx_path_cache
  として TOML 内に保存、PR-β（別スコープ）で GCS 同期予定

### Negative

- **同月複数候補時に人間判断が常に必要**（自動化されない）
  → ただし「規則固定」の前提なら初回 cache populate 後は cache hit が支配的
- **glob パターン誤記による誤マッチリスク**
  → 配置前確認ダイアログで人間目視 + 監査ログで遡行可能、Tera-station NAS の
    trashbox 経路で復旧可能（CLAUDE.md 既記載）
- **担当者追加時は TOML 直接編集が必要**（UI なし、Phase 2 で検討）

## Alternatives Considered

### A. 担当者別 deterministic resolver（Codex 推奨案）

`MiyashitaResolver` / `KizukaResolver` 等を担当者数ぶん独立実装する案。
hard match のみを許可し、複数候補時は強制 NEEDS_REVIEW にする。

**不採用理由**: 「規則固定」の前提では cache hit が同等の deterministic 性を
提供する。重複コード 5 個を維持するコストに見合う追加安全性が得られない。

### B. Vertex AI / LLM による自動マッチング

候補絞り込みに LLM judgment を使う案（P2）。

**不採用理由**: YAGNI。「規則固定」「現状吸収できれば OK」というユーザー指示と
整合しない。LLM の優位性（命名規則変更追従）が前提条件で消失する。
ismap GCP 内完結方針には適合（Vertex AI は asia-northeast1 で利用可）するが、
非決定性によるデバッグ困難 + 業務影響リスクが現状の cache + 人間補完で
構造的に低減できることに比べて ROI が低い。

将来「規則変更が頻発」「担当者数大幅増加」が起きた場合に再検討する。

### C. Strategy パターン + Resolver Protocol（YAGNI 違反として削除）

抽象 `Resolver` Protocol を定義し、`GlobResolver` / `LLMResolver` 差し替え可能
にする案。impl-plan v2 で計画したが evaluator 評価で「拡張余地の明記自体が
YAGNI 違反」と指摘され、本 ADR では Protocol 抽象化を不採用とした。

将来 LLMResolver 等を導入する時点で必要に応じて抽象化すれば十分。

## Related

- ADR-007（USB dongle 認証）: 影響なし
- ADR-014（ex_extractor 統合）: 影響なし
- PR #172（C MVP）: 本 ADR は PR #172 の MVP 上に積み増す形
- `mapping_sync.py`（PR #172 facility_routing GCS 同期）: PR-β で
  `xlsx_path_cache` / `report_staff` の GCS 同期を追加予定（同パターン流用）
- グローバル memory:
  - `feedback_destructive_command_safety.md`（誤削除安全性）
  - `feedback_nas_trashbox_recovery.md`（NAS 復旧経路）
  - `feedback_ismap_gcp_only.md`（GCP 内完結方針）
