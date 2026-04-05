from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import cache, r2
from app.config import JPX_CLOSED_OBJECT_KEY

router = APIRouter(prefix="/market-calendar", tags=["market-calendar"])


@router.get("/jpx-closed")
async def get_jpx_closed() -> dict:
    """JPX休場日 thin JSON を返す。"""
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
