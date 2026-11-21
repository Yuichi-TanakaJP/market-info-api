"""Authenticated reads of pinned EDINET financial artifacts."""

import hmac
import json
import re
from hashlib import sha256
from typing import Annotated

from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException, Response, Security
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app import config, dividend_source_storage as storage

router = APIRouter(prefix="/private/edinet/financials", tags=["private-edinet-financials"])
_bearer = HTTPBearer(auto_error=False)
_HEADERS = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}
_PREFIX = "edinet/financial-evidence/v1/daily/derived/period_compact"
_SCHEMA = "edinet-financial-compact-period-integrated-v1"
_MAX_BYTES = 4 * 1024 * 1024


def _error(status: int, detail: str) -> HTTPException:
    headers = dict(_HEADERS)
    if status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    return HTTPException(status, detail, headers=headers)


def _unique_object(pairs):
    values = dict(pairs)
    if len(values) != len(pairs):
        raise ValueError("duplicate JSON key")
    return values


def _reject_nonfinite(_value):
    raise ValueError("nonfinite JSON constant")


@router.get(
    "/{doc_id}/{artifact_sha256}",
    response_class=JSONResponse,
    summary="Read a pinned EDINET financial artifact",
    responses={
        400: {"description": "Invalid EDINET document selector"},
        401: {"description": "EDINET reader bearer token required"},
        404: {"description": "Exact saved artifact not found"},
        503: {"description": "Private reader or verified artifact unavailable"},
    },
)
async def financial_artifact(
    doc_id: str,
    artifact_sha256: str,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer)],
) -> Response:
    """Return the exact period-integrated compact JSON stored by Market Info."""
    token = config.EDINET_FINANCIAL_API_KEY
    if not token:
        raise _error(503, "EDINET authentication is not configured")
    if credentials is None or not hmac.compare_digest(
        credentials.credentials.encode(), token.encode()
    ):
        raise _error(401, "invalid or missing bearer token")
    if not re.fullmatch(r"S[A-Z0-9]{7}", doc_id) or not re.fullmatch(
        r"[0-9a-f]{64}", artifact_sha256
    ):
        raise _error(400, "invalid EDINET document selector")
    try:
        body = await storage.read_edinet_bytes(f"{_PREFIX}/{artifact_sha256}", _MAX_BYTES)
        if not 0 < len(body) <= _MAX_BYTES or sha256(body).hexdigest() != artifact_sha256:
            raise ValueError("artifact digest or size mismatch")
        artifact = json.loads(
            body, object_pairs_hook=_unique_object, parse_constant=_reject_nonfinite
        )
        if not isinstance(artifact, dict) or artifact.get("schema_version") != _SCHEMA:
            raise ValueError("unexpected artifact schema")
        if artifact.get("doc_id") != doc_id:
            raise _error(404, "exact EDINET artifact not found")
        facts = artifact.get("facts")
        if (
            not isinstance(facts, list)
            or type(artifact.get("fact_count")) is not int
            or artifact["fact_count"] != len(facts)
        ):
            raise ValueError("artifact fact count mismatch")
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "NoSuchKey":
            raise _error(404, "exact EDINET artifact not found") from None
        raise _error(503, "private EDINET artifact unavailable") from None
    except HTTPException:
        raise
    except Exception:
        raise _error(503, "private EDINET artifact unavailable or invalid") from None
    return Response(
        body, media_type="application/json",
        headers=_HEADERS | {"X-Content-SHA256": artifact_sha256},
    )
