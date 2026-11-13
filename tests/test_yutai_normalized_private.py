from __future__ import annotations
import json
import os
from pathlib import Path

os.environ.setdefault("R2_PUBLIC_BASE_URL", "https://example.invalid")
import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
from app.main import app
from app import (
    config,
    yutai_normalized_service as service,
    yutai_normalized_storage as storage,
)
from app.yutai_normalized_worker import read_validated, SavedReadError
from app.yutai_normalized_wire import canonical, digest, PREFIX, validate_release

AUTH = {"Authorization": "Bearer synthetic-normalized"}


@pytest.fixture
def saved(monkeypatch):
    row = json.loads(
        (
            Path(__file__).parent / "fixtures/yutai_normalized_delivery_synthetic.json"
        ).read_text(encoding="utf-8")
    )
    body = canonical(
        dict(
            schema_version="yutai-normalized-release-v1",
            coverage="partial",
            record_count=1,
            records=[dict(month="2027-03", record=row)],
        )
    )
    sha = digest(body)
    objects = {f"{PREFIX}/{sha}.json": body}
    calls = []

    def read(key, limit):
        calls.append(key)
        if key not in objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "read")
        return objects[key]

    async def local(selection, sha):
        return read_validated(selection, sha)

    monkeypatch.setattr(config, "YUTAI_NORMALIZED_API_KEY", "synthetic-normalized")
    monkeypatch.setattr(storage, "_read_sync", read)
    monkeypatch.setattr(service, "read_saved", local)
    return dict(
        row=row,
        sha=sha,
        body=body,
        objects=objects,
        calls=calls,
        path=f"/private/yutai/normalized/releases/{sha}/records/2027-03/1234",
    )


def test_exact_raw_record_and_nulls_preserved(saved):
    with TestClient(app) as client:
        response = client.get(saved["path"], headers=AUTH)
    assert response.status_code == 200
    assert response.json()["record"] == saved["row"]
    assert response.json()["record_sha256"] == digest(canonical(saved["row"]))
    assert response.headers["x-content-sha256"] == digest(response.content)
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}])
def test_auth_precedes_storage(saved, headers):
    with TestClient(app) as c:
        assert c.get(saved["path"], headers=headers).status_code == 401
    assert not saved["calls"]


def test_unconfigured_fails_closed(saved, monkeypatch):
    monkeypatch.setattr(config, "YUTAI_NORMALIZED_API_KEY", "")
    with TestClient(app) as c:
        assert c.get(saved["path"], headers=AUTH).status_code == 503
    assert not saved["calls"]


@pytest.mark.parametrize("selection", ["2028-03/1234", "2027-03/9324"])
def test_missing_is_not_no_benefit(saved, selection):
    with TestClient(app) as c:
        r = c.get(
            f"/private/yutai/normalized/releases/{saved['sha']}/records/{selection}",
            headers=AUTH,
        )
    assert r.status_code == 404 and "not saved" in r.json()["detail"]


def test_corruption_and_draft_fail_closed(saved):
    key = f"{PREFIX}/{saved['sha']}.json"
    saved["objects"][key] = saved["body"] + b" "
    with TestClient(app) as c:
        assert c.get(saved["path"], headers=AUTH).status_code == 503
    payload = json.loads(saved["body"])
    payload["records"][0]["record"]["normalization_status"] = "draft"
    with pytest.raises(ValueError):
        validate_release(canonical(payload))


@pytest.mark.parametrize(
    "selection,sha",
    [("2027-13/1234", "b" * 64), ("2027-03/../x", "b" * 64), ("2027-03/1234", "bad")],
)
def test_invalid_selector_before_storage(saved, selection, sha):
    with pytest.raises(SavedReadError) as exc:
        read_validated(selection, sha)
    assert exc.value.status == 400 and not saved["calls"]


def test_openapi_explicit_v2_record(saved):
    schema = app.openapi()
    model = schema["components"]["schemas"]["NormalizedReadDocument"]
    assert model["properties"]["record"]["$ref"].endswith("/YutaiNormalizedRecordV2")


@pytest.mark.asyncio
async def test_supervisor_deadline_drains_full_pipe_and_recovers(monkeypatch):
    import asyncio
    import sys
    from app import yutai_normalized_service as service
    from app.yutai_normalized_worker import SavedReadError

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
    task = asyncio.create_task(service.read_saved("2027-03/1234", "a" * 64))
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
    assert await service.read_saved("2027-03/1234", "a" * 64) == (body, digest(body))


@pytest.mark.asyncio
async def test_request_cancel_during_spawn_keeps_supervisor_ownership(monkeypatch):
    import asyncio
    import sys
    import threading
    from app import yutai_normalized_service as service
    from app.yutai_normalized_worker import SavedReadError

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
    task = asyncio.create_task(service.read_saved("2027-03/1234", "a" * 64))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        task.cancel()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(SavedReadError):
            await service.read_saved("2027-03/1234", "a" * 64)
    finally:
        release.set()
    for _ in range(200):
        if service._SLOT.acquire(blocking=False):
            service._SLOT.release()
            break
        await asyncio.sleep(0.01)
    else:
        pytest.fail("Supervisor did not reap/release")
    assert await service.read_saved("2027-03/1234", "a" * 64) == (body, digest(body))


@pytest.mark.parametrize(
    "path", ["/private/yutai/normalized", "/private/yutai/normalized/missing"]
)
def test_framework_errors_no_store(saved, path):
    with TestClient(app) as c:
        response = c.get(path)
    assert response.status_code in {404, 405}
    assert response.headers["cache-control"] == "private, no-store"


def test_oversize_and_utf16_fail_closed(saved):
    with pytest.raises(ValueError):
        validate_release(saved["body"].decode().encode("utf-16"))
    with pytest.raises(ValueError):
        validate_release(b" " * (4 * 1024 * 1024 + 1))
