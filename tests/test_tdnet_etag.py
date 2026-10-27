from __future__ import annotations

import asyncio

from cachetools import LRUCache
import httpx
import pytest

PATH = "tdnet/disclosures/latest.json"


@pytest.fixture()
async def r2_runtime(monkeypatch):
    monkeypatch.setenv("R2_PUBLIC_BASE_URL", "https://r2.example.test")
    from app import r2

    monkeypatch.setattr(r2, "R2_PUBLIC_BASE_URL", "https://r2.example.test")
    monkeypatch.setattr(r2, "_tdnet_bodies", LRUCache(maxsize=r2._TDNET_BODY_CACHE_BYTES, getsizeof=lambda entry: len(entry.body)))
    monkeypatch.setattr(r2, "_tdnet_locks", {})
    yield r2
    await r2.close_client()


def use_transport(monkeypatch, r2, handler):
    monkeypatch.setattr(r2, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))


@pytest.mark.parametrize("first_tag,confirmed_tag", [
    ('"v1"', '"v1"'), ('W/"v1"', '"v1"'), ('"v1"', 'W/"v1"'), ('"v1"', None),
])
async def test_304_confirmation_and_returned_body_mutation(r2_runtime, monkeypatch, first_tag, confirmed_tag):
    r2 = r2_runtime
    seen = []

    def handle(request):
        seen.append(request.headers.get("if-none-match"))
        if len(seen) == 1:
            return httpx.Response(200, json={"value": {"revision": 1}}, headers={"ETag": first_tag})
        return httpx.Response(304, headers={"ETag": confirmed_tag} if confirmed_tag else {})

    use_transport(monkeypatch, r2, handle)
    first = await r2.fetch_json(PATH)
    first["value"]["revision"] = 999
    assert await r2.fetch_json(PATH) == {"value": {"revision": 1}}
    assert seen == [None, first_tag]


@pytest.mark.parametrize("failure", ["404", "503", "timeout", "bad-json", "array", "bad-304", "206"])
async def test_failed_validation_discards_old_body_and_next_get_is_unconditional(r2_runtime, monkeypatch, failure):
    r2 = r2_runtime
    seen = []

    def handle(request):
        seen.append(request.headers.get("if-none-match"))
        if len(seen) == 1:
            return httpx.Response(200, json={"v": 1}, headers={"ETag": '"v1"'})
        if len(seen) == 3:
            return httpx.Response(200, json={"v": 2}, headers={"ETag": '"v2"'})
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic", request=request)
        if failure == "bad-json":
            return httpx.Response(200, content=b"not-json", headers={"ETag": '"bad"'})
        if failure == "array":
            return httpx.Response(200, json=[], headers={"ETag": '"bad"'})
        if failure == "bad-304":
            return httpx.Response(304, headers={"ETag": '"different"'})
        return httpx.Response(int(failure), json={"v": 9})

    use_transport(monkeypatch, r2, handle)
    assert await r2.fetch_json(PATH) == {"v": 1}
    with pytest.raises((RuntimeError, httpx.HTTPError, ValueError)):
        await r2.fetch_json(PATH)
    assert len(r2._tdnet_bodies) == 0
    assert await r2.fetch_json(PATH) == {"v": 2}
    assert seen == [None, '"v1"', None]


async def test_unexpected_304_without_retained_body_fails(r2_runtime, monkeypatch):
    r2 = r2_runtime
    use_transport(monkeypatch, r2, lambda request: httpx.Response(304))
    with pytest.raises(RuntimeError, match="without a retained"):
        await r2.fetch_json(PATH)


@pytest.mark.parametrize("new_tag", [None, "unquoted", '"bad\nvalue"'])
async def test_missing_or_invalid_etag_replaces_previous_validator(r2_runtime, monkeypatch, new_tag):
    r2 = r2_runtime
    seen = []

    def handle(request):
        seen.append(request.headers.get("if-none-match"))
        tag = '"v1"' if len(seen) == 1 else new_tag
        return httpx.Response(200, json={"v": len(seen)}, headers={"ETag": tag} if tag else {})

    use_transport(monkeypatch, r2, handle)
    for n in range(1, 4):
        assert await r2.fetch_json(PATH) == {"v": n}
    assert seen == [None, '"v1"', None]


