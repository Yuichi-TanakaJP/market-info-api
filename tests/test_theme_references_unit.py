from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import warnings

import pytest
from fastapi.testclient import TestClient

from app import cache
from app.routers import theme_references as router
import app.main as main_mod


_FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture()
def client():
    with TestClient(main_mod.app) as test_client:
        yield test_client


@pytest.fixture()
def real_shape_payloads() -> dict[str, dict]:
    return {
        "manifest": _fixture("theme_reference_manifest_real_shape.json"),
        "policy_index": _fixture("theme_reference_policy_index_real_shape.json"),
        "policy_detail": _fixture("theme_reference_policy_detail_real_shape.json"),
        "industry_index": _fixture("theme_reference_industry_index_real_shape.json"),
        "industry_detail": _fixture("theme_reference_industry_detail_real_shape.json"),
    }


def _r2_payloads(payloads: dict[str, dict]) -> dict[str, dict]:
    generation = payloads["manifest"]["object_root"]
    return {
        "theme-references/manifest.json": payloads["manifest"],
        f"theme-references/{generation}/policy-themes/index.json": payloads[
            "policy_index"
        ],
        f"theme-references/{generation}/policy-themes/policy-field-01.json": payloads[
            "policy_detail"
        ],
        f"theme-references/{generation}/industries/index.json": payloads[
            "industry_index"
        ],
        f"theme-references/{generation}/industries/industry-01.json": payloads[
            "industry_detail"
        ],
    }


def test_all_endpoints_validate_real_shapes_and_use_generation_scoped_paths(
    client: TestClient, real_shape_payloads: dict[str, dict]
):
    payloads = _r2_payloads(real_shape_payloads)
    manifest_keys: list[str] = []
    day_keys: list[str] = []

    async def fetch_json(path: str) -> dict:
        return payloads[path]

    async def get_manifest(key, fetch):
        manifest_keys.append(key)
        return await fetch()

    async def get_day(key, fetch):
        day_keys.append(key)
        return await fetch()

    with (
        patch(
            "app.routers.theme_references.r2.fetch_json",
            new=AsyncMock(side_effect=fetch_json),
        ) as r2_fetch,
        patch(
            "app.routers.theme_references.cache.get_manifest",
            new=AsyncMock(side_effect=get_manifest),
        ),
        patch(
            "app.routers.theme_references.cache.get_day",
            new=AsyncMock(side_effect=get_day),
        ),
    ):
        manifest_response = client.get("/references/policy-themes/manifest")
        policy_index_response = client.get("/references/policy-themes?limit=1")
        policy_detail_response = client.get("/references/policy-themes/1")
        industry_index_response = client.get("/references/industries?limit=1")
        industry_detail_response = client.get("/references/industries/1")

    responses = (
        manifest_response,
        policy_index_response,
        policy_detail_response,
        industry_index_response,
        industry_detail_response,
    )
    assert all(response.status_code == 200 for response in responses)
    assert all(
        len(json.dumps(response.json(), ensure_ascii=False, separators=(",", ":")))
        < 40_000
        for response in responses
    )
    assert manifest_response.json()["generation_id"] == "20260824T151519588507Z"
    assert policy_index_response.json()["items"][0]["stable_id"] == "policy-field-01"
    assert policy_detail_response.json()["stable_id"] == "policy-field-01"
    assert industry_index_response.json()["items"][0]["stable_id"] == "industry-01"
    assert industry_detail_response.json()["stable_id"] == "industry-01"

    assert manifest_keys == ["theme-references/manifest"] * 5
    assert day_keys == [
        "theme-references/20260824T151519588507Z/policy-themes/index",
        "theme-references/20260824T151519588507Z/policy-field-01",
        "theme-references/20260824T151519588507Z/industries/index",
        "theme-references/20260824T151519588507Z/industry-01",
    ]
    assert [call.args[0] for call in r2_fetch.await_args_list] == [
        "theme-references/manifest.json",
        "theme-references/manifest.json",
        "theme-references/generations/20260824T151519588507Z/policy-themes/index.json",
        "theme-references/manifest.json",
        "theme-references/generations/20260824T151519588507Z/policy-themes/policy-field-01.json",
        "theme-references/manifest.json",
        "theme-references/generations/20260824T151519588507Z/industries/index.json",
        "theme-references/manifest.json",
        "theme-references/generations/20260824T151519588507Z/industries/industry-01.json",
    ]
    assert (
        manifest_response.headers["cache-control"] == cache.MUTABLE_HTTP_CACHE_CONTROL
    )
    assert (
        policy_index_response.headers["cache-control"]
        == cache.MUTABLE_HTTP_CACHE_CONTROL
    )
    assert (
        industry_index_response.headers["cache-control"]
        == cache.MUTABLE_HTTP_CACHE_CONTROL
    )
    assert (
        policy_detail_response.headers["cache-control"]
        == cache.MUTABLE_HTTP_CACHE_CONTROL
    )
    assert (
        industry_detail_response.headers["cache-control"]
        == cache.MUTABLE_HTTP_CACHE_CONTROL
    )


