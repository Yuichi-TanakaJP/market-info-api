import asyncio
from app import cache


def test_yutai_latest_uses_short_cache():
    key = "yutai-stock-prices/latest"
    cache._observation_manifest_cache.pop(key, None)
    cache._manifest_cache.pop(key, None)
    calls = 0

    async def fetch():
        nonlocal calls
        calls += 1
        return {"version": calls}

    async def exercise():
        assert await cache.get_manifest(key, fetch) == {"version": 1}
        assert await cache.get_manifest(key, fetch) == {"version": 1}
        assert key not in cache._manifest_cache
        assert cache._observation_manifest_cache.ttl == 30
        cache._observation_manifest_cache.pop(key)
        assert await cache.get_manifest(key, fetch) == {"version": 2}

    try:
        asyncio.run(exercise())
    finally:
        cache._observation_manifest_cache.pop(key, None)
        cache._manifest_cache.pop(key, None)
