from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("R2_PUBLIC_BASE_URL", "https://r2.example.com")

    import app.config as cfg_mod
    import app.r2 as r2_mod
    import app.routers.tdnet_router_events as router_mod

    importlib.reload(cfg_mod)
    importlib.reload(r2_mod)
    importlib.reload(router_mod)

    import app.main as main_mod

    importlib.reload(main_mod)
    with TestClient(main_mod.app) as test_client:
        yield test_client


def _payload(date: str) -> dict:
    return {
        "schema_version": "tdnet-router-events-v1",
        "target_date": date,
        "total_count": 1,
        "items": [
            {
                "router_event_id": "tdnet-router-test",
                "tdnet_disclosure_id": "140120260920123456",
                "source": "tdnet",
                "event_type": "dividend_change",
                "disclosure_date": date,
                "disclosure_time": "15:00",
                "security_code": "72030",
                "title": "配当予想の修正",
                "disclosure_category": "その他",
                "source_url": "https://example.test/doc.pdf",
            }
        ],
    }


def test_router_manifest(client) -> None:
    manifest = {
        "schema_version": "tdnet-router-events-manifest-v1",
        "generated_at": "2026-09-20T00:00:00Z",
        "latest": "2026-09-20",
        "entries": [
            {
                "date": "2026-09-20",
                "sha256": "a" * 64,
                "event_count": 1,
            }
        ],
    }
    with patch(
        "app.routers.tdnet_router_events.cache.get_manifest",
        new=AsyncMock(return_value=manifest),
    ):
        response = client.get("/tdnet/router-events/manifest")

    assert response.status_code == 200
    assert response.json()["latest"] == "2026-09-20"
    assert response.headers["cache-control"]


def test_router_latest(client) -> None:
    with patch(
        "app.routers.tdnet_router_events.cache.get_manifest",
        new=AsyncMock(return_value=_payload("2026-09-20")),
    ):
        response = client.get("/tdnet/router-events/latest")

    assert response.status_code == 200
    assert response.json()["items"][0]["event_type"] == "dividend_change"


def test_router_dated_payload_is_immutable_cached(client) -> None:
    with patch(
        "app.routers.tdnet_router_events.cache.get_day",
        new=AsyncMock(return_value=_payload("2026-09-20")),
    ):
        response = client.get("/tdnet/router-events/2026-09-20")

    assert response.status_code == 200
    assert response.json()["target_date"] == "2026-09-20"
    assert response.headers["cache-control"]


def test_router_dated_payload_rejects_invalid_date(client) -> None:
    response = client.get("/tdnet/router-events/not-a-date")
    assert response.status_code == 422
