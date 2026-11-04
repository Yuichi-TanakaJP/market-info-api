from __future__ import annotations
import io
import json
import os
from pathlib import Path

os.environ.setdefault("R2_PUBLIC_BASE_URL", "https://example.invalid")

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

from app import config, dividend_source_storage
from app.dividend_source_wire import (
    PREFIX,
    MAX_MANIFEST_BYTES,
    digest,
)
from app.main import app
from app.routers import dividend_sources as mod

BASE = "/private/tdnet/dividend-sources/1234"
AUTH = {"Authorization": "Bearer synthetic-dividend-test-key"}


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


@pytest.fixture
def saved(monkeypatch):
    artifact = (
        Path(__file__)
        .with_name("fixtures")
        .joinpath("dividend_sources/annual_real_shape_synthetic.json")
        .read_bytes()
    )
    parsed = json.loads(artifact)
    primary = parsed["primary_disclosure"]
    entry = {
        "disclosure_id": primary["id"],
        "disclosure_date": primary["date"],
        "artifact_sha256": digest(artifact),
        "artifact_bytes": len(artifact),
        "extraction_status": parsed["extraction"]["status"],
        "source_input_sha256": sorted(
            {s["content_sha256"] for s in parsed["source_artifacts"]}
        ),
    }
    manifest = {
        "schema": "tdnet-dividend-private-manifest-v1",
        "security_code": "1234",
        "entries": [entry],
    }
    body = canonical(manifest)
    index = f"{PREFIX}/by-code/1234/manifest.json"
    snapshot = f"{PREFIX}/manifests/{digest(body)}.json"
    key = f"{PREFIX}/documents/{entry['disclosure_id']}/{entry['artifact_sha256']}.json"
    objects = {index: body, snapshot: body, key: artifact}
    reads = []

    async def read(object_key, limit):
        reads.append(object_key)
        if object_key not in objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        value = objects[object_key]
        if len(value) > limit:
            raise ValueError("oversized")
        return value

    monkeypatch.setattr(mod.storage, "read_bytes", read)
    monkeypatch.setattr(
        config, "DIVIDEND_SOURCE_API_KEY", "synthetic-dividend-test-key"
    )
    return objects, reads, entry, artifact, manifest


def test_exact_bytes_and_real_artifact_shape(saved):
    objects, reads, entry, artifact, _ = saved
    with TestClient(app) as client:
        response = client.get(BASE, headers=AUTH)
        assert response.status_code == 200
        assert response.content == objects[f"{PREFIX}/by-code/1234/manifest.json"]
        assert response.headers["X-Content-SHA256"] == digest(response.content)
        result = client.get(
            f"{BASE}/documents/{entry['disclosure_id']}/{entry['artifact_sha256']}",
            headers=AUTH,
        )
        assert result.status_code == 200 and result.content == artifact
        assert result.headers["X-Content-SHA256"] == digest(artifact)
        assert result.headers["cache-control"] == "private, no-store"
        assert result.json()["extraction"]["status"] == "partial"
        assert result.json()["observations"][0]["amount"]["amount_per_share"] == "80"
    assert len(reads) == 5


@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": "Basic abc"}]
)
def test_auth_denied_before_storage(saved, headers):
    with TestClient(app) as client:
        result = client.get(BASE, headers=headers)
        assert result.status_code == 401
        assert result.headers["cache-control"] == "private, no-store"
    assert saved[1] == []


def test_unconfigured_auth_fails_closed(saved, monkeypatch):
    monkeypatch.setattr(config, "DIVIDEND_SOURCE_API_KEY", "")
    with TestClient(app) as client:
        result = client.get(BASE, headers=AUTH)
        assert result.status_code == 503
    assert saved[1] == []


def test_missing_code_is_unsaved_not_zero(saved):
    with TestClient(app) as client:
        result = client.get(BASE.replace("1234", "9999"), headers=AUTH)
        assert result.status_code == 404
        assert "no saved" in result.json()["detail"]
        assert result.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize("selector", ["12340", "abcd", "%2e%2e", "1234%2fother"])
def test_invalid_symbol_no_storage(saved, selector):
    with TestClient(app) as client:
        result = client.get(BASE.replace("1234", selector), headers=AUTH)
        assert result.status_code in (400, 404)
    assert saved[1] == []


def test_unlisted_artifact_no_document_read(saved):
    with TestClient(app) as client:
        result = client.get(
            f"{BASE}/documents/140120261007000000/{'a' * 64}", headers=AUTH
        )
        assert result.status_code == 404
    assert len(saved[1]) == 2


