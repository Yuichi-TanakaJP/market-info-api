from __future__ import annotations
import io
import json
import os
from pathlib import Path

os.environ.setdefault("R2_PUBLIC_BASE_URL", "https://example.invalid")
import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
from app import config, yutai_comparison_storage as storage
from app.main import app
from app.yutai_comparison_wire import PREFIX, digest, validate_report, validate_receipt

from app.yutai_comparison_service import read_saved as production_read_saved

AUTH = {"Authorization": "Bearer synthetic-comparison-key"}
BASE = "/private/yutai/comparisons/receipts/"


def canonical(v):
    return json.dumps(v, sort_keys=True, separators=(",", ":")).encode()


@pytest.fixture
def saved(monkeypatch):
    report = (
        Path(__file__)
        .with_name("fixtures")
        .joinpath("yutai_comparison_real_shape_synthetic.json")
        .read_bytes()
    )
    parsed = json.loads(report)
    sha = digest(report)
    receipt = dict(
        schema_version="yutai-comparison-history-receipt-v1",
        mode="pending_comparison_history",
        report_key=f"{PREFIX}/objects/{sha}.json",
        report_sha256=sha,
        report_bytes=len(report),
        raw_retention="not_uploaded_local_assets_required",
        assessment_updated=False,
    )
    receipt.update(
        {
            k: parsed[k]
            for k in [
                "jpx_sha256",
                "generated_at",
                "universe_count",
                "record_count",
                "unobserved_count",
                "coverage",
            ]
        }
    )
    body = canonical(receipt)
    rsha = digest(body)
    objects = {f"{PREFIX}/receipts/{rsha}.json": body, receipt["report_key"]: report}
    calls = []

    def read(key, limit):
        calls.append(key)
        if key not in objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return objects[key]

    monkeypatch.setattr(config, "YUTAI_COMPARISON_API_KEY", "synthetic-comparison-key")
    monkeypatch.setattr(storage, "_read_sync", read)
    from app import yutai_comparison_service as service
    from app.yutai_comparison_worker import read_validated

    async def local_service(mode, sha):
        return read_validated(mode, sha)

    monkeypatch.setattr(service, "read_saved", local_service)
    return dict(
        report=report,
        receipt=body,
        sha=rsha,
        objects=objects,
        calls=calls,
        report_key=receipt["report_key"],
    )


def test_receipt_and_report_exact_bytes_no_store(saved):
    with TestClient(app) as client:
        for suffix, expected in [("", saved["receipt"]), ("/report", saved["report"])]:
            r = client.get(BASE + saved["sha"] + suffix, headers=AUTH)
            assert r.status_code == 200 and r.content == expected
            assert r.headers["cache-control"] == "private, no-store"
            assert r.headers["x-content-sha256"] == digest(expected)
            assert len(saved["calls"]) <= 3
    parsed = json.loads(saved["report"])
    assert parsed["coverage"] == "partial"
    assert all(r["review_status"] == "pending" for r in parsed["records"])


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}])
@pytest.mark.parametrize("suffix", ["", "/report"])
def test_unauthorized_no_storage(saved, headers, suffix):
    with TestClient(app) as client:
        r = client.get(BASE + saved["sha"] + suffix, headers=headers)
    assert r.status_code == 401 and not saved["calls"]
    assert r.headers["cache-control"] == "private, no-store"


def test_unconfigured_auth_fails_closed(saved, monkeypatch):
    monkeypatch.setattr(config, "YUTAI_COMPARISON_API_KEY", "")
    with TestClient(app) as client:
        r = client.get(BASE + saved["sha"], headers=AUTH)
    assert r.status_code == 503 and not saved["calls"]


def test_bad_identity_missing_receipt_and_no_public_fallback(saved):
    with TestClient(app) as client:
        assert client.get(BASE + "BAD", headers=AUTH).status_code == 400
        assert not saved["calls"]
        r = client.get(BASE + "f" * 64, headers=AUTH)
        assert r.status_code == 404
        assert saved["calls"] == [f"{PREFIX}/receipts/{'f' * 64}.json"]


def test_missing_referenced_report_is503(saved):
    del saved["objects"][saved["report_key"]]
    with TestClient(app) as client:
        r = client.get(BASE + saved["sha"] + "/report", headers=AUTH)
    assert r.status_code == 503


