from __future__ import annotations

from typing import Literal

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from app import cache, private_r2
from app.auth import require_yutai_stock_prices_key

router = APIRouter(
    prefix="/yutai/launch-display",
    tags=["yutai-launch-display"],
)

_PREFIX = "yutai/launch-display"


class YutaiLaunchDisplayCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int = Field(ge=0)
    conditions_available: int = Field(ge=0)
    needs_normalization: int = Field(ge=0)
    auto_calculable: int = Field(ge=0)
    requires_user_valuation: int = Field(ge=0)
    excluded_from_initial_calculation: int = Field(ge=0)


class YutaiLaunchDisplayWatchStateCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    crossable: int = Field(ge=0)
    temporarily_blocked_by_sell_regulation: int = Field(ge=0)
    watch_inventory_listed: int = Field(ge=0)


class YutaiLaunchDisplayCalculationStatusCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auto_calculable: int = Field(ge=0)
    mixed_user_input_required: int = Field(ge=0)
    no_conditions: int = Field(ge=0)
    user_input_required: int = Field(ge=0)


class YutaiLaunchDisplayReadiness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    launch_ready: int = Field(ge=0)
    launch_ready_auto_calculable: int = Field(ge=0)
    launch_ready_requires_user_valuation: int = Field(ge=0)
    needs_normalization: int = Field(ge=0)


class YutaiLaunchDisplayItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    kind: Literal["discount", "goods", "money_voucher", "points", "service"]
    official_value_yen: int | None = Field(default=None, ge=0)
    valuation_policy: Literal[
        "face_value",
        "official_equivalent",
        "user_estimate_required",
    ]
    quantity: float | None = Field(default=None, ge=0)
    unit: str | None = None
    notes: str | None = None


class YutaiLaunchDisplayGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["all", "choose_one"]
    allow_repeated_choices: bool
    items: list[YutaiLaunchDisplayItem]


class YutaiLaunchDisplayTier(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minimum_shares: int = Field(ge=0)
    maximum_shares: int | None = Field(default=None, ge=0)
    required_holding_months: int = Field(ge=0)
    groups: list[YutaiLaunchDisplayGroup]


class YutaiLaunchDisplayProgram(BaseModel):
    model_config = ConfigDict(extra="forbid")

    program_id: str
    label: str
    rights_months: list[int]
    tiers: list[YutaiLaunchDisplayTier]
    notes: str | None = None


class YutaiLaunchDisplayRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    month: str
    code: str
    company_name: str
    benefit_summary: str
    minimum_investment_yen: int | None = Field(default=None, ge=0)
    official_benefit_url: str | None = None
    nikko_watch_state: Literal[
        "crossable",
        "temporarily_blocked_by_sell_regulation",
        "watch_inventory_listed",
    ]
    nikko_general_short: bool
    nikko_available_shares: int | None = Field(default=None, ge=0)
    nikko_regulation_details: str
    display_status: Literal["conditions_available", "needs_normalization"]
    calculation_status: Literal[
        "auto_calculable",
        "mixed_user_input_required",
        "no_conditions",
        "user_input_required",
    ]
    requires_user_valuation: bool
    normalized_status: str | None = None
    normalized_as_of_date: str | None = None
    normalized_source_urls: list[str]
    programs: list[YutaiLaunchDisplayProgram]
    notes: str | None = None


class YutaiLaunchDisplayLatest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    month: str
    record_count: int = Field(ge=0)
    counts: YutaiLaunchDisplayCounts
    counts_by_nikko_watch_state: YutaiLaunchDisplayWatchStateCounts
    counts_by_calculation_status: YutaiLaunchDisplayCalculationStatusCounts
    readiness: YutaiLaunchDisplayReadiness
    records: list[YutaiLaunchDisplayRecord]
    generated_at: str
    source: Literal["market_info_yutai_launch_display"]


class YutaiLaunchDisplayManifestMonth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    month: str
    path: str
    count: int = Field(ge=0)
    conditions_available: int = Field(ge=0)
    auto_calculable: int = Field(ge=0)
    requires_user_valuation: int = Field(ge=0)


class YutaiLaunchDisplayManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    generated_at: str
    source: Literal["market_info_yutai_launch_display"]
    latest_month: str
    latest_path: str
    months: list[YutaiLaunchDisplayManifestMonth]


def _private_error(status_code: int, detail: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=detail,
        headers={"Cache-Control": cache.PRIVATE_HTTP_CACHE_CONTROL},
    )


async def _fetch_private_json(cache_key: str, object_key: str) -> dict:
    try:
        return await cache.get_manifest(
            cache_key,
            lambda: private_r2.fetch_json(object_key),
        )
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in {"NoSuchKey", "NotFound"}:
            raise _private_error(404, "private yutai launch display not found") from exc
        raise _private_error(502, "private yutai launch display unavailable") from exc
    except RuntimeError as exc:
        if str(exc).startswith("missing required env var:"):
            raise _private_error(
                503,
                "private yutai launch display storage is not configured",
            ) from exc
        raise _private_error(502, "private yutai launch display unavailable") from exc
    except Exception as exc:
        raise _private_error(502, "private yutai launch display unavailable") from exc


@router.get(
    "/latest",
    response_model=YutaiLaunchDisplayLatest,
    response_model_exclude_unset=True,
    summary="Private R2から優待ローンチ表示用latestを取得",
    dependencies=[Depends(require_yutai_stock_prices_key)],
    responses={
        401: {"description": "Bearer tokenがない、または一致しない"},
        404: {"description": "Private R2にlatestが存在しない"},
        502: {"description": "Private R2からの取得失敗"},
        503: {"description": "サーバー側の認証・R2設定不足"},
    },
)
async def get_latest(response: Response) -> dict:
    response.headers["Cache-Control"] = cache.PRIVATE_HTTP_CACHE_CONTROL
    return await _fetch_private_json(
        "yutai-launch-display/latest",
        f"{_PREFIX}/latest.json",
    )


@router.get(
    "/manifest",
    response_model=YutaiLaunchDisplayManifest,
    response_model_exclude_unset=True,
    summary="Private R2から優待ローンチ表示用manifestを取得",
    dependencies=[Depends(require_yutai_stock_prices_key)],
    responses={
        401: {"description": "Bearer tokenがない、または一致しない"},
        404: {"description": "Private R2にmanifestが存在しない"},
        502: {"description": "Private R2からの取得失敗"},
        503: {"description": "サーバー側の認証・R2設定不足"},
    },
)
async def get_manifest(response: Response) -> dict:
    response.headers["Cache-Control"] = cache.PRIVATE_HTTP_CACHE_CONTROL
    return await _fetch_private_json(
        "yutai-launch-display/manifest",
        f"{_PREFIX}/manifest.json",
    )


@router.get(
    "/monthly/{year_month}",
    response_model=YutaiLaunchDisplayLatest,
    response_model_exclude_unset=True,
    summary="Private R2から指定月の優待ローンチ表示用データを取得",
    dependencies=[Depends(require_yutai_stock_prices_key)],
    responses={
        401: {"description": "Bearer tokenがない、または一致しない"},
        404: {"description": "Private R2に指定月データが存在しない"},
        502: {"description": "Private R2からの取得失敗"},
        503: {"description": "サーバー側の認証・R2設定不足"},
    },
)
async def get_monthly(year_month: str, response: Response) -> dict:
    response.headers["Cache-Control"] = cache.PRIVATE_HTTP_CACHE_CONTROL
    return await _fetch_private_json(
        f"yutai-launch-display/monthly/{year_month}",
        f"{_PREFIX}/{year_month}.json",
    )
