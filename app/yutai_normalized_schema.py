"""Source schema mirror; independent of legacy display/apply."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


YutaiSourceType = Literal["official_html", "official_pdf", "tdnet_pdf"]
YutaiBenefitKind = Literal[
    "money_voucher",
    "points",
    "goods",
    "discount",
    "service",
    "lottery",
]
YutaiValuationPolicy = Literal[
    "face_value",
    "official_equivalent",
    "user_estimate_required",
    "excluded",
]


class YutaiSourceSeed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^[0-9A-Z]{4}$")
    company_name: str = Field(min_length=1)
    source_url: str = Field(pattern=r"^https?://")
    source_type: YutaiSourceType
    sample_categories: list[str] = Field(default_factory=list)


class YutaiSourceArchiveRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    company_name: str
    source_url: str
    resolved_url: str | None = None
    source_type: YutaiSourceType
    sample_categories: list[str]
    fetched_at: str
    status: Literal["saved", "error"]
    http_status: int | None = None
    content_type: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    content_bytes: int | None = None
    content_sha256: str | None = None
    content_encoding: Literal["gzip"] | None = None
    raw_path: str | None = None
    metadata_path: str | None = None
    parser_version: str
    error: str | None = None

    @model_validator(mode="after")
    def validate_status_fields(self) -> "YutaiSourceArchiveRecord":
        if self.status == "saved":
            required = (
                self.content_bytes,
                self.content_sha256,
                self.content_encoding,
                self.raw_path,
                self.metadata_path,
            )
            if any(value is None for value in required):
                raise ValueError("saved source record is missing archive fields")
            if self.error is not None:
                raise ValueError("saved source record cannot contain error")
        elif not self.error:
            raise ValueError("error source record must contain error")
        return self


class YutaiSourceArchiveManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    run_id: str
    generated_at: str
    input_path: str
    records: list[YutaiSourceArchiveRecord]


class YutaiDiscountTerm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = None
    discount_rate_pct: float = Field(ge=0, le=100)
    quantity: float | None = Field(default=None, ge=0)
    unit: str | None = None
    notes: str | None = None


class YutaiNormalizedBenefitItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1)
    kind: YutaiBenefitKind
    quantity: float | None = Field(default=None, ge=0)
    unit: str | None = None
    official_value_yen: int | None = Field(default=None, ge=0)
    discount_rate_pct: float | None = Field(default=None, ge=0, le=100)
    discount_terms: list[YutaiDiscountTerm] | None = None
    valuation_policy: YutaiValuationPolicy
    notes: str | None = None

    @model_validator(mode="after")
    def validate_official_value(self) -> "YutaiNormalizedBenefitItem":
        if self.valuation_policy in {"face_value", "official_equivalent"}:
            if self.official_value_yen is None:
                raise ValueError(
                    "official_value_yen is required for official-value policies"
                )
        return self

    @model_validator(mode="after")
    def validate_discount_metadata(self) -> "YutaiNormalizedBenefitItem":
        if self.kind != "discount":
            if self.discount_rate_pct is not None or self.discount_terms:
                raise ValueError("discount metadata is only valid for discount items")
        if self.discount_rate_pct is not None and self.discount_terms:
            raise ValueError("use either discount_rate_pct or discount_terms, not both")
        return self


class YutaiNormalizedBenefitGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["all", "choose_one", "choose_n", "lottery"]
    choice_count: int | None = Field(default=None, ge=1)
    allow_repeated_choices: bool = False
    items: list[YutaiNormalizedBenefitItem] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_choice_count(self) -> "YutaiNormalizedBenefitGroup":
        if self.mode == "choose_n":
            if self.choice_count is None:
                raise ValueError("choice_count is required for choose_n")
            if not self.allow_repeated_choices and self.choice_count > len(self.items):
                raise ValueError("choice_count cannot exceed item count")
        elif self.choice_count is not None:
            raise ValueError("choice_count is only valid for choose_n")
        if self.mode != "choose_n" and self.allow_repeated_choices:
            raise ValueError("allow_repeated_choices is only valid for choose_n")
        return self


class YutaiNormalizedTier(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minimum_shares: int = Field(ge=1)
    maximum_shares: int | None = Field(default=None, ge=1)
    required_holding_months: int = Field(default=0, ge=0)
    groups: list[YutaiNormalizedBenefitGroup] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_share_range(self) -> "YutaiNormalizedTier":
        if (
            self.maximum_shares is not None
            and self.maximum_shares < self.minimum_shares
        ):
            raise ValueError("maximum_shares must be >= minimum_shares")
        return self


class YutaiNormalizedProgram(BaseModel):
    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    rights_months: list[Annotated[int, Field(ge=1, le=12)]] = Field(min_length=1)
    tiers: list[YutaiNormalizedTier] = Field(min_length=1)
    effective_from: str | None = None
    effective_to: str | None = None
    notes: str | None = None

    @field_validator("effective_from", "effective_to")
    @classmethod
    def validate_effective_date(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                dt.date.fromisoformat(value)
            except ValueError as exc:
                raise ValueError("effective dates must be YYYY-MM-DD") from exc
        return value

    @model_validator(mode="after")
    def validate_effective_range(self) -> "YutaiNormalizedProgram":
        if self.effective_from and self.effective_to:
            if dt.date.fromisoformat(self.effective_from) > dt.date.fromisoformat(
                self.effective_to
            ):
                raise ValueError("effective_from must be on or before effective_to")
        return self


class YutaiNormalizedSourceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_url: str = Field(pattern=r"^https?://")
    archive_status: Literal["saved", "error", "not_archived"]
    archive_run_id: str | None = None
    fetched_at: str | None = None
    content_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )

    @model_validator(mode="after")
    def validate_archive_reference(self) -> "YutaiNormalizedSourceEvidence":
        if self.archive_status == "saved":
            if not (self.archive_run_id and self.fetched_at and self.content_sha256):
                raise ValueError(
                    "saved evidence requires run id, fetched_at, and sha256"
                )
        return self


class YutaiNormalizedRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    code: str = Field(pattern=r"^[0-9A-Z]{4}$")
    company_name: str = Field(min_length=1)
    as_of_date: str
    source_evidence: list[YutaiNormalizedSourceEvidence] = Field(min_length=1)
    normalization_status: Literal["draft", "reviewed"]
    programs: list[YutaiNormalizedProgram] = Field(min_length=1)
    notes: str | None = None


# V2 keeps the V1 program/tier/group/item hierarchy intact while separating
# "a shareholder-register date exists" from "a benefit is granted on that date".
# This is needed for programs where an intermediate record date only contributes
# to long-term eligibility, or where that date grants only to newly registered
# shareholder numbers.
YutaiGrantModeV2 = Literal[
    "regular",
    "new_shareholder_number_only",
    "none",
]
YutaiGrantFrequencyV2 = Literal[
    "per_qualifying_record_date",
    "annual",
]


class YutaiRecordDateRuleV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    month: Annotated[int, Field(ge=1, le=12)]
    grant_mode: YutaiGrantModeV2
    continuity_observation: bool
    notes: str | None = None

    @field_validator("month", mode="before")
    @classmethod
    def require_integer_month(cls, value):
        if type(value) is not int:
            raise ValueError("record-date month must be an integer")
        return value


class YutaiContinuityRequirementV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_consecutive_observations: int | None = Field(
        default=None, ge=1, strict=True
    )
    same_shareholder_number_required: bool | None = None
    continuous_holding_required: bool | None = None
    minimum_shares_each_observation: int | None = Field(default=None, ge=1, strict=True)
    minimum_shares_at_qualification: int | None = Field(default=None, ge=1, strict=True)
    starts_after_initial_entitlement: bool | None = None
    notes: str | None = None

    @field_validator(
        "required_consecutive_observations",
        "minimum_shares_each_observation",
        "minimum_shares_at_qualification",
        mode="before",
    )
    @classmethod
    def reject_coerced_counts(cls, value):
        if value is not None and type(value) is not int:
            raise ValueError("continuity counts and shares require an integer")
        return value

    @model_validator(mode="after")
    def validate_share_thresholds(self) -> "YutaiContinuityRequirementV2":
        if not (
            self.required_consecutive_observations is not None
            or self.same_shareholder_number_required is True
            or self.continuous_holding_required is True
            or self.minimum_shares_each_observation is not None
            or self.minimum_shares_at_qualification is not None
            or self.starts_after_initial_entitlement is True
        ):
            raise ValueError("continuity_requirement needs an explicit requirement")
        if (
            self.minimum_shares_each_observation is not None
            and self.minimum_shares_at_qualification is not None
            and self.minimum_shares_at_qualification
            < self.minimum_shares_each_observation
        ):
            raise ValueError(
                "minimum_shares_at_qualification cannot be below "
                "minimum_shares_each_observation"
            )
        return self


class YutaiNormalizedTierV2(YutaiNormalizedTier):
    continuity_requirement: YutaiContinuityRequirementV2 | None = None


class YutaiNormalizedProgramV2(YutaiNormalizedProgram):
    # rights_months remains the backward-compatible set of months in which this
    # program can actually grant a benefit. Continuity-only observation months
    # belong in record_date_rules but NOT rights_months.
    grant_frequency: YutaiGrantFrequencyV2
    record_date_rules: list[YutaiRecordDateRuleV2] = Field(min_length=1)
    tiers: list[YutaiNormalizedTierV2] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_record_date_semantics(self) -> "YutaiNormalizedProgramV2":
        rule_months = [rule.month for rule in self.record_date_rules]
        if len(rule_months) != len(set(rule_months)):
            raise ValueError("record_date_rules months must be unique")

        if any(
            rule.grant_mode == "none" and not rule.continuity_observation
            for rule in self.record_date_rules
        ):
            raise ValueError("non-grant record dates must observe continuity")
        if (
            self.grant_frequency == "annual"
            and sum(rule.grant_mode == "regular" for rule in self.record_date_rules) > 1
        ):
            raise ValueError("annual programs cannot have multiple regular grant dates")

        grant_months = {
            rule.month for rule in self.record_date_rules if rule.grant_mode != "none"
        }
        if set(self.rights_months) != grant_months:
            raise ValueError(
                "rights_months must equal the grant-capable record_date_rules months"
            )

        has_continuity_requirement = any(
            tier.continuity_requirement is not None for tier in self.tiers
        )
        if has_continuity_requirement and not any(
            rule.continuity_observation for rule in self.record_date_rules
        ):
            raise ValueError(
                "a continuity_requirement needs at least one continuity observation"
            )
        return self


class YutaiNormalizedRecordV2(YutaiNormalizedRecord):
    schema_version: Literal[2] = 2
    programs: list[YutaiNormalizedProgramV2] = Field(min_length=1)


YutaiNormalizedRecordAny = YutaiNormalizedRecord | YutaiNormalizedRecordV2


def validate_yutai_normalized_record(
    payload: object,
    *,
    strict: bool = False,
) -> YutaiNormalizedRecordAny:
    """Validate either the frozen V1 contract or the additive V2 contract."""
    if isinstance(payload, dict):
        schema_version = payload.get("schema_version", 1)
        # bool is a subclass of int in Python; never interpret true/false
        # (or coercible floats/strings) as an official contract version.
        if type(schema_version) is not int:
            raise ValueError(f"unsupported Yutai schema_version: {schema_version}")
        if schema_version == 2:
            model = YutaiNormalizedRecordV2
        elif schema_version == 1:
            model = YutaiNormalizedRecord
        else:
            raise ValueError(f"unsupported Yutai schema_version: {schema_version}")
    else:
        model = YutaiNormalizedRecord
    return model.model_validate(payload, strict=strict)
