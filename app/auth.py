from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app import cache, config

_bearer = HTTPBearer(auto_error=False)


async def require_yutai_stock_prices_key(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(_bearer),
    ],
) -> None:
    expected = config.YUTAI_STOCK_PRICES_API_KEY
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="private stock-price authentication is not configured",
            headers={"Cache-Control": cache.PRIVATE_HTTP_CACHE_CONTROL},
        )
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not secrets.compare_digest(credentials.credentials, expected)
    ):
        raise HTTPException(
            status_code=401,
            detail="invalid or missing bearer token",
            headers={
                "WWW-Authenticate": "Bearer",
                "Cache-Control": cache.PRIVATE_HTTP_CACHE_CONTROL,
            },
        )
