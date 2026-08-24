from __future__ import annotations

import json
import warnings
from datetime import date, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Path, Query, Response
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from app import cache, r2

router = APIRouter(prefix="/references", tags=["theme-references"])

_PREFIX = "theme-references"
_SCHEMA_VERSION = "theme-reference-artifacts-v1"
_WARNING_RESPONSE_CHARS = 50_000
_MAX_RESPONSE_CHARS = 60_000


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReferenceSource(_StrictModel):
    title: str
    url: HttpUrl
    publisher: str
    verified_on: date


class ReferenceArtifact(_StrictModel):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    record_count: int = Field(ge=1)
    char_count: int = Field(ge=1, lt=_MAX_RESPONSE_CHARS)


class ReferenceFamily(_StrictModel):
    index_path: str
    record_count: int = Field(ge=1)
    as_of: dict[str, date]


class ThemeReferenceManifest(_StrictModel):
    schema_version: Literal[_SCHEMA_VERSION]
    generation_id: str = Field(pattern=r"^[0-9]{8}T[0-9]{12}Z$")
    object_root: str
    generated_at: datetime
    as_of: dict[str, date]
    families: dict[Literal["policy-themes", "industries"], ReferenceFamily]
    artifacts: list[ReferenceArtifact]

    @model_validator(mode="after")
    def _generation_root_matches_id(self) -> "ThemeReferenceManifest":
        if self.object_root != f"generations/{self.generation_id}":
            raise ValueError("object_root must match generation_id")
        expected_index_paths = {
            "policy-themes": "policy-themes/index.json",
            "industries": "industries/index.json",
        }
        if set(self.families) != set(expected_index_paths):
            raise ValueError(
                "manifest must contain policy-themes and industries families"
            )
        if any(
            self.families[family].index_path != expected_path
            for family, expected_path in expected_index_paths.items()
        ):
            raise ValueError(
                "manifest family index_path does not match the v1 contract"
            )
        expected_paths = {
            "policy-themes/index.json",
            "industries/index.json",
            *(
                f"policy-themes/policy-field-{number:02}.json"
                for number in range(1, 18)
            ),
            *(f"industries/industry-{number:02}.json" for number in range(1, 14)),
        }
        if not expected_paths.issubset({artifact.path for artifact in self.artifacts}):
            raise ValueError(
                "manifest must contain the required 17 policy and 13 industry artifacts"
            )
        if self.families["policy-themes"].record_count != 17:
            raise ValueError("policy-themes record_count must be 17")
        if self.families["industries"].record_count != 13:
            raise ValueError("industries record_count must be 13")
        return self


class PolicyThemeIndexItem(_StrictModel):
    stable_id: str = Field(pattern=r"^policy-field-(?:0[1-9]|1[0-7])$")
    source_order: int = Field(ge=1, le=17)
    field_id: int = Field(ge=1, le=17)
    name: str
    summary: str
    path: str
    as_of: date
    related_industries: list[str]
    related_industry_count: int = Field(ge=0)
    related_company_count: int = Field(ge=0)
    wave_record_count: int = Field(ge=0)


class IndustryIndexItem(_StrictModel):
    stable_id: str = Field(pattern=r"^industry-(?:0[1-9]|1[0-3])$")
    source_order: int = Field(ge=1, le=13)
    name: str
    path: str
    as_of: date
    summary: str
    sectors: list[str]


class PolicyThemeIndex(_StrictModel):
    schema_version: Literal[_SCHEMA_VERSION]
    family: Literal["policy-themes"]
    generated_at: datetime
    as_of: dict[str, date]
    item_count: Literal[17]
    items: list[PolicyThemeIndexItem]

    @model_validator(mode="after")
    def _items_match_contract(self) -> "PolicyThemeIndex":
        expected = [f"policy-field-{number:02}" for number in range(1, 18)]
        if [item.stable_id for item in self.items] != expected:
            raise ValueError(
                "policy index must contain ordered policy-field-01 through 17"
            )
        if any(
            item.related_industry_count != len(item.related_industries)
            for item in self.items
        ):
            raise ValueError("related_industry_count must match related_industries")
        return self


