from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from app import cache, r2

router = APIRouter(prefix="/us-ranking", tags=["us-ranking"])

_PREFIX = "us-stock-ranking"


class UsRankingManifest(BaseModel):
    model_config = ConfigDict(extra="allow")
    dates: list[str]
    latest: str


class UsRankingRecord(BaseModel):
    model_config = ConfigDict(extra="allow")
    exchange: str
    ranking: str
    rank: int
    ticker: str
    listingExchange: str
    handlingFlag: str | None = None
    name: str
    nameEn: str | None = None
    price: float
    time: str
    change: float
    changeRate: float
    volume: float | None = None
    tradedValue: float | None = None
    per: float | None = None
    pbr: float | None = None


class UsRankingDay(BaseModel):
    model_config = ConfigDict(extra="allow")
    date: str
    records: list[UsRankingRecord]


@router.get(
    "/manifest",
    response_model=UsRankingManifest,
    summary="米国株ランキング manifest を取得",
    responses={502: {"description": "R2 からの取得失敗"}},
)
async def get_manifest() -> dict:
    """manifest.json を返す。

    - `latest`: 最新日付（YYYY-MM-DD）
    - `dates`: 利用可能な日付の降順リスト

    更新単位: 営業日ごと（market_info の日次バッチ完了後に R2 へ publish される）。
    """
    try:
        return await cache.get_manifest(
            f"{_PREFIX}/manifest",
            lambda: r2.fetch_json(f"{_PREFIX}/manifest.json"),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/{date}",
    response_model=UsRankingDay,
    summary="指定日の米国株ランキング JSON を取得",
    responses={
        404: {"description": "指定日のデータが R2 に存在しない（休場日・未来日・バッチ未実行日）"},
        502: {"description": "R2 からの取得失敗"},
    },
)
async def get_day(date: str) -> dict:
    """YYYY-MM-DD 形式の日付に対応する日次ランキング JSON を返す。

    - `date`: 対象日（YYYY-MM-DD）
    - `records`: 銘柄ごとのランキングデータ配列（exchange / ranking / rank / ticker ほか）

    404 の場合: 休場日・未来日・バッチ未実行日のいずれか。
    mini-tools 側は manifest の `dates` に含まれる日付のみリクエストすること。
    """
    file_key = date.replace("-", "")
    try:
        return await cache.get_day(
            f"{_PREFIX}/{file_key}",
            lambda: r2.fetch_json(f"{_PREFIX}/{file_key}.json"),
        )
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            raise HTTPException(status_code=404, detail=f"us-ranking not found: {date}") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
