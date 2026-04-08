from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app import cache, r2
from app.config import JPX_CLOSED_OBJECT_KEY, US_CLOSED_OBJECT_KEY

router = APIRouter(prefix="/market-calendar", tags=["market-calendar"])


class MarketCalendarDay(BaseModel):
    date: str
    market_closed: bool
    label: str


class MarketCalendar(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    as_of_date: str
    from_: str = Field(alias="from")
    to: str
    days: list[MarketCalendarDay]


@router.get(
    "/jpx-closed",
    response_model=MarketCalendar,
    response_model_by_alias=True,
    summary="JPX 休場日カレンダーを取得",
    responses={
        404: {"description": "R2 にファイルが存在しない"},
        502: {"description": "R2 からの取得失敗"},
    },
)
async def get_jpx_closed() -> dict:
    """JPX 休場日の thin JSON を返す。

    更新単位: 不定期（年次カレンダー更新時）。
    mini-tools はこのデータを使って営業日判定を行う。
    """
    try:
        return await cache.get_manifest(
            "market-calendar/jpx-closed",
            lambda: r2.fetch_json(JPX_CLOSED_OBJECT_KEY),
        )
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            raise HTTPException(status_code=404, detail="jpx closed calendar not found") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/us-closed",
    response_model=MarketCalendar,
    response_model_by_alias=True,
    summary="US 休場日カレンダーを取得",
    responses={
        404: {"description": "R2 にファイルが存在しない"},
        502: {"description": "R2 からの取得失敗"},
    },
)
async def get_us_closed() -> dict:
    """US 休場日の thin JSON を返す。

    更新単位: 不定期（年次カレンダー更新時）。
    mini-tools はこのデータを使って営業日判定を行う。
    """
    try:
        return await cache.get_manifest(
            "market-calendar/us-closed",
            lambda: r2.fetch_json(US_CLOSED_OBJECT_KEY),
        )
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            raise HTTPException(status_code=404, detail="us closed calendar not found") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
