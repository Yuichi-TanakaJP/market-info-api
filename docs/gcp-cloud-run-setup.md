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

無料枠と現行データ・キャッシュ容量の見積もりは [`resource-usage.md`](resource-usage.md) を参照。

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
| `YUTAI_STOCK_PRICES_PRIVATE_BUCKET` | Private R2 bucket 名 |
| `YUTAI_STOCK_PRICES_PRIVATE_ENDPOINT` | `https://<account-id>.r2.cloudflarestorage.com` |
| `YUTAI_STOCK_PRICES_PRIVATE_REGION` | `auto` |

`/market-calendar/jpx-closed` は `market_closed/jpx_market_closed_latest.json` を固定参照するため、追加の object key 設定は不要。

次の値は平文の環境変数ではなく Secret Manager から参照させる。

- `YUTAI_STOCK_PRICES_API_KEY`
- `YUTAI_STOCK_PRICES_PRIVATE_ACCESS_KEY_ID`
- `YUTAI_STOCK_PRICES_PRIVATE_SECRET_ACCESS_KEY`

R2 credentials は対象 bucket の読み取り権限だけを持つ専用tokenにする。
`YUTAI_STOCK_PRICES_API_KEY` は mini-tools backend と同じ値を設定するが、
ブラウザー向け環境変数や公開ログには記録しない。

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

## ビルドと配信の確認

通常はmain更新でCloud Buildを起動する。Actionsは手動実行のみ。
Cloud Buildも止めるコミットのスキップ指定は使わない。

承認済みの配備前に対象merge SHA・旧revision・配信設定を控える。
自動ビルドが起動しなかった場合だけ既存triggerを対象SHA固定で手動起動する。
Build成功だけで完了にせず、revisionのcommit-sha・image digest・Ready・100%配信を検査する。

```powershell
python scripts/verify_cloud_run_release.py --project market-info-api --region asia-northeast1 --service market-info-api --commit <merge-SHA> --digest <sha256:digest>
```

検査は読取専用。不一致は非0終了。続けて /health と変更対象APIの実データを確認する。
本番への人工的な更新や障害注入は不要。

通常は最新Ready revisionへ100%配信する。手動切替やrollbackの固定指定は次の配備にも残る。
本番操作の承認後、最新作成revisionが意図したSHA・digestでReadyであることと、
並行した別配備がないことを確認してから追従設定へ戻し、検査を再実行する。

```powershell
gcloud run services update-traffic market-info-api --project market-info-api --region asia-northeast1 --to-latest
```

旧revisionは削除しない。不具合時は控えた旧revisionへ `--to-revisions <old-revision>=100`
で戻しAPIを確認する。固定に戻るため次の配備で追従設定を再確認する。
リポジトリ変更だけではCloud側の設定・triggerは変更されない。

## ローカル検証とUAT

```powershell
python -m pytest tests/test_release_controls.py
python -m ruff check .
```

main反映後はpush/PRでActionsが自動起動しないことを確認する。
手動CIは必要な承認がある場合のみ実行し既存lint・test・import確認を照合する。
Cloud Buildは次の承認済みmain更新で起動・対象SHA・配信先を確認する。
確認のためだけに本番buildを起動しない。
