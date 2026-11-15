"""Authenticated immutable original bytes; no official-site fetching or writes."""

from __future__ import annotations

import asyncio
import re

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, Response

from app import dividend_source_storage as storage
from app.routers.dividend_sources import require_key
from app.tdnet_source_original import (
    MAX_RECORD_BYTES,
    PREFIX,
    SourceOriginal,
    parse_record,
    validate_content,
)

router = APIRouter(
    prefix="/private/tdnet/source-originals", tags=["private-source-originals"]
)
_gate = asyncio.Semaphore(1)
_HEADERS = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


def error(status, detail):
    return HTTPException(status_code=status, detail=detail, headers=dict(_HEADERS))


def selector(code, disclosure_id, sha):
    if (
        not re.fullmatch(r"[0-9A-Z]{4}", code)
        or not re.fullmatch(r"[0-9]{18}", disclosure_id)
        or not re.fullmatch(r"[0-9a-f]{64}", sha)
    ):
        raise error(400, "invalid original selector")


async def _read(code, disclosure_id, sha, content=False):
    selector(code, disclosure_id, sha)
    async with _gate:
        record_validated = False
        try:
            body = await storage.read_bytes(
                f"{PREFIX}/by-code/{code}/documents/{disclosure_id}/{sha}.json",
                MAX_RECORD_BYTES,
            )
            record = parse_record(body, code, disclosure_id, sha)
            record_validated = True
            headers = _HEADERS | {
                "X-Content-SHA256": sha,
                "Content-Disposition": f'attachment; filename="{disclosure_id}-{sha}.json"',
            }
            media = "application/json"
            if content:
                body = await storage.read_bytes(record.raw_key, record.content_limit)
                validate_content(body, record)
                extension = "zip" if record.source_kind == "xbrl_zip" else "pdf"
                headers |= {
                    "X-Content-SHA256": record.content_sha256,
                    "X-Source-Record-SHA256": sha,
                    "Content-Disposition": f'attachment; filename="{disclosure_id}-{record.content_sha256}.{extension}"',
                }
                media = record.media_type
            return Response(body, media_type=media, headers=headers)
        except ClientError as exc:
            if (
                exc.response.get("Error", {}).get("Code") == "NoSuchKey"
                and not record_validated
            ):
                raise error(404, "original is not saved") from exc
            raise error(503, "saved original unavailable") from exc
        except HTTPException:
            raise
        except Exception as exc:
            raise error(503, "saved original unavailable or invalid") from exc


@router.get(
    "/{security_code}/{disclosure_id}/{record_sha256}",
    dependencies=[Depends(require_key)],
    response_model=SourceOriginal,
    summary="Read exact immutable TDnet original metadata",
)
async def metadata(security_code: str, disclosure_id: str, record_sha256: str):
    """Verify canonical metadata, exact hash and issuer/disclosure binding before return."""
    return await _read(security_code, disclosure_id, record_sha256)


@router.get(
    "/{security_code}/{disclosure_id}/{record_sha256}/content",
    dependencies=[Depends(require_key)],
    response_class=Response,
    summary="Download verified immutable TDnet ZIP or PDF",
)
async def content(security_code: str, disclosure_id: str, record_sha256: str):
    """Authorize via exact pinned metadata, then verify raw SHA, length and magic."""
    return await _read(security_code, disclosure_id, record_sha256, content=True)
