from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict

from app import cache, r2

router = APIRouter(prefix="/disclosure-events", tags=["disclosure-events"])

_PREFIX = "disclosure-events"
_DATE_RE = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$")


class DisclosureEventItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    source: Literal["tdnet"]
    event_type: str
    audience: Literal["all", "personal"]
    priority: Literal["high", "medium", "low"]
    needs_review: bool
    disclosure_date: str
    disclosure_time: str
    security_code: str
    company_name: str
    title: str
    disclosure_category: str
    source_url: str
    pdf_url: str
    html_url: str
    xbrl_url: str


class DisclosureEventsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["disclosure-events-v1"]
    target_date: str
    generated_at: str
    total_count: int
    items: list[DisclosureEventItem]


class DisclosureEventsManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["disclosure-events-manifest-v1"]
    generated_at: str
    latest: str
    dates: list[str]


@router.get("/latest", response_model=DisclosureEventsPayload)
async def get_latest(response: Response) -> dict:
    """最新日の正規化済み開示イベントを返す。キャッシュTTL: 6時間。"""
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
                detail="disclosure events latest not found",
            ) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/manifest", response_model=DisclosureEventsManifest)
async def get_manifest(response: Response) -> dict:
    """利用可能な日付一覧を返す。キャッシュTTL: 6時間。"""
    response.headers["Cache-Control"] = cache.MUTABLE_HTTP_CACHE_CONTROL
    try:
        return await cache.get_manifest(
            f"{_PREFIX}/manifest",
            lambda: r2.fetch_json(f"{_PREFIX}/manifest.json"),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/{date}", response_model=DisclosureEventsPayload)
async def get_by_date(date: str, response: Response) -> dict:
    """指定日の正規化済み開示イベントを返す。キャッシュTTL: 24時間。"""
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
                detail=f"disclosure events not found: {date}",
            ) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
