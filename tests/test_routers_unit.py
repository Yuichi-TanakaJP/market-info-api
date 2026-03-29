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
    import app.routers.yutai as yutai_mod
    importlib.reload(ranking_mod)
    importlib.reload(nikkei_mod)
    importlib.reload(yutai_mod)
    from app.main import app
    return TestClient(app)


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ranking_latest(client):
    manifest = {"dates": ["2026-03-28"], "latest": "2026-03-28"}
    with patch("app.routers.ranking.r2.fetch_json", new=AsyncMock(return_value=manifest)):
        with patch("app.routers.ranking.cache.get_manifest", new=AsyncMock(return_value=manifest)):
            resp = client.get("/ranking/latest")
    assert resp.status_code == 200
    assert resp.json()["latest"] == "2026-03-28"


def test_ranking_day(client):
    day = {"date": "2026-03-28", "records": []}
    with patch("app.routers.ranking.cache.get_day", new=AsyncMock(return_value=day)):
        resp = client.get("/ranking/2026-03-28")
    assert resp.status_code == 200
    assert resp.json()["date"] == "2026-03-28"


def test_nikkei_latest(client):
    manifest = {"dates": ["2026-03-28"], "latest_date": "2026-03-28", "generated_at": ""}
    with patch("app.routers.nikkei.cache.get_manifest", new=AsyncMock(return_value=manifest)):
        resp = client.get("/nikkei/latest")
    assert resp.status_code == 200
    assert resp.json()["latest_date"] == "2026-03-28"


def test_nikkei_day(client):
    day = {"date": "2026-03-28", "index": "nikkei225", "records": []}
    with patch("app.routers.nikkei.cache.get_day", new=AsyncMock(return_value=day)):
        resp = client.get("/nikkei/2026-03-28")
    assert resp.status_code == 200
    assert resp.json()["date"] == "2026-03-28"


def test_yutai_latest(client):
    manifest = {"latest_month": "2026-03", "latest_path": "2026-03.json", "months": []}
    with patch("app.routers.yutai.cache.get_manifest", new=AsyncMock(return_value=manifest)):
        resp = client.get("/yutai/latest")
    assert resp.status_code == 200
    assert resp.json()["latest_month"] == "2026-03"


def test_yutai_month(client):
    month = {"year": 2026, "month": 3, "records": []}
    with patch("app.routers.yutai.cache.get_day", new=AsyncMock(return_value=month)):
        resp = client.get("/yutai/monthly/2026-03")
    assert resp.status_code == 200
    assert resp.json()["month"] == 3
