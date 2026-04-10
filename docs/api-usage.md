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

### TOPIX33

```
GET /topix33/manifest
→ {"dates": [...], "latest_date": "2026-04-01", "generated_at": "..."}

GET /topix33/{date}         # date: YYYY-MM-DD
→ {
    "date": "2026-04-01",
    "index": "topix33",
    "generated_at": "...",
    "summary": {"advancers": 20, "decliners": 12, "unchanged": 1},
    "top_positive": [...],
    "top_negative": [...],
    "sectors": [...]
  }
```

### 株主優待

```
GET /yutai/manifest
→ {
    "latest_month": "2026-12",
    "latest_path": "2026-12.json",
    "months": [{"year": 2026, "month": 12, "path": "2026-12.json", "count": 233}, ...]
  }

GET /yutai/monthly/{year_month}    # year_month: YYYY-MM
→ {"year": 2026, "month": 12, "records": [...]}
```

### 日興一般信用

```
GET /nikko/credit
→ {
    "date": "2026-04-04",
    "generated_at": "...",
    "record_count": 4243,
    "by_code": {...}
  }
```

### JPX休場日

```
GET /market-calendar/jpx-closed
→ {
    "as_of_date": "2026-04-05",
    "from": "2026-01-01",
    "to": "2027-12-31",
    "days": [
      {"date": "2026-01-01", "market_closed": true, "label": "元日"}
    ]
  }
```

### US休場日

```
GET /market-calendar/us-closed
→ {
    "as_of_date": "2026-04-08",
    "from": "2026-01-01",
    "to": "2027-12-31",
    "days": [
      {"date": "2026-01-01", "market_closed": true, "label": "New Year's Day"}
    ]
  }
```

---

## キャッシュ

| 種別 | TTL |
|------|-----|
| manifest | 5分 |
| 日次データ | 60分 |

## 関連環境変数

| 変数名 | 用途 |
|------|------|
| `R2_PUBLIC_BASE_URL` | 公開 JSON の取得元ベース URL |

---

## 動作確認コマンド

```bash
curl https://market-info-api-619599800912.asia-northeast1.run.app/health
curl https://market-info-api-619599800912.asia-northeast1.run.app/ranking/manifest
curl https://market-info-api-619599800912.asia-northeast1.run.app/ranking/2026-03-27
curl https://market-info-api-619599800912.asia-northeast1.run.app/nikkei/manifest
curl https://market-info-api-619599800912.asia-northeast1.run.app/nikkei/2026-03-27
curl https://market-info-api-619599800912.asia-northeast1.run.app/topix33/manifest
curl https://market-info-api-619599800912.asia-northeast1.run.app/topix33/2026-04-01
curl https://market-info-api-619599800912.asia-northeast1.run.app/yutai/manifest
curl https://market-info-api-619599800912.asia-northeast1.run.app/yutai/monthly/2026-12
curl https://market-info-api-619599800912.asia-northeast1.run.app/nikko/credit
curl https://market-info-api-619599800912.asia-northeast1.run.app/market-calendar/jpx-closed
curl https://market-info-api-619599800912.asia-northeast1.run.app/market-calendar/us-closed
```

`/market-calendar/jpx-closed` は `market_closed/jpx_market_closed_latest.json` を固定参照する。
`/market-calendar/us-closed` は `market_closed/us_market_closed_latest.json` を固定参照する。

---

## OpenAPI ドキュメント

```
https://market-info-api-619599800912.asia-northeast1.run.app/docs
```
