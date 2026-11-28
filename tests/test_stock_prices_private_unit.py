import asyncio
from copy import deepcopy
import threading
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx

from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
import pytest


_AUTH = {"Authorization": "Bearer dedicated-test-token"}
_NO_STORE = "private, no-store"
_FIXTURE = Path(__file__).parent / "fixtures" / "stock_prices_private_real_shape.json"


@pytest.fixture
def artifact():
    return json.loads(_FIXTURE.read_text(encoding="utf-8-sig"))


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("R2_PUBLIC_BASE_URL", "https://r2.example.invalid")
    from app import config, private_r2
    from app.main import app

    monkeypatch.setattr(config, "STOCK_PRICES_API_KEY", "dedicated-test-token")
    monkeypatch.setattr(config, "YUTAI_STOCK_PRICES_API_KEY", "yutai-test-token")
    read = AsyncMock()
    monkeypatch.setattr(private_r2, "fetch_stock_prices_json", read)
    with TestClient(app) as client:
        yield client, read


def test_withdrawn_or_other_scope_token_never_reads_storage(api, monkeypatch):
    client, read = api
    for headers in ({}, {"Authorization": "Bearer yutai-test-token"}):
        response = client.get("/stock-prices/latest", headers=headers)
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"
        assert response.headers["Cache-Control"] == _NO_STORE
    monkeypatch.setattr("app.config.STOCK_PRICES_API_KEY", "")
    response = client.get("/stock-prices/latest", headers=_AUTH)
    assert response.status_code == 503
    assert response.headers["Cache-Control"] == _NO_STORE
    read.assert_not_called()


def test_both_routes_project_exact_artifact_shape_and_reread(api, artifact):
    client, read = api
    newer = deepcopy(artifact)
    newer["revision"] += 1
    newer["records"][0]["price_jpy"] += 1
    read.side_effect = [artifact, newer, newer]
    first = client.get("/stock-prices/latest", headers=_AUTH)
    expected = {k: artifact[k] for k in ("schema_version", "trading_date", "revision")}
    expected["records"] = [
        {k: record[k] for k in ("code", "price_jpy")} for record in artifact["records"]
    ]
    assert first.json() == expected
    revised = client.get("/stock-prices/latest", headers=_AUTH, params={"code": "1234"})
    assert revised.json()["records"] == [{"code": "1234", "price_jpy": 176.5}]
    assert revised.json()["revision"] == 3
    absent = client.get("/stock-prices/2026-11-27", headers=_AUTH, params={"code": "0000"})
    assert absent.status_code == 200
    assert absent.json()["records"] == []
    assert all(response.headers["Cache-Control"] == _NO_STORE for response in (first, revised, absent))
    assert [pos.args for pos in read.await_args_list] == [
        ("stock-prices/latest.json",),
        ("stock-prices/latest.json",),
        ("stock-prices/daily/2026-11-27.json",),
    ]


@pytest.mark.parametrize("selector", ["/stock-prices/2026-02-30", "/stock-prices/latest?code=../1234"])
def test_bad_selectors_do_not_read_storage(api, selector):
    client, read = api
    response = client.get(selector, headers=_AUTH)
    assert response.status_code == 422
    assert response.headers["Cache-Control"] == _NO_STORE
    read.assert_not_called()


@pytest.mark.parametrize("change", [
    {"trading_date": "2026-11-26"},
    {"revision": True},
    {"schema_version": True},
    {"records": []},
    {"records": [{"code": "1234", "price_jpy": "175.5"}]},
    {"records": [{"code": "1234", "price_jpy": float("inf")}]},
    {"records": [{"code": "1234", "price_jpy": 1}, {"code": "1234", "price_jpy": 2}]},
])
def test_invalid_artifacts_cannot_become_empty_or_stale_success(api, artifact, change):
    client, read = api
    read.return_value = artifact | change
    response = client.get("/stock-prices/2026-11-27", headers=_AUTH, params={"code": "1234"})
    assert response.status_code == 502
    assert response.headers["Cache-Control"] == _NO_STORE
    assert response.json() == {"detail": "private stock prices unavailable or invalid"}


