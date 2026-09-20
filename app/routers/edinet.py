from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from app import cache, r2

router = APIRouter(prefix="/edinet", tags=["edinet"])

_PREFIX = "edinet/document-list"
_FILING_PREFIX = "edinet/filing-index/v2"
_DATE_RE = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$")


class EdinetItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    doc_id: str
    submit_datetime: str | None
    edinet_code: str | None
    sec_code: str | None
    filer_name: str | None
    doc_type_code: str | None
    doc_description: str | None
    has_xbrl: bool
    has_pdf: bool
    has_csv: bool


class EdinetDocumentList(BaseModel):
    model_config = ConfigDict(extra="allow")
    as_of_date: str
    total_count: int
    items: list[EdinetItem]


class EdinetManifest(BaseModel):
    model_config = ConfigDict(extra="allow")
    dates: list[str]


class EdinetFilingIndexItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_seq_number: int | None
    doc_id: str
    edinet_code: str | None
    sec_code: str | None
    jcn: str | None
    filer_name: str | None
    fund_code: str | None
    ordinance_code: str | None
    form_code: str | None
    doc_type_code: str | None
    period_start: str | None
    period_end: str | None
    submit_datetime: str | None
    doc_description: str | None
    issuer_edinet_code: str | None
    subject_edinet_code: str | None
    subsidiary_edinet_code: str | None
    current_report_reason: str | None
    parent_doc_id: str | None
    operation_datetime: str | None
    withdrawal_status: str | None
    doc_info_edit_status: str | None
    disclosure_status: str | None
    has_xbrl: bool
    has_pdf: bool
    has_attachment: bool
    has_english_document: bool
    has_csv: bool
    legal_status: str | None


class EdinetFilingIndexPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    as_of_date: str
    generated_at: str
    source_process_datetime: str | None
    total_count: int
    items: list[EdinetFilingIndexItem]


class EdinetFilingIndexManifestEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str
    content_sha256: str
    artifact_sha256: str
    item_count: int
    source_process_datetime: str | None


class EdinetFilingIndexManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    generated_at: str
    latest: str
    entries: list[EdinetFilingIndexManifestEntry]


def _date_or_422(date: str) -> None:
    if not _DATE_RE.match(date):
        raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD format")


def _raise_fetch_error(exc: Exception, *, not_found_detail: str) -> None:
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status == 404:
        raise HTTPException(status_code=404, detail=not_found_detail) from exc
    raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/document-list/latest",
    response_model=EdinetDocumentList,
    summary="EDINET書類一覧（最新）を取得",
    responses={502: {"description": "R2 からの取得失敗"}},
)
async def get_latest() -> dict:
    """最新日の EDINET 提出書類一覧を返す。"""
    try:
        return await cache.get_manifest(
            f"{_PREFIX}/latest",
            lambda: r2.fetch_json(f"{_PREFIX}/latest.json"),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/document-list/manifest",
    response_model=EdinetManifest,
    summary="EDINET書類一覧 manifest を取得",
    responses={502: {"description": "R2 からの取得失敗"}},
)
async def get_manifest() -> dict:
    """データが存在する日付の一覧を返す。"""
    try:
        return await cache.get_manifest(
            f"{_PREFIX}/manifest",
            lambda: r2.fetch_json(f"{_PREFIX}/manifest.json"),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/document-list/{date}",
    response_model=EdinetDocumentList,
    summary="EDINET書類一覧（日付指定）を取得",
    responses={
        404: {"description": "指定日のデータが R2 に存在しない"},
        422: {"description": "date が YYYY-MM-DD 形式でない"},
        502: {"description": "R2 からの取得失敗"},
    },
)
async def get_by_date(date: str) -> dict:
    """YYYY-MM-DD 形式の日付に対応する EDINET 提出書類一覧を返す。"""
    _date_or_422(date)
    try:
        return await cache.get_day(
            f"{_PREFIX}/{date}",
            lambda: r2.fetch_json(f"{_PREFIX}/{date}.json"),
        )
    except Exception as exc:
        _raise_fetch_error(exc, not_found_detail=f"edinet document-list not found: {date}")


@router.get(
    "/filing-index/v2/latest",
    response_model=EdinetFilingIndexPayload,
    summary="EDINET Filing Index v2（最新）を取得",
    responses={
        404: {"description": "Filing Index v2 latest が R2 に存在しない"},
        502: {"description": "R2 からの取得失敗"},
    },
)
async def get_filing_index_latest() -> dict:
    """最新の EDINET Filing Index v2 を返す。"""
    try:
        return await cache.get_manifest(
            f"{_FILING_PREFIX}/latest",
            lambda: r2.fetch_json(f"{_FILING_PREFIX}/latest.json"),
        )
    except Exception as exc:
        _raise_fetch_error(exc, not_found_detail="edinet filing-index latest not found")


@router.get(
    "/filing-index/v2/manifest",
    response_model=EdinetFilingIndexManifest,
    summary="EDINET Filing Index v2 manifest を取得",
    responses={
        404: {"description": "Filing Index v2 manifest が R2 に存在しない"},
        502: {"description": "R2 からの取得失敗"},
    },
)
async def get_filing_index_manifest() -> dict:
    """利用可能日・digest・件数を含む Filing Index v2 manifest を返す。"""
    try:
        return await cache.get_manifest(
            f"{_FILING_PREFIX}/manifest",
            lambda: r2.fetch_json(f"{_FILING_PREFIX}/manifest.json"),
        )
    except Exception as exc:
        _raise_fetch_error(exc, not_found_detail="edinet filing-index manifest not found")


@router.get(
    "/filing-index/v2/{date}",
    response_model=EdinetFilingIndexPayload,
    summary="EDINET Filing Index v2（日付指定）を取得",
    responses={
        404: {"description": "指定日の Filing Index v2 が R2 に存在しない"},
        422: {"description": "date が YYYY-MM-DD 形式でない"},
        502: {"description": "R2 からの取得失敗"},
    },
)
async def get_filing_index_by_date(date: str) -> dict:
    """日付指定の Filing Index v2 を返す。

    EDINET の過去日付は取下げ・書類情報修正・不開示状態変更で更新され得るため、
    immutable day cache ではなく mutable manifest/latest と同じ cache class を使う。
    """
    _date_or_422(date)
    try:
        return await cache.get_manifest(
            f"{_FILING_PREFIX}/{date}",
            lambda: r2.fetch_json(f"{_FILING_PREFIX}/{date}.json"),
        )
    except Exception as exc:
        _raise_fetch_error(
            exc,
            not_found_detail=f"edinet filing-index not found: {date}",
        )
