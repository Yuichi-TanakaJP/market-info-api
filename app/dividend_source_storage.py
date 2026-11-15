"""Dedicated bounded private reads, including workers surviving HTTP cancellation."""

from __future__ import annotations

import asyncio
from functools import partial
import threading
import time

from app import config

# An asyncio request lock cannot protect a to_thread worker after its caller is
# cancelled. Hold this process-local slot inside the worker until all I/O closes.
_READ_SLOT = threading.BoundedSemaphore(1)
READ_BUDGET_SECONDS = 30
AVAILABLE_CHUNK_BYTES = 64 * 1024


def _read_sync(key: str, limit: int, *, available_chunks: bool = False) -> bytes:
    if not _READ_SLOT.acquire(blocking=False):
        raise RuntimeError("private dividend reader is busy")
    try:
        return _read_claimed(key, limit, available_chunks=available_chunks)
    finally:
        _READ_SLOT.release()


def _available_reader(stream):
    """Opt in only for the locked botocore/urllib3 stream implementation.

    StreamingBody.read(n) waits to fill n. The underlying HTTPResponse.read1(n,
    decode_content=False) makes at most one buffered transport read, returning
    available bytes so the caller can recheck its elapsed deadline. We bypass
    StreamingBody's byte counter and checksum-subclass read validation here.
    The caller independently enforces exact length; the only opting-in route
    validates the pinned SHA-256 and magic before returning any bytes. The
    StreamingBody and its raw response close on all paths.
    Unknown/test stream types retain the existing one-byte bounded read.
    """
    from botocore.response import StreamingBody
    from urllib3.response import HTTPResponse

    raw = getattr(stream, "_raw_stream", None)
    if isinstance(stream, StreamingBody) and isinstance(raw, HTTPResponse):
        read1 = getattr(raw, "read1", None)
        if callable(read1):
            return partial(read1, decode_content=False)
    return None


def _read_claimed(key: str, limit: int, *, available_chunks: bool = False) -> bytes:
    started = time.monotonic()
    import boto3
    from botocore.config import Config

    names = ("BUCKET", "ENDPOINT", "ACCESS_KEY_ID", "SECRET_ACCESS_KEY")
    values = {n: getattr(config, f"DIVIDEND_SOURCE_PRIVATE_{n}") for n in names}
    if not all(values.values()):
        raise RuntimeError("private dividend storage is not configured")
    client = boto3.client(
        "s3",
        endpoint_url=values["ENDPOINT"],
        aws_access_key_id=values["ACCESS_KEY_ID"],
        aws_secret_access_key=values["SECRET_ACCESS_KEY"],
        region_name=config.DIVIDEND_SOURCE_PRIVATE_REGION,
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
            read_available = _available_reader(stream) if available_chunks else None
            while True:
                if time.monotonic() - started > READ_BUDGET_SECONDS:
                    raise ValueError("private object elapsed budget")
                # Never use a filling read(n): slow trickle must return control
                # between available chunks, with the socket timeout still 10s.
                size = min(AVAILABLE_CHUNK_BYTES, declared - len(body) + 1)
                chunk = read_available(size) if read_available else stream.read(1)
                if time.monotonic() - started > READ_BUDGET_SECONDS:
                    raise ValueError("private object elapsed budget")
                if not isinstance(chunk, bytes):
                    raise ValueError("invalid private object chunk")
                if not chunk:
                    break
                if len(chunk) > size or len(body) + len(chunk) > declared:
                    raise ValueError("private object length mismatch")
                body.extend(chunk)
            if len(body) != declared:
                raise ValueError("private object length mismatch")
            return bytes(body)
        finally:
            stream.close()
    finally:
        client.close()


async def read_bytes(key: str, limit: int, *, available_chunks: bool = False) -> bytes:
    return await asyncio.to_thread(
        partial(_read_sync, key, limit, available_chunks=available_chunks)
    )
