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
API 側はフォーマット検証を行わず、不正な形式の場合は R2 の 404 として扱われる。  
クライアント側でバリデーションすること。

### year_month パラメータの形式

`{year_month}` を受け付けるエンドポイントは全て **YYYY-MM** 形式。  
`/earnings-calendar/overseas/monthly/{year_month}` のみ API 側で 422 を返す。  
その他の `year_month` エンドポイントはフォーマット検証を行わない。

---

## 更新単位

| エンドポイントグループ | 更新タイミング | 備考 |
|------------------------|----------------|------|
| `/ranking/*` | 営業日ごと | market_info の日次バッチ完了後 |
| `/topix33/*` | 営業日ごと | 同上 |
| `/nikkei/*` | 営業日ごと | 同上 |
| `/market-calendar/jpx-closed` | 不定期（年次更新） | 休場日カレンダー更新時 |
| `/market-calendar/us-closed` | 不定期（年次更新） | 休場日カレンダー更新時 |
| `/earnings-calendar/overseas/*` | 不定期 | 決算データ更新時 |
| `/sbi/credit/*` | 週次 | SBI 信用残高更新に合わせて publish |
| `/nikko/credit` | 不定期 | 銘柄追加・除外時 |
| `/yutai/*` | 月次 | 月初に publish |

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
  "latest_path": "yutai/monthly/YYYY-MM.json",
  "months": ["YYYY-MM", ...]
}
```

### earnings-calendar overseas の manifest

```json
{
  "latest_month": "YYYY-MM",
  "months": ["YYYY-MM", ...]
}
```

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

## キャッシュ

manifest 系・日次/月次データ系ともに TTL キャッシュが入っている。  
TTL の値は `app/cache.py` を参照。  
テスト時は R2 への実リクエストをモックするか、キャッシュをクリアして確認すること。

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
