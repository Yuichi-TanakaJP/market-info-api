"""One supervised subprocess per API process; cancellation cannot release it early."""

from __future__ import annotations
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import subprocess
import sys
import threading
from app.yutai_comparison_wire import MAX_REPORT_BYTES, digest
from app.yutai_comparison_worker import SavedReadError

DEADLINE_SECONDS = 30
_SLOT = threading.BoundedSemaphore(1)
_EXECUTOR = ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="comparison-supervisor"
)


def _command(mode, sha):
    return [sys.executable, "-m", "app.yutai_comparison_worker", mode, sha]


def _supervise(mode, sha):
    try:
        # subprocess.run uses communicate: timeout kills, drains pipes and reaps.
        result = subprocess.run(
            _command(mode, sha),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=str(Path(__file__).resolve().parent.parent),
            timeout=DEADLINE_SECONDS,
        )
        output = result.stdout
        if result.returncode != 0 or len(output) > MAX_REPORT_BYTES + 100:
            raise SavedReadError(503)
        header, sep, body = output.partition(b"\n")
        if header in {b"400", b"404", b"503"}:
            raise SavedReadError(int(header))
        if not sep or not header.startswith(b"200 "):
            raise SavedReadError(503)
        response_sha = header[4:].decode("ascii")
        if (
            not re.fullmatch(r"[0-9a-f]{64}", response_sha)
            or digest(body) != response_sha
        ):
            raise SavedReadError(503)
        if mode == "receipt" and response_sha != sha:
            raise SavedReadError(503)
        return body, response_sha
    except (subprocess.SubprocessError, OSError, ValueError) as exc:
        raise SavedReadError(503) from exc
    finally:
        _SLOT.release()


async def read_saved(mode, sha):
    if mode not in {"receipt", "report"} or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise SavedReadError(400)
    if not _SLOT.acquire(blocking=False):
        raise SavedReadError(503)
    try:
        future = asyncio.get_running_loop().run_in_executor(
            _EXECUTOR, _supervise, mode, sha
        )
    except BaseException:
        _SLOT.release()
        raise
    # The supervisor owns subprocess/pipe/admission until exit, even when the
    # request is repeatedly cancelled. It has its own bounded executor, no queue.
    future.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
    return await asyncio.shield(future)
