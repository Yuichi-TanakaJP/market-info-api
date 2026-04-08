from __future__ import annotations

import pytest
import httpx
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
    import app.routers.earnings_calendar as earnings_calendar_mod
    import app.routers.ranking as ranking_mod
    import app.routers.nikkei as nikkei_mod
    import app.routers.market_calendar as market_calendar_mod
    import app.routers.sbi as sbi_mod
    import app.routers.topix33 as topix33_mod
    import app.routers.yutai as yutai_mod
    importlib.reload(earnings_calendar_mod)
    importlib.reload(ranking_mod)
    importlib.reload(nikkei_mod)
    importlib.reload(market_calendar_mod)
    importlib.reload(sbi_mod)
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
    assert cfg_mod.US_CLOSED_OBJECT_KEY == "market_closed/us_market_closed_latest.json"


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


def test_market_calendar_us_closed(client):
    payload = {
        "as_of_date": "2026-04-08",
        "from": "2026-01-01",
        "to": "2027-12-31",
        "days": [
            {"date": "2026-01-01", "market_closed": True, "label": "New Year's Day"},
            {"date": "2026-01-02", "market_closed": False, "label": ""},
        ],
    }
    with patch("app.routers.market_calendar.cache.get_manifest", new=AsyncMock(return_value=payload)):
        resp = client.get("/market-calendar/us-closed")
    assert resp.status_code == 200
    assert resp.json()["to"] == "2027-12-31"
    assert resp.json()["days"][0]["label"] == "New Year's Day"


def test_earnings_calendar_overseas_latest(client):
    payload = {
        "generated_at": "2026-04-05T12:00:00+09:00",
        "records": [{"symbol": "AAPL", "date": "2026-04-30"}],
    }
    with patch("app.routers.earnings_calendar.cache.get_manifest", new=AsyncMock(return_value=payload)):
        resp = client.get("/earnings-calendar/overseas/latest")
    assert resp.status_code == 200
    assert resp.json()["records"][0]["symbol"] == "AAPL"


def test_earnings_calendar_overseas_monthly(client):
    payload = {
        "year_month": "2026-04",
        "records": [{"symbol": "MSFT", "date": "2026-04-28"}],
    }
    with patch("app.routers.earnings_calendar.cache.get_day", new=AsyncMock(return_value=payload)):
        resp = client.get("/earnings-calendar/overseas/monthly/2026-04")
    assert resp.status_code == 200
    assert resp.json()["year_month"] == "2026-04"


def test_earnings_calendar_overseas_monthly_invalid_format(client):
    resp = client.get("/earnings-calendar/overseas/monthly/2026-4")
    assert resp.status_code == 422
    assert resp.json()["detail"] == "year_month must be YYYY-MM format"


def test_earnings_calendar_overseas_manifest_not_found(client):
    request = httpx.Request("GET", "https://r2.example.com/earnings-calendar/overseas/manifest.json")
    response = httpx.Response(404, request=request)
    error = httpx.HTTPStatusError("not found", request=request, response=response)
    with patch("app.routers.earnings_calendar.cache.get_manifest", new=AsyncMock(side_effect=error)):
        resp = client.get("/earnings-calendar/overseas/manifest")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "overseas earnings calendar manifest not found"


def test_sbi_credit_latest(client):
    payload = {
        "date": "2026-04-05",
        "generated_at": "2026-04-05T12:00:00+09:00",
        "record_count": 1,
        "by_code": {"1301": {"position_status": "available"}},
    }
    with patch("app.routers.sbi.cache.get_manifest", new=AsyncMock(return_value=payload)):
        resp = client.get("/sbi/credit/latest")
    assert resp.status_code == 200
    assert resp.json()["record_count"] == 1


def test_sbi_credit_monthly(client):
    payload = {
        "date": "2026-04-05",
        "generated_at": "2026-04-05T12:00:00+09:00",
        "record_count": 1,
        "by_code": {"1301": {"position_status": "available"}},
    }
    with patch("app.routers.sbi.cache.get_day", new=AsyncMock(return_value=payload)):
        resp = client.get("/sbi/credit/monthly/2026-04")
    assert resp.status_code == 200
    assert resp.json()["date"] == "2026-04-05"


def test_sbi_credit_latest_not_found(client):
    request = httpx.Request("GET", "https://r2.example.com/sbi/credit/latest.json")
    response = httpx.Response(404, request=request)
    error = httpx.HTTPStatusError("not found", request=request, response=response)
    with patch("app.routers.sbi.cache.get_manifest", new=AsyncMock(side_effect=error)):
        resp = client.get("/sbi/credit/latest")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "sbi credit latest not found"


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


# --- 404 / 502 contract tests ---

def _make_http_error(url: str, status: int) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", url)
    res = httpx.Response(status, request=req)
    return httpx.HTTPStatusError("error", request=req, response=res)


def test_ranking_day_not_found(client):
    err = _make_http_error("https://r2.example.com/stock-ranking/20260228.json", 404)
    with patch("app.routers.ranking.cache.get_day", new=AsyncMock(side_effect=err)):
        resp = client.get("/ranking/2026-02-28")
    assert resp.status_code == 404
    assert "2026-02-28" in resp.json()["detail"]


def test_ranking_manifest_502(client):
    err = _make_http_error("https://r2.example.com/stock-ranking/manifest.json", 500)
    with patch("app.routers.ranking.cache.get_manifest", new=AsyncMock(side_effect=err)):
        resp = client.get("/ranking/manifest")
    assert resp.status_code == 502


def test_topix33_day_not_found(client):
    err = _make_http_error("https://r2.example.com/topix33/topix33_2026-02-28.json", 404)
    with patch("app.routers.topix33.cache.get_day", new=AsyncMock(side_effect=err)):
        resp = client.get("/topix33/2026-02-28")
    assert resp.status_code == 404
    assert "2026-02-28" in resp.json()["detail"]


def test_nikkei_day_not_found(client):
    err = _make_http_error("https://r2.example.com/nikkei-contribution/nikkei_contribution_2026-02-28.json", 404)
    with patch("app.routers.nikkei.cache.get_day", new=AsyncMock(side_effect=err)):
        resp = client.get("/nikkei/2026-02-28")
    assert resp.status_code == 404
    assert "2026-02-28" in resp.json()["detail"]


def test_market_calendar_jpx_closed_not_found(client):
    err = _make_http_error("https://r2.example.com/market_closed/jpx_market_closed_latest.json", 404)
    with patch("app.routers.market_calendar.cache.get_manifest", new=AsyncMock(side_effect=err)):
        resp = client.get("/market-calendar/jpx-closed")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "jpx closed calendar not found"


def test_market_calendar_us_closed_not_found(client):
    err = _make_http_error("https://r2.example.com/market_closed/us_market_closed_latest.json", 404)
    with patch("app.routers.market_calendar.cache.get_manifest", new=AsyncMock(side_effect=err)):
        resp = client.get("/market-calendar/us-closed")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "us closed calendar not found"


def test_nikko_credit(client):
    payload = {"by_code": {"8591": {"margin": True}}, "generated_at": "2026-04-05"}
    with patch("app.routers.nikko.cache.get_manifest", new=AsyncMock(return_value=payload)):
        resp = client.get("/nikko/credit")
    assert resp.status_code == 200
    assert "by_code" in resp.json()


def test_nikko_credit_502(client):
    err = _make_http_error("https://r2.example.com/nikko/credit/latest.json", 500)
    with patch("app.routers.nikko.cache.get_manifest", new=AsyncMock(side_effect=err)):
        resp = client.get("/nikko/credit")
    assert resp.status_code == 502
