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
| `/ranking/*` | 営業日ごと | market_info の日次バッチ完了後 |
| `/us-ranking/*` | 営業日ごと | 同上 |
| `/topix33/*` | 営業日ごと | 同上 |
| `/nikkei/*` | 営業日ごと | 同上 |
| `/market-calendar/jpx-closed` | 不定期（年次更新） | 休場日カレンダー更新時 |
| `/market-calendar/us-closed` | 不定期（年次更新） | 休場日カレンダー更新時 |
| `/earnings-calendar/domestic/*` | 不定期 | 決算データ更新時 |
| `/earnings-calendar/overseas/*` | 不定期 | 決算データ更新時 |
| `/edinet/document-list/*` | 平日 1日1回 | 週末・祝日は件数 0 の場合あり |
| `/tdnet/disclosures/*` | 平日 1日1回 | TDNET 全適時開示一覧。PDF は再配信せず原文 URL を返す |
| `/sbi/credit/*` | 週次 | SBI 信用残高更新に合わせて publish |
| `/nikko/credit` | 不定期 | 銘柄追加・除外時 |
| `/yutai/*` | 月次 | 月初に publish |
| `/market-rankings/market-cap/*` | 月次 | 月初に publish |
| `/market-rankings/dividend-yield/*` | 月次 | 月初に publish |

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
