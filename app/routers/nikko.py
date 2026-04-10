from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from app import cache, r2

router = APIRouter(prefix="/nikko", tags=["nikko"])

_CREDIT_KEY = "nikko/credit/latest.json"


class NikkoCreditItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    institutional_buy: bool
    institutional_short: bool
    general_buy: bool
    general_short: bool
    available_shares: int | None


class NikkoCredit(BaseModel):
    model_config = ConfigDict(extra="allow")
    date: str
    generated_at: str
    record_count: int
    by_code: dict[str, NikkoCreditItem]


@router.get(
    "/credit",
    response_model=NikkoCredit,
    summary="日興証券 信用取引取扱銘柄一覧を取得",
    responses={502: {"description": "R2 からの取得失敗"}},
)
async def get_credit() -> dict:
    """日興証券の信用取引取扱銘柄情報を返す。

    - `by_code`: 証券コードをキーとした辞書形式。クライアントは `by_code[code]` で O(1) 参照できる。

    更新単位: 不定期（銘柄追加・除外時）。
    """
    try:
        return await cache.get_manifest(
            "nikko/credit",
            lambda: r2.fetch_json(_CREDIT_KEY),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