@pytest.mark.parametrize(("error", "status"), [
    ("NoSuchKey", 404),
    ("NotFound", 502),
    ("NoSuchBucket", 502),
    ("AccessDenied", 502),
])
def test_upstream_errors_have_no_sensitive_details(api, error, status):
    client, read = api
    read.side_effect = ClientError({"Error": {"Code": error, "Message": "internal marker"}}, "GetObject")
    response = client.get("/stock-prices/latest", headers=_AUTH)
    assert response.status_code == status
    assert response.headers["Cache-Control"] == _NO_STORE
    assert "internal marker" not in response.text


@pytest.fixture
def storage(monkeypatch):
    from app import config, private_r2

    endpoint = f"https://{'a' * 32}.r2.cloudflarestorage.com"
    values = {
        "STOCK_PRICES_PRIVATE_BUCKET": "test-private-bucket",
        "STOCK_PRICES_PRIVATE_ENDPOINT": endpoint,
        "STOCK_PRICES_PRIVATE_ACCESS_KEY_ID": "test-access",
        "STOCK_PRICES_PRIVATE_SECRET_ACCESS_KEY": "test-secret",
        "STOCK_PRICES_PRIVATE_REGION": "auto",
    }
    for name, value in values.items():
        monkeypatch.setattr(config, name, value)
    return private_r2, endpoint


class _ByteStream(httpx.AsyncByteStream):
    def __init__(self, data, *, wait=False):
        self.data = data
        self.closed = False
        self.wait = wait

    async def __aiter__(self):
        if self.wait:
            await asyncio.sleep(1)
        yield self.data

    async def aclose(self):
        self.closed = True


def _mock_transport(monkeypatch, private_r2, handler):
    client_cls = httpx.AsyncClient
    factory = Mock(side_effect=lambda **kwargs: client_cls(
        transport=httpx.MockTransport(handler), **kwargs,
    ))
    monkeypatch.setattr(private_r2.httpx, "AsyncClient", factory)
    return factory


@pytest.mark.asyncio
async def test_r2_read_signs_scoped_request_and_closes_response(storage, artifact, monkeypatch):
    private_r2, endpoint = storage
    raw = json.dumps(artifact).encode()
    stream = _ByteStream(raw)
    seen = []

    async def handle(request):
        seen.append(request)
        return httpx.Response(200, headers={"Content-Length": str(len(raw))}, stream=stream)

    factory = _mock_transport(monkeypatch, private_r2, handle)
    assert await private_r2.fetch_stock_prices_json("stock-prices/latest.json") == artifact
    assert str(seen[0].url) == f"{endpoint}/test-private-bucket/stock-prices/latest.json"
    assert seen[0].headers["Authorization"].startswith(
        "AWS4-HMAC-SHA256 Credential=test-access/"
    )
    assert seen[0].headers["Accept-Encoding"] == "identity"
    assert factory.call_args.kwargs["verify"] is True
    assert factory.call_args.kwargs["follow_redirects"] is False
    assert factory.call_args.kwargs["trust_env"] is False
    assert stream.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", [
    "", f"http://{'a' * 32}.r2.cloudflarestorage.com", "https://r2.example.invalid",
    f"https://{'a' * 32}.r2.cloudflarestorage.com/user",
])
async def test_configuration_rejects_untrusted_endpoints(storage, endpoint, monkeypatch):
    private_r2, _ = storage
    monkeypatch.setattr("app.config.STOCK_PRICES_PRIVATE_ENDPOINT", endpoint)
    factory = Mock()
    monkeypatch.setattr(private_r2.httpx, "AsyncClient", factory)
    with pytest.raises(private_r2.StockPriceStorageNotConfigured):
        await private_r2.fetch_stock_prices_json("stock-prices/latest.json")
    factory.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(("body", "declared"), [
    (b"{}", 4 * 1024 * 1024 + 1),
    (b"{}", 1),
    (b'{"schema_version":1,"schema_version":2}', None),
    (b'{"records":[{"code":"1234","price_jpy":175}],"sources":{"value":NaN}}', None),
])
async def test_r2_read_rejects_oversize_mismatched_or_invalid_json(
    storage, monkeypatch, body, declared,
):
    private_r2, _ = storage
    stream = _ByteStream(body)

    async def handle(_request):
        length = len(body) if declared is None else declared
        return httpx.Response(200, headers={"Content-Length": str(length)}, stream=stream)

    _mock_transport(monkeypatch, private_r2, handle)
    with pytest.raises(ValueError):
        await private_r2.fetch_stock_prices_json("stock-prices/latest.json")
    assert stream.closed


