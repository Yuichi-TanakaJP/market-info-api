from __future__ import annotations

from fastapi import FastAPI

from app.routers import health, nikkei, ranking, yutai

app = FastAPI(
    title="market-info-api",
    description="market_info が生成した JSON を mini-tools に提供する薄い API レイヤー。",
    version="0.1.0",
)

app.include_router(health.router)
app.include_router(ranking.router)
app.include_router(nikkei.router)
app.include_router(yutai.router)
