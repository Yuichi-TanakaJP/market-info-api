# market-info-api 使い方

## ベース URL

```
https://market-info-api-619599800912.asia-northeast1.run.app
```

---

## エンドポイント一覧

### ヘルスチェック

```
GET /health
→ {"status": "ok"}
```

### 株式ランキング

```
GET /ranking/manifest
→ {"dates": ["2026-03-27", ...], "latest": "2026-03-27"}

GET /ranking/{date}         # date: YYYY-MM-DD
→ {"date": "2026-03-27", "records": [...]}
```

### 日経寄与度

```
GET /nikkei/manifest
→ {"dates": [...], "latest_date": "2026-03-27", "generated_at": "..."}

GET /nikkei/{date}          # date: YYYY-MM-DD
→ {"date": "2026-03-27", "index": "nikkei225", "records": [...]}
```

### 株主優待

```
GET /yutai/manifest
→ {"latest_month": "2026-12", "latest_path": "2026-12.json", "months": [...]}

GET /yutai/monthly/{year_month}    # year_month: YYYY-MM
→ {"year": 2026, "month": 12, "records": [...]}
```

---

## キャッシュ

| 種別 | TTL |
|------|-----|
| manifest | 5分 |
| 日次データ | 60分 |

---

## 動作確認コマンド

```bash
curl https://market-info-api-619599800912.asia-northeast1.run.app/health
curl https://market-info-api-619599800912.asia-northeast1.run.app/ranking/manifest
curl https://market-info-api-619599800912.asia-northeast1.run.app/ranking/2026-03-27
curl https://market-info-api-619599800912.asia-northeast1.run.app/nikkei/manifest
curl https://market-info-api-619599800912.asia-northeast1.run.app/nikkei/2026-03-27
curl https://market-info-api-619599800912.asia-northeast1.run.app/yutai/manifest
curl https://market-info-api-619599800912.asia-northeast1.run.app/yutai/monthly/2026-12
```

---

## OpenAPI ドキュメント

```
https://market-info-api-619599800912.asia-northeast1.run.app/docs
```
