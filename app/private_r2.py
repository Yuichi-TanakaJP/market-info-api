from __future__ import annotations

import asyncio
import json
import re
import threading
from urllib.parse import quote
from xml.etree import ElementTree

import httpx
from botocore.auth import S3SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from botocore.exceptions import ClientError


from app import config

_TIMEOUT = 5


def _required(value: str, name: str) -> str:
    if not value:
        raise RuntimeError(f"missing required env var: {name}")
    return value


def _build_client():
    # Public requests do not use the private S3 SDK.
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=_required(
            config.YUTAI_STOCK_PRICES_PRIVATE_ENDPOINT,
            "YUTAI_STOCK_PRICES_PRIVATE_ENDPOINT",
        ),
        aws_access_key_id=_required(
            config.YUTAI_STOCK_PRICES_PRIVATE_ACCESS_KEY_ID,
            "YUTAI_STOCK_PRICES_PRIVATE_ACCESS_KEY_ID",
        ),
        aws_secret_access_key=_required(
            config.YUTAI_STOCK_PRICES_PRIVATE_SECRET_ACCESS_KEY,
            "YUTAI_STOCK_PRICES_PRIVATE_SECRET_ACCESS_KEY",
        ),
        region_name=config.YUTAI_STOCK_PRICES_PRIVATE_REGION,
        config=Config(
            connect_timeout=_TIMEOUT,
            read_timeout=_TIMEOUT,
            retries={"max_attempts": 2, "mode": "standard"},
        ),
    )


def _fetch_json_sync(key: str) -> dict:
    bucket = _required(
        config.YUTAI_STOCK_PRICES_PRIVATE_BUCKET,
        "YUTAI_STOCK_PRICES_PRIVATE_BUCKET",
    )
    response = _build_client().get_object(Bucket=bucket, Key=key)
    data = json.loads(response["Body"].read().decode("utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(
            f"expected JSON object from private R2, got {type(data).__name__}"
        )
    return data


async def fetch_json(key: str) -> dict:
    return await asyncio.to_thread(_fetch_json_sync, key)


class StockPriceStorageNotConfigured(RuntimeError):
    pass


_STOCK_PRICES_MAX_BYTES = 4 * 1024 * 1024
_STOCK_PRICES_ERROR_MAX_BYTES = 8 * 1024
_STOCK_PRICES_CONTAINER_LIMIT = 32_000
_STOCK_PRICES_SEPARATOR_LIMIT = 200_000
_STOCK_PRICES_DEADLINE = 15
_STOCK_PRICES_READ_SLOTS = threading.BoundedSemaphore(4)
_STOCK_PRICES_R2_ENDPOINT = re.compile(
    r"https://[0-9a-f]{32}(?:\.(?:eu|fedramp|us))?\.r2\.cloudflarestorage\.com/?"
)


def _stock_price_request(key: str) -> AWSRequest:
    bucket = config.STOCK_PRICES_PRIVATE_BUCKET
    endpoint = config.STOCK_PRICES_PRIVATE_ENDPOINT
    access_key = config.STOCK_PRICES_PRIVATE_ACCESS_KEY_ID
    secret_key = config.STOCK_PRICES_PRIVATE_SECRET_ACCESS_KEY
    if (
        not all((bucket, access_key, secret_key))
        or not _STOCK_PRICES_R2_ENDPOINT.fullmatch(endpoint)
        or config.STOCK_PRICES_PRIVATE_REGION != "auto"
    ):
        raise StockPriceStorageNotConfigured
    url = f"{endpoint.rstrip('/')}/{quote(bucket, safe='')}/{quote(key, safe='/')}"
    request = AWSRequest(method="GET", url=url, headers={"Accept-Encoding": "identity"})
    credentials = Credentials(access_key, secret_key)
    S3SigV4Auth(credentials, "s3", "auto").add_auth(request)
    return request


async def _bounded_stock_prices_body(response: httpx.Response, limit: int) -> bytearray:
    if response.headers.get("Content-Encoding", "identity").lower() != "identity":
        raise ValueError("unexpected private R2 response encoding")
    body = bytearray()
    async for chunk in response.aiter_raw():
        if len(body) + len(chunk) > limit:
            raise ValueError("private stock-price response exceeds size limit")
        body.extend(chunk)
    return body


async def _read_stock_prices(client: httpx.AsyncClient, request: AWSRequest) -> dict:
    async with client.stream("GET", request.url, headers=dict(request.headers.items())) as response:
        if response.status_code == 404:
            body = await _bounded_stock_prices_body(response, _STOCK_PRICES_ERROR_MAX_BYTES)
            failure = ElementTree.fromstring(body)
            error_codes = [
                node for node in failure.iter() if node.tag.rsplit("}", 1)[-1] == "Code"
            ]
            if (
                failure.tag == "Error"
                and len(error_codes) == 1
                and failure.find("Code") is error_codes[0]
            ):
                code = error_codes[0]
                if code.text == "NoSuchKey" and not code.attrib and len(code) == 0:
                    raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        if response.status_code != 200:
            raise ValueError("unexpected private R2 response status")
        count = response.headers.get("Content-Length")
        if count is None or not count.isascii() or not count.isdecimal():
            raise ValueError("invalid stock-price object length")
        length = int(count)
        if not 0 < length <= _STOCK_PRICES_MAX_BYTES:
            raise ValueError("invalid stock-price object size")
        body = await _bounded_stock_prices_body(response, length)
        if len(body) != length:
            raise ValueError("invalid stock-price object length")
        # Price artifacts have flat records and small provenance objects.
        # Count structural delimiters before allocating parsed containers.
        count = body.count(b"{") + body.count(b"[")
        if count > _STOCK_PRICES_CONTAINER_LIMIT or body.count(b",") > _STOCK_PRICES_SEPARATOR_LIMIT:
            raise ValueError("private stock-price object exceeds structure limits")
        return json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_unique_stock_price_json,
            parse_constant=_reject_stock_price_constant,
        )


def _unique_stock_price_json(pairs):
    value = dict(pairs)
    if len(value) != len(pairs):
        raise ValueError("duplicate JSON key")
    return value


def _reject_stock_price_constant(_value):
    raise ValueError("nonstandard stock-price JSON constant")


async def fetch_stock_prices_json(key: str) -> dict:
    request = _stock_price_request(key)
    if not _STOCK_PRICES_READ_SLOTS.acquire(blocking=False):
        raise RuntimeError("private stock-price reader is busy")
    try:
        # The request owns its connection and capacity through response cleanup.
        # The async deadline covers header arrival as well as streamed bodies.
        async with asyncio.timeout(_STOCK_PRICES_DEADLINE):
            async with httpx.AsyncClient(
                timeout=_TIMEOUT, verify=True, follow_redirects=False, trust_env=False
            ) as client:
                return await _read_stock_prices(client, request)
    finally:
        _STOCK_PRICES_READ_SLOTS.release()
