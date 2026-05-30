from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from app import cache, r2

router = APIRouter(prefix="/investor-flow", tags=["investor-flow"])

_PREFIX = "investor-flow"
_DATE_RE = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$")


class InvestorFlowWeekRef(BaseModel):
    model_config = ConfigDict(extra="allow")
    start_date: str
    end_date: str
    path: str


class InvestorFlowManifest(BaseModel):
    model_config = ConfigDict(extra="allow")
    data_source: str
    latest: InvestorFlowWeekRef
    weeks: list[InvestorFlowWeekRef]
    generated_at_jst: str


class InvestorFlowRecord(BaseModel):
    model_config = ConfigDict(extra="allow")
    row_index: int
    category: str
    sell_thousand_yen: int
    share_sell_pct: float | None
    buy_thousand_yen: int
    share_buy_pct: float | None
    diff_thousand_yen: int
    sell_yen: int
    buy_yen: int
    diff_yen: int


class InvestorFlowPayload(BaseModel):
    model_config = ConfigDict(extra="allow")
    data_source: str
    source_url: str
    source_file: str
    week_label_raw: str
    start_date: str
    end_date: str
    market_scope: str
    unit: str
    generated_at_jst: str
    records: list[InvestorFlowRecord]


@router.get(
    "/latest",
    response_model=InvestorFlowPayload,
    summary="投資主体別売買動向（最新）を取得",
    responses={
        404: {"description": "最新データが R2 に存在しない"},
        502: {"description": "R2 からの取得失敗"},
    },
)
async def get_latest() -> dict:
    """最新週の JPX 投資主体別売買動向を返す。

    更新単位: 週次。キャッシュ TTL: 6時間（可変）。
    """
    try:
        return await cache.get_manifest(
            f"{_PREFIX}/latest",
            lambda: r2.fetch_json(f"{_PREFIX}/latest.json"),
        )
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            raise HTTPException(status_code=404, detail="investor-flow latest not found") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/manifest",
    response_model=InvestorFlowManifest,
    summary="投資主体別売買動向 manifest を取得",
    responses={502: {"description": "R2 からの取得失敗"}},
)
async def get_manifest() -> dict:
    """利用可能な週次 snapshot の一覧を返す。

    キャッシュ TTL: 6時間（可変）。
    """
    try:
        return await cache.get_manifest(
            f"{_PREFIX}/manifest",
            lambda: r2.fetch_json(f"{_PREFIX}/manifest.json"),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/weeks/{start_date}/{end_date}",
    response_model=InvestorFlowPayload,
    summary="指定週の投資主体別売買動向を取得",
    responses={
        404: {"description": "指定週のデータが R2 に存在しない"},
        422: {"description": "start_date / end_date が YYYY-MM-DD 形式でない"},
        502: {"description": "R2 からの取得失敗"},
    },
)
async def get_week(start_date: str, end_date: str) -> dict:
    """YYYY-MM-DD の開始日・終了日に対応する週次 snapshot を返す。

    404 の場合: 指定週のデータが存在しない。manifest の `weeks[].path` に含まれる週のみリクエストすること。
    422 の場合: start_date / end_date が YYYY-MM-DD 形式でない。キャッシュ TTL: 24時間（不変）。
    """
    if not _DATE_RE.match(start_date) or not _DATE_RE.match(end_date):
        raise HTTPException(status_code=422, detail="start_date and end_date must be YYYY-MM-DD format")
    object_name = f"investor_flow_{start_date}_to_{end_date}.json"
    try:
        return await cache.get_day(
            f"{_PREFIX}/{start_date}/{end_date}",
            lambda: r2.fetch_json(f"{_PREFIX}/{object_name}"),
        )
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            raise HTTPException(
                status_code=404,
                detail=f"investor-flow week not found: {start_date} to {end_date}",
            ) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
