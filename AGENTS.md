# AGENTS.md — market-info-api

AI エージェント（Codex / Claude Code など）がこのリポジトリで作業する際の規則。

---

## 黄金律

1. **推測しない** — コードや既存ドキュメントで確認できないことは書かない・変えない
2. **変更は最小限・安全** — 必要な箇所だけ変える。副作用の広いリファクタはしない
3. **エンドポイント仕様の一次情報源は `/docs`（OpenAPI）** — response_model・summary・docstring を優先し、docs/ はそれを補足する
4. **認証情報を出力しない** — `.env` の値・API キーは絶対に表示・ログ出力しない

---

## ドキュメント記述ルール

### api-contract.md に書くもの
- エラーコードの意味と mini-tools 側の対応
- TTL 設計ルール・設計根拠
- manifest 形式の差異（endpoint グループ間のバリエーション）
- インシデント記録と再発防止策
- 認証の現状と将来構想

### api-usage.md に書くもの
- エンドポイント別のレスポンス例（実物に近い形）
- curl コマンド集
- キャッシュ TTL の参照表（api-contract.md の設計ルールと整合させること）

### README.md / docs/README.md に書くもの
- README.md: プロジェクト概要・エンドポイント一覧・起動方法・環境変数
- docs/README.md: ドキュメント一覧と配置ルールのみ

### 書いてはいけないもの
- 調査ログ・作業メモ（git commit message か PR description に書く）
- 廃止済みの仕様（削除して git history に任せる）

---

## コード変更ルール

### response_model の変更
- `market_info` が実際に publish する JSON の shape と一致させること
- 簡略化した型（`list[str]` など）は使わない
- nullable フィールドは `T | None` で明示する
- 変更前に `tests/` のフィクスチャが実 payload shape を反映しているか確認する

### キャッシュ
- TTL 値は `app/cache.py` の `_MANIFEST_TTL`（21600秒=6時間）/ `_DAY_TTL`（86400秒=24時間）で一元管理する
- router で直接数値を書かない

### テスト
- router unit test は `tests/fixtures/` の実 artifact shape（real_shape）を使う回帰ケースを必ず含める
- 簡略 mock だけで終わらせない

### 新しいエンドポイントを追加する場合
1. `app/routers/` に router ファイルを追加
2. `app/main.py` に `include_router` を追記
3. `docs/api-contract.md` の「更新単位」テーブルに追記
4. `docs/api-usage.md` にレスポンス例と curl コマンドを追記
5. `README.md` のエンドポイント一覧に追記
6. `tests/` にフィクスチャと回帰テストを追加

---

## Git / PR ルール

- **main への直接コミット・プッシュ禁止**
- バグ修正・動作変更は必ず PR を経由する
- 小さなドキュメント修正のみ、かつオーナーが明示的に許可した場合に限り PR を省略できる
- PR 前に `ruff check .` と `pytest` が通ることを確認する

---

## デプロイ

- main へのマージで GCP Cloud Run が自動デプロイされる
- 設定変更（環境変数・スケール）は Cloud Run コンソールで行う
- 詳細は [`docs/gcp-cloud-run-setup.md`](docs/gcp-cloud-run-setup.md) を参照
