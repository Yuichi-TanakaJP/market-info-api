from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import cache, r2

router = APIRouter(prefix="/nikkei", tags=["nikkei"])

_PREFIX = "nikkei-contribution"
_MANIFEST_FILE = "nikkei_contribution_manifest.json"


@router.get("/manifest")
async def get_manifest() -> dict:
    """nikkei_contribution_manifest.json を返す。latest_date で最新日付がわかる。"""
    try:
        return await cache.get_manifest(
            f"{_PREFIX}/manifest",
            lambda: r2.fetch_json(f"{_PREFIX}/{_MANIFEST_FILE}"),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/{date}")
async def get_day(date: str) -> dict:
    """YYYY-MM-DD 形式の日付に対応する日経寄与度 JSON を返す。"""
    file_name = f"nikkei_contribution_{date}.json"
    try:
        return await cache.get_day(
            f"{_PREFIX}/{date}",
            lambda: r2.fetch_json(f"{_PREFIX}/{file_name}"),
        )
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            raise HTTPException(status_code=404, detail=f"nikkei contribution not found: {date}") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
