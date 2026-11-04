"""Strict bounded wire manifest for stored private TDNET dividend observations."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PREFIX = "tdnet/dividend-source/v1"
MAX_MANIFEST_BYTES = 256 * 1024
MAX_ARTIFACT_BYTES = 32 * 1024 * 1024
HASH = r"^[0-9a-f]{64}$"


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Entry(WireModel):
    disclosure_id: str = Field(pattern=r"^[0-9]{18}$")
    disclosure_date: str
    artifact_sha256: str = Field(pattern=HASH)
    artifact_bytes: int = Field(gt=0, le=MAX_ARTIFACT_BYTES)
    extraction_status: Literal[
        "parsed", "partial", "ambiguous", "conflict", "unsupported"
    ]
    source_input_sha256: list[str] = Field(min_length=1, max_length=200)

    @field_validator("disclosure_date")
    @classmethod
    def valid_day(cls, value):
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError("invalid official date")
        return value

    @field_validator("source_input_sha256")
    @classmethod
    def hashes(cls, values):
        import re

        if values != sorted(set(values)) or any(
            not re.fullmatch(HASH, v) for v in values
        ):
            raise ValueError("invalid source digests")
        return values


class Manifest(WireModel):
    schema: Literal["tdnet-dividend-private-manifest-v1"]
    security_code: str = Field(pattern=r"^[0-9A-Z]{4}$")
    entries: list[Entry] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def unique_order(self):
        keys = [
            (e.disclosure_date, e.disclosure_id, e.artifact_sha256)
            for e in self.entries
        ]
        if keys != sorted(set(keys)):
            raise ValueError("unordered or duplicated manifest identity")
        dates_by_id = {}
        for entry in self.entries:
            prior = dates_by_id.setdefault(entry.disclosure_id, entry.disclosure_date)
            if prior != entry.disclosure_date:
                raise ValueError("conflicting official dates for disclosure identity")
        return self


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _constant(_):
    raise ValueError("nonfinite JSON value")


def parse_object(body: bytes, limit: int) -> dict:
    if not body or len(body) > limit:
        raise ValueError("private object byte limit")
    value = json.loads(
        body.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant
    )
    if not isinstance(value, dict):
        raise ValueError("expected object")
    stack = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        if depth > 64:
            raise ValueError("private object JSON depth limit")
        children = (
            item.values()
            if isinstance(item, dict)
            else item
            if isinstance(item, list)
            else ()
        )
        stack.extend(
            (child, depth + 1) for child in children if isinstance(child, (dict, list))
        )
    return value


def validate_artifact(body: bytes, entry: Entry, code: str):
    if len(body) != entry.artifact_bytes or digest(body) != entry.artifact_sha256:
        raise ValueError("artifact digest/length mismatch")
    payload = parse_object(body, MAX_ARTIFACT_BYTES)
    primary = payload.get("primary_disclosure", {})
    if (
        payload.get("schema") != "tdnet-dividend-source-artifact-v1"
        or payload.get("source") != "tdnet"
        or payload.get("absence_semantics") != "not_deletion_or_zero_or_nonexistence"
        or primary.get("id") != entry.disclosure_id
        or primary.get("date") != entry.disclosure_date
        or primary.get("source_security_code") != code + "0"
        or payload.get("extraction", {}).get("status") != entry.extraction_status
    ):
        raise ValueError("artifact identity mismatch")
    sources = payload.get("source_artifacts")
    if not isinstance(sources, list) or not sources:
        raise ValueError("missing source evidence")
    if any(
        source.get("raw_retention") == "retained_private"
        or source.get("private_evidence_key") is not None
        for source in sources
    ):
        raise ValueError(
            "private delivery must not claim packet-relative retained evidence"
        )
    hashes = sorted({source["content_sha256"] for source in sources})
    if hashes != entry.source_input_sha256:
        raise ValueError("source digest mismatch")
    # Full financial semantics are validated by the strict Stock Notes consumer.
