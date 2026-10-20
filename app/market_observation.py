from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class MarketObservation(BaseModel):
    snapshot_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    source: str
    market_date: date | None
    date_basis: Literal["explicit_source", "unknown"]
    source_observed_at: str | None
    collected_at: datetime | None
    generated_at: datetime
    input_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    raw_sha256: str | None = None

    @model_validator(mode="after")
    def consistent_basis(self):
        if (self.date_basis == "explicit_source") != (self.market_date is not None):
            raise ValueError("market_date requires explicit source basis")
        return self


class MarketSnapshot(BaseModel):
    observation: MarketObservation
    snapshot_file: str = Field(pattern=r"^snapshots/[a-f0-9]{64}\.json$")


async def fetch_observation_day(*, prefix: str, file_name: str, date_str: str,
                                manifest: dict, manifest_version_key: str | None = None) -> dict:
    """Resolve a validated content address; legacy day aliases remain mutable."""
    import hashlib
    import json

    from app import cache, r2

    raw = (manifest.get("snapshots") or {}).get(date_str)
    if raw is None:
        return await cache.get_manifest(
            f"{prefix}/legacy/{date_str}:{manifest_version_key or manifest.get('generated_at', 'legacy')}",
            lambda: r2.fetch_json(f"{prefix}/{file_name}"),
        )
    entry = MarketSnapshot.model_validate(raw)
    key = f"{prefix}/{entry.snapshot_file}"

    async def fetch():
        payload = await r2.fetch_json(key)
        # Canonical producer encoding is part of the immutable content contract.
        encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        if hashlib.sha256(encoded).hexdigest() != entry.snapshot_file.split("/")[-1][:-5]:
            raise ValueError("snapshot content hash mismatch")
        return payload

    payload = await cache.get_day(key, fetch)
    observation = MarketObservation.model_validate(payload.get("observation"))
    if observation != entry.observation or payload.get("date") != date_str:
        raise ValueError("snapshot date/provenance mismatch")
    return payload
