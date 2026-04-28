# ex_extractor 検証用 fixture ガイド

PR5 ex_extractor Windows 実機検証 (AC-2〜AC-14) で使う `.ex_` ファイル fixture の要件・調達・配置・クリーンアップ手順。

> 📌 **PII 注意**: 本ドキュメントの事業所名・利用者氏名は ADR-014 §PII 保護方針に従い仮名（`サービスA` / `サービスB` 等）で記述する。実環境では実在の事業所名 / 利用者氏名に置換するが、それらをコミット対象ファイルに書き戻してはならない。

## 目的

`ex_extractor` の振り分けロジック（`facility_resolver.py`）は CONFIRMED / AMBIGUOUS / UNMATCHED の 3 状態を返す。実機検証では **3 状態すべての発火を確認** する必要があり、それぞれに合った fixture が必要となる。実環境には実データがあるが PII を含むため、検証用にはローカルでの再現または墨塗り済データを使う。

## `.ex_` ファイルとは

ワイズマンシステム SP がエクスポートする SFX (自己解凍 archive) 形式の中間ファイル。実体は内部の PDF を含む実行ファイルで、ダブルクリックすると SFX ダイアログが開き、Desktop に PDF が展開される。本リポジトリの `ex_extractor` は pywinauto で SFX ダイアログを自動操作し、展開された PDF を `facility_root_dir` 配下の事業所フォルダへ移動する。

`.ex_` ファイル本体の中身を改変する必要はなく、**ファイル名のみが振り分け先決定に使われる**。検証では運用環境から取得した実 `.ex_` をそのまま使い、ファイル名だけ変えて fixture 化できる。

## 3 種 fixture の発火条件

`facility_resolver.resolve_facility(filename, facility_names, facility_aliases)` が返す状態と、それを引き起こすファイル名条件:

### SUCCESS (CONFIRMED)

`facility_resolver` が確信を持って 1 事業所に決定 → SFX 自動成功。AC-4 で使用。

| 条件 | 命名例（`facility_root_dir` に `サービスA` フォルダがある場合）|
|------|------|
| canonical 名（事業所正式名）を語境界付きで含む | `2025年04月_サービスA_提供実績.ex_` |
| alias 名を語境界付きで含む（一意 canonical） | `2025年04月_デイA_提供実績.ex_`（alias: `["デイA"]`）|

