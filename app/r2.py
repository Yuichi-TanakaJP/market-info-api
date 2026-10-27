from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import math
import re

from cachetools import LRUCache
import httpx

from app.config import R2_PUBLIC_BASE_URL
from app.tdnet_cache_policy import TDNET_MUTABLE_OBJECTS

_TIMEOUT = 5.0
_client: httpx.AsyncClient | None = None


@dataclass(frozen=True)
class _ETagBody:
    etag: str
    body: bytes


# Only the five mutable TDNET objects use this store. Bodies are immutable bytes;
# every reuse still requires upstream confirmation, and parsing returns a fresh dict.
_TDNET_BODY_CACHE_BYTES = 8 * 1024 * 1024
_tdnet_bodies = LRUCache(maxsize=_TDNET_BODY_CACHE_BYTES, getsizeof=lambda entry: len(entry.body))
_tdnet_locks: dict[str, asyncio.Lock] = {}
_ETAG_RE = re.compile(r'(?:W/)?"[\x21\x23-\x7e]*"')


def _etag(value: str | None) -> str | None:
    return value if value and len(value) <= 1024 and _ETAG_RE.fullmatch(value) else None


def _opaque_tag(value: str) -> str:
    return value.removeprefix("W/")


def _object(data, url: str) -> dict:
    if not isinstance(data, dict):
        raise RuntimeError(f"expected JSON object from {url}, got {type(data).__name__}")
    return data


def _reject_constant(value: str):
    raise ValueError("nonstandard JSON numeric constant")


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("JSON number exceeds finite float range")
    return number


def _validate_unicode(data: dict) -> None:
    pending = [data]
    while pending:
        value = pending.pop()
        if isinstance(value, str):
            value.encode("utf-8")  # rejects unpaired surrogates in values and keys
        elif isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)


def _parse_tdnet_body(body: bytes, url: str) -> dict:
    # Published TDNET JSON is UTF-8; do not use json.loads(bytes)' surrogatepass.
    text = body.decode("utf-8-sig")
    data = _object(json.loads(text, parse_constant=_reject_constant, parse_float=_finite_float), url)
    _validate_unicode(data)
    return data


async def _fetch_tdnet_json(path: str, url: str) -> dict:
    lock = _tdnet_locks.setdefault(path, asyncio.Lock())
    async with lock:
        cached = _tdnet_bodies.get(url)
        headers = {"Cache-Control": "no-cache"}
        if cached is not None:
            headers["If-None-Match"] = cached.etag
        try:
            response = await get_client().get(url, headers=headers)
            if response.status_code == 304:
                if cached is None:
                    raise RuntimeError("R2 returned 304 without a retained TDNET body")
                response_tag = response.headers.get("ETag")
                if response_tag is not None and (
                    _etag(response_tag) is None
                    or _opaque_tag(response_tag) != _opaque_tag(cached.etag)
                ):
                    raise RuntimeError("R2 returned 304 with an inconsistent ETag")
                return _parse_tdnet_body(cached.body, url)
            response.raise_for_status()
            if response.status_code != 200:
                raise RuntimeError("expected a complete HTTP 200 TDNET response")
            data = _parse_tdnet_body(response.content, url)
            # An absent/invalid ETag or oversized body cannot safely be reused.
            # Discard the previous validator even if the new body is uncacheable.
            _tdnet_bodies.pop(url, None)
            tag = _etag(response.headers.get("ETag"))
            if tag is not None and len(response.content) <= _TDNET_BODY_CACHE_BYTES:
                _tdnet_bodies[url] = _ETagBody(tag, response.content)
            return data
        except BaseException:
            # Includes timeout/cancellation: no stale fallback; next attempt starts fresh.
            _tdnet_bodies.pop(url, None)
            raise


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
    _tdnet_bodies.clear()
    _tdnet_locks.clear()


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
    if path in TDNET_MUTABLE_OBJECTS:
        return await _fetch_tdnet_json(path, url)
    mutable = path in {"stock-ranking/manifest.json", "topix33/topix33_manifest.json", "nikkei-contribution/nikkei_contribution_manifest.json", "investor-flow/manifest.json", "investor-flow/latest.json", "investor-flow-analysis/manifest.json", "investor-flow-analysis/latest.json"}
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
