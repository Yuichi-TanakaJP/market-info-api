from __future__ import annotations

import asyncio
import json

import boto3
from botocore.config import Config

from app import config

_TIMEOUT = 5


def _required(value: str, name: str) -> str:
    if not value:
        raise RuntimeError(f"missing required env var: {name}")
    return value


def _build_client():
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
