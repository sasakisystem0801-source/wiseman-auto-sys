# ADR-014: .ex_ ファイル PDF 抽出・事業所フォルダ振り分け機能のデスクトップアプリ統合

## ステータス

**Proposed (2026-04-27)** — PR シリーズ進行中（PR1 マージ済 / PR2 進行中 / PR3-5 計画段階）。Windows 実機検証完了後に Accepted 昇格予定。

### 変更履歴

- 2026-04-27: 本 ADR 作成（PR2 で初版を追加）
- 2026-04-27: Evaluator 指摘 HIGH-1/HIGH-2 を反映（alias canonical 実在検証 + 語境界要求の追加）。テストデータを仮名化（PII 保護徹底、AC2-9 PARTIAL → PASS）

## コンテキスト

Wiseman からダウンロードされる帳票は `.ex_` ファイル（WinSFX32 LZH 自己解凍 EXE）形式で、現状は `scripts/process_ex_files.py`（263 行）によりコマンドライン経由で PDF 抽出 + 事業所フォルダ振り分けを実行している。

ADR-013（PR #126）で `pdf_merge.facility_root_dir` 配下の事業所フォルダを一括結合するデスクトップアプリ機能が完成し、本田様の月次運用に投入された。次の業務改善として、**前段の `.ex_` 取込・振り分けもデスクトップアプリにワンボタン化** したいというユーザー要望が発生（2026-04-27）。

### 業務フロー上の位置づけ

```
[Wiseman ダウンロード] → .ex_ 群
       ↓
   ① ex_ → PDF 抽出 + 事業所フォルダ振り分け  ← 本 ADR の対象
       ↓
       事業所フォルダに B/C PDF が揃う
       ↓
   ②a 「事業所フォルダ一括結合」(ADR-013) または ②b 「PDF マージ処理」→「確認待ちセッション」
       ↓
       配布用 PDF 完成
```

### 制約

- **介護現場で誤配布が業務事故**: マッチング誤検知（false positive）は false negative より重大。事業所 A の介護記録が事業所 B に振り分けられると個人情報漏洩 + 業務信頼失墜
- **介護施設職員（IT 非専門）向け**: エラーは平易な日本語、手動振り分けは直感的な UI
- **Windows 専用機能**: pywinauto + subprocess 経由の SFX ダイアログ自動操作。macOS では fake runner で抽出フローのみテスト
- **既存 `scripts/process_ex_files.py` の挙動互換**: 本田様の現行運用を破壊しない
- **既存 ADR-013 / ADR-012 との整合**: facility_root_dir / 事業所フォルダ判定ロジックを共有

## 決定

### PR 分割（5 PR シリーズ）

Codex セカンドオピニオンによる「1 PR で 1,200+ LOC は事故率高い」指摘を受けて、機能を 5 PR に分割:

