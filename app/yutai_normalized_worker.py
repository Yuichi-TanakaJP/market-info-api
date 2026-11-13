"""Bounded isolated source-only read; no writes or canonical acceptance."""

from __future__ import annotations
import re
import sys
from botocore.exceptions import ClientError
from app import yutai_normalized_storage as storage
from app.yutai_normalized_wire import (
    PREFIX,
    MAX_RELEASE_BYTES,
    MAX_RECORD_BYTES,
    NormalizedRead,
    canonical,
    digest,
    validate_release,
)


class SavedReadError(Exception):
    def __init__(self, status):
        self.status = status


def read_validated(selection, sha):
    if not re.fullmatch(
        r"20[0-9]{2}-(0[1-9]|1[0-2])/[0-9A-Z]{4}", selection
    ) or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise SavedReadError(400)
    try:
        body = storage._read_sync(f"{PREFIX}/{sha}.json", MAX_RELEASE_BYTES)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "NoSuchKey":
            raise SavedReadError(404) from exc
        raise
    release = validate_release(body, sha)
    month, code = selection.split("/")
    matches = [
        e for e in release.records if e.month == month and e.record["code"] == code
    ]
    if not matches:
        raise SavedReadError(404)
    record = matches[0].record
    response = NormalizedRead(
        release_sha256=sha,
        month=month,
        code=code,
        record_sha256=digest(canonical(record)),
        record=record,
    )
    result = canonical(response.model_dump())
    if len(result) > MAX_RECORD_BYTES:
        raise ValueError("response exceeds delivery bound")
    return result, digest(result)


def main():
    try:
        body, sha = read_validated(*sys.argv[1:])
        sys.stdout.buffer.write(("200 " + sha + "\n").encode() + body)
    except SavedReadError as exc:
        sys.stdout.buffer.write((str(exc.status) + "\n").encode())
    except Exception:
        sys.stdout.buffer.write(b"503\n")


if __name__ == "__main__":
    main()