@pytest.mark.parametrize(
    ("path", "index_key", "expected_cursor"),
    [
        ("/references/policy-themes", "policy_index", "policy-field-02"),
        ("/references/industries", "industry_index", "industry-02"),
    ],
)
def test_list_endpoints_paginate_and_reject_invalid_cursor(
    client: TestClient,
    real_shape_payloads: dict[str, dict],
    path: str,
    index_key: str,
    expected_cursor: str,
):
    manifest = real_shape_payloads["manifest"]
    index = real_shape_payloads[index_key]
    with (
        patch(
            "app.routers.theme_references.cache.get_manifest",
            new=AsyncMock(return_value=manifest),
        ),
        patch(
            "app.routers.theme_references.cache.get_day",
            new=AsyncMock(return_value=index),
        ),
    ):
        first = client.get(f"{path}?limit=2")
        second = client.get(f"{path}?limit=1&cursor={expected_cursor}")
        invalid = client.get(f"{path}?cursor=not-a-stable-id")

    assert first.status_code == 200
    assert first.json()["returned_count"] == 2
    assert first.json()["next_cursor"] == expected_cursor
    assert second.status_code == 200
    assert second.json()["items"][0]["stable_id"] != expected_cursor
    assert invalid.status_code == 422
    assert invalid.json()["detail"] == "invalid cursor: not-a-stable-id"


@pytest.mark.parametrize(
    "path",
    [
        "/references/policy-themes/0",
        "/references/policy-themes/18",
        "/references/industries/0",
        "/references/industries/14",
    ],
)
def test_detail_endpoints_reject_out_of_range_ids_before_r2(
    client: TestClient, path: str
):
    with patch(
        "app.routers.theme_references.cache.get_manifest", new=AsyncMock()
    ) as get_manifest:
        response = client.get(path)

    assert response.status_code == 422
    get_manifest.assert_not_awaited()


def test_detail_endpoints_distinguish_missing_artifact_from_upstream_failure(
    client: TestClient, real_shape_payloads: dict[str, dict]
):
    missing = RuntimeError("not found")
    missing.response = SimpleNamespace(status_code=404)
    with (
        patch(
            "app.routers.theme_references.cache.get_manifest",
            new=AsyncMock(return_value=real_shape_payloads["manifest"]),
        ),
        patch(
            "app.routers.theme_references.cache.get_day",
            new=AsyncMock(side_effect=missing),
        ),
    ):
        missing_response = client.get("/references/policy-themes/1")

    with (
        patch(
            "app.routers.theme_references.cache.get_manifest",
            new=AsyncMock(return_value=real_shape_payloads["manifest"]),
        ),
        patch(
            "app.routers.theme_references.cache.get_day",
            new=AsyncMock(side_effect=RuntimeError("r2 unavailable")),
        ),
    ):
        upstream_response = client.get("/references/industries/1")

    assert missing_response.status_code == 404
    assert missing_response.json()["detail"] == "policy theme not found: 1"
    assert upstream_response.status_code == 502
    assert upstream_response.json()["detail"] == "r2 unavailable"


