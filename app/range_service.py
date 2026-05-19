from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app import cache

_SCHEMA_VERSION = "range-v1"
_FETCH_CONCURRENCY = 8
_MAX_RANGE_SOURCE_DATES = 31


class RangeRequestTooLarge(ValueError):
    pass


class RangeEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)
    family: str
    from_date: date = Field(alias="from")
    to_date: date = Field(alias="to")
    bucket: str
    schema_version: str
    manifest_version: str
    source_dates: list[str]
    missing: list[str]
    contains_latest: bool
    items: list[Any]


def latest_from_manifest(manifest: dict[str, Any]) -> str | None:
    for key in ("latest", "latest_date", "latest_month"):
        value = manifest.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def manifest_version(manifest: dict[str, Any]) -> str:
    for key in ("generated_at", "latest", "latest_date", "latest_month"):
        value = manifest.get(key)
        if isinstance(value, str) and value:
            return value
    return "unknown"


def select_dates(manifest: dict[str, Any], from_date: date, to_date: date) -> list[str]:
    dates = manifest.get("dates")
    if not isinstance(dates, list):
        return []

    selected: list[str] = []
    for value in dates:
        if not isinstance(value, str):
            continue
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            continue
        if from_date <= parsed <= to_date:
            selected.append(value)
    return selected


def contains_latest_date(manifest: dict[str, Any], source_dates: list[str]) -> bool:
    latest = latest_from_manifest(manifest)
    return latest in source_dates if latest else False


async def build_daily_range(
    *,
    family: str,
    from_date: date,
    to_date: date,
    manifest: dict[str, Any],
    fetch_day: Callable[[str, str], Awaitable[dict[str, Any]]],
    bucket: str = "day",
) -> dict[str, Any]:
    source_dates = select_dates(manifest, from_date, to_date)
    if len(source_dates) > _MAX_RANGE_SOURCE_DATES:
        raise RangeRequestTooLarge(
            f"range source_dates must be {_MAX_RANGE_SOURCE_DATES} or fewer; got {len(source_dates)}"
        )
    contains_latest = contains_latest_date(manifest, source_dates)
    version = manifest_version(manifest)
    cache_key = (
        f"range:{family}:{from_date.isoformat()}:{to_date.isoformat()}:"
        f"{bucket}:full:{_SCHEMA_VERSION}:{version}"
    )

    async def fetch_range() -> dict[str, Any]:
        semaphore = asyncio.Semaphore(_FETCH_CONCURRENCY)

        async def fetch_one(source_date: str) -> tuple[str, dict[str, Any]]:
            async with semaphore:
                return source_date, await fetch_day(source_date, version)

        results = await asyncio.gather(*(fetch_one(source_date) for source_date in source_dates))
        items: list[dict[str, Any]] = []
        missing: list[str] = []
        for _source_date, payload in results:
            items.append(payload)

        return {
            "family": family,
            "from_date": from_date,
            "to_date": to_date,
            "bucket": bucket,
            "schema_version": _SCHEMA_VERSION,
            "manifest_version": version,
            "source_dates": source_dates,
            "missing": missing,
            "contains_latest": contains_latest,
            "items": items,
        }

    return await cache.get_range(
        cache_key,
        contains_latest=contains_latest,
        fetch_fn=fetch_range,
    )
