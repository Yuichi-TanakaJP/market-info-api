from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("R2_PUBLIC_BASE_URL", "https://r2.example.com")

    import app.config as cfg_mod
    import app.r2 as r2_mod
    import app.routers.jpx_listed_companies as router_mod

    importlib.reload(cfg_mod)
    importlib.reload(r2_mod)
    importlib.reload(router_mod)

    import app.main as main_mod

    importlib.reload(main_mod)
    with TestClient(main_mod.app) as test_client:
        yield test_client


def _items(as_of: str = "2026-08-31") -> list[dict]:
    return [
        {
            "as_of_date": as_of,
            "code": "1306",
            "name": "ＮＥＸＴ　ＦＵＮＤＳ　ＴＯＰＩＸ連動型上場投信",
            "display_name": "NEXT FUNDS TOPIX連動型上場投信",
            "abbrev_name": "NEXT FUNDS TOPIX連動型上場投信",
            "market": "ETF・ETN",
            "sector": None,
        },
        {
            "as_of_date": as_of,
            "code": "7203",
            "name": "トヨタ自動車",
            "display_name": "トヨタ自動車",
            "abbrev_name": "トヨタ自動車",
            "market": "プライム（内国株式）",
            "sector": "輸送用機器",
        },
    ]


def test_jpx_listed_latest(client) -> None:
    with patch(
        "app.routers.jpx_listed_companies.cache.get_manifest",
        new=AsyncMock(return_value=_items()),
    ):
        response = client.get("/reference/jpx-listed-companies/latest")

    assert response.status_code == 200
    assert [row["code"] for row in response.json()] == ["1306", "7203"]
    assert response.headers["cache-control"]


def test_jpx_listed_manifest(client) -> None:
    manifest = {
        "schema_version": "jpx-listed-companies-manifest-v1",
        "generated_at": "2026-09-20T00:00:00Z",
        "latest": "2026-08-31",
        "entries": [
            {
                "date": "2026-08-31",
                "sha256": "a" * 64,
                "record_count": 4441,
            }
        ],
    }
    with patch(
        "app.routers.jpx_listed_companies.cache.get_manifest",
        new=AsyncMock(return_value=manifest),
    ):
        response = client.get("/reference/jpx-listed-companies/manifest")

    assert response.status_code == 200
    assert response.json()["latest"] == "2026-08-31"
    assert response.json()["entries"][0]["record_count"] == 4441
    assert response.headers["cache-control"]


def test_jpx_listed_dated_snapshot_is_immutable_cached(client) -> None:
    with patch(
        "app.routers.jpx_listed_companies.cache.get_day",
        new=AsyncMock(return_value=_items()),
    ):
        response = client.get("/reference/jpx-listed-companies/2026-08-31")

    assert response.status_code == 200
    assert response.json()[1]["code"] == "7203"
    assert "immutable" in response.headers["cache-control"]


def test_jpx_listed_dated_snapshot_rejects_invalid_date(client) -> None:
    response = client.get("/reference/jpx-listed-companies/not-a-date")

    assert response.status_code == 422


def test_jpx_listed_latest_maps_r2_not_found_to_404(client) -> None:
    request = httpx.Request(
        "GET",
        "https://r2.example.com/reference/jpx-listed-companies/latest.json",
    )
    upstream = httpx.Response(404, request=request)
    error = httpx.HTTPStatusError(
        "not found",
        request=request,
        response=upstream,
    )

    with patch(
        "app.routers.jpx_listed_companies.cache.get_manifest",
        new=AsyncMock(side_effect=error),
    ):
        response = client.get("/reference/jpx-listed-companies/latest")

    assert response.status_code == 404
    assert response.json()["detail"] == "jpx listed companies latest not found"


def test_jpx_listed_upstream_failure_does_not_leak_url_or_body(client) -> None:
    request = httpx.Request(
        "GET",
        "https://r2.example.com/reference/jpx-listed-companies/manifest.json?secret=x",
    )
    upstream = httpx.Response(
        502,
        request=request,
        text="upstream-debug-secret-looking-body",
    )
    error = httpx.HTTPStatusError(
        "bad gateway",
        request=request,
        response=upstream,
    )

    with patch(
        "app.routers.jpx_listed_companies.cache.get_manifest",
        new=AsyncMock(side_effect=error),
    ):
        response = client.get("/reference/jpx-listed-companies/manifest")

    assert response.status_code == 502
    assert response.json() == {
        "detail": "jpx listed companies manifest unavailable"
    }
    assert "r2.example.com" not in response.text
    assert "upstream-debug-secret-looking-body" not in response.text
