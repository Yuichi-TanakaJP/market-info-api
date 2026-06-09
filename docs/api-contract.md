# API Contract

エンドポイントの仕様は `/docs`（OpenAPI）が一次情報源。  
このドキュメントは OpenAPI では表現しにくい事項のみを補記する。

---

## 3 repo の関係

```
market_info  →（R2 publish）→  market-info-api  →（HTTP）→  mini-tools
```

- **market_info**: 日次バッチが JSON を生成し Cloudflare R2 に publish する
- **market-info-api**: R2 から取得して TTL キャッシュを挟み返す薄い API レイヤー
- **mini-tools**: この API を呼び出してチャート・テーブルを描画する

---

## 横断参照入口

API contract を変更する前に、次の docs を確認する。

| 参照先 | 確認すること |
|---|---|
| [`docs/resource-usage.md`](resource-usage.md) | cache / range / search / compact publish が Cloud Run memory、R2 reads、無料枠に与える影響 |
| [`market_info/docs/architecture.md`](https://github.com/Yuichi-TanakaJP/market_info/blob/main/docs/architecture.md) | 3 repo 全体のデータフローと関連 docs |
| [`market_info/docs/reference/policy_decision_rules.md`](https://github.com/Yuichi-TanakaJP/market_info/blob/main/docs/reference/policy_decision_rules.md) | heavy / broad-range / reusable derived data をどの層に置くかの標準ルール |
| [`market_info/docs/reference/publish_contract_inventory.md`](https://github.com/Yuichi-TanakaJP/market_info/blob/main/docs/reference/publish_contract_inventory.md) | R2 published family、object path、schema source、compact artifact 候補 |
| [`mini-tools/docs/specs/cross-cutting/market-tools-data-fetch-paths.md`](https://github.com/Yuichi-TanakaJP/mini-tools/blob/main/docs/specs/cross-cutting/market-tools-data-fetch-paths.md) | UI 側が必要とする endpoint、fallback、internal route の現在仕様 |

`market-info-api` は API contract、R2 fetch、軽い request-time composition、TTL cache、query filter、HTTP error contract を担当する。広範囲で再利用される派生データは、API process-local cache だけで抱えず、`market_info` で compact artifact として R2 publish する案を先に評価する。

---

## 共通ルール

### エラーコード

| コード | 意味 | mini-tools 側の対応 |
|--------|------|---------------------|
| 404 | 指定日・月のデータが R2 に存在しない | ローカル fallback に切り替える |
| 422 | パスパラメータの形式不正 | リクエスト前にバリデーションする |
| 502 | R2 からの取得失敗（ネットワーク障害・認証エラー等） | ローカル fallback に切り替える |

### Fallback 設計

mini-tools は API が 404 / 502 / timeout を返した場合、`public/` 以下のローカル JSON に fallback する。  
API が正常時はローカル JSON を使わないこと（stale データ混入を防ぐ）。

### date パラメータの形式

`{date}` を受け付けるエンドポイントは全て **YYYY-MM-DD** 形式。  
基本的に API 側はフォーマット検証を行わず、不正な形式の場合は R2 の 404 として扱われる。  
**例外**: `/edinet/document-list/{date}` は API 側で形式を検証し、不正な場合は 422 を返す。  
クライアント側でバリデーションすること。

### year_month パラメータの形式

`{year_month}` を受け付けるエンドポイントは全て **YYYY-MM** 形式。  
`/earnings-calendar/domestic/monthly/{year_month}` と `/earnings-calendar/overseas/monthly/{year_month}` は API 側で 422 を返す。  
その他の `year_month` エンドポイントはフォーマット検証を行わない。

---

## 更新単位

| エンドポイントグループ | 更新タイミング | 備考 |
|------------------------|----------------|------|
| `/econ-calendar/weekly` | 平日 1日1回（01:00 UTC） | 実績値マージ後に publish。**ポーリング不要** |
| `/econ-calendar/weekly/meta` | 平日 1日1回（01:00 UTC） | 同上 |
| `/ranking/*` | publish 時（通常は営業日ごと想定） | market_info の日次バッチ完了後。API は manifest の実内容を正とする |
| `/ranking-enriched/*` | publish 時（通常は営業日ごと想定） | stock-ranking-enriched が publish された場合 |
| `/us-ranking/*` | publish 時（通常は営業日ごと想定） | 同上 |
| `/topix33/*` | publish 時（通常は営業日ごと想定） | 同上 |
| `/nikkei/*` | publish 時（通常は営業日ごと想定） | 同上 |
| `/market-calendar/jpx-closed` | 不定期（年次更新） | 休場日カレンダー更新時 |
| `/market-calendar/us-closed` | 不定期（年次更新） | 休場日カレンダー更新時 |
| `/earnings-calendar/domestic/*` | 不定期 | 決算データ更新時 |
| `/earnings-calendar/overseas/*` | 不定期 | 決算データ更新時 |
| `/edinet/document-list/*` | 平日 1日1回 | 週末・祝日は件数 0 の場合あり |
| `/tdnet/disclosures/*` | 平日 1日1回 | TDNET 全適時開示一覧。PDF は再配信せず原文 URL を返す |
| `/sbi/credit/*` | 週次 | SBI 信用残高更新に合わせて publish |
| `/nikko/credit` | 不定期 | 銘柄追加・除外時 |
| `/yutai/*` | 月次 | 月初に publish |
| `/stock-master/latest` | publish 時 | 銘柄マスター生成・publish 時。latest-only reference |
| `/market-rankings/market-cap/*` | 月次 | 月初に publish |
| `/market-rankings/dividend-yield/*` | 月次 | 月初に publish |
| `/investor-flow/*` | 週次 | JPX 公式 Excel 掲載後に publish |
| `/investor-flow/analysis/*` | 週次 | investor-flow raw JSON から market_info が分析サマリーを生成して publish |

---

## manifest パターン

`manifest` を持つエンドポイントは、利用可能な日付・月の一覧を返す。  
mini-tools はこの一覧を参照してから日次・月次データをリクエストすること。  
manifest に含まれない日付・月をリクエストした場合、404 が返る。

### ranking / topix33 / nikkei の manifest

```json
{
  "latest": "YYYY-MM-DD",
  "dates": ["YYYY-MM-DD", ...]
}
```

※ topix33 / nikkei は `latest_date` キーを使う（`latest` ではない）。

`/ranking-enriched/manifest` は `ranking` と同じ `latest` / `dates` shape を返す。
日次 payload は `/ranking/{date}` と同じ base record fields に、`volumeSpikePct`, `per`, `pbr`, `tickCount`, `upCount`, `downCount`, `marketCapOkuYen`, `dividendYieldPct` を追加する。

### ranking / topix33 / nikkei の range response

`/ranking/range`, `/topix33/range`, `/nikkei/range` は manifest の `dates` から `from` / `to` に含まれる source date を選び、既存の日次 payload を `items[]` に束ねて返す。
Phase 1 は `bucket=day` のみ対応する。
Full payload を返すため、Phase 1 の range は最大 31 source dates までとし、超過時は 400 を返す。
Windows Task Scheduler の予定時刻ではなく、R2 の manifest に含まれる dates/latest metadata を正として range を解決する。

```json
{
  "family": "ranking",
  "from": "2026-04-01",
  "to": "2026-04-30",
  "bucket": "day",
  "schema_version": "range-v1",
  "manifest_version": "2026-05-19T16:10:00Z",
  "source_dates": ["2026-04-30", "2026-04-28"],
  "missing": [],
  "contains_latest": true,
  "items": []
}
```

`missing[]` は将来の部分取得許容用フィールドとして維持する。
Phase 1 では、manifest に含まれる source date の取得に失敗した場合、不完全な response を cache しないため request 全体を 502 にする。
休場日など manifest に含まれない日付は `source_dates` に入らず、`missing[]` にも入れない。

range response と、その元になる日次 object cache は `manifest_version` を cache key に含める。
これにより、過去日付の object が再publishされ manifest `generated_at` が更新された場合に、古い日次 cache と新しい manifest が混在しないようにする。

### ranking search response

広範囲の UI 検索では、full payload を返す `/ranking/range` ではなく、API 側で compact search index を作って該当結果だけ返す `/ranking/search` を使う。

```text
GET /ranking/search?from=2026-04-01&to=2026-05-19&q=トヨタ
GET /ranking/search?from=2026-04-01&to=2026-05-19&code=7203
GET /ranking/search?period=90d&market=東証プライム&ranking=値上がり率
```

`period` は `Nd` 形式で、Phase 1 は最大 `366d` とする。
`from` / `to` を直接指定した場合も、選択される source dates は最大 366 件までとし、超過時は 400 を返す。

Response:

```json
{
  "family": "ranking",
  "from": "2026-04-01",
  "to": "2026-05-19",
  "schema_version": "search-v1",
  "manifest_version": "2026-05-19T16:10:00Z",
  "source_dates": ["2026-05-19", "2026-05-18"],
  "missing": [],
  "contains_latest": true,
  "query": {
    "q": "トヨタ",
    "code": null,
    "market": null,
    "ranking": null
  },
  "items": [
    {
      "date": "2026-05-19",
      "market": "東証プライム",
      "ranking": "値上がり率",
      "rank": 12,
      "name": "トヨタ自動車",
      "code": "7203",
      "price": 1234.0,
      "change": 12.0,
      "changeRate": 1.23
    }
  ]
}
```

Search index は query ごとではなく、期間と `manifest_version` ごとにキャッシュする。
検索条件は cached index に毎回適用するため、同じ期間に対する複数検索で R2 読み込みを再利用できる。

```text
search-index:ranking:{from}:{to}:search-v1:{manifest_version}
```

R2 更新時の扱い:

- manifest の `latest` / `generated_at` が変われば `manifest_version` が変わり、新しい range/search cache と日次 object cache を使う。
- 過去日付の object を再publishする場合も、manifest の `generated_at` を更新すること。
- manifest metadata が変わらない object 差し替えは API が検知できず、TTL が切れるまで古い cache を返す可能性がある。
- source date の一部取得に失敗した search index は cache しない。request 全体を 502 にする。

### yutai の manifest

```json
{
  "latest_month": "YYYY-MM",
  "latest_path": "YYYY-MM.json",
  "months": [
    {
      "year": 2026,
      "month": 12,
      "path": "2026-12.json",
      "count": 233
    }
  ]
}
```

### stock-master latest

`/stock-master/latest` は manifest を持たない latest-only reference endpoint。
`reference/stock-master/latest.json` をそのまま返す。

```json
[
  {
    "code": "7203",
    "name": "トヨタ自動車",
    "display_name": "トヨタ自動車",
    "abbrev_name": "トヨタ",
    "short_name2": null,
    "market": "プライム",
    "sector": "輸送用機器",
    "is_nikkei225": true,
    "earnings_next_date": "2026-06-10",
    "earnings_next_type": "本決算",
    "earnings_history": "2026-05-08",
    "yutai_months": null,
    "dividend_yield_pct": 2.5,
    "dividend_per_share": 117,
    "dividend_as_of": "2026-06-07",
    "as_of_date": "2026-06-08"
  }
]
```

`dividend_per_share` は `market_info` 側で `price×yield/100` から逆算した推定値。
確定配当金としては扱わない。

### market-rankings の manifest

```json
{
  "latest": "YYYY-MM",
  "months": ["YYYY-MM", ...],
  "generatedAt": "YYYY-MM-DDTHH:MM:SSZ"
}
```

### earnings-calendar の manifest

```json
{
  "as_of_date": "YYYY-MM-DD",
  "current_window": {
    "from": "YYYY-MM-DD",
    "to": "YYYY-MM-DD"
  },
  "months": [
    {
      "id": "YYYY-MM",
      "year": 2026,
      "month": 4,
      "path": "monthly/YYYY-MM.json",
      "partial": false,
      "bucket": "current"
    }
  ]
}
```

国内・海外とも同じ manifest shape を返す。

### investor-flow の manifest

```json
{
  "data_source": "JPX",
  "latest": {
    "start_date": "YYYY-MM-DD",
    "end_date": "YYYY-MM-DD",
    "path": "investor_flow_YYYY-MM-DD_to_YYYY-MM-DD.json"
  },
  "weeks": [
    {
      "start_date": "YYYY-MM-DD",
      "end_date": "YYYY-MM-DD",
      "path": "investor_flow_YYYY-MM-DD_to_YYYY-MM-DD.json"
    }
  ],
  "generated_at_jst": "YYYY-MM-DDTHH:MM:SS+09:00"
}
```

`/investor-flow/weeks/{start_date}/{end_date}` は `investor-flow/investor_flow_{start_date}_to_{end_date}.json` を読む。
`start_date` / `end_date` は YYYY-MM-DD 形式で、API 側で 422 を返す。

### investor-flow analysis の manifest

```json
{
  "data_source": "JPX",
  "schema_version": "investor-flow-analysis-v1",
  "latest": {
    "start_date": "YYYY-MM-DD",
    "end_date": "YYYY-MM-DD",
    "path": "investor_flow_analysis_YYYY-MM-DD_to_YYYY-MM-DD.json"
  },
  "weeks": [
    {
      "start_date": "YYYY-MM-DD",
      "end_date": "YYYY-MM-DD",
      "path": "investor_flow_analysis_YYYY-MM-DD_to_YYYY-MM-DD.json"
    }
  ],
  "generated_at_jst": "YYYY-MM-DDTHH:MM:SS+09:00"
}
```

`/investor-flow/analysis/latest` と `/investor-flow/analysis/weeks/{start_date}/{end_date}` は、raw JSON から生成済みの分析サマリーを返す。
API は分析計算を行わず、`investor-flow-analysis/latest.json` または
`investor-flow-analysis/investor_flow_analysis_{start_date}_to_{end_date}.json` を読む。

主な payload fields:

- `summary`: 最大買い越し・最大売り越し
- `buy_composition` / `sell_composition`: 構成比。`group` により `total` と `commission` を分ける
- `net_ranking`: 買い越し・売り越し金額の絶対値ランキング
- `reversals`: 前週から買い越し/売り越しが反転した主体
- `streaks`: 同方向の継続週数
- `major_flows`: 主要主体の買い・売り・差引

`start_date` / `end_date` は YYYY-MM-DD 形式で、API 側で 422 を返す。

---

## 認証

### 現状

現在は認証なし。Cloud Run は公開アクセス許可のため、誰でも API を叩ける。  
`app/config.py` に `MARKET_INFO_API_KEY` が定義されているが、未実装。

### 将来構想（issue #19）

`MARKET_INFO_API_KEY` 環境変数を設定することで API キー認証を有効にする予定。  
クライアントは `X-API-Key` ヘッダーにキーを付与してリクエストする。  
未設定の場合は認証なし（ローカル開発・テスト用）のまま。

mini-tools 側も合わせてキー付与の対応が必要になる。

---

## 2026-04-10 Response Validation Incident

2026-04-10 JST に、`/yutai/manifest`、`/nikko/credit`、`/nikkei/{date}` の一部で
FastAPI の response validation による 500 が発生した。

原因は `market_info` の実 payload と `market-info-api` の `response_model` の不一致。

- `/yutai/manifest`
  - 実 payload の `months` は `[{year, month, path, count}, ...]`
  - API 側は `list[str]` として定義していた
- `/nikko/credit`
  - 実 payload の `available_shares` は `int | null`
  - API 側は `int` 固定で定義していた
- `/nikkei/{date}`
  - 実 payload の `records[]` は full-universe rows で `rank` を持たない
  - API 側は `top_positive` / `top_negative` と同じ ranked item model を流用していた

混入経路:

- `33f4efc` `feat: ranking / nikkei / topix33 / sbi / nikko / yutai に response_model を追加する (#16)`
- このコミットで OpenAPI 用の `response_model` を追加した際、3 endpoint の型を簡略化しすぎた
- 同時に更新した router unit test も簡略 mock のままで、`market_info` 実 payload を通す検証になっていなかった

再発防止:

- downstream contract を持つ endpoint の `response_model` は、`market_info` の実 payload shape または source-of-truth schema に合わせる
- router unit test には、簡略 mock だけでなく `market_info` 実 artifact shape をそのまま流す回帰ケースを含める
- `extra="allow"` は未知フィールド追加には有効だが、必須 key の型違い・nullable 不一致・配列要素 shape 不一致は防げない前提でレビューする

---

## 2026-05-03 yutai R2 パス不一致調査（Claude Code による判断）

**調査日**: 2026-05-03  
**判断者**: Claude Code（claude-sonnet-4-6）  
**ステータス**: API 修正待ち（`_PREFIX` 変更で解消見込み）

### 事象

mini-tools の優待ツールが `generated_at: 2026/03/29 01:58` と古い日付を表示していた。

### 調査結果

R2 上に **2つの独立したパスが存在する**ことを確認した。

| R2 パス | manifest generated_at | 月別ファイル状態 |
|---|---|---|
| `yutai/` | 2026-05-02T12:20:54Z ✅ | 全12ヶ月 HTTP 200（05〜08は5/2更新） |
| `yutai/monthly/` | 2026-03-29T00:39:57Z ❌ | 全12ヶ月 HTTP 200（全部3/28のまま） |

- `market_info` の publish パイプラインは `YUTAI_PUBLISH_PREFIX=yutai`（システム環境変数）で動いており、**`yutai/` に正常に書き続けている**。2026-05-02にも実行済み。
- `market-info-api` の `app/routers/yutai.py` の `_PREFIX = "yutai/monthly"` が古いパスを指しているため、新しいデータが届いていない。
- `yutai/monthly/` は過去に別の prefix 設定で書かれたと推定される。現在は誰も更新していない。

### Claude Code の判断根拠

`app/routers/yutai.py:10` の `_PREFIX` を `"yutai/monthly"` → `"yutai"` に変更することを推奨する。

**根拠として確認した事実：**
1. `yutai/` に全12ヶ月（2026-01〜2026-12）が存在し全て HTTP 200 を返すことを curl で直接確認した
2. `market_info` の環境変数 `YUTAI_PUBLISH_PREFIX=yutai` が設定済みであり、今後の publish も `yutai/` に書き続ける
3. `yutai/monthly/` を更新する publish 設定は現在存在しない（放棄済みパス）

**この判断はあくまで Claude Code による調査に基づくもの。** 修正前に人間によるレビューを推奨する。

### リスク

- `yutai/` の全月データが本当に正しい内容かどうかは、ファイルの存在と `generated_at` 以上の内容検証は行っていない
- `YUTAI_PUBLISH_PREFIX` が将来変更された場合、同じ問題が再発する

---

## キャッシュ

### TTL 設計ルール

TTL はデータの**可変性**によって 2 種類に分ける。TTL はサーバー側キャッシュの話であり、クライアントのポーリング間隔とは独立した概念。

**前提**: このシステムの最短更新間隔は **1日1回（24時間）**。TTL は必ず当該データの更新間隔より短くすること（TTL ≥ 更新間隔だと古いデータを返し続ける）。

| 種別 | 定義 | TTL | 導出根拠 |
|---|---|---|---|
| **可変データ**（latest / manifest） | 次回 publish で上書きされる | **6時間** | 最短更新間隔 24時間 × 1/4。1更新サイクルで最低 4 回は新鮮なデータを取得できる |
| **不変データ**（過去日次・月次） | publish 後に内容が変わらない | **24時間** | immutable なので Cloud Run インスタンス稼働中は再取得不要 |

> この TTL 設計は market_info の publish スケジュールに依存する。**最短更新間隔が 24時間未満に変わった場合は TTL を合わせて見直すこと**。設計ルールの正本は `market_info/docs/reference/policy_decision_rules.md` を参照。

TTL の実装値は `app/cache.py` の `_MANIFEST_TTL`（21600秒）/ `_DAY_TTL`（86400秒）を参照。
range response は latest/current period を含む場合 `_MANIFEST_TTL`、過去 immutable source のみの場合 `_DAY_TTL` を使う。
search index も同じ TTL 方針を使う。
API-side cache、range/search endpoint、または新しい R2 publish artifact を追加する前に、[`resource-usage.md`](resource-usage.md) の free-tier / measured-size / checklist を確認すること。
テスト時は R2 への実リクエストをモックするか、キャッシュをクリアして確認すること。

### ポーリングについて

ポーリング間隔はクライアント側の判断。クライアントは**データの更新頻度**に基づいて決定すること（TTL ではなく）。  
全データは最短でも 1日1回の更新のため、ポーリング自体が不要なケースがほとんど。  
更新頻度は「更新単位」テーブルを参照。

### 設計根拠: `_locks` に `defaultdict` を採用した理由

`cache.py` の Lock 管理に `defaultdict(asyncio.Lock)` を使用している。

**背景**: TTL キャッシュのエントリが期限切れで消えても、Lock は自動で消えない。  
手動管理（`dict` + if チェック）では Lock が無限に蓄積するメモリリークが発生する。

**選択肢と判断**:

| 方式 | メリット | デメリット |
|------|----------|-----------|
| `dict` + if チェック（旧） | シンプル | Lock が蓄積し続ける |
| `defaultdict(asyncio.Lock)` | 生成ロジックが簡潔、race condition なし | Lock は消えない（ただし key 数に上限あり） |
| `WeakValueDictionary` | Lock が GC で回収される | 実装が複雑、このユースケースでは過剰 |

key 数は「router 数 × 日付数」で上限が実質あるため、`defaultdict` で十分と判断。
