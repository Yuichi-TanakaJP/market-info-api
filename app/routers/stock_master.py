from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from app import cache, r2

router = APIRouter(prefix="/stock-master", tags=["stock-master"])

_LATEST_KEY = "reference/stock-master/latest.json"


class StockMasterRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    code: str
    name: str
    display_name: str
    abbrev_name: str
    short_name2: str | None = None
    market: str
    sector: str | None = None
    is_nikkei225: bool
    earnings_next_date: str | None = None
    earnings_next_type: str | None = None
    earnings_history: str | None = None
    yutai_months: str | None = None
    dividend_yield_pct: float | None = None
    dividend_per_share: int | None = None
    dividend_as_of: str | None = None
    as_of_date: str


@router.get(
    "/latest",
    response_model=list[StockMasterRecord],
    summary="銘柄マスターの最新スナップショットを取得",
    responses={
        404: {"description": "R2 にファイルが存在しない"},
        502: {"description": "R2 からの取得失敗"},
    },
)
async def get_latest() -> list[dict]:
    """銘柄マスター latest.json を返す。

    更新単位: stock master publish 時。キャッシュ TTL: 6時間（可変）。
    mini-tools は銘柄名・市場・決算・優待・配当利回りの基盤情報として利用する。
    """
    try:
        return await cache.get_manifest(
            "stock-master/latest",
            lambda: r2.fetch_json_array(_LATEST_KEY),
        )
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            raise HTTPException(status_code=404, detail="stock master latest not found") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
