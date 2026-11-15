"""Synthetic complete wire shape, integrity/authentication and failure boundaries."""

import asyncio
import json
import os
from pathlib import Path

os.environ.setdefault("R2_PUBLIC_BASE_URL", "https://example.invalid")
import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
from app import config
from app.main import app
from app.routers import tdnet_source_originals as mod
from app.tdnet_source_original import (
    SourceOriginal,
    canonical_bytes,
    digest,
    parse_record,
    validate_content,
)

AUTH = {"Authorization": "Bearer synthetic-original-test"}


@pytest.fixture
def saved(monkeypatch):
    data = json.loads(
        Path(__file__)
        .with_name("fixtures")
        .joinpath("tdnet_source_original/synthetic_full_shape.json")
        .read_text()
    )
    raw = b"PK\x03\x04test"
    data["content_sha256"] = digest(raw)
    model = SourceOriginal.model_validate(data)
    body = canonical_bytes(model)
    sha = digest(body)
    path = f"/private/tdnet/source-originals/1234/{model.disclosure_id}/{sha}"
    key = f"{mod.PREFIX}/by-code/1234/documents/{model.disclosure_id}/{sha}.json"
    objects = {key: body, model.raw_key: raw}
    reads = []

    async def read(key, limit):
        reads.append((key, limit))
        if key not in objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        if len(objects[key]) > limit:
            raise ValueError("oversize")
        return objects[key]

    monkeypatch.setattr(mod.storage, "read_bytes", read)
    monkeypatch.setattr(config, "DIVIDEND_SOURCE_API_KEY", "synthetic-original-test")
    return data, body, raw, path, objects, reads


def test_exact_full_shape_and_content(saved):
    data, body, raw, path, objects, reads = saved
    with TestClient(app) as c:
        a = c.get(path, headers=AUTH)
        b = c.get(path + "/content", headers=AUTH)
    assert a.status_code == b.status_code == 200
    assert a.content == body and b.content == raw
    assert a.headers["x-content-sha256"] == digest(body)
    assert b.headers["x-content-sha256"] == digest(raw)
    assert b.headers["x-source-record-sha256"] == digest(body)
    assert b.headers["content-type"] == data["media_type"]
    for r in (a, b):
        assert r.headers["cache-control"] == "private, no-store"
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["content-disposition"].startswith("attachment;")
    assert len(reads) == 3


def test_auth_before_invalid_selector_or_storage(saved, monkeypatch):
    *_, reads = saved
    with TestClient(app) as c:
        assert c.get("/private/tdnet/source-originals/bad/bad/bad").status_code == 401
        assert (
            c.get(
                "/private/tdnet/source-originals/bad/bad/bad", headers=AUTH
            ).status_code
            == 400
        )
        monkeypatch.setattr(config, "DIVIDEND_SOURCE_API_KEY", "")
        assert c.get(saved[3], headers=AUTH).status_code == 503
    assert reads == []


def test_missing_and_corrupt(saved):
    _, body, _, path, objects, reads = saved
    with TestClient(app) as c:
        key = next(iter(objects))
        objects[key] = body + b" "
        assert c.get(path + "/content", headers=AUTH).status_code == 503
        assert len(reads) == 1
        del objects[key]
        assert c.get(path, headers=AUTH).status_code == 404


def test_raw_corruption_and_storage_error(saved, monkeypatch):
    *_, path, objects, reads = saved
    with TestClient(app) as c:
        raw_key = list(objects)[1]
        objects[raw_key] = b"bad"
        assert c.get(path + "/content", headers=AUTH).status_code == 503

        async def bad(*args):
            raise RuntimeError("storage unavailable")

        monkeypatch.setattr(mod.storage, "read_bytes", bad)
        assert c.get(path, headers=AUTH).status_code == 503


@pytest.mark.parametrize(
    "change",
    [
        {"byte_length": True},
        {"byte_length": 4194305},
        {"extra": 1},
        {"disclosure_date": "20261115"},
        {"retrieved_at": "2026-11-15T12:00:00"},
        {"media_type": "application/pdf"},
        {"retrieved_url": "https://evil.invalid/test.zip"},
        {
            "official_url": "https://www.release.tdnet.info:443/inbs/140120261115654321.zip"
        },
    ],
)
def test_schema_rejects_invalid(saved, change):
    data = saved[0] | change
    with pytest.raises(ValueError):
        SourceOriginal.model_validate(data)


def test_pdf_and_strict_json(saved):
    data = saved[0] | {
        "source_kind": "pdf",
        "media_type": "application/pdf",
        "official_url": "https://www.release.tdnet.info/inbs/140120261115123456.pdf",
        "retrieved_url": "https://www.release.tdnet.info/inbs/140120261115123456.pdf",
        "byte_length": 9,
        "content_sha256": digest(b"%PDF-test"),
    }
    record = SourceOriginal.model_validate(data)
    validate_content(b"%PDF-test", record)
    data["official_url"] = data["official_url"].replace("123456", "999999")
    with pytest.raises(ValueError):
        SourceOriginal.model_validate(data)
    for body in (b'{"x":1,"x":2}', b'{"x":NaN}', b"[]", b"x" * 16385):
        with pytest.raises(ValueError):
            parse_record(body, "1234", "140120261115123456", digest(body))


