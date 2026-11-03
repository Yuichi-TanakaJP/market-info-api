from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from botocore.exceptions import ClientError

from app import config, credit_history_storage
from app.credit_history_wire import PREFIX, canonical, digest
from app.routers import credit_history as router

FIXTURE = Path(__file__).parent / "fixtures/credit_inventory_daily_builder_shape.json"


def build_objects(payloads):
    objects, entries = {}, []
    for payload in payloads:
        body = canonical(payload)
        sha = digest(body)
        key = f"{PREFIX}/months/{payload['broker']}/{payload['month']}/{sha}.json"
        objects[key] = body
        entries.append(
            dict(
                broker=payload["broker"],
                month=payload["month"],
                sha256=sha,
                bytes=len(body),
                key=key,
                observed_dates=payload["observed_dates"],
            )
        )
    manifest = canonical(
        dict(
            schema="credit-inventory-history-manifest-v1",
            entries=sorted(entries, key=lambda x: (x["broker"], x["month"])),
        )
    )
    generation = digest(manifest)
    objects[f"{PREFIX}/manifest.json"] = manifest
    objects[f"{PREFIX}/generations/{generation}.json"] = manifest
    return objects, generation


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(config, "CREDIT_HISTORY_API_KEY", "test-only-owner-key")
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    objects, generation = build_objects([payload])
    calls = []

    async def read(key, limit):
        calls.append((key, limit))
        if key not in objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        body = objects[key]
        if len(body) > limit:
            raise ValueError("oversized")
        return body

    monkeypatch.setattr(credit_history_storage, "read_bytes", read)
    app = FastAPI()
    app.include_router(router.router)
    with TestClient(app) as client:
        yield client, payload, objects, calls, generation


def get(client, **params):
    query = dict(
        broker="smbc_nikko", codes="2730", start="2026-09-01", end="2026-09-30"
    )
    query.update(params)
    return client.get(
        "/private/credit-inventory/history",
        params=query,
        headers={"Authorization": "Bearer test-only-owner-key"},
    )


def test_auth_closed_and_no_storage_access(setup, monkeypatch):
    client, _, _, calls, _ = setup
    assert client.get("/private/credit-inventory/history").status_code == 401
    monkeypatch.setattr(config, "CREDIT_HISTORY_API_KEY", "")
    response = get(client)
    assert response.status_code == 503 and calls == []
    assert response.headers["cache-control"] == "private, no-store"


def test_builder_shape_zero_unknown_restock_and_gaps(setup):
    client, payload, _, calls, generation = setup
    response = get(client, codes="367A,2730")
    assert response.status_code == 200, response.text
    page = response.json()
    assert page["generation"] == generation
    assert page["complete"] and page["next_cursor"] is None
    assert page["live_executability_confirmed"] is False
    rows = page["observations"]
    present = [r for r in rows if r["code"] == "2730"]
    assert [r["record"]["available_shares"] for r in present] == [500, 0, None, 1200]
    assert [r["observed_date"] for r in present] == payload["observed_dates"]
    assert all(r["record"] is None for r in rows if r["code"] == "367A")
    assert all(r["collection_completeness"] == "not_attested" for r in rows)
    assert len(calls) == 3  # latest manifest + pinned manifest + one month
    assert response.headers["cache-control"] == "private, no-store"
    assert len(response.content) <= router.MAX_RESPONSE_BYTES


def test_generation_pinned_pages_even_when_latest_changes(setup):
    client, payload, objects, calls, old_generation = setup
    codes = [f"{1000 + i}" for i in range(20)]
    # Six observation days * twenty requested codes force pagination.
    for day in (25, 28):
        snapshot = copy.deepcopy(payload["snapshots"][0])
        snapshot["observed_date"] = f"2026-09-{day}"
        snapshot["observed_at"] = f"2026-09-{day}T09:00:00+09:00"
        snapshot["source_snapshot_id"] = (
            f"smbc_nikko:{snapshot['observed_at']}:{snapshot['source_sha256']}"
        )
        payload["snapshots"].append(snapshot)
        payload["observed_dates"].append(snapshot["observed_date"])
    payload["selected_snapshot_count"] = payload["source_snapshot_count"] = 6
    new, generation = build_objects([payload])
    objects.clear()
    objects.update(new)
    first = get(client, codes=",".join(codes)).json()
    assert first["complete"] is False and len(first["observations"]) == 100
    objects[f"{PREFIX}/manifest.json"] = b"broken-latest"
    calls.clear()
    response = get(client, codes=",".join(reversed(codes)), cursor=first["next_cursor"])
    assert response.status_code == 200, response.text
    second = response.json()
    assert second["generation"] == generation and second["complete"]
    assert len(second["observations"]) == 20 and len(calls) == 2
    assert get(client, cursor=first["next_cursor"]).status_code == 400
    assert (
        get(
            client, codes=",".join(codes), cursor=first["next_cursor"] + "x"
        ).status_code
        == 400
    )


