# Handoff: Session 39 中断 - PR #172 (B/C MVP) 実機検証中、居宅マッピング自動化に方針転換

**更新日**: 2026-05-01（Session 39 / Mac + Windows TeamViewer 経由、ctx 大、未マージ状態で次セッションへ引き継ぎ）
**main HEAD**: `4f27ef4` fix(pdf): SFX 出力 PDF 名が任意のケースに対応 (snapshot 差分 fallback 復活) (#173)
**作業ブランチ**: `feature/checklist-bc-mvp` HEAD `ed6fb8b`（push 済、未マージ、PR #172 進行中）

---

## 次セッションの最優先アクション

### 🎯 ブロッカー解消: 居宅 → FAX 事業所マッピングを自動化方式に再設計

**現状の問題**:
- 設定ダイアログの Text widget に TOML フラグメントを手動貼り付け運用
- 49 件マッピング案を AI 生成 → ユーザーがコピペ時に **余分なスペースが混入** で使用不可と判断
- ユーザー要求: 「**今後 GCP と連動して自動的、もしくは手動で設定更新されるエリア**」として再設計

**設計選択肢（次セッション冒頭でユーザーと合意）**:

| 案 | 方針 | コスト | 互換性 |
|----|------|--------|--------|
| **C（推奨）** | 既存 `facility_resolver`（ex_extractor で実証済、alias > 完全一致 > 部分一致）を `checklist_b/c.py` の居宅解決にも組み込む。静的辞書を不要にする | 小（既存資産流用） | 高（既存挙動と整合） |
| **B** | アプリ内で `\\Tera-station\share\03.FAX(事業所)` をスキャンし、スプレッドシート居宅名と部分一致でマッピング自動生成 → ユーザーは確認 / 微調整のみ | 中 | 中 |
| **A** | 環境スキャン機能（既実装、`227daaf`）で GCS にアップロード → AI が GCS 上で TOML 生成 → アプリが定期取得して config 反映（プル型） | 大 | 高、要 SA キー実機配置 |

**推奨順序**: C → B → A。C なら **小規模 PR で完結**、ユーザー手動入力ゼロを実現可能。

### 着手前の確認事項
- 設計 C/B/A のどれで進めるか
- C 採用時、`PdfMergeConfig.facility_aliases` をそのまま流用するか別 alias 辞書にするか
- Windows 実機 ctx で B/C ダイアログから即動作確認できる状態に入れるか

---

## Session 39 の成果（時系列）

### ✅ PR #173 マージ完了（main 反映済）
**fix(pdf): SFX 出力 PDF 名が任意のケースに対応 (snapshot 差分 fallback 復活)**

- 実機運用で再発した「自動振り分け 0 / 失敗 3 件 (no_pdf_produced)」を修正
- PR #169 で消した `_collect_new_pdfs`（snapshot 差分）を fallback として復活、quarantine 方式と併用で誤配布リスクなしに任意名 PDF を採用可能に
- Windows 実機検証成功: 取込元 `C:\Users\sasak\OneDrive\デスクトップ\本田様` で **3 件全成功** 確認
- 検出順序: `<stem>.pdf` basename 完全一致 → snapshot 差分（任意名 1 件 OK / 複数 mtime 最新採用） → 変則命名 → NO_PDF_PRODUCED
- 教訓を `~/.claude/memory/feedback_overcorrection_regression.md` に記録（手段と目的の分離、修正前の成功挙動を消さない）

### ⏸️ PR #172 進行中（feature/checklist-bc-mvp、未マージ）
**feat(checklist): スプレッドシート連携 B/C PDF 自動配置機能 (MVP)**

積み上げコミット（main 起点 6 件）:
1. `8b3835c` feat(checklist): MVP 本体（ChecklistConfig + B/C 配置エンジン + Tk ダイアログ + 専用設定ダイアログ）
2. `9008b13` test(ui): test_launcher を 5 ボタン構成に追従（assert 5 == 3 失敗を修正）
3. `abc0946` feat(checklist): 実機向け固定パスを ChecklistConfig 初期値に焼き込み（spreadsheet_id / karte_root / fax_root）
4. `227daaf` feat(env-scan): FAX 事業所フォルダ名を GCS にアップロードする機能（手動ボタン、PII なし）
5. `0af9ddf` fix(config): SA キーパスを config_path 起点で絶対化（FileNotFoundError 修正）
6. `ed6fb8b` fix(config): SA キーパス解決時の `config/config/` 重複回避（2 段階修正完了）

**実機検証状況**:
- ✅ Launcher 起動 + 5 ボタン構成確認（ex_変換 / B 配置 / C 配置 / 事業所結合 / 設定）
- ✅ B ダイアログ起動 + 設定ダイアログ表示 + 初期値（spreadsheet_id / karte_root / fax_root）反映確認
- ❌ 環境スキャン機能（GCP 同期）は SA キーが `$HOME\wiseman-hub\config\sa-key.json` に未配置で失敗
- ⏸️ B/C 動作確認はマッピング登録段階で **コピペ運用の不便さで中断**

### 抽出済みデータ（次セッションで再利用可能）

**スプレッドシート 60 居宅**（`/tmp/wiseman-sheet/sheet.xlsx` から本セッション内で抽出済、出現頻度順）:
- 14m: ケアプラン太子 / 太子の郷 / きなり / まほろばの里 / 太子町地域包括支援センター / スマイルサポートセンター / 太子病院ケアプランセンター
- 13m: なごみの里
- 12m: 朝日地域包括支援センター
- 11m: 姫路医療生活協同組合 あぼし / 花の里 / 大津みやび野ホーム / リリーライフ / 有限会社 アミー
- 10m 以下: あんサポートオフィス / 姫路・勝原ホーム居宅介護支援事業所 / ツカザキ系 / 居宅介護支援事業所 各種 / 他
- 完全リストは次セッションで `/tmp/wiseman-sheet/sheet.xlsx` を再パースで取得可能（あるいは Drive API 経由で再取得）

**FAX 事業所 41 フォルダ名**（ユーザーが Windows 実機 PowerShell `Get-ChildItem` で取得済、Session 39 の画像 #35）:
LEBEN(メール) / RIN(メール) / あおぞら(FAX) / あゆみ愛(FAX) / あん(メール) / きなり(メール)※持参 / なごみの里(メール) / のもと本店（メール） / ほおずき（FAX） / まほろば(メール) / むれさき(FAX) / やまさん家（メール） / アミー(FAX) / オレンジ（メール） / ケアプラン太子（メール）※持参 / ケアプラン正條（FAX） / ケアプラン笑楽西明石（メール） / シスナブ御津(メール) / シルバーケア(メール) / スマイル(メール)※持参 / ツカザキ あぼし(メール) / ツカザキ 広畑(メール) / フラワー居宅（メール） / メディカルプラン結(FAX) / リリーたつの(メール)坂川CM / リリーライフ(メール)西久保CM / 大津みやびの(メール) / 大津地域包括支援センター（メール） / 太子の郷（FAX）※持参 / 太子町地域包括（メール）※持参 / 太子病院(メール) / 姫路・勝原ホーム(メール) / 姫路医療生活協同組合 あぼし(メール) / 広畑地域包括（メール） / 朝日地域包括(メール) / 清住園(FAX) / 緑ヶ丘(FAX)※17時まで / 花の里(メール) / 西はりま(FAX) / 銀の櫂（メール）

**機械マッチ済マッピング 49 件 + 不明 10 件** は Session 39 内で AI 生成済（コピペ運用は却下、次セッションで C 案実装後にこのデータをテストフィクスチャとして再利用可能）。

---

## 既存 follow-up Issue（Session 38 から継続、未着手）

| # | 由来 | 概要 | 推奨 timing |
|---|-----|------|-----|
| #170 | type-design-analyzer | `_quarantine_pre_existing_target` を Quarantine dataclass で tagged union 化 | 実害なし、優先度低 |
| #164 | silent-failure-hunter HIGH | ExExtractorViewModel.source_dir TOCTOU / 不変条件 | 設計変更で範囲広い |
| #162 | silent-failure-hunter Medium | Launcher 同期 callback フリーズ + 例外保護 | ADR 追記要件 |
| #161 | silent-failure-hunter HIGH | GUI 再統合時 messagebox マッピング再構築 | 復活前提なら都度 |
| #158 | codex review Medium | 起動後 callback の load_config 失敗 actionable 化 | 影響中 |
| #152 | (#27 PR-B 系) | UserNameBBox NaN/inf + OcrBackendConfig 空白 URL 検証 | 型強化、Mac で完結可 |

---

## Session 39 で顕在化した運用課題

### 🔴 SA キー実機配置の運用漏れ（Issue 化不要、CLAUDE.md 編集で対応）
- `$HOME\wiseman-hub\config\sa-key.json` がリポジトリ除外（秘密情報）+ runbook に配置手順記載なし
- GCP 機能（GCS upload / 環境スキャン）を実機で動かすには SA キー転送が必須
- **次セッション初手で CLAUDE.md runbook に Phase 0-3「SA キーを配布レイアウトに配置」を追記**

### 🟡 Windows 実機 pytest 失敗 9 件（PR #172 と独立、別件）
本セッションで Windows 実機 `uv run pytest` を回した結果、以下の既存問題が顕在化:
1. **Tcl/Tk 壊れ**: `Can't find a usable tk.tcl` / `icons.tcl no such file` → Python 311 修復インストール推奨
2. **`PywinautoEngine vs MockEngine`**（test_app.py）: Windows 実機で sys.platform == "win32" のため、macOS 専用テストが失敗。`@pytest.mark.skipif(sys.platform == "win32")` 不足。Session 38 で `test_constructor_raises_on_macos` に追加した skipif と同根
3. **`microseconds 比較失敗`**（test_session.py:1954）: `'2026-04-30T21:48:39.356190+00:00' != '2026-04-30T21:48:39.356190+00:00'` で同じ文字列が `!=` 判定。Windows のクロック解像度問題
4. **`'disk full' in msg`**（test_confirm_dialog.py）: メッセージ言語 / OS 文言の差
5. **`AttributeError: 'WindowsPath' has no attribute 'candidates'`**（test_confirm_dialog 系 5 件）: Tcl/Tk 壊れ連鎖の可能性高

→ Tcl/Tk 修復が最大の根本対応。修復後に他 4 件を再評価し、必要なら個別 Issue 起票（triage 基準: rating 7+ / 実害確認）。

---

## 関連 PR / ブランチ

| 種別 | 識別子 | 状態 |
|------|--------|------|
| PR #173 | fix(pdf): snapshot 差分 fallback | ✅ Merged (main 反映済) |
| PR #172 | feat(checklist): B/C 自動配置 MVP | ⏸️ Open（feature/checklist-bc-mvp、未マージ） |
| ADR-012 | facility_merger 出力仕様 | Accepted |
| ADR-013 | 事業所ルート一括結合 | Accepted |
| ADR-014 | ex_extractor + facility_aliases | Proposed → 実装進行中（PR6 実機検証完了で Accepted 化検討） |

---

## メモリ更新（次セッションで実施推奨）

- `~/.claude/memory/feedback_overcorrection_regression.md`: 「実証済み」に格上げ可能（PR #173 検証成功、Windows 実機で 3 件成功確認）→ Session 39 末で「実機検証完了」を 1 行追記推奨

---

## Issue Net 変化

- Close 数: **0 件**
- 起票数: **0 件**
- **Net: 0 件**

理由: 本セッションは PR #173 マージ + PR #172 実装積み上げ + 実機検証中断という構成で、新規 Issue 起票が triage 基準（rating 7+ / 実害確認）を満たすものは無し。Tcl/Tk 修復・skipif 追加等の運用課題は次セッションで再評価して必要なら起票。

---

## 次セッション開始時の推奨手順

```
1. /catchup → 本ハンドオフ + 関連 PR の確認
2. ユーザーに設計 C/B/A 提示 → 合意
3. C 採用時:
   - facility_resolver の現状コード確認 (src/wiseman_hub/pdf/facility_resolver.py)
   - checklist_b.py / checklist_c.py の resolve_facility() を facility_resolver 呼び出しに置換
   - ChecklistConfig.facility_routing は alias 入力欄として残す or 廃止
   - テスト追加 (実機の 60 居宅 + 41 フォルダ名でフィクスチャ作成可能)
4. Windows 実機反映 → B/C 動作確認 (1 居宅で SUCCESS 確認)
5. 既存 facility_merger との連携 (A→B→C 結合) 確認
6. PR #172 マージ判断
```

## 抽出済みリファレンスへのアクセス方法

```bash
# スプレッドシート再パース (60 居宅取得)
uv run python -c "
from wiseman_hub.cloud.sheets import list_sheet_names, parse_sheet
from pathlib import Path
xlsx = Path('/tmp/wiseman-sheet/sheet.xlsx').read_bytes()
all_facilities = {}
for sn in list_sheet_names(xlsx):
    for r in parse_sheet(xlsx, sn):
        if r.facility:
            all_facilities.setdefault(r.facility, set()).add(sn)
ranked = sorted(all_facilities.items(), key=lambda kv: -len(kv[1]))
for name, months in ranked:
    print(f'[{len(months):2d}m] {name!r}')
"
# (xlsx は /tmp 配下なので、新セッションで Drive API 経由で再取得が必要な可能性あり)
```
