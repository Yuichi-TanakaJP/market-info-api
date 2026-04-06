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
| `GET /topix33/manifest` | TOPIX33 manifest |
| `GET /topix33/{date}` | 指定日の TOPIX33 JSON |
| `GET /nikkei/manifest` | 日経寄与度 manifest |
| `GET /nikkei/{date}` | 指定日の日経寄与度 JSON |
| `GET /market-calendar/jpx-closed` | JPX 休場日カレンダー |
| `GET /earnings-calendar/overseas/latest` | 海外決算カレンダー（全件） |
| `GET /earnings-calendar/overseas/manifest` | 海外決算カレンダー manifest |
| `GET /earnings-calendar/overseas/monthly/{year_month}` | 指定月の海外決算カレンダー |
| `GET /sbi/credit/latest` | SBI 信用データ（最新） |
| `GET /sbi/credit/monthly/{year_month}` | 指定月の SBI 信用データ |
| `GET /nikko/credit` | 日興証券 信用取引取扱銘柄一覧 |
| `GET /yutai/manifest` | 優待データ manifest |
| `GET /yutai/monthly/{year_month}` | 指定月の優待データ |

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
curl http://localhost:8000/market-calendar/jpx-closed
```

---

## キャッシュ

| 種別 | TTL |
|------|-----|
| manifest 系 | 5 分 |
| 日次・月次データ | 60 分 |

インプロセスキャッシュのため、デプロイ（再起動）でリセットされる。
