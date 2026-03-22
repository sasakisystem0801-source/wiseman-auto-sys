# ADR-003: GCPサービスの選定

## ステータス
Accepted (2026-03-22)

## コンテキスト
ワイズマンから抽出したデータをクラウドに蓄積し、分析やアプリ配信の基盤を構築する。コストを最小化しつつ、将来の拡張に備える。日本の介護データ（個人情報）を扱うため、データレジデンシーの考慮が必要。

## 決定

### リージョン: asia-northeast1（東京）
個人情報保護法（APPI）への準拠と低レイテンシのため。

### 採用サービス

| サービス | 用途 | 推定月額コスト |
|---------|------|--------------|
| **Cloud Storage (Standard)** | データレイク（CSV, Excel, ログ） | ~$0.25 |
| **BigQuery** | 分析ウェアハウス | $0 (Free Tier) |
| **Pub/Sub** | クラウド→クライアント指示キュー | $0 (Free Tier) |
| **Cloud Functions 2nd gen** | ETLトリガー、軽量API | $0 (Free Tier) |
| **Secret Manager** | サービスアカウントキー管理 | $0 (Free Tier) |
| **Cloud Logging** | 集中ログ管理 | $0 (Free Tier) |

**合計推定月額: $0.25-2.00**

### 不採用サービス

| サービス | 不採用理由 |
|---------|-----------|
| Firestore | Pub/Subの方がメッセージング用途に適合。デスクトップアプリにはオーバースペック |
| Cloud Run | Cloud Functionsで十分。Phase 3で再検討 |
| Firebase | シングルクライアントのデスクトップアプリには過剰 |
| App Engine | 不要。サーバーレス関数で十分 |

## 理由
1. **コスト最適化**: シングルクライアント環境では全サービスがFree Tier内に収まる
2. **データレジデンシー**: 東京リージョンで日本国内にデータを保持
3. **スケーラビリティ**: BigQuery + Cloud Functionsは将来の複数クライアント対応に自然に拡張可能
4. **シンプルさ**: 最小限のサービス構成で複雑性を抑制

## 結果
- インフラはTerraformで管理（`infra/terraform/`）
- サービスアカウントは最小権限（Storage Object Creator, Pub/Sub Subscriber）
- GCPプロジェクトはクライアントアカウントに作成
- バケット命名規則: `{project-id}-wiseman-{用途}`（例: `xxx-wiseman-datalake`, `xxx-wiseman-releases`）
