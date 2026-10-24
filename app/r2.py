from __future__ import annotations

import httpx

from app.config import R2_PUBLIC_BASE_URL

_TIMEOUT = 5.0
_client: httpx.AsyncClient | None = None


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=_TIMEOUT)
    return _client


async def fetch_json(path: str) -> dict:
    """Fetch a JSON object from R2 public URL.

    Args:
        path: Object path relative to R2_PUBLIC_BASE_URL (no leading slash).

    Raises:
        httpx.HTTPStatusError: on 4xx/5xx responses.
        RuntimeError: if the response is not a JSON object.
    """
    url = f"{R2_PUBLIC_BASE_URL}/{path}"
    mutable = path in {"stock-ranking/manifest.json", "topix33/topix33_manifest.json", "nikkei-contribution/nikkei_contribution_manifest.json"}
    resp = await get_client().get(url, headers={"Cache-Control": "no-cache"} if mutable else {})
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"expected JSON object from {url}, got {type(data).__name__}")
    return data


async def fetch_json_array(path: str) -> list:
    """Fetch a JSON array from an R2 public URL."""
    url = f"{R2_PUBLIC_BASE_URL}/{path}"
    resp = await get_client().get(url)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        raise RuntimeError(f"expected JSON array from {url}, got {type(data).__name__}")
    return data