def test_corrupt_report_and_receipt_fail_closed(saved):
    with TestClient(app) as client:
        saved["objects"][saved["report_key"]] += b"x"
        assert (
            client.get(BASE + saved["sha"] + "/report", headers=AUTH).status_code == 503
        )
        saved["objects"][f"{PREFIX}/receipts/{saved['sha']}.json"] += b"x"
        assert client.get(BASE + saved["sha"], headers=AUTH).status_code == 503


@pytest.mark.parametrize(
    "change",
    [
        dict(report_key="other/private/path"),
        dict(unobserved_count=0),
        dict(assessment_updated=True),
        dict(raw_retention="retained_private"),
    ],
)
def test_signed_shape_invalid_receipt_rejected(saved, change):
    value = json.loads(saved["receipt"]) | change
    body = canonical(value)
    sha = digest(body)
    saved["objects"][f"{PREFIX}/receipts/{sha}.json"] = body
    with TestClient(app) as client:
        r = client.get(BASE + sha + "/report", headers=AUTH)
    assert r.status_code == 503
    assert len(saved["calls"]) == 1


def test_report_summary_mismatch_is_rejected(saved):
    receipt = validate_receipt(saved["receipt"], saved["sha"])
    with pytest.raises(ValueError):
        validate_report(
            saved["report"], receipt.model_copy(update={"jpx_sha256": "f" * 64})
        )


def test_duplicate_json_and_nonfinite_not_accepted(saved):
    from app.yutai_comparison_wire import parse_object

    for raw in [b'{"a":1,"a":2}', b'{"a":NaN}']:
        with pytest.raises(ValueError):
            parse_object(raw, 4096)


def test_provider_denial_is503(saved, monkeypatch):
    def denied(*a):
        raise ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject")

    monkeypatch.setattr(storage, "_read_sync", denied)
    with TestClient(app) as client:
        r = client.get(BASE + saved["sha"], headers=AUTH)
    assert r.status_code == 503


def test_private_read_failure_does_not_echo_details(saved, monkeypatch):
    def fail(*a):
        raise ValueError("synthetic confidential detail")

    monkeypatch.setattr(storage, "_read_sync", fail)
    with TestClient(app) as client:
        r = client.get(BASE + saved["sha"], headers=AUTH)
    assert r.status_code == 503 and "confidential" not in r.text


def test_openapi_describes_exact_wire_models():
    schema = app.openapi()
    path = schema["paths"][BASE + "{receipt_sha256}/report"]["get"]
    assert "security" in path
    assert "ComparisonReport" in str(path["responses"]["200"])


def test_bounded_reader_closes_stream_and_client_on_short_or_long(monkeypatch):
    for name in ["BUCKET", "ENDPOINT", "ACCESS_KEY_ID", "SECRET_ACCESS_KEY"]:
        monkeypatch.setattr(
            config,
            "YUTAI_COMPARISON_PRIVATE_" + name,
            "https://example.invalid" if name == "ENDPOINT" else "synthetic",
        )
    import boto3

    class Client:
        closed = False

        def get_object(self, **kw):
            return {"Body": stream, "ContentLength": 3}

        def close(self):
            self.closed = True

    for raw, ok in [(b"abc", True), (b"ab", False), (b"abcd", False)]:
        stream = io.BytesIO(raw)
        client = Client()
        monkeypatch.setattr(boto3, "client", lambda *a, **kw: client)
        if ok:
            assert storage._read_sync("synthetic", 10) == b"abc"
        else:
            with pytest.raises(ValueError):
                storage._read_sync("synthetic", 10)
        assert stream.closed and client.closed


def test_cancelled_request_does_not_release_worker_slot_early():
    assert storage._READ_SLOT.acquire(blocking=False)
    try:
        with pytest.raises(RuntimeError, match="busy"):
            storage._read_sync("synthetic", 1)
    finally:
        storage._READ_SLOT.release()


@pytest.mark.asyncio
async def test_request_cancellation_keeps_slot_until_worker_finishes(monkeypatch):
    import asyncio
    import threading

    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = storage._read_sync

    def claimed(key, limit):
        started.set()
        assert release.wait(3)
        return b"ok"

    def traced(key, limit):
        try:
            return original(key, limit)
        finally:
            finished.set()

    monkeypatch.setattr(storage, "_read_claimed", claimed)
    monkeypatch.setattr(storage, "_read_sync", traced)
    task = asyncio.create_task(storage.read_bytes("synthetic", 10))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(RuntimeError, match="busy"):
            original("synthetic", 10)
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 1)
    assert storage._READ_SLOT.acquire(blocking=False)
    storage._READ_SLOT.release()


