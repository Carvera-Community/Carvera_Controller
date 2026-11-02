"""Upload API: request validation, auth, origins, and the queue, against a real HTTP server on
localhost with a fake machine bridge (the Kivy bridge is exercised on hardware)."""

from __future__ import annotations

import hashlib
import http.client
import json
import threading
import time

import pytest

from carveracontroller.addons.upload_api.api import (
    REMOTE_DIR,
    UploadApi,
    UploadOutcome,
    UploadQueue,
    is_loopback,
    validate_name,
)


class FakeBridge:
    def __init__(self, ready=True, outcome=UploadOutcome.OK):
        self.ready = ready
        self.reason = "machine is Run"
        self.outcome = outcome
        self.uploads: list[tuple[str, str, bytes]] = []
        self.notices: list[str] = []
        self.started = threading.Event()

    def readiness(self):
        return (True, "") if self.ready else (False, self.reason)

    def machine_name(self):
        return "10.0.0.127"

    def upload(self, local_path, remote_dir, done):
        with open(local_path, "rb") as fh:
            self.uploads.append((local_path, remote_dir, fh.read()))
        self.started.set()
        done(self.outcome, "uploaded" if self.outcome == UploadOutcome.OK else "busy or failed")

    def notify(self, message):
        self.notices.append(message)


@pytest.fixture
def api():
    bridge = FakeBridge()
    server = UploadApi(bridge)
    server.start("127.0.0.1", 0)
    server.queue.poll_interval = 0.02
    yield server, bridge
    server.stop()


def request(server, method, path, body=None, headers=None):
    host, port = server.address
    conn = http.client.HTTPConnection(host, port, timeout=5)
    conn.request(method, path, body=body, headers=headers or {})
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    data = json.loads(raw) if raw else None
    return resp.status, data, dict(resp.getheaders())


def post_file(server, name, content: bytes, md5=None, headers=None):
    h = {"Content-Type": "application/octet-stream", "X-Content-MD5": md5 or hashlib.md5(content).hexdigest()}
    h.update(headers or {})
    return request(server, "POST", f"/v1/uploads?name={name}", body=content, headers=h)


