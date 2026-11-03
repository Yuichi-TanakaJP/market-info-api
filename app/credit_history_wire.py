"""Strict wire schema for private daily inventory and generation manifests."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PREFIX = "credit-inventory/history/v1"
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
MAX_MANIFEST_BYTES = 256 * 1024
MAX_ENTRIES = 480


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class NikkoRecord(WireModel):
    available_shares: int | None = Field(ge=0)
    available_shares_raw: str = Field(max_length=4096)
    general_short: bool | None
    general_buy: bool | None
    institutional_short: bool | None
    institutional_buy: bool | None
    has_exchange_regulation: bool | None
    has_internal_regulation: bool | None
    regulation_fetch_status: Literal[
        "complete", "failed", "not_requested", "unknown_legacy", "unknown"
    ]
    regulation_sources_raw: str | None = Field(max_length=4096)
    regulation_details_raw: str | None = Field(max_length=4096)


class SbiRecord(WireModel):
    position_status: Literal["available", "limited", "unavailable", "unknown"]
    position_status_raw: str | None = Field(max_length=4096)
    available_shares: None
    unit_upper_limit_raw: str | None = Field(max_length=4096)
    is_short: bool | None
    is_long: bool | None
    is_daily: bool | None
    is_hyper: bool | None


class Snapshot(WireModel):
    observed_date: str
    observed_at: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_snapshot_id: str
    collection_completeness: Literal["not_attested"]
    record_count: int = Field(ge=1, le=10000)
    by_code: dict[str, NikkoRecord | SbiRecord]


class DailyArtifact(WireModel):
    schema: Literal["credit-inventory-daily-v1"]
    broker: Literal["smbc_nikko", "sbi"]
    month: str = Field(pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")
    selection_rule: Literal["last_source_snapshot_per_jst_day"]
    source_snapshot_count: int = Field(ge=1)
    selected_snapshot_count: int = Field(ge=1, le=31)
    observed_dates: list[str]
    snapshots: list[Snapshot] = Field(min_length=1, max_length=31)

    @model_validator(mode="after")
    def identities(self):
        datetime.strptime(self.month, "%Y-%m")
        dates = [s.observed_date for s in self.snapshots]
        if (
            dates != sorted(set(dates))
            or dates != self.observed_dates
            or len(dates) != self.selected_snapshot_count
            or self.source_snapshot_count < len(dates)
        ):
            raise ValueError("inconsistent snapshot dates/counts")
        record_type = NikkoRecord if self.broker == "smbc_nikko" else SbiRecord
        for s in self.snapshots:
            at = datetime.fromisoformat(s.observed_at)
            if (
                at.utcoffset() != timedelta(hours=9)
                or at.date().isoformat() != s.observed_date
                or s.observed_date[:7] != self.month
            ):
                raise ValueError("inconsistent observation time")
            if (
                s.source_snapshot_id
                != f"{self.broker}:{s.observed_at}:{s.source_sha256}"
                or len(s.by_code) != s.record_count
            ):
                raise ValueError("inconsistent source identity/count")
            if any(
                not re.fullmatch(r"[0-9A-Z]{4,5}", c) or not isinstance(r, record_type)
                for c, r in s.by_code.items()
            ):
                raise ValueError("invalid broker record/code")
        return self


class Entry(WireModel):
    broker: Literal["smbc_nikko", "sbi"]
    month: str = Field(pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(ge=1, le=MAX_ARTIFACT_BYTES)
    key: str
    observed_dates: list[str] = Field(min_length=1, max_length=31)

    @model_validator(mode="after")
    def identity(self):
        datetime.strptime(self.month, "%Y-%m")
        if self.key != f"{PREFIX}/months/{self.broker}/{self.month}/{self.sha256}.json":
            raise ValueError("invalid artifact key")
        if self.observed_dates != sorted(set(self.observed_dates)):
            raise ValueError("invalid entry dates")
        for date in self.observed_dates:
            if (
                datetime.strptime(date, "%Y-%m-%d").strftime("%Y-%m-%d") != date
                or date[:7] != self.month
            ):
                raise ValueError("invalid entry month/date")
        return self


class Manifest(WireModel):
    schema: Literal["credit-inventory-history-manifest-v1"]
    entries: list[Entry] = Field(min_length=1, max_length=MAX_ENTRIES)

    @model_validator(mode="after")
    def unique(self):
        keys = [(e.broker, e.month) for e in self.entries]
        if keys != sorted(set(keys)):
            raise ValueError("duplicate/unsorted broker-month")
        return self
