from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app import cache, r2
from app.range_service import (
    RangeEnvelope,
    RangeRequestTooLarge,
    build_daily_range,
    contains_latest_date,
    manifest_version,
    select_dates,
)

router = APIRouter(prefix="/ranking", tags=["ranking"])

_PREFIX = "stock-ranking"


class RankingManifest(BaseModel):
    model_config = ConfigDict(extra="allow")
    dates: list[str]
    latest: str


class RankingRecord(BaseModel):
    model_config = ConfigDict(extra="allow")
    market: str
    ranking: str
    rank: int
    name: str
    code: str
    price: float
    change: float
    changeRate: float


class RankingDay(BaseModel):
    model_config = ConfigDict(extra="allow")
    date: str
    records: list[RankingRecord]


class RankingSearchItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    date: str
    market: str | None = None
    ranking: str | None = None
    rank: int | None = None
    name: str | None = None
    code: str | None = None
    price: float | None = None
    change: float | None = None
    changeRate: float | None = None


class RankingSearchQuery(BaseModel):
    q: str | None = None
    code: str | None = None
    market: str | None = None
    ranking: str | None = None


class RankingSearchEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)
    family: str
    from_date: date = Field(alias="from")
    to_date: date = Field(alias="to")
    schema_version: str
    manifest_version: str
    source_dates: list[str]
    missing: list[str]
    contains_latest: bool
    query: RankingSearchQuery
    items: list[RankingSearchItem]


_SEARCH_SCHEMA_VERSION = "search-v1"
_PERIOD_RE = re.compile(r"^(?P<days>[1-9]\d*)d$")
_MAX_SEARCH_PERIOD_DAYS = 366


def _file_key(date_str: str) -> str:
    return date_str.replace("-", "")


async def _get_day_payload(date_str: str, *, manifest_version_key: str | None = None) -> dict:
    file_key = _file_key(date_str)
    cache_key = f"{_PREFIX}/{file_key}"
    if manifest_version_key:
        cache_key = f"{cache_key}:{manifest_version_key}"
    return await cache.get_day(
        cache_key,
        lambda: r2.fetch_json(f"{_PREFIX}/{file_key}.json"),
    )


def _resolve_search_dates(
    *,
    manifest: dict,
    from_date: date | None,
    to_date: date | None,
    period: str | None,
) -> tuple[date, date]:
    if period:
        if from_date or to_date:
            raise HTTPException(status_code=400, detail="period cannot be combined with from/to")
        match = _PERIOD_RE.fullmatch(period.strip())
        if not match:
            raise HTTPException(status_code=400, detail="period must be like 30d or 90d")
        latest = manifest.get("latest")
        if not isinstance(latest, str) or not latest:
            raise HTTPException(status_code=502, detail="ranking manifest latest is missing")
        resolved_to = date.fromisoformat(latest)
        days = int(match.group("days"))
        if days > _MAX_SEARCH_PERIOD_DAYS:
            raise HTTPException(
                status_code=400,
                detail=f"period must be {_MAX_SEARCH_PERIOD_DAYS}d or less",
            )
        return resolved_to - timedelta(days=days - 1), resolved_to

    if from_date is None or to_date is None:
        raise HTTPException(status_code=400, detail="from/to or period is required")
    return from_date, to_date


def _compact_record(source_date: str, record: dict) -> dict:
    return {
        "date": source_date,
        "market": record.get("market"),
        "ranking": record.get("ranking"),
        "rank": record.get("rank"),
        "name": record.get("name"),
        "code": record.get("code"),
        "price": record.get("price"),
        "change": record.get("change"),
        "changeRate": record.get("changeRate"),
    }


def _matches_query(
    item: dict,
    *,
    q: str | None,
    code: str | None,
    market: str | None,
    ranking: str | None,
) -> bool:
    if code and str(item.get("code") or "").lower() != code.lower():
        return False
    if market and str(item.get("market") or "") != market:
        return False
    if ranking and str(item.get("ranking") or "") != ranking:
        return False
    if q:
        needle = q.lower()
        haystack = " ".join(
            str(item.get(key) or "")
            for key in ("code", "name", "market", "ranking")
        ).lower()
        if needle not in haystack:
            return False
    return True