@pytest.mark.parametrize("omit", ["schema_version", "mode"])
def test_report_requires_explicit_version_and_mode(saved, omit):
    value = json.loads(saved["report"])
    del value[omit]
    body = canonical(value)
    receipt = json.loads(saved["receipt"])
    receipt.update(
        report_sha256=digest(body),
        report_key=f"{PREFIX}/objects/{digest(body)}.json",
        report_bytes=len(body),
    )
    sha = digest(canonical(receipt))
    with pytest.raises(ValueError):
        validate_report(body, validate_receipt(canonical(receipt), sha))


@pytest.mark.parametrize("omit", ["review_status", "assessment_updated"])
def test_report_requires_explicit_pending_markers(saved, omit):
    value = json.loads(saved["report"])
    del value["records"][0][omit]
    body = canonical(value)
    receipt = json.loads(saved["receipt"])
    receipt.update(
        report_sha256=digest(body),
        report_key=f"{PREFIX}/objects/{digest(body)}.json",
        report_bytes=len(body),
    )
    with pytest.raises(ValueError):
        validate_report(
            body, validate_receipt(canonical(receipt), digest(canonical(receipt)))
        )


@pytest.mark.parametrize("encoding", ["utf-16", "utf-32"])
def test_wire_alternate_encoding_rejected(saved, encoding):
    body = saved["receipt"].decode().encode(encoding)
    with pytest.raises((ValueError, UnicodeError)):
        validate_receipt(body, digest(body))


def test_compact_malformed_structure_rejected_before_pydantic():
    from app.yutai_comparison_wire import parse_object, MAX_REPORT_BYTES

    body = b'{"records":[' + b"{}," * 50000 + b"{}]}"
    with pytest.raises(ValueError, match="structure"):
        parse_object(body, MAX_REPORT_BYTES)


def test_http_storage_endpoint_rejected_before_client_creation(monkeypatch):
    import boto3

    for name in ["BUCKET", "ACCESS_KEY_ID", "SECRET_ACCESS_KEY"]:
        monkeypatch.setattr(config, "YUTAI_COMPARISON_PRIVATE_" + name, "synthetic")
    monkeypatch.setattr(
        config, "YUTAI_COMPARISON_PRIVATE_ENDPOINT", "http://example.invalid"
    )
    monkeypatch.setattr(
        boto3, "client", lambda *a, **kw: pytest.fail("Must not build insecure client")
    )
    with pytest.raises(ValueError, match="HTTPS"):
        storage._read_sync("synthetic", 10)


def test_near_limit_valid_report_is_supported(saved):
    from app.yutai_comparison_wire import MAX_REPORT_BYTES

    row = dict(
        code="1000",
        status="not_checked",
        old=None,
        new=None,
        scope="none",
        extractor_version=None,
        old_text_sha256=None,
        new_text_sha256=None,
        reason="x" * 1900,
        review_status="pending",
        assessment_updated=False,
        byte_equal=None,
    )
    report = json.loads(saved["report"])
    report["records"] = [row | {"code": str(1000 + i)} for i in range(1750)]
    report.update(record_count=1750, unobserved_count=report["universe_count"] - 1750)
    body = canonical(report)
    assert MAX_REPORT_BYTES * 0.8 < len(body) < MAX_REPORT_BYTES
    receipt = json.loads(saved["receipt"])
    receipt.update(
        report_sha256=digest(body),
        report_key=f"{PREFIX}/objects/{digest(body)}.json",
        report_bytes=len(body),
        record_count=1750,
        unobserved_count=report["unobserved_count"],
    )
    model = validate_receipt(canonical(receipt), digest(canonical(receipt)))
    assert len(validate_report(body, model).records) == 1750


@pytest.mark.asyncio
async def test_supervisor_deadline_drains_full_pipe_and_recovers(monkeypatch):
    import asyncio
    import sys
    from app import yutai_comparison_service as service
    from app.yutai_comparison_worker import SavedReadError

    monkeypatch.setattr(service, "DEADLINE_SECONDS", 0.3)
    monkeypatch.setattr(
        service,
        "_command",
        lambda *a: [
            sys.executable,
            "-c",
            "import sys,time;sys.stdout.buffer.write(b'x'*1000000);sys.stdout.buffer.flush();time.sleep(30)",
        ],
    )
    task = asyncio.create_task(service.read_saved("report", "a" * 64))
    await asyncio.sleep(0.01)
    assert (
        await asyncio.wait_for(asyncio.sleep(0, result="responsive"), 0.1)
        == "responsive"
    )
    with pytest.raises(SavedReadError):
        await asyncio.wait_for(task, 3)
    assert service._SLOT.acquire(blocking=False)
    service._SLOT.release()
    body = b"synthetic"
    code = (
        "import sys;sys.stdout.buffer.write("
        + repr(("200 " + digest(body) + "\n").encode() + body)
        + ")"
    )
    monkeypatch.setattr(service, "_command", lambda *a: [sys.executable, "-c", code])
    monkeypatch.setattr(service, "DEADLINE_SECONDS", 5)
    assert await service.read_saved("report", "a" * 64) == (body, digest(body))


