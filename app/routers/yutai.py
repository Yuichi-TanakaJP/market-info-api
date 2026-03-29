from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import cache, r2

router = APIRouter(prefix="/yutai", tags=["yutai"])

_PREFIX = "yutai/monthly"


@router.get("/manifest")
async def get_manifest() -> dict:
    """manifest.json を返す。latest_month / latest_path で最新月がわかる。"""
    try:
        return await cache.get_manifest(
            f"{_PREFIX}/manifest",
            lambda: r2.fetch_json(f"{_PREFIX}/manifest.json"),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/monthly/{year_month}")
async def get_month(year_month: str) -> dict:
    """YYYY-MM 形式の月に対応する優待データ JSON を返す。"""
    try:
        return await cache.get_day(
            f"{_PREFIX}/{year_month}",
            lambda: r2.fetch_json(f"{_PREFIX}/{year_month}.json"),
        )
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            raise HTTPException(status_code=404, detail=f"yutai not found: {year_month}") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
