from __future__ import annotations

import importlib
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

_FIXTURE = (
    Path(__file__).parent / "fixtures" / "yutai_launch_display_latest_real_shape.json"
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
    import app.routers.yutai_launch_display as router_mod

    importlib.reload(config_mod)
    importlib.reload(auth_mod)
    importlib.reload(private_r2_mod)
    importlib.reload(router_mod)
    importlib.reload(main_mod)
    with TestClient(main_mod.app) as test_client:
        yield test_client


def _payload() -> dict:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _manifest_payload() -> dict:
    return {
        "schema_version": 1,
        "generated_at": "2026-07-22T14:57:25.239015Z",
        "source": "market_info_yutai_launch_display",
        "latest_month": "2026-09",
        "latest_path": "latest.json",
        "months": [
            {
                "month": "2026-09",
                "path": "2026-09.json",
                "count": 288,
                "conditions_available": 42,
                "auto_calculable": 33,
                "requires_user_valuation": 9,
            }
        ],
    }


def test_latest_requires_bearer_token(private_client):
    response = private_client.get("/yutai/launch-display/latest")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["cache-control"] == "private, no-store"


def test_latest_returns_real_artifact_shape(private_client):
    payload = _payload()
    with patch(
        "app.routers.yutai_launch_display.cache.get_manifest",
        new=AsyncMock(return_value=payload),
    ) as get_manifest:
        response = private_client.get(
            "/yutai/launch-display/latest",
            headers={"Authorization": "Bearer test-server-secret"},
        )

    assert response.status_code == 200
    assert response.json() == payload
    assert response.headers["cache-control"] == "private, no-store"
    get_manifest.assert_awaited_once()


def test_manifest_returns_launch_display_manifest(private_client):
    payload = _manifest_payload()
    with patch(
        "app.routers.yutai_launch_display.cache.get_manifest",
        new=AsyncMock(return_value=payload),
    ) as get_manifest:
        response = private_client.get(
            "/yutai/launch-display/manifest",
            headers={"Authorization": "Bearer test-server-secret"},
        )

    assert response.status_code == 200
    assert response.json() == payload
    assert response.headers["cache-control"] == "private, no-store"
    get_manifest.assert_awaited_once()


def test_monthly_uses_private_month_object(private_client):
    payload = _payload()
    with patch(
        "app.routers.yutai_launch_display.private_r2.fetch_json",
        new=AsyncMock(return_value=payload),
    ) as fetch_json:
        response = private_client.get(
            "/yutai/launch-display/monthly/2026-09",
            headers={"Authorization": "Bearer test-server-secret"},
        )

    assert response.status_code == 200
    fetch_json.assert_awaited_once_with("yutai/launch-display/2026-09.json")


def test_latest_fails_closed_when_private_r2_is_not_configured(private_client):
    with patch(
        "app.routers.yutai_launch_display.cache.get_manifest",
        new=AsyncMock(
            side_effect=RuntimeError(
                "missing required env var: YUTAI_STOCK_PRICES_PRIVATE_BUCKET"
            )
        ),
    ):
        response = private_client.get(
            "/yutai/launch-display/latest",
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
        "app.routers.yutai_launch_display.cache.get_manifest",
        new=AsyncMock(side_effect=upstream_error),
    ):
        response = private_client.get(
            "/yutai/launch-display/latest",
            headers={"Authorization": "Bearer test-server-secret"},
        )

    assert response.status_code == expected_status
    assert response.headers["cache-control"] == "private, no-store"
