"""Read the owner's unified Japanese stock-price snapshots."""

from datetime import date
from hmac import compare_digest
from typing import Annotated, Literal

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator

from app import config, private_r2

ROUTE_PREFIX = "/stock-prices"
router = APIRouter(prefix=ROUTE_PREFIX, tags=["private-stock-prices"])
_bearer = HTTPBearer(auto_error=False)
_CODE = r"^[0-9][0-9A-Z]{3,4}$"
_ISO_DAY = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"


async def require_key(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer)],
) -> None:
    expected = config.STOCK_PRICES_API_KEY
    if not expected:
        raise HTTPException(503, "stock price authentication is not configured")
    if credentials is None or not compare_digest(
        credentials.credentials.encode(), expected.encode()
    ):
        raise HTTPException(401, "invalid or missing bearer token", {"WWW-Authenticate": "Bearer"})


class StockPrice(BaseModel):
    code: str = Field(pattern=_CODE)
    price_jpy: float = Field(strict=True, gt=0, allow_inf_nan=False)


class StockPrices(BaseModel):
    schema_version: Literal[1]
    trading_date: str = Field(pattern=_ISO_DAY)
    revision: int = Field(strict=True, ge=1)
    records: list[StockPrice] = Field(min_length=1)

    @field_validator("schema_version", mode="before")
    @classmethod
    def validate_version(cls, value):
        if type(value) is not int:
            raise ValueError("an integer schema version is required")
        return value

    @field_validator("trading_date")
    @classmethod
    def validate_date(cls, value: str) -> str:
        return date.fromisoformat(value).isoformat()

    @field_validator("records")
    @classmethod
    def validate_codes(cls, records: list[StockPrice]) -> list[StockPrice]:
        if len({record.code for record in records}) != len(records):
            raise ValueError("duplicate stock code")
        return records


_RESPONSES = {
    401: {"description": "専用 Bearer token がない、または一致しない"},
    404: {"description": "指定のスナップショットが未保存"},
    502: {"description": "Private R2 の読取り失敗、または保存データが不正"},
    503: {"description": "認証または Private R2 が未設定"},
}
CodeQuery = Annotated[str | None, Query(pattern=_CODE, description="銘柄コードで絞り込む")]


async def _read_snapshot(key: str, code: str | None, expected_date: str | None = None) -> dict:
    try:
        snapshot = StockPrices.model_validate(await private_r2.fetch_stock_prices_json(key))
        if expected_date is not None and snapshot.trading_date != expected_date:
            raise ValueError("private snapshot date mismatch")
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "NotFound"}:
            raise HTTPException(404, "stock price snapshot not found") from None
        raise HTTPException(502, "private stock prices unavailable") from None
    except private_r2.StockPriceStorageNotConfigured:
        raise HTTPException(503, "private stock price storage is not configured") from None
    except Exception:
        raise HTTPException(502, "private stock prices unavailable or invalid") from None

    result = snapshot.model_dump()
    if code is not None:
        result["records"] = [record for record in result["records"] if record["code"] == code]
    return result


class StockPricesResponse(StockPrices):
    # A code lookup can match no record in an otherwise valid snapshot.
    records: list[StockPrice]


@router.get(
    "/latest",
    response_model=StockPricesResponse,
    summary="統合株価の最新スナップショットを取得",
    dependencies=[Depends(require_key)],
    responses=_RESPONSES,
)
async def latest(code: CodeQuery = None) -> dict:
    """Private R2 の最新の検証済み取引日・版を返す。"""
    return await _read_snapshot("stock-prices/latest.json", code)


@router.get(
    "/{trading_date}",
    response_model=StockPricesResponse,
    summary="指定取引日の統合株価を取得",
    dependencies=[Depends(require_key)],
    responses={**_RESPONSES, 422: {"description": "日付または銘柄コードの形式が不正"}},
)
async def daily(trading_date: Annotated[str, Path(pattern=_ISO_DAY)], code: CodeQuery = None) -> dict:
    """日付別スナップショットの現行版を返す。最新データへのフォールバックはしない。"""
    try:
        requested_date = date.fromisoformat(trading_date).isoformat()
    except ValueError:
        raise HTTPException(422, "invalid trading date") from None
    return await _read_snapshot(f"stock-prices/daily/{requested_date}.json", code, requested_date)
