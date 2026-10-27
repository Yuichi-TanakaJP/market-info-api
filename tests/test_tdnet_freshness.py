from __future__ import annotations

import copy
import json
from pathlib import Path

import httpx
import pytest
from cachetools import TTLCache
from fastapi.testclient import TestClient

FIXTURES = Path(__file__).parent / "fixtures"
CASES = [
    ("tdnet/disclosures/latest", "tdnet_disclosures_real_shape.json"),
    ("disclosure-events/latest", "disclosure_events_real_shape.json"),
    ("disclosure-events/manifest", "disclosure_events_manifest_real_shape.json"),
    ("tdnet/router-events/latest", "tdnet_router_events_real_shape.json"),
    ("tdnet/router-events/manifest", "tdnet_router_manifest_real_shape.json"),
]
DATED = [CASES[0], CASES[1], CASES[3]]


def versions(fixture):
    first = json.loads((FIXTURES / fixture).read_text(encoding="utf-8"))
    date = first.get("target_date", first.get("latest"))
    second = json.loads(json.dumps(first).replace(date, "2026-10-27"))
    assert first != second
    return first, second


@pytest.fixture()
def app_runtime(monkeypatch):
    monkeypatch.setenv("R2_PUBLIC_BASE_URL", "https://r2.example.test")
    from app import cache, config, r2
    from app.main import app

    # Patch attributes and let monkeypatch restore them; do not reload shared modules.
    monkeypatch.setattr(config, "R2_PUBLIC_BASE_URL", "https://r2.example.test")
    monkeypatch.setattr(r2, "R2_PUBLIC_BASE_URL", "https://r2.example.test")
    monkeypatch.setattr(cache, "_manifest_cache", TTLCache(maxsize=32, ttl=21600))
    monkeypatch.setattr(cache, "_day_cache", TTLCache(maxsize=32, ttl=86400))
    return app, r2, cache


@pytest.mark.parametrize("key,fixture", CASES)
def test_next_request_sees_publication_without_wait_or_restart(app_runtime, monkeypatch, key, fixture):
    app, r2, cache = app_runtime
    first, second = versions(fixture)
    current = [first]
    seen = []
    # Even an old, unexpired process-cache entry must not be returned.
    cache._manifest_cache[key] = first

    def handle(request):
        seen.append(request)
        assert request.url.path == f"/{key}.json"
        return httpx.Response(200, json=current[0])

    monkeypatch.setattr(r2, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    with TestClient(app) as client:
        before = client.get(f"/{key}")
        current[0] = second  # producer publishes while the API process stays alive
        after = client.get(f"/{key}")
    assert before.status_code == after.status_code == 200
    assert before.json() == first
    assert after.json() == second
    assert [x.headers.get("cache-control") for x in seen] == ["no-cache", "no-cache"]
    assert before.headers["cache-control"] == after.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("key,fixture", CASES)
def test_same_day_publication_change_is_not_hidden(app_runtime, monkeypatch, key, fixture):
    app, r2, _ = app_runtime
    first, _ = versions(fixture)
    second = copy.deepcopy(first)
    if "items" in second:
        second["items"][0]["title"] = "テスト更新後"
    else:
        second["generated_at"] = "2026-06-12T01:00:00Z"
    current = [first]
    monkeypatch.setattr(r2, "_client", httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=current[0])
    )))
    with TestClient(app) as client:
        before = client.get(f"/{key}")
        current[0] = second
        after = client.get(f"/{key}")
    assert before.status_code == after.status_code == 200
    assert before.json() != after.json()
    assert after.json() == second


@pytest.mark.parametrize("key,fixture", CASES)
@pytest.mark.parametrize("failure", ["404", "503", "timeout", "bad-json", "array"])
def test_failed_refresh_returns_error_not_stale_then_recovers(app_runtime, monkeypatch, key, fixture, failure):
    app, r2, cache = app_runtime
    first, second = versions(fixture)
    cache._manifest_cache[key] = first
    state = ["first"]

    def handle(request):
        if state[0] == "first":
            return httpx.Response(200, json=first)
        if state[0] == "recovered":
            return httpx.Response(200, json=second)
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        if failure == "bad-json":
            return httpx.Response(200, content=b"not-json")
        if failure == "array":
            return httpx.Response(200, json=[])
        return httpx.Response(int(failure))

    monkeypatch.setattr(r2, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    with TestClient(app) as client:
        assert client.get(f"/{key}").status_code == 200
        state[0] = "failed"
        failed = client.get(f"/{key}")
        expected = 404 if failure == "404" and key != "disclosure-events/manifest" else 502
        # Preserve the existing manifest missing-object error mapping.
        assert failed.status_code == expected
        assert failed.headers["cache-control"] == "no-store"
        assert "detail" in failed.json()
        state[0] = "recovered"
        recovered = client.get(f"/{key}")
        assert recovered.status_code == 200
        assert recovered.json() == second


@pytest.mark.parametrize("key,fixture", DATED)
def test_dated_payload_keeps_immutable_cache(app_runtime, monkeypatch, key, fixture):
    app, r2, _ = app_runtime
    first, second = versions(fixture)
    current = [first]
    seen = []
    date = first["target_date"]
    path = key.removesuffix("latest") + date

    def handle(request):
        seen.append(request)
        assert request.url.path == f"/{path}.json"
        return httpx.Response(200, json=current[0])

    monkeypatch.setattr(r2, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    with TestClient(app) as client:
        before = client.get(f"/{path}")
        current[0] = second
        after = client.get(f"/{path}")
    assert before.status_code == after.status_code == 200
    assert before.json() == after.json() == first
    assert len(seen) == 1
    assert seen[0].headers.get("cache-control") is None
    expected_header = None if key == "tdnet/disclosures/latest" else "public, max-age=31536000, immutable"
    assert after.headers.get("cache-control") == expected_header
