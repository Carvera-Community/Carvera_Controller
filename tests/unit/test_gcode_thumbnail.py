"""Tests for G-code embedded preview extraction and disk cache."""

from __future__ import annotations

import base64
import io
from pathlib import Path

from PIL import Image

import carveracontroller.ui.file_browser.thumbnail as thumbs
from carveracontroller.ui.file_browser.thumbnail import (
    GcodeThumbnailCache,
    extract_thumbnail_png,
    local_cache_key,
    machine_cache_key,
)


def _png_bytes(width: int, height: int, color=(255, 0, 0)) -> bytes:
    image = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _gcode_with_thumbnail(png: bytes, *, crlf: bool = False) -> bytes:
    encoded = base64.b64encode(png).decode("ascii")
    nl = "\r\n" if crlf else "\n"
    lines = ["G0 X0 Y0", "M02", ";(thumbnail_image_begin)"]
    for start in range(0, len(encoded), 76):
        lines.append(";" + encoded[start : start + 76])
    lines.append(";(thumbnail_image_end)")
    return nl.join(lines).encode("ascii") + nl.encode("ascii")


def test_extract_roundtrip_crlf(tmp_path: Path):
    png = _png_bytes(1, 1)
    path = tmp_path / "job.nc"
    path.write_bytes(_gcode_with_thumbnail(png, crlf=True))
    extracted = extract_thumbnail_png(path)
    assert extracted is not None
    with Image.open(io.BytesIO(extracted)) as image:
        assert image.size == (1, 1)
        assert image.getpixel((0, 0))[:3] == (255, 0, 0)


def test_extract_downscales_long_side(tmp_path: Path):
    png = _png_bytes(300, 100, color=(0, 128, 255))
    path = tmp_path / "wide.gcode"
    path.write_bytes(_gcode_with_thumbnail(png))
    extracted = extract_thumbnail_png(path, max_side=256)
    assert extracted is not None
    with Image.open(io.BytesIO(extracted)) as image:
        assert image.size == (256, 85)


def test_extract_missing_end_marker(tmp_path: Path):
    path = tmp_path / "plain.nc"
    path.write_bytes(b"G0 X0\nM02\n")
    assert extract_thumbnail_png(path) is None


def test_extract_begin_missing_from_tail(tmp_path: Path, monkeypatch):
    png = _png_bytes(1, 1)
    path = tmp_path / "split.nc"
    path.write_bytes(_gcode_with_thumbnail(png))
    monkeypatch.setattr(thumbs, "TAIL_READ_BYTES", len(thumbs.THUMB_END) + 2)
    assert extract_thumbnail_png(path) is None


def test_extract_bad_base64(tmp_path: Path):
    path = tmp_path / "bad.nc"
    path.write_bytes(b"M02\n;(thumbnail_image_begin)\n;@@@@\n;(thumbnail_image_end)\n")
    assert extract_thumbnail_png(path) is None


def test_extract_non_png_payload(tmp_path: Path):
    payload = base64.b64encode(b"not-a-png").decode("ascii")
    path = tmp_path / "nopng.nc"
    path.write_text(f"M02\n;(thumbnail_image_begin)\n;{payload}\n;(thumbnail_image_end)\n", encoding="ascii")
    assert extract_thumbnail_png(path) is None


def test_extract_skips_non_gcode(tmp_path: Path):
    path = tmp_path / "notes.txt"
    path.write_bytes(_gcode_with_thumbnail(_png_bytes(1, 1)))
    assert extract_thumbnail_png(path) is None


def test_cache_hit_miss_negative_and_lru(tmp_path: Path):
    png = _png_bytes(2, 2, color=(0, 255, 0))
    gcode = tmp_path / "cached.nc"
    gcode.write_bytes(_gcode_with_thumbnail(png))
    cache = GcodeThumbnailCache(tmp_path / "cache", max_images=2)
    key = local_cache_key(str(gcode))
    size = gcode.stat().st_size
    mtime = gcode.stat().st_mtime

    assert cache.lookup(key, size, mtime).hit is False
    stored = cache.ingest_file(str(gcode), key, size, mtime)
    assert stored is not None
    hit = cache.lookup(key, size, mtime)
    assert hit.hit is True
    assert hit.image_path == stored
    assert Path(stored).is_file()

    stale = cache.lookup(key, size + 1, mtime)
    assert stale.hit is False

    empty = tmp_path / "empty.nc"
    empty.write_text("G0 X0\nM02\n", encoding="ascii")
    empty_key = local_cache_key(str(empty))
    empty_stat = empty.stat()
    assert cache.ingest_file(str(empty), empty_key, empty_stat.st_size, empty_stat.st_mtime) is None
    negative = cache.lookup(empty_key, empty_stat.st_size, empty_stat.st_mtime)
    assert negative.hit is True
    assert negative.image_path is None

    extra1 = tmp_path / "a.nc"
    extra2 = tmp_path / "b.nc"
    extra1.write_bytes(_gcode_with_thumbnail(_png_bytes(1, 1, (1, 1, 1))))
    extra2.write_bytes(_gcode_with_thumbnail(_png_bytes(1, 1, (2, 2, 2))))
    cache.ingest_file(str(extra1), local_cache_key(str(extra1)), extra1.stat().st_size, extra1.stat().st_mtime)
    cache.ingest_file(str(extra2), local_cache_key(str(extra2)), extra2.stat().st_size, extra2.stat().st_mtime)
    # Original image should be evicted (LRU cap 2); not converted into a negative hit.
    evicted = cache.lookup(key, size, mtime)
    assert evicted.hit is False
    assert not Path(stored).exists()


def test_ingest_skips_quicklz_payload(tmp_path: Path):
    compressed = tmp_path / "job.nc"
    compressed.write_bytes(b"\x00\x00" + b"not-a-thumbnail")
    cache = GcodeThumbnailCache(tmp_path / "cache")
    key = local_cache_key(str(compressed))
    stat = compressed.stat()
    assert cache.ingest_file(str(compressed), key, stat.st_size, stat.st_mtime) is None
    assert cache.lookup(key, stat.st_size, stat.st_mtime).hit is False


def test_machine_cache_key_normalizes_slashes():
    assert machine_cache_key("wifi:1.2.3.4", r"\sd\gcodes\job.nc") == machine_cache_key(
        "wifi:1.2.3.4", "/sd/gcodes/job.nc"
    )
