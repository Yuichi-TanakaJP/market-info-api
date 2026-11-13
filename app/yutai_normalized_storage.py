"""Dedicated bounded private reads, including workers surviving HTTP cancellation."""

from __future__ import annotations

import asyncio
from urllib.parse import urlsplit
from functools import partial
import threading
import time

from app import config

# An asyncio request lock cannot protect a to_thread worker after its caller is
# cancelled. Hold this process-local slot inside the worker until all I/O closes.
_READ_SLOT = threading.BoundedSemaphore(1)
READ_BUDGET_SECONDS = 30


def _read_sync(key: str, limit: int) -> bytes:
    if not _READ_SLOT.acquire(blocking=False):
        raise RuntimeError("private normalized reader is busy")
    try:
        return _read_claimed(key, limit)
    finally:
        _READ_SLOT.release()


def _read_claimed(key: str, limit: int) -> bytes:
    started = time.monotonic()
    import boto3
    from botocore.config import Config

    names = ("BUCKET", "ENDPOINT", "ACCESS_KEY_ID", "SECRET_ACCESS_KEY")
    values = {n: getattr(config, f"YUTAI_NORMALIZED_PRIVATE_{n}") for n in names}
    if not all(values.values()):
        raise RuntimeError("private normalized storage is not configured")
    endpoint = urlsplit(values["ENDPOINT"])
    if (
        endpoint.scheme != "https"
        or not endpoint.hostname
        or endpoint.username
        or endpoint.password
        or endpoint.query
        or endpoint.fragment
    ):
        raise ValueError("private endpoint requires HTTPS without credentials/query")
    client = boto3.client(
        "s3",
        endpoint_url=values["ENDPOINT"],
        aws_access_key_id=values["ACCESS_KEY_ID"],
        aws_secret_access_key=values["SECRET_ACCESS_KEY"],
        region_name=config.YUTAI_NORMALIZED_PRIVATE_REGION,
        config=Config(
            connect_timeout=5,
            read_timeout=10,
            retries={"total_max_attempts": 1, "mode": "standard"},
        ),
    )
    try:
        response = client.get_object(Bucket=values["BUCKET"], Key=key)
        stream = response["Body"]
        try:
            declared = response.get("ContentLength")
            if type(declared) is not int or not 0 < declared <= limit:
                raise ValueError("invalid private object length")
            body = bytearray()
            while True:
                if time.monotonic() - started > READ_BUDGET_SECONDS:
                    raise ValueError("private object elapsed budget")
                # The supervised child has a hard outer deadline; chunk reads
                # preserve byte bounds without millions of SDK calls.
                chunk = stream.read(min(65536, limit + 1 - len(body)))
                if time.monotonic() - started > READ_BUDGET_SECONDS:
                    raise ValueError("private object elapsed budget")
                if not chunk:
                    break
                if len(body) + len(chunk) > declared:
                    raise ValueError("private object length mismatch")
                body.extend(chunk)
            if len(body) != declared:
                raise ValueError("private object length mismatch")
            return bytes(body)
        finally:
            stream.close()
    finally:
        client.close()


async def read_bytes(key: str, limit: int) -> bytes:
    return await asyncio.to_thread(partial(_read_sync, key, limit))
