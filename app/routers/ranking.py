from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import cache, r2

router = APIRouter(prefix="/ranking", tags=["ranking"])

_PREFIX = "stock-ranking"


@router.get("/latest")
async def get_latest() -> dict:
    """manifest.json を返す。latest フィールドで最新日付がわかる。"""
    try:
        return await cache.get_manifest(
            f"{_PREFIX}/manifest",
            lambda: r2.fetch_json(f"{_PREFIX}/manifest.json"),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/{date}")
async def get_day(date: str) -> dict:
    """YYYY-MM-DD 形式の日付に対応する日次ランキング JSON を返す。"""
    file_key = date.replace("-", "")
    try:
        return await cache.get_day(
            f"{_PREFIX}/{file_key}",
            lambda: r2.fetch_json(f"{_PREFIX}/{file_key}.json"),
        )
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            raise HTTPException(status_code=404, detail=f"ranking not found: {date}") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
