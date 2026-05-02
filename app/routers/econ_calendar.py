from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import cache, r2

router = APIRouter(prefix="/econ-calendar", tags=["econ-calendar"])

_LATEST_KEY = "econ-calendar/weekly/latest.json"
_META_KEY = "econ-calendar/weekly/latest_meta.json"
_MANIFEST_KEY = "econ-calendar/weekly/manifest.json"
_WEEK_START_RE = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$")


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


class EconWeeklyManifest(BaseModel):
    weeks: list[str]
    latest: str
    generated_at: str


@router.get(
    "/weekly",
    response_model=EconWeeklyLatest,
    summary="今週の経済指標カレンダーを取得",
    responses={502: {"description": "R2 からの取得失敗"}},
)
async def get_weekly() -> dict:
    """今週分の経済指標カレンダー（latest.json）を返す。

    更新単位: 平日 1日1回（01:00 UTC）。キャッシュ TTL: 6時間（可変）。
    データは 1日に 1度しか更新されないため、ポーリング不要。ページロード時の 1回取得で十分。
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
    更新単位: 平日 1日1回（01:00 UTC）。キャッシュ TTL: 6時間（可変）。
    """
    try:
        return await cache.get_manifest(
            "econ-calendar/weekly/latest_meta",
            lambda: r2.fetch_json(_META_KEY),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/weekly/manifest",
    response_model=EconWeeklyManifest,
    summary="利用可能な週一覧を取得",
    responses={502: {"description": "R2 からの取得失敗"}},
)
async def get_weekly_manifest() -> dict:
    """過去週を含む利用可能な週一覧（manifest.json）を返す。

    - `weeks`: 利用可能な week_start 日付の配列（YYYY-MM-DD、降順）
    - `latest`: 最新の week_start
    - `generated_at`: manifest 生成日時（UTC ISO 8601）

    キャッシュ TTL: 6時間（可変）。
    """
    try:
        return await cache.get_manifest(
            "econ-calendar/weekly/manifest",
            lambda: r2.fetch_json(_MANIFEST_KEY),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/weekly/{week_start}",
    response_model=EconWeeklyLatest,
    summary="指定週の経済指標カレンダーを取得",
    responses={
        404: {"description": "指定週のデータが R2 に存在しない"},
        422: {"description": "week_start が YYYY-MM-DD 形式でない"},
        502: {"description": "R2 からの取得失敗"},
    },
)
async def get_weekly_by_week(week_start: str) -> dict:
    """YYYY-MM-DD 形式の週開始日に対応する経済指標カレンダーを返す。

    404 の場合: 指定週のデータが存在しない（未取得週など）。
    422 の場合: week_start が YYYY-MM-DD 形式でない。キャッシュ TTL: 24時間（不変）。
    """
    if not _WEEK_START_RE.match(week_start):
        raise HTTPException(status_code=422, detail="week_start must be YYYY-MM-DD format")
    try:
        return await cache.get_day(
            f"econ-calendar/weekly/{week_start}",
            lambda: r2.fetch_json(f"econ-calendar/weekly/{week_start}.json"),
        )
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            raise HTTPException(status_code=404, detail=f"week not found: {week_start}") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
