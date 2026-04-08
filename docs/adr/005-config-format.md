# ADR-005: 設定形式の選定

## ステータス
Accepted (2026-03-22) — **認証情報管理 (keyring / username) 部分は ADR-007 により廃止 (2026-04-08)**

## コンテキスト
デスクトップアプリの設定（スケジュール、抽出対象帳票、GCP接続情報、RPAセレクタ等）を管理する形式を決定する。クライアントPCの管理者が手動で編集する可能性もある。

## 検討した選択肢

### A. TOML（採用）
- Python 3.11+で`tomllib`がstdlib
- 人間が読みやすく編集しやすい
- コメント対応

### B. YAML
- 広く使われるが、インデントの罠がある
- PyYAMLの依存追加が必要 → **不採用**

### C. JSON
- コメント非対応
- 設定ファイルとしての人間可読性が低い → **不採用**

### D. 環境変数
- サーバー向け。デスクトップアプリでは再起動を跨ぐ管理が不便 → **不採用**

### E. Windows Registry
- Windows専用すぎる。開発機(macOS)でテスト困難 → **不採用**

## 決定
**TOML形式を設定ファイルとして採用する。**

> **注記 (2026-04-08, ADR-007)**: 当初は「機密情報はkeyring（Windows DPAPI）で別管理する」としていたが、実機確認でワイズマンはUSBドングル認証のみであることが判明し、アプリ内ログイン画面も username/password も存在しないため、keyring 依存と `wiseman.username` フィールドは全削除された。以下の設定例中の username 行とkeyring参照は歴史的参考として残すが、現在は使用しない。

## 設定構造の例

```toml
[app]
version = "1.0.0"
log_level = "INFO"
log_dir = "C:\\ProgramData\\WisemanHub\\logs"

[wiseman]
exe_path = "C:\\Program Files\\Wiseman\\wiseman.exe"
startup_wait_sec = 10
username = "operator01"
# パスワードはkeyringで管理（この設定ファイルには含めない）

[schedule]
enabled = true
cron = "0 8 * * *"  # 毎日8時

[reports]
# 抽出対象の帳票リスト
[[reports.targets]]
name = "月次実績"
menu_path = ["帳票", "実績管理", "月次実績"]
output_format = "csv"

[[reports.targets]]
name = "利用者一覧"
menu_path = ["マスタ", "利用者一覧"]
output_format = "csv"

[gcp]
project_id = "wiseman-client-001"
bucket_name = "wiseman-client-001-datalake"
service_account_key_path = "C:\\ProgramData\\WisemanHub\\sa-key.json"
region = "asia-northeast1"

[updater]
enabled = true
check_interval_hours = 1
release_bucket = "wiseman-client-001-releases"
```

## 理由
1. **stdlib対応**: Python 3.11+で外部ライブラリ不要
2. **可読性**: INIの拡張として直感的。コメントでセクション説明可能
3. **構造化**: ネストしたテーブルで帳票リスト等を自然に表現
4. **セキュリティ分離**: 機密情報（パスワード、APIキー）はTOMLに含めず`keyring`で管理

## 結果
- `config/default.toml` にデフォルト設定テンプレート
- `src/wiseman_hub/config.py` にTOMLローダー実装
- `keyring`ライブラリでWindows DPAPI暗号化ストレージを使用
- 設定ファイルパス: `C:\ProgramData\WisemanHub\config.toml`（デフォルト）
