from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("R2_PUBLIC_BASE_URL", "https://r2.example.com")
    # config はモジュールロード時に評価されるため importlib でリロード
    import importlib
    import app.config as cfg_mod
    importlib.reload(cfg_mod)
    import app.r2 as r2_mod
    importlib.reload(r2_mod)
    import app.routers.ranking as ranking_mod
    import app.routers.nikkei as nikkei_mod
    import app.routers.market_calendar as market_calendar_mod
    import app.routers.topix33 as topix33_mod
    import app.routers.yutai as yutai_mod
    importlib.reload(ranking_mod)
    importlib.reload(nikkei_mod)
    importlib.reload(market_calendar_mod)
    importlib.reload(topix33_mod)
    importlib.reload(yutai_mod)
    from app.main import app
    return TestClient(app)


def test_market_calendar_uses_fixed_latest_object_key(monkeypatch):
    monkeypatch.setenv("R2_PUBLIC_BASE_URL", "https://r2.example.com")

    import importlib
    import app.config as cfg_mod
    import app.routers.market_calendar as market_calendar_mod

    importlib.reload(cfg_mod)
    importlib.reload(market_calendar_mod)

    assert cfg_mod.JPX_CLOSED_OBJECT_KEY == "market_closed/jpx_market_closed_latest.json"


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ranking_manifest(client):
    manifest = {"dates": ["2026-03-28"], "latest": "2026-03-28"}
    with patch("app.routers.ranking.cache.get_manifest", new=AsyncMock(return_value=manifest)):
        resp = client.get("/ranking/manifest")
    assert resp.status_code == 200
    assert resp.json()["latest"] == "2026-03-28"


def test_ranking_day(client):
    day = {"date": "2026-03-28", "records": []}
    with patch("app.routers.ranking.cache.get_day", new=AsyncMock(return_value=day)):
        resp = client.get("/ranking/2026-03-28")
    assert resp.status_code == 200
    assert resp.json()["date"] == "2026-03-28"


def test_nikkei_manifest(client):
    manifest = {"dates": ["2026-03-28"], "latest_date": "2026-03-28", "generated_at": ""}
    with patch("app.routers.nikkei.cache.get_manifest", new=AsyncMock(return_value=manifest)):
        resp = client.get("/nikkei/manifest")
    assert resp.status_code == 200
    assert resp.json()["latest_date"] == "2026-03-28"


def test_nikkei_day(client):
    day = {"date": "2026-03-28", "index": "nikkei225", "records": []}
    with patch("app.routers.nikkei.cache.get_day", new=AsyncMock(return_value=day)):
        resp = client.get("/nikkei/2026-03-28")
    assert resp.status_code == 200
    assert resp.json()["date"] == "2026-03-28"


def test_market_calendar_jpx_closed(client):
    payload = {
        "as_of_date": "2026-04-05",
        "from": "2026-01-01",
        "to": "2027-12-31",
        "days": [
            {"date": "2026-01-01", "market_closed": True, "label": "元日"},
            {"date": "2026-01-02", "market_closed": True, "label": "休業日"},
        ],
    }
    with patch("app.routers.market_calendar.cache.get_manifest", new=AsyncMock(return_value=payload)):
        resp = client.get("/market-calendar/jpx-closed")
    assert resp.status_code == 200
    assert resp.json()["from"] == "2026-01-01"
    assert resp.json()["days"][0]["market_closed"] is True


def test_topix33_manifest(client):
    manifest = {"dates": ["2026-04-01"], "latest_date": "2026-04-01", "generated_at": ""}
    with patch("app.routers.topix33.cache.get_manifest", new=AsyncMock(return_value=manifest)):
        resp = client.get("/topix33/manifest")
    assert resp.status_code == 200
    assert resp.json()["latest_date"] == "2026-04-01"


def test_topix33_day(client):
    day = {
        "date": "2026-04-01",
        "index": "topix33",
        "summary": {"advancers": 20, "decliners": 12, "unchanged": 1},
        "top_positive": [],
        "top_negative": [],
        "sectors": [],
    }
    with patch("app.routers.topix33.cache.get_day", new=AsyncMock(return_value=day)):
        resp = client.get("/topix33/2026-04-01")
    assert resp.status_code == 200
    assert resp.json()["index"] == "topix33"


def test_yutai_manifest(client):
    manifest = {"latest_month": "2026-03", "latest_path": "2026-03.json", "months": []}
    with patch("app.routers.yutai.cache.get_manifest", new=AsyncMock(return_value=manifest)):
        resp = client.get("/yutai/manifest")
    assert resp.status_code == 200
    assert resp.json()["latest_month"] == "2026-03"


def test_yutai_month(client):
    month = {"year": 2026, "month": 3, "records": []}
    with patch("app.routers.yutai.cache.get_day", new=AsyncMock(return_value=month)):
        resp = client.get("/yutai/monthly/2026-03")
    assert resp.status_code == 200
    assert resp.json()["month"] == 3
