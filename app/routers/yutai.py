from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from app import cache, r2

router = APIRouter(prefix="/yutai", tags=["yutai"])

_PREFIX = "yutai/monthly"


class YutaiManifest(BaseModel):
    model_config = ConfigDict(extra="allow")
    latest_month: str
    latest_path: str
    months: list[str]


class YutaiRecord(BaseModel):
    model_config = ConfigDict(extra="allow")
    month: int
    code: str
    company_name: str
    benefit_summary: str
    minimum_investment_yen: int


class YutaiMonth(BaseModel):
    model_config = ConfigDict(extra="allow")
    year: int
    month: int
    records: list[YutaiRecord]


@router.get(
    "/manifest",
    response_model=YutaiManifest,
    summary="優待 manifest を取得",
    responses={502: {"description": "R2 からの取得失敗"}},
)
async def get_manifest() -> dict:
    """優待データの月別ファイル一覧 manifest.json を返す。

    - `latest_month`: 最新月（YYYY-MM）
    - `latest_path`: 最新月のファイルパス
    - `months`: 利用可能な年月の一覧

    更新単位: 月次。
    """
    try:
        return await cache.get_manifest(
            f"{_PREFIX}/manifest",
            lambda: r2.fetch_json(f"{_PREFIX}/manifest.json"),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/monthly/{year_month}",
    response_model=YutaiMonth,
    summary="指定月の優待データを取得",
    responses={
        404: {"description": "指定月のデータが R2 に存在しない"},
        502: {"description": "R2 からの取得失敗"},
    },
)
async def get_month(year_month: str) -> dict:
    """YYYY-MM 形式の月に対応する株主優待データ JSON を返す。

    - `year_month`: 対象月（YYYY-MM）
    - `records`: 優待銘柄の配列

    404 の場合: 指定月のデータが存在しない。manifest の `months` に含まれる月のみリクエストすること。
    """
    try:
        return await cache.get_day(
            f"{_PREFIX}/{year_month}",
            lambda: r2.fetch_json(f"{_PREFIX}/{year_month}.json"),
        )
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            raise HTTPException(status_code=404, detail=f"yutai not found: {year_month}") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
