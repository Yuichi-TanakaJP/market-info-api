from __future__ import annotations

import pytest
import httpx
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch
import json
from pathlib import Path


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
    import app.routers.market_rankings as market_rankings_mod
    importlib.reload(earnings_calendar_mod)
    importlib.reload(ranking_mod)
    importlib.reload(nikkei_mod)
    importlib.reload(market_calendar_mod)
    importlib.reload(sbi_mod)
    importlib.reload(topix33_mod)
    importlib.reload(yutai_mod)
    importlib.reload(market_rankings_mod)
    from app.main import app
    return TestClient(app)


_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((_FIXTURES_DIR / name).read_text(encoding="utf-8"))


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
    day = {
        "date": "2026-03-28",
        "index": "nikkei225",
        "generated_at": "2026-03-28T21:00:00+09:00",
        "source": "https://nikkei225jp.com/",
        "summary": {"total_contribution": 100.0, "advancers": 150, "decliners": 70, "unchanged": 5},
        "top_positive": [],
        "top_negative": [],
        "records": [],
    }
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
        "as_of_date": "2026-04-05",
        "calendar": [
            {
                "date": "2026-04-30",
                "count": 1,
                "detail_status": "confirmed",
                "items": [{"event_id": "e1", "local_time": "09:00", "ticker": "AAPL", "stock_name": "Apple", "exchange_code": "US_NASDAQ", "fiscal_term": "26-2Q", "fiscal_term_name": "2026年 第2四半期", "sch_flg": "1", "country_code": "US"}],
            }
        ],
    }
    with patch("app.routers.earnings_calendar.cache.get_manifest", new=AsyncMock(return_value=payload)):
        resp = client.get("/earnings-calendar/overseas/latest")
    assert resp.status_code == 200
    assert resp.json()["calendar"][0]["items"][0]["ticker"] == "AAPL"


def test_earnings_calendar_overseas_monthly(client):
    payload = {
        "as_of_date": "2026-04-05",
        "calendar": [
            {
                "date": "2026-04-28",
                "count": 1,
                "detail_status": "confirmed",
                "items": [{"event_id": "e2", "local_time": "09:00", "ticker": "MSFT", "stock_name": "Microsoft", "exchange_code": "US_NASDAQ", "fiscal_term": "26-3Q", "fiscal_term_name": "2026年 第3四半期", "sch_flg": "1", "country_code": "US"}],
            }
        ],
    }
    with patch("app.routers.earnings_calendar.cache.get_day", new=AsyncMock(return_value=payload)):
        resp = client.get("/earnings-calendar/overseas/monthly/2026-04")
    assert resp.status_code == 200
    assert resp.json()["calendar"][0]["items"][0]["ticker"] == "MSFT"


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


def test_earnings_calendar_domestic_latest(client):
    payload = {
        "as_of_date": "2026-04-24",
        "calendar": [
            {
                "date": "2026-05-01",
                "count": 1,
                "detail_status": "confirmed",
                "items": [{"event_id": "d1", "time": "15:00", "code": "7203", "name": "トヨタ自動車", "market": "東証プライム", "announcement_type": "本決算", "publish_status": "発表予定", "progress_status": "通常"}],
            }
        ],
    }
    with patch("app.routers.earnings_calendar.cache.get_manifest", new=AsyncMock(return_value=payload)):
        resp = client.get("/earnings-calendar/domestic/latest")
    assert resp.status_code == 200
    assert resp.json()["calendar"][0]["items"][0]["code"] == "7203"


def test_earnings_calendar_domestic_manifest(client):
    payload = {
        "as_of_date": "2026-04-24",
        "current_window": {"from": "2026-04-01", "to": "2026-05-31"},
        "months": [
            {"id": "2026-05", "year": 2026, "month": 5, "path": "monthly/2026-05.json", "partial": False, "bucket": "future"}
        ],
    }
    with patch("app.routers.earnings_calendar.cache.get_manifest", new=AsyncMock(return_value=payload)):
        resp = client.get("/earnings-calendar/domestic/manifest")
    assert resp.status_code == 200
    assert resp.json()["months"][0]["id"] == "2026-05"