def test_missing_months_and_partial_not_zero(setup):
    client, _, _, _, _ = setup
    page = get(client, start="2026-08-01", end="2026-10-31").json()
    assert page["missing_months"] == ["2026-08", "2026-10"]
    assert len(page["observations"]) == 4
    page = get(client, start="2026-01-01", end="2026-01-31").json()
    assert page["observations"] == [] and page["missing_months"] == ["2026-01"]


@pytest.mark.parametrize(
    "params",
    [
        dict(codes="2730,2730"),
        dict(codes="../x"),
        dict(codes=",".join(str(1000 + i) for i in range(21))),
        dict(start="2026-10-01"),
        dict(start="2025-08-01"),
        dict(cursor="forged"),
    ],
)
def test_invalid_filter_does_not_read_storage(setup, params):
    client, _, _, calls, _ = setup
    assert get(client, **params).status_code in {400, 422}
    assert calls == []


def test_tampered_artifact_not_served(setup):
    client, _, objects, _, _ = setup
    key = next(k for k in objects if "/months/" in k)
    objects[key] = objects[key].replace(b"500", b"501")
    response = get(client)
    assert response.status_code == 502
    assert "501" not in response.text


def test_missing_pinned_generation_not_success(setup):
    client, _, objects, _, generation = setup
    del objects[f"{PREFIX}/generations/{generation}.json"]
    assert get(client).status_code == 503


def test_unbounded_or_unsafe_manifest_is_rejected(setup):
    client, _, objects, _, _ = setup
    manifest = json.loads(objects[f"{PREFIX}/manifest.json"])
    manifest["entries"][0]["key"] = "unrelated/secret.json"
    raw = canonical(manifest)
    generation = digest(raw)
    objects[f"{PREFIX}/manifest.json"] = raw
    objects[f"{PREFIX}/generations/{generation}.json"] = raw
    assert get(client).status_code == 502


def test_byte_bound_paginates_without_losing_observations(setup):
    client, payload, objects, _, _ = setup
    codes = [str(1000 + i) for i in range(20)]
    for snapshot in payload["snapshots"]:
        record = copy.deepcopy(snapshot["by_code"]["2730"])
        record["regulation_sources_raw"] = "x" * 4096
        record["regulation_details_raw"] = "y" * 4096
        snapshot["by_code"] = {c: copy.deepcopy(record) for c in codes}
        snapshot["record_count"] = len(codes)
    new, _ = build_objects([payload])
    objects.clear()
    objects.update(new)
    cursor, rows, pages = None, [], 0
    while True:
        response = get(
            client, codes=",".join(codes), **({"cursor": cursor} if cursor else {})
        )
        assert response.status_code == 200, response.text
        assert len(response.content) <= router.MAX_RESPONSE_BYTES
        page = response.json()
        rows.extend(page["observations"])
        pages += 1
        if page["complete"]:
            break
        cursor = page["next_cursor"]
        assert pages < 10
    assert pages > 1 and len(rows) == 80
    assert len({(r["observed_date"], r["code"]) for r in rows}) == 80


def test_month_pages_and_empty_month_slice(setup):
    client, september, objects, _, _ = setup
    october = copy.deepcopy(september)
    october["month"] = "2026-10"
    for s in october["snapshots"]:
        s["observed_date"] = s["observed_date"].replace("2026-09", "2026-10")
        s["observed_at"] = s["observed_at"].replace("2026-09", "2026-10")
        s["source_snapshot_id"] = f"smbc_nikko:{s['observed_at']}:{s['source_sha256']}"
    october["observed_dates"] = [s["observed_date"] for s in october["snapshots"]]
    new, _ = build_objects([september, october])
    objects.clear()
    objects.update(new)
    first = get(client, start="2026-09-29", end="2026-10-30").json()
    assert first["observations"] == [] and first["complete"] is False
    second = get(
        client, start="2026-09-29", end="2026-10-30", cursor=first["next_cursor"]
    ).json()
    assert second["page_month"] == "2026-10" and len(second["observations"]) == 4
    assert second["complete"] and second["missing_months"] == []
