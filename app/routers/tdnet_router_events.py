from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict

from app import cache, r2


router = APIRouter(prefix="/tdnet/router-events", tags=["tdnet-router-events"])

_PREFIX = "tdnet/router-events"
_DATE_RE = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$")


RouterEventType = Literal[
    "earnings_release",
    "performance_revision",
    "dividend_increase",
    "dividend_decrease",
    "dividend_change",
    "correction",
    "yutai_new",
    "yutai_expand",
    "yutai_change",
    "yutai_end",
    "yutai_review",
    "stock_split",
    "listing_regulatory",
    "share_buyback",
    "financing",
    "ma_reorganization",
    "midterm_plan",
    "governance",
]


class TdnetRouterEventItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    router_event_id: str
    tdnet_disclosure_id: str | None
    source: Literal["tdnet"]
    event_type: RouterEventType
    disclosure_date: str
    disclosure_time: str
    security_code: str
    title: str
    disclosure_category: str
    source_url: str


class TdnetRouterEventsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["tdnet-router-events-v1"]
    target_date: str
    total_count: int
    items: list[TdnetRouterEventItem]


class TdnetRouterManifestEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str
    sha256: str
    event_count: int


class TdnetRouterEventsManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["tdnet-router-events-manifest-v1"]
    generated_at: str
    latest: str
    entries: list[TdnetRouterManifestEntry]


@router.get("/latest", response_model=TdnetRouterEventsPayload)
async def get_latest(response: Response) -> dict:
    response.headers["Cache-Control"] = cache.MUTABLE_HTTP_CACHE_CONTROL
    try:
        return await cache.get_manifest(
            f"{_PREFIX}/latest",
            lambda: r2.fetch_json(f"{_PREFIX}/latest.json"),
        )
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            raise HTTPException(
                status_code=404,
                detail="tdnet router events latest not found",
            ) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/manifest", response_model=TdnetRouterEventsManifest)
async def get_manifest(response: Response) -> dict:
    response.headers["Cache-Control"] = cache.MUTABLE_HTTP_CACHE_CONTROL
    try:
        return await cache.get_manifest(
            f"{_PREFIX}/manifest",
            lambda: r2.fetch_json(f"{_PREFIX}/manifest.json"),
        )
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            raise HTTPException(
                status_code=404,
                detail="tdnet router events manifest not found",
            ) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/{date}", response_model=TdnetRouterEventsPayload)
async def get_by_date(date: str, response: Response) -> dict:
    if not _DATE_RE.match(date):
        raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD format")
    response.headers["Cache-Control"] = cache.IMMUTABLE_HTTP_CACHE_CONTROL
    try:
        return await cache.get_day(
            f"{_PREFIX}/{date}",
            lambda: r2.fetch_json(f"{_PREFIX}/{date}.json"),
        )
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            raise HTTPException(
                status_code=404,
                detail=f"tdnet router events not found: {date}",
            ) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