class IndustryIndex(_StrictModel):
    schema_version: Literal[_SCHEMA_VERSION]
    family: Literal["industries"]
    generated_at: datetime
    as_of: dict[str, date]
    item_count: Literal[13]
    items: list[IndustryIndexItem]

    @model_validator(mode="after")
    def _items_match_contract(self) -> "IndustryIndex":
        expected = [f"industry-{number:02}" for number in range(1, 14)]
        if [item.stable_id for item in self.items] != expected:
            raise ValueError(
                "industry index must contain ordered industry-01 through 13"
            )
        return self


class RelatedCompany(_StrictModel):
    code: str
    name: str
    relationship: str
    evidence_type: str
    evidence_status: str
    source_url: HttpUrl
    verified_on: date


class PolicyLink(_StrictModel):
    field_id: int = Field(ge=1, le=17)
    related_industries: list[str]
    companies: list[RelatedCompany]


class OfficialField(_StrictModel):
    id: int = Field(ge=1, le=17)
    name: str
    investment_tags: list[str]
    focus_examples: list[str]


class OfficialMetadata(_StrictModel):
    schema_version: str
    title: str
    as_of_date: date
    official_summary: str
    roadmap_watch: str
    support_mechanisms: list[str]
    investment_evaluation_steps: list[str]
    fund_lens: dict[str, Any]


class LinkMetadata(_StrictModel):
    schema_version: str
    as_of_date: date
    notice: str
    official_product_source: HttpUrl
    jpx_sector_map_note: str
    jpx_sector_map: dict[str, list[str]]


class ResearchWaveMetadata(_StrictModel):
    schema_version: str
    wave_id: str
    as_of_date: date
    scope: list[str]
    note: str | None = None
    earnings_signal_levels: dict[str, str]


class ResearchFieldSignal(_StrictModel):
    earnings_signal: str
    note: str


class ResearchRecord(_StrictModel):
    record_id: str
    wave_id: str
    wave_as_of_date: date
    code: str
    name: str
    field_ids: list[int]
    products: list[str]
    relationship: str
    evidence_status: str
    earnings_signal: str
    field_signals: dict[str, ResearchFieldSignal] | None = None
    earnings_evidence: str
    caution: str
    company_category: str | None = None
    sources: list[ReferenceSource]


class PolicyThemeDetail(_StrictModel):
    schema_version: Literal[_SCHEMA_VERSION]
    stable_id: str = Field(pattern=r"^policy-field-(?:0[1-9]|1[0-7])$")
    field_id: int = Field(ge=1, le=17)
    source_order: int = Field(ge=1, le=17)
    as_of: dict[str, date]
    official_field: OfficialField
    shared_official_metadata: OfficialMetadata
    policy_links: PolicyLink
    shared_link_metadata: LinkMetadata
    related_industries: list[str]
    related_companies: list[RelatedCompany]
    research_wave_metadata: list[ResearchWaveMetadata]
    wave_research_records: list[ResearchRecord]
    shared_official_sources: list[ReferenceSource]
    notice: str


class IndustryTopCompany(_StrictModel):
    code: str
    name: str
    business_model: list[str]
    financial_reading: list[str]
    watch_points: list[str]


class IndustryAnalysis(_StrictModel):
    name: str
    sectors: list[str]
    keywords: list[str]
    summary: str
    characteristics: list[str]
    focus_points: list[str]
    shikiho_caveats: list[str]
    top_companies: list[IndustryTopCompany]
    top_companies_as_of: date


class IndustryDetail(_StrictModel):
    schema_version: Literal[_SCHEMA_VERSION]
    stable_id: str = Field(pattern=r"^industry-(?:0[1-9]|1[0-3])$")
    source_order: int = Field(ge=1, le=13)
    as_of: date
    industry: IndustryAnalysis


class PolicyThemePage(_StrictModel):
    schema_version: Literal[_SCHEMA_VERSION]
    family: Literal["policy-themes"]
    generation_id: str
    as_of: dict[str, date]
    total_count: Literal[17]
    returned_count: int = Field(ge=0, le=17)
    next_cursor: str | None
    items: list[PolicyThemeIndexItem]


class IndustryPage(_StrictModel):
    schema_version: Literal[_SCHEMA_VERSION]
    family: Literal["industries"]
    generation_id: str
    as_of: dict[str, date]
    total_count: Literal[13]
    returned_count: int = Field(ge=0, le=13)
    next_cursor: str | None
    items: list[IndustryIndexItem]


