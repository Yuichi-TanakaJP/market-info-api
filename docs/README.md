# docs/

market-info-api のドキュメント置き場。

エンドポイント仕様の一次情報源は **`/docs`（OpenAPI）**。  
このディレクトリには OpenAPI では表現しにくい事項や運用手順を補記する。

---

## ドキュメント一覧

| ファイル | 内容 |
|----------|------|
| [api-contract.md](api-contract.md) | エラーコード・fallback 設計・TTL ルール・更新単位・manifest 形式・インシデント記録 |
| [api-usage.md](api-usage.md) | エンドポイント別レスポンス例・curl コマンド集 |
| [gcp-cloud-run-setup.md](gcp-cloud-run-setup.md) | GCP Cloud Run へのデプロイ手順（初期セットアップ・CI 連携） |
| [history/mini-tools-migration-20260501.md](history/mini-tools-migration-20260501.md) | mini-tools → API 移行手順（移行完了済み・retired 2026-05-01） |

---

## 配置ルール

| 置く場所 | 内容 |
|----------|------|
| `docs/` | API 仕様・運用・デプロイ・migration ガイド |
| `app/` | 実装コード（仕様の一次情報源は OpenAPI） |

「なぜこの TTL にしたか」「なぜこの Pydantic 型か」などの **設計根拠** は `api-contract.md` に追記する。  
調査ログや廃止済みの設計メモは `docs/` に残さず git history で参照すること。
