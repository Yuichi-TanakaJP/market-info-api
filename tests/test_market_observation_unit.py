import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app import cache
from app.market_observation import MarketObservation, fetch_observation_day


def make_payload():
    payload = json.loads((Path(__file__).parent / "fixtures/nikkei_day_real_shape.json").read_text(encoding="utf-8"))
    payload["observation"] = {
        "snapshot_id": "a" * 32, "source": "nikkei225jp_contribution",
        "market_date": None, "date_basis": "unknown", "source_observed_at": None,
        "collected_at": "2026-02-06T12:00:00Z", "generated_at": "2026-02-06T12:01:00Z",
        "input_sha256": "b" * 64,
    }
    return payload


def entry_for(payload):
    content_hash = hashlib.sha256(json.dumps(payload, ensure_ascii=False, indent=2).encode()).hexdigest()
    return {"observation": payload["observation"], "snapshot_file": f"snapshots/{content_hash}.json"}


@pytest.mark.asyncio
async def test_actual_shape_snapshot_preserves_unknown_and_versions_same_day(monkeypatch):
    cache._day_cache.clear()
    first = make_payload()
    second = make_payload()
    second["observation"] = {**second["observation"], "snapshot_id": "c" * 32}
    fetch = AsyncMock(side_effect=[first, second])
    monkeypatch.setenv("R2_PUBLIC_BASE_URL", "https://r2.example.com")
    from app import r2
    monkeypatch.setattr(r2, "fetch_json", fetch)
    for payload in [first, second]:
        entry = entry_for(payload)
        got = await fetch_observation_day(prefix="nikkei-contribution", file_name="legacy.json",
            date_str=payload["date"], manifest={"snapshots": {payload["date"]: entry}})
        assert got == payload
    assert fetch.call_count == 2
    assert all("snapshots/" in call.args[0] for call in fetch.call_args_list)


@pytest.mark.asyncio
async def test_corrupt_snapshot_fails_instead_of_returning_mismatched_day(monkeypatch):
    cache._day_cache.clear()
    payload = make_payload()
    entry = entry_for(payload)
    monkeypatch.setenv("R2_PUBLIC_BASE_URL", "https://r2.example.com")
    from app import r2
    monkeypatch.setattr(r2, "fetch_json", AsyncMock(return_value={**payload, "date": "2026-02-07"}))
    with pytest.raises(ValueError, match="hash"):
        await fetch_observation_day(prefix="test", file_name="legacy.json", date_str=payload["date"],
            manifest={"snapshots": {payload["date"]: entry}})


@pytest.mark.asyncio
async def test_legacy_is_mutable_and_kept_without_inventing_source_date(monkeypatch):
    cache._manifest_cache.clear()
    payload = make_payload()
    payload.pop("observation")
    fetch = AsyncMock(return_value=payload)
    monkeypatch.setenv("R2_PUBLIC_BASE_URL", "https://r2.example.com")
    from app import r2
    monkeypatch.setattr(r2, "fetch_json", fetch)
    got = await fetch_observation_day(prefix="test", file_name="legacy.json", date_str=payload["date"], manifest={})
    assert "observation" not in got
    assert "test/legacy/" + payload["date"] + ":legacy" in cache._manifest_cache


def test_basis_and_path_validation():
    payload = make_payload()
    with pytest.raises(ValidationError):
        MarketObservation.model_validate({**payload["observation"], "market_date": "2026-02-06"})


@pytest.mark.asyncio
async def test_cached_snapshot_still_rejects_changed_binding(monkeypatch):
    cache._day_cache.clear()
    payload = make_payload()
    entry = entry_for(payload)
    monkeypatch.setenv("R2_PUBLIC_BASE_URL", "https://r2.example.com")
    from app import r2
    monkeypatch.setattr(r2, "fetch_json", AsyncMock(return_value=payload))
    await fetch_observation_day(prefix="test", file_name="legacy.json", date_str=payload["date"],
        manifest={"snapshots": {payload["date"]: entry}})
    entry["observation"] = {**entry["observation"], "snapshot_id": "d" * 32}
    with pytest.raises(ValueError, match="provenance"):
        await fetch_observation_day(prefix="test", file_name="legacy.json", date_str=payload["date"],
            manifest={"snapshots": {payload["date"]: entry}})


@pytest.mark.asyncio
async def test_legacy_manifest_version_invalidates_same_day_alias(monkeypatch):
    cache._manifest_cache.clear()
    first = make_payload()
    second = {**first, "records": []}
    monkeypatch.setenv("R2_PUBLIC_BASE_URL", "https://r2.example.com")
    from app import r2
    fetch = AsyncMock(side_effect=[first, second])
    monkeypatch.setattr(r2, "fetch_json", fetch)
    for version, expected in [("v1", first), ("v2", second)]:
        got = await fetch_observation_day(prefix="test", file_name="legacy.json", date_str=first["date"],
            manifest={}, manifest_version_key=version)
        assert got == expected
    assert fetch.call_count == 2