def test_earnings_calendar_domestic_monthly(client):
    payload = {
        "as_of_date": "2026-04-24",
        "calendar": [
            {
                "date": "2026-05-10",
                "count": 1,
                "detail_status": "confirmed",
                "items": [{"event_id": "d2", "time": "15:00", "code": "6758", "name": "ソニーグループ", "market": "東証プライム", "announcement_type": "本決算", "publish_status": "発表予定", "progress_status": "通常"}],
            }
        ],
    }
    with patch("app.routers.earnings_calendar.cache.get_day", new=AsyncMock(return_value=payload)):
        resp = client.get("/earnings-calendar/domestic/monthly/2026-05")
    assert resp.status_code == 200
    assert resp.json()["calendar"][0]["items"][0]["code"] == "6758"


def test_earnings_calendar_domestic_monthly_invalid_format(client):
    resp = client.get("/earnings-calendar/domestic/monthly/2026-5")
    assert resp.status_code == 422
    assert resp.json()["detail"] == "year_month must be YYYY-MM format"


def test_earnings_calendar_domestic_manifest_not_found(client):
    request = httpx.Request("GET", "https://r2.example.com/earnings-calendar/domestic/manifest.json")
    response = httpx.Response(404, request=request)
    error = httpx.HTTPStatusError("not found", request=request, response=response)
    with patch("app.routers.earnings_calendar.cache.get_manifest", new=AsyncMock(side_effect=error)):
        resp = client.get("/earnings-calendar/domestic/manifest")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "domestic earnings calendar manifest not found"


