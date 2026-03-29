from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from cachetools import TTLCache

_MANIFEST_TTL = 300   # 5分
_DAY_TTL = 3600       # 60分

_manifest_cache: TTLCache = TTLCache(maxsize=16, ttl=_MANIFEST_TTL)
_day_cache: TTLCache = TTLCache(maxsize=128, ttl=_DAY_TTL)

_locks: dict[str, asyncio.Lock] = {}


def _lock_for(key: str) -> asyncio.Lock:
    if key not in _locks:
        _locks[key] = asyncio.Lock()
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
