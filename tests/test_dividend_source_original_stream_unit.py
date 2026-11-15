"""Real loopback SDK streams: bounded throughput, trickle, integrity and cancellation."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import io
import gzip
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from botocore.response import StreamingBody
import pytest
import urllib3

from app import config, dividend_source_storage as storage


@contextmanager
def sdk_response(
    payload, *, trickle_seconds=0, entered=None, release=None, content_encoding=None
):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            self.send_response(200)
            # No HTTP length so mismatch tests exercise our independent limit.
            self.send_header("Connection", "close")
            if content_encoding:
                self.send_header("Content-Encoding", content_encoding)
            self.end_headers()
            try:
                if trickle_seconds or release is not None:
                    for index, value in enumerate(payload):
                        self.wfile.write(bytes([value]))
                        self.wfile.flush()
                        if index == 0 and entered is not None:
                            entered.set()
                        if index == 0 and release is not None:
                            release.wait(3)
                        if trickle_seconds:
                            time.sleep(trickle_seconds)
                else:
                    self.wfile.write(payload)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    runner = threading.Thread(target=server.serve_forever, daemon=True)
    runner.start()
    pool = urllib3.PoolManager(
        timeout=urllib3.Timeout(connect=5, read=10), retries=False
    )
    response = None
    try:
        response = pool.request(
            "GET",
            f"http://127.0.0.1:{server.server_port}/synthetic",
            preload_content=False,
            decode_content=False,
        )
        yield response
    finally:
        if release is not None:
            release.set()
        if response is not None:
            response.close()
        pool.clear()
        server.shutdown()
        server.server_close()
        runner.join(2)


def client_for(monkeypatch, stream, length):
    import boto3

    class Client:
        closed = False
        configured = None

        def get_object(self, **_kwargs):
            return {"Body": stream, "ContentLength": length}

        def close(self):
            self.closed = True

    client = Client()

    def factory(*_args, **kwargs):
        client.configured = kwargs["config"]
        return client

    monkeypatch.setattr(boto3, "client", factory)
    for name in ("BUCKET", "ENDPOINT", "ACCESS_KEY_ID", "SECRET_ACCESS_KEY"):
        monkeypatch.setattr(config, "DIVIDEND_SOURCE_PRIVATE_" + name, "synthetic")
    return client


def assert_slot_free():
    assert storage._READ_SLOT.acquire(blocking=False)
    storage._READ_SLOT.release()


def test_five_mib_available_stream_preserves_bytes_in_bounded_calls(monkeypatch):
    payload = b"%PDF-" + bytes(range(256)) * 20480
    with sdk_response(payload) as response:
        original = response.read1
        sizes = []

        def observed(size, *, decode_content):
            assert decode_content is False
            sizes.append(size)
            return original(size, decode_content=False)

        response.read1 = observed
        body = StreamingBody(response, len(payload))
        client = client_for(monkeypatch, body, len(payload))
        started = time.monotonic()
        actual = storage._read_sync(
            "synthetic.pdf", 8 * 1024 * 1024, available_chunks=True
        )
        elapsed = time.monotonic() - started
        assert actual == payload
        assert len(sizes) < 2000  # Millions of byte reads would fail this bound.
        assert 0 < max(sizes) <= 65536
        assert elapsed < 10
        assert response.closed and client.closed
        assert client.configured.connect_timeout == 5
        assert client.configured.read_timeout == 10
        assert client.configured.retries == {
            "total_max_attempts": 1,
            "mode": "standard",
        }
        print(
            json.dumps(
                {
                    "synthetic_bytes": len(payload),
                    "read_calls": len(sizes),
                    "elapsed_seconds": round(elapsed, 4),
                }
            )
        )
    assert_slot_free()


def test_real_slow_trickle_returns_between_chunks_and_enforces_elapsed(monkeypatch):
    with sdk_response(b"x" * 40, trickle_seconds=0.04) as response:
        stream = StreamingBody(response, 40)
        client = client_for(monkeypatch, stream, 40)
        monkeypatch.setattr(storage, "READ_BUDGET_SECONDS", 0.15)
        started = time.monotonic()
        with pytest.raises(ValueError, match="elapsed budget"):
            storage._read_sync("synthetic.pdf", 40, available_chunks=True)
        elapsed = time.monotonic() - started
        assert elapsed < 0.7  # A filling read would wait about1.6s.
        assert response.closed and client.closed
    assert_slot_free()


@pytest.mark.parametrize("declared", [5, 15])
def test_actual_sdk_stream_rejects_overflow_and_truncation(monkeypatch, declared):
    with sdk_response(b"0123456789") as response:
        stream = StreamingBody(response, declared)
        client = client_for(monkeypatch, stream, declared)
        with pytest.raises(ValueError, match="length mismatch"):
            storage._read_sync("synthetic.pdf", 20, available_chunks=True)
        assert response.closed and client.closed
    assert_slot_free()


def test_opt_in_unknown_stream_keeps_one_byte_fallback(monkeypatch):
    class Legacy(io.BytesIO):
        def read(self, size):
            assert size == 1
            return super().read(size)

    stream = Legacy(b"exact")
    client = client_for(monkeypatch, stream, 5)
    assert storage._read_sync("synthetic", 5, available_chunks=True) == b"exact"
    assert stream.closed and client.closed
    assert_slot_free()


def test_opt_in_rejects_oversize_declared_before_any_body_read(monkeypatch):
    with sdk_response(b"abc") as response:
        stream = StreamingBody(response, 3)
        client = client_for(monkeypatch, stream, 3)
        with pytest.raises(ValueError, match="invalid private object length"):
            storage._read_sync("synthetic", 2, available_chunks=True)
        assert response.closed and client.closed
    assert_slot_free()


@pytest.mark.asyncio
async def test_cancelled_available_read_holds_slot_until_socket_worker_closes(
    monkeypatch,
):
    entered, release, closed = threading.Event(), threading.Event(), threading.Event()
    with sdk_response(b"ab", entered=entered, release=release) as response:
        stream = StreamingBody(response, 2)
        original_close = stream.close

        def mark_closed():
            original_close()
            closed.set()

        stream.close = mark_closed
        client = client_for(monkeypatch, stream, 2)
        caller = asyncio.create_task(
            storage.read_bytes("synthetic", 2, available_chunks=True)
        )
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            # Let the first byte be consumed and wait on the held-open socket.
            await asyncio.sleep(0.05)
            caller.cancel()
            with pytest.raises(asyncio.CancelledError):
                await caller
            with pytest.raises(RuntimeError, match="busy"):
                await storage.read_bytes("synthetic", 2, available_chunks=True)
            assert not client.closed
        finally:
            release.set()
            assert await asyncio.to_thread(closed.wait, 2)
            for _ in range(100):
                if storage._READ_SLOT.acquire(blocking=False):
                    storage._READ_SLOT.release()
                    break
                await asyncio.sleep(0.01)
            else:
                pytest.fail("slot remained held after worker completion")
        assert response.closed and client.closed


def test_actual_gzip_transport_keeps_compressed_bytes_without_decoding(monkeypatch):
    expanded = b"%PDF-" + b"x" * (5 * 1024 * 1024)
    payload = gzip.compress(expanded)
    assert len(payload) < 65536
    with sdk_response(payload, content_encoding="gzip") as response:
        stream = StreamingBody(response, len(payload))
        client = client_for(monkeypatch, stream, len(payload))
        actual = storage._read_sync("synthetic", len(payload), available_chunks=True)
        assert actual == payload
        assert actual != expanded
        assert len(actual) < 65536
        assert response.closed and client.closed
    assert_slot_free()
