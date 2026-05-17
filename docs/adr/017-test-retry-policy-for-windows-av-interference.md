# ADR-017: Windows 機の AV 干渉対策としてのテスト retry ポリシー

## Status

Accepted (2026-05-18)

## Context

本田様 PC (Windows 11、業務運用機) で `scripts/deploy-windows.ps1` の Phase 0 (`uv run pytest -q -m "not integration"`) が **intermittent fail** で deploy 阻害を起こしていた (Issue #316)。

### 観察された現象 (Issue #316 history)

- PR #311 マージ後の最初の deploy で 4 件のテスト失敗
- PR #312 で path tests 互換修正後 → 1 件失敗 (`test_persists_after_fetch`)
- 毎回 **異なるテストで失敗** する intermittent パターン
- GitHub Actions windows-latest CI では同じテストが PASS
- 「`couldn't read file ...init.tcl: No error`」(errno=0 で read fail) の典型エラー

### 実機診断結果 (2026-05-18、`scripts/diagnose-tcl.ps1`)

全 5 セクションを実機実行し以下を確認:

| Section | 結果 | 意味 |
|---------|------|------|
| 1. Python / init.tcl 実在 | ✅ OK (25633 bytes、Mode -a----) | ファイル健全、破損なし |
| 2. init.tcl read 5 回 | ✅ **5/5 成功** | スタンドアロン read 経路に AV 干渉なし |
| 3. tk.Tk() 起動 10 回 | ✅ **10/10 成功** | **tkinter コード自体は完全に健全** |
| 4. Windows Defender 状態 | ⚠️ `Get-MpPreference` 0x800106ba 失敗 | ESET が Tamper Protection 化 |
| 5. 第三者 AV プロセス | ⚠️ **ESET (ekrn) 検出** | NOD32 / Endpoint Security |

スタンドアロン実行で **15 連続全成功** という事実 + pytest 実行時のみ intermittent fail という観察から、Issue #316 の真因を以下に確定:

> **pytest 実行時の subprocess 大量起動 × ESET 動的 scan のタイミング競合**
>
> pytest は test isolation のため複数の subprocess を頻繁に起動する。ESET は新規 process 起動時に exe + DLL + Python script 全部を scan する。大量 subprocess + ESET scan → ファイル lock 競合 → 確率的に init.tcl の read が一時 lock される (errno=0 で read fail = "file is busy")。

### ユーザー方針 (制約条件)

「**本田様 PC 側で人手の設定変更 (ESET GUI 除外、Python 再 install、レジストリ編集等) は一切しない。AI 完結で完了する設計を優先する**」と明示。理由:

- 本田様 PC は業務運用機。GUI 設定変更を都度実施するのは現実的でない (介在コスト + 設定漂流リスク)
- AI が executor として完結する設計を維持したい

## Decision

`pytest-rerunfailures` プラグインを採用し、テスト失敗時に **最大 2 回の自動 retry** で intermittent fail を吸収する。

### 具体的な実装

`pyproject.toml`:

```toml
[project.optional-dependencies]
dev = [
    # ... 既存 ...
    "pytest-rerunfailures>=14.0",  # Issue #316 対応
    # ... 既存 ...
]

[tool.pytest.ini_options]
addopts = "-v --tb=short --reruns 2 --reruns-delay 1"
```

### 数値選定の根拠

- **`--reruns 2`** (初回 + 2 回 retry、合計 3 回試行):
  - AV intermittent 発生率を 30% と仮定すると、3 回試行の最終失敗率は `0.3^3 ≒ 2.7%` (= 約 97.3% 成功率)
  - 1 回試行なら成功率 70%、deploy が頻繁に阻害される
  - 4 回以上は deploy 時間が無視できなくなる (失敗 1 件あたり +3-4 秒)
- **`--reruns-delay 1`** (1 秒間隔):
  - ESET scan が完了するまでの時間を考慮、過短だと連続失敗、過長だと deploy 時間影響大
  - 実機計測なしのため、運用結果次第で 2-3 秒への調整余地あり

### 採用しなかった代替案 (Issue #316 [#issuecomment-4472459362](https://github.com/sasakisystem0801-source/wiseman-auto-sys/issues/316#issuecomment-4472459362) より)

| 候補 | 評価理由 |
|------|---------|
| **A. uv-managed Python 切替** | tkinter コード自体は健全 (Section 3 で 10/10 成功) なので AV scan path 変更で根本対処する必要なし。pyinstaller build 等への副作用も大きい。✕ |
| **B. `-SkipPytest` 正規化** | テストを丸ごとスキップする設計は CI 信頼倒し。CI で気づかれない実機固有問題を見逃すリスク (現状 CI で PASS、実機のみ fail なので逆方向)。⚠️ |
| **D. tk テスト marker skip** | どのテストが failing するか predictable でない (毎回違うテスト)。特定 marker skip では取りこぼし発生。✕ |

候補 C (本決定) は **副作用最小** で実装でき、tkinter コードが健全という診断結果と整合的 (retry すれば成功する性質)。

## Consequences

### Positive

- **AV intermittent fail の自動吸収** = `scripts/deploy-windows.ps1` の disaster recovery 手動手順への依存解消
- **CI / 開発機で副作用ゼロ** (intermittent が起きないので retry 発動しない)
- **本田様 PC で実機効果実証済**: PR #343 マージ後の `uv run pytest` で `1 rerun` を観測、`test_checklist_c_dialog_mirror_hook` の 1 件が retry で吸収された
- 真のバグ (3 回連続で fail するもの) は通常通り検出される

### Negative

- **真のバグの発見が retry 数回分遅延する可能性**: ただし 3/3 全失敗は通常通り fail として検出されるので、確定的な fail なら影響なし
- **deploy 時間影響**: AV 干渉発生時のみ +1-3 秒、平時はオーバーヘッドゼロ
- **dep 1 個追加**: `pytest-rerunfailures` (active maintained、PyPI 安定、`pytest>=7` 互換)

### Neutral

- retry log は pytest 出力に `R` マーカーで明示される (デバッグ可能性は維持)
- `--only-rerun=ERRORREGEX` 等で特定エラーパターン限定の retry も将来追加可能 (現状は全エラー対象)

## Future Considerations

### Retry 数調整の判断基準

運用結果次第で以下のいずれかの方向に調整する:

| 状況 | 対応 |
|------|------|
| 3 回試行でも頻繁に fail する | `--reruns 5` 等に増やす + ADR を amend |
| retry が一度も発火しない (3 ヶ月以上) | ESET 設定変更 / Python install 変更等の環境変化を疑い、retry 数削減検討 |
| 特定パターンのみ retry したい | `--only-rerun=` で error regex を絞る |
| dep そのものを廃止したい | tkinter テストを subprocess-free 化 / pytest --forked 等で subprocess 数削減 / または環境変化で intermittent 解消 |

### この ADR の廃止条件

以下のいずれかの場合、本 ADR を **Superseded** に変更:

1. 本田様 PC の ESET が他社製 AV に変更され、本問題が再現しなくなった (環境変化)
2. テスト構造を変更して subprocess 数を大幅削減し、AV 干渉が確率的に起きなくなった
3. CI / 業務運用機が分離され、本田様 PC で deploy 時に pytest を実行する必要がなくなった

### 関連設計事項

- 本 ADR は **Issue #316 の運用面対処**であり、tkinter / AV の根本問題には踏み込まない
- 将来 `.github/workflows/` に **PowerShell 構文 lint job** を追加することで、`scripts/*.ps1` の構文事故 (今回の PR #340-#342 で発生) を未然防止する候補あり (本 ADR の範囲外、別 Issue 候補)
- 本田様 PC の AV 干渉問題は、`uv-managed Python` への移行 (候補 A) で **path-based scan を回避できる可能性**は残るが、本 ADR では選択せず。将来 deploy 時間が更に問題化した場合の再評価対象

## References

- Issue #316: [chore(infra): 本田様 PC の Tcl init.tcl read failure 調査 (deploy Phase 0 阻害)](https://github.com/sasakisystem0801-source/wiseman-auto-sys/issues/316)
- Issue #316 真因確定コメント: [#issuecomment-4472459362](https://github.com/sasakisystem0801-source/wiseman-auto-sys/issues/316#issuecomment-4472459362)
- Issue #316 実機効果実証コメント: [#issuecomment-4472478145](https://github.com/sasakisystem0801-source/wiseman-auto-sys/issues/316#issuecomment-4472478145)
- PR #340 (merge `842d3a6`): diagnose-tcl.ps1 BOM 付き UTF-8 変換 (診断ツール復旧 part1)
- PR #341 (merge `cfb2cf7`): diagnose-tcl.ps1 line 53 backtick エスケープ修正 (part2)
- PR #342 (merge `e1fce7c`): diagnose-tcl.ps1 Section 3 Python embed 一時ファイル化 (part3)
- **PR #343 (merge `68054d2`): pytest-rerunfailures 導入 (本 ADR の実装)**
- 関連 memory (global): [feedback_no_manual_windows_changes.md](https://github.com/yasushi-honda/claude-code-config/blob/main/memory/feedback_no_manual_windows_changes.md)
- 関連 runbook: `docs/handoff/1c-exe-redistribution-runbook.md` の「🔬 Tcl init.tcl 連発失敗時の対処」セクション
- pytest-rerunfailures 公式: https://github.com/pytest-dev/pytest-rerunfailures
