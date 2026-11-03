"""Owner-scoped bounded history extraction; codes are filters, never authorization."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import re
from datetime import date
from typing import Annotated, Literal

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, Query, Response, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import Field

from app import config, credit_history_storage
from app.credit_history_wire import (
    PREFIX,
    MAX_ARTIFACT_BYTES,
    MAX_MANIFEST_BYTES,
    DailyArtifact,
    Manifest,
    NikkoRecord,
    SbiRecord,
    WireModel,
    canonical,
    digest,
)

router = APIRouter(
    prefix="/private/credit-inventory", tags=["private-credit-inventory"]
)
_bearer = HTTPBearer(auto_error=False)
_gate = asyncio.Semaphore(1)
MAX_RESPONSE_BYTES = 256 * 1024
MAX_ROWS = 100


def error(status, message):
    return HTTPException(
        status_code=status,
        detail=message,
        headers={"Cache-Control": "private, no-store"},
    )


async def require_key(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(_bearer)],
):
    expected = config.CREDIT_HISTORY_API_KEY
    if not expected:
        raise error(503, "private credit-history authentication is not configured")
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not hmac.compare_digest(credentials.credentials.encode(), expected.encode())
    ):
        exc = error(401, "invalid or missing bearer token")
        exc.headers["WWW-Authenticate"] = "Bearer"
        raise exc


class Observation(WireModel):
    code: str
    observed_date: str
    observed_at: str
    source_sha256: str
    source_snapshot_id: str
    collection_completeness: Literal["not_attested"]
    record: NikkoRecord | SbiRecord | None


class HistoryPage(WireModel):
    schema: Literal["credit-inventory-history-page-v1"]
    generation: str
    broker: Literal["smbc_nikko", "sbi"]
    codes: list[str]
    start: str
    end: str
    page_month: str | None
    observations: list[Observation] = Field(max_length=MAX_ROWS)
    # Months with no shared source object are explicit, never assumed zero.
    missing_months: list[str]
    complete: bool
    next_cursor: str | None
    live_executability_confirmed: Literal[False] = False


def _token(value):
    body = base64.urlsafe_b64encode(canonical(value)).decode().rstrip("=")
    signature = hmac.new(
        config.CREDIT_HISTORY_API_KEY.encode(),
        ("credit-history-v1:" + body).encode(),
        hashlib.sha256,
    ).hexdigest()
    return body + "." + signature


def _decode(token):
    try:
        body, signature = token.split(".")
        expected = hmac.new(
            config.CREDIT_HISTORY_API_KEY.encode(),
            ("credit-history-v1:" + body).encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError()
        value = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if (
            set(value) != {"generation", "query", "month", "offset"}
            or not re.fullmatch(r"[0-9a-f]{64}", value["generation"])
            or type(value["month"]) is not int
            or type(value["offset"]) is not int
            or value["month"] < 0
            or value["offset"] < 0
        ):
            raise ValueError()
        return value
    except Exception as exc:
        raise error(400, "invalid history cursor") from exc


def _months(start, end):
    y, m = start.year, start.month
    result = []
    while (y, m) <= (end.year, end.month):
        result.append(f"{y:04}-{m:02}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return result


async def _page(broker, codes, start, end, cursor):
    requested = codes.split(",")
    if (
        not 1 <= len(requested) <= 20
        or len(set(requested)) != len(requested)
        or any(not re.fullmatch(r"[0-9A-Z]{4,5}", c) for c in requested)
    ):
        raise error(422, "codes must contain 1 to 20 unique JPX codes")
    requested.sort()
    if start > end or (end - start).days > 366:
        raise error(
            422, "observation range must be ordered and at most 367 days inclusive"
        )
    query = digest(canonical([broker, requested, start.isoformat(), end.isoformat()]))
    position = _decode(cursor) if cursor else None
    if position and position["query"] != query:
        raise error(400, "cursor does not match request")
    generation = position["generation"] if position else None
    manifest_key = (
        f"{PREFIX}/generations/{generation}.json"
        if generation
        else f"{PREFIX}/manifest.json"
    )
    raw = await credit_history_storage.read_bytes(manifest_key, MAX_MANIFEST_BYTES)
    if generation and digest(raw) != generation:
        raise ValueError("generation digest mismatch")
    manifest = Manifest.model_validate_json(raw)
    generation = digest(raw)
    # The first request also verifies that its fixed generation exists.
    if not position:
        pinned = await credit_history_storage.read_bytes(
            f"{PREFIX}/generations/{generation}.json", MAX_MANIFEST_BYTES
        )
        if pinned != raw:
            raise ValueError("generation unavailable")
    months = _months(start, end)
    entries = {
        e.month: e for e in manifest.entries if e.broker == broker and e.month in months
    }
    missing = [m for m in months if m not in entries]
    available = [entries[m] for m in months if m in entries]
    month_index, offset = (
        (position["month"], position["offset"]) if position else (0, 0)
    )
    if month_index >= len(available) and (position or available):
        raise error(400, "cursor position out of range")
    result = dict(
        schema="credit-inventory-history-page-v1",
        generation=generation,
        broker=broker,
        codes=requested,
        start=start.isoformat(),
        end=end.isoformat(),
        page_month=None,
        observations=[],
        missing_months=missing,
        complete=True,
        next_cursor=None,
        live_executability_confirmed=False,
    )
    if not available:
        return result
    entry = available[month_index]
    body = await credit_history_storage.read_bytes(entry.key, MAX_ARTIFACT_BYTES)
    if len(body) != entry.bytes or digest(body) != entry.sha256:
        raise ValueError("artifact integrity mismatch")
    artifact = DailyArtifact.model_validate_json(body)
    if (
        artifact.broker != broker
        or artifact.month != entry.month
        or artifact.observed_dates != entry.observed_dates
    ):
        raise ValueError("artifact identity mismatch")
    result["page_month"] = entry.month
    slots = [
        (s, c)
        for s in artifact.snapshots
        if start.isoformat() <= s.observed_date <= end.isoformat()
        for c in requested
    ]
    if offset > len(slots):
        raise error(400, "cursor offset out of range")
    next_offset = offset
    for snapshot, code in slots[offset:]:
        row = snapshot.model_dump(exclude={"by_code", "record_count"})
        record = snapshot.by_code.get(code)
        row.update(code=code, record=None if record is None else record.model_dump())
        # Reserve enough room for the longest cursor and response metadata.
        candidate = result["observations"] + [row]
        if (
            len(candidate) > MAX_ROWS
            or len(canonical({**result, "observations": candidate}))
            > MAX_RESPONSE_BYTES - 2048
        ):
            if not result["observations"]:
                raise ValueError("single observation exceeds response size limit")
            break
        result["observations"].append(row)
        next_offset += 1
    if next_offset < len(slots):
        next_position = dict(
            generation=generation, query=query, month=month_index, offset=next_offset
        )
    elif month_index + 1 < len(available):
        next_position = dict(
            generation=generation, query=query, month=month_index + 1, offset=0
        )
    else:
        next_position = None
    result["complete"] = next_position is None
    result["next_cursor"] = _token(next_position) if next_position else None
    if len(canonical(result)) > MAX_RESPONSE_BYTES:
        raise ValueError("response exceeds size limit")
    return result


@router.get(
    "/history",
    response_model=HistoryPage,
    dependencies=[Depends(require_key)],
    summary="Extract explicitly requested private daily inventory observations",
)
async def history(
    response: Response,
    broker: Literal["smbc_nikko", "sbi"],
    codes: Annotated[str, Query(max_length=119)],
    start: date,
    end: date,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
):
    """One monthly object per page, maximum 20 codes, 100 rows and 256 KiB.

    Follow next_cursor until complete; complete describes pagination, never source
    collection completeness. Unobserved dates are absent and missing codes have
    record=null. All times retain their original JST source evidence.
    """
    response.headers["Cache-Control"] = "private, no-store"
    try:
        async with _gate:
            return await _page(broker, codes, start, end, cursor)
    except HTTPException:
        raise
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "NoSuchKey":
            raise error(
                409 if cursor else 503,
                "requested history generation/source is unavailable",
            ) from exc
        raise error(502, "private credit history unavailable") from exc
    except RuntimeError as exc:
        raise error(503, "private credit history storage is not configured") from exc
    except Exception as exc:
        raise error(502, "invalid or unavailable private credit history") from exc