@router.get(
    "/manifest",
    response_model=RankingManifest,
    summary="ランキング manifest を取得",
    responses={502: {"description": "R2 からの取得失敗"}},
)
async def get_manifest() -> dict:
    """manifest.json を返す。

    - `latest`: 最新日付（YYYY-MM-DD）
    - `dates`: 利用可能な日付の一覧

    更新単位: 営業日ごと（market_info の日次バッチ完了後に R2 へ publish される）。キャッシュ TTL: 6時間（可変）。
    """
    try:
        return await cache.get_manifest(
            f"{_PREFIX}/manifest",
            lambda: r2.fetch_json(f"{_PREFIX}/manifest.json"),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/range",
    response_model=RangeEnvelope,
    summary="期間内のランキング JSON をまとめて取得",
    responses={502: {"description": "R2 からの取得失敗"}},
)
async def get_range(
    from_date: date = Query(alias="from", description="開始日（YYYY-MM-DD）"),
    to_date: date = Query(alias="to", description="終了日（YYYY-MM-DD）"),
    bucket: Literal["day"] = Query(default="day", description="Phase 1 は day のみ対応"),
) -> dict:
    """manifest の `dates` から期間内の日次ランキング JSON を束ねて返す。

    range response は API 側でキャッシュされる。latest を含む range は 6時間、過去日付のみの range は 24時間。
    """
    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from must be before or equal to to")
    manifest = await get_manifest()
    try:
        return await build_daily_range(
            family="ranking",
            from_date=from_date,
            to_date=to_date,
            manifest=manifest,
            fetch_day=lambda source_date, version: _get_day_payload(
                source_date,
                manifest_version_key=version,
            ),
            bucket=bucket,
        )
    except RangeRequestTooLarge as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/search",
    response_model=RankingSearchEnvelope,
    summary="期間内のランキングを検索",
    responses={502: {"description": "R2 からの取得失敗"}},
)
async def search(
    from_date: date | None = Query(default=None, alias="from", description="開始日（YYYY-MM-DD）"),
    to_date: date | None = Query(default=None, alias="to", description="終了日（YYYY-MM-DD）"),
    period: str | None = Query(default=None, description="期間指定（例: 30d, 90d）"),
    q: str | None = Query(default=None, description="code/name/market/ranking の部分一致"),
    code: str | None = Query(default=None, description="銘柄コード完全一致"),
    market: str | None = Query(default=None, description="市場名完全一致"),
    ranking: str | None = Query(default=None, description="ランキング種別完全一致"),
) -> dict:
    """期間内の日次ランキングから compact search index を作り、該当行だけ返す。

    index と元の日次 object cache は manifest_version 付き key で管理する。
    """
    manifest = await get_manifest()
    resolved_from, resolved_to = _resolve_search_dates(
        manifest=manifest,
        from_date=from_date,
        to_date=to_date,
        period=period,
    )
    if resolved_from > resolved_to:
        raise HTTPException(status_code=400, detail="from must be before or equal to to")

    source_dates = select_dates(manifest, resolved_from, resolved_to)
    if len(source_dates) > _MAX_SEARCH_PERIOD_DAYS:
        raise HTTPException(
            status_code=400,
            detail=f"search source_dates must be {_MAX_SEARCH_PERIOD_DAYS} or fewer; got {len(source_dates)}",
        )
    contains_latest = contains_latest_date(manifest, source_dates)
    version = manifest_version(manifest)
    cache_key = (
        f"search-index:ranking:{resolved_from.isoformat()}:{resolved_to.isoformat()}:"
        f"{_SEARCH_SCHEMA_VERSION}:{version}"
    )

    async def build_index() -> dict:
        items: list[dict] = []
        for source_date in source_dates:
            payload = await _get_day_payload(source_date, manifest_version_key=version)
            for record in payload.get("records", []):
                if isinstance(record, dict):
                    items.append(_compact_record(source_date, record))
        return {"items": items, "missing": []}

    try:
        index = await cache.get_search_index(
            cache_key,
            contains_latest=contains_latest,
            fetch_fn=build_index,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    items = [
        item
        for item in index["items"]
        if _matches_query(item, q=q, code=code, market=market, ranking=ranking)
    ]
    return {
        "family": "ranking",
        "from_date": resolved_from,
        "to_date": resolved_to,
        "schema_version": _SEARCH_SCHEMA_VERSION,
        "manifest_version": version,
        "source_dates": source_dates,
        "missing": index["missing"],
        "contains_latest": contains_latest,
        "query": {"q": q, "code": code, "market": market, "ranking": ranking},
        "items": items,
    }


@router.get(
    "/{date}",
    response_model=RankingDay,
    summary="指定日のランキング JSON を取得",
    responses={
        404: {"description": "指定日のデータが R2 に存在しない（休場日・未来日・バッチ未実行日）"},
        502: {"description": "R2 からの取得失敗"},
    },
)
async def get_day(date: str) -> dict:
    """YYYY-MM-DD 形式の日付に対応する日次ランキング JSON を返す。

    - `date`: 対象日（YYYY-MM-DD）
    - `records`: 銘柄ごとのランキングデータ配列

    404 の場合: 休場日・未来日・バッチ未実行日のいずれか。キャッシュ TTL: 24時間（不変）。
    mini-tools 側は manifest の `dates` に含まれる日付のみリクエストすること。
    """
    try:
        return await _get_day_payload(date)
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            raise HTTPException(status_code=404, detail=f"ranking not found: {date}") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
