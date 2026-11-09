"""Authenticated exact-byte reads of saved pending yutai comparison history."""

from __future__ import annotations
import hmac
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Response, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app import config, yutai_comparison_service as service
from app.yutai_comparison_worker import SavedReadError
from app.yutai_comparison_wire import (
    HistoryReceipt,
    ComparisonReport,
)

router = APIRouter(
    prefix="/private/yutai/comparisons", tags=["private-yutai-comparisons"]
)
_bearer = HTTPBearer(auto_error=False)
_HEADERS = {"Cache-Control": "private, no-store"}


def error(status, message):
    return HTTPException(status_code=status, detail=message, headers=dict(_HEADERS))


async def require_key(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer)],
):
    expected = config.YUTAI_COMPARISON_API_KEY
    if not expected:
        raise error(503, "private comparison authentication is not configured")
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not hmac.compare_digest(credentials.credentials.encode(), expected.encode())
    ):
        exc = error(401, "invalid or missing bearer token")
        exc.headers["WWW-Authenticate"] = "Bearer"
        raise exc


@router.get(
    "/receipts/{receipt_sha256}",
    dependencies=[Depends(require_key)],
    response_model=HistoryReceipt,
    summary="Read a saved pending comparison receipt by exact digest",
)
async def receipt(receipt_sha256: str):
    """No acquisition, review acceptance or latest-pointer inference. Unknown is not absence."""
    try:
        body, sha = await service.read_saved("receipt", receipt_sha256)
        return Response(
            content=body,
            media_type="application/json",
            headers=_HEADERS | {"X-Content-SHA256": sha},
        )
    except SavedReadError as exc:
        raise error(exc.status, "comparison history is unavailable") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise error(503, "saved comparison receipt is unavailable or invalid") from exc


@router.get(
    "/receipts/{receipt_sha256}/report",
    dependencies=[Depends(require_key)],
    response_model=ComparisonReport,
    summary="Read the exact comparison report referenced by a saved receipt",
)
async def report(receipt_sha256: str):
    """Return unchanged JSON bytes after receipt, digest, schema and summary checks."""
    try:
        body, sha = await service.read_saved("report", receipt_sha256)
        return Response(
            content=body,
            media_type="application/json",
            headers=_HEADERS | {"X-Content-SHA256": sha},
        )
    except SavedReadError as exc:
        raise error(exc.status, "comparison history is unavailable") from exc
    except HTTPException:
        raise
    except Exception as exc:
        # Missing referenced report is an incomplete/corrupt saved pair, not404.
        raise error(503, "saved comparison report is unavailable or invalid") from exc
