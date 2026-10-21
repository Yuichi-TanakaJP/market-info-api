from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from app import cache, r2
from app.market_observation import MarketObservation, MarketSnapshot, fetch_observation_day
from app.range_service import RangeEnvelope, RangeRequestTooLarge, build_daily_range

router = APIRouter(prefix="/nikkei", tags=["nikkei"])

_PREFIX = "nikkei-contribution"
_MANIFEST_FILE = "nikkei_contribution_manifest.json"


class NikkeiManifest(BaseModel):
    snapshots: dict[str, MarketSnapshot] = {}
    observation: MarketObservation | None = None
    latest_market_observation: MarketSnapshot | None = None
    model_config = ConfigDict(extra="allow")
    dates: list[str]
    latest_date: str


class NikkeiSummary(BaseModel):
    total_contribution: float
    advancers: int
    decliners: int
    unchanged: int


class NikkeiContributionItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    rank: int
    code: str
    name: str
    contribution: float
    chg_pct: float
    weight_pct: float


class NikkeiRecord(BaseModel):
    model_config = ConfigDict(extra="allow")
    code: str
    name: str
    contribution: float
    chg_pct: float
    weight_pct: float


class NikkeiDay(BaseModel):
    observation: MarketObservation | None = None
    model_config = ConfigDict(extra="allow")
    date: str
    index: str
    summary: NikkeiSummary
    top_positive: list[NikkeiContributionItem]
    top_negative: list[NikkeiContributionItem]
    records: list[NikkeiRecord]


async def _get_day_payload(date_str: str, *, manifest_version_key: str | None = None, captured_manifest: dict | None = None) -> dict:
    file_name = f"nikkei_contribution_{date_str}.json"
    manifest = captured_manifest if captured_manifest is not None else await get_manifest()
    return await fetch_observation_day(
        prefix=_PREFIX, file_name=file_name, date_str=date_str, manifest=manifest,
        manifest_version_key=manifest_version_key,
    )


@router.get(
    "/manifest",
    response_model=NikkeiManifest,
    summary="日経寄与度 manifest を取得",
    responses={502: {"description": "R2 からの取得失敗"}},
)
async def get_manifest() -> dict:
    """nikkei_contribution_manifest.json を返す。

    - `latest_date`: 最新日付（YYYY-MM-DD）
    - `dates`: 利用可能な日付の一覧

    更新単位: 営業日ごと。キャッシュ TTL: 6時間（可変）。
    """
    try:
        return await cache.get_manifest(
            f"{_PREFIX}/manifest",
            lambda: r2.fetch_json(f"{_PREFIX}/{_MANIFEST_FILE}"),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/range",
    response_model=RangeEnvelope,
    summary="期間内の日経寄与度 JSON をまとめて取得",
    responses={502: {"description": "R2 からの取得失敗"}},
)
async def get_range(
    from_date: date = Query(alias="from", description="開始日（YYYY-MM-DD）"),
    to_date: date = Query(alias="to", description="終了日（YYYY-MM-DD）"),
    bucket: Literal["day"] = Query(default="day", description="Phase 1 は day のみ対応"),
) -> dict:
    """manifest の `dates` から期間内の日経寄与度 JSON を束ねて返す。

    range response は API 側でキャッシュされる。latest を含む range は 6時間、過去日付のみの range は 24時間。
    """
    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from must be before or equal to to")
    manifest = await get_manifest()
    try:
        return await build_daily_range(
            family="nikkei",
            from_date=from_date,
            to_date=to_date,
            manifest=manifest,
            fetch_day=lambda source_date, version: _get_day_payload(
                source_date,
                manifest_version_key=version, captured_manifest=manifest,
            ),
            bucket=bucket,
        )
    except RangeRequestTooLarge as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/{date}",
    response_model=NikkeiDay,
    summary="指定日の日経寄与度 JSON を取得",
    responses={
        404: {"description": "指定日のデータが R2 に存在しない"},
        502: {"description": "R2 からの取得失敗"},
    },
)
async def get_day(date: str) -> dict:
    """YYYY-MM-DD 形式の日付に対応する日経平均寄与度 JSON を返す。

    - `date`: 対象日（YYYY-MM-DD）
    - `records`: 銘柄ごとの寄与度データ配列

    404 の場合: 休場日・未来日・バッチ未実行日のいずれか。キャッシュ TTL: 24時間（不変）。
    """
    try:
        return await _get_day_payload(date)
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            raise HTTPException(status_code=404, detail=f"nikkei contribution not found: {date}") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
