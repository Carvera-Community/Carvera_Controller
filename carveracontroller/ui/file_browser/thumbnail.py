"""Extract and cache preview images embedded at the end of G-code files.

Makera Studio writes a PNG as ``;``-prefixed base64 between
``;(thumbnail_image_begin)`` and ``;(thumbnail_image_end)`` after the program.
This module is Kivy-free.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

logger = logging.getLogger(__name__)

GCODE_EXTENSIONS = {".nc", ".gcode", ".ngc", ".cnc", ".tap", ".gc"}

THUMB_BEGIN = b";(thumbnail_image_begin)"
THUMB_END = b";(thumbnail_image_end)"
PNG_MAGIC = b"\x89PNG"
TAIL_READ_BYTES = 512 * 1024
MAX_SIDE_PX = 256
CACHE_VERSION = 1
CACHE_MAX_IMAGES = 200
INDEX_NAME = "index.json"

_CACHE_LOCK = threading.Lock()
_APP_CACHE: GcodeThumbnailCache | None = None


def is_gcode_path(path: str) -> bool:
    """True when ``path`` has a G-code suffix (not ``.lz``)."""
    return Path(path).suffix.lower() in GCODE_EXTENSIONS


def is_quicklz_file(path: str) -> bool:
    """True when ``path`` still holds a Carvera QuickLZ payload (``\\x00\\x00`` prefix)."""
    try:
        with open(path, "rb") as handle:
            return handle.read(2) == b"\x00\x00"
    except OSError:
        return False


def local_cache_key(path: str) -> str:
    return "local|" + os.path.normpath(os.path.abspath(path))


def machine_cache_key(connection_key: str, remote_path: str) -> str:
    remote = os.path.normpath(remote_path or "").replace("\\", "/")
    return f"machine|{connection_key}|{remote}"


def mtime_token(mtime: Any) -> str:
    """Stable cache token for a listing mtime (raw string or numeric)."""
    if mtime is None:
        return ""
    if isinstance(mtime, str):
        return mtime
    if isinstance(mtime, bool):
        return str(int(mtime))
    if isinstance(mtime, int):
        return str(mtime)
    try:
        return f"{float(mtime):.6f}"
    except (TypeError, ValueError):
        return str(mtime)


def extract_thumbnail_png(path: str | os.PathLike[str], *, max_side: int = MAX_SIDE_PX) -> bytes | None:
    """Return a downscaled PNG from the G-code tail, or None if none is usable."""
    file_path = os.fspath(path)
    if not is_gcode_path(file_path):
        return None
    try:
        size = os.path.getsize(file_path)
    except OSError:
        return None
    if size <= 0:
        return None
    read_len = min(size, TAIL_READ_BYTES)
    try:
        with open(file_path, "rb") as handle:
            handle.seek(size - read_len)
            tail = handle.read(read_len)
    except OSError:
        logger.debug("Failed to read G-code tail from %s", file_path, exc_info=True)
        return None
    png = _png_from_tail(tail)
    if png is None:
        return None
    return _downscale_png(png, max_side)


def _png_from_tail(tail: bytes) -> bytes | None:
    end_idx = tail.rfind(THUMB_END)
    if end_idx < 0:
        return None
    begin_idx = tail.rfind(THUMB_BEGIN, 0, end_idx)
    if begin_idx < 0:
        return None
    payload = tail[begin_idx + len(THUMB_BEGIN) : end_idx]
    chunks: list[bytes] = []
    for raw_line in payload.splitlines():
        line = raw_line.strip()
        if line.startswith(b";"):
            line = line[1:]
        line = line.strip()
        if line:
            chunks.append(line)
    if not chunks:
        return None
    blob = b"".join(chunks)
    pad = (-len(blob)) % 4
    if pad:
        blob += b"=" * pad
    try:
        decoded = base64.b64decode(blob, validate=False)
    except Exception:
        return None
    if not decoded.startswith(PNG_MAGIC):
        return None
    return decoded


def _downscale_png(data: bytes, max_side: int) -> bytes | None:
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            width, height = image.size
            long_side = max(width, height)
            if max_side > 0 and long_side > max_side:
                scale = max_side / float(long_side)
                image = image.resize(
                    (max(1, round(width * scale)), max(1, round(height * scale))),
                    Image.Resampling.LANCZOS,
                )
            out = io.BytesIO()
            image.save(out, format="PNG", optimize=True)
            return out.getvalue()
    except Exception:
        logger.debug("Failed to decode or downscale embedded PNG", exc_info=True)
        return None


@dataclass(frozen=True)
class ThumbnailLookup:
    """Result of a cache probe.

    ``hit`` is True when size+mtime matched (image or negative). ``image_path``
    is a PNG path when a thumbnail is stored.
    """

    hit: bool
    image_path: str | None = None


class GcodeThumbnailCache:
    """Disk cache of extracted G-code previews, keyed by path + size + mtime."""

    def __init__(self, root: str | os.PathLike[str], *, max_images: int = CACHE_MAX_IMAGES):
        self.root = Path(root)
        self.max_images = max(1, int(max_images))
        self._lock = threading.Lock()
        self.root.mkdir(parents=True, exist_ok=True)
        self._index = self._load_index()

    def lookup(self, key: str, size: int, mtime: Any) -> ThumbnailLookup:
        token = mtime_token(mtime)
        size_i = int(size or 0)
        with self._lock:
            entry = self._index.get("entries", {}).get(key)
            if not isinstance(entry, dict):
                return ThumbnailLookup(hit=False)
            if int(entry.get("size") or 0) != size_i or str(entry.get("mtime") or "") != token:
                return ThumbnailLookup(hit=False)
            image_name = entry.get("image")
            entry["accessed"] = time.time()
            if not image_name:
                self._write_index_unlocked()
                return ThumbnailLookup(hit=True, image_path=None)
            image_path = self.root / str(image_name)
            if not image_path.is_file():
                return ThumbnailLookup(hit=False)
            self._write_index_unlocked()
            return ThumbnailLookup(hit=True, image_path=str(image_path))

    def store(self, key: str, size: int, mtime: Any, png_bytes: bytes | None) -> str | None:
        """Write an image or a negative sentinel. Returns the PNG path if stored."""
        token = mtime_token(mtime)
        size_i = int(size or 0)
        image_name = self._image_name(key)
        image_path = self.root / image_name
        with self._lock:
            entries: dict[str, Any] = self._index.setdefault("entries", {})
            if png_bytes:
                self._write_bytes_atomic(image_path, png_bytes)
                entries[key] = {
                    "size": size_i,
                    "mtime": token,
                    "image": image_name,
                    "accessed": time.time(),
                }
                self._evict_unlocked()
                self._write_index_unlocked()
                return str(image_path)
            if image_path.is_file():
                try:
                    image_path.unlink()
                except OSError:
                    pass
            entries[key] = {
                "size": size_i,
                "mtime": token,
                "image": None,
                "accessed": time.time(),
            }
            self._write_index_unlocked()
            return None

    def ingest_file(self, file_path: str, key: str, size: int, mtime: Any) -> str | None:
        if not file_path or not os.path.isfile(file_path):
            return None
        # Machine downloads arrive compressed; do not cache that as "no preview".
        if is_quicklz_file(file_path):
            return None
        png = extract_thumbnail_png(file_path)
        return self.store(key, size, mtime, png)

    def _image_name(self, key: str) -> str:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        return f"{digest}.png"

    def _evict_unlocked(self) -> None:
        entries: dict[str, Any] = self._index.get("entries", {})
        imaged = [(key, meta) for key, meta in entries.items() if isinstance(meta, dict) and meta.get("image")]
        overflow = len(imaged) - self.max_images
        if overflow <= 0:
            return
        imaged.sort(key=lambda item: float(item[1].get("accessed") or 0))
        for key, meta in imaged[:overflow]:
            name = meta.get("image")
            if name:
                path = self.root / str(name)
                try:
                    path.unlink()
                except OSError:
                    pass
            entries.pop(key, None)

    def _load_index(self) -> dict[str, Any]:
        index_path = self.root / INDEX_NAME
        try:
            raw = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"version": CACHE_VERSION, "entries": {}}
        if not isinstance(raw, dict) or raw.get("version") != CACHE_VERSION:
            return {"version": CACHE_VERSION, "entries": {}}
        entries = raw.get("entries")
        if not isinstance(entries, dict):
            raw["entries"] = {}
        return raw

    def _write_index_unlocked(self) -> None:
        index_path = self.root / INDEX_NAME
        payload = json.dumps(self._index, indent=0, sort_keys=True)
        self._write_bytes_atomic(index_path, payload.encode("utf-8"))

    def _write_bytes_atomic(self, path: Path, data: bytes) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)


def thumbnail_cache_for_app(user_data_dir: str | os.PathLike[str] | None = None) -> GcodeThumbnailCache | None:
    """Process-wide cache under the app data dir. Pass a dir in tests."""
    global _APP_CACHE
    if user_data_dir is None:
        if _APP_CACHE is not None:
            return _APP_CACHE
        return None
    root = Path(user_data_dir) / "gcode_previews"
    with _CACHE_LOCK:
        if _APP_CACHE is not None and _APP_CACHE.root == root:
            return _APP_CACHE
        _APP_CACHE = GcodeThumbnailCache(root)
        return _APP_CACHE
