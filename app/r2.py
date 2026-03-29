from __future__ import annotations

import httpx

from app.config import R2_PUBLIC_BASE_URL

_TIMEOUT = 5.0


async def fetch_json(path: str) -> dict:
    """Fetch a JSON object from R2 public URL.

    Args:
        path: Object path relative to R2_PUBLIC_BASE_URL (no leading slash).

    Raises:
        httpx.HTTPStatusError: on 4xx/5xx responses.
        RuntimeError: if the response is not a JSON object.
    """
    url = f"{R2_PUBLIC_BASE_URL}/{path}"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(url)
        resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"expected JSON object from {url}, got {type(data).__name__}")
    return data
