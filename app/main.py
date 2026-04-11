from __future__ import annotations

from fastapi import FastAPI

from app.routers import earnings_calendar, health, market_calendar, market_rankings, nikkei, nikko, ranking, sbi, topix33, yutai

app = FastAPI(
    title="market-info-api",
    description=(
        "market_info が生成した JSON を mini-tools に提供する薄い API レイヤー。\n\n"
        "**上流**: [market_info](https://github.com/Yuichi-TanakaJP/market_info) "
        "— 日次バッチが JSON を生成し Cloudflare R2 に publish する。\n\n"
        "**下流**: [mini-tools](https://github.com/Yuichi-TanakaJP/mini-tools) "
        "— この API を呼び出してチャート・テーブルを描画する。\n\n"
        "この API 自体はデータを持たず、R2 からの取得・TTL キャッシュ・エラー変換のみを担う。"
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