async def test_byte_limit_and_eviction_do_not_reuse_missing_body(r2_runtime, monkeypatch):
    r2 = r2_runtime
    monkeypatch.setattr(r2, "_TDNET_BODY_CACHE_BYTES", 16)
    monkeypatch.setattr(r2, "_tdnet_bodies", LRUCache(maxsize=16, getsizeof=lambda entry: len(entry.body)))
    seen = []

    def handle(request):
        seen.append(request.headers.get("if-none-match"))
        body = {"v": "x" * 32} if len(seen) == 2 else {"v": len(seen)}
        return httpx.Response(200, json=body, headers={"ETag": f'"v{len(seen)}"'})

    use_transport(monkeypatch, r2, handle)
    await r2.fetch_json(PATH)
    await r2.fetch_json(PATH)  # oversized: returned to caller, not retained
    assert r2._tdnet_bodies.currsize == 0
    await r2.fetch_json(PATH)
    await r2.fetch_json("tdnet/router-events/latest.json")  # evicts the first small body
    await r2.fetch_json("disclosure-events/latest.json")
    await r2.fetch_json(PATH)
    assert seen[:3] == [None, '"v1"', None]
    assert seen[-1] is None
    assert r2._tdnet_bodies.currsize <= 16


async def test_origin_change_never_shares_validator(r2_runtime, monkeypatch):
    r2 = r2_runtime
    seen = []
    def handle(request):
        seen.append((request.url.host, request.headers.get("if-none-match")))
        return httpx.Response(200, json={"ok": True}, headers={"ETag": '"v1"'})
    use_transport(monkeypatch, r2, handle)
    await r2.fetch_json(PATH)
    monkeypatch.setattr(r2, "R2_PUBLIC_BASE_URL", "https://other.example.test")
    await r2.fetch_json(PATH)
    assert seen == [("r2.example.test", None), ("other.example.test", None)]


async def test_concurrent_requests_validate_in_order(r2_runtime, monkeypatch):
    r2 = r2_runtime
    seen = []
    async def handle(request):
        seen.append(request.headers.get("if-none-match"))
        await asyncio.sleep(0)
        if len(seen) == 1:
            return httpx.Response(200, json={"v": 1}, headers={"ETag": '"v1"'})
        return httpx.Response(304, headers={"ETag": '"v1"'})
    use_transport(monkeypatch, r2, handle)
    results = await asyncio.gather(*(r2.fetch_json(PATH) for _ in range(8)))
    assert results == [{"v": 1}] * 8
    assert seen == [None] + ['"v1"'] * 7


async def test_cancelled_fetch_does_not_keep_validator(r2_runtime, monkeypatch):
    r2 = r2_runtime
    ready = asyncio.Event()
    async def handle(request):
        if request.headers.get("if-none-match"):
            ready.set()
            await asyncio.Event().wait()
        return httpx.Response(200, json={"v": 1}, headers={"ETag": '"v1"'})
    use_transport(monkeypatch, r2, handle)
    await r2.fetch_json(PATH)
    pending = asyncio.create_task(r2.fetch_json(PATH))
    await ready.wait()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert len(r2._tdnet_bodies) == 0


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity", "1e999"])
async def test_invalid_numeric_body_is_not_retained(r2_runtime, monkeypatch, constant):
    r2 = r2_runtime
    seen = []
    def handle(request):
        seen.append(request.headers.get("if-none-match"))
        if len(seen) == 2:
            return httpx.Response(200, content=('{"v":'+constant+'}').encode(), headers={"ETag": '"v2"'})
        return httpx.Response(200, json={"v": len(seen)}, headers={"ETag": '"valid"'})
    use_transport(monkeypatch, r2, handle)
    await r2.fetch_json(PATH)
    with pytest.raises(ValueError):
        await r2.fetch_json(PATH)
    assert len(r2._tdnet_bodies) == 0
    assert await r2.fetch_json(PATH) == {"v": 3}
    assert seen == [None, '"valid"', None]


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
async def test_304_retained_body_parser_also_rejects_invalid_constants(r2_runtime, monkeypatch, constant):
    r2 = r2_runtime
    url = r2.R2_PUBLIC_BASE_URL + "/" + PATH
    r2._tdnet_bodies[url] = r2._ETagBody('"v1"', ('{"v":'+constant+'}').encode())
    use_transport(monkeypatch, r2, lambda request: httpx.Response(304, headers={"ETag": '"v1"'}))
    with pytest.raises(ValueError):
        await r2.fetch_json(PATH)
    assert len(r2._tdnet_bodies) == 0


async def test_raw_non_ascii_response_etag_falls_back_without_forwarding(r2_runtime, monkeypatch):
    r2 = r2_runtime
    seen = []
    def handle(request):
        seen.append(request.headers.get("if-none-match"))
        return httpx.Response(200, json={"v": 1}, headers=[(b"etag", b'"\xff"')])
    use_transport(monkeypatch, r2, handle)
    assert await r2.fetch_json(PATH) == {"v": 1}
    assert await r2.fetch_json(PATH) == {"v": 1}
    assert seen == [None, None]
    assert len(r2._tdnet_bodies) == 0


async def test_json_strings_named_nan_remain_valid(r2_runtime, monkeypatch):
    r2 = r2_runtime
    use_transport(monkeypatch, r2, lambda request: httpx.Response(200, json={"v": "NaN"}, headers={"ETag": '"v1"'}))
    assert await r2.fetch_json(PATH) == {"v": "NaN"}