@pytest.mark.parametrize(
    "kind",
    [
        "bad_snapshot",
        "missing_snapshot",
        "wrong_code",
        "duplicate_key",
        "bad_count",
        "oversized",
        "unknown_field",
        "invalid_date",
    ],
)
def test_manifest_corruption_fails_closed(saved, kind):
    objects, _, _, _, manifest = saved
    index = f"{PREFIX}/by-code/1234/manifest.json"
    snapshot = f"{PREFIX}/manifests/{digest(objects[index])}.json"
    if kind == "bad_snapshot":
        objects[snapshot] += b" "
    elif kind == "missing_snapshot":
        del objects[snapshot]
    elif kind == "duplicate_key":
        objects[index] = b'{"schema":"x","schema":"y"}'
    elif kind == "oversized":
        objects[index] = b" " * (MAX_MANIFEST_BYTES + 1)
    else:
        if kind == "wrong_code":
            manifest["security_code"] = "9999"
        if kind == "bad_count":
            manifest["entries"] *= 21
        if kind == "unknown_field":
            manifest["arbitrary_key"] = "evil"
        if kind == "invalid_date":
            manifest["entries"][0]["disclosure_date"] = "20261007"
        objects[index] = canonical(manifest)
    with TestClient(app) as client:
        result = client.get(BASE, headers=AUTH)
        assert result.status_code == 503
        assert result.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize(
    "mutation",
    [
        "sha",
        "issuer",
        "date",
        "id",
        "source_hash",
        "extraction",
        "raw_retained",
        "packet_key",
    ],
)
def test_artifact_corruption_fails_closed(saved, mutation):
    objects, _, entry, artifact, manifest = saved
    payload = json.loads(artifact)
    if mutation == "sha":
        payload["observations"][0]["amount"]["amount_per_share"] = "81"
    if mutation == "issuer":
        payload["primary_disclosure"]["source_security_code"] = "99990"
    if mutation == "date":
        payload["primary_disclosure"]["date"] = "2026-10-08"
    if mutation == "id":
        payload["primary_disclosure"]["id"] = "140120261007000000"
    if mutation == "source_hash":
        payload["source_artifacts"][0]["content_sha256"] = "b" * 64
    if mutation == "extraction":
        payload["extraction"]["status"] = "parsed"
    if mutation == "raw_retained":
        payload["source_artifacts"][0]["raw_retention"] = "retained_private"
    if mutation == "packet_key":
        payload["source_artifacts"][0]["private_evidence_key"] = "sources/local.zip"
    changed = canonical(payload)
    if mutation != "sha":
        entry["artifact_sha256"], entry["artifact_bytes"] = (
            digest(changed),
            len(changed),
        )
        body = canonical(manifest)
        objects[f"{PREFIX}/by-code/1234/manifest.json"] = body
        objects[f"{PREFIX}/manifests/{digest(body)}.json"] = body
    objects[
        f"{PREFIX}/documents/{entry['disclosure_id']}/{entry['artifact_sha256']}.json"
    ] = changed
    with TestClient(app) as client:
        result = client.get(
            f"{BASE}/documents/{entry['disclosure_id']}/{entry['artifact_sha256']}",
            headers=AUTH,
        )
        assert result.status_code == 503


def test_storage_dedicated_settings_before_client(monkeypatch):
    for suffix in ("BUCKET", "ENDPOINT", "ACCESS_KEY_ID", "SECRET_ACCESS_KEY"):
        monkeypatch.setattr(config, f"DIVIDEND_SOURCE_PRIVATE_{suffix}", "")
    with pytest.raises(RuntimeError):
        dividend_source_storage._read_sync("safe-key", 12)


def test_bounded_storage_closes_body_and_client(monkeypatch):
    import boto3

    class Stream(io.BytesIO):
        def read(self, count):
            assert count == 1
            return super().read(count)

    stream = Stream(b"123456")

    class Client:
        closed = False

        def get_object(self, **kwargs):
            return {"Body": stream, "ContentLength": 6}

        def close(self):
            self.closed = True

    client = Client()
    monkeypatch.setattr(boto3, "client", lambda *a, **kw: client)
    for suffix in ("BUCKET", "ENDPOINT", "ACCESS_KEY_ID", "SECRET_ACCESS_KEY"):
        monkeypatch.setattr(config, f"DIVIDEND_SOURCE_PRIVATE_{suffix}", "synthetic")
    with pytest.raises(ValueError):
        dividend_source_storage._read_sync("key", 4)
    assert stream.closed and client.closed