@pytest.mark.asyncio
async def test_request_cancel_during_spawn_keeps_supervisor_ownership(monkeypatch):
    import asyncio
    import sys
    import threading
    from app import yutai_comparison_service as service
    from app.yutai_comparison_worker import SavedReadError

    started, release = threading.Event(), threading.Event()
    run = service.subprocess.run

    def stalled(*a, **kw):
        started.set()
        assert release.wait(3)
        return run(*a, **kw)

    body = b"synthetic"
    code = (
        "import sys;sys.stdout.buffer.write("
        + repr(("200 " + digest(body) + "\n").encode() + body)
        + ")"
    )
    monkeypatch.setattr(service, "_command", lambda *a: [sys.executable, "-c", code])
    monkeypatch.setattr(service.subprocess, "run", stalled)
    task = asyncio.create_task(service.read_saved("report", "a" * 64))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        task.cancel()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(SavedReadError):
            await service.read_saved("report", "a" * 64)
    finally:
        release.set()
    for _ in range(200):
        if service._SLOT.acquire(blocking=False):
            service._SLOT.release()
            break
        await asyncio.sleep(0.01)
    else:
        pytest.fail("Supervisor did not reap/release")
    assert await service.read_saved("report", "a" * 64) == (body, digest(body))


def test_scalar_array_rejected_before_json_allocation(monkeypatch):
    from app import yutai_comparison_wire as wire

    monkeypatch.setattr(
        wire.json,
        "loads",
        lambda *a, **kw: pytest.fail("Must reject before graph allocation"),
    )
    body = b'{"records":[' + b"0," * 250000 + b"0]}"
    with pytest.raises(ValueError, match="value limit"):
        wire.parse_object(body, wire.MAX_REPORT_BYTES)


@pytest.mark.parametrize("where", ["receipt", "report", "source"])
def test_numeric_wire_timestamps_rejected_with_correct_hashes(saved, where):
    report = json.loads(saved["report"])
    receipt = json.loads(saved["receipt"])
    if where in {"report", "receipt"}:
        report["generated_at"] = receipt["generated_at"] = 1793664000
    else:
        row = next(r for r in report["records"] if r["new"])
        row["new"]["fetched_at"] = 1793664000
    body = canonical(report)
    receipt.update(
        report_sha256=digest(body),
        report_key=f"{PREFIX}/objects/{digest(body)}.json",
        report_bytes=len(body),
    )
    if where == "receipt":
        with pytest.raises(ValueError):
            validate_receipt(canonical(receipt), digest(canonical(receipt)))
    elif where == "report":
        # Keep receipt a date-time string representing the same instant.
        receipt["generated_at"] = "2026-11-03T00:00:00Z"
        with pytest.raises(ValueError):
            validate_report(
                body, validate_receipt(canonical(receipt), digest(canonical(receipt)))
            )
    else:
        with pytest.raises(ValueError):
            validate_report(
                body, validate_receipt(canonical(receipt), digest(canonical(receipt)))
            )


