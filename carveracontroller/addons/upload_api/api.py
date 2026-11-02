"""Local HTTP API that queues G-code uploads through the Controller's own machine connection.

The machine's WiFi accepts one client at a time, and that client is usually this Controller. With
the Upload API on, another program (a CAM or design tool, or a script) can hand the Controller a
file instead of taking the connection away. The Controller uploads it to the SD card as soon as the
machine is idle, using the same upload path as the file browser.

The API only uploads. It never runs, jogs, homes or sends commands to the machine.

This module is Kivy-free so it can be unit tested. It talks to the application through a
:class:`MachineBridge` (see ``bridge.py`` for the Controller's implementation).

Endpoints (all JSON)::

    GET    /v1/status          API and machine state, queue length
    POST   /v1/uploads?name=x  body: the file; headers Content-Length, X-Content-MD5 (hex)
                               -> 202 {"id": ..., "state": "queued"}
    GET    /v1/uploads         recent uploads, newest first
    GET    /v1/uploads/<id>    one upload
    DELETE /v1/uploads/<id>    cancel a queued upload
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import socketserver
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional
from urllib.parse import parse_qs, urlparse

try:  # Protocol is in typing from 3.8
    from typing import Protocol
except ImportError:  # pragma: no cover
    Protocol = object  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

API_VERSION = 1
DEFAULT_PORT = 8642
#: Uploads larger than this are refused (413).
MAX_UPLOAD_BYTES = 64 * 1024 * 1024
#: Where API uploads go on the machine.
REMOTE_DIR = "/sd/gcodes"
#: How long one upload may take before the job is marked failed.
UPLOAD_TIMEOUT_S = 15 * 60
#: Finished jobs kept for GET /v1/uploads.
KEEP_FINISHED = 50

GCODE_EXTENSIONS = (".nc", ".gcode", ".cnc", ".ngc", ".tap", ".txt")
_NAME_RE = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9_.-]{0,99}$")
_MD5_RE = re.compile(r"^[0-9a-fA-F]{32}$")


def validate_name(name: str) -> str | None:
    """Return an error message for an unacceptable file name, or None.

    Plain names only: letters, digits, ``_ - .``, a G-code extension, no path, no ``..`` and no
    ``.lz`` (the firmware treats names containing ``.lz`` as compressed).
    """
    if not name or not _NAME_RE.match(name):
        return "name must be 1-100 characters of letters, digits, '_', '-' or '.', with no path"
    if ".." in name:
        return "name must not contain '..'"
    if ".lz" in name.lower():
        return "name must not contain '.lz'"
    if not name.lower().endswith(GCODE_EXTENSIONS):
        return "name must end with one of " + ", ".join(GCODE_EXTENSIONS)
    return None


class UploadOutcome:
    OK = "ok"
    FAILED = "failed"
    #: The machine became busy between the readiness check and the upload; try again later.
    BUSY = "busy"


class MachineBridge(Protocol):
    """What the queue needs from the application."""

    def readiness(self) -> tuple[bool, str]:
        """(ready, reason): ready means connected, Idle and no other transfer running."""

    def machine_name(self) -> str:
        """The connected machine's name or address, for status (may be empty)."""

    def upload(self, local_path: str, remote_dir: str, done: Callable[[str, str], None]) -> None:
        """Start uploading ``local_path`` into ``remote_dir``; call ``done(outcome, message)`` once."""

    def notify(self, message: str) -> None:
        """Tell the operator something happened (e.g. a line in the Controller's log)."""


@dataclass
class Job:
    id: str
    name: str
    size: int
    md5: str
    local_path: str
    client: str
    state: str = "queued"  # queued, uploading, done, failed, cancelled
    message: str = ""
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "path": f"{REMOTE_DIR}/{self.name}",
            "size": self.size,
            "md5": self.md5,
            "state": self.state,
            "message": self.message,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


