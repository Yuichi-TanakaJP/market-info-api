"""Authenticated, exact-byte transport of saved source observations by symbol."""

from __future__ import annotations
import asyncio
import hmac
import re
from typing import Annotated

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, Response, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app import config, dividend_source_storage as storage
from app.dividend_source_wire import (
    PREFIX,
    MAX_MANIFEST_BYTES,
    MAX_ARTIFACT_BYTES,
    Manifest,
    digest,
    parse_object,
    validate_artifact,
)

router = APIRouter(
    prefix="/private/tdnet/dividend-sources", tags=["private-dividend-sources"]
)
_bearer = HTTPBearer(auto_error=False)
_gate = asyncio.Semaphore(1)
_HEADERS = {"Cache-Control": "private, no-store"}


def error(status, message):
    return HTTPException(status_code=status, detail=message, headers=dict(_HEADERS))


async def require_key(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer)],
):
    expected = config.DIVIDEND_SOURCE_API_KEY
    if not expected:
        raise error(503, "private dividend authentication is not configured")
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not hmac.compare_digest(credentials.credentials.encode(), expected.encode())
    ):
        exc = error(401, "invalid or missing bearer token")
        exc.headers["WWW-Authenticate"] = "Bearer"
        raise exc


def _code(code):
    if not re.fullmatch(r"[0-9A-Z]{4}", code):
        raise error(400, "invalid security code")


async def _manifest(code):
    try:
        body = await storage.read_bytes(
            f"{PREFIX}/by-code/{code}/manifest.json", MAX_MANIFEST_BYTES
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "NoSuchKey":
            raise error(404, "no saved dividend source for security code") from exc
        raise
    model = Manifest.model_validate(parse_object(body, MAX_MANIFEST_BYTES))
    if model.security_code != code:
        raise ValueError("manifest issuer mismatch")
    sha = digest(body)
    snapshot = await storage.read_bytes(
        f"{PREFIX}/manifests/{sha}.json", MAX_MANIFEST_BYTES
    )
    if snapshot != body:
        raise ValueError("manifest snapshot mismatch")
    return body, model


@router.get(
    "/{security_code}",
    dependencies=[Depends(require_key)],
    response_model=Manifest,
    summary="Read a saved symbol's private dividend source manifest",
)
async def manifest(security_code: str):
    """Return the stored manifest bytes unchanged; missing means unsaved, never zero."""
    _code(security_code)
    async with _gate:
        try:
            body, _ = await _manifest(security_code)
            return Response(
                content=body,
                media_type="application/json",
                headers=_HEADERS | {"X-Content-SHA256": digest(body)},
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise error(503, "saved dividend source is unavailable or invalid") from exc


@router.get(
    "/{security_code}/documents/{disclosure_id}/{artifact_sha256}",
    dependencies=[Depends(require_key)],
    response_class=Response,
    summary="Read one manifest-authorized exact dividend source artifact",
)
async def document(security_code: str, disclosure_id: str, artifact_sha256: str):
    """Return exact JSON bytes only after manifest membership, SHA and identity checks."""
    _code(security_code)
    if not re.fullmatch(r"[0-9]{18}", disclosure_id) or not re.fullmatch(
        r"[0-9a-f]{64}", artifact_sha256
    ):
        raise error(400, "invalid artifact identity")
    async with _gate:
        try:
            _, model = await _manifest(security_code)
            entries = [
                e
                for e in model.entries
                if e.disclosure_id == disclosure_id
                and e.artifact_sha256 == artifact_sha256
            ]
            if len(entries) != 1:
                raise error(404, "artifact is not shared for security code")
            body = await storage.read_bytes(
                f"{PREFIX}/documents/{disclosure_id}/{artifact_sha256}.json",
                MAX_ARTIFACT_BYTES,
            )
            validate_artifact(body, entries[0], security_code)
            return Response(
                content=body,
                media_type="application/json",
                headers=_HEADERS | {"X-Content-SHA256": artifact_sha256},
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise error(503, "saved dividend source is unavailable or invalid") from exc
