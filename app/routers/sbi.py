from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import cache, r2

router = APIRouter(prefix="/sbi", tags=["sbi"])

_LATEST_KEY = "sbi/credit/latest.json"
_MONTHLY_PREFIX = "sbi/credit/monthly"


@router.get(
    "/credit/latest",
    summary="SBI 信用データの最新スナップショットを取得",
    responses={
        404: {"description": "R2 にファイルが存在しない"},
        502: {"description": "R2 からの取得失敗"},
    },
)
async def get_credit_latest() -> dict:
    """SBI 証券の信用取引データ latest.json を返す。

    更新単位: 週次（SBI の信用残高更新に合わせて market_info が publish）。
    """
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


@router.get(
    "/credit/monthly/{year_month}",
    summary="指定月の SBI 信用データを取得",
    responses={
        404: {"description": "指定月のデータが R2 に存在しない"},
        502: {"description": "R2 からの取得失敗"},
    },
)
async def get_credit_monthly(year_month: str) -> dict:
    """YYYY-MM 形式の月に対応する SBI 信用取引データ JSON を返す。

    - `year_month`: 対象月（YYYY-MM）
    404 の場合: 指定月のデータが存在しない。
    """
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
