# Upload API

The Carvera's WiFi accepts one client at a time, and that client is usually the Controller. The
Upload API lets another program hand the Controller a G-code file instead of taking the
connection away. CAM or design tools, scripts and `curl` can all use it. The Controller uploads the
file to `/sd/gcodes` as soon as the machine is Idle, through the same upload path as the file browser.

**The API only uploads.** It never runs, jogs, homes or sends commands to the machine.

## Turning it on

Settings → **Upload API**:

| Setting | Default | |
|---|---|---|
| Enable Upload API | off | |
| Upload API port | 8642 | |
| Allow other computers | off | Listens on all interfaces; requires a token |
| Upload API token | empty | Clients send `Authorization: Bearer <token>` |
| Allowed web origins | empty | Browser pages allowed to call it (CORS); empty means non-browser clients only |

## Endpoints

| | |
|---|---|
| `GET /v1/status` | API version, whether the machine is ready (and why not), queue counts |
| `POST /v1/uploads?name=<file>` | Body: the file. Headers: `Content-Length`, `X-Content-MD5` (hex). → `202` with the job, `Location: /v1/uploads/<id>` |
| `GET /v1/uploads` | Recent jobs, newest first |
| `GET /v1/uploads/<id>` | One job: `queued`, `uploading`, `done`, `failed` or `cancelled`, with a message |
| `DELETE /v1/uploads/<id>` | Cancel a queued job (`409` once it has started) |

Errors are `{"error": "..."}`:
- `400`: bad name, missing MD5, empty file
- `401`: missing or wrong token
- `403`: browser origin not allowed
- `411`: no `Content-Length`
- `413`: too large (64 MB)
- `422`: MD5 mismatch; nothing is queued

File names are plain names: letters, digits, `_ - .`, a G-code extension (`.nc .gcode .cnc .ngc .tap .txt`), no path, and no `.lz`.

```sh
f=job.nc
curl -X POST "http://127.0.0.1:8642/v1/uploads?name=$f" \
  -H "X-Content-MD5: $(md5 -q $f)" --data-binary @$f
# {"id": "96309555b5e8", "state": "queued", "path": "/sd/gcodes/job.nc", ...}
curl http://127.0.0.1:8642/v1/uploads/96309555b5e8
```

## How it decides the machine is ready

The machine is ready when all of these hold:
- the Controller is connected and the machine reports `Idle`
- no job is playing
- no other upload, download or batch transfer is running

That is checked twice: once by the queue, then again on the Kivy main thread just before the upload starts. If the machine became busy in between, the job goes back to `queued`.

## Code

- `api.py`: the queue and the HTTP server. Kivy-free and unit tested (`tests/unit/test_upload_api.py`).
- `bridge.py`: the Controller side. Readiness from `CNC.vars` and the app state, uploads via `Makera.uploadLocalFile(..., remote_dir=, on_finished=, remember_local_dir=False)`, and notices in the log.
