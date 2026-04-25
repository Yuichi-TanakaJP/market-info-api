from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app import cache, r2

router = APIRouter(prefix="/earnings-calendar", tags=["earnings-calendar"])

_OVERSEAS_PREFIX = "earnings-calendar/overseas"
_DOMESTIC_PREFIX = "earnings-calendar/domestic"
_YEAR_MONTH_RE = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])$")


class EarningsWindow(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    from_: str = Field(alias="from")
    to: str


class EarningsMonthEntry(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    year: int
    month: int
    path: str
    partial: bool
    bucket: str


class EarningsManifest(BaseModel):
    model_config = ConfigDict(extra="allow")
    as_of_date: str
    current_window: EarningsWindow
    months: list[EarningsMonthEntry]


class OverseasEarningsItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    event_id: str
    local_time: str
    ticker: str
    stock_name: str
    exchange_code: str
    fiscal_term: str
    fiscal_term_name: str
    sch_flg: str
    country_code: str


class DomesticEarningsItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    event_id: str
    time: str
    code: str
    name: str
    market: str
    announcement_type: str
    publish_status: str
    progress_status: str


class OverseasEarningsCalendarDay(BaseModel):
    model_config = ConfigDict(extra="allow")
    date: str
    count: int
    detail_status: str
    items: list[OverseasEarningsItem]


class DomesticEarningsCalendarDay(BaseModel):
    model_config = ConfigDict(extra="allow")
    date: str
    count: int
    detail_status: str
    items: list[DomesticEarningsItem]


class OverseasEarningsCalendar(BaseModel):
    model_config = ConfigDict(extra="allow")
    as_of_date: str
    calendar: list[OverseasEarningsCalendarDay]


class DomesticEarningsCalendar(BaseModel):
    model_config = ConfigDict(extra="allow")
    as_of_date: str
    calendar: list[DomesticEarningsCalendarDay]


async def _get_latest(prefix: str, label: str) -> dict:
    try:
        return await cache.get_manifest(
            f"{prefix}/latest",
            lambda: r2.fetch_json(f"{prefix}/latest.json"),
        )
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            raise HTTPException(status_code=404, detail=f"{label} earnings calendar not found") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc


async def _get_manifest(prefix: str, label: str) -> dict:
    try:
        return await cache.get_manifest(
            f"{prefix}/manifest",
            lambda: r2.fetch_json(f"{prefix}/manifest.json"),
        )
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            raise HTTPException(status_code=404, detail=f"{label} earnings calendar manifest not found") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc


async def _get_monthly(prefix: str, label: str, year_month: str) -> dict:
    if not _YEAR_MONTH_RE.match(year_month):
        raise HTTPException(status_code=422, detail="year_month must be YYYY-MM format")
    try:
        return await cache.get_day(
            f"{prefix}/monthly/{year_month}",
            lambda: r2.fetch_json(f"{prefix}/monthly/{year_month}.json"),
        )
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            raise HTTPException(status_code=404, detail=f"{label} earnings calendar not found: {year_month}") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/overseas/latest",
    response_model=OverseasEarningsCalendar,
    summary="海外決算カレンダー全件スナップショットを取得",
    responses={
        404: {"description": "R2 にファイルが存在しない"},
        502: {"description": "R2 からの取得失敗"},
    },
)
async def get_overseas_latest() -> dict:
    """海外決算カレンダー全件スナップショット (latest.json) を返す。

    全件を一括で返す。月別に分割して取得したい場合は manifest + monthly エンドポイントを使うこと。
    更新単位: 不定期（決算データ更新時）。
    """
    return await _get_latest(_OVERSEAS_PREFIX, "overseas")


@router.get(
    "/overseas/manifest",
    response_model=EarningsManifest,
    response_model_by_alias=True,
    summary="海外決算カレンダーの月別ファイル一覧を取得",
    responses={
        404: {"description": "R2 にファイルが存在しない"},
        502: {"description": "R2 からの取得失敗"},
    },
)
async def get_overseas_manifest() -> dict:
    """海外決算カレンダーの月別ファイル一覧 (manifest.json) を返す。

    - `months`: 利用可能な年月の一覧
    - `current_window`: 現在の取得ウィンドウ（from/to）
    """
    return await _get_manifest(_OVERSEAS_PREFIX, "overseas")


@router.get(
    "/overseas/monthly/{year_month}",
    response_model=OverseasEarningsCalendar,
    summary="指定月の海外決算カレンダー JSON を取得",
    responses={
        404: {"description": "指定月のデータが R2 に存在しない"},
        422: {"description": "year_month が YYYY-MM 形式でない"},
        502: {"description": "R2 からの取得失敗"},
    },
)
async def get_overseas_monthly(year_month: str) -> dict:
    """YYYY-MM 形式の月に対応する海外決算カレンダー JSON を返す。

    422 の場合: year_month が YYYY-MM 形式でない。
    404 の場合: 指定月のデータが存在しない。manifest の `months` に含まれる月のみリクエストすること。
    """
    return await _get_monthly(_OVERSEAS_PREFIX, "overseas", year_month)


@router.get(
    "/domestic/latest",
    response_model=DomesticEarningsCalendar,
    summary="国内決算カレンダー全件スナップショットを取得",
    responses={
        404: {"description": "R2 にファイルが存在しない"},
        502: {"description": "R2 からの取得失敗"},
    },
)
async def get_domestic_latest() -> dict:
    """国内決算カレンダー全件スナップショット (latest.json) を返す。

    全件を一括で返す。月別に分割して取得したい場合は manifest + monthly エンドポイントを使うこと。
    更新単位: 不定期（決算データ更新時）。
    """
    return await _get_latest(_DOMESTIC_PREFIX, "domestic")


@router.get(
    "/domestic/manifest",
    response_model=EarningsManifest,
    response_model_by_alias=True,
    summary="国内決算カレンダーの月別ファイル一覧を取得",
    responses={
        404: {"description": "R2 にファイルが存在しない"},
        502: {"description": "R2 からの取得失敗"},
    },
)
async def get_domestic_manifest() -> dict:
    """国内決算カレンダーの月別ファイル一覧 (manifest.json) を返す。

    - `months`: 利用可能な年月の一覧
    - `current_window`: 現在の取得ウィンドウ（from/to）
    """
    return await _get_manifest(_DOMESTIC_PREFIX, "domestic")


@router.get(
    "/domestic/monthly/{year_month}",
    response_model=DomesticEarningsCalendar,
    summary="指定月の国内決算カレンダー JSON を取得",
    responses={
        404: {"description": "指定月のデータが R2 に存在しない"},
        422: {"description": "year_month が YYYY-MM 形式でない"},
        502: {"description": "R2 からの取得失敗"},
    },
)
async def get_domestic_monthly(year_month: str) -> dict:
    """YYYY-MM 形式の月に対応する国内決算カレンダー JSON を返す。

    422 の場合: year_month が YYYY-MM 形式でない。
    404 の場合: 指定月のデータが存在しない。manifest の `months` に含まれる月のみリクエストすること。
    """
    return await _get_monthly(_DOMESTIC_PREFIX, "domestic", year_month)
