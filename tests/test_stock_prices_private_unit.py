from copy import deepcopy
import io
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

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


def test_private_storage_is_scoped_and_closes_response(monkeypatch, artifact):
    import boto3

    from app import config, private_r2

    values = {
        "STOCK_PRICES_PRIVATE_BUCKET": "test-private-bucket",
        "STOCK_PRICES_PRIVATE_ENDPOINT": "https://private-r2.example.invalid",
        "STOCK_PRICES_PRIVATE_ACCESS_KEY_ID": "test-access",
        "STOCK_PRICES_PRIVATE_SECRET_ACCESS_KEY": "test-secret",
        "STOCK_PRICES_PRIVATE_REGION": "auto",
    }
    for name, value in values.items():
        monkeypatch.setattr(config, name, value)
    raw = json.dumps(artifact).encode()
    stream = io.BytesIO(raw)
    client = Mock()
    client.get_object.return_value = {"Body": stream, "ContentLength": len(raw)}
    build = Mock(return_value=client)
    monkeypatch.setattr(boto3, "client", build)

    assert private_r2._stock_prices_json_sync("stock-prices/latest.json") == artifact
    client.get_object.assert_called_once_with(Bucket="test-private-bucket", Key="stock-prices/latest.json")
    assert build.call_args.kwargs["endpoint_url"] == values["STOCK_PRICES_PRIVATE_ENDPOINT"]
    assert stream.closed
    client.close.assert_called_once()

    monkeypatch.setattr(config, "STOCK_PRICES_PRIVATE_BUCKET", "")
    build.reset_mock()
    with pytest.raises(private_r2.StockPriceStorageNotConfigured):
        private_r2._stock_prices_json_sync("stock-prices/latest.json")
    build.assert_not_called()


def test_missing_private_storage_is_503(api):
    client, read = api
    from app import private_r2

    read.side_effect = private_r2.StockPriceStorageNotConfigured()
    response = client.get("/stock-prices/latest", headers=_AUTH)
    assert response.status_code == 503
    assert response.headers["Cache-Control"] == _NO_STORE

@pytest.mark.parametrize(("body", "declared"), [
    (b"{}", 4 * 1024 * 1024 + 1),
    (b"{}", 1),
    (b'{"schema_version":1,"schema_version":2}', None),
])
def test_private_storage_rejects_oversize_mismatched_or_ambiguous_json(
    monkeypatch, body, declared,
):
    import boto3

    from app import config, private_r2

    for suffix in ("BUCKET", "ENDPOINT", "ACCESS_KEY_ID", "SECRET_ACCESS_KEY"):
        monkeypatch.setattr(config, "STOCK_PRICES_PRIVATE_" + suffix, "test")
    stream = io.BytesIO(body)
    client = Mock()
    client.get_object.return_value = {
        "Body": stream,
        "ContentLength": len(body) if declared is None else declared,
    }
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: client)
    with pytest.raises(ValueError):
        private_r2._stock_prices_json_sync("stock-prices/latest.json")
    assert stream.closed
    client.close.assert_called_once()
