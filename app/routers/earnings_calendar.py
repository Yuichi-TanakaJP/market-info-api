from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException

from app import cache, r2

router = APIRouter(prefix="/earnings-calendar", tags=["earnings-calendar"])

_OVERSEAS_PREFIX = "earnings-calendar/overseas"
_YEAR_MONTH_RE = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])$")


@router.get("/overseas/latest")
async def get_overseas_latest() -> dict:
    """海外決算カレンダー全件スナップショット (latest.json) を返す。"""
    try:
        return await cache.get_manifest(
            f"{_OVERSEAS_PREFIX}/latest",
            lambda: r2.fetch_json(f"{_OVERSEAS_PREFIX}/latest.json"),
        )
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            raise HTTPException(status_code=404, detail="overseas earnings calendar not found") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/overseas/manifest")
async def get_overseas_manifest() -> dict:
    """海外決算カレンダーの月別ファイル一覧 (manifest.json) を返す。"""
    try:
        return await cache.get_manifest(
            f"{_OVERSEAS_PREFIX}/manifest",
            lambda: r2.fetch_json(f"{_OVERSEAS_PREFIX}/manifest.json"),
        )
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            raise HTTPException(status_code=404, detail="overseas earnings calendar manifest not found") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/overseas/monthly/{year_month}")
async def get_overseas_monthly(year_month: str) -> dict:
    """YYYY-MM 形式の月に対応する海外決算カレンダー JSON を返す。"""
    if not _YEAR_MONTH_RE.match(year_month):
        raise HTTPException(status_code=422, detail="year_month must be YYYY-MM format")
    try:
        return await cache.get_day(
            f"{_OVERSEAS_PREFIX}/monthly/{year_month}",
            lambda: r2.fetch_json(f"{_OVERSEAS_PREFIX}/monthly/{year_month}.json"),
        )
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            raise HTTPException(status_code=404, detail=f"overseas earnings calendar not found: {year_month}") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