**重要**: 語境界文字は `_-. ()/[]{}\,;:!?#@&%+=*~|<>'\` + 空白類。日本語文字や英数字に隣接すると非マッチ扱い。

### SKIPPED_AMBIGUOUS (AMBIGUOUS_PARTIAL)

複数事業所の名前が部分一致し、最長候補との差が `_PARTIAL_MATCH_DOMINANCE_THRESHOLD = 2` 文字未満で曖昧 → 手動振り分け。AC-5 で使用。

`facility_root_dir` に **長さ差が 2 文字未満の 2 事業所** が必要:

```
facility_root_dir/
├── サービスA/         ← 5 文字
└── サービスB/         ← 5 文字（差 0 文字 < 閾値 2）
```

ファイル名: `サービスA_サービスB_2025年04月.ex_`

- 両事業所名がファイル名に語境界付き（`_` で区切り）部分一致
- 候補 2、長さ差 0 文字 < 閾値 → **AMBIGUOUS_PARTIAL** 発火

実運用では稀だが、検証では fixture 用に意図的にこの命名で作る。

### SKIPPED_UNMATCHED (NO_CANDIDATE)

候補ゼロ → 手動振り分け（全 facility プルダウン）。AC-6 で使用。

ファイル名: `2025年04月_未登録事業所_提供実績.ex_`（`facility_root_dir` 配下のいずれの事業所名にも部分一致しない、alias にも一致しない）

## 各 AC で必要な fixture 組合せ

| AC | ファイル | 期待状態 |
|----|---------|---------|
| AC-4 | SUCCESS 用 1 件 | CONFIRMED → SFX 自動成功 |
| AC-5 | AMBIGUOUS 用 1 件 | AMBIGUOUS → 手動選択（候補プルダウン）|
| AC-6 | UNMATCHED 用 1 件 | UNMATCHED → 手動選択（全 facility プルダウン）|
| AC-7 | AC-4 + AC-5 + AC-6 のサマリ | 「自動振り分け成功 / 手動確定成功」が分離表示 |
| AC-8 | SUCCESS 用 1 件（mtime フィルタ用）| 別 PDF を SFX 実行中に Desktop 投入しても誤配布されない |
| AC-11 | (config の `orphan_alias_canonicals` で発火、fixture 不要) | banner 表示 |

最小構成は **3 種各 1 件 = 計 3 ファイル**（AC-4/5/6 で消費、AC-7 はその後のサマリ確認、AC-8 は SUCCESS 1 件追加で計 4 件）。

## 運用環境からのコピー手順（PII 注意）

実環境の `.ex_` には事業所名・利用者氏名等の PII が含まれるため、検証用にコピーする際は以下を厳守:

1. **TeamViewer 経由で Windows PC に接続後、ローカル外への送信禁止**
2. **検証用ファイル名にリネーム** — 元ファイル名から事業所名 / 利用者氏名等の PII を除き、検証目的の文字列に置換:
   - 元: `2025年04月_<事業所名>_<利用者氏名>_提供実績.ex_` → 改: `test_success_facilityA.ex_`（事業所名は `facility_root_dir` 配下の検証用 alias と対応する文字列に）
3. **配置先**: `%USERPROFILE%\wiseman-test\ex_source\`（**本番 NAS パスではない**、`config\test.toml` の `ex_source_dir` で指定するローカル一時パス）
4. **検証完了後**: runbook §5-2 のクリーンアップ手順を実行（`Remove-Item -Recurse -Force "$HOME\wiseman-test"` で完全削除）

## ローカル fixture 配置構造（推奨）

```
%USERPROFILE%\wiseman-test\
├── ex_source\                     ← config\test.toml の ex_source_dir
│   ├── test_success_サービスA.ex_      ← AC-4 (CONFIRMED)
│   ├── test_ambiguous.ex_              ← AC-5 (AMBIGUOUS_PARTIAL)
│   └── test_unmatched.ex_              ← AC-6 (NO_CANDIDATE)
└── facilities\                    ← config\test.toml の facility_root_dir
    ├── サービスA\                  ← AC-4 と AC-5 の片方が振り分けられる
    └── サービスB\                  ← AC-5 のもう片方候補（差 0 文字で AMBIGUOUS 誘発）
```

`facility_root_dir` 配下の事業所フォルダは空でよい（PDF が振り分けられる先として実在さえすればよい）。`mkdir` だけで作成可能。

## 検証完了後のクリーンアップ

runbook [§5-2 検証用 config / 環境変数のクリーンアップ](./pr5-ex-extractor-runbook.md#5-2-検証用-config--環境変数のクリーンアップ) に集約済み（`WISEMAN_HUB_CONFIG` 環境変数解除 + `wiseman-test` 配下完全削除 + `test.toml` 削除）。本ガイドの fixture もそこで一括削除される。

## 参照

- `src/wiseman_hub/pdf/facility_resolver.py:98-147` — `ResolveStatus` / `ResolveReason` / `_REASON_TO_STATUS` 定義
- `src/wiseman_hub/pdf/facility_resolver.py:82-95` — `_PARTIAL_MATCH_DOMINANCE_THRESHOLD` / `_ALIAS_BOUNDARY_CHARS`
- `docs/adr/014-ex-extractor-integration.md` §PII 保護方針
- `docs/handoff/pr5-ex-extractor-runbook.md` §2-2 (`WISEMAN_HUB_CONFIG` 経由起動手順)
- `config/test.toml.example` (検証用 config 雛形)