class UploadQueue:
    """Jobs, and a worker thread that uploads the oldest queued job whenever the machine is ready."""

    def __init__(
        self,
        bridge: MachineBridge,
        spool_dir: str | None = None,
        poll_interval: float = 1.0,
        upload_timeout: float = UPLOAD_TIMEOUT_S,
    ):
        self.bridge = bridge
        self.spool_dir = spool_dir or tempfile.mkdtemp(prefix="carvera-upload-api-")
        self.poll_interval = poll_interval
        self.upload_timeout = upload_timeout
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        #: Why the head of the queue is waiting (e.g. "machine is Run"), for status.
        self.waiting_reason = ""

    # -- jobs ---------------------------------------------------------------

    def add(self, name: str, local_path: str, size: int, md5: str, client: str) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], name=name, size=size, md5=md5, local_path=local_path, client=client)
        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
            self._prune()
        self._wake.set()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def recent(self) -> list[Job]:
        with self._lock:
            return [self._jobs[i] for i in reversed(self._order)]

    def counts(self) -> dict:
        with self._lock:
            states = [j.state for j in self._jobs.values()]
        return {s: states.count(s) for s in ("queued", "uploading")}

    def cancel(self, job_id: str) -> tuple[bool, str]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False, "not found"
            if job.state != "queued":
                return False, f"can't cancel an upload that is {job.state}"
            job.state, job.message, job.finished_at = "cancelled", "cancelled by client", time.time()
        self._discard(job)
        return True, ""

    def _prune(self) -> None:
        finished = [i for i in self._order if self._jobs[i].state in ("done", "failed", "cancelled")]
        for job_id in finished[: max(0, len(finished) - KEEP_FINISHED)]:
            self._order.remove(job_id)
            del self._jobs[job_id]

    def _next_queued(self) -> Job | None:
        with self._lock:
            for job_id in self._order:
                job = self._jobs[job_id]
                if job.state == "queued":
                    return job
        return None

    @staticmethod
    def _discard(job: Job) -> None:
        try:
            os.remove(job.local_path)
        except OSError:
            pass

    # -- worker ---------------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="upload-api-queue", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(self.poll_interval)
            self._wake.clear()
            if self._stop.is_set():
                break
            try:
                self.run_once()
            except Exception:  # never let the worker die
                logger.exception("Upload API worker error")

    def run_once(self) -> None:
        """Upload the oldest queued job if the machine is ready. Blocks until that upload ends."""
        job = self._next_queued()
        if job is None:
            self.waiting_reason = ""
            return
        ready, reason = self.bridge.readiness()
        if not ready:
            self.waiting_reason = reason
            return
        self.waiting_reason = ""
        with self._lock:
            if job.state != "queued":  # cancelled meanwhile
                return
            job.state, job.message = "uploading", ""

        finished = threading.Event()
        result: dict[str, str] = {}

        def done(outcome: str, message: str = "") -> None:
            result["outcome"], result["message"] = outcome, message
            finished.set()

        try:
            self.bridge.upload(job.local_path, REMOTE_DIR, done)
        except Exception as exc:
            done(UploadOutcome.FAILED, str(exc))
        if not finished.wait(self.upload_timeout):
            done(UploadOutcome.FAILED, "upload timed out")

        outcome, message = result.get("outcome", UploadOutcome.FAILED), result.get("message", "")
        with self._lock:
            if outcome == UploadOutcome.BUSY:
                job.state, job.message = "queued", message or "machine became busy"
                return
            job.state = "done" if outcome == UploadOutcome.OK else "failed"
            job.message = message
            job.finished_at = time.time()
        self._discard(job)
        if job.state == "done":
            self.bridge.notify(f"Upload API: uploaded {job.name} to {REMOTE_DIR} (from {job.client})")
        else:
            self.bridge.notify(f"Upload API: upload of {job.name} failed: {message or 'unknown error'}")
        self._wake.set()  # look at the next job straight away


# -- HTTP -------------------------------------------------------------------


class UploadApiServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], queue: UploadQueue, token: str = "", allowed_origins=()):
        self.queue = queue
        self.token = token
        self.allowed_origins = {o.strip().rstrip("/") for o in allowed_origins if o.strip()}
        super().__init__(address, _Handler)

    def server_bind(self):
        # HTTPServer.server_bind looks up the host's fully qualified name, a reverse-DNS query that
        # can block for tens of seconds on some networks. The name is only cosmetic here.
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name, self.server_port = str(host), int(port)


class _Handler(BaseHTTPRequestHandler):
    server: UploadApiServer
    server_version = "CarveraUploadAPI/1"

    def log_message(self, fmt, *args):  # route to logging, not stderr
        logger.info("%s %s", self.client_address[0], fmt % args)

    # -- helpers --

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        return origin is None or origin.rstrip("/") in self.server.allowed_origins

    def _send_json(self, status: int, body: dict, extra: dict | None = None) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        origin = self.headers.get("Origin")
        if origin and origin.rstrip("/") in self.server.allowed_origins:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _error(self, status: int, message: str) -> None:
        self._send_json(status, {"error": message})

    def _authorized(self) -> bool:
        if not self.server.token:
            return True
        header = self.headers.get("Authorization", "")
        given = header[7:] if header.startswith("Bearer ") else ""
        return hmac.compare_digest(given.encode(), self.server.token.encode())

    def _guard(self) -> bool:
        """Origin and token checks shared by every method. Sends the error itself."""
        if not self._origin_ok():
            self._error(HTTPStatus.FORBIDDEN, "origin not allowed")
            return False
        if not self._authorized():
            self._error(HTTPStatus.UNAUTHORIZED, "missing or wrong token")
            return False
        return True

    def _route(self) -> tuple[str, str | None, dict]:
        url = urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        if parts[:2] == ["v1", "status"] and len(parts) == 2:
            return "status", None, query
        if parts[:2] == ["v1", "uploads"]:
            if len(parts) == 2:
                return "uploads", None, query
            if len(parts) == 3:
                return "upload", parts[2], query
        return "", None, query

    # -- methods --

    def do_OPTIONS(self):  # CORS preflight
        origin = self.headers.get("Origin")
        if not origin or origin.rstrip("/") not in self.server.allowed_origins:
            self._error(HTTPStatus.FORBIDDEN, "origin not allowed")
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Content-MD5")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if not self._guard():
            return
        kind, job_id, _ = self._route()
        q = self.server.queue
        if kind == "status":
            ready, reason = q.bridge.readiness()
            self._send_json(
                HTTPStatus.OK,
                {
                    "api": API_VERSION,
                    "machine": {"name": q.bridge.machine_name(), "ready": ready, "reason": reason},
                    "queue": q.counts(),
                    "waiting": q.waiting_reason,
                    "remote_dir": REMOTE_DIR,
                    "max_bytes": MAX_UPLOAD_BYTES,
                },
            )
        elif kind == "uploads":
            self._send_json(HTTPStatus.OK, {"uploads": [j.to_json() for j in q.recent()]})
        elif kind == "upload":
            job = q.get(job_id or "")
            if job:
                self._send_json(HTTPStatus.OK, job.to_json())
            else:
                self._error(HTTPStatus.NOT_FOUND, "no such upload")
        else:
            self._error(HTTPStatus.NOT_FOUND, "not found")

    def do_DELETE(self):
        if not self._guard():
            return
        kind, job_id, _ = self._route()
        if kind != "upload":
            self._error(HTTPStatus.NOT_FOUND, "not found")
            return
        ok, why = self.server.queue.cancel(job_id or "")
        if ok:
            job = self.server.queue.get(job_id or "")
            self._send_json(HTTPStatus.OK, job.to_json() if job else {"id": job_id, "state": "cancelled"})
        elif why == "not found":
            self._error(HTTPStatus.NOT_FOUND, "no such upload")
        else:
            self._error(HTTPStatus.CONFLICT, why)

    def do_POST(self):
        if not self._guard():
            return
        kind, _, query = self._route()
        if kind != "uploads":
            self._error(HTTPStatus.NOT_FOUND, "not found")
            return
        name = query.get("name", "")
        problem = validate_name(name)
        if problem:
            self._error(HTTPStatus.BAD_REQUEST, problem)
            return
        md5 = (self.headers.get("X-Content-MD5") or "").strip().lower()
        if not _MD5_RE.match(md5):
            self._error(HTTPStatus.BAD_REQUEST, "X-Content-MD5 header with the file's MD5 (32 hex) is required")
            return
        if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
            self._error(HTTPStatus.LENGTH_REQUIRED, "send Content-Length; chunked uploads aren't supported")
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._error(HTTPStatus.LENGTH_REQUIRED, "Content-Length is required")
            return
        if length <= 0:
            self._error(HTTPStatus.BAD_REQUEST, "the file is empty")
            return
        if length > MAX_UPLOAD_BYTES:
            self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, f"files over {MAX_UPLOAD_BYTES} bytes aren't accepted")
            return

        q = self.server.queue
        os.makedirs(q.spool_dir, exist_ok=True)
        spool_name = f"{uuid.uuid4().hex[:8]}-{name}"
        local_path = os.path.join(q.spool_dir, spool_name)
        digest = hashlib.md5()  # noqa: S324 - an integrity check, as the machine uses MD5
        remaining = length
        try:
            with open(local_path, "wb") as fh:
                while remaining > 0:
                    chunk = self.rfile.read(min(65536, remaining))
                    if not chunk:
                        raise ConnectionError("connection closed before the whole file arrived")
                    digest.update(chunk)
                    fh.write(chunk)
                    remaining -= len(chunk)
        except Exception as exc:
            _remove(local_path)
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        if digest.hexdigest() != md5:
            _remove(local_path)
            self._error(HTTPStatus.UNPROCESSABLE_ENTITY, f"MD5 mismatch: received {digest.hexdigest()}, expected {md5}")
            return
        # The upload keeps the client's file name on the machine.
        final_path = os.path.join(q.spool_dir, f"{uuid.uuid4().hex[:8]}", name)
        os.makedirs(os.path.dirname(final_path), exist_ok=True)
        os.replace(local_path, final_path)
        job = q.add(name=name, local_path=final_path, size=length, md5=md5, client=self.client_address[0])
        self._send_json(HTTPStatus.ACCEPTED, job.to_json(), {"Location": f"/v1/uploads/{job.id}"})


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def is_loopback(host: str) -> bool:
    if host in ("localhost", ""):
        return host == "localhost"
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class UploadApi:
    """Owns the queue and the HTTP server; started and stopped from the Controller's settings."""

    def __init__(self, bridge: MachineBridge):
        self.bridge = bridge
        self.queue: UploadQueue | None = None
        self.server: UploadApiServer | None = None
        self._server_thread: threading.Thread | None = None
        self.address: tuple[str, int] | None = None

    @property
    def running(self) -> bool:
        return self.server is not None

    def start(self, host: str = "127.0.0.1", port: int = DEFAULT_PORT, token: str = "", allowed_origins=()) -> None:
        """Start (or restart) listening. Listening beyond this computer requires a token."""
        self.stop()
        if not is_loopback(host) and not token:
            raise ValueError("a token is required when the Upload API listens beyond this computer")
        self.queue = UploadQueue(self.bridge)
        self.queue.start()
        self.server = UploadApiServer((host, port), self.queue, token=token, allowed_origins=allowed_origins)
        self.address = self.server.server_address[:2]
        self._server_thread = threading.Thread(target=self.server.serve_forever, name="upload-api-http", daemon=True)
        self._server_thread.start()
        logger.info("Upload API listening on %s:%s", *self.address)

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        if self.queue:
            self.queue.stop()
            self.queue = None
        self.address = None
