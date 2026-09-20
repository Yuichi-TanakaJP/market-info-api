from __future__ import annotations

import re
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict

from app import cache, r2

router = APIRouter(
    prefix="/reference/jpx-listed-companies",
    tags=["reference-jpx-listed-companies"],
)

_PREFIX = "reference/jpx-listed-companies"
_DATE_RE = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$")


class JpxListedCompanyItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of_date: str
    code: str
    name: str
    display_name: str
    abbrev_name: str
    market: str
    sector: str | None


class JpxListedCompaniesManifestEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str
    sha256: str
    record_count: int


class JpxListedCompaniesManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["jpx-listed-companies-manifest-v1"]
    generated_at: str
    latest: str
    entries: list[JpxListedCompaniesManifestEntry]


def _status_code(exc: Exception) -> int | None:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None)


@router.get("/latest", response_model=list[JpxListedCompanyItem])
async def get_latest(response: Response) -> list[dict]:
    response.headers["Cache-Control"] = cache.MUTABLE_HTTP_CACHE_CONTROL
    try:
        return await cache.get_manifest(
            f"{_PREFIX}/latest",
            lambda: r2.fetch_json_array(f"{_PREFIX}/latest.json"),
        )
    except Exception as exc:
        if _status_code(exc) == 404:
            raise HTTPException(
                status_code=404,
                detail="jpx listed companies latest not found",
            ) from exc
        raise HTTPException(
            status_code=502,
            detail="jpx listed companies latest unavailable",
        ) from exc


@router.get("/manifest", response_model=JpxListedCompaniesManifest)
async def get_manifest(response: Response) -> dict:
    response.headers["Cache-Control"] = cache.MUTABLE_HTTP_CACHE_CONTROL
    try:
        return await cache.get_manifest(
            f"{_PREFIX}/manifest",
            lambda: r2.fetch_json(f"{_PREFIX}/manifest.json"),
        )
    except Exception as exc:
        if _status_code(exc) == 404:
            raise HTTPException(
                status_code=404,
                detail="jpx listed companies manifest not found",
            ) from exc
        raise HTTPException(
            status_code=502,
            detail="jpx listed companies manifest unavailable",
        ) from exc


@router.get("/{date}", response_model=list[JpxListedCompanyItem])
async def get_by_date(date: str, response: Response) -> list[dict]:
    if not _DATE_RE.fullmatch(date):
        raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD format")

    response.headers["Cache-Control"] = cache.IMMUTABLE_HTTP_CACHE_CONTROL
    try:
        return await cache.get_day(
            f"{_PREFIX}/{date}",
            lambda: r2.fetch_json_array(f"{_PREFIX}/{date}.json"),
        )
    except Exception as exc:
        if _status_code(exc) == 404:
            raise HTTPException(
                status_code=404,
                detail=f"jpx listed companies not found: {date}",
            ) from exc
        raise HTTPException(
            status_code=502,
            detail="jpx listed companies snapshot unavailable",
        ) from exc
