# market-info-api

market_info が生成した JSON を mini-tools に提供する薄い API レイヤー。

**上流**: [market_info](https://github.com/Yuichi-TanakaJP/market_info) — 日次バッチが JSON を生成し Cloudflare R2 に publish する  
**下流**: [mini-tools](https://github.com/Yuichi-TanakaJP/mini-tools) — この API を呼び出してチャート・テーブルを描画する

この API 自体はデータを持たず、R2 からの取得・TTL キャッシュ・エラー変換のみを担う。

---

## エンドポイント一覧

エンドポイントの詳細な仕様は **`/docs`（OpenAPI）** が一次情報源。  
404/502 の意味・更新単位・fallback 設計は [`docs/api-contract.md`](docs/api-contract.md) を参照。

| エンドポイント | 概要 |
|----------------|------|
| `GET /health` | ヘルスチェック |
| `GET /ranking/manifest` | 株価ランキング manifest |
| `GET /ranking/{date}` | 指定日のランキング JSON |
| `GET /ranking/range?from={date}&to={date}` | 期間内のランキング JSON |
| `GET /ranking/search?from={date}&to={date}` | 期間内のランキング検索 |
| `GET /ranking-enriched/manifest` | enriched 株価ランキング manifest |
| `GET /ranking-enriched/{date}` | 指定日の enriched ランキング JSON |
| `GET /topix33/manifest` | TOPIX33 manifest |
| `GET /topix33/{date}` | 指定日の TOPIX33 JSON |
| `GET /topix33/range?from={date}&to={date}` | 期間内の TOPIX33 JSON |
| `GET /nikkei/manifest` | 日経寄与度 manifest |
| `GET /nikkei/{date}` | 指定日の日経寄与度 JSON |
| `GET /nikkei/range?from={date}&to={date}` | 期間内の日経寄与度 JSON |
| `GET /market-calendar/jpx-closed` | JPX 休場日カレンダー |
| `GET /market-calendar/us-closed` | US 休場日カレンダー |
| `GET /earnings-calendar/domestic/latest` | 国内決算カレンダー（全件） |
| `GET /earnings-calendar/domestic/manifest` | 国内決算カレンダー manifest |
| `GET /earnings-calendar/domestic/monthly/{year_month}` | 指定月の国内決算カレンダー |
| `GET /earnings-calendar/overseas/latest` | 海外決算カレンダー（全件） |
| `GET /earnings-calendar/overseas/manifest` | 海外決算カレンダー manifest |
| `GET /earnings-calendar/overseas/monthly/{year_month}` | 指定月の海外決算カレンダー |
| `GET /sbi/credit/latest` | SBI 信用データ（最新） |
| `GET /sbi/credit/monthly/{year_month}` | 指定月の SBI 信用データ |
| `GET /nikko/credit` | 日興証券 信用取引取扱銘柄一覧 |
| `GET /yutai/manifest` | 優待データ manifest |
| `GET /yutai/monthly/{year_month}` | 指定月の優待データ |
| `GET /stock-master/latest` | 銘柄マスター（最新） |
| `GET /us-ranking/manifest` | 米国株ランキング manifest |
| `GET /us-ranking/{date}` | 指定日の米国株ランキング JSON |
| `GET /market-rankings/market-cap/manifest` | 時価総額ランキング manifest |
| `GET /market-rankings/market-cap/monthly/{year_month}` | 指定月の時価総額ランキング |
| `GET /market-rankings/dividend-yield/manifest` | 配当利回りランキング manifest |
| `GET /market-rankings/dividend-yield/monthly/{year_month}` | 指定月の配当利回りランキング |
| `GET /investor-flow/latest` | 投資主体別売買動向（最新） |
| `GET /investor-flow/manifest` | 投資主体別売買動向 manifest |
| `GET /investor-flow/weeks/{start_date}/{end_date}` | 指定週の投資主体別売買動向 |
| `GET /investor-flow/analysis/latest` | 投資主体別売買動向の分析サマリー（最新） |
| `GET /investor-flow/analysis/manifest` | 投資主体別売買動向の分析 manifest |
| `GET /investor-flow/analysis/weeks/{start_date}/{end_date}` | 指定週の投資主体別売買動向の分析サマリー |
| `GET /edinet/document-list/latest` | EDINET 書類一覧（最新） |
| `GET /edinet/document-list/{date}` | 指定日の EDINET 書類一覧 |
| `GET /tdnet/disclosures/latest` | TDNET 全適時開示一覧（最新） |
| `GET /tdnet/disclosures/{date}` | 指定日の TDNET 全適時開示一覧 |
| `GET /disclosure-events/latest` | 正規化済み開示イベント（最新） |
| `GET /disclosure-events/manifest` | 開示イベント日付一覧 |
| `GET /disclosure-events/{date}` | 指定日の正規化済み開示イベント |
| `GET /econ-calendar/weekly` | 今週の経済指標カレンダー |
| `GET /econ-calendar/weekly/meta` | 経済指標カレンダー更新メタ情報 |

---

## 起動方法

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

起動後、`http://localhost:8000/docs` で OpenAPI UI が確認できる。

---

## 必須環境変数

| 変数名 | 必須 | 説明 |
|--------|------|------|
| `R2_PUBLIC_BASE_URL` | 必須 | Cloudflare R2 のパブリック URL（末尾スラッシュなし） |
| `MARKET_INFO_API_KEY` | 任意 | 設定した場合、API キー認証が有効になる |

`.env` ファイルを使う場合:

```env
R2_PUBLIC_BASE_URL=https://pub-xxxx.r2.dev
MARKET_INFO_API_KEY=
```

---

## ローカル確認例

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ranking/manifest
curl http://localhost:8000/ranking/2026-04-04
curl "http://localhost:8000/ranking/range?from=2026-04-01&to=2026-04-30"
curl http://localhost:8000/ranking-enriched/manifest
curl http://localhost:8000/market-calendar/jpx-closed
curl http://localhost:8000/market-calendar/us-closed
curl http://localhost:8000/investor-flow/latest
curl http://localhost:8000/investor-flow/analysis/latest
curl http://localhost:8000/stock-master/latest
```

---

## キャッシュ

| 種別 | TTL |
|------|-----|
| 可変データ（latest / manifest 系） | 6 時間 |
| 不変データ（過去日次・月次） | 24 時間 |

インプロセスキャッシュのため、デプロイ（再起動）でリセットされる。  
TTL 設計ルールの詳細は [`docs/api-contract.md`](docs/api-contract.md) を参照。
