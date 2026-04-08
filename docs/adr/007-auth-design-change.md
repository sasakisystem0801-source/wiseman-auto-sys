# ADR-007: 認証設計の確定 - USBドングルのみ、アプリ内ログイン画面なし

## ステータス
**Accepted (2026-04-08)**

## コンテキスト

`docs/wiseman-system-spec.md` の当初記述では「アプリ起動後にユーザー名/パスワードで認証（要実機確認）」とされており、これを前提に以下が実装されていた:

- `RPAEngine.launch_and_login(exe_path, username, password)` API
- `WisemanConfig.username` フィールド
- `keyring` によるパスワード管理（`app.py:_get_password`）
- モックアプリ `WisemanMock/LoginForm.cs`（ユーザーID/パスワード入力画面）
- 統合テスト群での `("testuser", "testpass")` 認証

2026-04-08 のユーザー情報で、**実機ワイズマンはUSBドングル認証のみで動作し、アプリ内にログイン画面は一切存在しない** ことが確定した。exe 起動 → ドングル認証待機 → メインウィンドウ直接表示 というフローになる。

## 決定

1. **API契約**: `RPAEngine.launch_and_login(exe, user, pwd)` → `RPAEngine.launch(exe)` にシグネチャ変更
2. **config**: `WisemanConfig.username` フィールドを削除
3. **認証情報管理**: `keyring` 依存を削除、`_get_password` を削除
4. **モックアプリ**: `LoginForm.cs` を削除、`Program.cs` は `Application.Run(new MainForm())` に変更
5. **仕様書**: `docs/wiseman-system-spec.md` 6章を「ログイン画面なし」で確定
6. **ライセンスID認証**: 本クライアントは USB ドングル認証のみ使用するため、ライセンスID認証のフロー実装は対象外

## 影響

- Issue #3/#12/#6 のブロッカー解消（実機と乖離したログイン前提コードが消える）
- 統合テスト群（6ファイル）の `launch_and_login(...)` 呼び出しを `launch(exe_path)` に更新
- `pyproject.toml` から `keyring>=25.0.0` 依存を削除
- Windows CI（#10）には追加影響なし（conftest のプラットフォームガードは不変）

## 代替案と却下理由

- **案B: `username` を optional として残す** → 却下。未使用フィールドが残ると将来の混乱と「いつか使うかも」バイアスを生む。ライセンスID認証が将来必要になれば ADR-008 で新規設計する。
- **案C: モックの LoginForm を残す** → 却下。実機と乖離したテストは誤った安心感を生む。モックは実機と同じフロー（起動即メインウィンドウ）にすべき。

## 関連
- 旧状態の ADR-001 (Revised): pywinauto 選定
- 旧状態の ADR-006: ASP版自動化戦略（Superseded）
- Issue #3, #12, #6
