"""Read-only immutable TDNET corrections, guarded by a fresh repair fence.

This module never publishes, changes a revision mapping, or falls back on a
failed correction. An absent index alone preserves the legacy read contract.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone

from cachetools import LRUCache
from fastapi import HTTPException

from app import cache, r2

INDEX_KEY = "tdnet/corrections/v1/index.json"
PREFIX = "tdnet/corrections/v1"
INDEX_LIMIT = 64 * 1024
RELEASE_LIMIT = 16 * 1024
DOCUMENT_LIMIT = 16 * 1024 * 1024
FAMILIES = {"tdnet", "events", "router", "intent"}
_VERIFIED_BODY_LIMIT = 32 * 1024 * 1024
_verified_bodies = LRUCache(maxsize=_VERIFIED_BODY_LIMIT, getsizeof=len)
_SHA = re.compile(r"[0-9a-f]{64}")
_NOV12 = "2026-11-12"
_PAGINATION_GAP_DAYS = {_NOV12, "2026-11-13"}
_NOV12_REQUIRED_PDFS = {
    ("39790", "140120261111574498.pdf"),
    ("44840", "140120261111573095.pdf"),
    ("63300", "140120261110571395.pdf"),
    ("75670", "140120261111574580.pdf"),
    ("75670", "140120261111574574.pdf"),
}


def unavailable():
    return HTTPException(
        503,
        "tdnet correction unavailable or repair in progress",
        headers={"Cache-Control": "no-store"},
    )


def _keys(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError("invalid correction shape")


def _sha(value):
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise ValueError("invalid correction digest")
    return value


def _date(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError("invalid correction date")
    return value


def _parse(body):
    def pairs(items):
        obj = {}
        for key, value in items:
            if key in obj:
                raise ValueError("duplicate correction key")
            obj[key] = value
        return obj

    def constant(_):
        raise ValueError("invalid correction number")

    obj = json.loads(
        body.decode("utf-8"),
        object_pairs_hook=pairs,
        parse_constant=constant,
        parse_float=r2._finite_float,
    )
    if type(obj) is not dict:
        raise ValueError("invalid correction object")
    r2._validate_unicode(obj)
    return obj


async def _body(key, limit, *, missing=False):
    # Always bypass intermediary freshness for the index. Immutable objects use
    # this same transport so a partial/redirect response cannot become a release.
    async with r2.get_client().stream(
        "GET", f"{r2.R2_PUBLIC_BASE_URL}/{key}", headers={"Cache-Control": "no-cache"}
    ) as response:
        if response.status_code == 404 and missing:
            return None
        if response.status_code != 200:
            raise ValueError("correction HTTP status")
        chunks = []
        length = 0
        async for chunk in response.aiter_bytes():
            length += len(chunk)
            if length > limit:
                raise ValueError("correction body bound")
            chunks.append(chunk)
        if length == 0:
            raise ValueError("empty correction body")
        return b"".join(chunks)


async def load_index():
    try:
        body = await _body(INDEX_KEY, INDEX_LIMIT, missing=True)
        if body is None:
            return {
                "schema_version": "tdnet-correction-index-v1",
                "revisions": {},
                "pending": None,
            }
        value = _parse(body)
        _keys(value, {"schema_version", "revisions", "pending"})
        if value["schema_version"] != "tdnet-correction-index-v1":
            raise ValueError("index version")
        if type(value["revisions"]) is not dict or len(value["revisions"]) > 500:
            raise ValueError("index revisions")
        for day, digest in value["revisions"].items():
            _date(day)
            _sha(digest)
        if value["pending"] is not None:
            _keys(value["pending"], {"date", "plan_sha256"})
            _date(value["pending"]["date"])
            _sha(value["pending"]["plan_sha256"])
        return value
    except Exception:
        raise unavailable() from None


async def guard_index(day=None):
    value = await load_index()
    pending = value["pending"]
    if pending is not None and (day is None or pending["date"] == day):
        raise unavailable()
    return value


async def confirm_index(before, day=None):
    after = await guard_index(day)
    if (
        after != before
        if day is None
        else after["revisions"].get(day) != before["revisions"].get(day)
    ):
        raise unavailable()


async def _immutable(key, digest, limit=DOCUMENT_LIMIT):
    body = _verified_bodies.get(digest)
    if body is None:
        body = await _body(key, limit)
        if hashlib.sha256(body).hexdigest() != digest:
            raise ValueError("correction digest mismatch")
        # Cache only verified immutable bytes; fresh parses cannot mutate cache.
        if len(body) <= _VERIFIED_BODY_LIMIT:
            _verified_bodies[digest] = body
    if len(body) > limit:
        raise ValueError("correction body bound")
    return _parse(body)


def _validate_document(family, obj, day):
    if obj.get("target_date") != day:
        raise ValueError("document date mismatch")
    if family == "intent":
        _keys(
            obj, {"schema_version", "artifact_type", "target_date", "semantic_digests"}
        )
        if (
            type(obj["schema_version"]) is not int
            or obj["schema_version"] != 1
            or obj["artifact_type"] != "tdnet_cloud_bundle_intent"
        ):
            raise ValueError("intent schema mismatch")
        _keys(obj["semantic_digests"], {"tdnet", "events", "router"})
        for digest in obj["semantic_digests"].values():
            _sha(digest)
        return
    from app.routers.disclosure_events import DisclosureEventsPayload
    from app.routers.tdnet import TdnetDisclosures
    from app.routers.tdnet_router_events import TdnetRouterEventsPayload

    model = {
        "tdnet": TdnetDisclosures,
        "events": DisclosureEventsPayload,
        "router": TdnetRouterEventsPayload,
    }[family]
    model.model_validate(obj, strict=True)
    if type(obj.get("total_count")) is not int or obj["total_count"] != len(
        obj["items"]
    ):
        raise ValueError("document count mismatch")
    if any(item.get("disclosure_date") != day for item in obj["items"]):
        raise ValueError("document item date mismatch")


async def _release(revision, day):
    release = await _immutable(
        f"{PREFIX}/releases/{revision}.json", revision, RELEASE_LIMIT
    )
    _keys(
        release,
        {
            "schema_version",
            "target_date",
            "reason",
            "supersedes",
            "documents",
            "source",
        },
    )
    if (
        release["schema_version"] != "tdnet-correction-release-v1"
        or release["target_date"] != day
        or (
            release["reason"] != "premature_empty_day"
            and (
                release["reason"] != "historical_pagination_gap"
                or day not in _PAGINATION_GAP_DAYS
            )
        )
        or (day == _NOV12 and release["reason"] != "historical_pagination_gap")
    ):
        raise ValueError("release binding mismatch")
    for key in ("supersedes", "documents"):
        _keys(release[key], FAMILIES)
        for digest in release[key].values():
            _sha(digest)
    source = release["source"]
    _keys(source, {"page_sha256", "page_count", "disclosure_count", "fetched_at"})
    if (
        type(source["page_sha256"]) is not list
        or type(source["page_count"]) is not int
        or not 1 <= source["page_count"] <= 100
        or len(source["page_sha256"]) != source["page_count"]
        or type(source["disclosure_count"]) is not int
        or source["disclosure_count"] <= 0
    ):
        raise ValueError("release evidence invalid")
    if day == _NOV12 and (
        source["page_count"] != 12 or source["disclosure_count"] != 1180
    ):
        raise ValueError("November 12 pagination evidence mismatch")
    if not isinstance(source["fetched_at"], str):
        raise ValueError("collection timestamp invalid")
    fetched = datetime.fromisoformat(source["fetched_at"].replace("Z", "+00:00"))
    if (
        fetched.tzinfo is None
        or fetched.utcoffset() != timezone.utc.utcoffset(fetched)
        or fetched.astimezone(timezone(timedelta(hours=9))).date()
        <= date.fromisoformat(day)
    ):
        raise ValueError("release collection is not after closed day")
    for digest in source["page_sha256"]:
        _sha(digest)
    documents = {}
    for family, digest in release["documents"].items():
        document = await _immutable(f"{PREFIX}/documents/{digest}.json", digest)
        _validate_document(family, document, day)
        documents[family] = document
    if documents["tdnet"]["total_count"] != source["disclosure_count"]:
        raise ValueError("release disclosure count mismatch")
    if day == _NOV12 and not _NOV12_REQUIRED_PDFS <= {
        (item["security_code"], item["pdf_url"].rsplit("/", 1)[-1])
        for item in documents["tdnet"]["items"]
        if item["has_pdf"]
    }:
        raise ValueError("November 12 required disclosures missing")
    if documents["intent"]["semantic_digests"] != {
        family: semantic_digest(family, documents[family])
        for family in ("tdnet", "events", "router")
    }:
        raise ValueError("release intent mismatch")
    return documents


async def corrected_day(family, day, revision, response, api_path, *, before=None):
    """Return corrected body or None for a legacy day; guard even warm day caches."""
    before = before if before is not None else await guard_index(day)
    selected = before["revisions"].get(day)
    if revision is not None:
        try:
            _sha(revision)
        except ValueError:
            raise HTTPException(
                422,
                "revision must be a lowercase SHA256",
                headers={"Cache-Control": "no-store"},
            ) from None
        if revision != selected:
            raise HTTPException(
                404,
                "tdnet revision not active for this date",
                headers={"Cache-Control": "no-store"},
            )
    if selected is None:
        return None
    try:
        docs = await _release(selected, day)
        await confirm_index(before, day)
    except Exception:
        raise unavailable() from None
    response.headers["Cache-Control"] = (
        cache.IMMUTABLE_HTTP_CACHE_CONTROL if revision is not None else "no-store"
    )
    response.headers["ETag"] = f'"{selected}"'
    response.headers["Content-Location"] = f"{api_path}?revision={selected}"
    return docs[family]


async def day(family, target_date, revision, response, api_path, legacy_key, fetch_fn):
    before = await guard_index(target_date)
    corrected = await corrected_day(
        family, target_date, revision, response, api_path, before=before
    )
    if corrected is not None:
        return corrected
    result = await cache.get_day(legacy_key, fetch_fn)
    await confirm_index(before, target_date)
    return result


# Wire-compatible with market_info cloud_production_publish semantic digests.
_STABLE_FIELDS = (
    "disclosure_date",
    "disclosure_time",
    "security_code",
    "company_name",
    "title",
    "disclosure_category",
    "pdf_url",
    "xbrl_url",
    "html_url",
    "has_pdf",
    "has_xbrl",
    "has_html",
    "is_financial_related",
    "is_earnings_release",
    "is_correction",
)


def semantic_digest(family, payload):
    if family == "tdnet":
        rows = [
            {field: item.get(field) for field in _STABLE_FIELDS}
            for item in payload["items"]
        ]
        rows.sort(
            key=lambda row: tuple(
                str(row[field]) if row[field] is not None else ""
                for field in _STABLE_FIELDS
            )
        )
        value = {
            key: payload.get(key) for key in ("target_date", "source", "total_count")
        }
        value["items"] = rows
    elif family == "events":
        value = {
            key: payload.get(key)
            for key in ("schema_version", "target_date", "total_count", "items")
        }
    else:
        value = payload
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