def test_sbi_credit_latest(client):
    payload = {
        "date": "2026-04-05",
        "generated_at": "2026-04-05T12:00:00+09:00",
        "record_count": 1,
        "by_code": {"1301": {"position_status": "available", "unit_upper_limit": "50 単元", "is_hyper": False, "is_daily": True, "is_short": False, "is_long": False}},
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
        "by_code": {"1301": {"position_status": "available", "unit_upper_limit": "50 単元", "is_hyper": False, "is_daily": True, "is_short": False, "is_long": False}},
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
    manifest = {
        "latest_month": "2026-03",
        "latest_path": "2026-03.json",
        "months": [{"year": 2026, "month": 3, "path": "2026-03.json", "count": 0}],
    }
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
    payload = {
        "date": "2026-04-04",
        "generated_at": "2026-04-04T13:00:00+09:00",
        "record_count": 1,
        "by_code": {"8591": {"institutional_buy": True, "institutional_short": True, "general_buy": True, "general_short": True, "available_shares": 900}},
    }
    with patch("app.routers.nikko.cache.get_manifest", new=AsyncMock(return_value=payload)):
        resp = client.get("/nikko/credit")
    assert resp.status_code == 200
    assert "by_code" in resp.json()


def test_nikko_credit_502(client):
    err = _make_http_error("https://r2.example.com/nikko/credit/latest.json", 500)
    with patch("app.routers.nikko.cache.get_manifest", new=AsyncMock(side_effect=err)):
        resp = client.get("/nikko/credit")
    assert resp.status_code == 502


def test_yutai_manifest_accepts_market_info_manifest_shape(client):
    manifest = _load_fixture("yutai_manifest_real_shape.json")
    with patch("app.routers.yutai.cache.get_manifest", new=AsyncMock(return_value=manifest)):
        resp = client.get("/yutai/manifest")
    assert resp.status_code == 200
    assert resp.json()["months"][0]["path"].endswith(".json")


def test_yutai_month_accepts_market_info_month_shape(client):
    month = _load_fixture("yutai_month_real_shape.json")
    with patch("app.routers.yutai.cache.get_day", new=AsyncMock(return_value=month)):
        resp = client.get("/yutai/monthly/2026-04")
    assert resp.status_code == 200
    assert resp.json()["records"][0]["code"]


def test_nikkei_day_accepts_market_info_records_without_rank(client):
    day = _load_fixture("nikkei_day_real_shape.json")
    with patch("app.routers.nikkei.cache.get_day", new=AsyncMock(return_value=day)):
        resp = client.get("/nikkei/2026-02-06")
    assert resp.status_code == 200
    assert "rank" not in resp.json()["records"][0]


def test_nikko_credit_accepts_null_available_shares(client):
    payload = {
        "date": "2026-04-04",
        "generated_at": "2026-04-04T13:00:00+09:00",
        "record_count": 2,
        "by_code": {
            "130A": {
                "institutional_buy": True,
                "institutional_short": False,
                "general_buy": True,
                "general_short": False,
                "available_shares": None,
            },
            "133A": {
                "institutional_buy": False,
                "institutional_short": False,
                "general_buy": False,
                "general_short": True,
                "available_shares": 800,
            },
        },
    }
    with patch("app.routers.nikko.cache.get_manifest", new=AsyncMock(return_value=payload)):
        resp = client.get("/nikko/credit")
    assert resp.status_code == 200
    assert resp.json()["by_code"]["130A"]["available_shares"] is None


# ---------------------------------------------------------------------------
# market-rankings
# ---------------------------------------------------------------------------

_MARKET_RANKINGS_MANIFEST = {
    "latest": "2026-04",
    "months": ["2026-04"],
    "generatedAt": "2026-04-11T12:00:00Z",
}

_MARKET_RANKINGS_MONTH = {
    "month": "2026-04",
    "generatedAt": "2026-04-11T12:00:00Z",
    "markets": {
        "prime": {
            "date": "2026-04-11",
            "records": [
                {
                    "rank": 1,
                    "code": "7203",
                    "name": "トヨタ自動車",
                    "industry": "輸送用機器",
                    "marketCapOkuYen": 524236.0,
                    "price": 3500.0,
                    "priceTime": "15:30",
                    "changeAmount": 50.0,
                    "changeRate": 1.45,
                    "dividendYieldPct": 2.5,
                }
            ],
        },
        "standard": {"date": "2026-04-11", "records": []},
        "growth": {"date": "2026-04-11", "records": []},
    },
}


def test_market_cap_manifest(client):
    with patch("app.routers.market_rankings.cache.get_manifest", new=AsyncMock(return_value=_MARKET_RANKINGS_MANIFEST)):
        resp = client.get("/market-rankings/market-cap/manifest")
    assert resp.status_code == 200
    assert resp.json()["latest"] == "2026-04"
    assert resp.json()["months"] == ["2026-04"]


def test_market_cap_month(client):
    with patch("app.routers.market_rankings.cache.get_day", new=AsyncMock(return_value=_MARKET_RANKINGS_MONTH)):
        resp = client.get("/market-rankings/market-cap/monthly/2026-04")
    assert resp.status_code == 200
    data = resp.json()
    assert data["month"] == "2026-04"
    assert "prime" in data["markets"]
    assert data["markets"]["prime"]["records"][0]["code"] == "7203"
    assert data["markets"]["prime"]["records"][0]["marketCapOkuYen"] == 524236.0


def test_dividend_yield_manifest(client):
    with patch("app.routers.market_rankings.cache.get_manifest", new=AsyncMock(return_value=_MARKET_RANKINGS_MANIFEST)):
        resp = client.get("/market-rankings/dividend-yield/manifest")
    assert resp.status_code == 200
    assert resp.json()["latest"] == "2026-04"


def test_dividend_yield_month(client):
    with patch("app.routers.market_rankings.cache.get_day", new=AsyncMock(return_value=_MARKET_RANKINGS_MONTH)):
        resp = client.get("/market-rankings/dividend-yield/monthly/2026-04")
    assert resp.status_code == 200
    assert resp.json()["month"] == "2026-04"


def test_market_cap_month_not_found(client):
    err = _make_http_error("https://r2.example.com/market-rankings/market-cap/2026-03.json", 404)
    with patch("app.routers.market_rankings.cache.get_day", new=AsyncMock(side_effect=err)):
        resp = client.get("/market-rankings/market-cap/monthly/2026-03")
    assert resp.status_code == 404
    assert "2026-03" in resp.json()["detail"]


def test_dividend_yield_month_not_found(client):
    err = _make_http_error("https://r2.example.com/market-rankings/dividend-yield/2026-03.json", 404)
    with patch("app.routers.market_rankings.cache.get_day", new=AsyncMock(side_effect=err)):
        resp = client.get("/market-rankings/dividend-yield/monthly/2026-03")
    assert resp.status_code == 404
    assert "2026-03" in resp.json()["detail"]


def test_market_cap_manifest_502(client):
    err = _make_http_error("https://r2.example.com/market-rankings/market-cap/manifest.json", 500)
    with patch("app.routers.market_rankings.cache.get_manifest", new=AsyncMock(side_effect=err)):
        resp = client.get("/market-rankings/market-cap/manifest")
    assert resp.status_code == 502


def test_dividend_yield_manifest_502(client):
    err = _make_http_error("https://r2.example.com/market-rankings/dividend-yield/manifest.json", 500)
    with patch("app.routers.market_rankings.cache.get_manifest", new=AsyncMock(side_effect=err)):
        resp = client.get("/market-rankings/dividend-yield/manifest")
    assert resp.status_code == 502


# ---------------------------------------------------------------------------
# edinet
# ---------------------------------------------------------------------------

_EDINET_PAYLOAD = {
    "as_of_date": "2026-04-23",
    "total_count": 2,
    "items": [
        {
            "doc_id": "S100ABCD",
            "submit_datetime": "2026-04-23 09:00",
            "edinet_code": "E00001",
            "sec_code": "1234",
            "filer_name": "テスト株式会社",
            "doc_type_code": "120",
            "doc_description": "有価証券報告書－第1期",
            "has_xbrl": True,
            "has_pdf": True,
            "has_csv": True,
        },
        {
            "doc_id": "S100EFGH",
            "submit_datetime": "2026-04-23 10:00",
            "edinet_code": "E00002",
            "sec_code": None,
            "filer_name": "テスト投資信託",
            "doc_type_code": "010",
            "doc_description": "有価証券届出書",
            "has_xbrl": False,
            "has_pdf": True,
            "has_csv": False,
        },
    ],
}


def test_edinet_document_list_latest(client):
    with patch("app.routers.edinet.cache.get_manifest", new=AsyncMock(return_value=_EDINET_PAYLOAD)):
        resp = client.get("/edinet/document-list/latest")
    assert resp.status_code == 200
    data = resp.json()
    assert data["as_of_date"] == "2026-04-23"
    assert data["total_count"] == 2
    assert data["items"][0]["doc_id"] == "S100ABCD"
    assert data["items"][1]["sec_code"] is None


def test_edinet_document_list_by_date(client):
    with patch("app.routers.edinet.cache.get_day", new=AsyncMock(return_value=_EDINET_PAYLOAD)):
        resp = client.get("/edinet/document-list/2026-04-23")
    assert resp.status_code == 200
    assert resp.json()["as_of_date"] == "2026-04-23"


def test_edinet_document_list_by_date_not_found(client):
    err = _make_http_error("https://r2.example.com/edinet/document-list/2026-01-01.json", 404)
    with patch("app.routers.edinet.cache.get_day", new=AsyncMock(side_effect=err)):
        resp = client.get("/edinet/document-list/2026-01-01")
    assert resp.status_code == 404
    assert "2026-01-01" in resp.json()["detail"]


def test_edinet_document_list_latest_502(client):
    err = _make_http_error("https://r2.example.com/edinet/document-list/latest.json", 500)
    with patch("app.routers.edinet.cache.get_manifest", new=AsyncMock(side_effect=err)):
        resp = client.get("/edinet/document-list/latest")
    assert resp.status_code == 502


def test_edinet_document_list_by_date_invalid_format(client):
    resp = client.get("/edinet/document-list/20260423")
    assert resp.status_code == 422
    assert "YYYY-MM-DD" in resp.json()["detail"]
