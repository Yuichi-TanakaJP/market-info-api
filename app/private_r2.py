from __future__ import annotations

import asyncio
import json
import re
import threading
import time


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
_STOCK_PRICES_DEADLINE = 15
_STOCK_PRICES_READ_SLOTS = threading.BoundedSemaphore(4)
_STOCK_PRICES_R2_ENDPOINT = re.compile(
    r"https://[0-9a-f]{32}(?:\.(?:eu|fedramp|us))?\.r2\.cloudflarestorage\.com/?"
)


def _stock_prices_json_sync(key: str) -> dict:
    import boto3
    from botocore.config import Config

    bucket = config.STOCK_PRICES_PRIVATE_BUCKET
    endpoint = config.STOCK_PRICES_PRIVATE_ENDPOINT
    access_key = config.STOCK_PRICES_PRIVATE_ACCESS_KEY_ID
    secret_key = config.STOCK_PRICES_PRIVATE_SECRET_ACCESS_KEY
    if not all((bucket, access_key, secret_key)) or not _STOCK_PRICES_R2_ENDPOINT.fullmatch(endpoint):
        raise StockPriceStorageNotConfigured
    deadline = time.monotonic() + _STOCK_PRICES_DEADLINE
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=config.STOCK_PRICES_PRIVATE_REGION,
        verify=True,
        config=Config(
            connect_timeout=_TIMEOUT,
            read_timeout=_TIMEOUT,
            retries={"total_max_attempts": 1, "mode": "standard"},
            s3={"addressing_style": "path"},
        ),
    )
    try:
        response = client.get_object(Bucket=bucket, Key=key)
        stream = response["Body"]
        try:
            length = response.get("ContentLength")
            if type(length) is not int or not 0 < length <= _STOCK_PRICES_MAX_BYTES:
                raise ValueError("invalid stock-price object size")
            data = bytearray()
            # A filling SDK read can keep waiting as bytes trickle in. Recheck
            # elapsed time between bounded, non-filling reads.
            while len(data) <= length and time.monotonic() < deadline:
                chunk = stream.read(1)
                if not chunk:
                    break
                data.extend(chunk)
            if time.monotonic() >= deadline or len(data) != length:
                raise ValueError("invalid stock-price object length or elapsed budget")
            return json.loads(data.decode("utf-8"), object_pairs_hook=_unique_stock_price_json)
        finally:
            stream.close()
    finally:
        client.close()


def _unique_stock_price_json(pairs):
    value = dict(pairs)
    if len(value) != len(pairs):
        raise ValueError("duplicate JSON key")
    return value


def _stock_prices_read_reserved(key: str) -> dict:
    try:
        return _stock_prices_json_sync(key)
    finally:
        _STOCK_PRICES_READ_SLOTS.release()


def _consume_worker_error(future: asyncio.Future) -> None:
    # The HTTP request may have abandoned this future; do not log an unhandled
    # transport exception containing Private R2 metadata from the worker.
    if not future.cancelled():
        future.exception()


async def fetch_stock_prices_json(key: str) -> dict:
    if not _STOCK_PRICES_READ_SLOTS.acquire(blocking=False):
        raise RuntimeError("private stock-price reader is busy")
    try:
        pending = asyncio.get_running_loop().run_in_executor(
            None, _stock_prices_read_reserved, key
        )
    except BaseException:
        _STOCK_PRICES_READ_SLOTS.release()
        raise
    pending.add_done_callback(_consume_worker_error)
    # On timeout or request cancellation the running read retains its slot
    # until its response/client close.
    return await asyncio.wait_for(asyncio.shield(pending), _STOCK_PRICES_DEADLINE)