def wait_for(predicate, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_names():
    assert validate_name("coin-20261101.nc") is None
    assert validate_name("a_b.gcode") is None
    for bad in ["", "../x.nc", "a/b.nc", "a b.nc", "x.lz.nc", "x.bin", "..nc", "-" * 120 + ".nc"]:
        assert validate_name(bad), bad


def test_loopback():
    assert is_loopback("127.0.0.1") and is_loopback("::1") and is_loopback("localhost")
    assert not is_loopback("0.0.0.0") and not is_loopback("") and not is_loopback("10.0.0.5")


def test_status(api):
    server, _ = api
    status, data, _ = request(server, "GET", "/v1/status")
    assert status == 200
    assert data["api"] == 1
    assert data["machine"] == {"name": "10.0.0.127", "ready": True, "reason": ""}
    assert data["remote_dir"] == REMOTE_DIR


def test_upload_is_queued_and_sent(api):
    server, bridge = api
    content = b"G21\nG90\n" * 1000
    status, job, headers = post_file(server, "coin.nc", content)
    assert status == 202
    assert job["state"] == "queued" and job["path"] == f"{REMOTE_DIR}/coin.nc"
    assert headers["Location"] == f"/v1/uploads/{job['id']}"
    assert wait_for(lambda: request(server, "GET", f"/v1/uploads/{job['id']}")[1]["state"] == "done")
    (path, remote_dir, sent) = bridge.uploads[0]
    assert sent == content and remote_dir == REMOTE_DIR and path.endswith("/coin.nc")
    assert "uploaded coin.nc" in bridge.notices[0]


def test_waits_until_the_machine_is_ready(api):
    server, bridge = api
    bridge.ready = False
    _, job, _ = post_file(server, "wait.nc", b"G21\n")
    time.sleep(0.2)
    assert bridge.uploads == []
    assert request(server, "GET", "/v1/status")[1]["waiting"] == "machine is Run"
    bridge.ready = True
    assert wait_for(lambda: request(server, "GET", f"/v1/uploads/{job['id']}")[1]["state"] == "done")


def test_busy_at_the_last_moment_requeues(api):
    server, bridge = api
    bridge.outcome = UploadOutcome.BUSY
    _, job, _ = post_file(server, "again.nc", b"G21\n")
    assert bridge.started.wait(2)
    time.sleep(0.1)
    assert request(server, "GET", f"/v1/uploads/{job['id']}")[1]["state"] == "queued"
    bridge.outcome = UploadOutcome.OK
    assert wait_for(lambda: request(server, "GET", f"/v1/uploads/{job['id']}")[1]["state"] == "done")


def test_failed_upload_is_reported(api):
    server, bridge = api
    bridge.outcome = UploadOutcome.FAILED
    _, job, _ = post_file(server, "bad.nc", b"G21\n")
    assert wait_for(lambda: request(server, "GET", f"/v1/uploads/{job['id']}")[1]["state"] == "failed")
    assert "failed" in bridge.notices[0]


def test_md5_mismatch_is_rejected_and_nothing_queued(api):
    server, bridge = api
    status, data, _ = post_file(server, "x.nc", b"G21\n", md5="0" * 32)
    assert status == 422 and "MD5 mismatch" in data["error"]
    assert request(server, "GET", "/v1/uploads")[1]["uploads"] == []
    assert bridge.uploads == []


def test_bad_requests(api):
    server, _ = api
    assert post_file(server, "../x.nc", b"G21\n")[0] == 400
    assert post_file(server, "x.exe", b"G21\n")[0] == 400
    status, _, _ = request(server, "POST", "/v1/uploads?name=x.nc", body=b"G21\n", headers={})
    assert status == 400  # no MD5
    assert post_file(server, "x.nc", b"")[0] == 400  # empty
    assert request(server, "GET", "/v1/nope")[0] == 404
    assert request(server, "POST", "/v1/status", body=b"", headers={"Content-Length": "0"})[0] == 404
    assert request(server, "GET", "/v1/uploads/doesnotexist")[0] == 404


def test_cancel_queued(api):
    server, bridge = api
    bridge.ready = False
    _, job, _ = post_file(server, "c.nc", b"G21\n")
    status, data, _ = request(server, "DELETE", f"/v1/uploads/{job['id']}")
    assert status == 200 and data["state"] == "cancelled"
    bridge.ready = True
    time.sleep(0.2)
    assert bridge.uploads == []
    assert request(server, "DELETE", f"/v1/uploads/{job['id']}")[0] == 409


def test_token():
    bridge = FakeBridge()
    server = UploadApi(bridge)
    server.start("127.0.0.1", 0, token="s3cret")
    try:
        assert request(server, "GET", "/v1/status")[0] == 401
        assert request(server, "GET", "/v1/status", headers={"Authorization": "Bearer nope"})[0] == 401
        assert request(server, "GET", "/v1/status", headers={"Authorization": "Bearer s3cret"})[0] == 200
        assert post_file(server, "t.nc", b"G21\n")[0] == 401
    finally:
        server.stop()


def test_lan_requires_a_token():
    server = UploadApi(FakeBridge())
    with pytest.raises(ValueError):
        server.start("0.0.0.0", 0)
    assert not server.running


def test_browser_origins():
    bridge = FakeBridge()
    server = UploadApi(bridge)
    server.start("127.0.0.1", 0, allowed_origins=["https://app.example.com"])
    try:
        # A page from another origin can't use it, even for a "simple" request.
        status, _, _ = post_file(server, "o.nc", b"G21\n", headers={"Origin": "https://evil.example"})
        assert status == 403
        assert request(server, "OPTIONS", "/v1/uploads", headers={"Origin": "https://evil.example"})[0] == 403
        # The allowed origin gets CORS headers.
        status, _, headers = request(
            server,
            "OPTIONS",
            "/v1/uploads",
            headers={"Origin": "https://app.example.com", "Access-Control-Request-Method": "POST"},
        )
        assert status == 204 and headers["Access-Control-Allow-Origin"] == "https://app.example.com"
        status, _, headers = request(server, "GET", "/v1/status", headers={"Origin": "https://app.example.com"})
        assert status == 200 and headers["Access-Control-Allow-Origin"] == "https://app.example.com"
        # Non-browser clients send no Origin and are allowed.
        assert request(server, "GET", "/v1/status")[0] == 200
    finally:
        server.stop()


def test_queue_runs_jobs_in_order(tmp_path):
    bridge = FakeBridge()
    q = UploadQueue(bridge, spool_dir=str(tmp_path))
    for name in ("a.nc", "b.nc"):
        p = tmp_path / name
        p.write_bytes(name.encode())
        q.add(name=name, local_path=str(p), size=4, md5="x" * 32, client="test")
    q.run_once()
    q.run_once()
    assert [u[2] for u in bridge.uploads] == [b"a.nc", b"b.nc"]
    assert not (tmp_path / "a.nc").exists()  # spooled file removed after upload


def test_discard_pending_input_drops_a_stale_status_reply():
    from types import SimpleNamespace

    from carveracontroller.Controller import Controller

    class FakeStream:
        def __init__(self, chunks):
            self.chunks = list(chunks)

        def waiting_for_recv(self):
            return bool(self.chunks)

        def recv(self):
            return self.chunks.pop(0)

    stream = FakeStream([b"<Idle|MPos:0,0,0>\n", b"ok\r\n"])
    dropped = Controller.discardPendingInput(SimpleNamespace(stream=stream))
    assert dropped == len(b"<Idle|MPos:0,0,0>\n") + len(b"ok\r\n")
    assert stream.chunks == []
    assert Controller.discardPendingInput(SimpleNamespace(stream=None)) == 0
