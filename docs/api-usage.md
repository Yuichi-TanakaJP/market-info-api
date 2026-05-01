# market-info-api 使い方

## ベース URL

```
https://market-info-api-619599800912.asia-northeast1.run.app
```

---

## エンドポイント一覧

### 経済指標カレンダー

```
GET /econ-calendar/weekly
→ {
    "as_of_date": "2026-04-29",
    "source": "sbi_week_daily+with_master",
    "week_start": "2026-04-27",
    "week_end": "2026-05-03",
    "calendar": [
      {
        "date": "2026-04-28",
        "weekday_jp": "火",
        "events": [
          {
            "time": "21:30",
            "area": "overseas",
            "country": "米国",
            "country_tag": "US",
            "indicator": "非農業部門雇用者数",
            "indicator_key": "US_NFP_REPORT",
            "display": "米雇用統計",
            "category": "employment",
            "impact": 5,
            "frequency": "月次",
            "previous": "15.1万人",
            "forecast": "17.0万人",
            "result": "17.7万人"
          }
        ]
      }
    ]
  }

GET /econ-calendar/weekly/meta
→ {
    "published_at": "2026-04-29T01:00:10Z",
    "source": "sbi_week_daily+with_master",
    "week_start": "2026-04-27",
    "week_end": "2026-05-03",
    "event_count": 48,
    "matched_count": 14,
    "unmatched_count": 34,
    "actuals_filled": 14,
    "unmatched_indicators": [...],
    "diff": {
      "skipped": false,
      "removed_count": 0,
      "added_count": 1,
      "actuals_updated_count": 3,
      ...
    }
  }
```

- 更新単位: 平日 1日1回（01:00 UTC）。**ポーリング不要**。
- `time` フィールドの timezone は JST。
- `result` が `null` の場合は未発表、文字列の場合は発表済み。
- `impact` は 1〜5 の整数（5 が最重要）。`null` の場合は重要度不明。

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

### 株式ランキング（米国）

```
GET /us-ranking/manifest
→ {"dates": ["2026-04-28", ...], "latest": "2026-04-28"}

GET /us-ranking/{date}         # date: YYYY-MM-DD
→ {
    "date": "2026-04-28",
    "records": [
      {
        "exchange": "NYSE",
        "ranking": "volume",
        "rank": 1,
        "ticker": "NVDA",
        "listingExchange": "NASDAQ",
        "handlingFlag": null,
        "name": "エヌビディア",
        "nameEn": "NVIDIA Corp",
        "price": 875.4,
        "time": "16:00",
        "change": 12.3,
        "changeRate": 1.42,
        "volume": 45000000.0,
        "tradedValue": null,
        "per": null,
        "pbr": null
      }
    ]
  }
```

### SBI 信用

```
GET /sbi/credit/latest
→ {
    "date": "2026-04-25",
    "generated_at": "...",
    "record_count": 1234,
    "by_code": {
      "1234": {
        "position_status": "可能",
        "unit_upper_limit": "3000",
        "is_hyper": false,
        "is_daily": true,
        "is_short": false,
        "is_long": true
      }
    }
  }

GET /sbi/credit/monthly/{year_month}    # year_month: YYYY-MM
→ （same shape as /sbi/credit/latest）
```

### 決算カレンダー

```
GET /earnings-calendar/overseas/latest
→ {
    "as_of_date": "2026-04-28",
    "calendar": [
      {
        "date": "2026-04-29",
        "count": 3,
        "detail_status": "full",
        "items": [
          {
            "event_id": "EV001",
            "local_time": "16:00",
            "ticker": "AAPL",
            "stock_name": "Apple Inc",
            "exchange_code": "NASDAQ",
            "fiscal_term": "2026Q1",
            "fiscal_term_name": "2026年第1四半期",
            "sch_flg": "1",
            "country_code": "US"
          }
        ]
      }
    ]
  }

GET /earnings-calendar/overseas/manifest
→ {
    "as_of_date": "2026-04-28",
    "current_window": {"from": "2026-04-01", "to": "2026-06-30"},
    "months": [{"id": "2026-04", "year": 2026, "month": 4, "path": "monthly/2026-04.json", "partial": false, "bucket": "current"}, ...]
  }

GET /earnings-calendar/overseas/monthly/{year_month}    # year_month: YYYY-MM
→ （same shape as /earnings-calendar/overseas/latest）

GET /earnings-calendar/domestic/latest
→ {
    "as_of_date": "2026-04-28",
    "calendar": [
      {
        "date": "2026-04-29",
        "count": 5,
        "detail_status": "full",
        "items": [
          {
            "event_id": "EV002",
            "time": "15:30",
            "code": "7203",
            "name": "トヨタ自動車",
            "market": "プライム",
            "announcement_type": "本決算",
            "publish_status": "確定",
            "progress_status": "発表済"
          }
        ]
      }
    ]
  }

GET /earnings-calendar/domestic/manifest
→ （same shape as overseas manifest）

GET /earnings-calendar/domestic/monthly/{year_month}    # year_month: YYYY-MM
→ （same shape as /earnings-calendar/domestic/latest）
```

