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
                "candidate_record_count": 292,
                "unverified_candidate_count": 9,
                "verification_mode": "verified_only",
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


def test_latest_accepts_crossable_with_caution_watch_state(private_client):
    payload = _payload()
    payload["counts_by_nikko_watch_state"]["crossable_with_caution"] = 1
    payload["records"][0]["nikko_watch_state"] = "crossable_with_caution"
    with patch(
        "app.routers.yutai_launch_display.cache.get_manifest",
        new=AsyncMock(return_value=payload),
    ):
        response = private_client.get(
            "/yutai/launch-display/latest",
            headers={"Authorization": "Bearer test-server-secret"},
        )

    assert response.status_code == 200
    assert response.json()["records"][0]["nikko_watch_state"] == "crossable_with_caution"



def test_latest_accepts_discount_metadata(private_client):
    payload = _payload()
    record = next(record for record in payload["records"] if record["programs"])
    item = record["programs"][0]["tiers"][0]["groups"][0]["items"][0]
    item["kind"] = "discount"
    item["valuation_policy"] = "user_estimate_required"
    item["official_value_yen"] = None
    item["discount_terms"] = [
        {
            "label": "店舗",
            "discount_rate_pct": 20,
            "quantity": 1,
            "unit": "枚",
            "notes": "テスト",
        }
    ]
    with patch(
        "app.routers.yutai_launch_display.cache.get_manifest",
        new=AsyncMock(return_value=payload),
    ):
        response = private_client.get(
            "/yutai/launch-display/latest",
            headers={"Authorization": "Bearer test-server-secret"},
        )

    assert response.status_code == 200
    response_record = next(record for record in response.json()["records"] if record["programs"])
    response_item = response_record["programs"][0]["tiers"][0]["groups"][0]["items"][0]
    assert "discount_rate_pct" not in response_item
    assert response_item["discount_terms"][0]["discount_rate_pct"] == 20

def test_latest_accepts_long_term_metadata(private_client):
    payload = _payload()
    payload["counts"]["has_long_term_benefit"] = 1
    payload["counts"]["requires_long_term_holding"] = 1
    record = next(record for record in payload["records"] if record["programs"])
    tier = record["programs"][0]["tiers"][0]
    tier["required_holding_months"] = 12
    record["has_long_term_benefit"] = True
    record["requires_long_term_holding"] = True
    record["long_term_required_holding_months"] = [12]
    record["long_term_benefit_tiers"] = [
        {
            "program_id": record["programs"][0]["program_id"],
            "program_label": record["programs"][0]["label"],
            "minimum_shares": tier["minimum_shares"],
            "maximum_shares": tier.get("maximum_shares"),
            "required_holding_months": 12,
            "groups": tier["groups"],
        }
    ]
    with patch(
        "app.routers.yutai_launch_display.cache.get_manifest",
        new=AsyncMock(return_value=payload),
    ):
        response = private_client.get(
            "/yutai/launch-display/latest",
            headers={"Authorization": "Bearer test-server-secret"},
        )

    assert response.status_code == 200
    response_record = next(record for record in response.json()["records"] if record["programs"])
    assert response.json()["counts"]["has_long_term_benefit"] == 1
    assert response_record["has_long_term_benefit"] is True
    assert response_record["requires_long_term_holding"] is True
    assert response_record["long_term_required_holding_months"] == [12]
    assert response_record["long_term_benefit_tiers"][0]["groups"]


def test_latest_accepts_publish_metadata_and_program_effective_dates(private_client):
    payload = _payload()
    payload["artifact_type"] = "yutai_launch_display"
    payload["verification_mode"] = "verified_only"
    payload["source_artifact_type"] = "minkabu_candidate"
    payload["candidate_record_count"] = 292
    payload["unverified_candidate_count"] = 9
    record = next(record for record in payload["records"] if record["programs"])
    record["programs"][0]["effective_from"] = "2026-07-30"
    record["programs"][0]["effective_to"] = None

    with patch(
        "app.routers.yutai_launch_display.cache.get_manifest",
        new=AsyncMock(return_value=payload),
    ):
        response = private_client.get(
            "/yutai/launch-display/latest",
            headers={"Authorization": "Bearer test-server-secret"},
        )

    assert response.status_code == 200
    response_payload = response.json()
    assert response_payload["artifact_type"] == "yutai_launch_display"
    assert response_payload["candidate_record_count"] == 292
    response_record = next(record for record in response_payload["records"] if record["programs"])
    assert response_record["programs"][0]["effective_from"] == "2026-07-30"

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
