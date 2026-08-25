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
  .wrap {
    width: 100%;
    max-width: 900px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 20px;
  }
  .wrap .card { max-width: 480px; }
  .viewer-card {
    max-width: 100%;
    width: 100%;
    padding: 0;
    overflow: hidden;
  }
  .viewer-header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    padding: 14px 20px;
    border-bottom: 1px solid var(--border);
  }
  .viewer-header .title { font-weight: 600; font-size: 0.95rem; }
  .viewer-header .hint { font-size: 0.75rem; color: var(--muted); }
  .viewer-body { position: relative; }
  #glcanvas {
    display: block;
    width: 100%;
    height: min(60vh, 520px);
    background: var(--bg);
    touch-action: none;
  }
  .legend {
    position: absolute;
    left: 12px;
    bottom: 10px;
    display: flex;
    gap: 14px;
    font-size: 0.72rem;
    color: var(--muted);
    background: color-mix(in srgb, var(--card) 80%, transparent);
    padding: 4px 8px;
    border-radius: 8px;
  }
  .legend span { display: inline-flex; align-items: center; gap: 5px; }
  .legend i { width: 9px; height: 9px; border-radius: 2px; display: inline-block; }
  .viewer-empty {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--muted);
    font-size: 0.85rem;
    text-align: center;
    padding: 0 20px;
    pointer-events: none;
  }
</style>
</head>
<body>
<div class="wrap">
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
  <div class="card viewer-card">
    <div class="viewer-header">
      <span class="title">3D View</span>
      <span class="hint" id="viewerHint">drag to orbit &middot; scroll/pinch to zoom</span>
    </div>
    <div class="viewer-body">
      <canvas id="glcanvas"></canvas>
      <div class="legend">
        <span><i style="background:#3fb950"></i>cut &mdash; ahead</span>
        <span><i style="background:#e3b341"></i>rapid &mdash; ahead</span>
        <span><i style="background:#4da3ff"></i>done</span>
        <span><i style="background:#ff4d4f;border-radius:50%"></i>tool</span>
      </div>
      <div class="viewer-empty" id="viewerEmpty">No toolpath loaded yet</div>
    </div>
  </div>
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

