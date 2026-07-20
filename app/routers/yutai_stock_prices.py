from __future__ import annotations

from typing import Literal

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from app import cache, private_r2
from app.auth import require_yutai_stock_prices_key

router = APIRouter(
    prefix="/yutai/stock-prices",
    tags=["yutai-stock-prices"],
)

_LATEST_KEY = "yutai/stock-prices/latest.json"


class YutaiStockPriceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    target_months: list[str]
    status: Literal["ok", "not_found", "error"]
    price: float | None = Field(default=None, gt=0)
    price_date: str | None = None
    fetched_at: str
    error_code: str | None = None


class YutaiStockPriceLatest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    scope_month: str
    generated_at: str
    provider: str
    source_batch_dates: list[str]
    record_count: int = Field(ge=0)
    success_count: int = Field(ge=0)
    records: list[YutaiStockPriceRecord]


def _private_error(status_code: int, detail: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=detail,
        headers={"Cache-Control": cache.PRIVATE_HTTP_CACHE_CONTROL},
    )


@router.get(
    "/latest",
    response_model=YutaiStockPriceLatest,
    summary="Private R2から優待向け最新株価を取得",
    dependencies=[Depends(require_yutai_stock_prices_key)],
    responses={
        401: {"description": "Bearer tokenがない、または一致しない"},
        404: {"description": "Private R2にlatestが存在しない"},
        502: {"description": "Private R2からの取得失敗"},
        503: {"description": "サーバー側の認証・R2設定不足"},
    },
)
async def get_latest(response: Response) -> dict:
    """所有者専用の優待株価latestを返す。

    Authorization Bearer token必須。更新単位は日次、サーバーcache TTLは6時間。
    ブラウザー/CDNには保存させない。
    """
    response.headers["Cache-Control"] = cache.PRIVATE_HTTP_CACHE_CONTROL
    try:
        return await cache.get_manifest(
            "yutai-stock-prices/latest",
            lambda: private_r2.fetch_json(_LATEST_KEY),
        )
    except ClientError as exc:
        status = int(exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0))
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if status == 404 or code in {"404", "NoSuchKey", "NotFound"}:
            raise _private_error(
                404,
                "private yutai stock prices not found",
            ) from exc
        raise _private_error(502, "private stock prices unavailable") from exc
    except RuntimeError as exc:
        if str(exc).startswith("missing required env var:"):
            raise _private_error(
                503,
                "private stock-price storage is not configured",
            ) from exc
        raise _private_error(502, "private stock prices unavailable") from exc
    except Exception as exc:
        raise _private_error(502, "private stock prices unavailable") from exc