@pytest.mark.asyncio
async def test_near_limit_through_real_worker_and_sdk_loop(
    saved, tmp_path, monkeypatch
):
    import sys
    from app import yutai_comparison_service as service
    from app.yutai_comparison_wire import MAX_REPORT_BYTES

    report = json.loads(saved["report"])
    row = dict(
        code="1000",
        status="not_checked",
        old=None,
        new=None,
        scope="none",
        extractor_version=None,
        old_text_sha256=None,
        new_text_sha256=None,
        reason="x" * 1900,
        review_status="pending",
        assessment_updated=False,
        byte_equal=None,
    )
    report.update(
        records=[row | {"code": str(1000 + i)} for i in range(1750)],
        record_count=1750,
        unobserved_count=report["universe_count"] - 1750,
    )
    body = canonical(report)
    assert MAX_REPORT_BYTES * 0.8 < len(body) < MAX_REPORT_BYTES
    receipt = json.loads(saved["receipt"])
    receipt.update(
        report_sha256=digest(body),
        report_key=f"{PREFIX}/objects/{digest(body)}.json",
        report_bytes=len(body),
        record_count=1750,
        unobserved_count=report["unobserved_count"],
    )
    receipt_body = canonical(receipt)
    sha = digest(receipt_body)
    (tmp_path / "report.json").write_bytes(body)
    (tmp_path / "receipt.json").write_bytes(receipt_body)
    script = tmp_path / "synthetic_worker.py"
    script.write_text(
        """import io,sys
from pathlib import Path
import boto3
from app import config
from app import yutai_comparison_worker as worker
root=Path(__file__).parent
for name in ['BUCKET','ACCESS_KEY_ID','SECRET_ACCESS_KEY']:
    setattr(config,'YUTAI_COMPARISON_PRIVATE_'+name,'synthetic')
config.YUTAI_COMPARISON_PRIVATE_ENDPOINT='https://example.invalid'
class Client:
    def get_object(self,**kw):
        name='receipt.json' if '/receipts/' in kw['Key'] else 'report.json'
        body=(root/name).read_bytes()
        return {'Body':io.BytesIO(body),'ContentLength':len(body)}
    def close(self):pass
boto3.client=lambda *a,**kw:Client()
worker.main()
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        service, "_command", lambda mode, key: [sys.executable, str(script), mode, key]
    )
    monkeypatch.setattr(service, "DEADLINE_SECONDS", 10)
    actual, actual_sha = await production_read_saved("report", sha)
    assert actual == body and actual_sha == digest(body)


@pytest.mark.parametrize("where", ["receipt", "report", "source"])
def test_quoted_epochs_rejected_in_wire(saved, where):
    report = json.loads(saved["report"])
    receipt = json.loads(saved["receipt"])
    if where in {"receipt", "report"}:
        report["generated_at"] = receipt["generated_at"] = "1793664000"
    else:
        next(r for r in report["records"] if r["new"])["new"]["fetched_at"] = (
            "1793664000"
        )
    body = canonical(report)
    receipt.update(
        report_sha256=digest(body),
        report_key=f"{PREFIX}/objects/{digest(body)}.json",
        report_bytes=len(body),
    )
    if where == "receipt":
        with pytest.raises(ValueError):
            validate_receipt(canonical(receipt), digest(canonical(receipt)))
    else:
        if where == "report":
            receipt["generated_at"] = "2026-11-03T00:00:00Z"
        with pytest.raises(ValueError):
            validate_report(
                body, validate_receipt(canonical(receipt), digest(canonical(receipt)))
            )


@pytest.mark.parametrize(
    "method,suffix,status",
    [("post", "", 405), ("get", "/missing", 404), ("get", "/", 307)],
)
def test_framework_responses_are_private_no_store(saved, method, suffix, status):
    with TestClient(app) as client:
        r = client.request(method, BASE + saved["sha"] + suffix, follow_redirects=False)
    assert r.status_code == status and r.headers["cache-control"] == "private, no-store"
    assert not saved["calls"]


def test_bare_private_prefix_is_no_store(saved):
    with TestClient(app) as client:
        r = client.get("/private/yutai/comparisons", follow_redirects=False)
    assert r.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize("where", ["receipt", "report", "source"])
def test_nanosecond_timestamp_precision_is_rejected(saved, where):
    report = json.loads(saved["report"])
    receipt = json.loads(saved["receipt"])
    if where in {"receipt", "report"}:
        report["generated_at"] = "2026-11-03T00:00:00.123456001Z"
        receipt["generated_at"] = "2026-11-03T00:00:00.123456002Z"
    else:
        next(r for r in report["records"] if r["new"])["new"]["fetched_at"] = (
            "2026-11-03T00:00:00.123456001Z"
        )
    body = canonical(report)
    receipt.update(
        report_sha256=digest(body),
        report_key=f"{PREFIX}/objects/{digest(body)}.json",
        report_bytes=len(body),
    )
    if where == "receipt":
        with pytest.raises(ValueError):
            validate_receipt(canonical(receipt), digest(canonical(receipt)))
    else:
        if where == "report":
            receipt["generated_at"] = "2026-11-03T00:00:00.123456Z"
        with pytest.raises(ValueError):
            validate_report(
                body, validate_receipt(canonical(receipt), digest(canonical(receipt)))
            )
