from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from app import cache, r2

router = APIRouter(prefix="/ranking-enriched", tags=["ranking-enriched"])

_PREFIX = "stock-ranking-enriched"


class EnrichedRankingManifest(BaseModel):
    model_config = ConfigDict(extra="allow")
    dates: list[str]
    latest: str


class EnrichedRankingRecord(BaseModel):
    model_config = ConfigDict(extra="allow")
    market: str
    ranking: str
    rank: int
    name: str
    code: str
    marketLabel: str
    industry: str
    price: float
    time: str
    change: float
    changeRate: float
    volume: float
    value: float
    volumeSpikePct: float | None
    per: float | None
    pbr: float | None
    tickCount: float | None
    upCount: float | None
    downCount: float | None
    marketCapOkuYen: float | None
    dividendYieldPct: float | None


class EnrichedRankingDay(BaseModel):
    model_config = ConfigDict(extra="allow")
    date: str
    records: list[EnrichedRankingRecord]


@router.get(
    "/manifest",
    response_model=EnrichedRankingManifest,
    summary="enriched ランキング manifest を取得",
    responses={502: {"description": "R2 からの取得失敗"}},
)
async def get_manifest() -> dict:
    """stock-ranking-enriched の manifest.json を返す。

    - `latest`: 最新日付（YYYY-MM-DD）
    - `dates`: 利用可能な日付の降順リスト

    更新単位: 営業日ごと（publish された場合）。キャッシュ TTL: 6時間（可変）。
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
    response_model=EnrichedRankingDay,
    summary="指定日の enriched ランキング JSON を取得",
    responses={
        404: {"description": "指定日のデータが R2 に存在しない（未 publish 日など）"},
        502: {"description": "R2 からの取得失敗"},
    },
)
async def get_day(date: str) -> dict:
    """YYYY-MM-DD 形式の日付に対応する enriched ranking JSON を返す。

    404 の場合: 指定日の enriched JSON が存在しない。キャッシュ TTL: 24時間（不変）。
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
            raise HTTPException(status_code=404, detail=f"ranking-enriched not found: {date}") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
