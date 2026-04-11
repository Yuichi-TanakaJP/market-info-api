from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from app import cache, r2

router = APIRouter(prefix="/market-rankings", tags=["market-rankings"])


# ---------------------------------------------------------------------------
# Shared models
# ---------------------------------------------------------------------------

class MarketRankingsManifest(BaseModel):
    model_config = ConfigDict(extra="allow")
    latest: str
    months: list[str]
    generatedAt: str


class MarketRankingRecord(BaseModel):
    model_config = ConfigDict(extra="allow")
    rank: int
    code: str
    name: str
    industry: str | None = None
    marketCapOkuYen: float | None = None
    price: float | None = None
    priceTime: str | None = None
    changeAmount: float | None = None
    changeRate: float | None = None
    dividendYieldPct: float | None = None


class MarketData(BaseModel):
    model_config = ConfigDict(extra="allow")
    date: str
    records: list[MarketRankingRecord]


class MarketRankingsMonth(BaseModel):
    model_config = ConfigDict(extra="allow")
    month: str
    generatedAt: str
    markets: dict[str, MarketData]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _manifest_cache_key(prefix: str) -> str:
    return f"{prefix}/manifest"


def _month_cache_key(prefix: str, year_month: str) -> str:
    return f"{prefix}/{year_month}"


async def _get_manifest(r2_prefix: str) -> dict:
    try:
        return await cache.get_manifest(
            _manifest_cache_key(r2_prefix),
            lambda: r2.fetch_json(f"{r2_prefix}/manifest.json"),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


async def _get_month(r2_prefix: str, year_month: str) -> dict:
    try:
        return await cache.get_day(
            _month_cache_key(r2_prefix, year_month),
            lambda: r2.fetch_json(f"{r2_prefix}/{year_month}.json"),
        )
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            raise HTTPException(
                status_code=404,
                detail=f"market rankings not found: {year_month}",
            ) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Market cap endpoints
# ---------------------------------------------------------------------------

_MARKET_CAP_PREFIX = "market-rankings/market-cap"


@router.get(
    "/market-cap/manifest",
    response_model=MarketRankingsManifest,
    summary="時価総額ランキング manifest を取得",
    responses={502: {"description": "R2 からの取得失敗"}},
)
async def get_market_cap_manifest() -> dict:
    """利用可能な月の一覧を返す。

    - `latest`: 最新月（YYYY-MM）
    - `months`: 利用可能な月の降順リスト

    更新単位: 月次。
    """
    return await _get_manifest(_MARKET_CAP_PREFIX)


@router.get(
    "/market-cap/monthly/{year_month}",
    response_model=MarketRankingsMonth,
    summary="指定月の時価総額ランキングを取得（3市場統合）",
    responses={
        404: {"description": "指定月のデータが R2 に存在しない"},
        502: {"description": "R2 からの取得失敗"},
    },
)
async def get_market_cap_month(year_month: str) -> dict:
    """YYYY-MM 形式の月に対応する時価総額ランキング JSON を返す。

    - `month`: 対象月（YYYY-MM）
    - `markets.prime / standard / growth`: 各市場の上位 100 件

    404 の場合: 指定月のデータが存在しない。manifest の `months` に含まれる月のみリクエストすること。
    """
    return await _get_month(_MARKET_CAP_PREFIX, year_month)


# ---------------------------------------------------------------------------
# Dividend yield endpoints
# ---------------------------------------------------------------------------

_DIVIDEND_YIELD_PREFIX = "market-rankings/dividend-yield"


@router.get(
    "/dividend-yield/manifest",
    response_model=MarketRankingsManifest,
    summary="配当利回りランキング manifest を取得",
    responses={502: {"description": "R2 からの取得失敗"}},
)
async def get_dividend_yield_manifest() -> dict:
    """利用可能な月の一覧を返す。

    - `latest`: 最新月（YYYY-MM）
    - `months`: 利用可能な月の降順リスト

    更新単位: 月次。
    """
    return await _get_manifest(_DIVIDEND_YIELD_PREFIX)


@router.get(
    "/dividend-yield/monthly/{year_month}",
    response_model=MarketRankingsMonth,
    summary="指定月の配当利回りランキングを取得（3市場統合）",
    responses={
        404: {"description": "指定月のデータが R2 に存在しない"},
        502: {"description": "R2 からの取得失敗"},
    },
)
async def get_dividend_yield_month(year_month: str) -> dict:
    """YYYY-MM 形式の月に対応する配当利回りランキング JSON を返す。

    - `month`: 対象月（YYYY-MM）
    - `markets.prime / standard / growth`: 各市場の上位 100 件

    404 の場合: 指定月のデータが存在しない。manifest の `months` に含まれる月のみリクエストすること。
    """
    return await _get_month(_DIVIDEND_YIELD_PREFIX, year_month)
