"""Wire mirror of market_info comparison-observations-v1; no acceptance."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import timezone
from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StrictBool,
    StrictInt,
    model_validator,
    field_validator,
)


def _wire_timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})",
        value,
    ):
        raise ValueError("explicit timezone date-time wire string required")
    return value


class StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceReference(StrictRecord):
    url: HttpUrl
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fetched_at: AwareDatetime
    content_bytes: StrictInt = Field(gt=0)
    # Logical archive identity, not an arbitrary path to read.
    archive_run_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")

    @field_validator("fetched_at", mode="before")
    @classmethod
    def timestamp_string(cls, value):
        return _wire_timestamp(value)

    @model_validator(mode="after")
    def https_only(self):
        if self.url.scheme != "https" or self.url.username or self.url.password:
            raise ValueError("HTTPS reference without credentials required")
        return self


class ComparisonObservation(StrictRecord):
    code: str = Field(pattern=r"^[0-9A-Z]{4,5}$")
    status: Literal[
        "unchanged_text",
        "changed_text",
        "not_comparable",
        "fetch_failed",
        "not_checked",
    ]
    old: SourceReference | None = None
    new: SourceReference | None = None
    # Even matching text does not prove unchanged benefit conditions.
    scope: Literal["page_text", "selected_text", "none"]
    extractor_version: str | None = Field(default=None, min_length=1, max_length=100)
    old_text_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    new_text_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=2000)
    review_status: Literal["pending"] = "pending"
    # Raw observations never establish benefit presence, absence or acceptance.
    assessment_updated: Literal[False] = False
    byte_equal: StrictBool | None = None

    @model_validator(mode="after")
    def consistent_comparison(self):
        if not self.reason.strip():
            raise ValueError("substantive reason required")
        compared = self.status in {"unchanged_text", "changed_text"}
        if compared:
            if (
                not all(
                    (
                        self.old,
                        self.new,
                        self.extractor_version,
                        self.old_text_sha256,
                        self.new_text_sha256,
                    )
                )
                or self.scope == "none"
            ):
                raise ValueError("comparison requires two sources and text identities")
            if not self.extractor_version.strip():
                raise ValueError("substantive extractor version required")
            if self.old.url != self.new.url:
                raise ValueError("different source URLs require not_comparable")
            equal = self.old_text_sha256 == self.new_text_sha256
            if equal != (self.status == "unchanged_text"):
                raise ValueError("text status contradicts text digests")
        elif (
            any((self.old_text_sha256, self.new_text_sha256, self.extractor_version))
            or self.scope != "none"
        ):
            raise ValueError("uncompared observation cannot claim text comparison")
        if self.status in {"fetch_failed", "not_checked"} and self.new is not None:
            raise ValueError("failed/unperformed acquisition cannot claim new source")
        expected = self.old.sha256 == self.new.sha256 if self.old and self.new else None
        if self.byte_equal != expected:
            raise ValueError("byte equality contradicts source references")
        if expected:
            if self.old.content_bytes != self.new.content_bytes:
                raise ValueError("identical source digest requires identical length")
            if self.status == "changed_text":
                raise ValueError("identical source cannot yield different text")
        if (
            self.old
            and self.new
            and self.old.fetched_at.astimezone(timezone.utc)
            > self.new.fetched_at.astimezone(timezone.utc)
        ):
            raise ValueError("new observation predates baseline")
        return self


class ComparisonReport(StrictRecord):
    schema_version: Literal["yutai-comparison-observations-v1"] = (
        "yutai-comparison-observations-v1"
    )
    mode: Literal["local_pilot"] = "local_pilot"
    generated_at: AwareDatetime
    jpx_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    universe_count: StrictInt = Field(gt=0)
    record_count: StrictInt = Field(ge=0)
    unobserved_count: StrictInt = Field(ge=0)
    coverage: Literal["partial", "complete"]
    records: list[ComparisonObservation]

    @field_validator("generated_at", mode="before")
    @classmethod
    def timestamp_string(cls, value):
        return _wire_timestamp(value)

    @model_validator(mode="after")
    def consistent_counts(self):
        if self.record_count != len(self.records):
            raise ValueError("record count mismatch")
        if len({r.code for r in self.records}) != self.record_count:
            raise ValueError("duplicate code")
        if [r.code for r in self.records] != sorted(r.code for r in self.records):
            raise ValueError("records must be sorted by code")
        if self.unobserved_count != self.universe_count - self.record_count:
            raise ValueError("unobserved count mismatch")
        expected = "complete" if self.unobserved_count == 0 else "partial"
        if self.coverage != expected:
            raise ValueError("coverage mismatch")
        for row in self.records:
            for source in (row.old, row.new):
                if source and source.fetched_at.astimezone(
                    timezone.utc
                ) > self.generated_at.astimezone(timezone.utc):
                    raise ValueError("future source")
        return self


# Keep the wire shape aligned with market_info schemas/yutai_comparison.py.
# The receipt is content addressed; no arbitrary object keys are accepted.

PREFIX = "yutai/source-audit/v1/comparisons"
MAX_REPORT_BYTES = 4 * 1024 * 1024
MAX_RECEIPT_BYTES = 4096


def digest(body):
    return hashlib.sha256(body).hexdigest()


def parse_object(body, limit):
    if not isinstance(body, bytes) or not 0 < len(body) <= limit:
        raise ValueError("invalid object size")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError("nonfinite JSON")

    text = body.decode("utf-8", errors="strict")
    # Bound structure before json.loads allocates its object graph.
    depth = containers = quotes = separators = 0
    inside = escaped = False
    string_length = 0
    for char in text:
        if inside:
            string_length += 1
            if string_length > 8192:
                raise ValueError("JSON string limit")
            if escaped:
                escaped = False
            elif char == chr(92):
                escaped = True
            elif char == '"':
                inside = False
        elif char == '"':
            inside = True
            string_length = 0
            quotes += 1
            if quotes > 200000:
                raise ValueError("JSON token limit")
        elif char in ",:":
            separators += 1
            if separators > 200000:
                raise ValueError("JSON value limit")
        elif char in "[{":
            depth += 1
            containers += 1
            if depth > 24 or containers > 40000:
                raise ValueError("JSON structure limit")
        elif char in "]}":
            depth -= 1
    return json.loads(text, object_pairs_hook=pairs, parse_constant=reject_constant)


class HistoryReceipt(StrictRecord):
    schema_version: Literal["yutai-comparison-history-receipt-v1"]
    mode: Literal["pending_comparison_history"]
    report_key: str
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    report_bytes: StrictInt = Field(gt=0, le=MAX_REPORT_BYTES)
    jpx_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    generated_at: AwareDatetime
    universe_count: StrictInt = Field(gt=0)
    record_count: StrictInt = Field(ge=0)
    unobserved_count: StrictInt = Field(ge=0)
    coverage: Literal["partial", "complete"]
    raw_retention: Literal["not_uploaded_local_assets_required"]
    assessment_updated: Literal[False]

    @field_validator("generated_at", mode="before")
    @classmethod
    def timestamp_string(cls, value):
        return _wire_timestamp(value)

    @model_validator(mode="after")
    def validate_identity(self):
        if self.report_key != f"{PREFIX}/objects/{self.report_sha256}.json":
            raise ValueError("receipt object key mismatch")
        if self.unobserved_count != self.universe_count - self.record_count:
            raise ValueError("receipt count mismatch")
        if self.coverage != ("complete" if self.unobserved_count == 0 else "partial"):
            raise ValueError("receipt coverage mismatch")
        return self


def validate_receipt(body, expected_sha):
    if digest(body) != expected_sha:
        raise ValueError("receipt digest mismatch")
    value = parse_object(body, MAX_RECEIPT_BYTES)
    if not isinstance(value, dict):
        raise ValueError("receipt object required")
    if value.get("assessment_updated") is not False:
        raise ValueError("explicit false receipt marker required")
    return HistoryReceipt.model_validate(value)


def validate_report(body, receipt):
    if len(body) != receipt.report_bytes or digest(body) != receipt.report_sha256:
        raise ValueError("report bytes/digest mismatch")
    value = parse_object(body, MAX_REPORT_BYTES)
    if (
        not isinstance(value, dict)
        or not {"schema_version", "mode", "records"} <= value.keys()
    ):
        raise ValueError("explicit report wire discriminators required")
    rows = value["records"]
    if not isinstance(rows, list) or len(rows) > 10000:
        raise ValueError("report row limit")
    # Fail on the first invalid row rather than accumulating thousands of errors.
    for row in rows:
        if (
            not isinstance(row, dict)
            or not {"review_status", "assessment_updated"} <= row.keys()
        ):
            raise ValueError("explicit pending wire flags required")
        if row["review_status"] != "pending" or row["assessment_updated"] is not False:
            raise ValueError("pending/false wire flags required")
        ComparisonObservation.model_validate(row)
    model = ComparisonReport.model_validate(value)
    for name in (
        "jpx_sha256",
        "universe_count",
        "record_count",
        "unobserved_count",
        "coverage",
    ):
        if getattr(model, name) != getattr(receipt, name):
            raise ValueError("report receipt summary mismatch")
    if model.generated_at.astimezone(timezone.utc) != receipt.generated_at.astimezone(
        timezone.utc
    ):
        raise ValueError("report receipt time mismatch")
    return model
