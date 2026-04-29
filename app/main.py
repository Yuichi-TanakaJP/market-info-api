from __future__ import annotations

from fastapi import FastAPI

from app.routers import earnings_calendar, econ_calendar, edinet, health, market_calendar, market_rankings, nikkei, nikko, ranking, sbi, topix33, us_ranking, yutai

app = FastAPI(
    title="market-info-api",
    description=(
        "market_info が生成した JSON を mini-tools に提供する薄い API レイヤー。\n\n"
        "**上流**: [market_info](https://github.com/Yuichi-TanakaJP/market_info) "
        "— 日次バッチが JSON を生成し Cloudflare R2 に publish する。\n\n"
        "**下流**: [mini-tools](https://github.com/Yuichi-TanakaJP/mini-tools) "
        "— この API を呼び出してチャート・テーブルを描画する。\n\n"
        "この API 自体はデータを持たず、R2 からの取得・TTL キャッシュ・エラー変換のみを担う。\n\n"
        "---\n\n"
        "## キャッシュ\n\n"
        "レスポンスはサーバー側でインメモリキャッシュされる。"
        "manifest / latest 系は **TTL 5分**、日別データは **TTL 60分**。\n\n"
        "## 更新スケジュール\n\n"
        "| エンドポイント | 更新頻度 | キャッシュ TTL |\n"
        "|---|---|---|\n"
        "| `/econ-calendar/weekly` | 平日 1日1回（01:00 UTC） | 5分 |\n"
        "| `/econ-calendar/weekly/meta` | 平日 1日1回（01:00 UTC） | 5分 |\n"
        "| `/earnings-calendar/*/latest` | 不定期（決算データ更新時） | 5分 |\n"
        "| `/earnings-calendar/*/monthly/{year_month}` | 不定期 | 60分 |\n"
        "| `/ranking/manifest` | 営業日ごと（日次バッチ後） | 5分 |\n"
        "| `/ranking/{date}` | 営業日ごと | 60分 |\n"
        "| `/nikkei/manifest` | 営業日ごと | 5分 |\n"
        "| `/nikkei/{date}` | 営業日ごと | 60分 |\n"
        "| `/topix33/manifest` | 営業日ごと | 5分 |\n"
        "| `/topix33/{date}` | 営業日ごと | 60分 |\n"
        "| `/us-ranking/manifest` | 営業日ごと（日次バッチ後） | 5分 |\n"
        "| `/us-ranking/{date}` | 営業日ごと | 60分 |\n"
        "| `/market-rankings/*/manifest` | 月次 | 5分 |\n"
        "| `/market-rankings/*/monthly/{year_month}` | 月次 | 60分 |\n"
        "| `/sbi/credit/latest` | 週次 | 5分 |\n"
        "| `/sbi/credit/monthly/{year_month}` | 週次 | 60分 |\n"
        "| `/nikko/credit` | 不定期 | 5分 |\n"
        "| `/yutai/manifest` | 月次 | 5分 |\n"
        "| `/yutai/monthly/{year_month}` | 月次 | 60分 |\n"
        "| `/market-calendar/*` | 不定期（年次更新時） | 5分 |\n"
        "| `/edinet/document-list/latest` | 平日 1日1回 | 5分 |\n"
        "| `/edinet/document-list/{date}` | 1日1回 | 60分 |\n\n"
        "> **ポーリング実装時の注意**: "
        "全データは最短でも 1日1回の更新です。"
        "キャッシュ TTL より短い間隔でポーリングしても同じレスポンスが返ります。"
        "特に `/econ-calendar/weekly` は 1日1回更新のため、**ポーリング不要** です。"
    ),
    version="0.1.0",
)

app.include_router(health.router)
app.include_router(earnings_calendar.router)
app.include_router(ranking.router)
app.include_router(nikkei.router)
app.include_router(sbi.router)
app.include_router(nikko.router)
app.include_router(market_calendar.router)
app.include_router(topix33.router)
app.include_router(yutai.router)
app.include_router(market_rankings.router)
app.include_router(us_ranking.router)
app.include_router(edinet.router)
app.include_router(econ_calendar.router)
