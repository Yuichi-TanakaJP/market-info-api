from unittest.mock import AsyncMock

import httpx
import pytest
from cachetools import TTLCache
from app import cache


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["stock-ranking", "topix33", "nikkei-contribution"])
async def test_mutable_pointer_expires_and_failed_refresh_never_renews_old_data(monkeypatch, prefix):
    clock = [0]
    store = TTLCache(maxsize=16, ttl=30, timer=lambda: clock[0])
    monkeypatch.setattr(cache, "_observation_manifest_cache", store)
    fetch = AsyncMock(side_effect=[{"version": 1}, RuntimeError("offline"), {"version": 2}])
    key = prefix + "/manifest"
    assert await cache.get_manifest(key, fetch) == {"version": 1}
    clock[0] = 29
    assert await cache.get_manifest(key, fetch) == {"version": 1}
    clock[0] = 31
    with pytest.raises(RuntimeError):
        await cache.get_manifest(key, fetch)
    assert await cache.get_manifest(key, fetch) == {"version": 2}
    assert fetch.await_count == 3


@pytest.mark.asyncio
async def test_r2_reuses_client_and_revalidates_only_mutable_pointers(monkeypatch):
    monkeypatch.setenv("R2_PUBLIC_BASE_URL", "https://r2.example.com")
    from app import r2
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(r2, "_client", client)
    for path in ["stock-ranking/manifest.json", "topix33/topix33_manifest.json", "nikkei-contribution/nikkei_contribution_manifest.json", "stock-ranking/snapshots/hash.json"]:
        assert await r2.fetch_json(path) == {"ok": True}
        assert r2.get_client() is client
    assert all(r.headers["cache-control"] == "no-cache" for r in seen[:3])
    assert "cache-control" not in seen[3].headers
    await r2.close_client()
    assert client.is_closed
    assert r2._client is None
