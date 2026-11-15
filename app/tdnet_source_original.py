"""Strict immutable TDnet original archive wire contract; no network acquisition."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.dividend_source_wire import parse_object

PREFIX = "tdnet/source-original/v1"
MAX_RECORD_BYTES = 16384
ZIP_LIMIT = 4 * 1024 * 1024
PDF_LIMIT = 8 * 1024 * 1024
HASH = r"^[0-9a-f]{64}$"


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def canonical_bytes(record) -> bytes:
    value = record.model_dump() if isinstance(record, BaseModel) else record
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


class SourceOriginal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["tdnet-source-original-v1"]
    security_code: str = Field(pattern=r"^[0-9A-Z]{4}$")
    disclosure_id: str = Field(pattern=r"^[0-9]{18}$")
    disclosure_date: str
    source_kind: Literal["xbrl_zip", "pdf"]
    official_url: str
    retrieved_url: str
    retrieved_at: str = Field(max_length=32)
    content_sha256: str = Field(pattern=HASH)
    byte_length: int = Field(gt=0)
    media_type: Literal["application/zip", "application/pdf"]

    @field_validator("disclosure_date")
    @classmethod
    def valid_day(cls, value):
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError("noncanonical date")
        return value

    @field_validator("retrieved_at")
    @classmethod
    def valid_time(cls, value):
        if not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:[.][0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})",
            value,
        ):
            raise ValueError("timezone-aware ISO timestamp required")
        if datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset() is None:
            raise ValueError("missing timezone")
        return value

    @model_validator(mode="after")
    def binding(self):
        suffix = "zip" if self.source_kind == "xbrl_zip" else "pdf"
        expected_type = "application/zip" if suffix == "zip" else "application/pdf"
        if self.media_type != expected_type or self.byte_length > self.content_limit:
            raise ValueError("content type or size mismatch")
        tdnet = r"https://www\.release\.tdnet\.info/inbs/([0-9]{18})\." + suffix
        jpx = (
            r"https://www2\.jpx\.co\.jp/disc/"
            + self.security_code
            + r"0/([0-9]{18})\."
            + suffix
        )
        official = re.fullmatch(tdnet, self.official_url) or re.fullmatch(
            jpx, self.official_url
        )
        if official is None or (suffix == "pdf" and official[1] != self.disclosure_id):
            raise ValueError("invalid official URL identity")
        fallback = (
            f"https://www2.jpx.co.jp/disc/{self.security_code}0/{official[1]}.{suffix}"
        )
        if self.retrieved_url != self.official_url and not (
            re.fullmatch(tdnet, self.official_url) and self.retrieved_url == fallback
        ):
            raise ValueError("invalid retrieval binding")
        return self

    @property
    def content_limit(self):
        return ZIP_LIMIT if self.source_kind == "xbrl_zip" else PDF_LIMIT

    @property
    def raw_key(self):
        extension = "zip" if self.source_kind == "xbrl_zip" else "pdf"
        return f"{PREFIX}/objects/{self.content_sha256}.{extension}"


def parse_record(
    body: bytes, security_code: str, disclosure_id: str, record_sha256: str
) -> SourceOriginal:
    record = SourceOriginal.model_validate(parse_object(body, MAX_RECORD_BYTES))
    if canonical_bytes(record) != body or digest(body) != record_sha256:
        raise ValueError("record canonical bytes or hash mismatch")
    if (record.security_code, record.disclosure_id) != (security_code, disclosure_id):
        raise ValueError("record selector mismatch")
    return record


def validate_content(body: bytes, record: SourceOriginal) -> None:
    magic = b"PK\x03\x04" if record.source_kind == "xbrl_zip" else b"%PDF-"
    if (
        len(body) != record.byte_length
        or len(body) > record.content_limit
        or digest(body) != record.content_sha256
        or not body.startswith(magic)
    ):
        raise ValueError("original content integrity mismatch")