@pytest.mark.asyncio
async def test_cancellation_is_not_translated(saved, monkeypatch):
    async def cancelled(*args):
        raise asyncio.CancelledError()

    monkeypatch.setattr(mod.storage, "read_bytes", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await mod._read("1234", "140120261115123456", digest(saved[1]))


@pytest.mark.parametrize(
    "timestamp",
    [
        "2026-11-15 12:00:00Z",
        "2026-11-15T12:00:00,123Z",
        "2026-11-15T12:00:00.1234567Z",
        "2026-11-15T12:00Z",
        "2026-11-15T12:00:00",
        "2026-11-15T12:00:00+",
    ],
)
def test_retrieval_timestamp_rejects_noncontract_forms(saved, timestamp):
    with pytest.raises(ValueError):
        SourceOriginal.model_validate(saved[0] | {"retrieved_at": timestamp})


@pytest.mark.parametrize(
    "timestamp",
    [
        "2026-11-15T12:00:00Z",
        "2026-11-15T12:00:00.123456Z",
        "2026-11-15T12:00:00.123456+09:00",
    ],
)
def test_retrieval_timestamp_accepts_contract_forms(saved, timestamp):
    assert (
        SourceOriginal.model_validate(
            saved[0] | {"retrieved_at": timestamp}
        ).retrieved_at
        == timestamp
    )


def test_saved_record_missing_raw_is_unavailable(saved):
    _, _, _, path, objects, _ = saved
    del objects[list(objects)[1]]
    with TestClient(app) as client:
        assert client.get(path, headers=AUTH).status_code == 200
        response = client.get(path + "/content", headers=AUTH)
        assert response.status_code == 503
        assert response.headers["cache-control"] == "private, no-store"


def reference_path(saved):
    data, body, _, _, objects, _ = saved
    url_sha = digest(data["official_url"].encode("ascii"))
    prefix = f"{mod.PREFIX}/by-code/1234/documents/{data['disclosure_id']}"
    key = f"{prefix}/references/{url_sha}.json"
    objects[key] = body
    return (
        f"/private/tdnet/source-originals/1234/{data['disclosure_id']}/references/{url_sha}",
        key,
    )


def test_reference_resolves_complete_shape_and_pinned_record(saved):
    path, key = reference_path(saved)
    with TestClient(app) as client:
        response = client.get(path, headers=AUTH)
    assert response.status_code == 200
    assert response.content == saved[1]
    assert response.headers["x-content-sha256"] == digest(saved[1])
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert len(saved[-1]) == 2
    assert saved[-1][0] == (key, mod.MAX_RECORD_BYTES)
    assert saved[-1][1][0].endswith(digest(saved[1]) + ".json")


def test_reference_auth_precedes_selector_and_storage(saved):
    with TestClient(app) as client:
        path = "/private/tdnet/source-originals/bad/bad/references/bad"
        assert client.get(path).status_code == 401
        assert client.get(path, headers=AUTH).status_code == 400
    assert saved[-1] == []


def test_reference_missing_is_pending_not_absent_disclosure(saved):
    path, key = reference_path(saved)
    del saved[4][key]
    with TestClient(app) as client:
        assert client.get(path, headers=AUTH).status_code == 404
    assert len(saved[-1]) == 1


@pytest.mark.parametrize(
    "corruption",
    [
        "noncanonical",
        "wrong_issuer",
        "wrong_id",
        "wrong_url",
        "oversize",
        "missing_pinned",
        "different_pinned",
    ],
)
def test_reference_rejects_corrupt_or_uncommitted_metadata(saved, corruption):
    path, key = reference_path(saved)
    data, body, _, _, objects, reads = saved
    pinned_key = next(iter(objects))
    if corruption == "noncanonical":
        objects[key] = body + b" "
    elif corruption == "wrong_issuer":
        objects[key] = canonical_bytes(data | {"security_code": "9999"})
    elif corruption == "wrong_id":
        objects[key] = canonical_bytes(data | {"disclosure_id": "140120261115999999"})
    elif corruption == "wrong_url":
        objects[key] = canonical_bytes(
            data | {"official_url": data["official_url"].replace(".zip", ".zip?")}
        )
    elif corruption == "oversize":
        objects[key] = b"x" * (mod.MAX_RECORD_BYTES + 1)
    elif corruption == "missing_pinned":
        del objects[pinned_key]
    else:
        objects[pinned_key] = b"{}"
    with TestClient(app) as client:
        assert client.get(path, headers=AUTH).status_code == 503
    assert len(reads) == (2 if corruption.endswith("pinned") else 1)


def test_reference_rejects_valid_record_at_other_url_hash(saved):
    path, key = reference_path(saved)
    bad_sha = "a" * 64
    objects = saved[4]
    objects[key.replace(key.rsplit("/", 1)[1], bad_sha + ".json")] = saved[1]
    with TestClient(app) as client:
        assert (
            client.get(path.rsplit("/", 1)[0] + "/" + bad_sha, headers=AUTH).status_code
            == 503
        )
    assert len(saved[-1]) == 1


@pytest.mark.asyncio
async def test_reference_cancellation_propagates(saved, monkeypatch):
    async def cancelled(*args):
        raise asyncio.CancelledError()

    monkeypatch.setattr(mod.storage, "read_bytes", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await mod.reference("1234", saved[0]["disclosure_id"], "a" * 64)
