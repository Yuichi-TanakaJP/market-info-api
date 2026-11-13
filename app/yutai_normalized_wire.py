from __future__ import annotations
import calendar
from datetime import date
import hashlib
import json
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.yutai_normalized_schema import validate_yutai_normalized_record

PREFIX = "yutai/normalized/v1/releases"
MAX_RELEASE_BYTES = 4 * 1024 * 1024
MAX_RECORD_BYTES = 1024 * 1024
MONTH_PATTERN = r"^20[0-9]{2}-(0[1-9]|1[0-2])$"
HASH_PATTERN = r"^[0-9a-f]{64}$"


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _constant(value):
    raise ValueError("nonfinite JSON")


def parse_json(body: bytes, limit: int):
    if not 0 < len(body) <= limit:
        raise ValueError("invalid artifact length")
    return json.loads(
        body.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant
    )


def validate_selection(month: str, record: dict) -> None:
    if not re.fullmatch(MONTH_PATTERN, month):
        raise ValueError("invalid rights month")
    model = validate_yutai_normalized_record(record, strict=True)
    if model.schema_version != 2 or model.normalization_status != "reviewed":
        raise ValueError("only reviewed V2 source records may be released")
    if date.fromisoformat(model.as_of_date).isoformat() != model.as_of_date:
        raise ValueError("source date must be YYYY-MM-DD")
    if any(e.archive_status != "saved" for e in model.source_evidence):
        raise ValueError("all source evidence must be archived")
    first = date.fromisoformat(month + "-01")
    last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
    active = [
        p
        for p in model.programs
        if first.month in p.rights_months
        and (p.effective_from is None or date.fromisoformat(p.effective_from) <= last)
        and (p.effective_to is None or date.fromisoformat(p.effective_to) >= first)
    ]
    if not active:
        raise ValueError("record does not apply to requested month")
    intervals = {
        (
            max(first, date.fromisoformat(p.effective_from))
            if p.effective_from
            else first,
            min(last, date.fromisoformat(p.effective_to)) if p.effective_to else last,
        )
        for p in active
    }
    if len(intervals) != 1:
        raise ValueError("ambiguous within-month program transition")
    if len(canonical(record)) > MAX_RECORD_BYTES - 2048:
        raise ValueError("record exceeds delivery limit")


class ReleaseEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    month: str = Field(pattern=MONTH_PATTERN)
    record: dict

    @model_validator(mode="after")
    def valid_record(self):
        validate_selection(self.month, self.record)
        return self


class NormalizedRelease(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["yutai-normalized-release-v1"]
    coverage: Literal["partial"]
    record_count: int = Field(ge=1, le=4444)
    records: list[ReleaseEntry] = Field(min_length=1, max_length=4444)

    @model_validator(mode="after")
    def unique_records(self):
        keys = [(e.month, e.record["code"]) for e in self.records]
        if keys != sorted(set(keys)) or len(keys) != self.record_count:
            raise ValueError(
                "release entries must be sorted, unique and counted exactly"
            )
        return self


def validate_release(body: bytes, expected_sha: str | None = None) -> NormalizedRelease:
    if expected_sha is not None and (
        not re.fullmatch(HASH_PATTERN, expected_sha) or digest(body) != expected_sha
    ):
        raise ValueError("release digest mismatch")
    return NormalizedRelease.model_validate(parse_json(body, MAX_RELEASE_BYTES))


class NormalizedRead(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["yutai-normalized-read-v1"] = "yutai-normalized-read-v1"
    release_sha256: str = Field(pattern=HASH_PATTERN)
    month: str = Field(pattern=MONTH_PATTERN)
    code: str = Field(pattern=r"^[0-9A-Z]{4}$")
    record_sha256: str = Field(pattern=HASH_PATTERN)
    record: dict

    @model_validator(mode="after")
    def valid_read(self):
        validate_selection(self.month, self.record)
        if (
            self.record["code"] != self.code
            or digest(canonical(self.record)) != self.record_sha256
        ):
            raise ValueError("record identity or digest mismatch")
        return self
