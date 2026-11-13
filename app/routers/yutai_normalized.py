"""Authenticated reads of explicit reviewed V2 source releases."""

from __future__ import annotations
import hmac
from typing import Annotated, Literal
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Response, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app import config, yutai_normalized_service as service
from app.yutai_normalized_worker import SavedReadError
from app.yutai_normalized_schema import YutaiNormalizedRecordV2

router = APIRouter(
    prefix="/private/yutai/normalized", tags=["private-yutai-normalized"]
)
_bearer = HTTPBearer(auto_error=False)
_HEADERS = {"Cache-Control": "private, no-store"}


class NormalizedReadDocument(BaseModel):
    # Documentation model only; the route preserves already validated exact bytes.
    schema_version: Literal["yutai-normalized-read-v1"]
    release_sha256: str
    month: str
    code: str
    record_sha256: str
    record: YutaiNormalizedRecordV2


def error(status, message):
    return HTTPException(status_code=status, detail=message, headers=dict(_HEADERS))


async def require_key(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer)],
):
    expected = config.YUTAI_NORMALIZED_API_KEY
    if not expected:
        raise error(503, "private normalized authentication is not configured")
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not hmac.compare_digest(credentials.credentials.encode(), expected.encode())
    ):
        exc = error(401, "invalid or missing bearer token")
        exc.headers["WWW-Authenticate"] = "Bearer"
        raise exc


@router.get(
    "/releases/{release_sha256}/records/{month}/{code}",
    dependencies=[Depends(require_key)],
    response_model=NormalizedReadDocument,
    summary="Read one reviewed source record for an explicit rights month",
)
async def record(release_sha256: str, month: str, code: str):
    """404 means not saved in this partial release, never no benefit. No DB adoption."""
    try:
        body, sha = await service.read_saved(month + "/" + code, release_sha256)
        return Response(
            content=body,
            media_type="application/json",
            headers=_HEADERS | {"X-Content-SHA256": sha},
        )
    except SavedReadError as exc:
        raise error(
            exc.status,
            "record is not saved in release"
            if exc.status == 404
            else "normalized source is unavailable",
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise error(503, "normalized source is unavailable or invalid") from exc