// ---------------------------------------------------------------------
// Minimal WebGL 3D toolpath viewer. No external libraries (three.js etc.)
// so this keeps working on a machine-shop network with no internet access.
// ---------------------------------------------------------------------
var Viewer = (function () {
  var canvas = document.getElementById("glcanvas");
  var gl = canvas.getContext("webgl") || canvas.getContext("experimental-webgl");
  var emptyEl = document.getElementById("viewerEmpty");
  if (!gl) {
    emptyEl.textContent = "WebGL is not available in this browser";
    return { setBounds: function () {}, setPath: function () {}, setPlayedLine: function () {}, setMarker: function () {} };
  }

  // -- tiny column-major mat4 helpers (glMatrix-style, hand-rolled to avoid a dependency) --
  function perspective(fovy, aspect, near, far) {
    var f = 1.0 / Math.tan(fovy / 2);
    var nf = 1 / (near - far);
    return new Float32Array([
      f / aspect, 0, 0, 0,
      0, f, 0, 0,
      0, 0, (far + near) * nf, -1,
      0, 0, 2 * far * near * nf, 0,
    ]);
  }
  function lookAt(eye, center, up) {
    var z0 = eye[0] - center[0], z1 = eye[1] - center[1], z2 = eye[2] - center[2];
    var len = Math.hypot(z0, z1, z2) || 1;
    z0 /= len; z1 /= len; z2 /= len;
    var x0 = up[1] * z2 - up[2] * z1, x1 = up[2] * z0 - up[0] * z2, x2 = up[0] * z1 - up[1] * z0;
    len = Math.hypot(x0, x1, x2) || 1;
    x0 /= len; x1 /= len; x2 /= len;
    var y0 = z1 * x2 - z2 * x1, y1 = z2 * x0 - z0 * x2, y2 = z0 * x1 - z1 * x0;
    return new Float32Array([
      x0, y0, z0, 0,
      x1, y1, z1, 0,
      x2, y2, z2, 0,
      -(x0 * eye[0] + x1 * eye[1] + x2 * eye[2]),
      -(y0 * eye[0] + y1 * eye[1] + y2 * eye[2]),
      -(z0 * eye[0] + z1 * eye[1] + z2 * eye[2]),
      1,
    ]);
  }
  function multiply(a, b) {
    var out = new Float32Array(16);
    for (var i = 0; i < 4; i++) {
      for (var j = 0; j < 4; j++) {
        var sum = 0;
        for (var k = 0; k < 4; k++) sum += a[k * 4 + j] * b[i * 4 + k];
        out[i * 4 + j] = sum;
      }
    }
    return out;
  }

  function compile(type, src) {
    var sh = gl.createShader(type);
    gl.shaderSource(sh, src);
    gl.compileShader(sh);
    if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
      console.error(gl.getShaderInfoLog(sh));
    }
    return sh;
  }
  function program(vsSrc, fsSrc) {
    var p = gl.createProgram();
    gl.attachShader(p, compile(gl.VERTEX_SHADER, vsSrc));
    gl.attachShader(p, compile(gl.FRAGMENT_SHADER, fsSrc));
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) {
      console.error(gl.getProgramInfoLog(p));
    }
    return p;
  }

  var pathProgram = program(
    "attribute vec3 aPos; attribute float aLine; attribute float aFeed;" +
      "uniform mat4 uMVP; uniform float uPlayedLine;" +
      "uniform vec3 uCutColor; uniform vec3 uRapidColor; uniform vec3 uDoneColor;" +
      "varying vec3 vColor;" +
      "void main() {" +
      "  vec3 base = aFeed > 0.5 ? uCutColor : uRapidColor;" +
      "  float done = step(aLine, uPlayedLine);" +
      "  vColor = mix(base, uDoneColor, done);" +
      "  gl_Position = uMVP * vec4(aPos, 1.0);" +
      "}",
    "precision mediump float; varying vec3 vColor;" +
      "void main() { gl_FragColor = vec4(vColor, 1.0); }"
  );
  var markerProgram = program(
    "attribute vec3 aPos; uniform mat4 uMVP;" +
      "void main() { gl_Position = uMVP * vec4(aPos, 1.0); gl_PointSize = 14.0; }",
    "precision mediump float; uniform vec3 uColor;" +
      "void main() {" +
      "  vec2 c = gl_PointCoord - vec2(0.5);" +
      "  if (dot(c, c) > 0.25) discard;" +
      "  gl_FragColor = vec4(uColor, 1.0);" +
      "}"
  );

  var pathBuf = gl.createBuffer();
  var markerBuf = gl.createBuffer();
  var vertexCount = 0;
  var bounds = null;
  var center = [0, 0, 0];
  var radius = 100;
  var playedLine = -1;
  var marker = null;

  var yaw = Math.PI * 0.25;
  var pitch = Math.PI * 0.22;
  var distance = 300;
  var minDistance = 5;

  function frame() {
    if (!bounds) return;
    center = [
      (bounds.min[0] + bounds.max[0]) / 2,
      (bounds.min[1] + bounds.max[1]) / 2,
      (bounds.min[2] + bounds.max[2]) / 2,
    ];
    var dx = bounds.max[0] - bounds.min[0];
    var dy = bounds.max[1] - bounds.min[1];
    var dz = bounds.max[2] - bounds.min[2];
    radius = Math.max(1, Math.hypot(dx, dy, dz) / 2);
    distance = radius * 2.2;
    minDistance = radius * 0.05;
  }

  function setBounds(b) {
    bounds = b;
    frame();
  }

  function setPath(points, line, feed) {
    vertexCount = line.length;
    if (!vertexCount) return;
    var interleaved = new Float32Array(vertexCount * 5);
    for (var i = 0; i < vertexCount; i++) {
      interleaved[i * 5 + 0] = points[i * 3 + 0];
      interleaved[i * 5 + 1] = points[i * 3 + 1];
      interleaved[i * 5 + 2] = points[i * 3 + 2];
      interleaved[i * 5 + 3] = line[i];
      interleaved[i * 5 + 4] = feed[i];
    }
    gl.bindBuffer(gl.ARRAY_BUFFER, pathBuf);
    gl.bufferData(gl.ARRAY_BUFFER, interleaved, gl.STATIC_DRAW);
    emptyEl.style.display = "none";
  }

  function setPlayedLine(n) {
    playedLine = typeof n === "number" ? n : -1;
  }

  function setMarker(x, y, z) {
    marker = [x, y, z];
  }

  function resize() {
    var rect = canvas.getBoundingClientRect();
    var dpr = window.devicePixelRatio || 1;
    var w = Math.max(1, Math.round(rect.width * dpr));
    var h = Math.max(1, Math.round(rect.height * dpr));
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
    }
    gl.viewport(0, 0, canvas.width, canvas.height);
  }

  function draw() {
    resize();
    gl.clearColor(0, 0, 0, 0);
    gl.enable(gl.DEPTH_TEST);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

    if (!vertexCount) {
      requestAnimationFrame(draw);
      return;
    }

    var aspect = canvas.width / Math.max(1, canvas.height);
    var proj = perspective((45 * Math.PI) / 180, aspect, Math.max(0.1, radius * 0.01), radius * 20 + distance);
    var cp = Math.cos(pitch), sp = Math.sin(pitch);
    var cy = Math.cos(yaw), sy = Math.sin(yaw);
    var eye = [
      center[0] + distance * cp * cy,
      center[1] + distance * cp * sy,
      center[2] + distance * sp,
    ];
    var view = lookAt(eye, center, [0, 0, 1]); // Z is the vertical (spindle) axis in machine coordinates
    var mvp = multiply(proj, view);

    gl.useProgram(pathProgram);
    gl.bindBuffer(gl.ARRAY_BUFFER, pathBuf);
    var stride = 5 * 4;
    var aPos = gl.getAttribLocation(pathProgram, "aPos");
    var aLine = gl.getAttribLocation(pathProgram, "aLine");
    var aFeed = gl.getAttribLocation(pathProgram, "aFeed");
    gl.enableVertexAttribArray(aPos);
    gl.vertexAttribPointer(aPos, 3, gl.FLOAT, false, stride, 0);
    gl.enableVertexAttribArray(aLine);
    gl.vertexAttribPointer(aLine, 1, gl.FLOAT, false, stride, 12);
    gl.enableVertexAttribArray(aFeed);
    gl.vertexAttribPointer(aFeed, 1, gl.FLOAT, false, stride, 16);
    gl.uniformMatrix4fv(gl.getUniformLocation(pathProgram, "uMVP"), false, mvp);
    gl.uniform1f(gl.getUniformLocation(pathProgram, "uPlayedLine"), playedLine);
    gl.uniform3f(gl.getUniformLocation(pathProgram, "uCutColor"), 0.247, 0.725, 0.314);
    gl.uniform3f(gl.getUniformLocation(pathProgram, "uRapidColor"), 0.89, 0.702, 0.255);
    gl.uniform3f(gl.getUniformLocation(pathProgram, "uDoneColor"), 0.302, 0.639, 1.0);
    gl.drawArrays(gl.LINE_STRIP, 0, vertexCount);

    if (marker) {
      gl.useProgram(markerProgram);
      gl.bindBuffer(gl.ARRAY_BUFFER, markerBuf);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(marker), gl.DYNAMIC_DRAW);
      var mPos = gl.getAttribLocation(markerProgram, "aPos");
      gl.enableVertexAttribArray(mPos);
      gl.vertexAttribPointer(mPos, 3, gl.FLOAT, false, 0, 0);
      gl.uniformMatrix4fv(gl.getUniformLocation(markerProgram, "uMVP"), false, mvp);
      gl.uniform3f(gl.getUniformLocation(markerProgram, "uColor"), 1.0, 0.302, 0.302);
      gl.drawArrays(gl.POINTS, 0, 1);
    }

    requestAnimationFrame(draw);
  }
  requestAnimationFrame(draw);

  // -- orbit (drag to rotate, wheel/pinch to zoom) --
  var pointers = new Map();
  canvas.addEventListener("pointerdown", function (e) {
    canvas.setPointerCapture(e.pointerId);
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
  });
  canvas.addEventListener("pointerup", function (e) { pointers.delete(e.pointerId); });
  canvas.addEventListener("pointercancel", function (e) { pointers.delete(e.pointerId); });
  canvas.addEventListener("pointermove", function (e) {
    if (!pointers.has(e.pointerId)) return;
    var prev = pointers.get(e.pointerId);
    var curr = { x: e.clientX, y: e.clientY };
    if (pointers.size === 1) {
      yaw += (curr.x - prev.x) * 0.008;
      pitch += (curr.y - prev.y) * 0.008;
      pitch = Math.max(-1.5, Math.min(1.5, pitch));
    } else if (pointers.size === 2) {
      var others = [];
      pointers.forEach(function (v, k) { others.push(k === e.pointerId ? curr : v); });
      var before = 0, after = 0;
      var ids = Array.from(pointers.keys());
      var a = ids[0] === e.pointerId ? curr : pointers.get(ids[0]);
      var b = ids[1] === e.pointerId ? curr : pointers.get(ids[1]);
      var aP = ids[0] === e.pointerId ? prev : pointers.get(ids[0]);
      var bP = ids[1] === e.pointerId ? prev : pointers.get(ids[1]);
      before = Math.hypot(aP.x - bP.x, aP.y - bP.y);
      after = Math.hypot(a.x - b.x, a.y - b.y);
      if (before > 0) distance *= before / after;
      distance = Math.max(minDistance, Math.min(radius * 20, distance));
    }
    pointers.set(e.pointerId, curr);
  });
  canvas.addEventListener(
    "wheel",
    function (e) {
      e.preventDefault();
      distance *= e.deltaY > 0 ? 1.1 : 0.9;
      distance = Math.max(minDistance, Math.min(radius * 20, distance));
    },
    { passive: false }
  );

  return { setBounds: setBounds, setPath: setPath, setPlayedLine: setPlayedLine, setMarker: setMarker };
})();

