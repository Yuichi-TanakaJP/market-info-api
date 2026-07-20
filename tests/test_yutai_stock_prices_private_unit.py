from __future__ import annotations

import importlib
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient


_FIXTURE = (
    Path(__file__).parent / "fixtures" / "yutai_stock_prices_latest_real_shape.json"
)


@pytest.fixture()
def private_client(monkeypatch):
    monkeypatch.setenv("R2_PUBLIC_BASE_URL", "https://r2.example.com")
    monkeypatch.setenv("YUTAI_STOCK_PRICES_API_KEY", "test-server-secret")
    monkeypatch.setenv("YUTAI_STOCK_PRICES_PRIVATE_BUCKET", "private-bucket")
    monkeypatch.setenv(
        "YUTAI_STOCK_PRICES_PRIVATE_ENDPOINT",
        "https://account.r2.cloudflarestorage.com",
    )
    monkeypatch.setenv("YUTAI_STOCK_PRICES_PRIVATE_ACCESS_KEY_ID", "access-key")
    monkeypatch.setenv("YUTAI_STOCK_PRICES_PRIVATE_SECRET_ACCESS_KEY", "secret-key")

    import app.auth as auth_mod
    import app.config as config_mod
    import app.main as main_mod
    import app.private_r2 as private_r2_mod
    import app.routers.yutai_stock_prices as router_mod

    importlib.reload(config_mod)
    importlib.reload(auth_mod)
    importlib.reload(private_r2_mod)
    importlib.reload(router_mod)
    importlib.reload(main_mod)
    with TestClient(main_mod.app) as test_client:
        yield test_client


def _payload() -> dict:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def test_latest_requires_bearer_token(private_client):
    response = private_client.get("/yutai/stock-prices/latest")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["cache-control"] == "private, no-store"


def test_latest_rejects_invalid_bearer_token(private_client):
    response = private_client.get(
        "/yutai/stock-prices/latest",
        headers={"Authorization": "Bearer wrong-secret"},
    )

    assert response.status_code == 401


def test_latest_returns_real_artifact_shape(private_client):
    payload = _payload()
    with patch(
        "app.routers.yutai_stock_prices.cache.get_manifest",
        new=AsyncMock(return_value=payload),
    ) as get_manifest:
        response = private_client.get(
            "/yutai/stock-prices/latest",
            headers={"Authorization": "Bearer test-server-secret"},
        )

    assert response.status_code == 200
    assert response.json() == payload
    assert response.headers["cache-control"] == "private, no-store"
    get_manifest.assert_awaited_once()


def test_latest_fails_closed_when_server_secret_is_missing(
    private_client,
    monkeypatch,
):
    monkeypatch.setattr("app.auth.config.YUTAI_STOCK_PRICES_API_KEY", None)

    response = private_client.get(
        "/yutai/stock-prices/latest",
        headers={"Authorization": "Bearer test-server-secret"},
    )

    assert response.status_code == 503
    assert response.headers["cache-control"] == "private, no-store"


def test_latest_fails_closed_when_private_r2_is_not_configured(private_client):
    with patch(
        "app.routers.yutai_stock_prices.cache.get_manifest",
        new=AsyncMock(
            side_effect=RuntimeError(
                "missing required env var: YUTAI_STOCK_PRICES_PRIVATE_BUCKET"
            )
        ),
    ):
        response = private_client.get(
            "/yutai/stock-prices/latest",
            headers={"Authorization": "Bearer test-server-secret"},
        )

    assert response.status_code == 503
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize(
    ("error_code", "expected_status"),
    [
        ("NoSuchKey", 404),
        ("NoSuchBucket", 502),
    ],
)
def test_latest_distinguishes_missing_object_from_missing_bucket(
    private_client,
    error_code,
    expected_status,
):
    upstream_error = ClientError(
        {
            "Error": {"Code": error_code, "Message": error_code},
            "ResponseMetadata": {"HTTPStatusCode": 404},
        },
        "GetObject",
    )
    with patch(
        "app.routers.yutai_stock_prices.cache.get_manifest",
        new=AsyncMock(side_effect=upstream_error),
    ):
        response = private_client.get(
            "/yutai/stock-prices/latest",
            headers={"Authorization": "Bearer test-server-secret"},
        )

    assert response.status_code == expected_status
    assert response.headers["cache-control"] == "private, no-store"


def test_private_r2_uses_configured_bucket_and_key(monkeypatch):
    import app.private_r2 as private_r2_mod

    body = json.dumps(_payload()).encode("utf-8")

    class FakeBody:
        def read(self):
            return body

    class FakeClient:
        def __init__(self):
            self.request = None

        def get_object(self, **kwargs):
            self.request = kwargs
            return {"Body": FakeBody()}

    fake_client = FakeClient()
    monkeypatch.setattr(
        private_r2_mod.config,
        "YUTAI_STOCK_PRICES_PRIVATE_BUCKET",
        "private-bucket",
    )
    monkeypatch.setattr(private_r2_mod, "_build_client", lambda: fake_client)

    result = private_r2_mod._fetch_json_sync("yutai/stock-prices/latest.json")

    assert result == _payload()
    assert fake_client.request == {
        "Bucket": "private-bucket",
        "Key": "yutai/stock-prices/latest.json",
    }