def test_manifest_upstream_failure_is_502(client: TestClient):
    with patch(
        "app.routers.theme_references.cache.get_manifest",
        new=AsyncMock(side_effect=RuntimeError("manifest unavailable")),
    ):
        response = client.get("/references/policy-themes/manifest")

    assert response.status_code == 502
    assert response.json()["detail"] == "manifest unavailable"


def test_manifest_rejects_wrong_family_index_path(client: TestClient):
    manifest = _fixture("theme_reference_manifest_real_shape.json")
    manifest["families"]["policy-themes"]["index_path"] = "other/index.json"
    with patch(
        "app.routers.theme_references.cache.get_manifest",
        new=AsyncMock(return_value=manifest),
    ):
        response = client.get("/references/policy-themes/manifest")

    assert response.status_code == 502
    assert "index_path" in response.json()["detail"]


def test_manifest_allows_additional_forward_compatible_artifacts(client: TestClient):
    manifest = _fixture("theme_reference_manifest_real_shape.json")
    manifest["artifacts"].append(
        {
            "path": "auxiliary/notes.json",
            "sha256": "0" * 64,
            "record_count": 1,
            "char_count": 100,
        }
    )
    with patch(
        "app.routers.theme_references.cache.get_manifest",
        new=AsyncMock(return_value=manifest),
    ):
        response = client.get("/references/policy-themes/manifest")

    assert response.status_code == 200
    assert response.json()["artifacts"][-1]["path"] == "auxiliary/notes.json"


def test_industry_detail_uses_stable_id_not_source_order_for_identity(
    client: TestClient, real_shape_payloads: dict[str, dict]
):
    detail = real_shape_payloads["industry_detail"] | {"source_order": 2}
    with (
        patch(
            "app.routers.theme_references.cache.get_manifest",
            new=AsyncMock(return_value=real_shape_payloads["manifest"]),
        ),
        patch(
            "app.routers.theme_references.cache.get_day",
            new=AsyncMock(return_value=detail),
        ),
    ):
        response = client.get("/references/industries/1")

    assert response.status_code == 200
    assert response.json()["stable_id"] == "industry-01"
    assert response.json()["source_order"] == 2


def test_response_size_thresholds_warn_and_reject_at_sixty_thousand_characters():
    normal = {"value": "normal"}
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert router._enforce_payload_size(normal) is normal
    assert not caught

    warning_payload = {"value": "x" * 50_000}
    with pytest.warns(UserWarning, match="50000"):
        assert router._enforce_payload_size(warning_payload) is warning_payload

    empty_payload_size = len(
        json.dumps({"value": ""}, ensure_ascii=False, separators=(",", ":"))
    )
    at_limit = {"value": "x" * (60_000 - empty_payload_size)}
    assert (
        len(json.dumps(at_limit, ensure_ascii=False, separators=(",", ":"))) == 60_000
    )
    with pytest.raises(RuntimeError, match="60000"):
        router._enforce_payload_size(at_limit)


def test_theme_reference_openapi_operation_ids_are_unique(client: TestClient):
    schema = client.get("/openapi.json").json()
    operation_ids = [
        operation["operationId"]
        for path, methods in schema["paths"].items()
        if path.startswith("/references/")
        for operation in methods.values()
        if "operationId" in operation
    ]

    assert operation_ids == [
        "getThemeReferenceManifest",
        "listPolicyThemes",
        "getPolicyThemeDetail",
        "listReferenceIndustries",
        "getReferenceIndustryDetail",
    ]
    assert len(operation_ids) == len(set(operation_ids))
