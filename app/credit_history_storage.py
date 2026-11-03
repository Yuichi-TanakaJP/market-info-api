"""Bounded private source reads for credit inventory (dedicated credentials)."""

from __future__ import annotations

import asyncio
from functools import partial

from app import config


def _read_sync(key: str, limit: int) -> bytes:
    import boto3
    from botocore.config import Config

    names = ("BUCKET", "ENDPOINT", "ACCESS_KEY_ID", "SECRET_ACCESS_KEY")
    values = {n: getattr(config, f"CREDIT_HISTORY_PRIVATE_{n}") for n in names}
    if not all(values.values()):
        raise RuntimeError("credit history private storage is not configured")
    client = boto3.client(
        "s3",
        endpoint_url=values["ENDPOINT"],
        aws_access_key_id=values["ACCESS_KEY_ID"],
        aws_secret_access_key=values["SECRET_ACCESS_KEY"],
        region_name=config.CREDIT_HISTORY_PRIVATE_REGION,
        config=Config(
            connect_timeout=5,
            read_timeout=10,
            retries={"max_attempts": 2, "mode": "standard"},
        ),
    )
    try:
        response = client.get_object(Bucket=values["BUCKET"], Key=key)
        stream = response["Body"]
        try:
            body = stream.read(limit + 1)
        finally:
            stream.close()
    finally:
        client.close()
    if len(body) > limit:
        raise ValueError("credit history object exceeds size limit")
    return body


async def read_bytes(key: str, limit: int) -> bytes:
    return await asyncio.to_thread(partial(_read_sync, key, limit))
