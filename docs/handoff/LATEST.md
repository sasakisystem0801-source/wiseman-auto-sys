# Handoff: Session 37 完了 - Windows 実機反映 + CLAUDE.md 永続化 (#167)

**更新日**: 2026-04-29（Session 37 / Mac + Windows TeamViewer 経由で完結）
**ブランチ**: docs/handoff-session-37 (PR 予定)
**main HEAD**: `22614dc` docs(claude-md): Windows 実機反映手順を CLAUDE.md に永続化 (#167)

## 次セッション主軸

Session 36 LATEST の主軸 #1（Windows 実機検証）は本 Session で消化済。残りは:

### 次セッションの優先候補

1. **業務フロー ② BC PDF 生成の指示受け** — Session 35→36→37 と 3 セッション越しの未消化。ユーザー明示「次セッションに指示」が継続中、**最優先で確認推奨**
2. **#152 着手 (#27 PR-B 系)** — UserNameBBox NaN/inf + OcrBackendConfig 空白 URL 検証。型強化系の継続、Mac で完結可能
3. **Session 36 派生 follow-up Issue (#158/#161/#162/#164/#165)** — 必要に応じて着手

### Session 36 で派生した follow-up Issue（再掲、未着手）

| # | 由来 | 概要 | 推奨 timing |
|---|-----|------|-----|
| #158 | codex review (Medium) | 起動後 callback の load_config 失敗 actionable 化 (`__main__.py:81/128/373/405`) | 既存設計修正、影響範囲中 |
| #161 | silent-failure-hunter HIGH | GUI 再統合時の messagebox マッピング再構築要件（将来 GUI 復活時の guard） | 復活前提なら都度実装 |
| #162 | silent-failure-hunter Medium ×2 | 同期 callback 重い処理時 UI フリーズ + `_invoke_or_show` 例外保護 | ADR 追記要件 |
| #164 | silent-failure-hunter HIGH | ExExtractorViewModel.source_dir setter 検証で TOCTOU / 不変条件 | 設計変更で範囲広い |
| #165 | silent-failure-hunter Medium | GUI 選択した取込元の「(セッション限定)」UX hint | UX 改善、軽微 |

## Session 37 の成果

### Windows 実機反映完了（Session 36 主軸 #1 消化）

`docs/handoff/1c-exe-redistribution-runbook.md` に従い、PR #160 (#154) / PR #163 (#155) の Windows 実機反映を実施:

| Phase | 内容 | 結果 |
|---|---|---|
| Phase 0 | リポジトリ最新化 + 現行 exe バックアップ | ✅ `wiseman_hub.exe.bak-20260429-092624` 保存（rollback 可能） |
| Phase 0-4 | テスト実行（`pytest -q -m "not integration"`） | ✅ VS Build Tools 不要構成で完走 |
| Phase 1 | clean ビルド + warning 検査 | ✅ 既知無害 warning のみ（pycparser.lextab/yacctab/jinja2） |
| Phase 2 | 配布先上書き | ✅ `$HOME\wiseman-hub\wiseman_hub.exe` 78,623,990 bytes / 2026-04-29 9:24 |
| Phase 3 | 動作確認 | ✅ Launcher 起動 / 3 ボタン構成（PR #160 反映確認） / ExExtractorDialog 取込元選択ボタン表示（PR #163 反映確認） |

### マージ済 1 PR

| PR | Issue | 内容 | 規模 |
|----|-------|------|------|
| #167 | なし（ハーネス改善） | CLAUDE.md `Cross-Platform Development` 配下に「Windows 実機環境（本田様 PC、TeamViewer 経由）」サブセクション追加。環境定数（PowerShell user / clone 先 / 配布先 / 本番データ / Wiseman 本体）/ 正規 runbook リンク（1c-runbook）/ 最小フル手順（コピペ可、実機検証済）/ 動作確認チェックリスト / 既知の落とし穴 / rollback 手順 / 開発検証ショートカットを記述 | 1 ファイル / +89 / -0 |

### グローバル memory 更新

- `~/.claude/memory/feedback_project_runtime_paths.md` 新規作成: 「プロジェクト固有の運用パスはプロジェクト CLAUDE.md に書く」原則を確立（ADR 内「Session N 実機検証結果」に埋もれさせない、グローバル memory にはプロジェクト固有を書かない）
- `~/.claude/memory/MEMORY.md` インデックス更新

### Issue Net 変化

```
- Close 数: 0 件
- 起票数: 0 件
- Net: 0 件
```

Session 37 はハーネス改善 + 実機反映 = Issue 化されないタイプの作業。Issue 操作ゼロだが、Session 36 LATEST「次セッション主軸 #1 Windows 実機検証」の消化が実質的な進捗。

### Session 37 で派生した教訓 / 設計判断

| 教訓 | 永続化先 |
|------|---------|
| ADR の「実機検証結果」内に運用パスを埋めると catchup で見落とす（毎回探し直す無駄が発生） | プロジェクト CLAUDE.md (PR #167) |
| プロジェクト固有運用パスはプロジェクト CLAUDE.md に書く（グローバル memory に置くと他プロジェクト作業時にノイズ） | グローバル `feedback_project_runtime_paths.md` |
| `pytest` から実 Wiseman は起動されない（`scripts/smoke_real.py` 経由のみ）。`tests/integration/` は自前モック `WisemanMock.exe` を起動 | CLAUDE.md 落とし穴セクション |
| `uv run pytest -q -m "not integration"` で VS Build Tools 不要構成で完走可能 | CLAUDE.md 落とし穴セクション |
| PowerShell `Select-String` パイプチェーンの `-NotMatch "..."` で引数解釈エラー発生（実機 2026-04-29 観測） | CLAUDE.md 落とし穴セクション |
| `Copy-Item -Force dist\wiseman_hub.exe "$dist\wiseman_hub.exe"` は exe 起動中だと file lock で失敗 | CLAUDE.md 落とし穴セクション |
| `uv sync` 単独だと dev extras（pyinstaller/ruff/mypy/pytest）が削除される、`--extra dev` 必須 | CLAUDE.md 落とし穴セクション（既知だが再確認） |

### Session 37 のレビュー / コミュニケーションプロセス

- PR #167 は `/review-pr` で 2 エージェント並列レビュー（comment-analyzer + code-reviewer）→ Critical/Important なし（GO 無条件）→ ユーザー番号単位明示認可（4 原則 §3）→ squash merge
- Windows 機反映フェーズで AI が clone 先を 2 度誤推測（`Desktop\wiseman-auto-sys` → `wiseman-hub\` → 正しい `Projects\wiseman-auto-sys`）。この実体験が PR #167 の動機になり、再発防止の機構（CLAUDE.md セクション + グローバル feedback memory）に昇華

## 次セッション開始時の意思決定

1. **業務フロー ② BC PDF 生成の指示受け** — ユーザー明示「次セッションに指示」が 3 セッション継続。最優先確認
2. **#152 着手判断** — Mac で完結可能（UserNameBBox NaN/inf 検証等の型強化）
3. **Session 36 派生 follow-up Issue (#158/#161/#162/#164/#165)** — 必要に応じて

### catchup 時の確認項目

#### Mac 側（macOS 開発機）

```bash
cd /Users/yyyhhh/Projects/wiseman_auto_sys
git checkout main && git pull --ff-only
# main HEAD が 22614dc 以降（Session 37 マージ後）であることを確認
gh issue list --state open
```

#### Windows 機側（TeamViewer 経由、必要時のみ）

**反映手順は CLAUDE.md「Windows 実機環境」セクション参照**（Session 37 で永続化、最初に読む）。要約:

```powershell
cd $HOME\Projects\wiseman-auto-sys
git pull --ff-only
# 実機反映が必要な場合は CLAUDE.md の「main を実機反映する正規手順」をコピペ実行
```

---

## 参照ファイル

### Session 37 成果物

- `CLAUDE.md`: Windows 実機環境セクション追加 (PR #167)。clone 先 `C:\Users\sasak\Projects\wiseman-auto-sys` / 配布先 `C:\Users\sasak\wiseman-hub\` / PowerShell 手順 / 動作確認チェックリスト / 落とし穴 / rollback を集約

### 重要 doc

- `docs/handoff/1c-exe-redistribution-runbook.md`: exe 再ビルド + 配布の正規 runbook（CLAUDE.md から明示参照、Session 37 で参照経路を確立）
- `docs/handoff/pr5-ex-extractor-runbook.md`: AC-2〜14 実機検証 runbook（次セッション主軸 #1 関連、Session 37 では未着手）
- `docs/adr/011-distribution-format.md`: 配布レイアウト（`wiseman-hub/` 構造定義）
- `docs/adr/013-facility-root-bulk-merge.md`: UNC パス定義 `\\Tera-station\share\03.FAX(事業所)` + 別人混入禁止 fail-safe
- `docs/adr/014-ex-extractor-integration.md`: ex_extractor 業務フロー + PR5 Accepted 昇格条件

### グローバル memory（Session 37 関連）

- `~/.claude/memory/feedback_project_runtime_paths.md`: プロジェクト固有運用パス記載原則（Session 37 で確立）
- `~/.claude/memory/MEMORY.md`: インデックス更新（同 feedback へのエントリ追加）

### 履歴

- `docs/handoff/archive/2026-04-history.md`: Session 11-34 詳細
- Session 35: PR #156 / git log 参照
- Session 36: PR #166 / git log 参照
- Session 37: 本 LATEST.md