var lastToolpathRevision = null;
function maybeLoadToolpath(revision) {
  if (!revision || revision === lastToolpathRevision) return;
  lastToolpathRevision = revision;
  fetch("toolpath.json", { cache: "no-store" })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (!data.bounds || !data.points || !data.points.length) return;
      Viewer.setBounds(data.bounds);
      Viewer.setPath(data.points, data.line, data.feed);
    })
    .catch(function () {});
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

  maybeLoadToolpath(data.toolpath_revision);
  Viewer.setPlayedLine(typeof data.played_line === "number" ? data.played_line : -1);
  if (data.connected && (data.x || data.y || data.z)) {
    Viewer.setMarker(data.x || 0, data.y || 0, data.z || 0);
  }
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
setInterval(poll, 1000);
</script>
</body>
</html>
"""


class _Handler(BaseHTTPRequestHandler):
    # Set per-server via a subclass in StatusServer.start().
    status_provider: Callable[[], dict] = None
    toolpath_provider: Callable[[], dict] | None = None

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
        if self.path in ("/toolpath.json", "/toolpath"):
            try:
                payload = self.toolpath_provider() if self.toolpath_provider else {}
            except Exception:
                logger.exception("Toolpath provider failed")
                payload = {"error": "unavailable"}
            self._write(200, json.dumps(payload).encode("utf-8"), "application/json")
            return
        self._write(404, b"Not found", "text/plain; charset=utf-8")


class StatusServer:
    """Serves a read-only job-progress page/JSON on the local network."""

    def __init__(
        self,
        status_provider: Callable[[], dict],
        toolpath_provider: Callable[[], dict] | None = None,
        host: str = "0.0.0.0",
        port: int = 8765,
    ):
        self._status_provider = status_provider
        self._toolpath_provider = toolpath_provider
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
        handler = type(
            "_BoundHandler",
            (_Handler,),
            {
                "status_provider": staticmethod(self._status_provider),
                "toolpath_provider": staticmethod(self._toolpath_provider) if self._toolpath_provider else None,
            },
        )
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
