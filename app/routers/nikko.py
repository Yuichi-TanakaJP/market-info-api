from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import cache, r2

router = APIRouter(prefix="/nikko", tags=["nikko"])

_CREDIT_KEY = "nikko/credit/latest.json"


@router.get("/credit")
async def get_credit() -> dict:
    """日興証券の信用取引取扱銘柄情報を返す。

    by_code 辞書形式で返すので、クライアントは by_code[code] でO(1)参照できる。
    """
    try:
        return await cache.get_manifest(
            "nikko/credit",
            lambda: r2.fetch_json(_CREDIT_KEY),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