def _enforce_payload_size(payload: dict[str, Any]) -> dict[str, Any]:
    char_count = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    if char_count >= _MAX_RESPONSE_CHARS:
        raise RuntimeError(
            f"reference response exceeds {_MAX_RESPONSE_CHARS} characters"
        )
    if char_count >= _WARNING_RESPONSE_CHARS:
        warnings.warn(
            f"reference response exceeds {_WARNING_RESPONSE_CHARS} character warning threshold",
            stacklevel=2,
        )
    return payload


async def _manifest() -> ThemeReferenceManifest:
    payload = await cache.get_manifest(
        f"{_PREFIX}/manifest",
        lambda: r2.fetch_json(f"{_PREFIX}/manifest.json"),
    )
    return ThemeReferenceManifest.model_validate(payload)


async def _index(
    manifest: ThemeReferenceManifest,
    family: Literal["policy-themes", "industries"],
) -> PolicyThemeIndex | IndustryIndex:
    index_path = manifest.families[family].index_path
    object_path = f"{_PREFIX}/{manifest.object_root}/{index_path}"
    payload = await cache.get_day(
        f"{_PREFIX}/{manifest.generation_id}/{family}/index",
        lambda: r2.fetch_json(object_path),
    )
    model = PolicyThemeIndex if family == "policy-themes" else IndustryIndex
    return model.model_validate(payload)


def _page_items(
    items: list[Any], *, cursor: str | None, limit: int
) -> tuple[list[Any], str | None]:
    start = 0
    if cursor is not None:
        matching = [
            index for index, item in enumerate(items) if item.stable_id == cursor
        ]
        if not matching:
            raise HTTPException(status_code=422, detail=f"invalid cursor: {cursor}")
        start = matching[0] + 1
    selected = items[start : start + limit]
    has_more = start + len(selected) < len(items)
    next_cursor = selected[-1].stable_id if selected and has_more else None
    return selected, next_cursor


def _translate_error(exc: Exception, *, missing: str | None = None) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status == 404 and missing is not None:
        return HTTPException(status_code=404, detail=missing)
    return HTTPException(status_code=502, detail=str(exc))


@router.get(
    "/policy-themes/manifest",
    response_model=ThemeReferenceManifest,
    operation_id="getThemeReferenceManifest",
    summary="テーマ参照 manifest を取得",
    responses={502: {"description": "R2取得またはproducer契約の検証失敗"}},
)
async def get_policy_theme_manifest(response: Response) -> dict[str, Any]:
    """政策テーマ・業界参照の現行世代とartifact一覧を返す。"""
    response.headers["Cache-Control"] = cache.MUTABLE_HTTP_CACHE_CONTROL
    try:
        return _enforce_payload_size((await _manifest()).model_dump(mode="json"))
    except Exception as exc:
        raise _translate_error(exc) from exc


@router.get(
    "/policy-themes",
    response_model=PolicyThemePage,
    operation_id="listPolicyThemes",
    summary="政策テーマ一覧をページ取得",
    responses={
        422: {"description": "cursorが不正"},
        502: {"description": "R2取得失敗"},
    },
)
async def list_policy_themes(
    response: Response,
    limit: int = Query(default=10, ge=1, le=17, description="1回に返す件数（1〜17）"),
    cursor: str | None = Query(default=None, description="前回レスポンスのnext_cursor"),
) -> dict[str, Any]:
    """政策17分野のcompact indexだけを返す。detail本文は含めない。"""
    response.headers["Cache-Control"] = cache.MUTABLE_HTTP_CACHE_CONTROL
    try:
        manifest = await _manifest()
        index = await _index(manifest, "policy-themes")
        assert isinstance(index, PolicyThemeIndex)
        items, next_cursor = _page_items(index.items, cursor=cursor, limit=limit)
        payload = PolicyThemePage(
            schema_version=_SCHEMA_VERSION,
            family="policy-themes",
            generation_id=manifest.generation_id,
            as_of=index.as_of,
            total_count=index.item_count,
            returned_count=len(items),
            next_cursor=next_cursor,
            items=items,
        ).model_dump(mode="json")
        return _enforce_payload_size(payload)
    except Exception as exc:
        raise _translate_error(exc) from exc


