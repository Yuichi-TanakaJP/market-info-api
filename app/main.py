from __future__ import annotations

from fastapi import FastAPI

from app.routers import (
    disclosure_events,
    earnings_calendar,
    econ_calendar,
    edinet,
    health,
    investor_flow,
    market_calendar,
    market_rankings,
    nikkei,
    nikko,
    ranking,
    ranking_enriched,
    sbi,
    stock_master,
    tdnet,
    theme_references,
    topix33,
    us_ranking,
    yutai,
    yutai_launch_display,
    yutai_stock_prices,
)

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
        "可変データ（latest / manifest 系）は **TTL 6時間**、不変データ（過去日次・月次）は **TTL 24時間**。\n\n"
        "## 更新スケジュール\n\n"
        "| エンドポイント | 更新頻度 | キャッシュ種別 |\n"
        "|---|---|---|\n"
        "| `/econ-calendar/weekly` | 平日 1日1回（01:00 UTC） | 可変（6時間） |\n"
        "| `/econ-calendar/weekly/meta` | 平日 1日1回（01:00 UTC） | 可変（6時間） |\n"
        "| `/earnings-calendar/*/latest` | 不定期（決算データ更新時） | 可変（6時間） |\n"
        "| `/earnings-calendar/*/monthly/{year_month}` | 不定期 | 不変（24時間） |\n"
        "| `/ranking/manifest` | 営業日ごと（日次バッチ後） | 可変（6時間） |\n"
        "| `/ranking/{date}` | 営業日ごと | 不変（24時間） |\n"
        "| `/ranking-enriched/manifest` | 営業日ごと（publish された場合） | 可変（6時間） |\n"
        "| `/ranking-enriched/{date}` | 営業日ごと（publish された場合） | 不変（24時間） |\n"
        "| `/nikkei/manifest` | 営業日ごと | 可変（6時間） |\n"
        "| `/nikkei/{date}` | 営業日ごと | 不変（24時間） |\n"
        "| `/topix33/manifest` | 営業日ごと | 可変（6時間） |\n"
        "| `/topix33/{date}` | 営業日ごと | 不変（24時間） |\n"
        "| `/us-ranking/manifest` | 営業日ごと（日次バッチ後） | 可変（6時間） |\n"
        "| `/us-ranking/{date}` | 営業日ごと | 不変（24時間） |\n"
        "| `/market-rankings/*/manifest` | 月次 | 可変（6時間） |\n"
        "| `/market-rankings/*/monthly/{year_month}` | 月次 | 不変（24時間） |\n"
        "| `/investor-flow/latest` | 週次 | 可変（6時間） |\n"
        "| `/investor-flow/manifest` | 週次 | 可変（6時間） |\n"
        "| `/investor-flow/weeks/{start_date}/{end_date}` | 週次 | 不変（24時間） |\n"
        "| `/investor-flow/analysis/latest` | 週次 | 可変（6時間） |\n"
        "| `/investor-flow/analysis/manifest` | 週次 | 可変（6時間） |\n"
        "| `/investor-flow/analysis/weeks/{start_date}/{end_date}` | 週次 | 不変（24時間） |\n"
        "| `/sbi/credit/latest` | 週次 | 可変（6時間） |\n"
        "| `/sbi/credit/monthly/{year_month}` | 週次 | 不変（24時間） |\n"
        "| `/nikko/credit` | 不定期 | 可変（6時間） |\n"
        "| `/yutai/manifest` | 月次 | 可変（6時間） |\n"
        "| `/yutai/monthly/{year_month}` | 月次 | 不変（24時間） |\n"
        "| `/yutai/launch-display/latest` | 月次 | 可変（6時間・private） |\n"
        "| `/yutai/launch-display/manifest` | 月次 | 可変（6時間・private） |\n"
        "| `/yutai/launch-display/monthly/{year_month}` | 月次 | 可変（6時間・private） |\n"
        "| `/yutai/stock-prices/latest` | 日次 | 可変（6時間・private） |\n"
        "| `/stock-master/latest` | publish 時 | 可変（6時間） |\n"
        "| `/market-calendar/*` | 不定期（年次更新時） | 可変（6時間） |\n"
        "| `/edinet/document-list/latest` | 平日 1日1回 | 可変（6時間） |\n"
        "| `/edinet/document-list/{date}` | 1日1回 | 不変（24時間） |\n"
        "| `/tdnet/disclosures/latest` | 平日 1日1回 | 可変（6時間） |\n"
        "| `/tdnet/disclosures/{date}` | 1日1回 | 不変（24時間） |\n"
        "| `/disclosure-events/latest`, `/manifest` | 平日 1日1回 | 可変（6時間） |\n"
        "| `/disclosure-events/{date}` | 1日1回 | 不変（24時間） |\n\n"
        "> **ポーリングはデータの更新頻度に基づいて決定すること**（キャッシュ TTL ではなく）。"
        "全データは最短でも 1日1回の更新のため、ポーリング自体が不要なケースがほとんど。"
    ),
    version="0.1.0",
)

app.include_router(health.router)
app.include_router(earnings_calendar.router)
app.include_router(ranking.router)
app.include_router(ranking_enriched.router)
app.include_router(nikkei.router)
app.include_router(sbi.router)
app.include_router(nikko.router)
app.include_router(market_calendar.router)
app.include_router(topix33.router)
app.include_router(yutai.router)
app.include_router(yutai_launch_display.router)
app.include_router(yutai_stock_prices.router)
app.include_router(stock_master.router)
app.include_router(market_rankings.router)
app.include_router(us_ranking.router)
app.include_router(edinet.router)
app.include_router(econ_calendar.router)
app.include_router(tdnet.router)
app.include_router(disclosure_events.router)
app.include_router(investor_flow.router)
app.include_router(theme_references.router)
