from __future__ import annotations

import importlib
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient


_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((_FIXTURES_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("R2_PUBLIC_BASE_URL", "https://r2.example.com")

    import app.config as cfg_mod
    import app.r2 as r2_mod
    import app.routers.edinet as edinet_mod

    importlib.reload(cfg_mod)
    importlib.reload(r2_mod)
    importlib.reload(edinet_mod)

    import app.main as main_mod

    importlib.reload(main_mod)
    with TestClient(main_mod.app) as test_client:
        yield test_client


def test_large_holding_latest_returns_compact_shape(client):
    payload = _load_fixture("edinet_large_holding_v1_real_shape.json")
    with patch(
        "app.routers.edinet.cache.get_manifest",
        new=AsyncMock(return_value=payload),
    ):
        resp = client.get("/edinet/large-holding/v1/latest")

    assert resp.status_code == 200
    data = resp.json()
    assert data["schema_version"] == "edinet-large-holding-compact-v1"
    assert data["items"][0]["filer_security_code"] == "99990"
    assert data["items"][0]["issuer"]["security_code"] == "1234"
    assert data["items"][0]["aggregate"]["holding_ratio_pct"] == 6.0


def test_large_holding_manifest_returns_dual_digests(client):
    manifest = _load_fixture(
        "edinet_large_holding_v1_manifest_real_shape.json"
    )
    with patch(
        "app.routers.edinet.cache.get_manifest",
        new=AsyncMock(return_value=manifest),
    ):
        resp = client.get("/edinet/large-holding/v1/manifest")

    assert resp.status_code == 200
    data = resp.json()
    assert data["latest"] == "2026-09-20"
    assert len(data["entries"][0]["content_sha256"]) == 64
    assert len(data["entries"][0]["artifact_sha256"]) == 64
    assert data["entries"][0]["item_count"] == 1


def test_large_holding_dated_uses_mutable_cache_class(client):
    payload = _load_fixture("edinet_large_holding_v1_real_shape.json")
    with (
        patch(
            "app.routers.edinet.cache.get_manifest",
            new=AsyncMock(return_value=payload),
        ) as mutable_cache,
        patch(
            "app.routers.edinet.cache.get_day",
            new=AsyncMock(
                side_effect=AssertionError(
                    "immutable day cache must not be used"
                )
            ),
        ),
    ):
        resp = client.get("/edinet/large-holding/v1/2026-09-20")

    assert resp.status_code == 200
    assert mutable_cache.await_count == 1


def test_large_holding_dated_rejects_invalid_date(client):
    resp = client.get("/edinet/large-holding/v1/2026-9-20")
    assert resp.status_code == 422
    assert resp.json()["detail"] == "date must be YYYY-MM-DD format"


def test_large_holding_dated_not_found_returns_404(client):
    request = httpx.Request(
        "GET",
        "https://r2.example.com/edinet/large-holding/v1/2026-09-20.json",
    )
    response = httpx.Response(404, request=request)
    error = httpx.HTTPStatusError(
        "not found",
        request=request,
        response=response,
    )

    with patch(
        "app.routers.edinet.cache.get_manifest",
        new=AsyncMock(side_effect=error),
    ):
        resp = client.get("/edinet/large-holding/v1/2026-09-20")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "edinet large-holding not found: 2026-09-20"
