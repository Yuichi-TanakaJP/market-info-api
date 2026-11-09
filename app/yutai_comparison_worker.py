"""Single-request private read/validation subprocess; no writes or logging."""

from __future__ import annotations
import re
import sys
from botocore.exceptions import ClientError
from app import yutai_comparison_storage as storage
from app.yutai_comparison_wire import (
    PREFIX,
    MAX_RECEIPT_BYTES,
    MAX_REPORT_BYTES,
    validate_receipt,
    validate_report,
)


class SavedReadError(Exception):
    def __init__(self, status):
        self.status = status


def read_validated(mode, sha):
    if mode not in {"receipt", "report"} or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise SavedReadError(400)
    try:
        body = storage._read_sync(f"{PREFIX}/receipts/{sha}.json", MAX_RECEIPT_BYTES)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "NoSuchKey":
            raise SavedReadError(404) from exc
        raise
    receipt = validate_receipt(body, sha)
    if mode == "receipt":
        return body, sha
    body = storage._read_sync(receipt.report_key, MAX_REPORT_BYTES)
    validate_report(body, receipt)
    return body, receipt.report_sha256


def main():
    try:
        body, sha = read_validated(*sys.argv[1:])
        # Only a fixed small header and bounded validated bytes reach the parent.
        sys.stdout.buffer.write(("200 " + sha + "\n").encode() + body)
    except SavedReadError as exc:
        sys.stdout.buffer.write((str(exc.status) + "\n").encode())
    except Exception:
        sys.stdout.buffer.write(b"503\n")


if __name__ == "__main__":
    main()