def test_openapi_declares_exact_manifest_contract(saved):
    with TestClient(app) as client:
        spec = client.get("/openapi.json").json()
    assert "/private/tdnet/dividend-sources/{security_code}" in spec["paths"]
    assert len(spec["components"]["schemas"]["Manifest"]["properties"]) == 3


def test_manifest_rejects_conflicting_dates_for_same_disclosure(saved):
    objects, _, entry, _, manifest = saved
    second = dict(entry)
    second["disclosure_date"] = "2026-10-08"
    second["artifact_sha256"] = "c" * 64
    manifest["entries"].append(second)
    body = canonical(manifest)
    objects[f"{PREFIX}/by-code/1234/manifest.json"] = body
    objects[f"{PREFIX}/manifests/{digest(body)}.json"] = body
    with TestClient(app) as client:
        result = client.get(BASE, headers=AUTH)
        assert result.status_code == 503


def test_manifest_allows_full_200_source_hash_bound():
    from app.dividend_source_wire import Entry

    value = {
        "disclosure_id": "140120261007123456",
        "disclosure_date": "2026-10-07",
        "artifact_sha256": "a" * 64,
        "artifact_bytes": 1,
        "extraction_status": "partial",
        "source_input_sha256": [f"{i:064x}" for i in range(200)],
    }
    assert len(Entry.model_validate(value).source_input_sha256) == 200


def _install_storage_client(monkeypatch, stream, length):
    import boto3

    class Client:
        closed = False

        def get_object(self, **kwargs):
            return {"Body": stream, "ContentLength": length}

        def close(self):
            self.closed = True

    client = Client()
    monkeypatch.setattr(boto3, "client", lambda *a, **kw: client)
    for suffix in ("BUCKET", "ENDPOINT", "ACCESS_KEY_ID", "SECRET_ACCESS_KEY"):
        monkeypatch.setattr(config, f"DIVIDEND_SOURCE_PRIVATE_{suffix}", "synthetic")
    return client


def test_storage_slow_trickle_has_elapsed_deadline(monkeypatch):
    ticks = [0]

    class SlowStream(io.BytesIO):
        calls = 0

        def read(self, size):
            assert size == 1
            self.calls += 1
            ticks[0] += 9
            return super().read(size)

    stream = SlowStream(b"1234567890")
    client = _install_storage_client(monkeypatch, stream, 10)
    monkeypatch.setattr(dividend_source_storage.time, "monotonic", lambda: ticks[0])
    with pytest.raises(ValueError, match="elapsed budget"):
        dividend_source_storage._read_sync("key", 10)
    assert stream.calls == 4 and ticks[0] == 36
    assert stream.closed and client.closed
    assert dividend_source_storage._READ_SLOT.acquire(blocking=False)
    dividend_source_storage._READ_SLOT.release()


def test_storage_one_byte_reads_preserve_exact_bytes(monkeypatch):
    class CheckedStream(io.BytesIO):
        def read(self, size):
            assert size == 1
            return super().read(size)

    stream = CheckedStream(b"exact bytes\n")
    client = _install_storage_client(monkeypatch, stream, 12)
    assert dividend_source_storage._read_sync("key", 12) == b"exact bytes\n"
    assert stream.closed and client.closed


@pytest.mark.asyncio
async def test_cancelled_caller_keeps_worker_slot_until_thread_exits(monkeypatch):
    import asyncio
    import threading

    entered, release = threading.Event(), threading.Event()
    done = threading.Event()

    class BlockingStream(io.BytesIO):
        first = True

        def read(self, size):
            assert size == 1
            if self.first:
                self.first = False
                entered.set()
                if not release.wait(timeout=5):
                    raise RuntimeError("test worker release deadline")
            return super().read(size)

        def close(self):
            super().close()
            done.set()

    stream = BlockingStream(b"x")
    client = _install_storage_client(monkeypatch, stream, 1)
    caller = asyncio.create_task(dividend_source_storage.read_bytes("key", 1))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        for _ in range(3):
            with pytest.raises(RuntimeError, match="busy"):
                await dividend_source_storage.read_bytes("key", 1)
        assert not stream.closed and not client.closed
    finally:
        release.set()
        assert await asyncio.to_thread(done.wait, 2)
        # Closing the body precedes client close and releasing the slot.
        for _ in range(100):
            if dividend_source_storage._READ_SLOT.acquire(blocking=False):
                dividend_source_storage._READ_SLOT.release()
                break
            await asyncio.sleep(0.01)
        else:
            pytest.fail("worker slot was not released after completion")
    assert stream.closed and client.closed
