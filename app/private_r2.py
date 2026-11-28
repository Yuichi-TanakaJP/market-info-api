from __future__ import annotations

import asyncio
import json


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


def _stock_prices_json_sync(key: str) -> dict:
    import boto3
    from botocore.config import Config

    bucket = config.STOCK_PRICES_PRIVATE_BUCKET
    endpoint = config.STOCK_PRICES_PRIVATE_ENDPOINT
    access_key = config.STOCK_PRICES_PRIVATE_ACCESS_KEY_ID
    secret_key = config.STOCK_PRICES_PRIVATE_SECRET_ACCESS_KEY
    if not all((bucket, endpoint, access_key, secret_key)):
        raise StockPriceStorageNotConfigured
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=config.STOCK_PRICES_PRIVATE_REGION,
        config=Config(
            connect_timeout=_TIMEOUT,
            read_timeout=_TIMEOUT,
            retries={"total_max_attempts": 1, "mode": "standard"},
        ),
    )
    try:
        response = client.get_object(Bucket=bucket, Key=key)
        stream = response["Body"]
        try:
            length = response.get("ContentLength")
            if type(length) is not int or not 0 < length <= _STOCK_PRICES_MAX_BYTES:
                raise ValueError("invalid stock-price object size")
            data = stream.read(length + 1)
            if len(data) != length:
                raise ValueError("invalid stock-price object length")
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


async def fetch_stock_prices_json(key: str) -> dict:
    return await asyncio.to_thread(_stock_prices_json_sync, key)
