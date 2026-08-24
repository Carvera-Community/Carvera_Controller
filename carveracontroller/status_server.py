"""Small read-only HTTP server exposing current job progress.

Lets a second device (phone, tablet, another PC) watch time-remaining/elapsed
for the job this Controller instance is running, without needing its own
connection to the machine (the machine's firmware only accepts one TCP
client on port 2222 at a time, so a second *Controller* can't connect
directly).

The server just serves a small self-contained status page plus the JSON it
polls. It has no write/control endpoints - it cannot jog, send gcode, or
otherwise touch the machine.
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

logger = logging.getLogger(__name__)


_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Carvera Job Status</title>
<style>
  :root {
    color-scheme: light dark;
    --bg: #f4f5f7;
    --card: #ffffff;
    --text: #1b1d21;
    --muted: #6b7280;
    --track: #e5e7eb;
    --bar: #2f8cff;
    --border: #e5e7eb;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #16181d;
      --card: #1f2229;
      --text: #f2f3f5;
      --muted: #9aa1ac;
      --track: #2b2f38;
      --bar: #4da3ff;
      --border: #2b2f38;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    min-height: 100vh;
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
  }
  .card {
    width: 100%;
    max-width: 480px;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 24px;
  }
  .filename {
    font-size: 1.05rem;
    font-weight: 600;
    word-break: break-word;
    margin-bottom: 2px;
  }
  .state {
    font-size: 0.85rem;
    color: var(--muted);
    margin-bottom: 20px;
  }
  .state.playing { color: var(--bar); }
  .bar-track {
    width: 100%;
    height: 14px;
    border-radius: 7px;
    background: var(--track);
    overflow: hidden;
    margin-bottom: 10px;
  }
  .bar-fill {
    height: 100%;
    width: 0%;
    background: var(--bar);
    transition: width 0.6s ease;
  }
  .percent {
    text-align: right;
    font-size: 0.9rem;
    color: var(--muted);
    margin-bottom: 20px;
  }
  .times {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 8px;
    text-align: center;
  }
  .times div { display: flex; flex-direction: column; gap: 4px; }
  .times .label {
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--muted);
  }
  .times .value { font-size: 1.15rem; font-weight: 600; font-variant-numeric: tabular-nums; }
  .banner {
    display: none;
    margin-top: 18px;
    padding: 10px 12px;
    border-radius: 10px;
    background: #7a1f1f;
    color: #fff;
    font-size: 0.85rem;
    text-align: center;
  }
  .banner.show { display: block; }
  .updated {
    margin-top: 16px;
    text-align: center;
    font-size: 0.75rem;
    color: var(--muted);
    font-variant-numeric: tabular-nums;
  }
</style>
</head>
<body>
  <div class="card">
    <div class="filename" id="filename">&nbsp;</div>
    <div class="state" id="state">Loading&hellip;</div>
    <div class="bar-track"><div class="bar-fill" id="bar"></div></div>
    <div class="percent" id="percent">0%</div>
    <div class="times">
      <div><span class="label">Elapsed</span><span class="value" id="elapsed">--:--:--</span></div>
      <div><span class="label">Remaining</span><span class="value" id="remaining">--:--:--</span></div>
      <div><span class="label">Total (est.)</span><span class="value" id="total">--:--:--</span></div>
    </div>
    <div class="banner" id="banner">Lost contact with the Controller app</div>
    <div class="updated" id="updated">Waiting for first update&hellip;</div>
  </div>
<script>
function fmt(sec) {
  sec = Math.max(0, Math.round(sec || 0));
  var h = Math.floor(sec / 3600);
  var m = Math.floor((sec % 3600) / 60);
  var s = sec % 60;
  function pad(n) { return n < 10 ? "0" + n : "" + n; }
  return h + ":" + pad(m) + ":" + pad(s);
}

function render(data) {
  document.getElementById("banner").classList.remove("show");
  var name = data.filename || (data.connected ? "No file selected" : "Not connected");
  document.getElementById("filename").textContent = name;

  var stateEl = document.getElementById("state");
  stateEl.textContent = data.connected ? data.state : "Machine not connected";
  stateEl.classList.toggle("playing", !!data.playing);

  var pct = Math.max(0, Math.min(100, data.percent || 0));
  document.getElementById("bar").style.width = pct + "%";
  document.getElementById("percent").textContent = Math.round(pct) + "%";

  document.getElementById("elapsed").textContent = fmt(data.elapsed_sec);
  document.getElementById("remaining").textContent = fmt(data.remaining_sec);
  document.getElementById("total").textContent = fmt(data.total_sec);

  // Local-time stamp of this successful poll, so a stalled page is obvious
  // (this stops advancing) rather than silently showing stale numbers.
  var now = new Date();
  var timeStr = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  document.getElementById("updated").textContent = "Updated " + timeStr;
}

function poll() {
  fetch("status.json", { cache: "no-store" })
    .then(function (r) { return r.json(); })
    .then(render)
    .catch(function () {
      document.getElementById("banner").classList.add("show");
    });
}

poll();
setInterval(poll, 3000);
</script>
</body>
</html>
"""


class _Handler(BaseHTTPRequestHandler):
    # Set per-server via a subclass in StatusServer.start().
    status_provider: Callable[[], dict] = None

    def log_message(self, fmt, *args):  # noqa: A003 - stdlib signature
        logger.debug("%s - %s", self.address_string(), fmt % args)

    def _write(self, status: int, body: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._write(200, _PAGE.encode("utf-8"), "text/html; charset=utf-8")
            return
        if self.path in ("/status.json", "/status"):
            try:
                payload = self.status_provider()
            except Exception:
                logger.exception("Status provider failed")
                payload = {"error": "unavailable"}
            self._write(200, json.dumps(payload).encode("utf-8"), "application/json")
            return
        self._write(404, b"Not found", "text/plain; charset=utf-8")


class StatusServer:
    """Serves a read-only job-progress page/JSON on the local network."""

    def __init__(self, status_provider: Callable[[], dict], host: str = "0.0.0.0", port: int = 8765):
        self._status_provider = status_provider
        self._host = host
        self._port = port
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._httpd is not None

    @property
    def port(self) -> int:
        return self._httpd.server_address[1] if self._httpd else self._port

    def start(self):
        if self._httpd is not None:
            return
        handler = type("_BoundHandler", (_Handler,), {"status_provider": staticmethod(self._status_provider)})
        try:
            self._httpd = ThreadingHTTPServer((self._host, self._port), handler)
        except OSError as e:
            logger.error(f"Could not start status server on {self._host}:{self._port}: {e}")
            self._httpd = None
            return
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="StatusServer", daemon=True)
        self._thread.start()
        logger.info(f"Job status server listening on port {self.port}")

    def stop(self):
        if self._httpd is None:
            return
        self._httpd.shutdown()
        self._httpd.server_close()
        self._httpd = None
        self._thread = None
