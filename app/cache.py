from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Awaitable, Callable

from cachetools import TTLCache

_MANIFEST_TTL = 21600  # 6時間（可変データ）
_DAY_TTL = 86400  # 24時間（不変データ）

MUTABLE_HTTP_CACHE_CONTROL = "public, max-age=300"
IMMUTABLE_HTTP_CACHE_CONTROL = "public, max-age=31536000, immutable"
PRIVATE_HTTP_CACHE_CONTROL = "private, no-store"

_manifest_cache: TTLCache = TTLCache(maxsize=16, ttl=_MANIFEST_TTL)
_day_cache: TTLCache = TTLCache(maxsize=128, ttl=_DAY_TTL)
_range_current_cache: TTLCache = TTLCache(maxsize=64, ttl=_MANIFEST_TTL)
_range_past_cache: TTLCache = TTLCache(maxsize=64, ttl=_DAY_TTL)
_search_index_current_cache: TTLCache = TTLCache(maxsize=128, ttl=_MANIFEST_TTL)
_search_index_past_cache: TTLCache = TTLCache(maxsize=128, ttl=_DAY_TTL)

_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


def _lock_for(key: str) -> asyncio.Lock:
    return _locks[key]


async def get_or_fetch(
    cache: TTLCache,
    key: str,
    fetch_fn: Callable[[], Awaitable[Any]],
) -> Any:
    if key in cache:
        return cache[key]
    async with _lock_for(key):
        if key in cache:
            return cache[key]
        value = await fetch_fn()
        cache[key] = value
        return value


async def get_manifest(key: str, fetch_fn: Callable[[], Awaitable[Any]]) -> Any:
    return await get_or_fetch(_manifest_cache, key, fetch_fn)


async def get_day(key: str, fetch_fn: Callable[[], Awaitable[Any]]) -> Any:
    return await get_or_fetch(_day_cache, key, fetch_fn)


async def get_range(
    key: str,
    *,
    contains_latest: bool,
    fetch_fn: Callable[[], Awaitable[Any]],
) -> Any:
    cache = _range_current_cache if contains_latest else _range_past_cache
    return await get_or_fetch(cache, key, fetch_fn)


async def get_search_index(
    key: str,
    *,
    contains_latest: bool,
    fetch_fn: Callable[[], Awaitable[Any]],
) -> Any:
    cache = _search_index_current_cache if contains_latest else _search_index_past_cache
    return await get_or_fetch(cache, key, fetch_fn)
