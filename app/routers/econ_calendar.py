from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import cache, r2

router = APIRouter(prefix="/econ-calendar", tags=["econ-calendar"])

_LATEST_KEY = "econ-calendar/weekly/latest.json"
_META_KEY = "econ-calendar/weekly/latest_meta.json"


class EconEvent(BaseModel):
    time: str | None = None
    area: str | None = None
    country: str | None = None
    country_tag: str | None = None
    indicator: str
    indicator_key: str | None = None
    display: str | None = None
    category: str | None = None
    impact: int | None = None
    frequency: str | None = None
    previous: str | None = None
    forecast: str | None = None
    result: str | None = None


class EconDay(BaseModel):
    date: str
    weekday_jp: str
    events: list[EconEvent]


class EconWeeklyLatest(BaseModel):
    as_of_date: str
    source: str
    week_start: str
    week_end: str
    calendar: list[EconDay]


class UnmatchedIndicator(BaseModel):
    date: str
    country: str
    indicator: str


class ActualsUpdated(BaseModel):
    date: str
    indicator: str
    field: str
    before: str | None = None
    after: str | None = None


class DiffResult(BaseModel):
    skipped: bool
    reason: str | None = None
    source_note: str | None = None
    removed_count: int | None = None
    added_count: int | None = None
    actuals_updated_count: int | None = None
    removed: list[dict] | None = None
    added: list[dict] | None = None
    actuals_updated: list[ActualsUpdated] | None = None


class EconWeeklyMeta(BaseModel):
    published_at: str
    source: str
    week_start: str
    week_end: str
    event_count: int
    matched_count: int | None = None
    unmatched_count: int | None = None
    actuals_filled: int | None = None
    unmatched_indicators: list[UnmatchedIndicator] | None = None
    diff: DiffResult | None = None


@router.get(
    "/weekly",
    response_model=EconWeeklyLatest,
    summary="今週の経済指標カレンダーを取得",
    responses={502: {"description": "R2 からの取得失敗"}},
)
async def get_weekly() -> dict:
    """今週分の経済指標カレンダー（latest.json）を返す。

    更新単位: 平日 1日1回（01:00 UTC）。キャッシュ TTL: 5分。

    **ポーリング不要** — データは 1日に 1度しか更新されない。
    ページロード時の 1回取得で十分。
    """
    try:
        return await cache.get_manifest(
            "econ-calendar/weekly/latest",
            lambda: r2.fetch_json(_LATEST_KEY),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/weekly/meta",
    response_model=EconWeeklyMeta,
    summary="今週の経済指標カレンダー更新メタ情報を取得",
    responses={502: {"description": "R2 からの取得失敗"}},
)
async def get_weekly_meta() -> dict:
    """今週分の publish メタ情報（latest_meta.json）を返す。

    diff（前回との差分）・統計カウント・未マッチ指標リストを含む。
    更新単位: 平日 1日1回（01:00 UTC）。キャッシュ TTL: 5分。
    """
    try:
        return await cache.get_manifest(
            "econ-calendar/weekly/latest_meta",
            lambda: r2.fetch_json(_META_KEY),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
