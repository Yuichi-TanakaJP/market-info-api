# GCP Cloud Run セットアップ手順

## なぜ GCP Cloud Run を選んだか

| 候補 | 結論 | 理由 |
|------|------|------|
| Railway | 見送り | トライアル期間は $5 クレジットあり、終了後の永続無料枠は $1/月のみ。常時起動サービスでは数日で枯渇する |
| Render | 見送り | 無料プランは15分無通信でスリープ、ping 等の workaround が必要 |
| **GCP Cloud Run** | **採用** | 月200万リクエストまで永続無料枠あり、スリープなし、Dockerfile そのまま使える |

Cloud Run は「リクエストがないときは課金されない（コールドスタートあり）」モデルで、mini-tools 程度のアクセス頻度では実質無料で運用できる。

---

## 前提

- Google アカウント（個人）
- GitHub リポジトリ: `Yuichi-TanakaJP/market-info-api`
- GCP プロジェクト ID: `market-info-api`
- プロジェクト番号: `619599800912`
- リージョン: `asia-northeast1` (東京)
- エンドポイント URL: `https://market-info-api-619599800912.asia-northeast1.run.app`

## 料金

- Cloud Run 永続無料枠: 月200万リクエストまで無料（トライアル終了後も継続）
- 無料トライアル: $300 クレジット / 90日間
- mini-tools 程度のアクセス頻度では無料枠を超えない見込み

---

## セットアップ手順

### 1. GCP プロジェクト作成

1. [console.cloud.google.com](https://console.cloud.google.com) にログイン
2. **New Project** → プロジェクト名 `market-info-api` で作成

### 2. Cloud Run サービス作成

1. 左メニュー → **Cloud Run** → **サービス** → **サービスの作成**
2. **「リポジトリから継続的にデプロイする」** を選択
3. **Developer Connect** を選択 → **「Developer Connect で設定」**
4. GitHub OAuth 認証 → `Yuichi-TanakaJP/market-info-api` のみ許可（Only select repositories）
5. ビルド構成:
   - ブランチ: `main`
   - ビルドタイプ: `Dockerfile`
   - ソースの場所: `/Dockerfile`

### 3. サービス構成

| 項目 | 設定値 |
|------|--------|
| サービス名 | `market-info-api` |
| リージョン | `asia-northeast1 (東京)` |
| 認証 | 公開アクセスを許可する |
| 課金 | リクエストベース |
| スケーリング | 自動（最小0、最大20） |
| コンテナポート | `8000` |
| メモリ | 512 MiB |
| CPU | 1 |

### 4. 環境変数

「コンテナ、ネットワーキング、セキュリティ」→「変数とシークレット」タブで設定:

| 変数名 | 値 |
|--------|-----|
| `R2_PUBLIC_BASE_URL` | `https://pub-b1f1de37018549c8a5ae3e6f9a7a1c6c.r2.dev` |

`/market-calendar/jpx-closed` は `market_closed/jpx_market_closed_latest.json` を固定参照するため、追加の object key 設定は不要。

---

## 権限設定（ハマりポイント）

### Cloud Build サービスアカウントへの権限付与

ビルドが `IAM_PERMISSION_DENIED` で失敗する場合、以下の手順で修正する。

**方法A: Build Trigger の画面から付与（推奨）**

1. Cloud Run サービス → **「トリガー」タブ** 下部の **「build trigger」** リンク
2. トリガー編集画面のソースセクションに黄色い警告が表示される
3. **「すべて付与」** ボタンをクリック
   - 対象: `service-619599800912@gcp-sa-cloudbuild.iam.gserviceaccount.com`
   - 付与ロール: `roles/developerconnect.tokenAccessor`

**方法B: IAM から手動付与**

1. **「IAM と管理」→「IAM」**
2. `service-619599800912@gcp-sa-cloudbuild.iam.gserviceaccount.com` を編集
3. `Developer Connect 読み取りトークン アクセサー` ロールを追加

### サービスアカウントの警告について

トリガー編集画面に「このサービスアカウントには非常に幅広い権限が付与されている」という警告が出るが、**個人プロジェクトなので無視してよい**。チームや本番環境では最小権限のサービスアカウントを別途作成すること。

---

## ビルドの手動実行

1. Cloud Run サービス → **「トリガー」タブ** → **「build trigger」**
2. トリガー一覧でトリガー右の **「▶ 実行」** をクリック

または、`main` ブランチに push すると自動でビルドが走る。

---

## 動作確認

```bash
curl https://market-info-api-619599800912.asia-northeast1.run.app/health
# → {"status": "ok"}

curl https://market-info-api-619599800912.asia-northeast1.run.app/ranking/manifest
curl https://market-info-api-619599800912.asia-northeast1.run.app/nikkei/manifest
curl https://market-info-api-619599800912.asia-northeast1.run.app/yutai/manifest
```
