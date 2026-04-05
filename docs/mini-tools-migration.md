# mini-tools → market-info-api 移行手順

## 概要

現在 mini-tools は R2 に直接アクセスしてデータを取得している。
これを market-info-api 経由に切り替えることで、キャッシュ・型保証・将来の認証が使えるようになる。

market-info-api ベース URL:
```
https://market-info-api-619599800912.asia-northeast1.run.app
```

---

## 現状と変更後の比較

### stock-ranking

**現状**
- 環境変数 `STOCK_RANKING_DATA_BASE_URL` に R2 の URL を設定
- `data-loader.ts` が `{baseUrl}/manifest.json` や `{baseUrl}/{fileKey}.json` を直接 fetch

**変更後**
- 環境変数 `STOCK_RANKING_DATA_BASE_URL` を削除（または空に）
- 新しい環境変数 `MARKET_INFO_API_BASE_URL` を追加
- `data-loader.ts` のフェッチ先を以下に変更:
  - manifest: `{MARKET_INFO_API_BASE_URL}/ranking/manifest`
  - 日次データ: `{MARKET_INFO_API_BASE_URL}/ranking/{date}` （`date` は YYYY-MM-DD 形式）

**注意**: 現在の実装は `{fileKey}.json`（ハイフンなしの数字8桁）にアクセスしているが、
API は `/ranking/{date}`（YYYY-MM-DD）を受け付け、内部でファイル名変換している。
よって API に渡す日付は **YYYY-MM-DD 形式のまま**でよい。

---

### nikkei-contribution

**現状**
- 環境変数 `NIKKEI_CONTRIBUTION_DATA_BASE_URL` を参照（未設定時はハードコードされた R2 URL を使用）
- `data-loader.ts` が `nikkei_contribution_manifest.json` や `nikkei_contribution_{date}.json` を直接 fetch

**変更後**
- 環境変数 `NIKKEI_CONTRIBUTION_DATA_BASE_URL` を削除
- 新しい環境変数 `MARKET_INFO_API_BASE_URL` を追加（stock-ranking と共通）
- `data-loader.ts` のフェッチ先を以下に変更:
  - manifest: `{MARKET_INFO_API_BASE_URL}/nikkei/manifest`
  - 日次データ: `{MARKET_INFO_API_BASE_URL}/nikkei/{date}` （YYYY-MM-DD 形式）

**注意**: `data-loader.ts` にハードコードされたデフォルト R2 URL がある（6行目）。
これを削除して環境変数のみに依存するよう修正が必要。

---

### yutai-candidates

**現状**
- 環境変数 `MONTHLY_YUTAI_DATA_BASE_URL` に R2 の manifest.json URL を設定
- `data-loader.ts` が manifest を fetch してから月次データを fetch

**変更後**
- 環境変数 `MONTHLY_YUTAI_DATA_BASE_URL` を削除
- 新しい環境変数 `MARKET_INFO_API_BASE_URL` を追加（他ツールと共通）
- `data-loader.ts` のフェッチ先を以下に変更:
  - manifest: `{MARKET_INFO_API_BASE_URL}/yutai/manifest`
  - 月次データ: `{MARKET_INFO_API_BASE_URL}/yutai/monthly/{year_month}` （YYYY-MM 形式）

**注意**: 現在の実装は manifest の `latest_path` を使って月次データの URL を組み立てているが、
API 移行後は `latest_month` から直接 `/yutai/monthly/{latest_month}` で取得できる。
`data-loader.ts` のロジックを大幅に簡略化できる。

---

### 共通休場日カレンダー

**現状**
- mini-tools は公開 JSON を直接参照して JPX休場日を判定している
- 参照先は `jpx_market_closed_20260101_to_20271231.json` と同等 shape の thin JSON

**変更後**
- 取得先を `MARKET_INFO_API_BASE_URL` 配下の共通 endpoint に寄せる
- フェッチ先:
  - `{MARKET_INFO_API_BASE_URL}/market-calendar/jpx-closed`

**注意**
- API は current period filename を隠し、常に共通 endpoint を返す
- response shape は既存 thin JSON と同じ:
  - top-level: `as_of_date`, `from`, `to`, `days`
  - `days[]`: `date`, `market_closed`, `label`
- Cloud Run 側では `JPX_CLOSED_OBJECT_KEY` の設定が必要

---

## 環境変数の変更まとめ

| 環境変数 | 変更 |
|----------|------|
| `STOCK_RANKING_DATA_BASE_URL` | 削除 |
| `NIKKEI_CONTRIBUTION_DATA_BASE_URL` | 削除 |
| `MONTHLY_YUTAI_DATA_BASE_URL` | 削除 |
| `MARKET_INFO_API_BASE_URL` | **新規追加**: `https://market-info-api-619599800912.asia-northeast1.run.app` |

Vercel の環境変数設定画面で上記を変更する。

Cloud Run 側の追加設定:

| 環境変数 | 用途 |
|----------|------|
| `JPX_CLOSED_OBJECT_KEY` | `/market-calendar/jpx-closed` が参照する休場日 JSON object key |

---

## API レスポンス形式

移行後に各 data-loader.ts が受け取るレスポンスの型。

### `/ranking/manifest`
```json
{
  "dates": ["2026-03-27", "2026-03-26", ...],
  "latest": "2026-03-27"
}
```

### `/ranking/{date}`
```json
{
  "date": "2026-03-27",
  "records": [...]
}
```

### `/nikkei/manifest`
```json
{
  "dates": ["2026-03-27", ...],
  "latest_date": "2026-03-27",
  "generated_at": "2026-03-27T..."
}
```

### `/nikkei/{date}`
```json
{
  "date": "2026-03-27",
  "index": "nikkei225",
  "records": [...]
}
```

### `/yutai/manifest`
```json
{
  "latest_month": "2026-12",
  "latest_path": "2026-12.json",
  "months": [{"year": 2026, "month": 12, "path": "2026-12.json", "count": 225}, ...]
}
```

### `/yutai/monthly/{year_month}`
```json
{
  "year": 2026,
  "month": 12,
  "records": [...]
}
```

### `/market-calendar/jpx-closed`
```json
{
  "as_of_date": "2026-04-05",
  "from": "2026-01-01",
  "to": "2027-12-31",
  "days": [
    {
      "date": "2026-01-01",
      "market_closed": true,
      "label": "元日"
    }
  ]
}
```