@pytest.mark.asyncio
@pytest.mark.parametrize(("code", "exception"), [
    ("NoSuchKey", ClientError), ("NotFound", ValueError), ("NoSuchBucket", ValueError),
])
async def test_only_r2_xml_no_such_key_reports_known_missing_object(
    storage, monkeypatch, code, exception,
):
    private_r2, _ = storage
    stream = _ByteStream(f"<Error><Code>{code}</Code></Error>".encode())

    async def handle(_request):
        return httpx.Response(404, stream=stream)

    _mock_transport(monkeypatch, private_r2, handle)
    with pytest.raises(exception):
        await private_r2.fetch_stock_prices_json("stock-prices/latest.json")
    assert stream.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("slow", ["headers", "error_body"])
async def test_deadline_covers_headers_and_error_bodies_and_releases_capacity(
    storage, monkeypatch, slow,
):
    private_r2, _ = storage
    monkeypatch.setattr(private_r2, "_STOCK_PRICES_READ_SLOTS", threading.BoundedSemaphore(1))
    monkeypatch.setattr(private_r2, "_STOCK_PRICES_DEADLINE", 0.04)
    stream = _ByteStream(b"<Error />", wait=True)
    started = asyncio.Event()

    async def handle(_request):
        started.set()
        if slow == "headers":
            await asyncio.sleep(1)
        return httpx.Response(404, stream=stream)

    _mock_transport(monkeypatch, private_r2, handle)
    pending = asyncio.create_task(private_r2.fetch_stock_prices_json("key"))
    await started.wait()
    with pytest.raises(RuntimeError, match="reader is busy"):
        await private_r2.fetch_stock_prices_json("key")
    with pytest.raises(TimeoutError):
        await pending
    if slow == "error_body":
        assert stream.closed
    assert private_r2._STOCK_PRICES_READ_SLOTS.acquire(blocking=False)
    private_r2._STOCK_PRICES_READ_SLOTS.release()


def test_missing_private_storage_is_503(api):
    client, read = api
    from app import private_r2

    read.side_effect = private_r2.StockPriceStorageNotConfigured()
    response = client.get("/stock-prices/latest", headers=_AUTH)
    assert response.status_code == 503
    assert response.headers["Cache-Control"] == _NO_STORE

@pytest.mark.asyncio
async def test_region_must_match_r2_signing_contract(storage, monkeypatch):
    private_r2, _ = storage
    monkeypatch.setattr("app.config.STOCK_PRICES_PRIVATE_REGION", "us-east-1")
    with pytest.raises(private_r2.StockPriceStorageNotConfigured):
        await private_r2.fetch_stock_prices_json("stock-prices/latest.json")


@pytest.mark.asyncio
@pytest.mark.parametrize(("body", "status"), [
    (b"<Error><Code>NoSuchKey</Code><Code>AccessDenied</Code></Error>", 404),
    (b"<Error><Code><Nested/>NoSuchKey</Code></Error>", 404),
    (b'["' + b"[" * 32_001 + b'"]', 200),
])
async def test_dense_structures_and_ambiguous_missing_codes_fail_closed(
    storage, monkeypatch, body, status,
):
    private_r2, _ = storage

    async def handle(_request):
        return httpx.Response(
            status, headers={"Content-Length": str(len(body))}, stream=_ByteStream(body),
        )

    _mock_transport(monkeypatch, private_r2, handle)
    with pytest.raises(ValueError):
        await private_r2.fetch_stock_prices_json("stock-prices/latest.json")


def test_snapshot_length_limit_precedes_record_validation(artifact):
    from pydantic import ValidationError

    from app.routers.stock_prices import StockPrices

    artifact["records"] = [{}] * 10_001
    with pytest.raises(ValidationError) as exc_info:
        StockPrices.model_validate(artifact)
    errors = exc_info.value.errors()
    assert len(errors) == 1
    assert errors[0]["type"] == "too_long"