### マーケットランキング

```
GET /market-rankings/market-cap/manifest
→ {"latest": "2026-04", "months": ["2026-04", ...], "generatedAt": "..."}

GET /market-rankings/market-cap/monthly/{year_month}    # year_month: YYYY-MM
→ {
    "month": "2026-04",
    "generatedAt": "2026-04-30T01:00:00Z",
    "markets": {
      "prime": {
        "date": "2026-04-30",
        "records": [
          {
            "rank": 1,
            "code": "7203",
            "name": "トヨタ自動車",
            "industry": "輸送用機器",
            "marketCapOkuYen": 350000.0,
            "price": 2800.0,
            "priceTime": "2026-04-30T15:30:00",
            "changeAmount": 30.0,
            "changeRate": 1.08,
            "dividendYieldPct": null
          }
        ]
      },
      "standard": {"date": "2026-04-30", "records": [...]},
      "growth": {"date": "2026-04-30", "records": [...]}
    }
  }

GET /market-rankings/dividend-yield/manifest
→ （same shape as market-cap manifest）

GET /market-rankings/dividend-yield/monthly/{year_month}    # year_month: YYYY-MM
→ （same shape as market-cap monthly）
```

### EDINET書類一覧

```
GET /edinet/document-list/latest
→ {
    "as_of_date": "2026-04-28",
    "total_count": 42,
    "items": [
      {
        "doc_id": "S100XXXX",
        "submit_datetime": "2026-04-28T09:00:00",
        "edinet_code": "E12345",
        "sec_code": "72030",
        "filer_name": "トヨタ自動車株式会社",
        "doc_type_code": "120",
        "doc_description": "有価証券報告書",
        "has_xbrl": true,
        "has_pdf": true,
        "has_csv": false
      }
    ]
  }

GET /edinet/document-list/{date}    # date: YYYY-MM-DD
→ （same shape as /edinet/document-list/latest）
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

| 種別 | TTL | 対象の例 |
|------|-----|---------|
| manifest / latest 系 | 6時間 | `/econ-calendar/weekly`, `*/manifest`, `*/latest` |
| 日次・月次データ | 24時間 | `*/YYYY-MM-DD`, `*/monthly/YYYY-MM` |

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
curl https://market-info-api-619599800912.asia-northeast1.run.app/us-ranking/manifest
curl https://market-info-api-619599800912.asia-northeast1.run.app/sbi/credit/latest
curl https://market-info-api-619599800912.asia-northeast1.run.app/earnings-calendar/domestic/manifest
curl https://market-info-api-619599800912.asia-northeast1.run.app/earnings-calendar/overseas/manifest
curl https://market-info-api-619599800912.asia-northeast1.run.app/market-rankings/market-cap/manifest
curl https://market-info-api-619599800912.asia-northeast1.run.app/market-rankings/dividend-yield/manifest
curl https://market-info-api-619599800912.asia-northeast1.run.app/edinet/document-list/latest
```

`/market-calendar/jpx-closed` は `market_closed/jpx_market_closed_latest.json` を固定参照する。
`/market-calendar/us-closed` は `market_closed/us_market_closed_latest.json` を固定参照する。

---

## OpenAPI ドキュメント

```
https://market-info-api-619599800912.asia-northeast1.run.app/docs
```
