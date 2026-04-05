from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import cache, r2

router = APIRouter(prefix="/sbi", tags=["sbi"])

_LATEST_KEY = "sbi/credit/latest.json"
_MONTHLY_PREFIX = "sbi/credit/monthly"


@router.get("/credit/latest")
async def get_credit_latest() -> dict:
    """SBI 信用データの latest.json を返す。"""
    try:
        return await cache.get_manifest(
            "sbi/credit/latest",
            lambda: r2.fetch_json(_LATEST_KEY),
        )
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            raise HTTPException(status_code=404, detail="sbi credit latest not found") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/credit/monthly/{year_month}")
async def get_credit_monthly(year_month: str) -> dict:
    """YYYY-MM 形式の月に対応する SBI 信用データ JSON を返す。"""
    try:
        return await cache.get_day(
            f"{_MONTHLY_PREFIX}/{year_month}",
            lambda: r2.fetch_json(f"{_MONTHLY_PREFIX}/{year_month}.json"),
        )
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            raise HTTPException(status_code=404, detail=f"sbi credit not found: {year_month}") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
