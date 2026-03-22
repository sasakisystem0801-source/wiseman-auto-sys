# ADR-004: 自動更新メカニズムの設計

## ステータス
Accepted (2026-03-22)

## コンテキスト
クライアントPCのデスクトップアプリを、現場訪問なしに自動更新したい。更新失敗時のロールバックも必要。クライアントPCの管理者権限やITリテラシーに依存しない仕組みが望ましい。

## 検討した選択肢

### A. GCSマニフェストポーリング（採用）
- GCS上の`manifest.json`を定期チェック
- 新バージョン検出→ダウンロード→チェックサム検証→アトミック置換

### B. Pub/Subプッシュ通知
- サーバーからプッシュで更新通知
- リアルタイム性は高いが、常時接続が必要 → **不採用**（ポーリング1時間で十分）

### C. GitHub Releases直接チェック
- GitHub API Rate Limitの制約
- クライアントにGitHub認証が必要 → **不採用**

### D. Sparkle / WinSparkle
- 既存の自動更新フレームワーク
- C/C++ベースでPython統合が複雑 → **不採用**

## 決定
**GCS上のmanifest.jsonをポーリングする自前の自動更新メカニズムを採用する。**

## 設計

### GCSバケット構造
```
wiseman-hub-releases/
├── manifest.json          # 現在バージョンのメタデータ
├── releases/
│   ├── wiseman-hub-1.0.0.exe
│   └── wiseman-hub-1.1.0.exe
└── checksums/
    ├── wiseman-hub-1.0.0.sha256
    └── wiseman-hub-1.1.0.sha256
```

### manifest.json
```json
{
  "current_version": "1.2.0",
  "minimum_version": "1.0.0",
  "download_url": "releases/wiseman-hub-1.2.0.exe",
  "checksum_sha256": "abc123...",
  "release_notes": "バグ修正とパフォーマンス改善",
  "released_at": "2026-03-22T10:00:00Z",
  "force_update": false
}
```

### 更新フロー
1. **ポーリング**: 1時間ごとにmanifest.jsonを取得
2. **比較**: semverで現在バージョンと比較
3. **ダウンロード**: 新バージョンをtempディレクトリに取得
4. **検証**: SHA256チェックサム照合
5. **ステージング**: `.new`サフィックスで配置
6. **再起動**: バッチスクリプトでアトミック置換

### ロールバック
- 更新前のexeを`.bak`として3世代保持
- 新バージョンが起動に失敗（ヘルスチェック用センチネルファイル未生成）→ 自動ロールバック
- `minimum_version`フィールドでセキュリティパッチの強制更新を制御

## 理由
1. **シンプルさ**: HTTP GETのみで完結。永続接続不要
2. **堅牢性**: チェックサム検証 + アトミック置換 + ロールバック
3. **GCP統合**: 他のGCSバケットと同一の認証情報で利用可能
4. **帯域**: ポーリングはmanifest.json（数百バイト）のみ。exe本体のダウンロードは必要時のみ

## 結果
- `src/wiseman_hub/updater/auto_update.py` に実装
- CI/CDパイプラインがタグpush時にGCSへexeをアップロードし、manifest.jsonを更新
- Phase 2（MVP）後半で実装開始、Phase 3（Production）で本番投入
