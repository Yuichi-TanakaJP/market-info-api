"""Real published shapes through HTTP/R2, including repair fences and warm caches."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import httpx
import pytest
from cachetools import LRUCache, TTLCache
from fastapi.testclient import TestClient

FIXTURES = Path(__file__).parent / "fixtures"
DAY = "2026-11-16"
PATHS = {
    "tdnet": "/tdnet/disclosures",
    "events": "/disclosure-events",
    "router": "/tdnet/router-events",
}
FIXTURE_NAMES = {
    "tdnet": "tdnet_disclosures_real_shape.json",
    "events": "disclosure_events_real_shape.json",
    "router": "tdnet_router_events_real_shape.json",
}


def encoded(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


@pytest.fixture()
def runtime(monkeypatch):
    monkeypatch.setenv("R2_PUBLIC_BASE_URL", "https://r2.example.test")
    from app import cache, r2, tdnet_corrections as corrections
    from app.main import app

    monkeypatch.setattr(r2, "R2_PUBLIC_BASE_URL", "https://r2.example.test")
    monkeypatch.setattr(cache, "_day_cache", TTLCache(maxsize=128, ttl=86400))
    monkeypatch.setattr(
        corrections,
        "_verified_bodies",
        LRUCache(maxsize=corrections._VERIFIED_BODY_LIMIT, getsizeof=len),
    )
    docs = {}
    for family, name in FIXTURE_NAMES.items():
        value = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
        docs[family] = json.loads(json.dumps(value).replace(value["target_date"], DAY))
    docs["intent"] = {
        "schema_version": 1,
        "artifact_type": "tdnet_cloud_bundle_intent",
        "target_date": DAY,
        "semantic_digests": {
            family: corrections.semantic_digest(family, body)
            for family, body in docs.items()
        },
    }
    release = {
        "schema_version": "tdnet-correction-release-v1",
        "target_date": DAY,
        "reason": "premature_empty_day",
        "supersedes": {family: "a" * 64 for family in docs},
        "documents": {family: digest(body) for family, body in docs.items()},
        "source": {
            "page_sha256": ["b" * 64],
            "page_count": 1,
            "disclosure_count": docs["tdnet"]["total_count"],
            "fetched_at": "2026-11-17T00:01:00Z",
        },
    }
    revision = digest(release)
    index = {
        "schema_version": "tdnet-correction-index-v1",
        "revisions": {DAY: revision},
        "pending": None,
    }
    objects = {
        corrections.INDEX_KEY: encoded(index),
        f"{corrections.PREFIX}/releases/{revision}.json": encoded(release),
    }
    for family, body in docs.items():
        objects[f"{corrections.PREFIX}/documents/{digest(body)}.json"] = encoded(body)
    seen = []

    def handle(request):
        key = request.url.path.lstrip("/")
        seen.append(request)
        body = objects.get(key)
        if callable(body):
            body = body(request)
        if isinstance(body, Exception):
            raise body
        if isinstance(body, int):
            return httpx.Response(body)
        if body is None:
            return httpx.Response(404)
        return httpx.Response(200, content=body, headers={"ETag": '"test"'})

    monkeypatch.setattr(
        r2, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handle))
    )
    with TestClient(app) as client:
        yield client, corrections, cache, objects, docs, release, index, revision, seen


@pytest.mark.parametrize("family", PATHS)
def test_corrected_body_bypasses_cached_zero_and_exposes_immutable_revision(
    runtime, family
):
    client, corrections, cache, objects, docs, release, index, revision, seen = runtime
    legacy_key = f"{PATHS[family].lstrip('/')}/{DAY}"
    cache._day_cache[legacy_key] = {**docs[family], "total_count": 0, "items": []}
    response = client.get(f"{PATHS[family]}/{DAY}")
    assert response.status_code == 200 and response.json() == docs[family]
    assert response.headers["cache-control"] == "no-store"
    assert (
        response.headers["content-location"]
        == f"{PATHS[family]}/{DAY}?revision={revision}"
    )
    version = client.get(response.headers["content-location"])
    assert version.status_code == 200 and version.json() == docs[family]
    assert "immutable" in version.headers["cache-control"]
    assert all(req.headers.get("cache-control") == "no-cache" for req in seen)
    assert not any(req.url.path == f"/{legacy_key}.json" for req in seen)


@pytest.mark.parametrize("family", PATHS)
def test_unknown_revision_rejected_without_legacy_fallback(runtime, family):
    client, _, _, _, _, _, _, _, _ = runtime
    response = client.get(f"{PATHS[family]}/{DAY}?revision={'f' * 64}")
    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "failure",
    [404, 503, b"{", b"[]", b'{"schema_version":"unknown"}', b"{}", b" " * 65537],
    ids=["absent", "outage", "json", "array", "schema", "empty", "oversize"],
)
def test_index_absence_only_preserves_legacy_other_failures_closed(runtime, failure):
    client, corrections, _, objects, docs, _, _, _, _ = runtime
    objects[corrections.INDEX_KEY] = failure
    objects[f"tdnet/disclosures/{DAY}.json"] = encoded(docs["tdnet"])
    response = client.get(f"/tdnet/disclosures/{DAY}")
    assert response.status_code == (200 if failure == 404 else 503)


@pytest.mark.parametrize(
    "path",
    [
        "/tdnet/disclosures/latest",
        "/disclosure-events/latest",
        "/disclosure-events/manifest",
        "/tdnet/router-events/latest",
        "/tdnet/router-events/manifest",
        f"/tdnet/disclosures/{DAY}",
        f"/disclosure-events/{DAY}",
        f"/tdnet/router-events/{DAY}",
    ],
)
def test_pending_fences_all_mutable_and_repair_day_even_warm(runtime, path):
    client, corrections, cache, objects, docs, _, index, _, _ = runtime
    pending = copy.deepcopy(index)
    pending["pending"] = {"date": DAY, "plan_sha256": "c" * 64}
    objects[corrections.INDEX_KEY] = encoded(pending)
    cache._day_cache[path.lstrip("/")] = docs["tdnet"]
    response = client.get(path)
    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"


def test_other_dated_data_continues_during_pending(runtime):
    client, corrections, _, objects, docs, _, index, _, _ = runtime
    pending = copy.deepcopy(index)
    pending["pending"] = {"date": DAY, "plan_sha256": "c" * 64}
    objects[corrections.INDEX_KEY] = encoded(pending)
    other = json.loads(json.dumps(docs["tdnet"]).replace(DAY, "2026-11-13"))
    objects["tdnet/disclosures/2026-11-13.json"] = encoded(other)
    response = client.get("/tdnet/disclosures/2026-11-13")
    assert response.status_code == 200 and response.json() == other


@pytest.mark.parametrize("target", ["release", "tdnet", "events", "router", "intent"])
@pytest.mark.parametrize("failure", [404, b"{}"])
def test_any_partial_or_digest_changed_release_fails_closed(runtime, target, failure):
    client, corrections, _, objects, _, release, _, revision, _ = runtime
    key = (
        f"{corrections.PREFIX}/releases/{revision}.json"
        if target == "release"
        else f"{corrections.PREFIX}/documents/{release['documents'][target]}.json"
    )
    objects[key] = failure
    response = client.get(f"/tdnet/disclosures/{DAY}")
    assert response.status_code == 503


def test_duplicate_index_key_is_rejected(runtime):
    client, corrections, _, objects, _, _, _, _, _ = runtime
    objects[corrections.INDEX_KEY] = (
        b'{"schema_version":"tdnet-correction-index-v1","revisions":{},"pending":null,"pending":null}'
    )
    assert client.get(f"/tdnet/disclosures/{DAY}").status_code == 503


def test_warm_corrected_cache_still_checks_new_pending_index(runtime):
    client, corrections, _, objects, _, _, index, _, _ = runtime
    path = f"/tdnet/disclosures/{DAY}"
    assert client.get(path).status_code == 200
    index["pending"] = {"date": DAY, "plan_sha256": "d" * 64}
    objects[corrections.INDEX_KEY] = encoded(index)
    assert client.get(path).status_code == 503


@pytest.mark.parametrize("family", PATHS)
def test_activation_race_between_index_and_payload_fails_closed(runtime, family):
    client, corrections, _, objects, docs, _, index, _, _ = runtime
    objects[corrections.INDEX_KEY] = encoded({**index, "revisions": {}})

    def publish_pending(_):
        objects[corrections.INDEX_KEY] = encoded(
            {**index, "pending": {"date": DAY, "plan_sha256": "e" * 64}}
        )
        return encoded(docs[family])

    objects[f"{PATHS[family].lstrip('/')}/{DAY}.json"] = publish_pending
    assert client.get(f"{PATHS[family]}/{DAY}").status_code == 503


def test_mutable_fetch_straddling_pending_is_not_returned(runtime):
    client, corrections, _, objects, docs, _, index, _, _ = runtime
    objects[corrections.INDEX_KEY] = encoded({**index, "revisions": {}})

    def publish_pending(_):
        objects[corrections.INDEX_KEY] = encoded(
            {**index, "pending": {"date": DAY, "plan_sha256": "e" * 64}}
        )
        return encoded(docs["tdnet"])

    objects["tdnet/disclosures/latest.json"] = publish_pending
    assert client.get("/tdnet/disclosures/latest").status_code == 503


@pytest.mark.parametrize(
    "bad", ["day", "count", "item_day", "schema", "intent", "closed_day", "page_count"]
)
def test_valid_content_hash_does_not_make_invalid_release_acceptable(runtime, bad):
    client, corrections, _, objects, docs, release, index, _, _ = runtime
    if bad == "day":
        docs["tdnet"]["target_date"] = "2026-11-15"
    elif bad == "count":
        docs["tdnet"]["total_count"] += 1
    elif bad == "item_day":
        docs["tdnet"]["items"][0]["disclosure_date"] = "2026-11-15"
    elif bad == "schema":
        docs["events"]["schema_version"] = "future-unrecognized"
    elif bad == "intent":
        docs["intent"]["semantic_digests"]["tdnet"] = "f" * 64
    elif bad == "closed_day":
        release["source"]["fetched_at"] = "2026-11-16T00:00:00Z"
    elif bad == "page_count":
        release["source"]["page_count"] = 101
    for family, body in docs.items():
        release["documents"][family] = digest(body)
        objects[f"{corrections.PREFIX}/documents/{digest(body)}.json"] = encoded(body)
    revision = digest(release)
    objects[f"{corrections.PREFIX}/releases/{revision}.json"] = encoded(release)
    objects[corrections.INDEX_KEY] = encoded({**index, "revisions": {DAY: revision}})
    assert client.get(f"/tdnet/disclosures/{DAY}").status_code == 503


@pytest.mark.parametrize("family", PATHS)
def test_shared_market_info_publisher_wire_fixture(runtime, family):
    client, corrections, _, objects, _, _, _, _, _ = runtime
    fixture = json.loads(
        (FIXTURES / "tdnet_corrections_v1.json").read_text(encoding="utf-8")
    )
    revision = fixture["release_sha256"]
    release = fixture["release"]
    assert digest(release) == revision
    objects.clear()
    objects[corrections.INDEX_KEY] = encoded(fixture["index"])
    objects[f"{corrections.PREFIX}/releases/{revision}.json"] = encoded(release)
    for key, value in fixture["new"].items():
        assert digest(value) == release["documents"][key]
        objects[f"{corrections.PREFIX}/documents/{digest(value)}.json"] = encoded(value)
    day = release["target_date"]
    response = client.get(f"{PATHS[family]}/{day}?revision={revision}")
    assert response.status_code == 200
    assert response.json() == fixture["new"][family]
    assert response.headers["etag"] == f'"{revision}"'
    assert "immutable" in response.headers["cache-control"]


@pytest.mark.parametrize("count,expected", [(500, 200), (501, 503)])
def test_index_entry_limit_500_independent_of_byte_limit(runtime, count, expected):
    from datetime import date, timedelta

    client, corrections, _, objects, docs, _, index, _, _ = runtime
    revisions = {
        (date(2020, 1, 1) + timedelta(days=i)).isoformat(): "f" * 64
        for i in range(count)
    }
    body = encoded({**index, "revisions": revisions})
    assert len(body) < corrections.INDEX_LIMIT
    objects[corrections.INDEX_KEY] = body
    objects[f"tdnet/disclosures/{DAY}.json"] = encoded(docs["tdnet"])
    assert client.get(f"/tdnet/disclosures/{DAY}").status_code == expected


@pytest.mark.parametrize("extra,expected", [(0, 200), (1, 503)])
def test_index_exact_byte_boundary(runtime, extra, expected):
    client, corrections, _, objects, docs, _, index, _, _ = runtime
    body = encoded({**index, "revisions": {}})
    objects[corrections.INDEX_KEY] = body + b" " * (
        corrections.INDEX_LIMIT - len(body) + extra
    )
    objects[f"tdnet/disclosures/{DAY}.json"] = encoded(docs["tdnet"])
    assert client.get(f"/tdnet/disclosures/{DAY}").status_code == expected


@pytest.mark.parametrize(
    "bad",
    [
        b"\xff",
        b"\xef\xbb\xbf{}",
        b'{"x":"\\ud800"}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":1e999}',
        b'{"x":1,"x":2}',
    ],
    ids=["utf8", "bom", "surrogate", "nan", "infinity", "overflow", "duplicate"],
)
def test_strict_utf8_json_byte_parser_rejects_unknown_or_nonportable_values(
    runtime, bad
):
    _, corrections, *_ = runtime
    with pytest.raises((ValueError, UnicodeError)):
        corrections._parse(bad)