@router.get(
    "/policy-themes/{field_id}",
    response_model=PolicyThemeDetail,
    response_model_exclude_unset=True,
    operation_id="getPolicyThemeDetail",
    summary="政策テーマ1件の詳細を取得",
    responses={
        404: {"description": "指定分野が未公開"},
        502: {"description": "R2取得失敗"},
    },
)
async def get_policy_theme_detail(
    response: Response,
    field_id: int = Path(ge=1, le=17, description="政策分野ID（1〜17）"),
) -> dict[str, Any]:
    """指定した政策分野1件だけを返す。"""
    try:
        manifest = await _manifest()
        stable_id = f"policy-field-{field_id:02}"
        relative_path = f"policy-themes/{stable_id}.json"
        object_path = f"{_PREFIX}/{manifest.object_root}/{relative_path}"
        payload = await cache.get_day(
            f"{_PREFIX}/{manifest.generation_id}/{stable_id}",
            lambda: r2.fetch_json(object_path),
        )
        model = PolicyThemeDetail.model_validate(payload)
        if model.field_id != field_id or model.stable_id != stable_id:
            raise RuntimeError(f"policy theme artifact identity mismatch: {stable_id}")
        validated = model.model_dump(mode="json", exclude_unset=True)
        response.headers["Cache-Control"] = cache.MUTABLE_HTTP_CACHE_CONTROL
        return _enforce_payload_size(validated)
    except Exception as exc:
        raise _translate_error(
            exc, missing=f"policy theme not found: {field_id}"
        ) from exc


@router.get(
    "/industries",
    response_model=IndustryPage,
    operation_id="listReferenceIndustries",
    summary="業界分析一覧をページ取得",
    responses={
        422: {"description": "cursorが不正"},
        502: {"description": "R2取得失敗"},
    },
)
async def list_industries(
    response: Response,
    limit: int = Query(default=10, ge=1, le=13, description="1回に返す件数（1〜13）"),
    cursor: str | None = Query(default=None, description="前回レスポンスのnext_cursor"),
) -> dict[str, Any]:
    """業界13件のcompact indexだけを返す。detail本文は含めない。"""
    response.headers["Cache-Control"] = cache.MUTABLE_HTTP_CACHE_CONTROL
    try:
        manifest = await _manifest()
        index = await _index(manifest, "industries")
        assert isinstance(index, IndustryIndex)
        items, next_cursor = _page_items(index.items, cursor=cursor, limit=limit)
        payload = IndustryPage(
            schema_version=_SCHEMA_VERSION,
            family="industries",
            generation_id=manifest.generation_id,
            as_of=index.as_of,
            total_count=index.item_count,
            returned_count=len(items),
            next_cursor=next_cursor,
            items=items,
        ).model_dump(mode="json")
        return _enforce_payload_size(payload)
    except Exception as exc:
        raise _translate_error(exc) from exc


@router.get(
    "/industries/{industry_id}",
    response_model=IndustryDetail,
    response_model_exclude_unset=True,
    operation_id="getReferenceIndustryDetail",
    summary="業界分析1件の詳細を取得",
    responses={
        404: {"description": "指定業界が未公開"},
        502: {"description": "R2取得失敗"},
    },
)
async def get_industry_detail(
    response: Response,
    industry_id: int = Path(ge=1, le=13, description="業界ID（1〜13）"),
) -> dict[str, Any]:
    """指定した業界分析1件だけを返す。"""
    try:
        manifest = await _manifest()
        stable_id = f"industry-{industry_id:02}"
        relative_path = f"industries/{stable_id}.json"
        object_path = f"{_PREFIX}/{manifest.object_root}/{relative_path}"
        payload = await cache.get_day(
            f"{_PREFIX}/{manifest.generation_id}/{stable_id}",
            lambda: r2.fetch_json(object_path),
        )
        model = IndustryDetail.model_validate(payload)
        if model.stable_id != stable_id:
            raise RuntimeError(f"industry artifact identity mismatch: {stable_id}")
        validated = model.model_dump(mode="json", exclude_unset=True)
        response.headers["Cache-Control"] = cache.MUTABLE_HTTP_CACHE_CONTROL
        return _enforce_payload_size(validated)
    except Exception as exc:
        raise _translate_error(
            exc, missing=f"industry not found: {industry_id}"
        ) from exc