| # | スコープ | 状態 |
|---|---------|-----|
| PR1 | 設定スキーマ拡張（`ex_source_dir` + `facility_aliases`） | Merged (#130) |
| PR2 | `pdf/facility_resolver` 単体（alias 優先 + 安全マッチング） | 本 PR |
| PR3 | `pdf/ex_extractor` core 移植 + SFX adapter 化 + macOS fake runner + scripts ラッパー | 計画段階 |
| PR4 | UI 統合（dialog + launcher 5 ボタン化 + 手動振り分け UI） | 計画段階 |
| PR5 | Windows 実機検証 + 修正 + settings.py タブ化（独立評価） | 計画段階 |

### マッチング戦略（安全設計）

Codex 指摘「双方向部分一致 + 最長一致は false positive リスク」+ Evaluator 指摘
「短 alias の無境界マッチで誤配布」「alias canonical 不在で存在しないフォルダへの
書き込み」を受けて、以下の優先順序 + 安全制約で評価する:

| 順位 | 判定 | reason | 説明 |
|------|------|-------|------|
| 1 | alias 一致 | `ALIAS_MATCH` | `facility_aliases[canonical]` のいずれかが正規化ファイル名に **語境界付きで** 含まれる。**かつ canonical が facility_names に実在** する場合のみ |
| 2 | 正規化完全一致 | `EXACT_MATCH` | 正規化後のファイル名が事業所名そのものと等しい（レアケース） |
| 3 | 部分一致（一意） | `PARTIAL_UNIQUE` | 事業所名がファイル名に **語境界付き** 部分一致し、候補が 1 つだけ |
| 4 | 部分一致（最長優位） | `PARTIAL_DOMINANT` | 候補複数だが最長候補と次長候補の差が `_PARTIAL_MATCH_DOMINANCE_THRESHOLD = 2` 文字以上 |
| 5 | AMBIGUOUS | `AMBIGUOUS_PARTIAL` | 候補複数で差が閾値未満 → UI で手動選択 |
| 6 | UNMATCHED | `NO_CANDIDATE` | 候補ゼロ → UI でスキップ or 全事業所からのプルダウン選択 |

#### 部分一致の方向性

**事業所名 ⊂ ファイル名 の一方向のみ** を採用。逆方向（ファイル名 ⊂ 事業所名）は通常ファイル名が日付・記号付きで長いため起こらず、許容すると false positive を増やす。

#### 語境界要求（Evaluator HIGH-2 対応）

alias / canonical name のマッチには **「語境界」が必須**:
- 前後の文字が `_ALIAS_BOUNDARY_CHARS = "_-. ()/[]{}\,;:!?#@&%+=*~|<>'\"\`"` に含まれる
- または文字列の開始/終端

これにより以下の誤配布パスを遮断:
- alias `{"サービスA": ["デイ"]}` + ファイル名「夜間デイサービスB_提供.ex_」
  → "デイ" は前後「夜間」「サ」(日本語) で語境界なし → 誤ヒットせず UNMATCHED
- canonical「サービスA」+ ファイル名「夜間サービスA東_提供.ex_」
  → "サービスA" は前後「間」「東」(日本語) で語境界なし → 候補から除外

#### canonical 実在検証（Evaluator HIGH-1 対応）

alias 辞書の canonical が `facility_names` に存在しない場合、当該 alias 候補を skip する:
- 例: alias `{"消えた施設": ["短縮"]}` + facility_names ["訪問BX"]
  → canonical「消えた施設」が facility_names にないので skip
  → 部分一致 step に進み、訪問BX もマッチしないため UNMATCHED

これにより「alias 設定を残したまま実フォルダを削除した」運用ミスで存在しないパスへ
書き込もうとする経路を構造的に排除。

#### 「十分差」閾値（2 文字）の根拠

- 1 文字差: 「本田デイケア」と「本田デイケア東」のような僅差は人為的命名ミスとの区別が困難 → AMBIGUOUS
- 2 文字差以上: 「本田デイケア」と「本田デイケア（メール）」(差 5 文字、半角化後) のような明確な追加修飾は別事業所と判定可能 → CONFIRMED

将来この閾値の調整が必要な場合は、設定ファイル化または ADR 改訂で対応。

### 正規化規則

- NFKC 正規化（半角カナ ⇔ 全角カナ、半角英数 ⇔ 全角英数、（）⇔ () 統一）
- 空白除去（半角・全角・タブ・改行・CR）

### facility_aliases の入力検証（PR1 で実装済）

`config._validate_facility_aliases` で以下を検証し、違反は `ValueError` / `TypeError` で fail-fast:

1. 正式名 key が空文字列でない
2. value が `list` 型である（文字列を直接書くと文字単位分解されるため `TypeError`）
3. value 要素がすべて非空 `str`
4. 同じ list 内で alias 重複なし
5. 異なる事業所間で同じ alias を共有しない（global 一意性）
6. alias が他事業所の正式名と一致しない（alias 一致と完全一致の衝突回避）

これにより `facility_resolver` は valid な alias 辞書を前提にできる契約。

### PII 保護方針

ファイル名・事業所名・別名は介護現場で機密扱いとなる場合があるため:

- `facility_resolver` モジュールは **ログ出力を一切行わない**
- 例外メッセージには「衝突した alias 文字列」のみ含めて運用者の修正を助けるが、正式事業所名・他別名は出さない
- 不正入力（空文字列、空白のみ）は例外を投げず `UNMATCHED` を返す（例外メッセージ経由の PII 漏洩防止）

### Windows 専用機能の検証戦略

`scripts/process_ex_files.py` の SFX ダイアログ自動操作（pywinauto）は Windows 実機でしか動作しない。PR3 で以下の構造に分離:

- `_extract_with_sfx`: SFX 実行 adapter（実装は Windows のみ、macOS では `NotImplementedError`）
- `extract_ex_file(adapter)`: 純粋ロジック（adapter を DI 受け取り、macOS で fake adapter を使ってテスト可能）
- macOS 単体テスト: fake adapter で `.exe コピー → 抽出成功扱い → PDF 検出 → 移動 → cleanup` の挙動を保証
- Windows 実機検証: PR5 で実施、合格基準を ADR / TEST_PLAN に明記

## 結果

### Pros

- **誤配布リスクの構造的低減**: alias 優先 + AMBIGUOUS への手動回避で false positive を最小化
- **テスト容易性**: `facility_resolver` は純粋関数、UI / I/O から独立 → macOS で全網羅テスト可能
- **段階的レビュー可能性**: 5 PR 分割により各 PR のレビュー負荷が分散、設計判断ごとに承認取得
- **既存 ADR-013 と整合**: `facility_root_dir` を共有、事業所フォルダ判定ロジック流用

### Cons

- **PR 数増加**: 5 PR の段階的マージで全機能完成まで時間がかかる
- **手動振り分け UI の運用負荷**: AMBIGUOUS 判定が多いと UI 操作が増える → alias 登録で軽減を期待
- **Windows 実機検証の遅延**: PR3-5 完成まで実機統合動作が確認できない

### 中立

- 既存 `scripts/process_ex_files.py` は PR3 で薄いラッパーに置換し CLI 互換維持

## 関連

- ADR-012: facility_merger 出力仕様（事業所単位 1 ファイル ABCABC 連結）
- ADR-013: 事業所ルートフォルダ管理 + 一括/選択 PDF 結合（デスクトップアプリ統合）
- PR #130: PR1 設定スキーマ拡張（`ex_source_dir` + `facility_aliases`）
- Codex セカンドオピニオン（2026-04-27）: 1 PR 分割推奨 + マッチング戦略の安全設計
- 4 並列レビュー（PR #130, 2026-04-27）: code-reviewer / pr-test-analyzer / comment-analyzer / type-design-analyzer

## 未決事項

- AMBIGUOUS 判定の頻度実測（実機投入後にデータ収集）
- alias 自動学習（手動振り分け結果を alias に昇格する UX）の検討（PR4 で議論）
- `_PARTIAL_MATCH_DOMINANCE_THRESHOLD = 2` の妥当性検証（実例 50+ ファイル投入後）
