import asyncio
import os
from threading import Event
from hashlib import sha256
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

os.environ.setdefault("R2_PUBLIC_BASE_URL", "https://example.invalid")

from app import config
from app.main import app
from app.routers import edinet_financials

BASE = "/private/edinet/financials"
AUTH = {"Authorization": "Bearer edinet-test-only"}


@pytest.fixture
def read(monkeypatch):
    monkeypatch.setattr(config, "EDINET_FINANCIAL_API_KEY", "edinet-test-only")
    monkeypatch.setattr(config, "DIVIDEND_SOURCE_API_KEY", "dividend-test-only")
    reader = AsyncMock()
    monkeypatch.setattr(edinet_financials.storage, "read_edinet_bytes", reader)
    return reader


@pytest.mark.parametrize("real", [False, True], ids=["producer-shape", "saved-original"])
def test_exact_private_edinet_artifact(read, real):
    if real:
        filepath = os.getenv("EDINET_FINANCIAL_REAL_ARTIFACT_TEST_FILE")
        if not filepath:
            pytest.skip("configure locally replayed official specimen")
        fixture = Path(filepath)
    else:
        fixture = Path(__file__).parent / "fixtures/edinet_financial_period_compact_producer_shape.json"
    content = fixture.read_bytes()
    digest = sha256(content).hexdigest()
    read.return_value = content
    client = TestClient(app)
    response = client.get(f"{BASE}/S100T65I/{digest}", headers=AUTH)
    assert response.status_code == 200
    assert response.content == content
    assert response.headers["X-Content-SHA256"] == digest
    assert response.headers["Cache-Control"] == "private, no-store"
    read.assert_awaited_once_with(
        "edinet/financial-evidence/v1/daily/derived/period_compact/" + digest,
        4 * 1024 * 1024,
    )
    assert client.get(f"{BASE}/S100ABCD/{digest}", headers=AUTH).status_code == 404


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer dividend-test-only"}])
def test_edinet_separate_auth_scope(read, headers):
    response = TestClient(app).get(f"{BASE}/S100T65I/{'0' * 64}", headers=headers)
    assert response.status_code == 401
    assert response.headers["Cache-Control"] == "private, no-store"
    read.assert_not_called()


def test_edinet_unsafe_selector_and_missing_config_stop_before_storage(read, monkeypatch):
    client = TestClient(app)
    assert client.get(f"{BASE}/invalid/{'0' * 64}", headers=AUTH).status_code == 400
    monkeypatch.setattr(config, "EDINET_FINANCIAL_API_KEY", "")
    assert client.get(f"{BASE}/S100T65I/{'0' * 64}", headers=AUTH).status_code == 503
    read.assert_not_called()


def test_edinet_distinguishes_missing_from_access_or_data_failure(read):
    client = TestClient(app)
    path = f"{BASE}/S100T65I/{'0' * 64}"
    read.side_effect = ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
    assert client.get(path, headers=AUTH).status_code == 404
    read.side_effect = ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject")
    assert client.get(path, headers=AUTH).status_code == 503
    read.side_effect = None
    read.return_value = b"{}"
    assert client.get(path, headers=AUTH).status_code == 503


def test_edinet_storage_rejects_non_r2_endpoint(monkeypatch):
    monkeypatch.setattr(config, "EDINET_FINANCIAL_PRIVATE_ENDPOINT", "https://example.invalid")
    with pytest.raises(ValueError, match="endpoint"):
        edinet_financials.storage._read_edinet_sync("unused", 100)


@pytest.mark.asyncio
async def test_edinet_storage_dedicated_scope_and_slot_survives_cancel(monkeypatch):
    reader = edinet_financials.storage
    endpoint = "https://" + "a" * 32 + ".r2.cloudflarestorage.com"
    monkeypatch.setattr(config, "EDINET_FINANCIAL_PRIVATE_ENDPOINT", endpoint)
    monkeypatch.setattr(config, "EDINET_FINANCIAL_PRIVATE_ACCESS_KEY_ID", "edinet-test-id")
    monkeypatch.setattr(config, "EDINET_FINANCIAL_PRIVATE_SECRET_ACCESS_KEY", "edinet-test-secret")
    monkeypatch.setattr(config, "DIVIDEND_SOURCE_PRIVATE_ACCESS_KEY_ID", "other-test-id")
    entered, release, finished = Event(), Event(), Event()

    def worker(key, limit, *, available_chunks, private_config):
        assert (key, limit, available_chunks) == ("fixed-key", 100, True)
        assert private_config == ({
            "BUCKET": "mini-tools-private",
            "ENDPOINT": endpoint,
            "ACCESS_KEY_ID": "edinet-test-id",
            "SECRET_ACCESS_KEY": "edinet-test-secret",
        }, "auto")
        entered.set()
        try:
            assert release.wait(3)
            return b"{}"
        finally:
            finished.set()

    monkeypatch.setattr(reader, "_read_claimed", worker)
    first = asyncio.create_task(reader.read_edinet_bytes("fixed-key", 100))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        with pytest.raises(RuntimeError, match="busy"):
            await reader.read_edinet_bytes("fixed-key", 100)
    finally:
        release.set()
    assert await asyncio.to_thread(finished.wait, 2)
    # Wait for the wrapper's finally, which releases the slot after worker exit.
    for _ in range(50):
        try:
            assert await reader.read_edinet_bytes("fixed-key", 100) == b"{}"
            break
        except RuntimeError as exc:
            assert "busy" in str(exc)
            await asyncio.sleep(0.01)
    else:
        pytest.fail("EDINET storage slot did not recover")


@pytest.mark.parametrize("body", [
    b'{"schema_version":"edinet-financial-compact-period-integrated-v1","doc_id":"S100T65I","doc_id":"S100T65I","fact_count":0,"facts":[]}',
    b'{"schema_version":"edinet-financial-compact-period-integrated-v1","doc_id":"S100T65I","fact_count":1,"facts":[NaN]}',
])
def test_edinet_rejects_ambiguous_producer_json_even_with_matching_digest(read, body):
    read.return_value = body
    digest = sha256(body).hexdigest()
    assert TestClient(app).get(f"{BASE}/S100T65I/{digest}", headers=AUTH).status_code == 503
